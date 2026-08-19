"""Delete the archive rows the convicted default-path bug minted.

    uv run python -m cairn_api.ops.purge_default_briefs [--apply]

**This is not archive pruning, and the criterion is the argument.** Before
`briefs.is_record`, the endpoint treated every *default* request as a finished
period: `end` defaulted to `now`, `is_complete(now)` was true by `<=`, and each
read archived a "record" of a period that had not finished being lived - 206 of
them accumulated in one workspace. Those rows were never history; they were the
present, mislabelled.

A cleanup command rather than a migration, in one line: this deletes data whose
existence depends on an environment's traffic, so it belongs to an auditable,
re-runnable, per-environment action - not to schema history that replays a
one-time deletion in every database forever.

The criterion, and why it cannot match a caller-named period:

- ``period_end - period_start`` is **exactly** ``DEFAULT_BRIEF_DAYS`` days, to
  the microsecond. Only the default path derives both boundaries from a single
  ``now()`` capture; a caller supplies its own values.
- ``period_end`` carries **non-zero microseconds**. A named boundary is a human
  or client choice - midnight, the hour, an ISO date - and the product's own
  web client (`apps/web/src/brief/adapter.ts`) sends no boundaries at all, so
  it cannot have named one of any shape.
- The row was **created within one hour of its own period ending**. The junk
  path captured ``end = now`` and stored seconds later; a legitimately archived
  period ended first and was asked about afterwards.

Each condition alone is circumstantial; a row matching all three simultaneously
would require a caller to have computed ``until`` as its own clock's microsecond
"now", subtracted exactly the server's default span, and asked within the hour -
which is a description of the default path, not of a person naming a week.

Idempotent: rows matching the criterion cannot be minted any more (`is_record`
requires a caller-named, finished boundary), so a second run deletes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

from sqlalchemy import ColumnElement, extract, func, select

from cairn_api.db.brief_models import Brief
from cairn_api.db.session import platform_session

#: Mirrors the endpoint's default span. Asserted equal in the test suite so the
#: criterion cannot drift from the path it describes.
DEFAULT_BRIEF_DAYS = 7

#: How soon after its own period end a junk row was written. Generous: the
#: generation between `end = now` and the INSERT took seconds to a couple of
#: minutes; an hour bounds every observed case with margin.
CREATED_WITHIN = timedelta(hours=1)


def _junk_conditions() -> list[ColumnElement[bool]]:
    """The three conditions, as SQL. See the module docstring for the argument
    that their conjunction cannot describe a caller-named finished period."""
    return [
        Brief.period_end - Brief.period_start == timedelta(days=DEFAULT_BRIEF_DAYS),
        extract("microseconds", Brief.period_end) % 1_000_000 != 0,
        Brief.created_at - Brief.period_end < CREATED_WITHIN,
        Brief.created_at > Brief.period_end,
    ]


async def run(*, apply: bool) -> int:
    async with platform_session() as db:
        per_tenant = list(
            await db.execute(
                select(Brief.tenant_id, func.count())
                .where(*_junk_conditions())
                .group_by(Brief.tenant_id)
            )
        )
        total = sum(count for _, count in per_tenant)

        print(f"Rows matching the default-path shape: {total}")
        for tenant_id, count in per_tenant:
            print(f"  workspace {tenant_id}: {count}")

        if not apply:
            print("Dry run. Re-run with --apply to delete.")
            return 0
        if total == 0:
            print("Nothing to delete.")
            return 0

        from sqlalchemy import delete as sql_delete

        await db.execute(sql_delete(Brief).where(*_junk_conditions()))
        await db.commit()
        print(f"Deleted {total} row(s). Legitimately archived periods were untouched.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete; default is a dry run.")
    return asyncio.run(run(apply=parser.parse_args().apply))


if __name__ == "__main__":
    sys.exit(main())
