"""The backfill job handler.

A batch re-enqueues itself rather than looping: `process_batch` returns after a
bounded number of pages to release the worker slot, and looping would hold one
worker for a run's whole life.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.backfill_models import BackfillRun, BackfillState
from cairn_api.github.backfill import BACKFILL_JOB, claim, process_batch
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import JobQueue, Priority
from cairn_api.jobs.runner import JobRegistry, registry

logger = structlog.get_logger(__name__)


class BackfillRunNotFoundError(LookupError):
    """Run deleted, or the job's tenant does not match it — a tenant-scoping failure."""


def make_handler(queue: JobQueue, *, worker_id: str | None = None) -> object:
    """Build the handler, bound to the queue it re-enqueues onto.

    A factory because the job runner's signature supplies no queue (`runner.py`).
    """
    identity = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

    async def handle_backfill(session: AsyncSession, envelope: JobEnvelope) -> None:
        raw_id = envelope.payload.get("run_id")
        if not isinstance(raw_id, str):
            msg = f"Job {envelope.job_id} has no run_id"
            raise BackfillRunNotFoundError(msg)

        run_id = uuid.UUID(raw_id)
        run = await claim(session, run_id, worker=identity)
        if run is None:
            # Not an error: at-least-once delivery makes a duplicate job normal.
            await logger.adebug("backfill.already_claimed", run_id=raw_id)
            return

        from cairn_api.github.client import GitHubGraphQLClient

        client = _client_for(session)
        if client is None:
            # Parked rather than FAILED so it recovers once the secret is injected.
            run.state = BackfillState.THROTTLED
            run.resume_after = datetime.now(UTC)
            await logger.aerror(
                "backfill.no_credentials",
                run_id=raw_id,
                detail="CAIRN_GITHUB_APP_ID and CAIRN_GITHUB_PRIVATE_KEY are required.",
            )
            return

        assert isinstance(client, GitHubGraphQLClient)  # noqa: S101
        progress = await process_batch(session, run, client)

        if progress.finished:
            return

        # Re-enqueue rather than loop; see module docstring.
        delay = progress.throttled_for or 0.0
        await queue.publish(
            JobEnvelope(
                job_type=BACKFILL_JOB,
                tenant_id=envelope.tenant_id,
                payload={"run_id": raw_id},
            ),
            priority=Priority.BULK,
            delay_seconds=delay,
        )

    return handle_backfill


def _client_for(session: AsyncSession) -> object | None:
    from cairn_api.config import get_settings
    from cairn_api.github.auth import InstallationTokenCache
    from cairn_api.github.client import GitHubGraphQLClient

    _ = session
    settings = get_settings()
    if not settings.github_app_id or not settings.github_private_key:
        return None

    import httpx

    http = httpx.AsyncClient(timeout=30)
    tokens = InstallationTokenCache(
        app_id=settings.github_app_id,
        private_key=settings.github_private_key,
        client=http,
    )
    return GitHubGraphQLClient(tokens=tokens, client=http)


async def enqueue(queue: JobQueue, run: BackfillRun, *, delay_seconds: float = 0.0) -> None:
    """Publish a run at `BULK`: an import must not sit ahead of live events (md/06 §6B.3)."""
    await queue.publish(
        JobEnvelope(
            job_type=BACKFILL_JOB,
            tenant_id=run.tenant_id,
            payload={"run_id": str(run.id)},
        ),
        priority=Priority.BULK,
        delay_seconds=delay_seconds,
    )


def register(queue: JobQueue, target: JobRegistry | None = None) -> None:
    """Register the backfill handler. Explicit so contents do not depend on import order."""
    (target or registry).register(BACKFILL_JOB)(make_handler(queue))  # type: ignore[arg-type]
