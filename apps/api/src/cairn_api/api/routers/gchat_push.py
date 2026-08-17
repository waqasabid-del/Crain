"""Google Chat event receipt: verify → resolve → gate → record → enqueue → acknowledge.

The third unauthenticated write endpoint in the service, and it follows the same
order as the first two, because the order is the shared contract in
`ingestion/receipt.py` rather than any one provider's house style: correlation id
bound before verification, size cap before the crypto, verification before
anything parses, tenant from the stored space selection and never from the body,
idempotency committed before the enqueue, acknowledge fast.

What Pub/Sub changes is **what a refusal costs**, and it is the whole reason this
file does not simply copy Slack's status codes.

**The budget cannot be extended.** A push request's deadline is the
subscription's `ackDeadlineSeconds` — ten seconds by default — and unlike a pull
subscription there is no way to extend it for one message. So this endpoint does
the same four things Slack's does (verify, gate, record, enqueue) and nothing
else; normalisation, attribution and understanding happen on the worker where
the existing retry and dead-letter guarantees apply.

**Only 102, 200, 201, 202 and 204 acknowledge.** Everything else is a NACK, and
Pub/Sub redelivers with a backoff between 100ms and 60s until the message expires
or dead-letters. There is no `x-slack-no-retry` equivalent, so the status code is
the entire vocabulary: a *permanent* refusal — an unknown space, a deselected
one, a disconnected connection, a bot's message, an event type CAIRN does not
ingest — must answer **2xx**, because redelivering it would only produce the same
refusal every minute for a week. A *transient* failure — Google's key set
unreachable, the database down — must answer non-2xx so the message comes back.
Getting this backwards in either direction is the bug: 2xx on a transient failure
silently drops customer data, and non-2xx on a permanent one is an infinite
redelivery loop of data we already declined to read.

**The gate is the space selection.** A connected Google Chat account permits
nothing by itself — a customer chooses which spaces CAIRN may read, and that
check runs *before* the idempotency row is written, before the payload is
stored, before the enqueue and before anything about the event reaches a log or a
span. An event from an unselected space therefore leaves no trace at all, which
is the only honest implementation of "we do not read that space".
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, FastAPI, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import PlatformDb
from cairn_api.api.errors import ProblemDetailError
from cairn_api.db.connector_models import SourceConnection
from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.gchat.events import (
    GCHAT_EVENT_JOB,
    ChatEvent,
    ChatMessage,
    DroppedMessage,
    read_event,
    read_message,
    stored_payload,
)
from cairn_api.gchat.pubsub import (
    CE_TYPE_ATTRIBUTE,
    MAX_PAYLOAD_BYTES,
    PROVIDER,
    GoogleChatPush,
    GoogleJwks,
    PushEnvelope,
    RecentMessageIds,
    SigningKeys,
    SigningKeyUnavailableError,
    SpaceRegistry,
    SpaceSubscription,
    StoredSpaceRegistry,
    configured_audience,
    configured_service_account,
    configured_subscription,
    read_push,
    record_healthy_delivery,
)
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

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: The one status this endpoint uses to mean "taken, and nothing more will
#: happen here". 200 rather than 204 so a refusal can still say *why* in a body
#: an operator can read in the Pub/Sub console; both acknowledge identically.
ACKNOWLEDGED = status.HTTP_200_OK


def install(app: FastAPI, *, prefix: str) -> None:
    """Mount the endpoint and register the job it publishes.

    Both, in one call, deliberately. A router mounted without its handler
    registered publishes a job type no worker can resolve, which dead-letters as
    "unknown" — a failure that looks like a queue problem and is a wiring one.
    Guarded per type because the registry is process-wide and a second
    `create_app` in one test session must not re-register.
    """
    from cairn_api.gchat import events as gchat_events
    from cairn_api.jobs.runner import registry as job_registry

    app.include_router(router, prefix=prefix)
    # Per application instance rather than per process: it is a cache, and two
    # apps in one test session sharing one would make a delivery to the first
    # look like a duplicate to the second.
    app.state.gchat_recent_messages = RecentMessageIds()
    if GCHAT_EVENT_JOB not in job_registry.registered_types():
        gchat_events.register()


@router.post(
    "/google-chat",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a Google Chat event from Pub/Sub",
    include_in_schema=False,
    responses={
        200: {"description": "Acknowledged: a duplicate, a drop, or a permanent refusal."},
        202: {"description": "Verified and queued."},
        401: {"description": "The push token did not verify, or the envelope was malformed."},
        413: {"description": "Payload too large."},
        503: {"description": "Google's key set was unreachable; Pub/Sub should redeliver."},
    },
)
async def receive_chat_event(
    request: Request,
    response: Response,
    db: PlatformDb,
) -> dict[str, str]:
    """Accept a Google Chat event.

    Excluded from the OpenAPI schema for the same reason the other two inbound
    endpoints are: it is Google's interface, not the frontend's, and publishing
    it would put an unauthenticated write path into the generated client.
    """
    ingestor = Ingestor(
        name=PROVIDER,
        provider=_verifier(request),
        max_body_bytes=MAX_PAYLOAD_BYTES,
    )

    inbound = InboundRequest(body=await request.body(), headers=dict(request.headers))

    try:
        # Correlation id, size cap, then the token — in that order, and all of it
        # before a single byte of the Chat resource is parsed. See
        # `ingestion/receipt.py`.
        event = ingestor.accept(inbound)
    except PayloadTooLargeError as exc:
        raise ProblemDetailError(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload too large",
            detail=f"Google Chat push payloads are limited to {MAX_PAYLOAD_BYTES} bytes.",
            problem_type="payload-too-large",
        ) from exc
    except SigningKeyUnavailableError as exc:
        # Caught *before* `VerificationError`, which it subclasses. This is the
        # one refusal that is genuinely transient: the token may well be
        # perfect, and answering it like a forgery would silently drop real
        # messages for the length of a Google outage. Non-2xx, so Pub/Sub brings
        # it back.
        await logger.awarning("gchat.signing_keys_unavailable", provider=PROVIDER)
        raise ProblemDetailError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="Verification temporarily unavailable",
            detail="The push token could not be verified right now. Retry.",
            problem_type="verification-unavailable",
        ) from exc
    except VerificationError as exc:
        # The reason is ours — "missing authorization header", "unexpected
        # service account" — and never the payload. The *response* says none of
        # it.
        await logger.awarning("gchat.push_rejected", provider=PROVIDER, reason=str(exc))
        raise _unauthorised() from exc
    except SourceMetadataError as exc:
        # A malformed envelope, an unknown subscription, or missing CloudEvent
        # attributes — refused after verification rather than before, so a
        # malformed body and a forged one are indistinguishable from outside.
        raise _unauthorised() from exc

    return await _receive(event, request=request, response=response, db=db)


async def _receive(
    event: VerifiedEvent, *, request: Request, response: Response, db: AsyncSession
) -> dict[str, str]:
    """Everything after verification.

    Split from the endpoint so the HTTP-shaped concerns stay in one place and
    this reads as the sequence the module docstring describes.
    """
    envelope = read_push(event.body)

    recent: RecentMessageIds = request.app.state.gchat_recent_messages
    if recent.seen(envelope.message_id):
        # The in-process fast path, and an optimisation only: at-least-once
        # delivery makes redelivery normal, and recognising it here saves a
        # database round trip inside a budget that cannot be extended. The
        # unique constraint below is what actually makes a redelivery one unit
        # of work — see `pubsub.RecentMessageIds`.
        return _acknowledged(response, "duplicate")

    chat = read_event(envelope.data, event_type=envelope.attribute(CE_TYPE_ATTRIBUTE))
    if chat is None:
        # A reaction, a membership change, a space update, or a body that no
        # longer parses. Acknowledged: it will not parse differently in a
        # minute, and the reason is a bounded value rather than anything read
        # out of the payload.
        await logger.ainfo(
            "gchat.event_ignored",
            provider=PROVIDER,
            reason="unsupported_event_type",
        )
        return _acknowledged(response, "ignored")

    decision = read_message(chat)
    if isinstance(decision, DroppedMessage):
        # A bot's message — including CAIRN's own, which is how the loop stays
        # closed — or a payload with no usable identity.
        await logger.ainfo(
            "gchat.event_ignored",
            provider=PROVIDER,
            reason=decision.reason.value,
        )
        return _acknowledged(response, "ignored")

    # The space name comes from the verified payload's message resource name and
    # is looked up against a mapping only an authenticated connect flow may
    # write. Nothing else in the body can influence which workspace this becomes:
    # a payload claiming a tenant, a customer or another space is data, not
    # authority.
    subscription = await _registry(request, db).subscription_for(decision.space_name)
    if subscription is None or not subscription.active:
        # Unknown, unselected, deselected, disconnected, revoked or expired —
        # one decision from here: do not read this space. Nothing above this line
        # has stored the payload, written a delivery row, published a job or
        # named the space anywhere, which is the control: a check that ran after
        # the insert would leave the message in a table nobody consented to it
        # being in.
        #
        # Acknowledged rather than refused, because it is permanent. A non-2xx
        # would bring the same message back every minute for a week.
        await logger.ainfo("gchat.space_not_permitted", provider=PROVIDER)
        return _acknowledged(response, "rejected")

    return await _ingest(
        event,
        chat,
        decision,
        envelope,
        subscription=subscription,
        request=request,
        response=response,
        db=db,
    )


async def _ingest(
    event: VerifiedEvent,
    chat: ChatEvent,
    message: ChatMessage,
    envelope: PushEnvelope,
    *,
    subscription: SpaceSubscription,
    request: Request,
    response: Response,
    db: AsyncSession,
) -> dict[str, str]:
    """Record, enqueue, and report health."""
    tenant = ResolvedTenant(
        tenant_id=subscription.tenant_id,
        # The space, not a Google account id: the two Chat scopes CAIRN requests
        # carry no account identity at all, and the space is what the selection
        # was made against.
        external_account_id=subscription.space_name,
    )

    delivery_id = event.idempotency_key.value

    if not await _record_delivery(
        db,
        tenant=tenant,
        delivery_id=delivery_id,
        event_type=chat.event_type,
        action=message.action.value,
        payload=stored_payload(chat),
    ):
        # The unique constraint rejected it: a redelivery of a push we already
        # hold, or a *re-publish* of the same event under a different
        # `messageId`. The key is a digest over the CloudEvent id and the message
        # resource name precisely so the second case dedupes too — see
        # `pubsub.GoogleChatPush.idempotency_key`.
        await logger.ainfo(
            "gchat.duplicate_event",
            delivery_id=delivery_id,
            tenant_id=str(tenant.tenant_id),
        )
        recent: RecentMessageIds = request.app.state.gchat_recent_messages
        recent.remember(envelope.message_id)
        return _acknowledged(response, "duplicate")

    # Honest health, on the one path where data actually arrived.
    connection = await db.scalar(
        select(SourceConnection).where(SourceConnection.id == subscription.connection_id)
    )
    if connection is not None:
        await record_healthy_delivery(connection)

    # Committed before the enqueue. Acknowledging first would let a rollback
    # erase work Google believes we already hold, and an acknowledged Pub/Sub
    # message is never re-sent.
    await db.commit()

    await enqueue(
        request.app.state.queue,
        event,
        tenant,
        job_type=GCHAT_EVENT_JOB,
        payload=job_payload(event),
        priority=Priority.STANDARD,
    )

    # Remembered only now, and only for a delivery that was actually taken.
    # Remembering a refused one would acknowledge a message nobody stored.
    recent = request.app.state.gchat_recent_messages
    recent.remember(envelope.message_id)

    await logger.ainfo(
        "gchat.event_accepted",
        delivery_id=delivery_id,
        action=message.action.value,
        tenant_id=str(tenant.tenant_id),
    )
    return {"status": "accepted"}


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

    `ON CONFLICT DO NOTHING`, not select-then-insert: Pub/Sub's backoff starts at
    100ms, so a redelivery can arrive while the first is still in flight, and two
    concurrent inserts of one key would both find nothing and the second would
    abort the transaction.

    `webhook_deliveries` is reused rather than duplicated for Chat, exactly as it
    is for Slack. It already holds "one inbound delivery, its payload, its tenant
    and its status" under row-level security, and a third table would mean a
    third place to get isolation and retention right for the same shape of data.
    """
    statement = (
        insert(WebhookDelivery)
        .values(
            tenant_id=tenant.tenant_id,
            delivery_id=delivery_id,
            event_type=event_type[:64],
            action=action[:64],
            # Chat spaces are resource names, not numbers; this column is a
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


def _registry(request: Request, db: AsyncSession) -> SpaceRegistry:
    """The space selection store, or the one that reads the selection table.

    The override exists so the connect flow can bind its own reader without this
    module importing it, and so a test can state a selection directly. The
    default is not a permissive fallback: it resolves against
    `google_chat_space_selections` and treats absence — and its own
    unavailability — as "not selected".
    """
    override: SpaceRegistry | None = getattr(request.app.state, "gchat_space_registry", None)
    if override is not None:
        return override
    return StoredSpaceRegistry(db=db)


def _verifier(request: Request) -> GoogleChatPush:
    """The push verifier, configured from app state or the environment.

    Every value is required and none is derived from the request. In particular
    the audience is **never** defaulted to the endpoint URL: a URL is decided by
    a proxy, a rewrite or a `Host` header, and a verifier that compares a token
    against something an attacker can influence is not verifying. Absent
    configuration is a refusal of every request, not an acceptance of any — see
    `GoogleChatPush._require_configuration`.
    """
    state = request.app.state
    return GoogleChatPush(
        audience=configured_audience(getattr(state, "gchat_push_audience", None)),
        service_account_email=configured_service_account(
            getattr(state, "gchat_push_service_account", None)
        ),
        subscription=configured_subscription(getattr(state, "gchat_push_subscription", None)),
        keys=_signing_keys(request),
    )


def _signing_keys(request: Request) -> SigningKeys:
    """Google's key set, cached across requests.

    Process-wide rather than per app instance, because the cache is the whole
    point: a fresh client per request would fetch the JWKS on every push and
    spend the acknowledgement budget on Google's network rather than ours.
    """
    override: SigningKeys | None = getattr(request.app.state, "gchat_signing_keys", None)
    if override is not None:
        return override
    return _google_jwks()


@lru_cache(maxsize=1)
def _google_jwks() -> GoogleJwks:
    return GoogleJwks()


def _acknowledged(response: Response, outcome: str) -> dict[str, str]:
    """Acknowledge, and stop.

    Used for every *permanent* outcome that is not an accepted message: a
    duplicate, a drop, an unpermitted space. All of them are 2xx because Pub/Sub
    would otherwise redeliver a decision that will not change.
    """
    response.status_code = ACKNOWLEDGED
    return {"status": outcome}


def _unauthorised() -> ProblemDetailError:
    """One response for every verification failure.

    Undifferentiated on purpose: a forger who learns *which* claim of their
    forgery was wrong learns how to fix it. A malformed envelope is answered the
    same way for the same reason.
    """
    return ProblemDetailError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Invalid push token",
        detail="The request could not be verified.",
        problem_type="invalid-signature",
    )


__all__ = ["install", "router"]
