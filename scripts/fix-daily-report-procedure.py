"""
Fix the 'daily-opportunity-intelligence-report' procedure definition.

Changes:
1. Replace detail_url references with source_url in forecast link templates
2. Add conciseness instructions to reduce report verbosity
3. Reduce max_tokens on verbose steps

Usage from localdev:
  docker exec curatore-backend python -c "$(cat scripts/fix-daily-report-procedure.py)"
"""

import asyncio
import json
import sys


def walk_steps(steps):
    """Recursively yield all step dicts from a nested procedure definition."""
    for step in steps:
        yield step
        branches = step.get("branches") or {}
        for branch_steps in branches.values():
            if isinstance(branch_steps, list):
                yield from walk_steps(branch_steps)


def fix_detail_url_in_string(s):
    """Replace all detail_url patterns with source_url equivalents."""
    return (
        s.replace("{{ fc.detail_url or fc.source_url }}", "{{ fc.source_url or '' }}")
        .replace("{{ item.detail_url or item.source_url }}", "{{ item.source_url or '' }}")
        .replace("{{ detail_url or source_url }}", "{{ source_url or '' }}")
        .replace('"detail_url"', '"source_url"')
        .replace("fc.detail_url", "fc.source_url")
        .replace("item.detail_url", "item.source_url")
    )


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
            print(f"ERROR: Procedure '{slug}' not found in database.")
            sys.exit(1)

        proc_id, proc_name, definition = row
        print(f"Found procedure: {proc_name} (id={proc_id})")

        if isinstance(definition, str):
            definition = json.loads(definition)

        changes_made = []

        for step in walk_steps(definition.get("steps", [])):
            step_name = step.get("name", "")
            params = step.get("params", {})

            # --- Fix 1: Replace detail_url in all string fields within params ---
            for key in list(params.keys()):
                val = params[key]
                if isinstance(val, str) and "detail_url" in val:
                    updated = fix_detail_url_in_string(val)
                    if updated != val:
                        params[key] = updated
                        changes_made.append(f"  - Step '{step_name}': replaced detail_url refs in params.{key}")

            # --- Fix 2: Add conciseness to report compilation step ---
            if step_name == "categorize_and_compile_report":
                prompt = params.get("prompt", "")
                if isinstance(prompt, str) and "Target 4-5 pages" not in prompt:
                    params["prompt"] = prompt + (
                        "\n\nIMPORTANT FORMATTING CONSTRAINT: Be concise. Target 4-5 pages maximum. "
                        "Use bullet points, not paragraphs. "
                        "For low-relevance items, list them in a single summary table "
                        "rather than individual writeups."
                    )
                    changes_made.append(f"  - Step '{step_name}': added conciseness instructions")

                mt = params.get("max_tokens", 0)
                if mt > 3000:
                    params["max_tokens"] = 3000
                    changes_made.append(f"  - Step '{step_name}': reduced max_tokens from {mt} to 3000")

            # --- Fix 3: Add brevity to per-item summary steps ---
            if step_name in ("summarize_notice", "summarize_forecast"):
                prompt = params.get("prompt", "")
                if isinstance(prompt, str) and "under 200 words" not in prompt:
                    params["prompt"] = prompt + (
                        "\n\nKeep your response under 200 words. Use bullet points."
                    )
                    changes_made.append(f"  - Step '{step_name}': added brevity constraint")

                mt = params.get("max_tokens", 0)
                target = 800
                if mt > target:
                    params["max_tokens"] = target
                    changes_made.append(f"  - Step '{step_name}': reduced max_tokens from {mt} to {target}")

        if not changes_made:
            print("No changes needed — procedure definition already up to date.")
            return

        await session.execute(
            text("UPDATE procedures SET definition = :definition WHERE id = :id"),
            {"definition": json.dumps(definition), "id": str(proc_id)},
        )
        await session.commit()

        print(f"\nUpdated procedure '{proc_name}' with {len(changes_made)} changes:")
        for change in changes_made:
            print(change)
        print("\nDone. Re-run the procedure to verify the fixes.")


if __name__ == "__main__":
    asyncio.run(main())
