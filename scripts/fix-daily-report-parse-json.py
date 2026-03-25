"""
Fix parse_json null handling in daily-opportunity-intelligence-report.

The LLM sometimes returns truncated/invalid JSON that parse_json can't parse,
returning None. The templates then crash on |length or iteration of None.

Fix: wrap parse_json results with 'or []' so that None falls back to empty list.

Usage:
  docker exec curatore-backend python -c "$(cat scripts/fix-daily-report-parse-json.py)"
"""

import asyncio
import json
import re
import sys


def walk_steps(steps):
    for step in steps:
        yield step
        branches = step.get("branches") or {}
        for branch_steps in branches.values():
            if isinstance(branch_steps, list):
                yield from walk_steps(branch_steps)


def fix_parse_json_null(s):
    """Wrap parse_json results with 'or []' to handle None returns."""
    # Fix: X | parse_json | length  ->  (X | parse_json or []) | length
    # But only when not already guarded
    s = re.sub(
        r'\{\{\s*([^}]+?\|\s*parse_json)\s*\|\s*length\s*(?:if\s+[^}]+?\s+else\s+\d+\s*)?\}\}',
        r'{{ (\1 or []) | length }}',
        s,
    )
    # Fix: for X in Y | parse_json %}  ->  for X in (Y | parse_json or []) %}
    s = re.sub(
        r'\{%\s*for\s+(\w+)\s+in\s+([^%]+?\|\s*parse_json)\s*%\}',
        r'{% for \1 in (\2 or []) %}',
        s,
    )
    # Also fix the duplicate source_url from the earlier fix script
    s = s.replace(
        '"source_url": "{{ fc.source_url or \'\' }}", "source_url": "{{ fc.source_url }}"',
        '"source_url": "{{ fc.source_url or \'\' }}"',
    )
    return s


async def main():
    from sqlalchemy import text
    from app.core.shared.database_service import database_service

    slug = "daily-opportunity-intelligence-report"

    async with database_service.get_session() as session:
        result = await session.execute(
            text("SELECT id, name, definition FROM procedures WHERE slug = :slug"),
            {"slug": slug},
        )
        row = result.fetchone()
        if not row:
            print(f"ERROR: Procedure '{slug}' not found.")
            sys.exit(1)

        proc_id, proc_name, definition = row
        print(f"Found procedure: {proc_name} (id={proc_id})")

        if isinstance(definition, str):
            definition = json.loads(definition)

        changes_made = []

        for step in walk_steps(definition.get("steps", [])):
            step_name = step.get("name", "")
            params = step.get("params", {})

            for key in list(params.keys()):
                val = params[key]
                if isinstance(val, str) and "parse_json" in val:
                    updated = fix_parse_json_null(val)
                    if updated != val:
                        params[key] = updated
                        changes_made.append(f"  - Step '{step_name}': fixed parse_json null handling in params.{key}")

        if not changes_made:
            print("No changes needed.")
            return

        await session.execute(
            text("UPDATE procedures SET definition = :definition WHERE id = :id"),
            {"definition": json.dumps(definition), "id": str(proc_id)},
        )
        await session.commit()

        print(f"\nUpdated with {len(changes_made)} changes:")
        for change in changes_made:
            print(change)
        print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
