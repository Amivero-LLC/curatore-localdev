"""Report generator — markdown + JSON output."""

import json
from datetime import datetime, timezone
from pathlib import Path

from config import RESULTS_DIR


class Reporter:
    def __init__(self, transport_name: str):
        self.transport_name = transport_name
        self.scenario: dict = {}
        self.persona: dict = {}
        self.turns: list[dict] = []
        self.start_time: datetime | None = None
        self.output_dir: Path | None = None

    def start_scenario(self, scenario: dict, persona: dict) -> None:
        self.scenario = scenario
        self.persona = persona
        self.turns = []
        self.start_time = datetime.now(timezone.utc)

        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        slug = scenario["name"].lower().replace(" ", "_")
        self.output_dir = RESULTS_DIR / f"{timestamp}_{slug}"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def add_turn(
        self,
        turn: int,
        user_message: str,
        assistant_response: str,
        reaction: str,
        duration: float,
        usage: dict | None,
        tool_calls: list[dict] | None = None,
    ) -> None:
        self.turns.append({
            "turn": turn,
            "user_message": user_message,
            "assistant_response": assistant_response,
            "reaction": reaction,
            "duration": duration,
            "usage": usage,
            "tool_calls": tool_calls or [],
        })

    def finalize(self, summary: dict) -> None:
        """Write report.md, timeline.json, and raw_responses.json."""
        if not self.output_dir:
            return

        self._write_markdown(summary)
        self._write_timeline(summary)
        self._write_raw_responses()

    def _write_markdown(self, summary: dict) -> None:
        s = self.scenario
        p = self.persona
        lines = [
            f"# Simulation Report: {s['name']}",
            f"- **Persona:** {p['name']} ({p['title']}, {p['team']} Team)",
            f"- **Date:** {self.start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"- **Transport:** {self.transport_name}",
            f"- **Duration:** {summary['total_duration']:.1f}s ({len(self.turns)} turns)",
            "",
        ]

        if s.get("description"):
            lines.extend(["## Scenario", "", s["description"].strip(), ""])

        if s.get("goal"):
            lines.extend(["## Goal", "", s["goal"].strip(), ""])

        if summary.get("dry_run"):
            lines.append("> **DRY RUN** — messages were generated but not sent.\n")

        lines.append("## Conversation\n")

        for t in self.turns:
            lines.extend([
                f"### Turn {t['turn']}",
                f"**{p['name']} typed:** \"{t['user_message']}\"",
                "",
                f"**AmiChat responded:** {t['assistant_response'][:3000]}",
                "",
            ])

            if t["tool_calls"]:
                lines.append("**Tools used:**")
                for tc in t["tool_calls"]:
                    lines.append(f"- `{tc['tool']}` (round {tc.get('round', '?')})")
                lines.append("")

            lines.extend([
                f"**{p['name']}'s reaction:** {t['reaction']}",
                "",
                f"*Duration: {t['duration']:.1f}s*",
                "",
                "---",
                "",
            ])

        # Summary table
        lines.extend([
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Turns | {len(self.turns)} / {s.get('max_turns', 6)} max |",
            f"| Total duration | {summary['total_duration']:.1f}s |",
            f"| Verified claims | {summary.get('verified_count', 0)} |",
            f"| Failed checks | {summary.get('failed_count', 0)} |",
            f"| Errors | {summary.get('error_count', 0)} |",
            "",
        ])

        # Verification results
        verification = summary.get("verification", [])
        if verification:
            lines.extend(["## Verification Results\n"])
            for v in verification:
                icon = {
                    "verified": "PASS",
                    "not_found": "FAIL",
                    "mismatch": "WARN",
                    "error": "ERROR",
                }.get(v["result"], "?")
                lines.append(
                    f"- **{icon}** [{v['diagnostic'].upper()}] "
                    f"{v['claim']} — {v['detail']}"
                )
            lines.append("")

        # Acceptance criteria (from scenario definition)
        acceptance = s.get("acceptance_criteria", [])
        if acceptance:
            lines.extend(["## Acceptance Criteria\n"])
            for ac in acceptance:
                lines.append(
                    f"- **[{ac['diagnostic'].upper()}]** {ac['criterion']}"
                )
                if ac.get("detail"):
                    lines.append(f"  - {ac['detail']}")
            lines.append("")

        report_path = self.output_dir / "report.md"
        report_path.write_text("\n".join(lines))

    def _write_timeline(self, summary: dict) -> None:
        timeline = {
            "scenario": self.scenario["name"],
            "persona": self.persona["name"],
            "start_time": self.start_time.isoformat(),
            "transport": self.transport_name,
            "summary": summary,
            "turns": [
                {
                    "turn": t["turn"],
                    "duration": t["duration"],
                    "usage": t["usage"],
                    "tool_calls": [
                        {"tool": tc["tool"], "round": tc.get("round")}
                        for tc in t["tool_calls"]
                    ],
                }
                for t in self.turns
            ],
            "verification": summary.get("verification", []),
        }

        path = self.output_dir / "timeline.json"
        path.write_text(json.dumps(timeline, indent=2, default=str))

    def _write_raw_responses(self) -> None:
        raw = [
            {
                "turn": t["turn"],
                "user_message": t["user_message"],
                "assistant_response": t["assistant_response"],
                "usage": t["usage"],
                "tool_calls": t["tool_calls"],
            }
            for t in self.turns
        ]

        path = self.output_dir / "raw_responses.json"
        path.write_text(json.dumps(raw, indent=2, default=str))
