"""Measuring the objectives, from the tables that can actually answer them.

Every function here either returns a number it can defend or returns `None`
with a reason. There is no third case, and specifically no default — an
objective whose measurement raised, or whose window held no work, must not fall
back to the target and report itself satisfied.

The measurements read platform-wide counts. Nothing is grouped by tenant and
nothing selects a payload: the objective "95% of deliveries complete in fifteen
minutes" needs two integers, and asking for anything more would put customer
content behind a staff role that md/15 §5.2 keeps it out of.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.config import Settings
from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.ops.slo import OBJECTIVES, PIPELINE_COMPLETION_TARGET, ServiceLevelObjective


@dataclass(frozen=True, slots=True)
class Measurement:
    """One objective and what it currently reads.

    `measured is None` is a first-class answer, and the `note` says which kind
    of "no number" it is: the infrastructure cannot produce it at all, or it
    can and there was nothing in the window. Those need different actions —
    build the instrumentation, or wait — and one field for both would hide it.
    """

    objective: ServiceLevelObjective
    measured: float | None = None
    note: str | None = None

    @property
    def met(self) -> bool | None:
        return self.objective.met(self.measured)


async def measure_all(db: AsyncSession, settings: Settings) -> tuple[Measurement, ...]:
    """Every objective, measured or explicitly not."""
    return tuple([await measure(objective, db, settings) for objective in OBJECTIVES])


async def measure(
    objective: ServiceLevelObjective, db: AsyncSession, settings: Settings
) -> Measurement:
    """One objective.

    Dispatch on the key rather than on a method attached to the objective, so
    `slo.py` stays a description of what is promised and has no database
    import — the definitions are readable by somebody who is not going to read
    SQL, which is the point of writing them down.
    """
    if not objective.measurable:
        return Measurement(objective, None, objective.unmeasurable_reason)

    if objective.key == "queue_first_attempt":
        return await _queue_first_attempt(objective, settings)
    if objective.key == "pipeline_completion":
        return await _pipeline_completion(objective, db)
    if objective.key == "delivery_error_rate":
        return await _delivery_error_rate(objective, db)

    # Reachable only by adding a measurable objective and no measurement for
    # it. Reported rather than raised: one unfinished objective must not take
    # the operations screen down during the incident it was added for.
    return Measurement(objective, None, "No measurement is implemented for this objective.")


async def _queue_first_attempt(objective: ServiceLevelObjective, settings: Settings) -> Measurement:
    """The longest a job has been waiting to be claimed, right now.

    Only the PostgreSQL scheduler has a durable queue. On the in-memory broker
    the queue is per replica and lost on restart; on Pub/Sub the wait is inside
    a service CAIRN cannot query. Both report unmeasurable rather than zero —
    an empty number on this row would read as "nothing is waiting".
    """
    if settings.queue_backend != "postgres":
        return Measurement(
            objective,
            None,
            (
                f"CAIRN_QUEUE_BACKEND is '{settings.queue_backend}'. Only the "
                "postgres scheduler keeps enqueue times in a table this process "
                "can read."
            ),
        )

    from cairn_api.jobs.postgres import PostgresJobQueue

    fairness = await PostgresJobQueue().fairness()
    if fairness.tenants_waiting == 0:
        # Genuinely zero: nothing is waiting, so the longest wait is zero
        # minutes. Distinct from the unmeasurable cases above.
        return Measurement(objective, 0.0, "No jobs are waiting.")

    return Measurement(objective, fairness.max_wait_seconds / 60)


async def _pipeline_completion(objective: ServiceLevelObjective, db: AsyncSession) -> Measurement:
    """Share of deliveries in the window that finished inside the target.

    Unprocessed rows count as misses. Counting only processed rows would let a
    pipeline that has stopped entirely report a perfect score, which is the
    exact failure this objective exists to catch.
    """
    since = datetime.now(UTC) - objective.window

    total = await db.scalar(
        select(func.count()).select_from(WebhookDelivery).where(WebhookDelivery.created_at >= since)
    )
    if not total:
        return Measurement(objective, None, "No deliveries in the window.")

    # `extract(epoch from ...)` rather than comparing an interval, so the
    # comparison is between two numbers and needs no dialect-specific casting.
    elapsed_seconds = func.extract(
        "epoch", WebhookDelivery.processed_at - WebhookDelivery.created_at
    )
    completed = await db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(
            WebhookDelivery.created_at >= since,
            WebhookDelivery.processed_at.is_not(None),
            cast(elapsed_seconds, Numeric) <= PIPELINE_COMPLETION_TARGET.total_seconds(),
        )
    )
    return Measurement(objective, int(completed or 0) / int(total))


async def _delivery_error_rate(objective: ServiceLevelObjective, db: AsyncSession) -> Measurement:
    """Share of deliveries in the window that ended in a failure."""
    since = datetime.now(UTC) - objective.window

    total = await db.scalar(
        select(func.count()).select_from(WebhookDelivery).where(WebhookDelivery.created_at >= since)
    )
    if not total:
        return Measurement(objective, None, "No deliveries in the window.")

    failed = await db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(
            WebhookDelivery.created_at >= since,
            WebhookDelivery.status == DeliveryStatus.FAILED,
        )
    )
    return Measurement(objective, int(failed or 0) / int(total))


__all__ = ["Measurement", "measure", "measure_all"]
