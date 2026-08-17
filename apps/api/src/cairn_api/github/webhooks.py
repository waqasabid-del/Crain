"""Webhook receipt: verify → resolve → record → enqueue → acknowledge.

The one unauthenticated write endpoint in the service. GitHub expects a 2xx
within ten seconds (md/01 §4.1) or it retries, so the handler does only what
can't be deferred; normalisation and attribution happen on the worker.

Delivery is not exactly-once — GitHub documents duplicates and gaps as
normal — so the delivery ID is written with a unique constraint *before* the
job is enqueued. The row is committed before enqueuing: acknowledging first
would let a rollback erase work GitHub believes we already have.

The ordering above is no longer GitHub's alone. It is the provider-neutral
contract in `cairn_api.ingestion`, and this module is its first caller: the
verifier, the account extractor and the delivery table below are the
GitHub-specific parts, and everything between them — the size cap, the mint of a
`VerifiedEvent`, the idempotency key, tenant resolution, the envelope, the
correlation id — is shared with the Slack and Google Chat endpoints that arrive
next. What is *not* shared is what a provider does with each refusal, which is
why the responses are still assembled here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import APIRouter, Header, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import PlatformDb, SettingsDep
from cairn_api.api.errors import ProblemDetailError
from cairn_api.db.github_models import DeliveryStatus, GitHubInstallation, WebhookDelivery
from cairn_api.github.handlers import GITHUB_DELIVERY_JOB
from cairn_api.github.signatures import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    SignatureError,
    verify,
)
from cairn_api.ingestion import (
    IdempotencyKey,
    InboundRequest,
    Ingestor,
    PayloadTooLargeError,
    ResolvedTenant,
    SourceMetadata,
    SourceMetadataError,
    UnknownAccountError,
    VerificationError,
    VerifiedEvent,
    enqueue,
    job_payload,
    resolve_tenant,
)
from cairn_api.jobs.queue import Priority

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: This provider's name in `SourceMetadata`, on spans, and in logs.
PROVIDER = "github"

#: GitHub caps payloads at 25 MB; capped lower here since an unauthenticated
#: endpoint accepting the full 25 MB is an amplification vector and a
#: monorepo push is comfortably under 5 MB.
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

#: Events that change installation state. Handled inline, not queued: they
#: decide whether *future* deliveries are processed, and deferring them would
#: leave a window where a suspended installation's activity is still captured.
LIFECYCLE_EVENTS = frozenset({"installation", "installation_repositories"})


@dataclass(frozen=True, slots=True)
class GitHubInbound:
    """GitHub's half of the ingestion contract: HMAC-SHA256, and two headers.

    The whole provider-specific surface of this integration is here. Slack signs
    a versioned string that includes a timestamp, and Google Chat sends a bearer
    JWT — both are a different implementation of this same protocol, and neither
    changes anything downstream of it.
    """

    secret: str

    def verify(self, request: InboundRequest) -> None:
        """Check the signature against the raw bytes."""
        try:
            verify(request.body, request.header(SIGNATURE_HEADER), self.secret)
        except SignatureError as exc:
            # Re-raised as the contract's error so the shared path does not
            # import GitHub's exception type; the message is kept for the log.
            raise VerificationError(str(exc)) from exc

    def read_source(self, request: InboundRequest) -> SourceMetadata:
        """Name the delivery, from headers only.

        The account is not known yet: GitHub puts the installation id in the
        body, which may only be read once the bytes above have verified. It is
        attached in `_receive` via `VerifiedEvent.attributed_to`.
        """
        event_type = request.header(EVENT_HEADER)
        delivery_id = request.header(DELIVERY_HEADER)
        if not event_type or not delivery_id:
            msg = "A delivery must carry both an event type and a delivery id"
            raise SourceMetadataError(msg)

        return SourceMetadata(
            provider=PROVIDER, event_type=event_type, external_event_id=delivery_id
        )

    def idempotency_key(self, request: InboundRequest, source: SourceMetadata) -> IdempotencyKey:
        """`X-GitHub-Delivery`, unchanged.

        GitHub reuses the GUID on every retry of a delivery, which is exactly
        the property an idempotency key needs, so nothing is derived. Providers
        without one fall back to `IdempotencyKey.derive`.
        """
        if source.external_event_id is None:  # pragma: no cover - read_source guarantees it
            msg = "A GitHub delivery must carry a delivery id"
            raise SourceMetadataError(msg)
        return IdempotencyKey.from_provider(source.external_event_id)


class _InstallationResolver:
    """Tenant from installation id, via the mapping the connect flow wrote.

    The row is kept after resolution because a lifecycle event has to be applied
    to an installation that is suspended, uninstalled, or otherwise not eligible
    to have work enqueued for it — and looking it up twice inside a ten-second
    budget is a cost with no benefit.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self.installation: GitHubInstallation | None = None

    async def resolve(self, source: SourceMetadata) -> ResolvedTenant | None:
        if source.external_account_id is None:
            return None

        try:
            installation_id = int(source.external_account_id)
        except ValueError:  # pragma: no cover - only an int reaches this today
            return None

        self.installation = await self._db.scalar(
            select(GitHubInstallation).where(GitHubInstallation.installation_id == installation_id)
        )
        if self.installation is None:
            return None

        return ResolvedTenant(
            tenant_id=self.installation.tenant_id,
            external_account_id=source.external_account_id,
            active=self.installation.is_active,
        )


