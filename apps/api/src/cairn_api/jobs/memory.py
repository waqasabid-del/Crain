"""An in-process broker backing local dev and the whole test suite. Not a
toy: implements delayed delivery, ack deadlines, redelivery, dead lettering
and fair scheduling, so the worker isn't written against semantics no real
broker provides. Ordering here is deterministic within a priority band
(Pub/Sub gives none without ordering keys); nothing survives the process,
which is why it's never the production broker. Fair scheduling is real
here since Pub/Sub has none of its own (md/06 §6B.3).
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field

import structlog

from cairn_api import telemetry
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import Priority, QueueDepth, QueueMessage

logger = structlog.get_logger(__name__)

#: Mirrors a Pub/Sub subscription's ack deadline.
DEFAULT_ACK_DEADLINE_SECONDS = 60.0


@dataclass(order=True)
class _Queued:
    """Ordered by (descending priority, earliest visible, sequence) so the
    natural sort is the scheduling decision.
    """

    sort_priority: int
    visible_at: float
    sequence: int
    envelope: JobEnvelope = field(compare=False)
    priority: Priority = field(compare=False, default=Priority.STANDARD)


@dataclass(slots=True)
class _InFlight:
    message: QueueMessage
    deadline: float


@dataclass(frozen=True, slots=True)
class DeadLetter:
    envelope: JobEnvelope
    reason: str
    failed_at: float


class InMemoryJobQueue:
    def __init__(
        self,
        *,
        ack_deadline_seconds: float = DEFAULT_ACK_DEADLINE_SECONDS,
        fair_scheduling: bool = True,
    ) -> None:
        self._pending: list[_Queued] = []
        self._in_flight: dict[str, _InFlight] = {}
        self._dead: list[DeadLetter] = []
        self._sequence = itertools.count()
        self._receipts = itertools.count()
        self._ack_deadline = ack_deadline_seconds
        self._fair_scheduling = fair_scheduling
        self._lock = asyncio.Lock()  # Guards concurrent pollers from double-taking a message.
        self._last_tenant: uuid.UUID | None = None

    async def publish(
        self,
        envelope: JobEnvelope,
        *,
        priority: Priority = Priority.STANDARD,
        delay_seconds: float = 0.0,
    ) -> None:
        async with self._lock:
            self._pending.append(
                _Queued(
                    sort_priority=-int(priority),
                    visible_at=time.monotonic() + max(delay_seconds, 0.0),
                    sequence=next(self._sequence),
                    envelope=envelope,
                    priority=priority,
                )
            )
        telemetry.record_queue_event(
            job_type=envelope.job_type, outcome="published", priority=priority.name.lower()
        )

    async def receive(self, *, max_messages: int = 1) -> list[QueueMessage]:
        async with self._lock:
            self._requeue_expired_locked()

            now = time.monotonic()
            available = [item for item in self._pending if item.visible_at <= now]
            if not available:
                return []

            available.sort()
            chosen = (
                self._choose_fairly(available, max_messages)
                if self._fair_scheduling
                else available[:max_messages]
            )

            messages: list[QueueMessage] = []
            for item in chosen:
                self._pending.remove(item)
                receipt = str(next(self._receipts))
                message = QueueMessage(
                    envelope=item.envelope,
                    receipt=receipt,
                    priority=item.priority,
                    delivery_attempt=item.envelope.attempt,
                )
                self._in_flight[receipt] = _InFlight(
                    message=message, deadline=now + self._ack_deadline
                )
                messages.append(message)

        # Outside the lock: telemetry must never be on the critical path of the
        # thing it describes.
        for message in messages:
            telemetry.record_queue_event(
                job_type=message.envelope.job_type,
                outcome="claimed",
                priority=message.priority.name.lower(),
            )
        return messages

    def _choose_fairly(self, available: list[_Queued], limit: int) -> list[_Queued]:
        """Round-robin within the highest priority band that has work, one
        message per tenant per turn (md/06 §6B.3).
        """
        chosen: list[_Queued] = []

        # Must fill the rest of the batch after the top band, not stop
        # there — an earlier version did, collapsing throughput to one job
        # per poll whenever a single interactive job was queued.
        for priority in sorted({item.sort_priority for item in available}):
            if len(chosen) >= limit:
                break
            band = [item for item in available if item.sort_priority == priority]
            chosen.extend(self._round_robin(band, limit - len(chosen)))

        return chosen

    def _round_robin(self, band: list[_Queued], limit: int) -> list[_Queued]:
        by_tenant: dict[uuid.UUID, deque[_Queued]] = defaultdict(deque)
        for item in band:
            by_tenant[item.envelope.tenant_id].append(item)

        # Resume after whoever was served last rather than restarting at the same tenant.
        tenants = sorted(by_tenant, key=lambda t: (by_tenant[t][0].sequence, t.bytes))
        if self._last_tenant in tenants:
            start = tenants.index(self._last_tenant) + 1
            tenants = tenants[start:] + tenants[:start]

        taken: list[_Queued] = []
        while len(taken) < limit and any(by_tenant.values()):
            for tenant in tenants:
                if len(taken) >= limit:
                    break
                queue = by_tenant[tenant]
                if queue:
                    taken.append(queue.popleft())
                    self._last_tenant = tenant

        return taken

    async def ack(self, message: QueueMessage) -> None:
        async with self._lock:
            self._in_flight.pop(message.receipt, None)
        telemetry.record_queue_event(job_type=message.envelope.job_type, outcome="acked")

    async def retry(self, message: QueueMessage, *, delay_seconds: float) -> None:
        telemetry.record_queue_event(job_type=message.envelope.job_type, outcome="retried")
        async with self._lock:
            self._in_flight.pop(message.receipt, None)
            # New envelope with an incremented attempt — the envelope is frozen.
            self._pending.append(
                _Queued(
                    sort_priority=-int(message.priority),
                    visible_at=time.monotonic() + max(delay_seconds, 0.0),
                    sequence=next(self._sequence),
                    envelope=message.envelope.next_attempt(),
                    priority=message.priority,
                )
            )

    async def dead_letter(self, message: QueueMessage, *, reason: str) -> None:
        telemetry.record_queue_event(job_type=message.envelope.job_type, outcome="dead_lettered")
        # The dedicated counter as well as the general one: the general counter
        # is where dead letters are invisible among publishes and acks, and this
        # is the series an operator alerts on.
        telemetry.record_dead_letter(
            job_type=message.envelope.job_type,
            reason=reason,
            priority=message.priority.name.lower(),
        )
        async with self._lock:
            self._in_flight.pop(message.receipt, None)
            self._dead.append(
                DeadLetter(
                    envelope=message.envelope,
                    reason=reason,
                    failed_at=time.monotonic(),
                )
            )
        # ERROR with the category as its own field: the reason is kept in full
        # here (the log store is where an investigation starts) while the
        # category is what a log-based alert and the metric agree on.
        await logger.aerror(
            "job.dead_lettered",
            job_id=str(message.envelope.job_id),
            job_type=message.envelope.job_type,
            tenant_id=str(message.envelope.tenant_id),
            correlation_id=message.envelope.correlation_id,
            attempts=message.envelope.attempt,
            error_category=telemetry.dead_letter_category(reason),
            reason=reason,
        )

    async def depth(self) -> QueueDepth:
        async with self._lock:
            self._requeue_expired_locked()

            per_tenant: dict[uuid.UUID, int] = defaultdict(int)
            for item in self._pending:
                per_tenant[item.envelope.tenant_id] += 1

            return QueueDepth(
                pending=len(self._pending),
                in_flight=len(self._in_flight),
                dead_lettered=len(self._dead),
                per_tenant=dict(per_tenant),
            )

    def dead_letters(self) -> list[DeadLetter]:
        """Not part of `JobQueue`: reading a Pub/Sub dead-letter topic means subscribing to it."""
        return list(self._dead)

    def _requeue_expired_locked(self) -> None:
        """What makes at-least-once delivery real for a worker killed
        mid-job. Attempt count is *not* incremented — a crash isn't an
        attempt the job made, and counting it would burn its retry budget.
        """
        now = time.monotonic()
        expired = [receipt for receipt, entry in self._in_flight.items() if entry.deadline <= now]
        for receipt in expired:
            entry = self._in_flight.pop(receipt)
            self._pending.append(
                _Queued(
                    sort_priority=-int(entry.message.priority),
                    visible_at=now,
                    sequence=next(self._sequence),
                    envelope=entry.message.envelope,
                    priority=entry.message.priority,
                )
            )
            logger.warning(
                "job.redelivered_after_deadline",
                job_id=str(entry.message.envelope.job_id),
                tenant_id=str(entry.message.envelope.tenant_id),
            )
