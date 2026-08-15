"""The job envelope. ``tenant_id`` is **structurally mandatory** — a message
without one fails to parse rather than running unscoped, which matters since
CAIRN is almost entirely background work (md/06 §4.3) where a scope leak
fails silently. A plain dict would make it optional by omission instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobEnvelope(BaseModel):
    """A unit of background work, bound to exactly one tenant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_type: str = Field(min_length=1)

    #: No default, no sentinel — a job that can't name its tenant must not run.
    tenant_id: uuid.UUID

    payload: dict[str, Any] = Field(default_factory=dict)

    #: Stable id for idempotent consumption across redelivery.
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)

    #: Set at creation, not pickup, so retries keep queue latency measurable.
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    attempt: int = Field(default=1, ge=1)

    #: W3C trace context (md/10 §7); optional since scheduled jobs have none.
    traceparent: str | None = None

    @model_validator(mode="after")
    def reject_nil_tenant(self) -> Self:
        """Refuse ``uuid.UUID(int=0)`` — what a buggy default would produce."""
        if self.tenant_id.int == 0:
            msg = "tenant_id must be a real tenant, not the nil UUID"
            raise ValueError(msg)
        return self

    def next_attempt(self) -> JobEnvelope:
        """Copy with attempt+1; frozen envelopes can't be mutated in place."""
        return self.model_copy(update={"attempt": self.attempt + 1})
