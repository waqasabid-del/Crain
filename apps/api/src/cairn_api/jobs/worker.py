"""The worker loop: pulls messages, runs them through `run_job`, and is the
only place that decides between ack, retry and dead-letter, so the three
outcomes can't diverge across job types. Every message ends in exactly one
of them — one left neither acked nor retried sits in flight until its
deadline, then redelivers forever. Concurrency is bounded per worker so one
poll can't exhaust the database pool sized for steady state (`db/session.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict, dataclass

import structlog

from cairn_api.jobs.queue import JobQueue, QueueMessage
from cairn_api.jobs.retry import DEFAULT_RETRY_POLICY, RetryPolicy
from cairn_api.jobs.runner import JobRegistry, UnknownJobTypeError, run_job

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Tuning for one worker process."""

    #: Too large and a slow batch holds messages past their ack deadline.
    batch_size: int = 10

    #: Deliberately below the database pool size.
    concurrency: int = 4

    idle_poll_seconds: float = 0.5

    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            msg = "batch_size must be at least 1"
            raise ValueError(msg)
        if self.concurrency < 1:
            msg = "concurrency must be at least 1"
            raise ValueError(msg)


@dataclass(slots=True)
class WorkerStats:
    """Read by tests and by `/readyz`."""

    processed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0


class Worker:
    """Consumes a queue until asked to stop."""

    def __init__(
        self,
        queue: JobQueue,
        *,
        config: WorkerConfig | None = None,
        job_registry: JobRegistry | None = None,
    ) -> None:
        self._queue = queue
        self._config = config or WorkerConfig()
        self._registry = job_registry
        self._stop = asyncio.Event()
        self._semaphore = asyncio.Semaphore(self._config.concurrency)
        self.stats = WorkerStats()

    async def run_forever(self) -> None:
        """Drains rather than cancels in-flight work on shutdown — Cloud Run
        sends SIGTERM and waits; cancelling would burst-redeliver every deploy.
        """
        await logger.ainfo(
            "worker.started",
            batch_size=self._config.batch_size,
            concurrency=self._config.concurrency,
        )
        running: set[asyncio.Task[None]] = set()

        try:
            while not self._stop.is_set():
                processed = await self._poll_once(running)
                if processed == 0:
                    # wait_for the stop event so shutdown doesn't wait out
                    # the poll interval.
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._stop.wait(), timeout=self._config.idle_poll_seconds
                        )
        finally:
            if running:
                await logger.ainfo("worker.draining", in_flight=len(running))
                await asyncio.gather(*running, return_exceptions=True)
            await logger.ainfo("worker.stopped", **asdict(self.stats))

    async def run_once(self) -> int:
        """Process one batch; the entry point tests use."""
        running: set[asyncio.Task[None]] = set()
        count = await self._poll_once(running)
        if running:
            await asyncio.gather(*running)
        return count

    def stop(self) -> None:
        """Ask the loop to finish the current batch and exit."""
        self._stop.set()

    async def _poll_once(self, running: set[asyncio.Task[None]]) -> int:
        messages = await self._queue.receive(max_messages=self._config.batch_size)
        if not messages:
            return 0

        for message in messages:
            task = asyncio.create_task(self._handle_with_limit(message))
            running.add(task)
            task.add_done_callback(running.discard)

        return len(messages)

    async def _handle_with_limit(self, message: QueueMessage) -> None:
        async with self._semaphore:
            await self._handle(message)

    async def _handle(self, message: QueueMessage) -> None:
        """Run one job; every path acknowledges, retries or dead-letters."""
        envelope = message.envelope
        self.stats.processed += 1

        structlog.contextvars.bind_contextvars(
            job_id=str(envelope.job_id),
            job_type=envelope.job_type,
            tenant_id=str(envelope.tenant_id),
            attempt=envelope.attempt,
        )
        try:
            await run_job(envelope, job_registry=self._registry)
        except UnknownJobTypeError as exc:
            await self._queue.dead_letter(message, reason=f"unknown job type: {exc}")
            self.stats.dead_lettered += 1
        except Exception as exc:
            await self._on_failure(message, exc)
        else:
            await self._queue.ack(message)
            self.stats.succeeded += 1
            await logger.ainfo("job.succeeded")
        finally:
            structlog.contextvars.unbind_contextvars("job_id", "job_type", "tenant_id", "attempt")

    async def _on_failure(self, message: QueueMessage, exc: Exception) -> None:
        """Retry or dead-letter a job whose handler raised."""
        policy = self._config.retry_policy
        envelope = message.envelope

        if not policy.should_retry(envelope.attempt):
            await self._queue.dead_letter(message, reason=f"{type(exc).__name__}: {exc}")
            self.stats.dead_lettered += 1
            await logger.aexception("job.exhausted_retries", exc_info=exc)
            return

        delay = policy.delay_for(envelope.attempt)
        await self._queue.retry(message, delay_seconds=delay)
        self.stats.retried += 1
        await logger.awarning(
            "job.failed_will_retry",
            error=str(exc),
            error_type=type(exc).__name__,
            retry_in_seconds=round(delay, 2),
            attempts_remaining=policy.max_attempts - envelope.attempt,
        )
