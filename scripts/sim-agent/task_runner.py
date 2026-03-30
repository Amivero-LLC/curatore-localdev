"""Core scenario runner — goal-driven conversation with MCP verification."""

import time

import yaml

from config import SCENARIOS_DIR
from narrator import Narrator
from reporter import Reporter
from transports.base import BaseTransport
from verifier import Verifier


def load_scenario(name: str) -> dict:
    """Load a scenario by name (filename without extension)."""
    path = SCENARIOS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def list_scenarios() -> list[str]:
    """Return available scenario names."""
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml"))


async def run_scenario(
    scenario: dict,
    persona: dict,
    transport: BaseTransport,
    narrator: Narrator,
    reporter: Reporter,
    verifier: Verifier | None = None,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict:
    """Execute a scenario — goal-driven conversation with verification.

    Flow:
    1. Narrator generates messages driven by the goal (no scripted beats)
    2. Transport sends to LLM + MCP tools
    3. Narrator decides whether to continue or stop
    4. After conversation, verifier checks claims against MCP data
    """
    scenario_name = scenario["name"]
    goal = scenario["goal"]
    max_turns = scenario.get("max_turns", 6)

    reporter.start_scenario(scenario, persona)
    transport.reset()

    turns = []
    conversation = []  # full message history for narrator context
    all_tool_calls = []  # accumulated for data_quality verification
    total_start = time.time()

    for turn_num in range(1, max_turns + 1):
        turn_start = time.time()

        # Step 1: Narrator generates message from goal + history
        user_message = narrator.generate_message(goal, conversation, turn_num)

        if verbose:
            _print_turn_header(turn_num)
            _print_user(persona["name"], user_message)

        conversation.append({"role": "user", "content": user_message})

        if dry_run:
            reporter.add_turn(
                turn=turn_num,
                user_message=user_message,
                assistant_response="[DRY RUN — not sent]",
                reaction="[DRY RUN]",
                duration=0,
                usage=None,
                tool_calls=None,
            )
            turns.append({"turn": turn_num, "dry_run": True})
            continue

        # Step 2: Send to transport
        try:
            response = await transport.send_message(user_message)
            assistant_content = response["content"]
            usage = response.get("usage")
            tool_calls = response.get("tool_calls")
        except Exception as e:
            assistant_content = f"[ERROR: {e}]"
            usage = None
            tool_calls = None

        if tool_calls:
            all_tool_calls.extend(tool_calls)

        turn_duration = time.time() - turn_start
        conversation.append({"role": "assistant", "content": assistant_content})

        if verbose:
            _print_assistant(assistant_content)
            if tool_calls:
                _print_tool_calls(tool_calls)

        # Step 3: Narrator reacts
        reaction = narrator.generate_reaction(goal, user_message, assistant_content)

        if verbose:
            _print_reaction(persona["name"], reaction)

        reporter.add_turn(
            turn=turn_num,
            user_message=user_message,
            assistant_response=assistant_content,
            reaction=reaction,
            duration=turn_duration,
            usage=usage,
            tool_calls=tool_calls,
        )

        turns.append({
            "turn": turn_num,
            "duration": turn_duration,
        })

        # Step 4: Should the persona keep going?
        if not dry_run and not narrator.should_continue(goal, conversation, turn_num, max_turns):
            if verbose:
                _print_done(persona["name"])
            break

    total_duration = time.time() - total_start

    # Step 5: Verification — independently check claims via MCP
    verification_results = []
    if verifier and not dry_run:
        if verbose:
            _print_verification_header()
        verification_results = await verifier.verify_conversation(
            conversation, tool_calls=all_tool_calls,
        )
        if verbose:
            _print_verification_results(verification_results)

    summary = {
        "scenario": scenario_name,
        "persona": persona["name"],
        "turns": len(turns),
        "total_duration": total_duration,
        "dry_run": dry_run,
        "verification": verification_results,
        "verified_count": sum(1 for v in verification_results if v["result"] == "verified"),
        "failed_count": sum(1 for v in verification_results if v["result"] in ("not_found", "mismatch")),
        "error_count": sum(1 for v in verification_results if v["result"] == "error"),
    }

    reporter.finalize(summary)
    return summary


def _print_turn_header(turn: int) -> None:
    from rich.console import Console
    Console().rule(f"[bold]Turn {turn}[/bold]")


def _print_user(name: str, message: str) -> None:
    from rich.console import Console
    Console().print(f"\n[bold blue]{name}:[/bold blue] {message}\n")


def _print_assistant(response: str) -> None:
    from rich.console import Console
    from rich.panel import Panel
    Console().print(Panel(response[:2000], title="AmiChat", border_style="green"))


def _print_tool_calls(tool_calls: list[dict]) -> None:
    from rich.console import Console
    console = Console()
    for tc in tool_calls:
        console.print(
            f"  [dim]Tool: {tc['tool']}() [round {tc.get('round', '?')}][/dim]"
        )


def _print_reaction(name: str, reaction: str) -> None:
    from rich.console import Console
    Console().print(f"[dim italic]{name} thinks: {reaction}[/dim italic]\n")


def _print_done(name: str) -> None:
    from rich.console import Console
    Console().print(f"[bold yellow]{name} is satisfied — ending conversation.[/bold yellow]\n")


def _print_verification_header() -> None:
    from rich.console import Console
    Console().rule("[bold]Verification[/bold]")


def _print_verification_results(results: list[dict]) -> None:
    from rich.console import Console
    console = Console()
    if not results:
        console.print("  [dim]No verifiable claims found.[/dim]")
        return
    for v in results:
        color = {"verified": "green", "not_found": "red", "mismatch": "yellow", "error": "red"}
        c = color.get(v["result"], "white")
        console.print(
            f"  [{c}]{v['result'].upper()}[/{c}] [{v['diagnostic']}] "
            f"{v['claim']} — {v['detail']}"
        )
