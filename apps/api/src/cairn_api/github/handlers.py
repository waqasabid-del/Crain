"""Processing a delivery, on the worker.

The payload is re-read from the database, not taken from the job message:
the queue is not a durable store and redelivery is normal. Idempotency is
checked here too, guarding duplicate *execution* where the endpoint only
guards duplicate *enqueue*.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.github.attribution import attribute
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import JobQueue
from cairn_api.jobs.retry import DEFAULT_RETRY_POLICY
from cairn_api.jobs.runner import JobHandler, JobRegistry, registry
from cairn_api.pipeline import jobs as pipeline_jobs

logger = structlog.get_logger(__name__)

GITHUB_DELIVERY_JOB = "github.delivery"

#: Mirrors `RetryPolicy.max_attempts`; a test asserts the two agree.
FINAL_ATTEMPT_THRESHOLD = DEFAULT_RETRY_POLICY.max_attempts


class DeliveryNotFoundError(LookupError):
    """The delivery named by a job does not exist in this tenant."""


async def handle_delivery(
    session: AsyncSession, envelope: JobEnvelope, *, queue: JobQueue | None = None
) -> None:
    """Process one webhook delivery. The session is already tenant-scoped."""
    delivery_id = envelope.payload.get("delivery_id")
    if not isinstance(delivery_id, str):
        msg = f"Job {envelope.job_id} has no delivery_id"
        raise DeliveryNotFoundError(msg)

    delivery = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
    )
    if delivery is None:
        msg = f"Delivery {delivery_id} not found for tenant {envelope.tenant_id}"
        raise DeliveryNotFoundError(msg)

    if delivery.status is DeliveryStatus.PROCESSED:
        await logger.adebug("github.delivery_already_processed", delivery_id=delivery_id)
        return

    try:
        await _process(session, delivery, tenant_id=envelope.tenant_id, queue=queue)
    except Exception as exc:
        delivery.error = f"{type(exc).__name__}: {exc}"[:1024]
        if envelope.attempt >= FINAL_ATTEMPT_THRESHOLD:
            delivery.status = DeliveryStatus.FAILED
        raise

    delivery.status = DeliveryStatus.PROCESSED
    delivery.processed_at = datetime.now(UTC)
    delivery.error = None

    await logger.ainfo(
        "github.delivery_processed",
        delivery_id=delivery_id,
        event_type=delivery.event_type,
        action=delivery.action,
    )


async def _process(
    session: AsyncSession,
    delivery: WebhookDelivery,
    *,
    tenant_id: uuid.UUID,
    queue: JobQueue | None = None,
) -> None:
    """Attribute the payload's work, then publish understanding.

    Order is load-bearing: publishing first would resolve mentions against
    an identity graph missing the person who just pushed.
    """
    result = await attribute(session, delivery.payload, tenant_id=tenant_id)

    await logger.ainfo(
        "github.delivery_attributed",
        event_type=delivery.event_type,
        commits=result.commits_seen,
        # Counts only: names/addresses in the log store would escape erasure.
        people=len(result.people),
        bots=len(result.bots),
        unparseable=result.unparseable,
    )

    if queue is None:
        # Loud, not silent: without a queue this delivery never produces a fact.
        await logger.aerror(
            "github.understanding_not_published",
            delivery_id=delivery.delivery_id,
            detail=(
                "No queue was bound to the delivery handler, so no understanding "
                "job was published and this delivery will never produce a fact. "
                "Register with github.handlers.register(queue=...)."
            ),
        )
        return

    await pipeline_jobs.publish(queue, tenant_id=tenant_id, delivery_id=delivery.delivery_id)


def make_handler(queue: JobQueue) -> JobHandler:
    """Build the handler, bound to the queue it publishes onto (see `runner.py`)."""

    async def handler(session: AsyncSession, envelope: JobEnvelope) -> None:
        await handle_delivery(session, envelope, queue=queue)

    return handler


def register(target: JobRegistry | None = None, *, queue: JobQueue | None = None) -> None:
    """Register the handler, explicit rather than by import side effect."""
    handler = make_handler(queue) if queue is not None else handle_delivery
    (target or registry).register(GITHUB_DELIVERY_JOB)(handler)
