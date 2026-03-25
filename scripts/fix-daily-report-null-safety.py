"""
Fix null-safety in daily-opportunity-intelligence-report procedure templates.

The report_assembly step fails when steps return None (e.g., 0 SAM notices
after filtering). Jinja2 filters like |length, |compact, |parse_json crash
on NoneType. Fix by adding 'or []' / 'or ""' guards.

Usage:
  docker exec curatore-backend python -c "$(cat scripts/fix-daily-report-null-safety.py)"
"""

import asyncio
import json
import re
import sys


def walk_steps(steps):
    """Recursively yield all step dicts from a nested procedure definition."""
    for step in steps:
        yield step
        branches = step.get("branches") or {}
        for branch_steps in branches.values():
            if isinstance(branch_steps, list):
                yield from walk_steps(branch_steps)


def fix_null_safety(s):
    """Add null guards to Jinja2 template expressions that crash on None."""
    # Fix: steps.X | length  ->  (steps.X or []) | length
    s = re.sub(
        r'\{\{\s*steps\.(\w+)\s*\|\s*length\s*\}\}',
        r'{{ (steps.\1 or []) | length }}',
        s,
    )
    # Fix: steps.X | compact  ->  (steps.X or []) | compact
    s = re.sub(
        r'\{\{\s*steps\.(\w+)\s*\|\s*compact\s*\}\}',
        r'{{ (steps.\1 or []) | compact }}',
        s,
    )
    # Fix: steps.X | parse_json | length  ->  (steps.X or "[]") | parse_json | length
    s = re.sub(
        r'\{\{\s*steps\.(\w+)\s*\|\s*parse_json\s*\|\s*length\s*\}\}',
        r'{{ (steps.\1 or "[]") | parse_json | length }}',
        s,
    )
    # Fix: steps.X | parse_json  (without further chaining)
    # Only when used as items input, not when already guarded
    s = re.sub(
        r'\{\{\s*steps\.(\w+)\s*\|\s*parse_json\s*\}\}',
        r'{{ (steps.\1 or "[]") | parse_json }}',
        s,
    )
    # Fix: for X in steps.Y  ->  for X in (steps.Y or [])
    s = re.sub(
        r'\{%\s*for\s+(\w+)\s+in\s+steps\.(\w+)\s*%\}',
        r'{% for \1 in (steps.\2 or []) %}',
        s,
    )
    # Fix: for X in steps.Y | parse_json  ->  for X in (steps.Y or "[]") | parse_json
    s = re.sub(
        r'\{%\s*for\s+(\w+)\s+in\s+steps\.(\w+)\s*\|\s*parse_json\s*%\}',
        r'{% for \1 in (steps.\2 or "[]") | parse_json %}',
        s,
    )
    # Fix: for X in steps.Y | compact  ->  for X in (steps.Y or []) | compact
    s = re.sub(
        r'\{%\s*for\s+(\w+)\s+in\s+steps\.(\w+)\s*\|\s*compact\s*%\}',
        r'{% for \1 in (steps.\2 or []) | compact %}',
        s,
    )
    # Fix: if steps.X  (already safe, but ensure consistency)
    # These are already null-safe in Jinja2
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
                if isinstance(val, str) and "steps." in val:
                    updated = fix_null_safety(val)
                    if updated != val:
                        params[key] = updated
                        changes_made.append(f"  - Step '{step_name}': added null guards in params.{key}")

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