@dataclass(frozen=True, slots=True)
class _DeliveryLedger:
    """GitHub's idempotency record — `webhook_deliveries` (md/01 §4.1)."""

    db: AsyncSession
    payload: dict[str, Any]
    installation_id: int
    status: DeliveryStatus = DeliveryStatus.ACCEPTED

    async def claim(self, event: VerifiedEvent, tenant: ResolvedTenant) -> bool:
        return await _record_delivery(
            self.db,
            tenant_id=tenant.tenant_id,
            delivery_id=event.idempotency_key.value,
            event_type=event.source.event_type,
            action=_action_of(self.payload),
            installation_id=self.installation_id,
            payload=self.payload,
            status=self.status,
        )


@router.post(
    "/github",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a GitHub webhook",
    include_in_schema=False,
    responses={
        202: {"description": "Verified and queued."},
        401: {"description": "Signature missing or invalid."},
        413: {"description": "Payload too large."},
    },
)
async def receive_github_webhook(
    request: Request,
    response: Response,
    db: PlatformDb,
    settings: SettingsDep,
    signature: str = Header(default=None, alias=SIGNATURE_HEADER),
    delivery_id: str = Header(default=None, alias=DELIVERY_HEADER),
    event_type: str = Header(default=None, alias=EVENT_HEADER),
) -> dict[str, str]:
    """Accept a webhook.

    Excluded from the OpenAPI schema: it's GitHub's interface, not the
    frontend's, and publishing it would put this unauthenticated write path
    into the generated client.

    The headers are declared as parameters purely so the rejection path can name
    the delivery that was refused; verification reads them from the raw request,
    because a framework-coerced value is not what the signature covered.
    """
    ingestor = Ingestor(
        name=PROVIDER,
        provider=GitHubInbound(secret=settings.github_webhook_secret),
        max_body_bytes=MAX_PAYLOAD_BYTES,
    )

    inbound = InboundRequest(body=await request.body(), headers=dict(request.headers))

    try:
        # Correlation id, size cap and signature, in that order — see
        # `ingestion/receipt.py`, where the order and its reasons live.
        event = ingestor.accept(inbound)
    except PayloadTooLargeError as exc:
        raise ProblemDetailError(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload too large",
            detail=f"Webhook payloads are limited to {MAX_PAYLOAD_BYTES} bytes.",
            problem_type="payload-too-large",
        ) from exc
    except VerificationError as exc:
        await logger.awarning(
            "github.webhook_rejected",
            reason=str(exc),
            event_type=event_type,
            delivery_id=delivery_id,  # GitHub's ID, safe to log; the payload isn't
        )
        raise _unauthorised() from exc
    except SourceMetadataError as exc:
        # Rejected after verification, not before, so header absence can't be
        # used to probe.
        raise _unauthorised() from exc

    return await _receive(event, request=request, response=response, db=db)


