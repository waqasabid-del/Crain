"""Broker selection and the worker's background loops.

The guard in `build_queue` is the kind of control this project's audit kept
finding: verified once by hand, then never again. An in-memory broker in a
deployed environment would accept work, hold it in RAM and lose all of it on the
next deploy — with no error anywhere, because a message that was published and
never processed looks exactly like one still queued.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from cairn_api.config import Settings
from cairn_api.jobs.factory import QueueConfigurationError, build_queue
from cairn_api.jobs.main import report_depth
from cairn_api.jobs.memory import InMemoryJobQueue
from cairn_api.jobs.queue import QueueDepth

REMOTE_URL = "postgresql+asyncpg://cairn:injected-secret@10.0.0.4:5432/cairn"
SECURE_ORIGIN = "https://app.example.com"


def deployed_settings(**overrides: object) -> Settings:
    """Settings that pass every production guard except the one under test."""
    values: dict[str, object] = {
        "environment": "production",
        "database_url": REMOTE_URL,
        "platform_database_url": REMOTE_URL,
        "cors_allowed_origins": (SECURE_ORIGIN,),
        # Required outside local development: the webhook endpoint is
        # unauthenticated, so a blank secret makes it an open write path.
        "github_webhook_secret": "a-real-secret",
        # Also required outside local development: the console backend writes
        # invitations to the log, where nobody invited will ever read them.
        "email_backend": "smtp",
        "smtp_host": "relay.example.com",
    }
    values.update(overrides)
    return Settings.model_validate(values)


class TestBrokerSelection:
    def test_local_development_gets_the_in_memory_broker(self) -> None:
        queue = build_queue(Settings(environment="local"))

        assert isinstance(queue, InMemoryJobQueue)

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_a_deployed_environment_refuses_the_in_memory_broker(self, environment: str) -> None:
        # The failure this prevents is silent: work accepted, held in RAM, and
        # gone on the next deploy, with nothing logged and nothing to see.
        with pytest.raises(QueueConfigurationError, match="loses every one of them"):
            build_queue(deployed_settings(environment=environment, queue_backend="memory"))

    def test_pubsub_without_a_project_is_refused(self) -> None:
        # The client library would otherwise infer a project from ambient
        # credentials, which is how a staging worker ends up consuming
        # production's queue — a failure with no error and real consequences.
        with pytest.raises(QueueConfigurationError, match="CAIRN_GCP_PROJECT_ID"):
            build_queue(deployed_settings(queue_backend="pubsub", gcp_project_id=None))

    def test_pubsub_is_refused_in_a_deployed_environment(self) -> None:
        # Durable, but it cannot enforce per-tenant fairness and emits no retry
        # or dead-letter metrics — so one workspace's backfill can occupy every
        # worker, and the DLQ alert has nothing to fire on. Both losses are
        # silent in a way that surfaces first as a customer complaint.
        with pytest.raises(QueueConfigurationError, match="per-tenant fairness"):
            build_queue(deployed_settings(queue_backend="pubsub", gcp_project_id="cairn-prod"))

    def test_pubsub_with_a_project_is_constructed_when_the_trade_is_accepted(self) -> None:
        # The positive control. Without it, the tests above would pass against a
        # factory that refused every configuration and nothing could be deployed
        # at all. `queue_fairness_optional` is what turns the refusal into a
        # recorded decision rather than a wall.
        queue = build_queue(
            deployed_settings(
                queue_backend="pubsub",
                gcp_project_id="cairn-prod",
                queue_fairness_optional=True,
            )
        )

        assert type(queue).__name__ == "PubSubJobQueue"

    def test_a_deployed_environment_can_use_the_scheduler(self) -> None:
        """The backend that enforces Step 30's fairness must be selectable.

        It is also the one the in-memory refusal now points operators at, so a
        runbook that follows that message has to arrive somewhere that works.
        """
        queue = build_queue(deployed_settings(queue_backend="postgres"))

        assert type(queue).__name__ == "PostgresJobQueue"

    def test_the_in_memory_refusal_names_the_backend_with_fairness(self) -> None:
        """It used to say "set pubsub", which is durable and *not* fair.

        An operator following that message deployed a queue where one tenant's
        backfill can occupy every worker — the exact failure Step 30 exists to
        prevent, reached by doing what the error told them to do.
        """
        with pytest.raises(QueueConfigurationError, match="CAIRN_QUEUE_BACKEND=postgres"):
            build_queue(deployed_settings(queue_backend="memory"))


class _StubQueue:
    """A queue that reports a fixed depth, or fails.

    Signals an event once it has been called enough times, so tests can wait for
    a *condition* rather than for a duration. An earlier version slept for a
    fixed 0.07s and asserted three calls at a 0.02s interval — which passed
    alone and failed in the full suite, because a loaded event loop does not
    schedule a timer as often as arithmetic suggests. A test that depends on
    scheduler timing is a test that fails in CI for reasons unrelated to the
    code.
    """

    def __init__(self, depth: QueueDepth | None = None, *, signal_after: int = 3) -> None:
        self._depth = depth
        self._signal_after = signal_after
        self.calls = 0
        self.reached = asyncio.Event()

    async def depth(self) -> QueueDepth:
        self.calls += 1
        if self.calls >= self._signal_after:
            self.reached.set()
        if self._depth is None:
            msg = "monitoring unavailable"
            raise RuntimeError(msg)
        return self._depth


class TestDepthReporting:
    async def test_depth_is_emitted_on_a_schedule(self) -> None:
        # Depth is the primary backpressure signal and what workers autoscale
        # on, so it has to be emitted on a timer rather than only when something
        # happens — a queue that stops being consumed would otherwise stop
        # producing the metric that says so.
        queue = _StubQueue(QueueDepth(pending=7, in_flight=2, dead_lettered=0))

        task = asyncio.create_task(report_depth(queue, interval=0.01))  # type: ignore[arg-type]
        # Wait for the condition, with a generous ceiling. The timeout is a
        # deadlock guard, not the thing being measured.
        await asyncio.wait_for(queue.reached.wait(), timeout=5)
        task.cancel()

        assert queue.calls >= 3

    async def test_a_metrics_failure_does_not_kill_the_worker(self) -> None:
        # Observability must never be load-bearing. A worker that dies because
        # it could not report its backlog has turned a monitoring outage into a
        # processing outage.
        queue = _StubQueue(depth=None)

        task = asyncio.create_task(report_depth(queue, interval=0.01))  # type: ignore[arg-type]
        await asyncio.wait_for(queue.reached.wait(), timeout=5)
        still_running = not task.done()
        task.cancel()

        # Kept polling through three consecutive failures rather than dying on
        # the first — observability must never be load-bearing.
        assert still_running
        assert queue.calls >= 3


class TestPerTenantDepth:
    async def test_the_breakdown_identifies_the_heavy_tenant(self) -> None:
        """The noisy-neighbour diagnostic.

        A single total answers "are we keeping up". Only the breakdown answers
        "is one customer starving the rest", and only the second is an isolation
        failure (md/06 §6B.3) — which otherwise reaches us as "CAIRN is slow"
        from everyone except the customer causing it.
        """
        queue = InMemoryJobQueue()
        heavy, quiet = uuid.uuid4(), uuid.uuid4()

        from cairn_api.jobs.envelope import JobEnvelope

        for _ in range(20):
            await queue.publish(JobEnvelope(job_type="backfill", tenant_id=heavy))
        await queue.publish(JobEnvelope(job_type="webhook", tenant_id=quiet))

        depth = await queue.depth()

        assert depth.per_tenant[heavy] == 20
        assert depth.per_tenant[quiet] == 1
        assert depth.total == 21
