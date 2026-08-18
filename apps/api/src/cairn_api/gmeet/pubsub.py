"""Google Meet's half of the ingestion contract: the JWT, the subscription, the meeting.

The same shape as `gchat/pubsub.py`, and for the same reason: Cloud Pub/Sub
attaches an OIDC bearer token to a push, and **that token authenticates the
caller, not the body**. It says "Google's push subsystem, on the subscription you
configured, sent this" and says nothing at all about the JSON underneath.
Everything below follows from that.

Three things are deliberately *not* shared with the Chat receiver, and each one
is a silent failure if it is.

**The configuration.** ``CAIRN_GMEET_PUSH_AUDIENCE``,
``CAIRN_GMEET_PUSH_SERVICE_ACCOUNT`` and ``CAIRN_GMEET_PUSH_SUBSCRIPTION``, with
``app.state.gmeet_*`` overrides. Reusing Chat's would mean a token minted for
Chat's push subscription verifies at Meet's endpoint — the audience and the
service account would both match, and the only thing left standing between the
two streams would be the subscription-name comparison, which is the check most
likely to be relaxed by somebody debugging a delivery.

**The provider label.** :data:`PROVIDER` is ``"google_meet"``. It reaches spans,
log fields, ``SourceMetadata.provider`` and — critically —
``IdempotencyKey.derive``. Importing Chat's would label every Meet event as Chat
*and* let a Meet announcement dedupe against a Chat message that happened to
digest the same, which is a dropped event with no error anywhere.

**The tenancy lookup.** Chat resolves a space name to a selection row. Meet
resolves the **subscription resource name** to a stored, active,
tenant-scoped subscription — and then re-runs Step 35's consent gate inside the
transaction before recording anything. A stored subscription is not a standing
permission; the capture request is, and it can be withdrawn between the create
and the delivery.

What *is* shared, deliberately, is Google's key set: the JWKS client is fetched
and cached process-wide, and two receivers verifying against one copy of Google's
public keys is correct and cheaper than two.

**Nothing here fetches an artifact.** The payload is read for exactly one thing —
the resource name of the transcript file Google says exists — and that name is
immediately hashed. There is no code path in this module, or reachable from it,
that turns the announcement into a request for content.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import jwt
import structlog
from jwt.exceptions import PyJWTError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.connector_models import ConnectionHealth, ConnectorProvider, SourceConnection
from cairn_api.gchat.pubsub import (
    ACCEPTED_ISSUERS,
    CE_ID_ATTRIBUTE,
    CE_TYPE_ATTRIBUTE,
    SIGNING_ALGORITHM,
    GoogleJwks,
    PushEnvelope,
    RecentMessageIds,
    SigningKeys,
    SigningKeyUnavailableError,
    read_push,
)
from cairn_api.ingestion import (
    IdempotencyKey,
    InboundRequest,
    SourceMetadata,
    SourceMetadataError,
    VerificationError,
)

logger = structlog.get_logger(__name__)

#: This provider's name in `SourceMetadata`, on spans, in logs, and inside the
#: idempotency digest. Lowercase and ours, matching
#: `ConnectorProvider.GOOGLE_MEET` — and deliberately **not** imported from
#: `gchat/pubsub.py`, where the identical constant says ``google_chat``.
PROVIDER: Final = "google_meet"

AUTHORIZATION_HEADER: Final = "Authorization"
BEARER_SCHEME: Final = "bearer"

#: The CloudEvent attribute naming the Workspace Events subscription that
#: produced this event: ``//workspaceevents.googleapis.com/subscriptions/{id}``.
#:
#: This is the tenancy key, and it is an *attribute* rather than a payload field
#: on purpose — it is set by Workspace Events rather than by anything inside the
#: meeting, so a body claiming a different subscription is data, not authority.
CE_SOURCE_ATTRIBUTE: Final = "ce-source"

#: The prefix stripped off `ce-source` to recover ``subscriptions/{id}``.
SUBSCRIPTION_SOURCE_PREFIX: Final = "//workspaceevents.googleapis.com/"

#: The one CloudEvent type this receiver accepts.
#:
#: Restated here rather than imported from `subscriptions.py` so that the
#: *receiving* side has its own closed list: a widened subscription would then
#: still be dropped at the door, and the two lists disagreeing is a test failure
#: rather than an event nobody expected being ingested.
TRANSCRIPT_READY_EVENT: Final = "google.workspace.meet.transcript.v2.fileGenerated"

#: A Meet announcement is a few hundred bytes. Capped far below the shared
#: default because this endpoint is unauthenticated at the transport level and
#: decodes whatever it is handed.
MAX_PAYLOAD_BYTES: Final = 256 * 1024

#: Configuration, read from the environment when `app.state` does not carry it.
#: **Meet's own variables.** Absent, verification refuses everything: an unset
#: audience or service account makes every token acceptable, so failing closed is
#: the only safe reading.
AUDIENCE_VAR: Final = "CAIRN_GMEET_PUSH_AUDIENCE"
SERVICE_ACCOUNT_VAR: Final = "CAIRN_GMEET_PUSH_SERVICE_ACCOUNT"
SUBSCRIPTION_VAR: Final = "CAIRN_GMEET_PUSH_SUBSCRIPTION"


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoogleMeetPush:
    """Verify a Pub/Sub push, and name the Meet event it carries.

    Implements `InboundProvider`. Everything after this — the idempotency ledger,
    the consent re-check, the receipt row — is in `api/routers/gmeet_push.py`.
    """

    #: The audience configured **on the Meet push subscription**. Required, and
    #: never defaulted to the endpoint URL: a URL is decided by a proxy, a
    #: rewrite or a `Host` header, and a verifier that compares a token against
    #: something an attacker can influence is not verifying.
    audience: str

    #: The service account Pub/Sub was told to sign as, checked against `email`.
    service_account_email: str

    #: The full subscription resource name we expect
    #: (``projects/P/subscriptions/S``). A valid Google token proves Google sent
    #: the request; this proves it came from *our* subscription rather than from
    #: some other project's, pointed at our URL by whoever owns it.
    subscription: str

    keys: SigningKeys

    #: Clock skew allowance on `exp`. Zero by default — Google's tokens are valid
    #: for an hour, so nothing legitimate needs the slack.
    leeway_seconds: float = 0.0

    # -- verification -------------------------------------------------------

    def verify(self, request: InboundRequest) -> None:
        """Prove the push came from our subscription, before anything parses it.

        Six checks, and all six are required: signature, audience, expiry,
        issuer, publisher address, and that the issuer vouched for that address.
        Each one alone is bypassable — a signature with no `aud` check accepts a
        token minted for somebody else's endpoint; an `aud` check with no `email`
        check accepts a token from any service account pointed here; an `email`
        check with no `email_verified` check accepts an address the issuer itself
        would not vouch for.
        """
        self._require_configuration()

        token = self._bearer_token(request)

        # The key is chosen from the token's `kid`, and the algorithm is *not*
        # taken from the token: `algorithms=[RS256]` below is what makes
        # `alg: none` and the HS256-with-a-public-key confusion impossible.
        key = self.keys.public_key(token)

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[SIGNING_ALGORITHM],
                audience=self.audience,
                leeway=self.leeway_seconds,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    # A token with no `exp` never expires, and a token with no
                    # `aud` verifies against every audience. Both are absences
                    # rather than mismatches, which is exactly the class of
                    # failure a verifier misses unless told to require the claim.
                    "require": ["exp", "iat", "aud", "iss"],
                },
            )
        except PyJWTError as exc:
            # One exception for every mode, so a forger who gets a rejection
            # learns nothing about which part of the forgery was wrong.
            msg = "The push token did not verify"
            raise VerificationError(msg) from exc

        self._check_identity(claims)

    def _require_configuration(self) -> None:
        """Refuse everything if we do not know what to compare against.

        A blank audience makes every token's audience acceptable and a blank
        service account makes every caller acceptable, so a misconfigured
        deployment must reject Google rather than accept everyone.
        """
        if not self.audience:
            msg = "No Google Meet push audience is configured"
            raise VerificationError(msg)
        if not self.service_account_email:
            msg = "No Google Meet push service account is configured"
            raise VerificationError(msg)
        if not self.subscription:
            msg = "No Google Meet push subscription is configured"
            raise VerificationError(msg)

    def _bearer_token(self, request: InboundRequest) -> str:
        """The token, or a refusal.

        The catastrophic implementation is `if token: verify(token)`, which
        accepts every request that simply omits the header.
        """
        header = request.header(AUTHORIZATION_HEADER)
        if not header:
            msg = "Missing authorization header"
            raise VerificationError(msg)

        scheme, separator, remainder = header.partition(" ")
        token = remainder.strip()
        if not separator or scheme.strip().lower() != BEARER_SCHEME or not token:
            msg = "Authorization is not a bearer token"
            raise VerificationError(msg)
        return token

    def _check_identity(self, claims: Mapping[str, Any]) -> None:
        """Issuer, service account address, and that the address was verified.

        Checked after the signature rather than before, because a claim from an
        unverified token is a string an attacker chose.
        """
        issuer = claims.get("iss")
        if not isinstance(issuer, str) or issuer not in ACCEPTED_ISSUERS:
            msg = "The push token names an unexpected issuer"
            raise VerificationError(msg)

        email = claims.get("email")
        # Case-insensitively: addresses are not case-sensitive, and a
        # configuration written with different capitalisation would otherwise
        # reject every real delivery.
        if not isinstance(email, str) or email.casefold() != self.service_account_email.casefold():
            msg = "The push token names an unexpected service account"
            raise VerificationError(msg)

        if not _is_true(claims.get("email_verified")):
            msg = "The push token's service account address is not verified"
            raise VerificationError(msg)

    # -- naming -------------------------------------------------------------

    def read_source(self, request: InboundRequest) -> SourceMetadata:
        """Name the delivery, from the verified request.

        Runs only after `verify`, so parsing here is parsing something Google
        sent. The order inside is load-bearing: the envelope is decoded, the
        **subscription identity** is checked, and only then are the CloudEvent
        attributes read.
        """
        envelope = read_push(request.body)

        if envelope.subscription != self.subscription:
            # Google signed it, but not for us. Somebody else's subscription
            # pointed at our endpoint would otherwise deliver their traffic into
            # our tenancy lookup.
            msg = "The push named an unexpected subscription"
            raise SourceMetadataError(msg)

        ce_type = envelope.attribute(CE_TYPE_ATTRIBUTE)
        ce_id = envelope.attribute(CE_ID_ATTRIBUTE)
        if ce_type is None or ce_id is None:
            # A push that cannot name itself cannot be recorded idempotently,
            # which makes it unsafe to accept rather than merely unusual.
            msg = "A Meet push must carry ce-type and ce-id attributes"
            raise SourceMetadataError(msg)

        return SourceMetadata(
            provider=PROVIDER,
            event_type=ce_type[:64],
            # Pub/Sub's delivery id. Recorded because it is what an operator sees
            # in the console — *not* used as the idempotency key.
            external_event_id=envelope.message_id,
        )

    def idempotency_key(self, request: InboundRequest, source: SourceMetadata) -> IdempotencyKey:
        """A digest over the CloudEvent id and the announced artifact's name.

        Not `messageId`. That value is stable across redeliveries of one publish
        and unstable across a *re-publish* of the same event, so keying on it
        means one transcript announcement can be recorded twice.

        `provider=PROVIDER` is what keeps this namespace disjoint from the Chat
        receiver's. Two connectors deriving keys from the same provider string
        can collide, and the visible symptom is a real event silently treated as
        a duplicate.
        """
        envelope = read_push(request.body)
        ce_id = envelope.attribute(CE_ID_ATTRIBUTE) or ""

        # Best effort: a payload whose artifact name does not decode still needs
        # a stable key, and the raw bytes are stable for the same delivery.
        # `\x00` cannot occur in either identifier, so the two fields cannot be
        # re-split into a different pair with the same digest.
        identity = artifact_name_of(envelope.data)
        tail = identity.encode("utf-8") if identity is not None else envelope.data

        return IdempotencyKey.derive(
            provider=PROVIDER,
            external_account_id=None,
            event_type=source.event_type,
            body=ce_id.encode("utf-8") + b"\x00" + tail,
        )


def subscription_name_of(envelope: PushEnvelope) -> str | None:
    """``subscriptions/{id}`` from the push's ``ce-source``, or nothing.

    The **only** thing on an inbound push that decides which workspace this is,
    and it is taken from a CloudEvent attribute Workspace Events sets rather than
    from anything inside the meeting payload.

    Returns ``None`` for an absent, malformed or unprefixed value. The caller
    fails closed on ``None``: "we cannot tell whose subscription this is" has
    exactly one safe answer.
    """
    raw = envelope.attribute(CE_SOURCE_ATTRIBUTE)
    if raw is None:
        return None
    name = raw.removeprefix(SUBSCRIPTION_SOURCE_PREFIX)
    if not name.startswith("subscriptions/") or name == "subscriptions/":
        return None
    return name


def artifact_name_of(data: bytes) -> str | None:
    """The transcript resource name Google announced, or nothing.

    Read for exactly two purposes — the idempotency digest and the stored
    ``artifact_digest`` — and **hashed before either**. It is never returned to a
    caller, never logged, and never stored in the clear: a Meet transcript
    resource name embeds the conference record id, which is a durable handle to
    one specific meeting.

    Google nests it as ``{"transcript": {"name": "conferenceRecords/…"}}``. A
    body that does not decode is not an error here; the caller has a stable
    fallback and a separate decision to make about it.
    """
    try:
        decoded: object = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    transcript = decoded.get("transcript")
    if not isinstance(transcript, dict):
        return None
    return _text(transcript.get("name"))


def artifact_digest(name: str) -> str:
    """SHA-256, hex, of an artifact resource name.

    The value that reaches the database. Hashing costs nothing here and is what
    makes `google_meet_artifact_signals` useless to anybody who obtains it —
    including us, which is the point: Step 36A must not leave behind the pointer
    a later step would need in order to fetch content without asking again.
    """
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Which workspace, and which meeting
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MeetSubscription:
    """The stored record that CAIRN holds a lease for one consented meeting.

    This record is a *lookup*, not the permission. The permission is the Step 35
    capture request `meeting_id` points at, and the receiver re-checks it through
    `meetings.guard.permit_collection` before recording anything — because the
    thing that changes between creating a subscription and receiving an event is
    exactly somebody's mind.
    """

    tenant_id: uuid.UUID

    #: The `source_connections` row this lease belongs to — where health is
    #: recorded, and what a disconnect switches off.
    connection_id: uuid.UUID

    #: Our own subscription row.
    subscription_id: uuid.UUID

    #: The Step 35 capture request. Internal id only: there is no meeting ref and
    #: no joining code anywhere on this type, because there is none on the row.
    meeting_id: uuid.UUID

    #: False when the lease is known but must not deliver: the connection was
    #: disconnected or revoked, or CAIRN deleted the subscription. Kept separate
    #: from "unknown" because one is a stranger and the other is a customer who
    #: turned us off, and capturing the second is a consent failure rather than a
    #: mystery.
    active: bool = True


class SubscriptionRegistry(Protocol):
    """Which workspace, if any, holds this subscription.

    Narrow on purpose, and the *only* question the receiver may ask before the
    consent gate. ``None`` means refused — unknown, deleted, expired,
    disconnected and revoked all arrive here as "no answer", because from the
    receiver's point of view they are one decision: do not record this.
    """

    async def subscription_for(self, subscription_name: str) -> MeetSubscription | None: ...


@dataclass(frozen=True, slots=True)
class StaticSubscriptionRegistry:
    """A fixed mapping of subscription name to record.

    Used by tests, and kept in the source tree rather than in a test file so the
    protocol has a real implementation the type checker is actually checking it
    against.
    """

    subscriptions: Mapping[str, MeetSubscription]

    async def subscription_for(self, subscription_name: str) -> MeetSubscription | None:
        return self.subscriptions.get(subscription_name)


@dataclass(frozen=True, slots=True)
class StoredSubscriptionRegistry:
    """The production registry: the stored Meet subscription row.

    One query, joined to the connection it hangs off. Fails **closed** on
    anything it cannot answer, including its own unavailability: "we cannot tell
    whose subscription this is" has exactly one safe answer, and a permissive
    fallback here would record a meeting for a workspace chosen by a database
    error.
    """

    db: AsyncSession

    async def subscription_for(self, subscription_name: str) -> MeetSubscription | None:
        from cairn_api.db.gmeet_models import GoogleMeetSubscription, GoogleMeetSubscriptionState

        try:
            row = (
                await self.db.execute(
                    select(GoogleMeetSubscription, SourceConnection)
                    .join(
                        SourceConnection,
                        SourceConnection.id == GoogleMeetSubscription.connection_id,
                    )
                    # Belt and braces on the provider: a mix-up would otherwise
                    # resolve a Meet subscription onto a Chat connection's
                    # tenancy.
                    .where(
                        GoogleMeetSubscription.subscription_name == subscription_name,
                        SourceConnection.provider == ConnectorProvider.GOOGLE_MEET,
                    )
                )
            ).first()
        except SQLAlchemyError:
            # The rollback matters as much as the refusal: a failed statement
            # leaves the session's transaction aborted, and every later query on
            # this request would fail for a reason unrelated to what it was doing.
            await self.db.rollback()
            await logger.aerror("gmeet.subscription_registry_unavailable", provider=PROVIDER)
            return None

        if row is None:
            return None

        subscription, connection = row
        # `DELETED` and `EXPIRED` are leases CAIRN has stopped honouring. A lease
        # Google is still delivering on after a consent withdrawal is precisely
        # the case `remove_subscription` blocks locally first, so the local row is
        # the authority here rather than the fact that an event arrived.
        stopped = subscription.state in {
            GoogleMeetSubscriptionState.DELETED,
            GoogleMeetSubscriptionState.EXPIRED,
        }

        return MeetSubscription(
            # From the stored row, never from the payload that asked.
            tenant_id=subscription.tenant_id,
            connection_id=connection.id,
            subscription_id=subscription.id,
            meeting_id=subscription.meeting_id,
            # Computed on the connection rather than stored, so a stale boolean
            # cannot read as live consent.
            active=connection.is_active and not stopped,
        )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def record_healthy_delivery(connection: SourceConnection) -> None:
    """A verified push for a consented meeting was accepted for this connection.

    `last_successful_sync_at` is the number a customer means by "is it working",
    and the one a stalled-but-authorised connection cannot fake — so it is set
    only here, on the one path where a delivery was actually accepted.
    """
    connection.last_successful_sync_at = datetime.now(UTC)
    connection.health = ConnectionHealth.HEALTHY
    connection.last_error_category = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def configured_audience(override: str | None) -> str:
    return override or os.environ.get(AUDIENCE_VAR, "")


def configured_service_account(override: str | None) -> str:
    return override or os.environ.get(SERVICE_ACCOUNT_VAR, "")


def configured_subscription(override: str | None) -> str:
    return override or os.environ.get(SUBSCRIPTION_VAR, "")


def _is_true(value: object) -> bool:
    """`email_verified`, which Google sends as a boolean.

    The string form is accepted because some OIDC issuers render it that way and
    a false negative here rejects every real delivery. Everything else — absent,
    `false`, `0`, an object — is not a claim that the address was verified.
    """
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().casefold() == "true"


def _text(value: object) -> str | None:
    """A non-empty string, or nothing. Never a coerced number or an object."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "AUDIENCE_VAR",
    "CE_ID_ATTRIBUTE",
    "CE_SOURCE_ATTRIBUTE",
    "CE_TYPE_ATTRIBUTE",
    "MAX_PAYLOAD_BYTES",
    "PROVIDER",
    "SERVICE_ACCOUNT_VAR",
    "SUBSCRIPTION_VAR",
    "TRANSCRIPT_READY_EVENT",
    "GoogleJwks",
    "GoogleMeetPush",
    "MeetSubscription",
    "PushEnvelope",
    "RecentMessageIds",
    "SigningKeyUnavailableError",
    "SigningKeys",
    "StaticSubscriptionRegistry",
    "StoredSubscriptionRegistry",
    "SubscriptionRegistry",
    "artifact_digest",
    "artifact_name_of",
    "configured_audience",
    "configured_service_account",
    "configured_subscription",
    "read_push",
    "record_healthy_delivery",
    "subscription_name_of",
]
