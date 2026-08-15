"""Export production corrections as golden cases, for a human to review.

    uv run python -m cairn_api.evaluation.export_corrections --tenant <uuid>

Prints the cases as dataset JSON and the skipped corrections with their
reasons. Writing the file is left to the person running it —
`> dataset/corrections.json` is one keystroke, and the keystroke is the
review.

A command, not a scheduled job: cases need human review (preference vs.
defect), the dataset gates releases, and corrections contain customer
content — moving them into a committed file is a disclosure decision (md/10
§5), not something a cron job does at 3am.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from cairn_api.db.session import dispose_engines
from cairn_api.db.tenancy import tenant_session
from cairn_api.evaluation.corrections import harvest


async def run(tenant_id: uuid.UUID, *, version: str) -> int:
    async with tenant_session(tenant_id) as session:
        found = await harvest(session, tenant_id=tenant_id)

    if found.skipped:
        # To stderr, so JSON on stdout stays pipeable.
        print(f"Skipped {len(found.skipped)} correction(s):", file=sys.stderr)
        for item in found.skipped:
            print(f"  {item.fact_id}  {item.reason.value}", file=sys.stderr)

    payload = {
        "version": version,
        "cases": [case.model_dump(mode="json", exclude_none=True) for case in found.cases],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    print(
        f"\n{len(found.cases)} case(s) ready for review. Read before committing.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, help="Workspace to export corrections from.")
    parser.add_argument(
        "--version",
        default="0.2.0-corrections",
        help="Dataset version stamped into the output.",
    )
    args = parser.parse_args(argv)

    try:
        tenant_id = uuid.UUID(args.tenant)
    except ValueError:
        print(f"Not a workspace id: {args.tenant}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(_main(tenant_id, args.version))
    finally:
        pass


async def _main(tenant_id: uuid.UUID, version: str) -> int:
    try:
        return await run(tenant_id, version=version)
    finally:
        # Engines are process-wide; leaving them open exits with a spurious warning.
        await dispose_engines()


if __name__ == "__main__":
    sys.exit(main())
