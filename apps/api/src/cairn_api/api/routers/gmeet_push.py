"""Google Meet event receipt: verify → resolve → **re-gate** → record → acknowledge.

The fourth unauthenticated write endpoint in the service, and it follows the same
order as the first three because that order is the shared contract in
`ingestion/receipt.py`: correlation id bound before verification, size cap before
the crypto, verification before anything parses, tenant from a stored record and
never from the body, idempotency committed before anything else happens.

Two things are genuinely different here, and both are about consent rather than
about transport.

**There is a gate after the tenancy lookup, and it is Step 35's.** For Google
Chat the stored space selection *is* the permission, so resolving the tenant and
checking the permission are one query. For Meet the stored subscription is only a
lease; the permission is a `MeetingCaptureRequest` whose every participant agreed
— and the whole point of withdrawal is that it can happen after the subscription
was created and before the transcript exists. So `meetings.guard.permit_collection`
runs **inside the recording transaction**, and a refusal writes nothing at all.
An announcement for a meeting somebody withdrew from therefore leaves no row, no
log line naming it, and no trace.

**Nothing is fetched here.** The endpoint records that Google said a transcript
file exists — the meeting it belongs to, the subscription that delivered it, a
digest of the artifact's name, and the time — and, for a workspace that has taken
Step 36B's *separate* transcript-access consent action, that the artifact is
available to retrieve. It does not read the transcript: this handler answers
Pub/Sub inside an acknowledgement deadline, and a download in that path would
either blow the deadline or be abandoned halfway. The retrieval pass does the
work, and re-runs the entire consent gate when it does, because minutes will have
passed.

For a workspace that has **not** granted transcript access — the normal state —
`retrieval.record_availability` writes nothing at all, not even an encrypted
reference, so Step 36A's promise that the pointer is not lying around holds
unchanged for everybody who has not asked for it to be.

**Only 102, 200, 201, 202 and 204 acknowledge.** Everything else is a NACK and
Pub/Sub redelivers with a backoff until the message expires or dead-letters. A
*permanent* refusal — an unknown subscription, a torn-down lease, a withdrawn
consent, an event type CAIRN does not subscribe to — must answer **2xx**, because
redelivering it would produce the same refusal every minute for a week. A
*transient* failure — Google's key set unreachable, the database down — must
answer non-2xx so the message comes back. Getting this backwards in either
direction is the bug.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache

import structlog
from fastapi import APIRouter, FastAPI, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import PlatformDb
from cairn_api.api.errors import ProblemDetailError
from cairn_api.db.connector_models import SourceConnection
from cairn_api.db.gmeet_models import (
    GoogleMeetArtifactKind,
    GoogleMeetArtifactSignal,
    GoogleMeetSubscription,
)
from cairn_api.gmeet import retrieval
from cairn_api.gmeet.pubsub import (
    CE_TYPE_ATTRIBUTE,
    MAX_PAYLOAD_BYTES,
    PROVIDER,
    TRANSCRIPT_READY_EVENT,
    GoogleJwks,
    GoogleMeetPush,
    MeetSubscription,
    SigningKeys,
    SigningKeyUnavailableError,
    StoredSubscriptionRegistry,
    SubscriptionRegistry,
    artifact_digest,
    artifact_name_of,
    configured_audience,
    configured_service_account,
    configured_subscription,
    read_push,
    record_healthy_delivery,
    subscription_name_of,
)
from cairn_api.ingestion import (
    InboundRequest,
    Ingestor,
    PayloadTooLargeError,
    SourceMetadataError,
    VerificationError,
    VerifiedEvent,
)
from cairn_api.meetings.guard import CollectionRefusedError, permit_collection

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: The one status this endpoint uses to mean "taken, and nothing more will happen
#: here". 200 rather than 204 so a refusal can still say *why* in a body an
#: operator can read in the Pub/Sub console; both acknowledge identically.
ACKNOWLEDGED = status.HTTP_200_OK


def install(app: FastAPI, *, prefix: str) -> None:
    """Mount the endpoint.

    There is deliberately no job type registered alongside it, unlike
    `gchat_push.install`: Step 36A publishes no work. A job here would be a
    worker with a transcript resource name in its payload, which is the one thing
    this step is built not to hold.

    That reasoning survived the gap being closed. Transcripts now become facts -
    `gmeet/understanding.py`, on the worker's maintenance loop, consent
    re-checked inside the reading transaction - and still nothing is published
    from here, because the raw table grants the application role nothing and the
    property above (no transcript identifier in any broker payload) holds
    structurally when there is no payload at all.
    """
    from cairn_api.gchat.pubsub import RecentMessageIds

    app.include_router(router, prefix=prefix)
    # Per application instance rather than per process: it is a cache, and two
    # apps in one test session sharing one would make a delivery to the first
    # look like a duplicate to the second. `gmeet_`-prefixed, so it cannot be
    # confused with Chat's.
    app.state.gmeet_recent_messages = RecentMessageIds()


@router.post(
    "/google-meet",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a Google Meet event from Pub/Sub",
    include_in_schema=False,
    responses={
        200: {"description": "Acknowledged: a duplicate, a drop, or a permanent refusal."},
        202: {"description": "Verified, gated and recorded."},
        401: {"description": "The push token did not verify, or the envelope was malformed."},
        413: {"description": "Payload too large."},
        503: {"description": "Google's key set was unreachable; Pub/Sub should redeliver."},
    },
)
async def receive_meet_event(
    request: Request,
    response: Response,
    db: PlatformDb,
) -> dict[str, str]:
    """Accept a Google Meet event.

    Excluded from the OpenAPI schema for the same reason the other inbound
    endpoints are: it is Google's interface, not the frontend's, and publishing it
    would put an unauthenticated write path into the generated client.
    """
    ingestor = Ingestor(
        name=PROVIDER,
        provider=_verifier(request),
        max_body_bytes=MAX_PAYLOAD_BYTES,
    )

    inbound = InboundRequest(body=await request.body(), headers=dict(request.headers))

    try:
        # Correlation id, size cap, then the token — in that order, and all of it
        # before a single byte of the Meet payload is parsed.
        event = ingestor.accept(inbound)
    except PayloadTooLargeError as exc:
        raise ProblemDetailError(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            title="Payload too large",
            detail=f"Google Meet push payloads are limited to {MAX_PAYLOAD_BYTES} bytes.",
            problem_type="payload-too-large",
        ) from exc
    except SigningKeyUnavailableError as exc:
        # Caught *before* `VerificationError`, which it subclasses. This is the
        # one refusal that is genuinely transient, and answering it like a forgery
        # would silently drop real announcements for the length of a Google
        # outage. Non-2xx, so Pub/Sub brings it back.
        await logger.awarning("gmeet.signing_keys_unavailable", provider=PROVIDER)
        raise ProblemDetailError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            title="Verification temporarily unavailable",
            detail="The push token could not be verified right now. Retry.",
            problem_type="verification-unavailable",
        ) from exc
    except VerificationError as exc:
        # The reason is ours — "missing authorization header", "unexpected service
        # account" — and never the payload. The *response* says none of it.
        await logger.awarning("gmeet.push_rejected", provider=PROVIDER, reason=str(exc))
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
    """Everything after verification, in the order the module docstring describes."""
    envelope = read_push(event.body)

    recent = request.app.state.gmeet_recent_messages
    if recent.seen(envelope.message_id):
        # The in-process fast path, and an optimisation only: at-least-once
        # delivery makes redelivery normal, and recognising it here saves a
        # database round trip inside a budget that cannot be extended. The unique
        # constraint below is what actually makes a redelivery one unit of work.
        return _acknowledged(response, "duplicate")

    ce_type = envelope.attribute(CE_TYPE_ATTRIBUTE)
    if ce_type != TRANSCRIPT_READY_EVENT:
        # A participant event, a recording, smart notes, a conference lifecycle
        # event — none of which CAIRN subscribes to, and every one of which is
        # dropped here as well as excluded there. Two closed lists rather than
        # one, so a widened subscription still ingests nothing.
        #
        # Acknowledged: it will not become a different event type in a minute, and
        # the reason is a bounded value rather than anything read out of the body.
        await logger.ainfo(
            "gmeet.event_ignored", provider=PROVIDER, reason="unsupported_event_type"
        )
        return _acknowledged(response, "ignored")

    subscription_name = subscription_name_of(envelope)
    if subscription_name is None:
        # A push that cannot name the subscription that produced it cannot be
        # resolved to a workspace, and there is no fallback that is not a guess.
        await logger.ainfo("gmeet.event_ignored", provider=PROVIDER, reason="no_subscription")
        return _acknowledged(response, "ignored")

    # The tenancy decision, from a row only an authenticated, consent-gated flow
    # may write. Nothing in the body can influence which workspace this becomes.
    stored = await _registry(request, db).subscription_for(subscription_name)
    if stored is None or not stored.active:
        # Unknown, torn down, expired, disconnected or revoked — one decision from
        # here. Nothing above this line has written a row, named a meeting or
        # stored a byte of the payload, which is the control: a check that ran
        # after the insert would leave the announcement in a table nobody
        # consented to it being in.
        await logger.ainfo("gmeet.subscription_not_permitted", provider=PROVIDER)
        return _acknowledged(response, "rejected")

    return await _record(
        event, envelope_data=envelope.data, stored=stored, request=request, response=response, db=db
    )


async def _record(
    event: VerifiedEvent,
    *,
    envelope_data: bytes,
    stored: MeetSubscription,
    request: Request,
    response: Response,
    db: AsyncSession,
) -> dict[str, str]:
    """Re-check consent, then record the announcement and nothing else."""
    delivery_id = event.idempotency_key.value

    # --- The gate, inside the transaction that would do the writing ----------
    #
    # Re-run rather than inferred from the subscription's existence. Between the
    # create and this delivery a participant can have withdrawn, declined, been
    # added, or the meeting can have moved, been cancelled, or had its policy
    # wording changed — and every one of those means this announcement must not
    # be recorded. `permit_collection` refuses anything short of unanimous,
    # current, unexpired agreement, and logs its reason as a bounded category
    # with no meeting in it.
    try:
        permit = await permit_collection(
            db, tenant_id=stored.tenant_id, meeting_id=stored.meeting_id
        )
    except CollectionRefusedError:
        # Acknowledged, because it is permanent: consent does not un-withdraw, and
        # a non-2xx would bring the same announcement back every minute for a
        # week. Nothing is written — not the digest, not a delivery row, not a
        # health update.
        await logger.ainfo("gmeet.collection_refused_at_receipt", provider=PROVIDER)
        return _acknowledged(response, "rejected")

    # Read for the digest and immediately hashed. The resource name itself does
    # not reach a variable that outlives this function, a column, or a log field.
    name = artifact_name_of(envelope_data)
    if name is None:
        # A transcript announcement with no artifact name is a shape this client
        # is not built for. Acknowledged rather than retried: it will not parse
        # differently in a minute.
        await logger.ainfo("gmeet.event_ignored", provider=PROVIDER, reason="no_artifact")
        return _acknowledged(response, "ignored")

    signal = await _record_signal(
        db,
        tenant_id=stored.tenant_id,
        subscription_id=stored.subscription_id,
        meeting_id=stored.meeting_id,
        digest=artifact_digest(name),
    )
    if signal is None:
        # The unique constraint rejected it: a redelivery, or a *re-publish* of
        # the same announcement under a different `messageId`.
        await logger.ainfo(
            "gmeet.duplicate_event",
            delivery_id=delivery_id,
            tenant_id=str(stored.tenant_id),
        )
        request.app.state.gmeet_recent_messages.remember(_message_id(event))
        return _acknowledged(response, "duplicate")

    # --- Step 36B: availability, on the far side of the same gate ------------
    #
    # Passed the permit obtained above rather than re-deriving one, so the record
    # is provably the same consent decision this transaction already checked.
    # Writes nothing at all on a workspace that has not taken the separate
    # transcript-access consent action, which is the normal state — so Step 36A's
    # promise holds unchanged for everybody who has not granted it.
    #
    # **Nothing is downloaded here.** This endpoint answers Pub/Sub inside an
    # acknowledgement deadline, and a download in that path would either blow the
    # deadline or be abandoned halfway. The retrieval pass picks the row up, and
    # re-runs the entire gate when it does, because minutes will have passed.
    await retrieval.record_availability(
        db,
        permit=permit,
        signal=signal,
        connection_id=stored.connection_id,
        artifact_reference=name,
    )

    await _touch_subscription(db, subscription_id=stored.subscription_id)

    # Honest health, on the one path where a delivery was actually accepted.
    connection = await db.scalar(
        select(SourceConnection).where(SourceConnection.id == stored.connection_id)
    )
    if connection is not None:
        await record_healthy_delivery(connection)

    await db.commit()

    # Remembered only now, and only for a delivery that was actually taken.
    request.app.state.gmeet_recent_messages.remember(_message_id(event))

    await logger.ainfo(
        "gmeet.event_accepted",
        delivery_id=delivery_id,
        tenant_id=str(stored.tenant_id),
        # The kind, not the artifact. There is one kind, and naming it is what
        # makes "a transcript existed" auditable without naming which.
        kind=GoogleMeetArtifactKind.TRANSCRIPT.value,
    )
    return {"status": "accepted"}


def _message_id(event: VerifiedEvent) -> str:
    """Pub/Sub's delivery id for the in-process fast path."""
    return read_push(event.body).message_id


