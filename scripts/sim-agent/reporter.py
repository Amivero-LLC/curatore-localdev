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
        beat: dict,
        user_message: str,
        assistant_response: str,
        reaction: str,
        assessment: dict,
        duration: float,
        usage: dict | None,
        tool_calls: list[dict] | None = None,
    ) -> None:
        self.turns.append({
            "turn": turn,
            "beat": beat,
            "user_message": user_message,
            "assistant_response": assistant_response,
            "reaction": reaction,
            "assessment": assessment,
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

        if summary.get("dry_run"):
            lines.append("> **DRY RUN** — messages were generated but not sent.\n")

        lines.append("## Conversation\n")

        for t in self.turns:
            beat = t["beat"]
            status = "MET" if t["assessment"]["met"] else "NOT MET"
            if t["assessment"]["met"] is None:
                status = "N/A"

            lines.extend([
                f"### Turn {t['turn']}: {beat['intent']}",
                f"**{p['name']} typed:** \"{t['user_message']}\"",
                "",
                f"**AmiChat responded:** {t['assistant_response'][:2000]}",
                "",
            ])

            # Tool calls
            if t["tool_calls"]:
                lines.append("**Tools used:**")
                for tc in t["tool_calls"]:
                    lines.append(f"- `{tc['tool']}` (round {tc.get('round', '?')})")
                lines.append("")

            lines.extend([
                f"**{p['name']}'s reaction:** {t['reaction']}",
                "",
                f"**Beat assessment:** {status} — {t['assessment']['reason']}",
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
            f"| Turns | {len(self.turns)} / {s.get('max_turns', 10)} max |",
            f"| Beats met | {summary['beats_met']} |",
            f"| Beats not met | {summary['beats_not_met']} |",
            f"| Total duration | {summary['total_duration']:.1f}s |",
            "",
        ])

        # Acceptance criteria
        acceptance = summary.get("acceptance_criteria", [])
        if acceptance:
            lines.extend(["## Acceptance Criteria\n"])
            for ac in acceptance:
                lines.append(
                    f"- **[{ac['diagnostic'].upper()}]** {ac['criterion']}"
                )
                if ac.get("detail"):
                    lines.append(f"  - {ac['detail']}")
            lines.append("")

        # Friction points
        friction = [
            t for t in self.turns if t["assessment"]["met"] is False
        ]
        if friction:
            lines.append("## Friction Points\n")
            for i, t in enumerate(friction, 1):
                lines.append(
                    f"{i}. Turn {t['turn']}: {t['assessment']['reason']}"
                )
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
                    "intent": t["beat"]["intent"],
                    "duration": t["duration"],
                    "beat_met": t["assessment"]["met"],
                    "assessment": t["assessment"]["reason"],
                    "usage": t["usage"],
                    "tool_calls": [
                        {"tool": tc["tool"], "round": tc.get("round")}
                        for tc in t["tool_calls"]
                    ],
                }
                for t in self.turns
            ],
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
