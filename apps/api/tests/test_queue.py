"""Queue infrastructure: retry, dead-lettering, fairness and backlog visibility.

Step 10's exit criterion is *a failing job retries then lands in DLQ; queue
depth is observable*. `TestRetryToDeadLetter` is that criterion, asserted end to
end through a real worker against a real broker.

The rest guard the properties that are cheap now and expensive to retrofit:
at-least-once redelivery after a crash, priority so backfill cannot delay live
events, and per-tenant fairness so one heavy customer cannot starve the others.
"""

from __future__ import annotations

import asyncio
import random
import uuid

import pytest
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.memory import InMemoryJobQueue
from cairn_api.jobs.queue import Priority, QueueMessage
from cairn_api.jobs.retry import DEFAULT_RETRY_POLICY, RetryPolicy
from cairn_api.jobs.runner import JobRegistry
from cairn_api.jobs.worker import Worker, WorkerConfig

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def envelope(job_type: str = "test.job", *, tenant: uuid.UUID = TENANT_A) -> JobEnvelope:
    return JobEnvelope(job_type=job_type, tenant_id=tenant)


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def registry() -> JobRegistry:
    """A registry per test.

    The process-wide one would carry handlers between tests and make failures
    depend on execution order — the hardest kind to diagnose.
    """
    return JobRegistry()


def worker_for(
    queue: InMemoryJobQueue,
    registry: JobRegistry,
    *,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    batch_size: int = 10,
) -> Worker:
    return Worker(
        queue,
        config=WorkerConfig(
            batch_size=batch_size,
            # Zero retry delay in most tests: the backoff schedule is asserted
            # directly in `TestRetryPolicy`, and sleeping through a real one
            # here would add a minute to the suite to re-test arithmetic.
            retry_policy=retry_policy,
        ),
        job_registry=registry,
    )


class TestRetryPolicy:
    """The schedule, asserted as a value rather than by waiting for it."""

    def test_delays_grow_exponentially(self) -> None:
        # A constant delay against a dependency that is down is just a slower
        # flood — the retries become the load preventing recovery.
        policy = RetryPolicy(base_delay_seconds=1, jitter_ratio=0)

        assert [policy.delay_for(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 8]

    def test_delays_are_capped(self) -> None:
        # Unbounded doubling reaches delays measured in days, and a job that
        # retries next Thursday is a job nobody notices has failed.
        policy = RetryPolicy(base_delay_seconds=1, max_delay_seconds=5, jitter_ratio=0)

        assert policy.delay_for(10) == 5

    def test_jitter_spreads_a_synchronised_burst(self) -> None:
        # Without jitter, a thousand jobs that failed together retry together
        # forever, hitting the recovering dependency in lockstep at every
        # doubling.
        policy = RetryPolicy(base_delay_seconds=10, jitter_ratio=0.25)
        rng = random.Random(1234)  # noqa: S311 — jitter, not a secret

        delays = {policy.delay_for(1, rng=rng) for _ in range(50)}

        assert len(delays) > 1
        assert all(7.5 <= d <= 12.5 for d in delays)

    def test_a_delay_is_never_negative(self) -> None:
        # `asyncio.sleep` silently accepts a negative value, so a sign error
        # here would present as "retries are instant" rather than as an error.
        policy = RetryPolicy(base_delay_seconds=1, jitter_ratio=0.99)
        rng = random.Random(7)  # noqa: S311 — jitter, not a secret

        assert all(policy.delay_for(1, rng=rng) >= 0 for _ in range(200))

    def test_retries_stop_at_the_limit(self) -> None:
        policy = RetryPolicy(max_attempts=3)

        assert [policy.should_retry(n) for n in (1, 2, 3, 4)] == [True, True, False, False]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_attempts": 0},
            {"base_delay_seconds": 0},
            {"base_delay_seconds": 10, "max_delay_seconds": 1},
            {"jitter_ratio": 1.0},
        ],
    )
    def test_a_nonsensical_policy_is_refused_at_construction(
        self, kwargs: dict[str, float]
    ) -> None:
        # These are configuration mistakes that should fail at import rather
        # than produce a queue that retries forever or not at all.
        with pytest.raises(ValueError, match=r"must be|cannot be"):
            RetryPolicy(**kwargs)  # type: ignore[arg-type]


