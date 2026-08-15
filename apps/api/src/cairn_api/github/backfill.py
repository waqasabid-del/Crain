"""The backfill job.

Walks a repository's last-ninety-days history through the same attribution
pipeline live webhooks use. Enqueued at `BULK` priority so a new customer's
import can't queue ahead of an existing customer's live events (md/06 §6B.3).

The cursor is committed only after the page's contents are in the session —
writing it first would silently lose a page on crash. Re-processing a page is
free since ingestion is idempotent by commit SHA.

Exhausting the rate budget is not a failure: the run parks as `THROTTLED`
with a resume time rather than retrying into the reserve live traffic depends on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.backfill_models import (
    BACKFILL_WINDOW_DAYS,
    BackfillRun,
    BackfillState,
)
from cairn_api.github.attribution import attribute
from cairn_api.github.budget import BudgetExhaustedError
from cairn_api.github.client import (
    GitHubApiError,
    SecondaryRateLimitError,
    sleep_for_backoff,
    to_commit_payload,
)

if TYPE_CHECKING:
    from cairn_api.github.client import GitHubGraphQLClient

logger = structlog.get_logger(__name__)

BACKFILL_JOB = "github.backfill"

#: How long a worker holds a run before the lease must be renewed. Long enough
#: for an ordinary page to finish; short enough that a killed worker's run is
#: picked up again within a minute.
LEASE_SECONDS = 300

#: Pages processed before yielding the lease and re-enqueuing, so one run
#: can't occupy a worker slot for its whole life and starve the live stream.
PAGES_PER_LEASE = 20


def _release(run: BackfillRun) -> None:
    """Hand the run back so any worker can take the next batch.

    The lease protects work in flight, not the gaps between batches — holding
    it after yielding would leave the run unclaimable for the rest of the
    lease period.
    """
    run.leased_by = None
    run.leased_until = None


@dataclass(frozen=True, slots=True)
class BackfillProgress:
    """What one batch achieved. Returned so the caller can decide what is next."""

    pages: int
    commits: int
    finished: bool
    throttled_for: float | None = None


def window_start(now: datetime | None = None) -> datetime:
    """The oldest commit date a new run imports."""
    return (now or datetime.now(UTC)) - timedelta(days=BACKFILL_WINDOW_DAYS)


async def create_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    installation_id: int,
    repository: str,
) -> BackfillRun | None:
    """Create a run, or return None if one is already live.

    A partial unique index enforces this too; checking first turns a
    constraint violation into an ordinary answer instead of an exception.
    """
    existing = await session.scalar(
        select(BackfillRun).where(
            BackfillRun.installation_id == installation_id,
            BackfillRun.repository == repository,
            BackfillRun.state.in_(
                [BackfillState.PENDING, BackfillState.RUNNING, BackfillState.THROTTLED]
            ),
        )
    )
    if existing is not None:
        return None

    run = BackfillRun(
        tenant_id=tenant_id,
        installation_id=installation_id,
        repository=repository,
        # Fixed at creation so a multi-day run doesn't widen its window on resume.
        since=window_start(),
    )
    try:
        async with session.begin_nested():
            session.add(run)
            await session.flush()
    except IntegrityError:
        # The unique index is global but the pre-check runs under row-level
        # security, so a conflicting run in an invisible workspace passes the
        # SELECT and fails the INSERT. The savepoint keeps that from aborting
        # the caller's whole transaction.
        await logger.ainfo(
            "backfill.run_already_exists",
            installation_id=installation_id,
            repository=repository,
        )
        return None
    return run


async def claim(session: AsyncSession, run_id: uuid.UUID, *, worker: str) -> BackfillRun | None:
    """Take the lease on a run, or return None if someone else holds it.

    `FOR UPDATE` on the row: without it, two workers could both see an
    expired lease and both claim it.
    """
    run = await session.scalar(
        select(BackfillRun).where(BackfillRun.id == run_id).with_for_update()
    )
    if run is None or not run.is_claimable:
        return None

    now = datetime.now(UTC)
    held_by_someone_else = (
        run.leased_until is not None and run.leased_until > now and run.leased_by != worker
    )
    if held_by_someone_else:
        return None

    run.leased_by = worker
    run.leased_until = now + timedelta(seconds=LEASE_SECONDS)
    run.state = BackfillState.RUNNING
    if run.started_at is None:
        run.started_at = now
    await session.flush()
    return run


async def process_batch(
    session: AsyncSession,
    run: BackfillRun,
    client: GitHubGraphQLClient,
    *,
    max_pages: int = PAGES_PER_LEASE,
) -> BackfillProgress:
    """Fetch and attribute up to `max_pages`, then yield the worker.

    Returns rather than looping to completion so fair scheduling can let live
    events through between batches.
    """
    owner, _, name = run.repository.partition("/")
    if not owner or not name:
        run.state = BackfillState.FAILED
        run.error = f"Malformed repository name: {run.repository!r}"
        _release(run)
        return BackfillProgress(pages=0, commits=0, finished=True)

    since = run.since.isoformat()
    pages = 0
    commits = 0

    while pages < max_pages:
        try:
            page = await client.fetch_commits(
                installation_id=run.installation_id,
                owner=owner,
                name=name,
                since=since,
                after=run.cursor,
            )
        except BudgetExhaustedError as exhausted:
            # Not a failure: park with a resume time rather than retrying into
            # the reserve live traffic depends on.
            run.state = BackfillState.THROTTLED
            run.resume_after = datetime.now(UTC) + timedelta(seconds=exhausted.retry_after_seconds)
            await logger.ainfo(
                "backfill.throttled",
                run_id=str(run.id),
                resume_in_seconds=round(exhausted.retry_after_seconds),
                pages_so_far=run.pages_fetched,
            )
            _release(run)
            return BackfillProgress(
                pages=pages,
                commits=commits,
                finished=False,
                throttled_for=exhausted.retry_after_seconds,
            )
        except SecondaryRateLimitError as secondary:
            # Distinct from budget exhaustion: no reliable reset, and
            # ignoring it is what GitHub escalates against.
            await sleep_for_backoff(secondary.retry_after_seconds)
            continue
        except GitHubApiError as failure:
            run.state = BackfillState.FAILED
            run.error = str(failure)[:1024]
            await logger.aexception("backfill.failed", run_id=str(run.id), exc_info=failure)
            _release(run)
            return BackfillProgress(pages=pages, commits=commits, finished=True)

        if page.commits:
            await attribute(
                session,
                {"commits": [to_commit_payload(node) for node in page.commits]},
                tenant_id=run.tenant_id,
            )

        pages += 1
        commits += len(page.commits)
        run.pages_fetched += 1
        run.commits_imported += len(page.commits)

        # Advances only after the page's contents are in the session; see
        # module docstring.
        run.cursor = page.end_cursor

        if not page.has_next_page:
            run.state = BackfillState.COMPLETED
            run.completed_at = datetime.now(UTC)
            _release(run)
            await logger.ainfo(
                "backfill.completed",
                run_id=str(run.id),
                repository=run.repository,
                commits=run.commits_imported,
                pages=run.pages_fetched,
            )
            return BackfillProgress(pages=pages, commits=commits, finished=True)

    _release(run)
    await logger.ainfo(
        "backfill.batch_complete",
        run_id=str(run.id),
        pages=pages,
        commits=commits,
        total_commits=run.commits_imported,
    )
    return BackfillProgress(pages=pages, commits=commits, finished=False)


async def claimable_runs(session: AsyncSession, *, limit: int) -> list[BackfillRun]:
    """Runs a worker may pick up, oldest first so newer signups can't starve
    older ones. Excludes runs whose lease is live or throttle hasn't elapsed.
    """
    now = datetime.now(UTC)
    statement = (
        select(BackfillRun)
        .where(
            BackfillRun.state.in_(
                [BackfillState.PENDING, BackfillState.RUNNING, BackfillState.THROTTLED]
            ),
            (BackfillRun.leased_until.is_(None)) | (BackfillRun.leased_until <= now),
            (BackfillRun.resume_after.is_(None)) | (BackfillRun.resume_after <= now),
        )
        .order_by(BackfillRun.created_at)
        .limit(limit)
    )
    return list((await session.scalars(statement)).all())
