"""One protocol, two implementations. At-least-once delivery: `job_id` is
stable and handlers must be idempotent (md/01 §4.1); priority is per-message
so backfill can't delay live events (md/06 §6B.3)."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Protocol

from cairn_api.jobs.envelope import JobEnvelope


class Priority(enum.IntEnum):
    INTERACTIVE = 30
    STANDARD = 20
    BULK = 10  #: Yields to everything above it.


@dataclass(frozen=True, slots=True)
class QueueMessage:
    envelope: JobEnvelope
    receipt: str
    priority: Priority = Priority.STANDARD
    #: Broker's count, not envelope.attempt — dead-lettering reads the latter.
    delivery_attempt: int = 1
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QueueDepth:
    pending: int
    in_flight: int
    dead_lettered: int
    per_tenant: dict[uuid.UUID, int] = field(default_factory=dict)  #: Who's starved.

    @property
    def total(self) -> int:
        return self.pending + self.in_flight


class JobQueue(Protocol):
    async def publish(
        self,
        envelope: JobEnvelope,
        *,
        priority: Priority = Priority.STANDARD,
        delay_seconds: float = 0.0,
    ) -> None:
        """``delay_seconds`` backs retry backoff via redelivery deadline — Pub/Sub has no native delayed delivery."""
        ...

    async def receive(self, *, max_messages: int = 1) -> list[QueueMessage]: ...

    async def ack(self, message: QueueMessage) -> None: ...

    async def retry(self, message: QueueMessage, *, delay_seconds: float) -> None:
        """Distinct from a bare nack: immediate redelivery turns a failing job into a hot loop."""
        ...

    async def dead_letter(self, message: QueueMessage, *, reason: str) -> None:
        """Aside, not deleted — stays inspectable (md/06 §6B.2)."""
        ...

    async def depth(self) -> QueueDepth: ...
