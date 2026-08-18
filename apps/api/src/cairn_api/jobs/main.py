"""The worker process entrypoint (``make worker``), separate from the API
since they scale on different signals (md/06 §6B.2). Handlers are imported
here, not scanned for, so a missing registration fails as an import error."""

from __future__ import annotations

import asyncio
import contextlib
import signal

import structlog

from cairn_api.api.ratelimit import purge_expired_buckets
from cairn_api.config import get_settings
from cairn_api.connectors.credentials import build_cipher
from cairn_api.db.preflight import run_preflight_checks
from cairn_api.db.session import dispose_engines, platform_session
from cairn_api.gchat import subscriptions as gchat_subscriptions
from cairn_api.github import handlers as github_handlers
from cairn_api.github import jobs as github_jobs
from cairn_api.gmeet import retrieval as gmeet_retrieval
from cairn_api.gmeet import subscriptions as gmeet_subscriptions
from cairn_api.jobs.factory import build_queue
from cairn_api.jobs.queue import JobQueue
from cairn_api.jobs.runner import JobRegistry
from cairn_api.jobs.worker import Worker, WorkerConfig
from cairn_api.logging import configure_logging
from cairn_api.pipeline import jobs as pipeline_jobs
from cairn_api.pipeline import retention
from cairn_api.telemetry.startup import check_telemetry

logger = structlog.get_logger(__name__)

DEPTH_REPORT_INTERVAL_SECONDS = 15.0
MAINTENANCE_INTERVAL_SECONDS = 3600.0

RATE_LIMIT_BUCKET_TTL_SECONDS = 86400.0


async def report_depth(queue: JobQueue, *, interval: float) -> None:
    """Per-tenant depth answers "who is starving" (md/06 §6B.3), which the total alone hides."""
    while True:
        try:
            depth = await queue.depth()
        except Exception as exc:
            await logger.awarning("queue.depth_unavailable", error=str(exc))
        else:
            await logger.ainfo(
                "queue.depth",
                pending=depth.pending,
                in_flight=depth.in_flight,
                dead_lettered=depth.dead_lettered,
                total=depth.total,
            )
            # Only the busiest few — a line per tenant is unreadable at scale.
            for tenant_id, count in sorted(depth.per_tenant.items(), key=lambda item: -item[1])[:5]:
                await logger.ainfo("queue.depth.tenant", tenant_id=str(tenant_id), pending=count)

        await asyncio.sleep(interval)


