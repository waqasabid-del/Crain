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


def _current_traceparent() -> str | None:
    """The active trace, if this process is tracing."""
    from cairn_api.telemetry import current_trace_context

    return current_trace_context().get("traceparent")


def _current_correlation_id() -> str:
    """The unit of work this job belongs to, or a new one.

    Unlike `traceparent` this never comes back empty: work with no ambient id
    (a scheduled sweep, a backfill, a job built in a test) starts its own rather
    than being the delivery nobody can follow.
    """
    from cairn_api.telemetry import correlation_id_for_new_work

    return correlation_id_for_new_work()


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

    #: W3C trace context (md/10 §7). Captured at construction rather than
    #: passed by callers: a worker span that does not link back to the
    #: request is the one nobody can follow when a brief is wrong.
    traceparent: str | None = Field(default_factory=_current_traceparent)

    #: The durable half of "follow this webhook to its brief". `traceparent`
    #: links spans and exists only while a tracer is installed — which is
    #: nowhere without a collector, including local development and any
    #: deployment that has not configured one. This id is always present, is
    #: carried through every queue implementation, is bound into the logging
    #: context on the worker, and is inherited by any job a handler publishes,
    #: so one webhook and the brief it produced share one greppable name. The
    #: two coexist; neither replaces the other.
    #:
    #: Constrained to the generated shape (32 hex characters) rather than left
    #: free: it is stamped on spans, so an envelope arriving from storage with
    #: a sentence in this field would be a leak, and refusing to parse is the
    #: failure everyone notices.
    correlation_id: str = Field(default_factory=_current_correlation_id, pattern=r"^[0-9a-f]{32}$")

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