async def _record_signal(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    meeting_id: uuid.UUID,
    digest: str,
) -> GoogleMeetArtifactSignal | None:
    """Write the announcement. ``None`` if it already existed.

    `ON CONFLICT DO NOTHING`, not select-then-insert: Pub/Sub's backoff starts at
    100ms, so a redelivery can arrive while the first is still in flight, and two
    concurrent inserts of one key would both find nothing and the second would
    abort the transaction.

    **`webhook_deliveries` is deliberately not reused here**, unlike the Chat and
    Slack receivers. That table has a `payload` column, and it exists to hold the
    inbound body so a worker can process it later. There must be no stored body:
    the announcement is recorded and the push payload is not, and a table with
    nowhere to put it is what makes that true of the data rather than of the code.
    Step 36B's retrieval reads the artifact from Google under its own consent,
    never a payload replayed out of a receipt row.
    """
    statement = (
        insert(GoogleMeetArtifactSignal)
        .values(
            tenant_id=tenant_id,
            subscription_id=subscription_id,
            meeting_id=meeting_id,
            kind=GoogleMeetArtifactKind.TRANSCRIPT,
            artifact_digest=digest,
            announced_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_google_meet_artifact_signals_digest")
        .returning(GoogleMeetArtifactSignal.id)
    )
    signal_id = await db.scalar(statement)
    if signal_id is None:
        return None
    # Re-read rather than constructed from the values above: the row is what the
    # retrieval record is built against, and a hand-built copy that drifted from
    # it would be a provenance chain that agrees with itself and not with the
    # database.
    signal: GoogleMeetArtifactSignal | None = await db.scalar(
        select(GoogleMeetArtifactSignal).where(GoogleMeetArtifactSignal.id == signal_id)
    )
    return signal


async def _touch_subscription(db: AsyncSession, *, subscription_id: uuid.UUID) -> None:
    """Record that this lease actually delivered something.

    `last_event_at` is the field that distinguishes a lease which is ACTIVE and
    silent from one that is working, and it is set only where a delivery was
    accepted.
    """
    subscription = await db.scalar(
        select(GoogleMeetSubscription).where(GoogleMeetSubscription.id == subscription_id)
    )
    if subscription is not None:
        subscription.last_event_at = datetime.now(UTC)


def _registry(request: Request, db: AsyncSession) -> SubscriptionRegistry:
    """The subscription store, or the one that reads the subscription table.

    The override exists so a test can state a subscription directly. The default
    is not a permissive fallback: it resolves against `google_meet_subscriptions`
    and treats absence — and its own unavailability — as "not ours".
    """
    override: SubscriptionRegistry | None = getattr(
        request.app.state, "gmeet_subscription_registry", None
    )
    if override is not None:
        return override
    return StoredSubscriptionRegistry(db=db)


def _verifier(request: Request) -> GoogleMeetPush:
    """The push verifier, configured from Meet's app state or Meet's environment.

    Every value is required and none is derived from the request. In particular
    the audience is **never** defaulted to the endpoint URL, and none of these
    falls back to the Google Chat receiver's configuration: a token minted for
    Chat's push subscription must not verify here.
    """
    state = request.app.state
    return GoogleMeetPush(
        audience=configured_audience(getattr(state, "gmeet_push_audience", None)),
        service_account_email=configured_service_account(
            getattr(state, "gmeet_push_service_account", None)
        ),
        subscription=configured_subscription(getattr(state, "gmeet_push_subscription", None)),
        keys=_signing_keys(request),
    )


def _signing_keys(request: Request) -> SigningKeys:
    """Google's key set, cached across requests.

    Process-wide rather than per app instance, because the cache is the whole
    point. Shared with the Chat receiver deliberately: it is Google's *public*
    key set, the same document verifies both streams, and two caches would mean
    two JWKS fetches on every rotation for no gain.
    """
    override: SigningKeys | None = getattr(request.app.state, "gmeet_signing_keys", None)
    if override is not None:
        return override
    return _google_jwks()


@lru_cache(maxsize=1)
def _google_jwks() -> GoogleJwks:
    return GoogleJwks()


def _acknowledged(response: Response, outcome: str) -> dict[str, str]:
    """Acknowledge, and stop.

    Used for every *permanent* outcome that is not an accepted announcement: a
    duplicate, a drop, an unknown subscription, a withdrawn consent. All of them
    are 2xx because Pub/Sub would otherwise redeliver a decision that will not
    change.
    """
    response.status_code = ACKNOWLEDGED
    return {"status": outcome}


def _unauthorised() -> ProblemDetailError:
    """One response for every verification failure.

    Undifferentiated on purpose: a forger who learns *which* claim of their
    forgery was wrong learns how to fix it.
    """
    return ProblemDetailError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Invalid push token",
        detail="The request could not be verified.",
        problem_type="invalid-signature",
    )


__all__ = ["install", "router"]