class TestRetryToDeadLetter:
    """Step 10's exit criterion."""

    async def test_a_failing_job_retries_then_dead_letters(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        attempts: list[int] = []

        @registry.register("always.fails")
        async def _handler(_session: object, env: JobEnvelope) -> None:
            attempts.append(env.attempt)
            msg = "dependency unavailable"
            raise RuntimeError(msg)

        policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.01, jitter_ratio=0)
        worker = worker_for(queue, registry, retry_policy=policy)
        await queue.publish(envelope("always.fails"))

        # Each pass processes whatever is visible; the sleep covers the backoff
        # delay so the retry becomes visible for the next pass.
        for _ in range(5):
            await worker.run_once()
            await asyncio.sleep(0.03)

        assert attempts == [1, 2, 3]  # tried exactly max_attempts times
        assert worker.stats.retried == 2
        assert worker.stats.dead_lettered == 1

        dead = queue.dead_letters()
        assert len(dead) == 1
        # The reason travels with it. A dead-letter entry saying only "failed"
        # starts a debugging session from nothing.
        assert "dependency unavailable" in dead[0].reason
        assert dead[0].envelope.attempt == 3

    async def test_a_dead_lettered_job_stops_blocking_the_queue(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        # The point of a dead-letter queue: one unprocessable message must move
        # aside rather than stall the stream behind it (md/06 §6B.2).
        succeeded: list[str] = []

        @registry.register("poison")
        async def _poison(_session: object, _env: JobEnvelope) -> None:
            raise ValueError("unparseable payload")

        @registry.register("healthy")
        async def _healthy(_session: object, env: JobEnvelope) -> None:
            succeeded.append(env.job_type)

        policy = RetryPolicy(max_attempts=1, base_delay_seconds=0.01, jitter_ratio=0)
        worker = worker_for(queue, registry, retry_policy=policy)

        await queue.publish(envelope("poison"))
        await queue.publish(envelope("healthy"))
        await worker.run_once()

        assert succeeded == ["healthy"]
        assert (await queue.depth()).pending == 0

    async def test_an_unknown_job_type_dead_letters_without_retrying(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        # Not transient: no amount of waiting registers a handler. Retrying
        # five times would only delay the alert and add four useless log lines.
        worker = worker_for(queue, registry)
        await queue.publish(envelope("nobody.handles.this"))

        await worker.run_once()

        assert worker.stats.retried == 0
        assert worker.stats.dead_lettered == 1
        # Formatted `Type: message` like every other dead letter, so the
        # category the DLQ metric is labelled with is derived the same way.
        assert queue.dead_letters()[0].reason.startswith("UnknownJobTypeError:")

    async def test_a_job_that_recovers_is_acknowledged_not_dead_lettered(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        # The positive control. Without it, every test above would still pass
        # against a worker that dead-letters everything.
        calls: list[int] = []

        @registry.register("flaky")
        async def _handler(_session: object, env: JobEnvelope) -> None:
            calls.append(env.attempt)
            if env.attempt < 2:
                msg = "transient"
                raise ConnectionError(msg)

        policy = RetryPolicy(max_attempts=5, base_delay_seconds=0.01, jitter_ratio=0)
        worker = worker_for(queue, registry, retry_policy=policy)
        await queue.publish(envelope("flaky"))

        for _ in range(3):
            await worker.run_once()
            await asyncio.sleep(0.03)

        assert calls == [1, 2]
        assert worker.stats.succeeded == 1
        assert queue.dead_letters() == []


class TestTheDeadLetterQueueRaisesItsOwnAlarm:
    """A job that fails permanently used to disappear quietly.

    The counter is asserted through a real worker and a real broker, so it fails
    if the wiring is removed rather than only if the helper is renamed.
    """

    @pytest.fixture
    def dead_letter_metric(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
        from cairn_api import telemetry

        captured: list[dict[str, object]] = []

        class Recorder:
            def add(self, amount: int, attributes: dict[str, object] | None = None) -> None:
                captured.append(dict(attributes or {}))

        monkeypatch.setattr(telemetry.spans, "dead_letters", Recorder())
        return captured

    async def test_exhausting_retries_increments_the_dedicated_counter(
        self,
        queue: InMemoryJobQueue,
        registry: JobRegistry,
        dead_letter_metric: list[dict[str, object]],
    ) -> None:
        @registry.register("always.fails")
        async def _handler(_session: object, _env: JobEnvelope) -> None:
            msg = "could not read the row for Priya"
            raise ConnectionError(msg)

        policy = RetryPolicy(max_attempts=1, base_delay_seconds=0.01, jitter_ratio=0)
        worker = worker_for(queue, registry, retry_policy=policy)
        await queue.publish(envelope("always.fails"))

        await worker.run_once()

        assert worker.stats.dead_lettered == 1
        assert dead_letter_metric == [
            {
                "job_type": "always.fails",
                "error_category": "ConnectionError",
                "priority": "standard",
            }
        ]

    async def test_an_unknown_job_type_is_counted_under_its_own_category(
        self,
        queue: InMemoryJobQueue,
        registry: JobRegistry,
        dead_letter_metric: list[dict[str, object]],
    ) -> None:
        # The other permanent failure, and the one that skips retrying — it
        # must not skip the alert with it.
        worker = worker_for(queue, registry)
        await queue.publish(envelope("nobody.handles.this"))

        await worker.run_once()

        assert [entry["error_category"] for entry in dead_letter_metric] == ["UnknownJobTypeError"]

    async def test_the_full_reason_stays_where_it_is_allowed_to(
        self, queue: InMemoryJobQueue, dead_letter_metric: list[dict[str, object]]
    ) -> None:
        # Two stores with two retention policies: the durable record keeps the
        # text an investigation needs, the exporter gets a category.
        [message] = await _published(queue)
        reason = "ValueError: could not parse 'Priya shipped the payments migration'"

        await queue.dead_letter(message, reason=reason)

        assert queue.dead_letters()[0].reason == reason
        assert "Priya" not in str(dead_letter_metric)


class TestTheCorrelationIdSurvivesTheQueue:
    """One webhook, one greppable name, all the way to the brief.

    `traceparent` is absent whenever no tracer is installed — the default — and
    is stored nowhere. The correlation id is the half that always exists.
    """

    async def test_it_survives_publish_receive_and_the_handler(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        seen: list[str] = []

        @registry.register("carries.the.id")
        async def _handler(_session: object, env: JobEnvelope) -> None:
            seen.append(env.correlation_id)

        published = envelope("carries.the.id")
        await queue.publish(published)
        await worker_for(queue, registry).run_once()

        assert seen == [published.correlation_id]

    async def test_the_worker_binds_it_into_the_log_context(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        """Every line emitted beneath a job carries the id without being handed
        it — which is what makes `grep <correlation_id>` reconstruct the path."""
        import structlog

        bound: list[object] = []

        @registry.register("logs.its.context")
        async def _handler(_session: object, _env: JobEnvelope) -> None:
            bound.append(structlog.contextvars.get_contextvars().get("correlation_id"))

        published = envelope("logs.its.context")
        await queue.publish(published)
        await worker_for(queue, registry).run_once()

        assert bound == [published.correlation_id]

    async def test_a_retried_job_keeps_the_same_id(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        """The whole point. An id that changed on retry would tell an operator
        the second attempt was a different piece of work."""
        seen: list[str] = []

        @registry.register("flaky")
        async def _handler(_session: object, env: JobEnvelope) -> None:
            seen.append(env.correlation_id)
            if env.attempt < 2:
                msg = "transient"
                raise ConnectionError(msg)

        policy = RetryPolicy(max_attempts=5, base_delay_seconds=0.01, jitter_ratio=0)
        worker = worker_for(queue, registry, retry_policy=policy)
        published = envelope("flaky")
        await queue.publish(published)

        for _ in range(3):
            await worker.run_once()
            await asyncio.sleep(0.03)

        assert seen == [published.correlation_id, published.correlation_id]

    async def test_a_dead_letter_carries_it_too(self, queue: InMemoryJobQueue) -> None:
        # The failure is exactly when somebody needs to reconstruct the path.
        [message] = await _published(queue)

        await queue.dead_letter(message, reason="ValueError: no")

        assert queue.dead_letters()[0].envelope.correlation_id == message.envelope.correlation_id

    async def test_a_job_with_no_ambient_id_gets_one(self) -> None:
        """Scheduled and backfill work has no originating request, and must not
        be the case that has no id at all."""
        from cairn_api.telemetry import correlation

        assert correlation.current_correlation_id() is None
        assert correlation.coerce(envelope().correlation_id) is not None

    async def test_work_published_beneath_a_job_inherits_its_id(
        self, queue: InMemoryJobQueue
    ) -> None:
        """A handler that publishes further work continues the same story —
        the delivery job publishing understanding is exactly this."""
        from cairn_api.telemetry import correlation

        origin = envelope()
        with correlation.correlated(origin.correlation_id):
            follow_on = envelope("pipeline.understand")

        assert follow_on.correlation_id == origin.correlation_id


async def _published(queue: InMemoryJobQueue) -> list[QueueMessage]:
    """Publish one job and claim it back."""
    await queue.publish(envelope())
    return await queue.receive(max_messages=1)


class TestDepthObservability:
    """The other half of the exit criterion, and the backpressure signal."""

    async def test_depth_reports_pending_in_flight_and_dead(self, queue: InMemoryJobQueue) -> None:
        for _ in range(3):
            await queue.publish(envelope())

        assert (await queue.depth()).pending == 3

        taken = await queue.receive(max_messages=2)
        depth = await queue.depth()

        # In-flight is counted separately from pending. Collapsing them would
        # make a stuck worker look like an empty queue.
        assert (depth.pending, depth.in_flight) == (1, 2)
        assert depth.total == 3

        await queue.ack(taken[0])
        await queue.dead_letter(taken[1], reason="test")
        depth = await queue.depth()

        assert (depth.pending, depth.in_flight, depth.dead_lettered) == (1, 0, 1)

    async def test_depth_is_broken_down_per_tenant(self, queue: InMemoryJobQueue) -> None:
        # The diagnostic that surfaces noisy-neighbour starvation before
        # customers report it. One tenant holding most of the backlog is
        # invisible in a single total, and presents to everyone else as "CAIRN
        # is slow" with no cause they can point at.
        for _ in range(5):
            await queue.publish(envelope(tenant=TENANT_A))
        await queue.publish(envelope(tenant=TENANT_B))

        depth = await queue.depth()

        assert depth.per_tenant == {TENANT_A: 5, TENANT_B: 1}


class TestDeliverySemantics:
    async def test_a_crashed_worker_has_its_message_redelivered(
        self, registry: JobRegistry
    ) -> None:
        # At-least-once, made real. A worker killed mid-job never acknowledges,
        # and without deadline expiry its message sits in flight forever —
        # work lost silently, which is the failure this module exists to stop.
        queue = InMemoryJobQueue(ack_deadline_seconds=0.05)
        await queue.publish(envelope())

        taken = await queue.receive()
        assert len(taken) == 1
        assert (await queue.depth()).in_flight == 1

        await asyncio.sleep(0.06)  # the worker "crashed" without acking

        redelivered = await queue.receive()
        assert len(redelivered) == 1
        assert redelivered[0].envelope.job_id == taken[0].envelope.job_id

    async def test_a_crash_does_not_consume_the_retry_budget(self) -> None:
        # A crash is not an attempt the job made. Counting it would let a worker
        # crash-looping for unrelated reasons burn every job's budget and
        # dead-letter a queue full of perfectly good work.
        queue = InMemoryJobQueue(ack_deadline_seconds=0.05)
        await queue.publish(envelope())

        await queue.receive()
        await asyncio.sleep(0.06)
        redelivered = await queue.receive()

        assert redelivered[0].envelope.attempt == 1

    async def test_a_retry_increments_the_attempt_count(self, queue: InMemoryJobQueue) -> None:
        await queue.publish(envelope())
        taken = await queue.receive()

        await queue.retry(taken[0], delay_seconds=0)
        again = await queue.receive()

        assert again[0].envelope.attempt == 2
        assert again[0].envelope.job_id == taken[0].envelope.job_id  # stable identity

    async def test_a_delayed_message_is_not_visible_early(self, queue: InMemoryJobQueue) -> None:
        # Without this, a retry redelivers immediately and a failing job becomes
        # a hot loop against whatever it is failing against.
        await queue.publish(envelope(), delay_seconds=0.05)

        assert await queue.receive() == []

        await asyncio.sleep(0.06)

        assert len(await queue.receive()) == 1

    async def test_concurrent_receives_never_hand_out_the_same_message(
        self, queue: InMemoryJobQueue
    ) -> None:
        # Receiving is read-modify-write across the pending list and the
        # in-flight map. Without the lock, two workers polling at once both take
        # the same message — which reads as a mysterious duplicate execution
        # rather than as a race.
        for _ in range(20):
            await queue.publish(envelope())

        batches = await asyncio.gather(*(queue.receive(max_messages=5) for _ in range(8)))

        receipts = [m.receipt for batch in batches for m in batch]
        assert len(receipts) == len(set(receipts))
        assert len(receipts) == 20


class TestScheduling:
    async def test_priority_beats_arrival_order(self, queue: InMemoryJobQueue) -> None:
        # Backfill must never delay live events: a new customer's ninety-day
        # import arriving during another customer's business hours is the
        # concrete failure (md/06 §6B.3).
        await queue.publish(envelope("backfill"), priority=Priority.BULK)
        await queue.publish(envelope("webhook"), priority=Priority.STANDARD)
        await queue.publish(envelope("user.waiting"), priority=Priority.INTERACTIVE)

        order = [m.envelope.job_type for m in await queue.receive(max_messages=3)]

        assert order == ["user.waiting", "webhook", "backfill"]

    async def test_one_heavy_tenant_cannot_starve_a_quiet_one(
        self, queue: InMemoryJobQueue
    ) -> None:
        """Fair scheduling, which is the whole noisy-neighbour defence.

        Strict arrival order means a tenant with a thousand queued jobs is
        served a thousand times before anyone else is served once. At small
        scale this is invisible; it appears exactly when the product starts
        succeeding.
        """
        for _ in range(50):
            await queue.publish(envelope(tenant=TENANT_A))
        await queue.publish(envelope(tenant=TENANT_B))  # arrives last

        first_batch = await queue.receive(max_messages=4)
        tenants = [m.envelope.tenant_id for m in first_batch]

        # The quiet tenant is served in the first batch despite queueing last
        # and holding 2% of the backlog.
        assert TENANT_B in tenants

    async def test_fairness_does_not_override_priority(self, queue: InMemoryJobQueue) -> None:
        # Fairness operates *within* a priority band. If it crossed bands, a
        # quiet tenant's bulk backfill would preempt a busy tenant's live
        # webhook — trading one starvation problem for another.
        await queue.publish(envelope("bulk", tenant=TENANT_B), priority=Priority.BULK)
        for _ in range(3):
            await queue.publish(envelope("live", tenant=TENANT_A))

        types = [m.envelope.job_type for m in await queue.receive(max_messages=3)]

        assert types == ["live", "live", "live"]

    async def test_strict_ordering_is_available_when_fairness_is_off(self) -> None:
        # The positive control for fairness: with it disabled the heavy tenant
        # does monopolise the batch, which is what the test above proves we
        # avoid. Without this, that test could pass by accident.
        queue = InMemoryJobQueue(fair_scheduling=False)
        for _ in range(5):
            await queue.publish(envelope(tenant=TENANT_A))
        await queue.publish(envelope(tenant=TENANT_B))

        tenants = {m.envelope.tenant_id for m in await queue.receive(max_messages=4)}

        assert tenants == {TENANT_A}


class TestWorkerLifecycle:
    async def test_an_empty_queue_is_not_an_error(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        worker = worker_for(queue, registry)

        assert await worker.run_once() == 0

    async def test_shutdown_drains_rather_than_cancelling(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        """Cloud Run sends SIGTERM and waits.

        A worker that cancels in-flight jobs turns every deploy into a burst of
        redeliveries, and any job that is not perfectly idempotent into a
        corruption. Finishing what is in hand costs seconds.
        """
        finished: list[str] = []

        @registry.register("slow")
        async def _handler(_session: object, env: JobEnvelope) -> None:
            await asyncio.sleep(0.05)
            finished.append(str(env.job_id))

        worker = worker_for(queue, registry)
        await queue.publish(envelope("slow"))

        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0.01)  # let the job start
        worker.stop()
        await asyncio.wait_for(task, timeout=2)

        assert len(finished) == 1
        assert worker.stats.succeeded == 1

    async def test_concurrency_is_bounded(
        self, queue: InMemoryJobQueue, registry: JobRegistry
    ) -> None:
        # Unbounded `gather` over a batch opens as many database sessions as the
        # batch size, which is how a connection pool sized for steady state is
        # exhausted by the burst a queue exists to absorb.
        concurrent = 0
        peak = 0

        @registry.register("counted")
        async def _handler(_session: object, _env: JobEnvelope) -> None:
            nonlocal concurrent, peak
            concurrent += 1
            peak = max(peak, concurrent)
            await asyncio.sleep(0.02)
            concurrent -= 1

        worker = Worker(
            queue,
            config=WorkerConfig(batch_size=10, concurrency=3),
            job_registry=registry,
        )
        for _ in range(10):
            await queue.publish(envelope("counted"))

        await worker.run_once()

        assert peak <= 3
        assert worker.stats.succeeded == 10
