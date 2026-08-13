"""The job envelope.

Every background job carries this. Its most important property is that
``tenant_id`` is **structurally mandatory** — a job message cannot be
constructed without one, and one that arrives without it fails to parse rather
than running unscoped.

This matters more here than anywhere else in the system. CAIRN is almost
entirely background work: every webhook, every pipeline stage, every scheduled
brief runs outside a user request, which is exactly the context where tenant
scoping is easiest to lose (md/06 §4.3). And a background job that loses tenant
context does not fail loudly — it silently reads across tenants, with no user
watching to notice.

The envelope is deliberately not a plain dict. A dict makes ``tenant_id``
optional by omission; a validated model makes its absence a parse failure at the
boundary, before any handler code runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobEnvelope(BaseModel):
    """A unit of background work, bound to exactly one tenant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Which handler runs this. Resolved through the registry.
    job_type: str = Field(min_length=1)

    #: The workspace this work belongs to.
    #:
    #: Required, and validated as a UUID rather than a string. There is no
    #: default and no sentinel — a job that cannot name its tenant is a job that
    #: must not run.
    tenant_id: uuid.UUID

    #: Handler-specific data. Validated by the handler's own model, not here.
    payload: dict[str, Any] = Field(default_factory=dict)

    #: Stable identifier for idempotent consumption. Redelivery is normal in
    #: any queue with at-least-once semantics, so handlers must tolerate it.
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)

    #: When the job was created, not when it was picked up. Retries keep the
    #: original value so that queue latency is measurable.
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    #: How many times delivery has been attempted. Incremented by the runner.
    attempt: int = Field(default=1, ge=1)

    #: W3C trace context, so a job can be correlated with the request that
    #: caused it (md/10 §7). Optional because scheduled jobs have no originating
    #: request.
    traceparent: str | None = None

    @model_validator(mode="after")
    def reject_nil_tenant(self) -> Self:
        """Refuse the all-zero UUID.

        ``uuid.UUID(int=0)`` parses successfully and looks like a valid tenant,
        so it is exactly the value a buggy default or an uninitialised variable
        would produce. Rejecting it here means that mistake surfaces at the
        boundary rather than as a job that runs against a tenant which does not
        exist.
        """
        if self.tenant_id.int == 0:
            msg = "tenant_id must be a real tenant, not the nil UUID"
            raise ValueError(msg)
        return self

    def next_attempt(self) -> JobEnvelope:
        """Return a copy marked as one attempt later.

        The envelope is frozen, so a retry produces a new value rather than
        mutating the one already in flight.
        """
        return self.model_copy(update={"attempt": self.attempt + 1})
