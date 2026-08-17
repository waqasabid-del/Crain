"""A queue that decides *whose* work runs next.

Pub/Sub answers "what arrived first". Step 30 needs "whose turn is it", and that
is a scheduling decision with two rules:

**Priority is absolute.** A live GitHub push outranks a backfill however long the
backfill has waited. Backfill is work nobody is waiting for; a push is somebody
watching a screen.

**Within a priority, a tenant's second job loses to another tenant's first.** A
customer importing three years of history has thousands of jobs queued and, at
any moment, no more of them running than anyone else. Ordering by `enqueued_at`
alone is what lets one backlog occupy every worker.

Both live in one `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)`, so
the decision is atomic across however many workers are running. Two workers
cannot lease the same row, and no worker has to know the others exist.

Nothing is deleted except on success. A job that failed its retries becomes
`dead` with a reason; a job that flooded its tenant's share is deferred by moving
`available_at` forward. A queue that drops work under load is one nobody can
reason about afterwards.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api import telemetry
from cairn_api.db.session import platform_session
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import Priority, QueueDepth, QueueMessage
from cairn_api.telemetry import correlation

logger = structlog.get_logger(__name__)

#: How many jobs one tenant may have in flight at once.
#:
#: The cap is what makes fairness hold under sustained load rather than only at
#: the moment of claiming: without it, a tenant with ten thousand queued jobs
#: takes every free slot as soon as one frees up.
MAX_ACTIVE_PER_TENANT = 4

#: Queued jobs per tenant before new work is deferred rather than claimed.
#:
#: Deferred, never dropped: the row stays, `available_at` moves forward, and the
#: job runs when the backlog drains. Dropping would make the queue's promise
#: conditional on load, which is when the promise matters.
MAX_QUEUED_PER_TENANT = 500

#: How long a deferred job waits before it may be claimed again.
DEFER_SECONDS = 30

#: How long a lease lasts. Longer than any handler should take; a worker that
#: dies mid-job has its work reclaimed after this, not lost.
LEASE_SECONDS = 300

#: Where the correlation id lives until it has a column of its own.
#:
#: `scheduled_jobs` has a `traceparent` column and nothing for the durable
#: correlation id (`telemetry/correlation.py`), and adding one is a migration —
#: serialised in this release. The payload column is JSONB and already durable,
#: so the id travels inside it under a reserved key that is written on publish
#: and removed again on receive: a handler never sees it, and a payload can
#: never collide with it because the key is not one any GitHub or internal
#: payload produces.
#:
#: This is a placement, not a design preference. A column would be indexable and
#: would let an operator answer "show me every job for this webhook" in SQL;
#: `docs/CORRELATION.md` records the migration to apply when the release allows
#: one, and `_unpack` will keep working against rows written either way.
CORRELATION_KEY = "__cairn_correlation_id"

#: How far back "recent" reaches for the dead-letter alert. Matches the window
#: in `docs/OPERATIONS.md`: page above five dead letters in an hour.
DEAD_LETTER_WINDOW_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class Fairness:
    """How evenly the queue is being served.

    Not a productivity measure and not per person: this counts jobs waiting for
    machines, and exists so an operator can see starvation before a customer
    reports it.
    """

    tenants_waiting: int
    max_wait_seconds: float
    min_wait_seconds: float

    @property
    def starving(self) -> bool:
        """True when one tenant has waited far longer than another.

        Ten times the shortest wait, floored at a minute so an idle queue with
        two jobs a second apart does not read as unfair.
        """
        return self.max_wait_seconds > max(60.0, self.min_wait_seconds * 10)


@dataclass(frozen=True, slots=True)
class DeadLetterHealth:
    """What an operator needs to answer the DLQ alert.

    `docs/OPERATIONS.md` specifies "warning = any dead letter, page = >5 in an
    hour". `total` answers the first, `recent` the second, and `oldest_age_seconds`
    is what distinguishes a burst that has been sitting unnoticed for a week from
    one that started five minutes ago.

    Counts of jobs, per job type and per error category — never per person, and
    the category is `telemetry.dead_letter_category`'s bounded output, not the
    stored reason.
    """

    total: int
    recent: int
    window_seconds: float
    oldest_age_seconds: float | None
    newest_age_seconds: float | None
    by_job_type: dict[str, int]
    by_category: dict[str, int]

    @property
    def paging(self) -> bool:
        """True at the threshold `docs/OPERATIONS.md` pages on."""
        return self.recent > 5


class PostgresJobQueue:
    """`JobQueue`, backed by the scheduling table.

    Implements the same protocol as the in-memory and Pub/Sub brokers, so the
    worker is unchanged: it still receives, acks, retries and dead-letters.
    """

    def __init__(self, *, worker_id: str | None = None) -> None:
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"

    async def publish(
        self,
        envelope: JobEnvelope,
        *,
        priority: Priority = Priority.STANDARD,
        delay_seconds: float = 0.0,
    ) -> None:
        """Record a job, or recognise a redelivery.

        `ON CONFLICT DO NOTHING` on the envelope's job id: publishing the same
        job twice is a redelivery, and the idempotency the pipeline already
        relies on lives on that id.

        The queued-count check is not atomic with the insert, so two concurrent
        publishes can both see room and put a tenant a little over the limit.
        Deliberate: this is a throttle, not a quota. Nothing is refused either
        way — being a few jobs above the line delays that tenant slightly and
        costs nobody else anything, whereas serialising every publish behind a
        lock would put a contention point in front of every webhook.
        """
        async with platform_session() as session:
            queued = await self._queued_for(session, envelope.tenant_id)
            deferred = queued >= MAX_QUEUED_PER_TENANT
            delay = max(delay_seconds, DEFER_SECONDS if deferred else 0.0)

            await session.execute(
                text("""
                    INSERT INTO scheduled_jobs (
                        job_id, tenant_id, job_type, priority, payload, attempt,
                        traceparent, state, available_at
                    ) VALUES (
                        :job_id, :tenant_id, :job_type, :priority, CAST(:payload AS jsonb),
                        :attempt, :traceparent, 'queued',
                        now() + make_interval(secs => :defer)
                    )
                    ON CONFLICT (job_id) DO NOTHING
                """),
                {
                    "job_id": str(envelope.job_id),
                    "tenant_id": str(envelope.tenant_id),
                    "job_type": envelope.job_type,
                    "priority": int(priority),
                    "payload": _json(_pack(envelope.payload, envelope.correlation_id)),
                    "attempt": envelope.attempt,
                    "traceparent": envelope.traceparent,
                    "defer": delay,
                },
            )
            await session.commit()

        telemetry.record_queue_event(
            job_type=envelope.job_type,
            outcome="deferred" if deferred else "published",
            priority=priority.name.lower(),
        )
        if deferred:
            await logger.awarning(
                "queue.tenant_deferred",
                tenant_id=str(envelope.tenant_id),
                queued=queued,
                defer_seconds=DEFER_SECONDS,
            )

    async def receive(self, *, max_messages: int = 1) -> list[QueueMessage]:
        """Claim work, in one statement.

        Ordering is by priority, then by *cost to the tenant's share*, then by
        age. That middle term is what makes fairness hold inside a single batch
        as well as across workers.

        Counting only live leases would let one `receive(max_messages=4)` hand a
        heavy tenant all four slots: every row is scored against the same
        pre-statement state, so ten queued jobs from one tenant all score zero.
        The tenant's own backlog position is added — job *n* of that tenant's
        eligible queue costs *n* — so the batch interleaves. Tenant A's second
        job scores 1 and loses to tenant B's first, which scores 0.

        The same figure bounds the claim: a tenant may hold `cap` jobs, live
        leases and this batch's claims counted together. It is computed once in
        a `LATERAL` so the bound and the ordering cannot drift apart.

        `FOR UPDATE SKIP LOCKED` makes the whole thing safe to run from as many
        workers as are up. A row another worker has locked is passed over rather
        than waited on, so two workers never lease the same job and neither one
        blocks.

        The backlog-position subquery is correlated and unindexed on the
        comparison, so it is linear in a tenant's queued backlog. That is fine at
        the per-tenant caps here and would not be at a hundred thousand; it is
        the first thing to revisit if claim latency grows.
        """
        async with platform_session() as session:
            await self._reclaim_expired(session)

            rows = (
                (
                    await session.execute(
                        text("""
                        UPDATE scheduled_jobs
                        SET state = 'leased',
                            leased_by = :worker,
                            leased_until = now() + make_interval(secs => :lease)
                        WHERE job_id IN (
                            SELECT j.job_id
                            FROM scheduled_jobs j
                            CROSS JOIN LATERAL (
                                -- What claiming this job would cost its tenant's
                                -- share: what that tenant is already running,
                                -- plus this job's position in its own backlog.
                                -- Computed once, then used to both bound and
                                -- order the claim.
                                SELECT (
                                    SELECT count(*) FROM scheduled_jobs active
                                    WHERE active.tenant_id = j.tenant_id
                                      AND active.state = 'leased'
                                      AND active.leased_until > now()
                                ) + (
                                    SELECT count(*) FROM scheduled_jobs ahead
                                    WHERE ahead.tenant_id = j.tenant_id
                                      AND ahead.state = 'queued'
                                      AND ahead.available_at <= now()
                                      AND (
                                          ahead.priority > j.priority
                                          OR (ahead.priority = j.priority
                                              AND ahead.enqueued_at < j.enqueued_at)
                                      )
                                ) AS share_cost
                            ) cost
                            WHERE j.state = 'queued'
                              AND j.available_at <= now()
                              AND cost.share_cost < :cap
                            ORDER BY
                                j.priority DESC,
                                cost.share_cost ASC,
                                j.enqueued_at ASC
                            LIMIT :limit
                            FOR UPDATE OF j SKIP LOCKED
                        )
                        RETURNING job_id, tenant_id, job_type, priority, payload,
                                  attempt, traceparent
                    """),
                        {
                            "worker": self._worker_id,
                            "lease": LEASE_SECONDS,
                            "cap": MAX_ACTIVE_PER_TENANT,
                            "limit": max_messages,
                        },
                    )
                )
                .mappings()
                .all()
            )
            await session.commit()

        messages = [self._message_from(row) for row in rows]

        for message in messages:
            telemetry.record_queue_event(
                job_type=message.envelope.job_type,
                outcome="claimed",
                priority=message.priority.name.lower(),
            )
        return messages

    def _message_from(self, row: Any) -> QueueMessage:
        """Rebuild the envelope a claimed row describes.

        The correlation id comes back out of the payload and off the handler's
        plate. A row written before this existed — a rolling deploy, a backlog
        published by the previous revision — has no id in it; `JobEnvelope` then
        mints one rather than refusing to parse, so the job runs and is
        followable from here on even if it cannot be joined to its webhook.
        """
        payload, correlation_id = _unpack(row["payload"])
        fields: dict[str, Any] = {
            "job_type": row["job_type"],
            "tenant_id": row["tenant_id"],
            "payload": payload,
            "job_id": row["job_id"],
            "attempt": row["attempt"],
            "traceparent": row["traceparent"],
        }
        # Omitted rather than passed as None when the row predates the id, so
        # the envelope's default factory mints one instead of failing to parse.
        if correlation_id is not None:
            fields["correlation_id"] = correlation_id
        envelope = JobEnvelope(**fields)
        return QueueMessage(
            envelope=envelope,
            receipt=str(row["job_id"]),
            priority=Priority(row["priority"]),
            delivery_attempt=row["attempt"],
        )

    async def ack(self, message: QueueMessage) -> None:
        """Done. The only path that deletes a row."""
        async with platform_session() as session:
            await session.execute(
                text("DELETE FROM scheduled_jobs WHERE job_id = :job_id"),
                {"job_id": message.receipt},
            )
            await session.commit()

        telemetry.record_queue_event(job_type=message.envelope.job_type, outcome="acked")

    async def retry(self, message: QueueMessage, *, delay_seconds: float) -> None:
        """Release the lease and wait before offering it again."""
        async with platform_session() as session:
            await session.execute(
                text("""
                    UPDATE scheduled_jobs
                    SET state = 'queued',
                        leased_by = NULL,
                        leased_until = NULL,
                        attempt = attempt + 1,
                        available_at = now() + make_interval(secs => :delay)
                    WHERE job_id = :job_id
                """),
                {"job_id": message.receipt, "delay": delay_seconds},
            )
            await session.commit()

        telemetry.record_queue_event(job_type=message.envelope.job_type, outcome="retried")

    async def dead_letter(self, message: QueueMessage, *, reason: str) -> None:
        """Give up, and keep the row.

        A job that disappeared is indistinguishable from one that was never
        sent, which is the position nobody can investigate from.

        `available_at` is set to now as the time of death. A dead row is never
        claimed — every query that reads `available_at` filters `state =
        'queued'` first — so the column's "when may this be claimed" meaning is
        vacuous here, and it is the only durable timestamp available without a
        migration. It is what makes "more than five in the last hour" a question
        the queue can answer rather than a graph somebody has to eyeball.
        `docs/CORRELATION.md` records the `dead_at` column that replaces it.
        """
        async with platform_session() as session:
            await session.execute(
                text("""
                    UPDATE scheduled_jobs
                    SET state = 'dead',
                        leased_by = NULL,
                        leased_until = NULL,
                        dead_reason = :reason,
                        available_at = now()
                    WHERE job_id = :job_id
                """),
                {"job_id": message.receipt, "reason": reason[:500]},
            )
            await session.commit()

        telemetry.record_queue_event(job_type=message.envelope.job_type, outcome="dead_lettered")
        telemetry.record_dead_letter(
            job_type=message.envelope.job_type,
            reason=reason,
            priority=message.priority.name.lower(),
        )
        # ERROR, with the correlation id and the bounded category as fields and
        # the full reason kept alongside them: the row and the log hold the
        # text, the metric holds the category, and neither the exporter nor a
        # dashboard ever sees what the failure quoted.
        await logger.aerror(
            "queue.dead_lettered",
            job_id=str(message.envelope.job_id),
            job_type=message.envelope.job_type,
            tenant_id=str(message.envelope.tenant_id),
            correlation_id=message.envelope.correlation_id,
            attempt=message.envelope.attempt,
            error_category=telemetry.dead_letter_category(reason),
            reason=reason,
        )

    async def depth(self) -> QueueDepth:
        """Global and per-tenant counts, from the durable record."""
        async with platform_session() as session:
            rows = (
                (
                    await session.execute(
                        text("""
                        SELECT tenant_id,
                               count(*) FILTER (WHERE state = 'queued') AS queued,
                               count(*) FILTER (WHERE state = 'leased') AS leased,
                               count(*) FILTER (WHERE state = 'dead') AS dead
                        FROM scheduled_jobs
                        GROUP BY tenant_id
                    """)
                    )
                )
                .mappings()
                .all()
            )

        # Per tenant, the count that answers "who is starved" is what is still
        # waiting. In-flight work is not starvation; it is service.
        per_tenant = {row["tenant_id"]: int(row["queued"]) for row in rows if row["queued"]}
        return QueueDepth(
            pending=sum(per_tenant.values()),
            in_flight=sum(int(row["leased"]) for row in rows),
            dead_lettered=sum(int(row["dead"]) for row in rows),
            per_tenant=per_tenant,
        )

    async def dead_letter_health(
        self, *, window_seconds: float = DEAD_LETTER_WINDOW_SECONDS
    ) -> DeadLetterHealth:
        """The dead-letter queue, as an operator needs to see it.

        Not an endpoint — routers belong to someone else — but the whole of what
        one would serve: totals, the count inside the alert's window, the age of
        the oldest and newest, and a breakdown by job type and by category.

        The categories are derived here, from `dead_reason`, rather than stored:
        the reason is the durable record and the category is a *view* of it, so
        changing how failures are grouped never means backfilling a column, and
        the metric and this reader cannot disagree because they call the same
        function.
        """
        async with platform_session() as session:
            rows = (
                (
                    await session.execute(
                        text("""
                        SELECT job_type,
                               dead_reason,
                               extract(epoch FROM now() - available_at) AS age_seconds
                        FROM scheduled_jobs
                        WHERE state = 'dead'
                    """)
                    )
                )
                .mappings()
                .all()
            )

        ages = [float(row["age_seconds"] or 0.0) for row in rows]
        by_job_type: dict[str, int] = defaultdict(int)
        by_category: dict[str, int] = defaultdict(int)
        for row in rows:
            by_job_type[str(row["job_type"])] += 1
            by_category[telemetry.dead_letter_category(row["dead_reason"])] += 1

        return DeadLetterHealth(
            total=len(rows),
            recent=sum(1 for age in ages if age <= window_seconds),
            window_seconds=window_seconds,
            oldest_age_seconds=max(ages) if ages else None,
            newest_age_seconds=min(ages) if ages else None,
            by_job_type=dict(by_job_type),
            by_category=dict(by_category),
        )

    async def fairness(self) -> Fairness:
        """How long the longest-waiting tenant has waited against the shortest."""
        async with platform_session() as session:
            rows = (
                await session.execute(
                    text("""
                        SELECT extract(epoch FROM now() - min(enqueued_at)) AS waited
                        FROM scheduled_jobs
                        WHERE state = 'queued' AND available_at <= now()
                        GROUP BY tenant_id
                    """)
                )
            ).all()

        waits = [float(row[0] or 0) for row in rows]
        return Fairness(
            tenants_waiting=len(waits),
            max_wait_seconds=max(waits, default=0.0),
            min_wait_seconds=min(waits, default=0.0),
        )

    async def _queued_for(self, session: AsyncSession, tenant_id: uuid.UUID) -> int:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM scheduled_jobs "
                "WHERE tenant_id = :tenant_id AND state = 'queued'"
            ),
            {"tenant_id": str(tenant_id)},
        )
        return int(count or 0)

    async def _reclaim_expired(self, session: AsyncSession) -> None:
        """Return work from a worker that stopped talking.

        The lease is the only thing standing between a crashed worker and a job
        nobody ever runs again.
        """
        # `RETURNING` rather than `rowcount`: the count is then a value the query
        # produced rather than a driver attribute whose type depends on which
        # Result implementation came back.
        reclaimed = len(
            (
                await session.execute(
                    text("""
                        UPDATE scheduled_jobs
                        SET state = 'queued', leased_by = NULL, leased_until = NULL
                        WHERE state = 'leased' AND leased_until <= now()
                        RETURNING job_id
                    """)
                )
            ).all()
        )
        if reclaimed:
            await logger.awarning("queue.leases_reclaimed", count=reclaimed)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str)


def _pack(payload: dict[str, Any], correlation_id: str) -> dict[str, Any]:
    """The payload as it is stored, with the correlation id alongside it."""
    return {**payload, CORRELATION_KEY: correlation_id}


def _unpack(stored: dict[str, Any] | None) -> tuple[dict[str, Any], str | None]:
    """Split a stored payload back into the handler's payload and the id.

    The id is validated on the way out (`telemetry.correlation.coerce`) rather
    than trusted: this is a database column, and anything that reached it by a
    route other than `_pack` must not be able to put a string of its choosing
    onto a span.
    """
    payload = dict(stored or {})
    return payload, correlation.coerce(payload.pop(CORRELATION_KEY, None))