async def _receive(
    event: VerifiedEvent, *, request: Request, response: Response, db: AsyncSession
) -> dict[str, str]:
    """Everything after verification: attribute, record, enqueue.

    Split from the endpoint so the request-shaped concerns — headers, status
    codes, problem documents — stay in one place and this reads as the sequence
    md/01 §4.1 describes.
    """
    delivery_id = event.idempotency_key.value
    event_type = event.source.event_type

    # `ping` arrives before any installation exists; answered before tenant
    # resolution so a correctly configured app doesn't show a failed test delivery.
    if event_type == "ping":
        await logger.ainfo("github.ping", delivery_id=delivery_id)
        return {"status": "pong"}

    # Decoded only now, and only because verification has already passed on the
    # exact bytes this parses.
    payload: dict[str, Any] = json.loads(event.body)

    installation_id = _installation_id_from(payload)
    if installation_id is None:
        await logger.awarning(
            "github.webhook_without_installation",
            event_type=event_type,
            delivery_id=delivery_id,
        )
        # 202, not an error: retrying wouldn't add an installation ID anyway.
        return {"status": "ignored"}

    # The account identifier comes from the verified body's `installation.id`
    # and is looked up against the mapping an authenticated connect flow wrote.
    # Nothing else in the payload can influence which workspace this becomes:
    # a body claiming `tenant_id`, `org` or `account` is data, not authority.
    event = event.attributed_to(str(installation_id))
    resolver = _InstallationResolver(db)
    try:
        tenant: ResolvedTenant | None = await resolve_tenant(resolver, event.source)
    except UnknownAccountError:
        # Refused rather than guessed: there is no default workspace, and
        # picking one would bind a stranger's activity to a customer.
        tenant = None

    if event_type in LIFECYCLE_EVENTS:
        await _apply_lifecycle(db, resolver.installation, payload)
        await db.commit()
        return {"status": "accepted"}

    if tenant is None or not tenant.active:
        # Unknown, suspended or uninstalled: not enqueued, since capturing
        # activity for a switched-off integration is a consent problem.
        # Recorded only when there's a tenant to attribute the row to —
        # `tenant_id` is not nullable, so an unknown installation is just logged.
        if tenant is not None:
            ledger = _DeliveryLedger(
                db=db,
                payload=payload,
                installation_id=installation_id,
                status=DeliveryStatus.UNCLAIMED,
            )
            await ledger.claim(event, tenant)
            await db.commit()

        await logger.ainfo(
            "github.delivery_unclaimed",
            installation_id=installation_id,
            event_type=event_type,
            known=tenant is not None,
            recorded=tenant is not None,
        )
        return {"status": "unclaimed"}

    ledger = _DeliveryLedger(db=db, payload=payload, installation_id=installation_id)
    if not await ledger.claim(event, tenant):
        # Unique constraint rejected it: a GitHub redelivery we already hold.
        # Acknowledge without re-enqueuing to avoid processing it twice.
        await logger.ainfo(
            "github.duplicate_delivery",
            delivery_id=delivery_id,
            event_type=event_type,
            tenant_id=str(tenant.tenant_id),
        )
        response.status_code = status.HTTP_200_OK
        return {"status": "duplicate"}

    # Commit before enqueuing — GitHub never re-sends an acknowledged delivery.
    await db.commit()

    # The shared enqueue: one `JobEnvelope`, on the one queue, carrying the
    # correlation id minted at receipt and the active trace.
    await enqueue(
        request.app.state.queue,
        event,
        tenant,
        job_type=GITHUB_DELIVERY_JOB,
        payload=job_payload(event),
        priority=Priority.STANDARD,
    )

    await logger.ainfo(
        "github.delivery_accepted",
        delivery_id=delivery_id,
        event_type=event_type,
        action=_action_of(payload),
        tenant_id=str(tenant.tenant_id),
    )
    return {"status": "accepted"}


def _unauthorised() -> ProblemDetailError:
    """One response for every verification failure, undifferentiated on
    purpose: it must not tell a forger which part was wrong."""
    return ProblemDetailError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Invalid signature",
        detail="The request signature could not be verified.",
        problem_type="invalid-signature",
    )


def _action_of(payload: dict[str, Any]) -> str | None:
    """The payload's `action`, if it has one and it is a string.

    Type-checked rather than taken: it is written to a `String(64)` column and
    logged, and a payload whose `action` is an object would fail the insert for
    every delivery of that event type.
    """
    action = payload.get("action")
    return action if isinstance(action, str) else None


def _installation_id_from(payload: dict[str, Any]) -> int | None:
    """Read the installation ID out of a payload.

    Read defensively: GitHub's schema can change, and a `KeyError` here would
    500 every delivery of that event type.
    """
    installation = payload.get("installation")
    if not isinstance(installation, dict):
        return None
    raw = installation.get("id")
    return raw if isinstance(raw, int) else None


async def _record_delivery(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    delivery_id: str,
    event_type: str,
    action: str | None,
    installation_id: int,
    payload: dict[str, Any],
    status: DeliveryStatus = DeliveryStatus.ACCEPTED,
) -> bool:
    """Write the idempotency record. Returns False if it already existed.

    `ON CONFLICT DO NOTHING`, not select-then-insert: two concurrent
    deliveries of the same ID (which GitHub's retries produce) would both
    find nothing and both insert, aborting the transaction on the second.
    """
    statement = (
        insert(WebhookDelivery)
        .values(
            tenant_id=tenant_id,
            delivery_id=delivery_id,
            event_type=event_type,
            action=action,
            installation_id=installation_id,
            status=status,
            payload=payload,
        )
        .on_conflict_do_nothing(constraint="uq_webhook_deliveries_delivery_id")
        .returning(WebhookDelivery.id)
    )
    return await db.scalar(statement) is not None


async def _apply_lifecycle(
    db: AsyncSession,
    installation: GitHubInstallation | None,
    payload: dict[str, Any],
) -> None:
    """Apply an installation lifecycle event.

    Handled inline; see `LIFECYCLE_EVENTS`. An `installation.created` for an
    installation CAIRN has never seen is deliberately ignored: binding it to a
    tenant here would let an inbound webhook create the ownership mapping,
    which only an authenticated user's connect flow may do.
    """
    from datetime import UTC, datetime

    action = payload.get("action")
    if installation is None:
        await logger.ainfo("github.lifecycle_for_unknown_installation", action=action)
        return

    now = datetime.now(UTC)
    if action == "suspend":
        installation.suspended_at = now
    elif action == "unsuspend":
        installation.suspended_at = None
    elif action == "deleted":
        installation.uninstalled_at = now

    await logger.ainfo(
        "github.installation_lifecycle",
        action=action,
        installation_id=installation.installation_id,
        tenant_id=str(installation.tenant_id),
    )
