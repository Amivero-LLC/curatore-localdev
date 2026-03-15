"""Core scenario runner — orchestrates beats, narration, transport, and assessment."""

import time

import yaml

from config import SCENARIOS_DIR
from narrator import Narrator
from reporter import Reporter
from transports.base import BaseTransport


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
    verbose: bool = False,
    dry_run: bool = False,
) -> dict:
    """Execute a full scenario — iterate beats, narrate, send, assess.

    Returns summary dict with results.
    """
    scenario_name = scenario["name"]
    beats = scenario["conversation_beats"]
    max_turns = scenario.get("max_turns", 10)
    acceptance_criteria = scenario.get("acceptance_criteria", [])

    reporter.start_scenario(scenario, persona)
    transport.reset()

    results = []
    previous_response = None
    total_start = time.time()

    for i, beat in enumerate(beats):
        if i >= max_turns:
            break

        turn_start = time.time()

        # Step 1: Narrator generates user message
        user_message = narrator.generate_user_message(beat, previous_response)

        if verbose:
            _print_turn_header(i + 1, beat["intent"])
            _print_user(persona["name"], user_message)

        if dry_run:
            reporter.add_turn(
                turn=i + 1,
                beat=beat,
                user_message=user_message,
                assistant_response="[DRY RUN — not sent]",
                reaction="[DRY RUN]",
                assessment={"met": None, "reason": "Dry run"},
                duration=0,
                usage=None,
                tool_calls=None,
            )
            results.append({"turn": i + 1, "dry_run": True})
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

        turn_duration = time.time() - turn_start

        if verbose:
            _print_assistant(assistant_content)
            if tool_calls:
                _print_tool_calls(tool_calls)

        # Step 3: Narrator reacts
        reaction = narrator.generate_reaction(
            beat, user_message, assistant_content
        )

        if verbose:
            _print_reaction(persona["name"], reaction)

        # Step 4: Assess beat
        assessment = narrator.assess_beat(beat, assistant_content)

        if verbose:
            status = "MET" if assessment["met"] else "NOT MET"
            _print_assessment(status, assessment["reason"])

        reporter.add_turn(
            turn=i + 1,
            beat=beat,
            user_message=user_message,
            assistant_response=assistant_content,
            reaction=reaction,
            assessment=assessment,
            duration=turn_duration,
            usage=usage,
            tool_calls=tool_calls,
        )

        previous_response = assistant_content
        results.append({
            "turn": i + 1,
            "beat_met": assessment["met"],
            "duration": turn_duration,
        })

    total_duration = time.time() - total_start

    summary = {
        "scenario": scenario_name,
        "persona": persona["name"],
        "turns": len(results),
        "beats_met": sum(1 for r in results if r.get("beat_met")),
        "beats_not_met": sum(
            1 for r in results if r.get("beat_met") is False
        ),
        "acceptance_criteria": acceptance_criteria,
        "total_duration": total_duration,
        "dry_run": dry_run,
    }

    reporter.finalize(summary)
    return summary


def _print_turn_header(turn: int, intent: str) -> None:
    from rich.console import Console
    console = Console()
    console.rule(f"[bold]Turn {turn}: {intent}[/bold]")


def _print_user(name: str, message: str) -> None:
    from rich.console import Console
    console = Console()
    console.print(f"\n[bold blue]{name}:[/bold blue] {message}\n")


def _print_assistant(response: str) -> None:
    from rich.console import Console
    from rich.panel import Panel
    console = Console()
    console.print(Panel(response[:2000], title="AmiChat", border_style="green"))


def _print_tool_calls(tool_calls: list[dict]) -> None:
    from rich.console import Console
    console = Console()
    for tc in tool_calls:
        console.print(
            f"  [dim]Tool: {tc['tool']}({tc.get('arguments', {})}) "
            f"[round {tc.get('round', '?')}][/dim]"
        )


def _print_reaction(name: str, reaction: str) -> None:
    from rich.console import Console
    console = Console()
    console.print(f"[dim italic]{name} thinks: {reaction}[/dim italic]\n")


def _print_assessment(status: str, reason: str) -> None:
    from rich.console import Console
    console = Console()
    color = "green" if status == "MET" else "red"
    console.print(f"[bold {color}]Beat: {status}[/bold {color}] — {reason}\n")
