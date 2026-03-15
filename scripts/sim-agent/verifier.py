"""Verifier — independently checks claims in assistant responses via MCP."""

import json
import logging
import re

from mcp.client.session import ClientSession

logger = logging.getLogger(__name__)


class Verifier:
    """Parses assistant responses for verifiable claims and checks them via MCP."""

    def __init__(self, mcp_session: ClientSession):
        self.session = mcp_session

    async def verify_conversation(self, conversation: list[dict]) -> list[dict]:
        """Verify all assistant responses in a conversation.

        Returns a list of verification results, each with:
          - claim: what was claimed
          - check: what we verified
          - result: "verified", "not_found", "mismatch", "error"
          - detail: explanation
          - diagnostic: "mcp", "cwr", "llm", "system_prompt"
        """
        results = []

        for msg in conversation:
            if msg["role"] != "assistant":
                continue

            content = msg["content"]

            # Check referenced asset/item IDs
            results.extend(await self._verify_ids(content))

            # Check Salesforce claims
            results.extend(await self._verify_salesforce_refs(content))

            # Check SAM.gov solicitation numbers
            results.extend(await self._verify_solicitation_numbers(content))

            # Check URLs
            results.extend(self._verify_urls(content))

        return results

    async def _verify_ids(self, content: str) -> list[dict]:
        """Find UUIDs in content and verify they exist via get()."""
        results = []
        # Match UUIDs (common format for asset/item IDs)
        uuids = set(re.findall(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            content, re.IGNORECASE,
        ))

        for uid in list(uuids)[:5]:  # cap at 5 to avoid flooding
            try:
                # Try as solicitation first, then asset
                for item_type in ["solicitation", "asset"]:
                    result = await self.session.call_tool(
                        "get", {"item_type": item_type, "item_id": uid}
                    )
                    text = _extract_text(result)
                    if "error" not in text.lower() and "not found" not in text.lower():
                        results.append({
                            "claim": f"Referenced {item_type} ID {uid[:12]}...",
                            "check": f"get({item_type}, {uid})",
                            "result": "verified",
                            "detail": f"{item_type} exists",
                            "diagnostic": "mcp",
                        })
                        break
                else:
                    results.append({
                        "claim": f"Referenced ID {uid[:12]}...",
                        "check": f"get(solicitation|asset, {uid})",
                        "result": "not_found",
                        "detail": "ID not found as solicitation or asset",
                        "diagnostic": "mcp",
                    })
            except Exception as e:
                results.append({
                    "claim": f"Referenced ID {uid[:12]}...",
                    "check": "get()",
                    "result": "error",
                    "detail": str(e)[:200],
                    "diagnostic": "mcp",
                })

        return results

    async def _verify_salesforce_refs(self, content: str) -> list[dict]:
        """Check if Salesforce opportunity names mentioned actually exist."""
        results = []

        # Look for patterns like "Salesforce opportunity" or "in Salesforce"
        # followed by a name, or quoted opportunity names
        sf_indicators = [
            "salesforce", "pipeline", "CRM", "opportunity record",
            "opportunity_url", "salesforce.com",
        ]
        has_sf_ref = any(ind.lower() in content.lower() for ind in sf_indicators)
        if not has_sf_ref:
            return results

        # If Salesforce is referenced, verify we can actually search it
        try:
            result = await self.session.call_tool(
                "search_salesforce",
                {"query": "*", "entity_types": ["opportunity"], "is_open": True, "limit": 3},
            )
            text = _extract_text(result)
            if "error" in text.lower():
                results.append({
                    "claim": "References Salesforce data",
                    "check": "search_salesforce(query=*, is_open=true)",
                    "result": "error",
                    "detail": f"Salesforce search failed: {text[:200]}",
                    "diagnostic": "mcp",
                })
            elif "0 results" in text.lower() or "no results" in text.lower():
                results.append({
                    "claim": "References Salesforce data",
                    "check": "search_salesforce(query=*, is_open=true)",
                    "result": "mismatch",
                    "detail": "No open Salesforce opportunities found — data may not be synced",
                    "diagnostic": "cwr",
                })
            else:
                results.append({
                    "claim": "References Salesforce data",
                    "check": "search_salesforce(query=*, is_open=true)",
                    "result": "verified",
                    "detail": "Salesforce data accessible and contains opportunities",
                    "diagnostic": "mcp",
                })
        except Exception as e:
            results.append({
                "claim": "References Salesforce data",
                "check": "search_salesforce()",
                "result": "error",
                "detail": str(e)[:200],
                "diagnostic": "mcp",
            })

        return results

    async def _verify_solicitation_numbers(self, content: str) -> list[dict]:
        """Find solicitation numbers and verify they exist."""
        results = []

        # Common solicitation number patterns
        sol_patterns = [
            r'(?:solicitation|sol\.?|notice)\s*(?:#|number|num\.?)?\s*[:=]?\s*([A-Z0-9][\w-]{5,30})',
            r'\b([A-Z]{2,5}\d{2,4}-\d{4,})\b',  # e.g., FY26-0046, W519TC-25-R-0001
            r'\b(7[05]\w{10,15})\b',  # SAM.gov style IDs
        ]

        found_sols = set()
        for pattern in sol_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            found_sols.update(m.strip() for m in matches if len(m) > 5)

        for sol_num in list(found_sols)[:3]:  # cap at 3
            try:
                result = await self.session.call_tool(
                    "search_solicitations",
                    {"keyword": sol_num, "limit": 1},
                )
                text = _extract_text(result)
                if "0 results" in text.lower() or "no results" in text.lower():
                    results.append({
                        "claim": f"Referenced solicitation {sol_num}",
                        "check": f"search_solicitations(keyword={sol_num})",
                        "result": "not_found",
                        "detail": "Solicitation number not found in system",
                        "diagnostic": "cwr",
                    })
                else:
                    results.append({
                        "claim": f"Referenced solicitation {sol_num}",
                        "check": f"search_solicitations(keyword={sol_num})",
                        "result": "verified",
                        "detail": "Solicitation exists in system",
                        "diagnostic": "mcp",
                    })
            except Exception as e:
                results.append({
                    "claim": f"Referenced solicitation {sol_num}",
                    "check": "search_solicitations()",
                    "result": "error",
                    "detail": str(e)[:200],
                    "diagnostic": "mcp",
                })

        return results

    def _verify_urls(self, content: str) -> list[dict]:
        """Check that URLs in responses point to expected external systems."""
        results = []
        urls = re.findall(r'https?://[^\s)\]>"\']+', content)

        if not urls:
            return results

        valid_domains = [
            "sam.gov", "salesforce.com", "force.com",
            "usaspending.gov", "apfs.dhs.gov",
        ]

        external_count = 0
        internal_count = 0
        for url in urls[:10]:
            is_external = any(domain in url.lower() for domain in valid_domains)
            if is_external:
                external_count += 1
            elif "localhost" in url or "127.0.0.1" in url:
                internal_count += 1

        if external_count > 0:
            results.append({
                "claim": f"Provided {external_count} external URL(s)",
                "check": "URL domain validation",
                "result": "verified",
                "detail": f"{external_count} URLs point to known external systems",
                "diagnostic": "mcp",
            })

        if internal_count > 0:
            results.append({
                "claim": f"Provided {internal_count} internal URL(s)",
                "check": "URL domain validation",
                "result": "mismatch",
                "detail": f"{internal_count} URLs point to localhost — not useful for the user",
                "diagnostic": "system_prompt",
            })

        return results


def _extract_text(result) -> str:
    """Extract text content from an MCP tool result."""
    parts = []
    for block in result.content:
        if hasattr(block, "text"):
            parts.append(block.text)
        else:
            parts.append(str(block))
    return "\n".join(parts)
