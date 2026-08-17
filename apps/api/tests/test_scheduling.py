"""Step 30: who runs next, and what happens when the answer is contested.

The exit criterion is that one heavy tenant cannot starve another, and that
backfill never delays live processing. Both are claims about behaviour under
load, so the tests here build the load rather than asserting on the query.

Everything runs against real PostgreSQL. The mechanisms being tested — row
locking, `SKIP LOCKED`, transaction-time `now()` — do not exist anywhere else,
and a test double would be asserting that the double behaves as written.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cairn_api.db.session import platform_session
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.postgres import MAX_ACTIVE_PER_TENANT, MAX_QUEUED_PER_TENANT, PostgresJobQueue
from cairn_api.jobs.queue import Priority
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def clean_queue(platform_engine: AsyncEngine) -> AsyncIterator[None]:
    """Start and finish with an empty queue.

    The queue opens its own connections rather than joining the rolled-back
    `session` fixture — it has to, since the whole point is several connections
    contending — so rows outlive the test that made them unless removed.
    """
    async with platform_engine.begin() as conn:
        await conn.execute(text("DELETE FROM scheduled_jobs"))
    yield
    async with platform_engine.begin() as conn:
        await conn.execute(text("DELETE FROM scheduled_jobs"))


def job(tenant: uuid.UUID, job_type: str = "pipeline.understand") -> JobEnvelope:
    return JobEnvelope(job_type=job_type, tenant_id=tenant)


class TestPriorityIsAbsolute:
    async def test_a_live_event_overtakes_a_backfill_queued_before_it(self) -> None:
        """Backfill is work nobody is waiting for; a push is somebody watching."""
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()

        backfill = job(tenant, "backfill.page")
        await queue.publish(backfill, priority=Priority.BULK)
        live = job(tenant, "github.push")
        await queue.publish(live, priority=Priority.INTERACTIVE)

        [claimed] = await queue.receive(max_messages=1)

        assert claimed.envelope.job_id == live.job_id
        assert claimed.priority is Priority.INTERACTIVE

    async def test_a_heavy_backlog_does_not_delay_another_tenant_s_live_event(self) -> None:
        """The headline claim, built the way it actually happens.

        One workspace imports its history — a hundred bulk jobs, queued first —
        and another workspace pushes a commit. The push is claimed on the very
        next poll, not after the import drains.
        """
        queue = PostgresJobQueue(worker_id="w1")
        importing, pushing = uuid.uuid4(), uuid.uuid4()

        for _ in range(100):
            await queue.publish(job(importing, "backfill.page"), priority=Priority.BULK)

        push = job(pushing, "github.push")
        await queue.publish(push, priority=Priority.INTERACTIVE)

        [claimed] = await queue.receive(max_messages=1)

        assert claimed.envelope.job_id == push.job_id


class TestOneTenantCannotTakeEverything:
    async def test_a_batch_is_shared_rather_than_won(self) -> None:
        """Fairness has to hold inside one claim, not only across workers.

        A quiet tenant's single job is claimed in the same batch as a flooding
        tenant's, even though ten of the flooder's jobs were queued first. This
        is the case that fails if fairness is scored only on live leases.
        """
        queue = PostgresJobQueue(worker_id="w1")
        heavy, quiet = uuid.uuid4(), uuid.uuid4()

        for _ in range(10):
            await queue.publish(job(heavy), priority=Priority.STANDARD)
        only = job(quiet)
        await queue.publish(only, priority=Priority.STANDARD)

        claimed = await queue.receive(max_messages=4)

        assert only.job_id in {message.envelope.job_id for message in claimed}

    async def test_a_tenant_never_holds_more_than_its_share(self) -> None:
        """The cap is what keeps fairness true under sustained load.

        Without it a flooding tenant retakes every slot the moment one frees.
        """
        queue = PostgresJobQueue(worker_id="w1")
        heavy = uuid.uuid4()

        for _ in range(50):
            await queue.publish(job(heavy), priority=Priority.STANDARD)

        claimed = await queue.receive(max_messages=50)

        assert len(claimed) == MAX_ACTIVE_PER_TENANT

    async def test_a_flooding_tenant_is_deferred_and_never_dropped(
        self, platform_engine: AsyncEngine
    ) -> None:
        """Over the queue limit the job waits. It does not disappear.

        A queue that sheds load silently is one nobody can reconcile against
        what they sent it.
        """
        queue = PostgresJobQueue(worker_id="w1")
        heavy = uuid.uuid4()
        overflow = 5

        for _ in range(MAX_QUEUED_PER_TENANT + overflow):
            await queue.publish(job(heavy), priority=Priority.STANDARD)

        depth = await queue.depth()
        async with platform_engine.begin() as conn:
            held = await conn.scalar(
                text("SELECT count(*) FROM scheduled_jobs WHERE available_at > now()")
            )

        assert depth.per_tenant[heavy] == MAX_QUEUED_PER_TENANT + overflow
        assert held == overflow


class TestTwoWorkersNeverCollide:
    async def test_concurrent_claims_do_not_overlap(self) -> None:
        """Eight workers, twelve jobs, no job claimed twice.

        `SKIP LOCKED` is the whole mechanism: a row another worker has locked is
        passed over rather than waited on.
        """
        publisher = PostgresJobQueue(worker_id="publisher")
        tenants = [uuid.uuid4() for _ in range(4)]
        for tenant in tenants:
            for _ in range(3):
                await publisher.publish(job(tenant), priority=Priority.STANDARD)

        workers = [PostgresJobQueue(worker_id=f"w{index}") for index in range(8)]
        batches = await asyncio.gather(*(worker.receive(max_messages=3) for worker in workers))

        claimed = [message.envelope.job_id for batch in batches for message in batch]

        assert len(claimed) == len(set(claimed))

    async def test_a_leased_job_is_invisible_to_everyone_else(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        await queue.publish(job(tenant), priority=Priority.STANDARD)

        first = await queue.receive(max_messages=5)
        second = await PostgresJobQueue(worker_id="w2").receive(max_messages=5)

        assert len(first) == 1
        assert second == []

    async def test_a_dead_worker_s_job_is_reclaimed_rather_than_lost(
        self, platform_engine: AsyncEngine
    ) -> None:
        """The lease is what stands between a crashed worker and orphaned work.

        The lease is expired directly rather than waited out: a test that sleeps
        for the real deadline is a test nobody runs.
        """
        queue = PostgresJobQueue(worker_id="crashed")
        tenant = uuid.uuid4()
        original = job(tenant)
        await queue.publish(original, priority=Priority.STANDARD)
        await queue.receive(max_messages=1)

        async with platform_engine.begin() as conn:
            await conn.execute(
                text("UPDATE scheduled_jobs SET leased_until = now() - interval '1 minute'")
            )

        [reclaimed] = await PostgresJobQueue(worker_id="healthy").receive(max_messages=1)

        assert reclaimed.envelope.job_id == original.job_id


class TestNothingIsLost:
    async def test_a_retry_returns_the_job_and_counts_the_attempt(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        original = job(tenant)
        await queue.publish(original, priority=Priority.STANDARD)

        [message] = await queue.receive(max_messages=1)
        await queue.retry(message, delay_seconds=0)

        [again] = await queue.receive(max_messages=1)

        assert again.envelope.job_id == original.job_id
        assert again.envelope.attempt == 2

    async def test_a_retry_delay_is_respected(self) -> None:
        """Immediate redelivery turns a failing job into a hot loop."""
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        await queue.publish(job(tenant), priority=Priority.STANDARD)

        [message] = await queue.receive(max_messages=1)
        await queue.retry(message, delay_seconds=60)

        assert await queue.receive(max_messages=1) == []

    async def test_a_dead_letter_stays_inspectable(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        await queue.publish(job(tenant), priority=Priority.STANDARD)

        [message] = await queue.receive(max_messages=1)
        await queue.dead_letter(message, reason="UnknownJobTypeError")

        depth = await queue.depth()
        assert depth.dead_lettered == 1
        assert await queue.receive(max_messages=1) == []

    async def test_only_success_removes_a_job(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        await queue.publish(job(tenant), priority=Priority.STANDARD)

        [message] = await queue.receive(max_messages=1)
        await queue.ack(message)

        depth = await queue.depth()
        assert depth.total == 0
        assert depth.dead_lettered == 0

    async def test_publishing_the_same_job_twice_is_one_unit_of_work(self) -> None:
        """At-least-once delivery means this happens, not that it might."""
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        envelope = job(tenant)

        await queue.publish(envelope, priority=Priority.STANDARD)
        await queue.publish(envelope, priority=Priority.STANDARD)

        depth = await queue.depth()
        assert depth.per_tenant[tenant] == 1


class TestTheDeadLetterQueueIsReadable:
    """ "Warning on any dead letter, page above five in an hour" has to be a
    question the queue can answer, not a graph somebody has to eyeball."""

    async def test_health_counts_what_the_alert_thresholds_ask_about(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        for _ in range(3):
            await queue.publish(job(tenant), priority=Priority.STANDARD)

        for message in await queue.receive(max_messages=3):
            await queue.dead_letter(message, reason="DeliveryNotFoundError: no such delivery")

        health = await queue.dead_letter_health()

        assert health.total == 3
        assert health.recent == 3
        assert health.paging is False  # three is a warning, not a page
        assert health.by_job_type == {"pipeline.understand": 3}
        assert health.by_category == {"DeliveryNotFoundError": 3}
        assert (await queue.depth()).dead_lettered == 3

    async def test_the_age_of_the_oldest_dead_letter_is_answerable(self) -> None:
        """Without it, a burst that has been sitting for a week is
        indistinguishable from one that started five minutes ago."""
        queue = PostgresJobQueue(worker_id="w1")
        await queue.publish(job(uuid.uuid4()), priority=Priority.STANDARD)

        [message] = await queue.receive(max_messages=1)
        await queue.dead_letter(message, reason="TimeoutError: upstream")

        health = await queue.dead_letter_health()

        assert health.oldest_age_seconds is not None
        assert 0 <= health.oldest_age_seconds < 60

    async def test_an_empty_dlq_reports_no_age_rather_than_zero(self) -> None:
        # Zero would read as "a dead letter arrived this instant".
        health = await PostgresJobQueue(worker_id="w1").dead_letter_health()

        assert (health.total, health.recent) == (0, 0)
        assert health.oldest_age_seconds is None

    async def test_the_stored_reason_keeps_its_full_text(self) -> None:
        """The durable row is where an investigation starts; the bounded
        category is only what leaves the building."""
        queue = PostgresJobQueue(worker_id="w1")
        await queue.publish(job(uuid.uuid4()), priority=Priority.STANDARD)
        reason = "ValueError: could not parse 'Priya shipped the payments migration'"

        [message] = await queue.receive(max_messages=1)
        await queue.dead_letter(message, reason=reason)

        async with platform_session() as session:
            stored = await session.scalar(
                text("SELECT dead_reason FROM scheduled_jobs WHERE state = 'dead'")
            )

        assert stored == reason
        assert (await queue.dead_letter_health()).by_category == {"ValueError": 1}


class TestTheCorrelationIdIsDurable:
    """The database is the second place `traceparent` cannot help: it is not
    stored, so without this there is nothing in the row tying a job to the
    webhook that caused it."""

    async def test_it_survives_publish_and_receive(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        published = job(uuid.uuid4())

        await queue.publish(published, priority=Priority.STANDARD)
        [message] = await queue.receive(max_messages=1)

        assert message.envelope.correlation_id == published.correlation_id

    async def test_a_retried_job_keeps_it(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        published = job(uuid.uuid4())
        await queue.publish(published, priority=Priority.STANDARD)

        [message] = await queue.receive(max_messages=1)
        await queue.retry(message, delay_seconds=0)
        [again] = await queue.receive(max_messages=1)

        assert again.envelope.attempt == 2
        assert again.envelope.correlation_id == published.correlation_id

    async def test_the_handler_s_payload_does_not_see_it(self) -> None:
        """It rides in the payload column for want of a column of its own; a
        handler must never find it among its own keys."""
        queue = PostgresJobQueue(worker_id="w1")
        envelope = JobEnvelope(
            job_type="pipeline.understand",
            tenant_id=uuid.uuid4(),
            payload={"delivery_id": "d-1"},
        )

        await queue.publish(envelope, priority=Priority.STANDARD)
        [message] = await queue.receive(max_messages=1)

        assert message.envelope.payload == {"delivery_id": "d-1"}

    async def test_a_row_written_without_one_still_runs(self) -> None:
        """A rolling deploy leaves rows from the previous revision. They must
        run — with a fresh id — rather than fail to parse."""
        tenant = uuid.uuid4()
        job_id = uuid.uuid4()
        async with platform_session() as session:
            await session.execute(
                text("""
                    INSERT INTO scheduled_jobs (job_id, tenant_id, job_type, priority, payload)
                    VALUES (:job_id, :tenant_id, 'pipeline.understand', 20, '{}'::jsonb)
                """),
                {"job_id": str(job_id), "tenant_id": str(tenant)},
            )
            await session.commit()

        [message] = await PostgresJobQueue(worker_id="w1").receive(max_messages=1)

        assert message.envelope.job_id == job_id
        assert len(message.envelope.correlation_id) == 32

    async def test_an_id_stored_by_something_other_than_the_queue_is_discarded(self) -> None:
        """The payload column is storage, not truth. A "correlation id" that
        arrived by another route must not reach a span."""
        tenant = uuid.uuid4()
        async with platform_session() as session:
            await session.execute(
                text("""
                    INSERT INTO scheduled_jobs (job_id, tenant_id, job_type, priority, payload)
                    VALUES (
                        :job_id, :tenant_id, 'pipeline.understand', 20,
                        CAST(:payload AS jsonb)
                    )
                """),
                {
                    "job_id": str(uuid.uuid4()),
                    "tenant_id": str(tenant),
                    "payload": (
                        '{"__cairn_correlation_id": "Priya shipped the payments migration"}'
                    ),
                },
            )
            await session.commit()

        [message] = await PostgresJobQueue(worker_id="w1").receive(max_messages=1)

        assert "Priya" not in message.envelope.correlation_id
        assert len(message.envelope.correlation_id) == 32


class TestOperatorsCanSeeStarvation:
    async def test_depth_separates_waiting_from_working(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        tenant = uuid.uuid4()
        for _ in range(6):
            await queue.publish(job(tenant), priority=Priority.STANDARD)

        await queue.receive(max_messages=MAX_ACTIVE_PER_TENANT)
        depth = await queue.depth()

        assert depth.in_flight == MAX_ACTIVE_PER_TENANT
        assert depth.pending == 6 - MAX_ACTIVE_PER_TENANT

    async def test_fairness_reports_who_has_waited_longest(
        self, platform_engine: AsyncEngine
    ) -> None:
        """Starvation is visible before a customer reports it, or it is not
        visible at all."""
        queue = PostgresJobQueue(worker_id="w1")
        waiting, recent = uuid.uuid4(), uuid.uuid4()
        await queue.publish(job(waiting), priority=Priority.STANDARD)

        async with platform_engine.begin() as conn:
            await conn.execute(
                text("UPDATE scheduled_jobs SET enqueued_at = now() - interval '2 hours'")
            )
        await queue.publish(job(recent), priority=Priority.STANDARD)

        fairness = await queue.fairness()

        assert fairness.tenants_waiting == 2
        assert fairness.starving

    async def test_an_evenly_served_queue_does_not_read_as_starving(self) -> None:
        queue = PostgresJobQueue(worker_id="w1")
        for _ in range(3):
            await queue.publish(job(uuid.uuid4()), priority=Priority.STANDARD)

        assert not (await queue.fairness()).starving


class TestTheSchedulerIsReachable:
    def test_the_factory_builds_it(self) -> None:
        """A backend production cannot select is a backend that does not exist."""
        from cairn_api.config import Settings
        from cairn_api.jobs.factory import build_queue

        built = build_queue(Settings(queue_backend="postgres"))

        assert isinstance(built, PostgresJobQueue)
