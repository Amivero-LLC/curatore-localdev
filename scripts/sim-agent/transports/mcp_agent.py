"""MCP Agent transport — LLM + MCP tool-call loop.

Connects to the LLM via OpenAI-compatible API (LiteLLM) and to the
MCP gateway via the official MCP Python SDK. Handles the full agentic
loop: LLM decides tools → execute via MCP → feed results back → repeat.
"""

import json
import logging

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from transports.base import BaseTransport

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10  # Safety limit to prevent infinite loops


class MCPAgentTransport(BaseTransport):
    """Agentic transport that connects LLM to MCP tools directly."""

    def __init__(
        self,
        llm_base_url: str,
        llm_api_key: str,
        llm_model: str,
        mcp_url: str,
        mcp_api_key: str,
        mcp_user_email: str,
        system_prompt: str = "",
    ):
        self.llm_base_url = llm_base_url.rstrip("/")
        self.llm_api_key = llm_api_key
        self.llm_model = llm_model
        self.mcp_url = mcp_url
        self.mcp_api_key = mcp_api_key
        self.mcp_user_email = mcp_user_email
        self.system_prompt = system_prompt
        self.history: list[dict] = []
        self.http_client = httpx.AsyncClient()

        # Populated on first use
        self._tools_openai: list[dict] = []
        self._mcp_session: ClientSession | None = None
        self._mcp_cm = None  # context managers kept open
        self._mcp_session_cm = None

    async def _ensure_mcp_connected(self) -> None:
        """Connect to MCP gateway and discover tools (lazy init)."""
        if self._mcp_session is not None:
            return

        headers = {
            "Authorization": f"Bearer {self.mcp_api_key}",
            "X-OpenWebUI-User-Email": self.mcp_user_email,
        }
        self._mcp_cm = streamablehttp_client(self.mcp_url, headers=headers)
        read, write, _ = await self._mcp_cm.__aenter__()

        self._mcp_session_cm = ClientSession(read, write)
        self._mcp_session = await self._mcp_session_cm.__aenter__()
        await self._mcp_session.initialize()

        # Discover tools and convert to OpenAI format
        tools_result = await self._mcp_session.list_tools()
        self._tools_openai = []
        for tool in tools_result.tools:
            self._tools_openai.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                },
            })
        logger.info("MCP connected: %d tools available", len(self._tools_openai))

    async def _call_llm(self, messages: list[dict]) -> dict:
        """Call LLM via OpenAI-compatible API."""
        payload = {
            "model": self.llm_model,
            "messages": messages,
            "max_tokens": 4096,
        }
        if self._tools_openai:
            payload["tools"] = self._tools_openai

        response = await self.http_client.post(
            f"{self.llm_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        return response.json()

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        """Execute a tool via MCP and return the text result."""
        try:
            result = await self._mcp_session.call_tool(name, arguments)
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts)
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e)
            return f"Error executing {name}: {e}"

    async def send_message(self, message: str) -> dict:
        await self._ensure_mcp_connected()

        self.history.append({"role": "user", "content": message})

        # Build messages with system prompt
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.history)

        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        tool_calls_log = []

        # Agentic loop
        for round_num in range(MAX_TOOL_ROUNDS):
            result = await self._call_llm(messages)

            # Accumulate usage
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)

            choice = result["choices"][0]
            msg = choice["message"]
            finish_reason = choice.get("finish_reason", "")

            # If no tool calls, we're done
            if finish_reason != "tool_calls" and not msg.get("tool_calls"):
                content = msg.get("content", "")
                self.history.append({"role": "assistant", "content": content})
                return {
                    "content": content,
                    "model": result.get("model"),
                    "usage": total_usage,
                    "tool_calls": tool_calls_log,
                    "raw": None,
                }

            # Execute tool calls
            messages.append(msg)  # Add assistant message with tool_calls

            for tc in msg.get("tool_calls", []):
                fn = tc["function"]
                tool_name = fn["name"]
                try:
                    tool_args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                except json.JSONDecodeError:
                    tool_args = {}

                logger.info("Tool call [round %d]: %s(%s)", round_num + 1, tool_name, json.dumps(tool_args)[:200])
                tool_result = await self._execute_tool(tool_name, tool_args)

                tool_calls_log.append({
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result_preview": tool_result[:500],
                    "round": round_num + 1,
                })

                # Add tool result to conversation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result,
                })

        # Safety: hit max rounds
        logger.warning("Hit max tool rounds (%d)", MAX_TOOL_ROUNDS)
        content = msg.get("content", "[Max tool rounds reached]")
        self.history.append({"role": "assistant", "content": content})
        return {
            "content": content,
            "model": result.get("model"),
            "usage": total_usage,
            "tool_calls": tool_calls_log,
            "raw": None,
        }

    def reset(self) -> None:
        """Start fresh conversation (new task)."""
        self.history = []

    async def close(self) -> None:
        await self.http_client.aclose()
        if self._mcp_session_cm:
            await self._mcp_session_cm.__aexit__(None, None, None)
        if self._mcp_cm:
            await self._mcp_cm.__aexit__(None, None, None)
