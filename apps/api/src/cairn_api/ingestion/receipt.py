"""Receipt: the shared order every provider's endpoint follows.

The order is the contract, and it is the part that took a production incident
elsewhere to learn:

1. **Bind the correlation id first** — before verification, so a *rejected*
   delivery is greppable too. An id minted after the signature check exists only
   for the traffic that was already fine.
2. **Check the size before the HMAC** — hashing an unbounded body on an
   unauthenticated endpoint is the amplification the cap exists to prevent.
3. **Verify before parsing** — the signature covers the exact bytes; a parser
   that runs first is attacker-reachable code running on unauthenticated input.
4. **Resolve the tenant from the account identifier**, never from the body
   (`tenancy.py`).
5. **Claim the idempotency key, and commit it, before enqueuing** —
   acknowledging first would let a rollback erase work the provider believes we
   already hold.
6. **Enqueue and acknowledge fast.** GitHub allows ten seconds, Slack three
   (md/01 §4.1, md/02 §9); everything else happens on the worker, where the
   existing retry and dead-letter guarantees in `jobs/worker.py` apply
   unchanged. Nothing here re-implements them, and there is no second queue.

Steps 2 and 3 live in `Ingestor.accept`; steps 4 to 6 are the functions below, typed
against `VerifiedEvent` so none of them can be reached with anything unverified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from cairn_api import telemetry
from cairn_api.ingestion.errors import PayloadTooLargeError
from cairn_api.ingestion.inbound import (
    InboundProvider,
    InboundRequest,
    VerifiedEvent,
    verify_and_mint,
)
from cairn_api.ingestion.tenancy import ResolvedTenant
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import JobQueue, Priority
from cairn_api.telemetry import correlation

#: Well under any provider's own cap (GitHub allows 25 MB), because an
#: unauthenticated endpoint that will hash 25 MB on demand is an amplification
#: vector and no legitimate event is close to this.
DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Ingestor:
    """One provider's inbound endpoint, minus the provider-specific parts."""

    #: Stable, lowercase, and safe for telemetry: it is a category, not content.
    name: str

    provider: InboundProvider

    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES

    def accept(self, request: InboundRequest) -> VerifiedEvent:
        """Steps 1 to 3. Synchronous on purpose: nothing here waits on anything, so
        the acknowledgement budget is spent on the database and the queue.

        Raises `PayloadTooLargeError`, `VerificationError` or
        `SourceMetadataError`. The caller maps them to responses, because only
        it knows what its provider does with a rejection.
        """
        # The true entry point of everything that follows: bound before the
        # signature check so a rejected delivery carries an id too, inherited by
        # every envelope published below, and carried through the queue into the
        # worker. Unscoped is safe — each request runs in its own task with its
        # own copy of the context, and `api/middleware.py` clears the logging
        # context per request.
        correlation_id = correlation.begin()

        # Only allow-listed attributes (`telemetry/attributes.py`): a category
        # and an opaque id. Nothing from the body reaches a span, here or below.
        with telemetry.stage("ingest", source=self.name, correlation_id=correlation_id):
            if len(request.body) > self.max_body_bytes:
                msg = f"Payloads are limited to {self.max_body_bytes} bytes"
                raise PayloadTooLargeError(msg)

            return verify_and_mint(request, self.provider, correlation_id=correlation_id)


class IdempotencyLedger(Protocol):
    """Where a provider records the events it has already taken.

    A protocol rather than a shared table: the record belongs with the
    provider's own data (GitHub's `webhook_deliveries`, and whatever Slack and
    Chat are given), under that table's row-level security. What is shared is
    the *rule* — write the key with a unique constraint, commit it, and only
    then enqueue.
    """

    async def claim(self, event: VerifiedEvent, tenant: ResolvedTenant) -> bool:
        """True if this event is new; False if the key is already held.

        Must be a conditional insert (`ON CONFLICT DO NOTHING`), not
        select-then-insert: two concurrent redeliveries of one key both find
        nothing and both insert, and the second aborts the transaction.
        """
        ...


async def enqueue(
    queue: JobQueue,
    event: VerifiedEvent,
    tenant: ResolvedTenant,
    *,
    job_type: str,
    payload: dict[str, Any],
    priority: Priority = Priority.STANDARD,
) -> JobEnvelope:
    """Hand a verified event to the existing queue as an ordinary job.

    `JobEnvelope` is reused deliberately — a second envelope type would mean a
    second worker, a second retry policy and a second dead-letter path, none of
    which would have the guarantees `jobs/worker.py` already provides.

    Note what this signature cannot express: there is no way to publish an
    unverified event or a tenant-less one. `VerifiedEvent` is unconstructable
    without verification and `JobEnvelope.tenant_id` has no default.

    `correlation_id` is passed rather than left to the envelope's default, so
    propagation is a property of this call and not of whichever context it
    happens to run in. `traceparent` is captured by the envelope from the active
    span, which is what joins the worker's spans to this request.
    """
    envelope = JobEnvelope(
        job_type=job_type,
        tenant_id=tenant.tenant_id,
        payload=payload,
        correlation_id=event.correlation_id,
    )
    await queue.publish(envelope, priority=priority)
    return envelope


def job_payload(event: VerifiedEvent) -> dict[str, str]:
    """The minimal job body: the key, and nothing else.

    The queue is not a durable store and redelivery is normal, so the worker
    re-reads the event from the provider's own table under the tenant's
    row-level security. Putting the payload on the message instead would put
    customer content in a broker that has none of the storage promises in md/05.
    """
    return {"delivery_id": event.idempotency_key.value}
