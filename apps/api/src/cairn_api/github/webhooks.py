"""Webhook receipt: verify → resolve → record → enqueue → acknowledge.

The one unauthenticated write endpoint in the service. GitHub expects a 2xx
within ten seconds (md/01 §4.1) or it retries, so the handler does only what
can't be deferred; normalisation and attribution happen on the worker.

Delivery is not exactly-once — GitHub documents duplicates and gaps as
normal — so the delivery ID is written with a unique constraint *before* the
job is enqueued. The row is committed before enqueuing: acknowledging first
would let a rollback erase work GitHub believes we already have.
"""

from __future__ import annotations

import uuid
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
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import Priority

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: GitHub caps payloads at 25 MB; capped lower here since an unauthenticated
#: endpoint accepting the full 25 MB is an amplification vector and a
#: monorepo push is comfortably under 5 MB.
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

#: Events that change installation state. Handled inline, not queued: they
#: decide whether *future* deliveries are processed, and deferring them would
#: leave a window where a suspended installation's activity is still captured.
LIFECYCLE_EVENTS = frozenset({"installation", "installation_repositories"})


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
    """
    body = await request.body()

    # Size check before signature: HMAC over an unbounded body is the
    # amplification this check exists to prevent.
    if len(body) > MAX_PAYLOAD_BYTES:
        raise ProblemDetailError(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload too large",
            detail=f"Webhook payloads are limited to {MAX_PAYLOAD_BYTES} bytes.",
            problem_type="payload-too-large",
        )

    # Verify before parsing: the signature covers these exact bytes.
    try:
        verify(body, signature, settings.github_webhook_secret)
    except SignatureError as exc:
        await logger.awarning(
            "github.webhook_rejected",
            reason=str(exc),
            event_type=event_type,
            delivery_id=delivery_id,  # GitHub's ID, safe to log; the payload isn't
        )
        raise _unauthorised() from exc

    if not delivery_id or not event_type:
        # Rejected after verification, not before, so header absence can't be
        # used to probe.
        raise _unauthorised()

    payload: dict[str, Any] = await request.json()

    # `ping` arrives before any installation exists; answered before tenant
    # resolution so a correctly configured app doesn't show a failed test delivery.
    if event_type == "ping":
        await logger.ainfo("github.ping", delivery_id=delivery_id)
        return {"status": "pong"}

    installation_id = _installation_id_from(payload)
    if installation_id is None:
        await logger.awarning(
            "github.webhook_without_installation",
            event_type=event_type,
            delivery_id=delivery_id,
        )
        # 202, not an error: retrying wouldn't add an installation ID anyway.
        return {"status": "ignored"}

    installation = await db.scalar(
        select(GitHubInstallation).where(GitHubInstallation.installation_id == installation_id)
    )

    if event_type in LIFECYCLE_EVENTS:
        await _apply_lifecycle(db, installation, payload)
        await db.commit()
        return {"status": "accepted"}

    if installation is None or not installation.is_active:
        # Unknown, suspended or uninstalled: not enqueued, since capturing
        # activity for a switched-off integration is a consent problem.
        # Recorded only when there's a tenant to attribute the row to —
        # `tenant_id` is not nullable, so an unknown installation is just logged.
        if installation is not None:
            await _record_delivery(
                db,
                tenant_id=installation.tenant_id,
                delivery_id=delivery_id,
                event_type=event_type,
                action=payload.get("action"),
                installation_id=installation_id,
                payload=payload,
                status=DeliveryStatus.UNCLAIMED,
            )
            await db.commit()

        await logger.ainfo(
            "github.delivery_unclaimed",
            installation_id=installation_id,
            event_type=event_type,
            known=installation is not None,
            recorded=installation is not None,
        )
        return {"status": "unclaimed"}

    recorded = await _record_delivery(
        db,
        tenant_id=installation.tenant_id,
        delivery_id=delivery_id,
        event_type=event_type,
        action=payload.get("action"),
        installation_id=installation_id,
        payload=payload,
    )

    if not recorded:
        # Unique constraint rejected it: a GitHub redelivery we already hold.
        # Acknowledge without re-enqueuing to avoid processing it twice.
        await logger.ainfo(
            "github.duplicate_delivery",
            delivery_id=delivery_id,
            event_type=event_type,
            tenant_id=str(installation.tenant_id),
        )
        response.status_code = status.HTTP_200_OK
        return {"status": "duplicate"}

    # Commit before enqueuing — GitHub never re-sends an acknowledged delivery.
    await db.commit()

    queue = request.app.state.queue
    await queue.publish(
        JobEnvelope(
            job_type=GITHUB_DELIVERY_JOB,
            tenant_id=installation.tenant_id,
            payload={"delivery_id": delivery_id},
        ),
        priority=Priority.STANDARD,
    )

    await logger.ainfo(
        "github.delivery_accepted",
        delivery_id=delivery_id,
        event_type=event_type,
        action=payload.get("action"),
        tenant_id=str(installation.tenant_id),
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
