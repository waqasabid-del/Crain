"""Slack event receipt: verify → resolve → gate → record → enqueue → acknowledge.

The second unauthenticated write endpoint in the service, and it follows the
same order as the first (`github/webhooks.py`), because the order is the shared
contract in `ingestion/receipt.py` rather than GitHub's house style: correlation
id bound before verification, size cap before the HMAC, verification before
anything parses, tenant from the account identifier and never from the body,
idempotency committed before the enqueue, acknowledge fast.

What Slack adds to that order is a **budget** and a **gate**.

The budget is three seconds. Everything here is one signature check, one or two
indexed lookups and one publish; normalisation, attribution and understanding
happen on the worker where the existing retry and dead-letter guarantees apply.

The gate is the channel selection. A workspace being connected permits nothing
by itself — a customer chooses which public channels CAIRN may read, and that
check runs *before* the idempotency row is written, before the payload is
stored, before the enqueue and before anything about the event reaches a log or
a span. An event from an unselected channel therefore leaves no trace at all,
which is the only honest implementation of "we do not read that channel".

**Retries.** Slack retries a non-200 three times: immediately, at one minute and
at five. That is right for a transient failure and wrong for a permanent one, so
every refusal that will still be a refusal in five minutes — an unknown
workspace, a disconnected one, an unselected channel — is answered with
``x-slack-no-retry: 1`` and no further deliveries arrive.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog
from fastapi import APIRouter, FastAPI, Request, Response, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import PlatformDb
from cairn_api.api.errors import ProblemDetailError
from cairn_api.config import Settings
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectorErrorCategory,
    SourceConnection,
)
from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.ingestion import (
    InboundRequest,
    Ingestor,
    PayloadTooLargeError,
    ResolvedTenant,
    SourceMetadataError,
    VerificationError,
    VerifiedEvent,
    enqueue,
    job_payload,
)
from cairn_api.jobs.queue import Priority
from cairn_api.slack import events as slack_events
from cairn_api.slack.events import (
    SLACK_EVENT_JOB,
    DroppedMessage,
    SlackEnvelope,
    SlackMessage,
    read_envelope,
    read_message,
)
from cairn_api.slack.inbound import (
    MAX_PAYLOAD_BYTES,
    NO_RETRY_HEADER,
    NO_RETRY_VALUE,
    PROVIDER,
    RETRY_NUM_HEADER,
    RETRY_REASON_HEADER,
    ChannelPolicy,
    SlackInbound,
    SlackTeamResolver,
    StoredChannelPolicy,
    apply_teardown,
    record_connection_error,
    record_healthy_delivery,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: The environment variable holding the app's signing secret.
#:
#: Read here rather than from `Settings` only because the setting is added by
#: the install flow landing alongside this. `app.state.slack_signing_secret`
#: takes precedence, which is the seam `Settings` will be wired through and the
#: one tests use. Absent, verification refuses everything — a blank secret makes
#: every signature verifiable, so failing closed is the only safe reading.
SIGNING_SECRET_VAR = "CAIRN_SLACK_SIGNING_SECRET"  # noqa: S105 - a variable name, not a secret


def install(app: FastAPI, *, prefix: str) -> None:
    """Mount the endpoint and register the job it publishes.

    Both, in one call, deliberately. A router mounted without its handler
    registered publishes a job type no worker can resolve, which dead-letters as
    "unknown" — a failure that looks like a queue problem and is a wiring one.
    Guarded per type because the registry is process-wide and a second
    `create_app` in one test session must not re-register.
    """
    from cairn_api.jobs.runner import registry as job_registry

    app.include_router(router, prefix=prefix)
    if SLACK_EVENT_JOB not in job_registry.registered_types():
        slack_events.register()


@router.post(
    "/slack",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a Slack event",
    include_in_schema=False,
    responses={
        200: {"description": "Acknowledged: a challenge, a duplicate, or nothing to do."},
        202: {"description": "Verified and queued."},
        400: {"description": "Permanently refused; Slack is told not to retry."},
        401: {"description": "Signature missing, invalid, or outside the replay window."},
        413: {"description": "Payload too large."},
    },
)
async def receive_slack_event(
    request: Request,
    response: Response,
    db: PlatformDb,
) -> dict[str, str]:
    """Accept a Slack event.

    Excluded from the OpenAPI schema for the same reason the GitHub endpoint is:
    it is Slack's interface, not the frontend's, and publishing it would put an
    unauthenticated write path into the generated client.
    """
    ingestor = Ingestor(
        name=PROVIDER,
        provider=SlackInbound(secret=_signing_secret(request)),
        max_body_bytes=MAX_PAYLOAD_BYTES,
    )

    inbound = InboundRequest(body=await request.body(), headers=dict(request.headers))

    try:
        # Correlation id, size cap, then the signature — in that order, and all
        # of it before a single byte is parsed. See `ingestion/receipt.py`.
        event = ingestor.accept(inbound)
    except PayloadTooLargeError as exc:
        raise ProblemDetailError(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload too large",
            detail=f"Slack event payloads are limited to {MAX_PAYLOAD_BYTES} bytes.",
            problem_type="payload-too-large",
        ) from exc
    except VerificationError as exc:
        # The reason is ours — "missing signature", "outside the replay window" —
        # and never the payload. The *response* says none of it.
        await logger.awarning(
            "slack.event_rejected",
            reason=str(exc),
            retry_num=inbound.header(RETRY_NUM_HEADER),
            retry_reason=inbound.header(RETRY_REASON_HEADER),
        )
        raise _unauthorised() from exc
    except SourceMetadataError as exc:
        # Refused after verification rather than before, so a malformed body and
        # a forged one are indistinguishable from outside.
        raise _unauthorised() from exc

    return await _receive(event, request=request, response=response, db=db)


async def _receive(
    event: VerifiedEvent, *, request: Request, response: Response, db: AsyncSession
) -> dict[str, str]:
    """Everything after verification.

    Split from the endpoint so the HTTP-shaped concerns stay in one place and
    this reads as the sequence the module docstring describes.
    """
    envelope = read_envelope(event.body)
    if envelope is None:  # pragma: no cover - `read_source` already parsed it
        raise _unauthorised()

    # Answered *after* verification, never before. `url_verification` is signed
    # like everything else, and special-casing it to skip the check would leave
    # an unauthenticated endpoint that echoes attacker-chosen strings.
    if envelope.type == "url_verification":
        if envelope.challenge is None:
            return _no_retry(response, "malformed_challenge")
        response.status_code = status.HTTP_200_OK
        return {"challenge": envelope.challenge}

    team_id = envelope.team_id
    if team_id is None:
        # Verified, but it names no workspace. Retrying will not add one.
        return _no_retry(response, "no_team")

    # The account identifier comes from the verified body's top-level `team_id`
    # and is looked up against a mapping only an authenticated connect flow may
    # write. Nothing else in the payload can influence which workspace this
    # becomes: a body claiming a tenant, a channel or another team is data, not
    # authority.
    event = event.attributed_to(team_id)
    resolver = SlackTeamResolver(db)
    tenant: ResolvedTenant | None = await resolver.resolve(event.source)
    connection = resolver.connection

    if tenant is None or connection is None:
        # Refused rather than guessed. There is no default workspace, and
        # picking one would bind a stranger's messages to a customer.
        await logger.awarning("slack.unknown_team", provider=PROVIDER)
        return _no_retry(response, "unknown_workspace")

    # Before the active check: a teardown has to reach a connection that is
    # already inactive, which is the whole point of it being idempotent.
    if envelope.is_teardown:
        return await _teardown(db, connection, envelope, response=response)

    if envelope.type == "app_rate_limited":
        return await _rate_limited(db, connection, response=response)

    if not tenant.active:
        # Disconnected, revoked, or never confirmed. Capturing activity for a
        # switched-off integration is a consent failure, not a bug — and it will
        # still be switched off in five minutes.
        return _no_retry(response, "workspace_not_connected")

    decision = read_message(envelope)
    if isinstance(decision, DroppedMessage):
        # Acknowledged with a 2xx: Slack does not retry those, and the drop is a
        # decision rather than a failure. The reason is a closed enum, so this
        # log line cannot grow a channel name or a fragment of a message.
        await logger.ainfo(
            "slack.event_ignored",
            provider=PROVIDER,
            reason=decision.reason.value,
            event_type=envelope.event_type,
        )
        response.status_code = status.HTTP_200_OK
        return {"status": "ignored"}

    return await _ingest(
        event,
        decision,
        envelope,
        tenant=tenant,
        connection=connection,
        request=request,
        response=response,
        db=db,
    )


async def _ingest(
    event: VerifiedEvent,
    message: SlackMessage,
    envelope: SlackEnvelope,
    *,
    tenant: ResolvedTenant,
    connection: SourceConnection,
    request: Request,
    response: Response,
    db: AsyncSession,
) -> dict[str, str]:
    """Gate on the channel, record, enqueue, and report health."""
    policy = _channel_policy(request, db)
    if not await policy.is_selected(connection.id, message.channel_id):
        # Nothing above this line has stored the payload, written a delivery
        # row, published a job or named the channel anywhere. That ordering is
        # the control: a check that ran after the insert would leave the message
        # in a table nobody consented to it being in.
        await logger.ainfo("slack.channel_not_selected", provider=PROVIDER)
        return _no_retry(response, "channel_not_selected")

    delivery_id = event.idempotency_key.value
    payload: dict[str, Any] = json.loads(event.body)

    if not await _record_delivery(
        db,
        tenant=tenant,
        delivery_id=delivery_id,
        event_type=envelope.event_type,
        action=message.action.value,
        payload=payload,
    ):
        # The unique constraint rejected it: one of Slack's three retries of a
        # delivery we already hold. Acknowledged without re-enqueuing, which is
        # what makes a retried event one unit of work rather than three.
        await logger.ainfo(
            "slack.duplicate_event",
            delivery_id=delivery_id,
            tenant_id=str(tenant.tenant_id),
        )
        response.status_code = status.HTTP_200_OK
        return {"status": "duplicate"}

    # Honest health, on the one path where data actually arrived.
    await record_healthy_delivery(connection)

    # Committed before the enqueue. Acknowledging first would let a rollback
    # erase work Slack believes we already hold, and Slack never re-sends an
    # acknowledged event.
    await db.commit()

    await enqueue(
        request.app.state.queue,
        event,
        tenant,
        job_type=SLACK_EVENT_JOB,
        payload=job_payload(event),
        priority=Priority.STANDARD,
    )

    await logger.ainfo(
        "slack.event_accepted",
        delivery_id=delivery_id,
        action=message.action.value,
        tenant_id=str(tenant.tenant_id),
    )
    return {"status": "accepted"}


async def _teardown(
    db: AsyncSession,
    connection: SourceConnection,
    envelope: SlackEnvelope,
    *,
    response: Response,
) -> dict[str, str]:
    """Stop ingesting for this workspace. Idempotent, keyed on the connection.

    Slack sends `app_uninstalled` and `tokens_revoked` for one teardown with no
    guaranteed order, so whichever arrives first switches the connection off and
    the second is a no-op. Applied inline rather than queued, for the reason
    GitHub's lifecycle events are: it decides whether *future* deliveries are
    processed, and deferring it leaves a window in which an uninstalled
    workspace's messages are still being captured.
    """
    changed = await apply_teardown(connection, envelope.event_type)
    await db.commit()

    await logger.ainfo(
        "slack.workspace_torn_down",
        provider=PROVIDER,
        event_type=envelope.event_type,
        changed=changed,
        tenant_id=str(connection.tenant_id),
    )
    response.status_code = status.HTTP_200_OK
    return {"status": "disconnected"}


async def _rate_limited(
    db: AsyncSession, connection: SourceConnection, *, response: Response
) -> dict[str, str]:
    """Slack is dropping this workspace's events.

    Recorded as *degraded*, never healthy. This is not a delay — the events
    discarded during the rate-limited minute are never re-sent, so the record
    has a hole in it. Showing a green tick while that happens is the failure
    md/05 calls worse than an honest one.
    """
    await record_connection_error(
        connection,
        ConnectorErrorCategory.RATE_LIMITED,
        health=ConnectionHealth.DEGRADED,
    )
    await db.commit()

    await logger.awarning(
        "slack.app_rate_limited",
        provider=PROVIDER,
        tenant_id=str(connection.tenant_id),
        # Deliberately not the minute count or anything else from the payload:
        # the category is what an operator acts on.
        error_category=ConnectorErrorCategory.RATE_LIMITED.value,
    )
    response.status_code = status.HTTP_200_OK
    return {"status": "rate_limited"}


async def _record_delivery(
    db: AsyncSession,
    *,
    tenant: ResolvedTenant,
    delivery_id: str,
    event_type: str,
    action: str,
    payload: dict[str, Any],
) -> bool:
    """Write the idempotency record. False if it already existed.

    `ON CONFLICT DO NOTHING`, not select-then-insert: Slack's immediate retry
    can arrive while the first is still in flight, and two concurrent inserts of
    one key would both find nothing and the second would abort the transaction.

    `webhook_deliveries` is reused rather than duplicated for Slack. It already
    holds "one inbound delivery, its payload, its tenant and its status" under
    row-level security, and a second table would mean a second place to get
    isolation and retention right for the same shape of data.
    """
    statement = (
        insert(WebhookDelivery)
        .values(
            tenant_id=tenant.tenant_id,
            delivery_id=delivery_id,
            event_type=event_type[:64],
            action=action[:64],
            # Slack team ids are strings (`T0123ABCD`); this column is a
            # bigint for GitHub's numeric installation ids and is left null
            # rather than coerced into a number that means nothing.
            installation_id=None,
            status=DeliveryStatus.ACCEPTED,
            payload=payload,
        )
        .on_conflict_do_nothing(constraint="uq_webhook_deliveries_delivery_id")
        .returning(WebhookDelivery.id)
    )
    return await db.scalar(statement) is not None


def _channel_policy(request: Request, db: AsyncSession) -> ChannelPolicy:
    """The selection store, or the one that reads the selection table.

    The override exists so the install flow can bind its own reader without this
    module importing it, and so a test can state a selection directly. The
    default is not a permissive fallback: it queries `slack_channel_selections`
    and treats absence as "not selected".
    """
    override: ChannelPolicy | None = getattr(request.app.state, "slack_channel_policy", None)
    if override is not None:
        return override
    return StoredChannelPolicy(db=db)


def _signing_secret(request: Request) -> str:
    """The app's Slack signing secret, or an empty string.

    Empty is not a bypass: `SlackInbound.verify` refuses every request without a
    secret, so a misconfigured deployment rejects Slack rather than accepting
    everyone.
    """
    # The override seam stays first so a test can install a secret without
    # touching process configuration.
    configured: str | None = getattr(request.app.state, "slack_signing_secret", None)
    if configured:
        return configured

    # Then the real setting. `Settings` validates it once at startup, which is
    # where a malformed value should be caught; reading the environment directly
    # would bypass that and re-read it on every request.
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is not None and settings.slack_signing_secret.get_secret_value():
        return settings.slack_signing_secret.get_secret_value()

    return os.environ.get(SIGNING_SECRET_VAR, "")


def _no_retry(response: Response, reason: str) -> dict[str, str]:
    """Refuse permanently, and tell Slack not to come back.

    A non-200 without this header is three deliveries of something we have
    already declined — for an unselected channel, that is three arrivals of
    content a customer asked us not to read.
    """
    response.status_code = status.HTTP_400_BAD_REQUEST
    response.headers[NO_RETRY_HEADER] = NO_RETRY_VALUE
    return {"status": "rejected", "reason": reason}


def _unauthorised() -> ProblemDetailError:
    """One response for every verification failure.

    Undifferentiated on purpose: a forger who learns *which* part of their
    forgery was wrong learns how to fix it. A malformed body is answered the
    same way for the same reason.
    """
    return ProblemDetailError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Invalid signature",
        detail="The request signature could not be verified.",
        problem_type="invalid-signature",
    )