async def run_maintenance(*, interval: float) -> None:
    """Not a queued job: `rate_limit_buckets` isn't tenant-scoped, but handlers only get one (`runner.py`)."""
    while True:
        await asyncio.sleep(interval)
        try:
            async with platform_session() as session:
                purged = await purge_expired_buckets(
                    session, older_than_seconds=RATE_LIMIT_BUCKET_TTL_SECONDS
                )
                expired = await retention.sweep(session)
                # Google Chat subscriptions are four-hour leases that are
                # *deleted* when they lapse, so this pass is not housekeeping:
                # a missed renewal is a space that stops delivering and cannot
                # be backfilled. It lives here rather than in a scheduler of its
                # own because a second periodic loop is a second thing to
                # supervise, and `gchat/subscriptions.py` already claims its
                # rows `FOR UPDATE SKIP LOCKED` so running it from every worker
                # is safe and renews nothing twice.
                renewals = await gchat_subscriptions.renew_expiring_subscriptions(session)
                # The Google Meet pass, on the same loop and claiming its rows
                # the same way. It is *not* housekeeping either, and it does one
                # thing Chat's does not: it re-asks Step 35's consent gate for
                # every lease before renewing it, so a withdrawal, a decline, a
                # late participant, a reschedule or a policy change tears the
                # subscription down on the next pass rather than waiting for it
                # to lapse.
                meet_renewals = await gmeet_subscriptions.renew_expiring_subscriptions(session)
                # Step 36B: retrieve the transcripts a consented meeting
                # announced. On this loop rather than on the job queue because
                # the unit of work is "whatever is waiting" rather than one
                # message, and because a queued job would carry an artifact
                # reference in its payload — which is the one identifier this
                # connector keeps encrypted and off every diagnostics screen.
                #
                # The pass re-asks Step 35's consent gate for every artifact
                # immediately before the download it authorises, so a withdrawal
                # between the announcement and the retrieval collects nothing.
                transcripts = await gmeet_retrieval.retrieve_pending_transcripts(session)
                # And the retention path, which is what makes the raw store
                # deletable rather than merely bounded. Provenance survives it.
                transcripts_purged = await gmeet_retrieval.purge_expired_transcripts(session)
        except Exception as exc:
            await logger.awarning("maintenance.failed", error=str(exc))
        else:
            if purged:
                await logger.ainfo("maintenance.rate_limit_buckets_purged", count=purged)
            if expired:
                await logger.ainfo("maintenance.raw_activity_deleted", count=expired)
            if renewals.considered:
                await logger.ainfo(
                    "maintenance.gchat_subscriptions_renewed",
                    count=renewals.changed,
                    failed=renewals.failed,
                )
            if meet_renewals.considered:
                await logger.ainfo(
                    "maintenance.gmeet_subscriptions_renewed",
                    count=meet_renewals.changed,
                    # Counted separately from `failed` on purpose: a lease torn
                    # down because consent moved is the product working, and an
                    # aggregate that called it a failure would page somebody
                    # every time somebody exercised a right.
                    withdrawn=meet_renewals.withdrawn,
                    failed=meet_renewals.failed,
                )
            if transcripts.considered:
                await logger.ainfo(
                    "maintenance.gmeet_transcripts_retrieved",
                    count=transcripts.retrieved,
                    # Separate from `failed` for the reason `withdrawn` is above:
                    # a transcript refused because consent moved, or because the
                    # thing announced was not a transcript, is the product
                    # working.
                    refused=transcripts.refused,
                    retired=transcripts.retired,
                    failed=transcripts.dead_lettered,
                )
            if transcripts_purged:
                await logger.ainfo("maintenance.gmeet_transcripts_purged", count=transcripts_purged)


def register_handlers(queue: JobQueue, target: JobRegistry | None = None) -> None:
    """Every job type this deployment can execute, in one place — two of
    these were added to close audit findings of a type nobody published or handled.
    """
    github_handlers.register(target, queue=queue)
    github_jobs.register(queue, target)
    pipeline_jobs.register(target)


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings)

    if settings.is_deployed:
        # A role that can bypass row-level security means no tenant isolation.
        await run_preflight_checks()

    # The worker is where the pipeline actually runs, so it is the process whose
    # traces explain a bad brief. It refuses to start blind for the same reason
    # the API does.
    check_telemetry(settings)

    # The worker reads connector credentials to poll and to backfill, so it
    # refuses to start without somewhere safe to decrypt them from — the same
    # refusal the API makes, for the same reason.
    build_cipher(settings)

    queue = build_queue(settings)
    register_handlers(queue)
    worker = Worker(queue, config=WorkerConfig())

    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()

    def _request_stop(signal_name: str) -> None:
        logger.info("worker.signal_received", signal=signal_name)
        worker.stop()
        stopping.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # No signal handlers on Windows.
            loop.add_signal_handler(sig, _request_stop, sig.name)

    background = [
        asyncio.create_task(report_depth(queue, interval=DEPTH_REPORT_INTERVAL_SECONDS)),
        asyncio.create_task(run_maintenance(interval=MAINTENANCE_INTERVAL_SECONDS)),
    ]

    try:
        await worker.run_forever()
    finally:
        for task in background:
            task.cancel()
        for task in background:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await dispose_engines()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("worker.interrupted")


if __name__ == "__main__":
    main()
