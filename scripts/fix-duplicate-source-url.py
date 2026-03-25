import asyncio, json
from app.core.shared.database_service import database_service
from sqlalchemy import text

def walk_steps(steps):
    for step in steps:
        yield step
        branches = step.get('branches') or {}
        for branch_steps in branches.values():
            if isinstance(branch_steps, list):
                yield from walk_steps(branch_steps)

async def main():
    async with database_service.get_session() as session:
        result = await session.execute(
            text("SELECT id, definition FROM procedures WHERE slug = 'daily-opportunity-intelligence-report'")
        )
        row = result.fetchone()
        proc_id, definition = row
        if isinstance(definition, str):
            definition = json.loads(definition)

        changes = []
        for step in walk_steps(definition.get('steps', [])):
            params = step.get('params', {})
            for key in list(params.keys()):
                val = params[key]
                if isinstance(val, str):
                    old = ', "source_url": "{{ fc.source_url }}"}'
                    new = '}'
                    if old in val and '"source_url": "{{ fc.source_url or' in val:
                        params[key] = val.replace(old, new)
                        changes.append(f'{step["name"]}: removed duplicate source_url')

        if changes:
            await session.execute(
                text("UPDATE procedures SET definition = :definition WHERE id = :id"),
                {"definition": json.dumps(definition), "id": str(proc_id)},
            )
            await session.commit()
            for c in changes:
                print(c)
        else:
            print("No changes needed")

asyncio.run(main())
