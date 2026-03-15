#!/usr/bin/env python3
"""CLI entry point for the BD User Simulation Agent."""

import argparse
import asyncio
import sys

from rich.console import Console

import config
from narrator import Narrator
from persona import list_personas, load_persona
from reporter import Reporter
from task_runner import list_scenarios, load_scenario, run_scenario
from transports.mcp_agent import MCPAgentTransport
from verifier import Verifier

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BD User Simulation Agent — exercises Curatore MCP tools"
    )
    parser.add_argument(
        "--scenario",
        default="all",
        help="Scenario name (or 'all'). Available: " + ", ".join(list_scenarios()),
    )
    parser.add_argument(
        "--persona",
        default=None,
        help="Override persona (default: use scenario's persona). Available: "
        + ", ".join(list_personas()),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate messages without sending them",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print conversation in real-time",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip MCP verification of assistant responses",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios and personas",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()

    if args.list:
        console.print("[bold]Available scenarios:[/bold]")
        for name in list_scenarios():
            s = load_scenario(name)
            console.print(f"  - {name} ({s.get('persona', '?')}): {s['name']}")
        console.print("\n[bold]Available personas:[/bold]")
        for p in list_personas():
            persona = load_persona(p)
            console.print(f"  - {p}: {persona['name']} — {persona['title']}")
        return

    # Validate config
    errors = config.validate(args.dry_run)
    if errors:
        console.print("[red bold]Configuration errors:[/red bold]")
        for e in errors:
            console.print(f"  [red]- {e}[/red]")
        console.print(
            f"\nSet these in [bold]{config._ROOT_ENV}[/bold] "
            f"(see .env.example for reference)"
        )
        sys.exit(1)

    # Create MCP agent transport (LLM + MCP tool loop)
    transport = MCPAgentTransport(
        llm_base_url=config.LLM_BASE_URL,
        llm_api_key=config.LLM_API_KEY,
        llm_model=config.LLM_MODEL,
        mcp_url=config.MCP_URL,
        mcp_api_key=config.MCP_API_KEY,
        mcp_user_email=config.MCP_USER_EMAIL,
    )
    transport_label = f"MCP Agent ({config.LLM_MODEL} + {config.MCP_URL})"
    console.print(f"[bold]Transport:[/bold] {transport_label}")

    if args.dry_run:
        console.print("[yellow]DRY RUN — messages will be generated but not sent[/yellow]")

    # Determine scenarios to run
    if args.scenario == "all":
        scenario_names = list_scenarios()
    else:
        scenario_names = [args.scenario]

    # Run scenarios
    all_summaries = []
    for scenario_name in scenario_names:
        scenario = load_scenario(scenario_name)

        # Load persona: CLI override > scenario's persona field
        persona_key = args.persona or scenario.get("persona", "bd_lead")
        persona = load_persona(persona_key)

        console.print(
            f"\n[bold green]Scenario:[/bold green] {scenario['name']}"
        )
        console.print(
            f"[bold]Persona:[/bold] {persona['name']} — {persona['title']}"
        )

        # Create narrator with this persona
        narrator = Narrator(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            model=config.LLM_NARRATOR_MODEL,
            persona=persona,
        )

        # Create verifier (shares MCP session with transport)
        verifier = None
        if not args.no_verify and not args.dry_run:
            # Ensure transport's MCP session is connected
            await transport._ensure_mcp_connected()
            verifier = Verifier(transport._mcp_session)

        reporter = Reporter(transport_name=transport_label)

        summary = await run_scenario(
            scenario=scenario,
            persona=persona,
            transport=transport,
            narrator=narrator,
            reporter=reporter,
            verifier=verifier,
            verbose=args.verbose,
            dry_run=args.dry_run,
        )

        narrator.close()
        all_summaries.append(summary)

        v = summary.get("verified_count", 0)
        f = summary.get("failed_count", 0)
        e = summary.get("error_count", 0)
        duration = summary["total_duration"]
        console.print(
            f"  {summary['turns']} turns, {duration:.1f}s — "
            f"[green]{v} verified[/green], "
            f"[red]{f} failed[/red], "
            f"[yellow]{e} errors[/yellow]"
        )

        if reporter.output_dir:
            console.print(f"  Report: {reporter.output_dir / 'report.md'}")

    # Cleanup
    await transport.close()

    # Final summary
    if len(all_summaries) > 1:
        console.print("\n[bold]Overall Summary:[/bold]")
        total_v = sum(s.get("verified_count", 0) for s in all_summaries)
        total_f = sum(s.get("failed_count", 0) for s in all_summaries)
        total_e = sum(s.get("error_count", 0) for s in all_summaries)
        total_dur = sum(s["total_duration"] for s in all_summaries)
        console.print(
            f"  {len(all_summaries)} scenarios, {total_dur:.1f}s — "
            f"[green]{total_v} verified[/green], "
            f"[red]{total_f} failed[/red], "
            f"[yellow]{total_e} errors[/yellow]"
        )


if __name__ == "__main__":
    asyncio.run(main())
