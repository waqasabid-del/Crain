"""Google Chat's half of the ingestion contract: the JWT, the space, the key.

This is the security-critical stream, and it is critical for a reason that does
not apply to the other two providers: **the token does not cover the body.**
GitHub and Slack sign the exact bytes they send, so a verified request is a
request nobody altered. Cloud Pub/Sub instead attaches an OIDC bearer token to a
push, and that token authenticates *the caller* — it says "Google's push
subsystem, on the subscription you configured, sent this" and says nothing at all
about the JSON underneath.

Everything below follows from that.

**The token is checked completely, or not at all.** Six claims, every one of them
required, because each one alone is bypassable: a signature with no `aud` check
accepts a token minted for somebody else's endpoint and replayed at ours; an
`aud` check with no `email` check accepts a token from any service account in any
project that happened to be pointed here; an `email` check with no
`email_verified` check accepts an address the issuer itself would not vouch for.
The audience is **required to be configured explicitly** and is never defaulted
to the request URL — deriving it from the endpoint means a proxy, a rewrite or a
`Host` header decides what our own verifier compares against.

**The subscription identity is checked too.** A valid Google token proves Google
sent it; the `subscription` field proves it came from *our* subscription rather
than from some other project's, pointed at our URL by whoever owns it.

**Idempotency is not keyed on `messageId`.** `messageId` is stable across
redeliveries of one publish, which is the easy half. It is *not* stable if the
event is published again — a Workspace Events retry, a subscription rebuild —
and staking correctness on it means the same Chat message can be counted twice.
The key is a digest over the CloudEvent id (`ce-id`) and the Chat message
resource name, both of which name the event itself rather than one attempt to
deliver it. `messageId` is used only as an in-process fast path that skips a
database round trip; it is never the correctness boundary.

**The key is a digest rather than the ids themselves.** `delivery_id` is on the
telemetry allow-list and reaches spans and logs, and a Chat message resource name
contains the space id. Hashing costs nothing and keeps "no space name in
telemetry" true by construction instead of by review.

**Tenancy comes from the stored space subscription, never from the payload.**
The space name in the body is a *lookup key* into a mapping only an authenticated
connect flow may write — exactly as Slack's `team_id` is. A body claiming a
tenant, a customer or another space is data, not authority.
"""

from __future__ import annotations

import base64
import binascii
import importlib
import json
import os
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Final, Protocol, cast

import jwt
import structlog
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError, PyJWTError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.connector_models import ConnectionHealth, SourceConnection
from cairn_api.ingestion import (
    IdempotencyKey,
    InboundRequest,
    SourceMetadata,
    SourceMetadataError,
    VerificationError,
)

logger = structlog.get_logger(__name__)

#: This provider's name in `SourceMetadata`, on spans, in logs, and as the
#: source label on a citation. Lowercase and ours, matching
#: `ConnectorProvider.GOOGLE_CHAT`.
PROVIDER: Final = "google_chat"

AUTHORIZATION_HEADER: Final = "Authorization"
BEARER_SCHEME: Final = "bearer"

#: Google's JWKS, and the document that advertises it. The URI is pinned; the
#: *keys* are always fetched and cached, never hardcoded — Google rotates them,
#: and a pinned key is an outage with a fixed date.
GOOGLE_OPENID_CONFIGURATION: Final = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_JWKS_URI: Final = "https://www.googleapis.com/oauth2/v3/certs"

#: Both forms Google issues. Accepting only one rejects real traffic; accepting
#: anything is not an issuer check at all.
ACCEPTED_ISSUERS: Final = frozenset({"https://accounts.google.com", "accounts.google.com"})

#: Pinned. Passed to `jwt.decode`, which is what makes `alg: none` and the
#: HS256-signed-with-the-public-key confusion unrepresentable rather than
#: something a later reader has to notice.
SIGNING_ALGORITHM: Final = "RS256"

#: The CloudEvent attributes Pub/Sub carries beside the data. **The event type
#: is here and not in the payload** — created, updated and deleted bodies are
#: structurally identical, so this is the only thing that discriminates them.
CE_TYPE_ATTRIBUTE: Final = "ce-type"
CE_ID_ATTRIBUTE: Final = "ce-id"

#: A Chat message is at most a few kilobytes of text. Capped far below the
#: shared default because this endpoint is unauthenticated at the transport
#: level and decodes whatever it is handed.
MAX_PAYLOAD_BYTES: Final = 1024 * 1024

#: Short. The push request budget is the subscription's `ackDeadlineSeconds`
#: (10s by default, and *not extendable per message*), so a JWKS fetch that hung
#: for the library's 30s default would turn a key-rotation blip into every
#: message being redelivered.
JWKS_TIMEOUT_SECONDS: Final = 2.0

#: How long a fetched key set is reused. Google's keys rotate on the order of
#: days; five minutes is the library default and is short enough that a
#: compromised key leaves the cache quickly.
JWKS_CACHE_SECONDS: Final = 300.0

#: Configuration, read from the environment because `config.Settings` does not
#: carry these yet (Step 33 does not own `config.py`). `app.state` takes
#: precedence — see `api/routers/gchat_push.py`. Absent, verification refuses
#: everything: an unset audience or service account makes every token
#: acceptable, so failing closed is the only safe reading.
AUDIENCE_VAR: Final = "CAIRN_GCHAT_PUSH_AUDIENCE"
SERVICE_ACCOUNT_VAR: Final = "CAIRN_GCHAT_PUSH_SERVICE_ACCOUNT"
SUBSCRIPTION_VAR: Final = "CAIRN_GCHAT_PUSH_SUBSCRIPTION"


# ---------------------------------------------------------------------------
# The push envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PushEnvelope:
    """One Pub/Sub push, decoded no further than Pub/Sub's own envelope.

    Deliberately stops at `data`: the bytes are handed on as bytes, and only
    `gchat/events.py` decides what a Chat event means. That boundary is what
    lets the subscription identity be checked before anything looks at the
    customer's message.
    """

    subscription: str
    message_id: str
    publish_time: str | None
    attributes: Mapping[str, str]
    data: bytes

    def attribute(self, name: str) -> str | None:
        value = self.attributes.get(name)
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None


def read_push(body: bytes) -> PushEnvelope:
    """Decode a push envelope, or refuse it.

    Raises `SourceMetadataError` for every malformed shape — a body that is not
    JSON, that is not an object, that has no `message`, that names no
    subscription, or whose `data` is not valid base64. The caller answers all of
    them identically, so a malformed envelope cannot be used to probe which
    requests get further.

    Both key spellings are handled. Pub/Sub's REST envelope is documented in
    camelCase (`messageId`, `publishTime`) and its own client libraries and some
    emulator paths emit snake_case; reading only one silently loses the delivery
    id on half the traffic.
    """
    try:
        decoded: object = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = "A Pub/Sub push must be JSON"
        raise SourceMetadataError(msg) from exc

    if not isinstance(decoded, dict):
        msg = "A Pub/Sub push must be a JSON object"
        raise SourceMetadataError(msg)

    message = decoded.get("message")
    if not isinstance(message, dict):
        msg = "A Pub/Sub push must carry a message"
        raise SourceMetadataError(msg)

    subscription = _text(decoded.get("subscription"))
    if subscription is None:
        msg = "A Pub/Sub push must name its subscription"
        raise SourceMetadataError(msg)

    message_id = _text(message.get("messageId")) or _text(message.get("message_id"))
    if message_id is None:
        msg = "A Pub/Sub message must carry a message id"
        raise SourceMetadataError(msg)

    return PushEnvelope(
        subscription=subscription,
        message_id=message_id,
        publish_time=_text(message.get("publishTime")) or _text(message.get("publish_time")),
        attributes=_attributes(message.get("attributes")),
        data=_decode_data(message.get("data")),
    )


def _attributes(raw: object) -> Mapping[str, str]:
    """The CloudEvent attributes, string-to-string and nothing else.

    A non-string value is dropped rather than coerced: `ce-type` decides what an
    event *is*, and `str(value)` on an object would produce a type that matches
    nothing and drops the event for a reason nobody could read.
    """
    if not isinstance(raw, dict):
        return {}
    return {
        key: value for key, value in raw.items() if isinstance(key, str) and isinstance(value, str)
    }


def _decode_data(raw: object) -> bytes:
    """`message.data` as bytes.

    Absent is legitimate — Pub/Sub allows an attributes-only message — and is
    an empty payload rather than an error, so the drop happens where event
    types are understood. Present and *not* base64 is a refusal.
    """
    if raw is None:
        return b""
    if not isinstance(raw, str):
        msg = "A Pub/Sub message's data must be base64 text"
        raise SourceMetadataError(msg)
    try:
        # `validate=True`: the permissive default silently discards characters
        # outside the alphabet, which turns a corrupted payload into a
        # different, well-formed one.
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        msg = "A Pub/Sub message's data was not valid base64"
        raise SourceMetadataError(msg) from exc


# ---------------------------------------------------------------------------
# Google's signing keys
# ---------------------------------------------------------------------------


class SigningKeyUnavailableError(VerificationError):
    """Google's key set could not be reached.

    A `VerificationError` so it cannot escape the contract, and a *distinct*
    one so the endpoint can answer it with a non-2xx. This is the one refusal
    that is genuinely transient: the token may well be perfect, and Pub/Sub
    redelivering it in a minute is exactly the right outcome. Answering it like
    a forgery would silently drop real messages during a Google outage.
    """


class SigningKeys(Protocol):
    """Where the public key for a token comes from.

    A protocol so tests can mint their own tokens against a generated key
    without patching verification out — a test that disables the control proves
    the code works when the control is absent, which is not a property anybody
    wants.
    """

    def public_key(self, token: str) -> RSAPublicKey: ...


class GoogleJwks:
    """Google's published keys, fetched over the network and cached.

    Never hardcoded, and never pinned to a single key: Google rotates, and a
    literal in the source is an outage with a date on it. The cache is what
    keeps this off the hot path — a push arrives with one of a handful of key
    ids, and the fetch happens on rotation rather than per message.
    """

    def __init__(
        self,
        *,
        jwks_uri: str = GOOGLE_JWKS_URI,
        timeout: float = JWKS_TIMEOUT_SECONDS,
        lifespan: float = JWKS_CACHE_SECONDS,
    ) -> None:
        self._client = PyJWKClient(
            jwks_uri,
            cache_keys=True,
            cache_jwk_set=True,
            lifespan=lifespan,
            timeout=timeout,
        )

    def public_key(self, token: str) -> RSAPublicKey:
        try:
            signing_key = self._client.get_signing_key_from_jwt(token)
        except PyJWKClientConnectionError as exc:
            # Transient. See `SigningKeyUnavailableError`.
            msg = "Google's key set could not be fetched"
            raise SigningKeyUnavailableError(msg) from exc
        except PyJWKClientError as exc:
            # A key id Google does not publish — after the client has already
            # refreshed once. That is a forged or long-retired token, not an
            # outage.
            msg = "No published Google key matches this token"
            raise VerificationError(msg) from exc
        except PyJWTError as exc:
            # The token is malformed enough that its header cannot be read.
            msg = "The push token could not be read"
            raise VerificationError(msg) from exc

        key = signing_key.key
        if not isinstance(key, RSAPublicKey):
            # RS256 is pinned below, so a non-RSA key here means the key set
            # changed shape. Refusing is correct: verifying RS256 against
            # something else is not a thing that can succeed safely.
            msg = "Google's signing key is not an RSA key"
            raise VerificationError(msg)
        return key


# ---------------------------------------------------------------------------
# The provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoogleChatPush:
    """Verify a Pub/Sub push, and name the Chat event it carries.

    Implements `InboundProvider`. Everything after this — the idempotency
    ledger, the enqueue, the retry and dead-letter behaviour — is the shared
    machinery in `ingestion/`, unchanged.
    """

    #: The audience configured **on the push subscription**. Required, and never
    #: defaulted to the endpoint URL: a URL is decided by a proxy, a rewrite or
    #: a `Host` header, and a verifier that compares a token against something
    #: an attacker can influence is not verifying.
    audience: str

    #: The service account Pub/Sub was told to sign as, checked against `email`.
    service_account_email: str

    #: The full subscription resource name we expect
    #: (`projects/P/subscriptions/S`). A valid Google token proves Google sent
    #: the request; this proves it came from *our* subscription.
    subscription: str

    keys: SigningKeys

    #: Clock skew allowance on `exp`. Zero by default — Google's tokens are
    #: valid for an hour, so nothing legitimate needs the slack.
    leeway_seconds: float = 0.0

    # -- verification -------------------------------------------------------

    def verify(self, request: InboundRequest) -> None:
        """Prove the push came from our subscription, before anything parses it.

        Six checks, and all six are required. Removing any one of them leaves a
        verifier that accepts a token it should not — see the module docstring
        for which attack each one closes.
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
                # (2) audience and (3) expiry, enforced by the library against
                # the explicitly configured value.
                audience=self.audience,
                leeway=self.leeway_seconds,
                options={
                    "verify_signature": True,  # (1) the signature
                    "verify_exp": True,
                    "verify_aud": True,
                    # A token with no `exp` never expires, and a token with no
                    # `aud` verifies against every audience. Both are absences
                    # rather than mismatches, which is exactly the class of
                    # failure a verifier misses unless it is told to require
                    # the claim.
                    "require": ["exp", "iat", "aud", "iss"],
                },
            )
        except PyJWTError as exc:
            # One exception for every mode — bad signature, wrong audience,
            # expired, missing claim — so a forger who gets a rejection learns
            # nothing about which part of the forgery was wrong.
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
            msg = "No Google Chat push audience is configured"
            raise VerificationError(msg)
        if not self.service_account_email:
            msg = "No Google Chat push service account is configured"
            raise VerificationError(msg)
        if not self.subscription:
            msg = "No Google Chat push subscription is configured"
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
        """(4) issuer, (5) service account address, (6) address verified.

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
            # Absent, false, or anything else. Without this, a token carrying an
            # address the issuer itself would not vouch for is accepted.
            msg = "The push token's service account address is not verified"
            raise VerificationError(msg)

    # -- naming -------------------------------------------------------------

    def read_source(self, request: InboundRequest) -> SourceMetadata:
        """Name the delivery, from the verified request.

        Runs only after `verify`, so parsing here is parsing something Google
        sent. The order inside is load-bearing: the envelope is decoded, the
        **subscription identity** is checked, and only then are the CloudEvent
        attributes read — every one of those precedes any decoding of the Chat
        resource in `message.data`.
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
            msg = "A Chat push must carry ce-type and ce-id attributes"
            raise SourceMetadataError(msg)

        return SourceMetadata(
            provider=PROVIDER,
            # The event type is the CloudEvent type and nothing else. The three
            # payload shapes are identical, so reading a "type" out of the body
            # would make a delete indistinguishable from a create.
            event_type=ce_type[:64],
            # Pub/Sub's delivery id. Recorded because it is what an operator
            # sees in the console — *not* used as the idempotency key.
            external_event_id=envelope.message_id,
        )

    def idempotency_key(self, request: InboundRequest, source: SourceMetadata) -> IdempotencyKey:
        """A digest over the CloudEvent id and the Chat message resource name.

        Not `messageId`. That value is stable across redeliveries of one publish
        and unstable across a re-publish of the same event, so keying on it
        means a republished message is counted twice — in a product whose output
        is "what happened this week", that is a correctness failure a customer
        notices before we do.

        `ce-id` names the event and the resource name names the message, so the
        pair is identical for every delivery of one thing and different for two
        genuinely different things. The digest is what makes it safe to log.
        """
        envelope = read_push(request.body)
        ce_id = envelope.attribute(CE_ID_ATTRIBUTE) or ""

        # Best effort: a payload whose Chat resource does not decode still needs
        # a stable key, and the raw bytes are stable for exactly the same
        # delivery. `\x00` cannot occur in either identifier, so the two fields
        # cannot be re-split into a different pair with the same digest.
        identity = message_name_of(envelope.data)
        tail = identity.encode("utf-8") if identity is not None else envelope.data

        return IdempotencyKey.derive(
            provider=PROVIDER,
            # Deliberately not the space: the space is already inside the
            # message resource name, and mixing in a second copy would let a
            # payload that disagrees with itself produce two keys for one event.
            external_account_id=None,
            event_type=source.event_type,
            body=ce_id.encode("utf-8") + b"\x00" + tail,
        )


def message_name_of(data: bytes) -> str | None:
    """`message.name` from a decoded Chat payload, or nothing.

    Lives here rather than in `events.py` because the idempotency key needs it
    before anything has decided whether the event is one CAIRN ingests — a
    dropped event still has to be recorded under a stable key if it is recorded
    at all.
    """
    try:
        decoded: object = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, dict):
        return None
    message = decoded.get("message")
    if not isinstance(message, dict):
        return None
    return _text(message.get("name"))


# ---------------------------------------------------------------------------
# Which workspace, and which space
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpaceSubscription:
    """The stored record that a workspace selected a space, and CAIRN subscribed.

    This record *is* the tenancy decision. It is written only by a connect flow
    behind a session, a membership and a permission check; ingestion reads it
    and never writes it.
    """

    tenant_id: uuid.UUID

    #: The `source_connections` row this subscription belongs to — where health
    #: is recorded, and what a disconnect switches off.
    connection_id: uuid.UUID

    space_name: str

    #: False when the space is still known but must not be read: the connection
    #: was disconnected or revoked, the customer deselected the space, or the
    #: Workspace Events subscription lapsed. Kept separate from "unknown"
    #: because the two mean different things — one is a stranger, the other is a
    #: customer who turned us off, and capturing the second is a consent failure
    #: rather than a mystery.
    active: bool = True


class SpaceRegistry(Protocol):
    """Which workspace, if any, has selected this space.

    Narrow on purpose, and the *only* question ingestion may ask. Which spaces
    an admin ticked, when, by whom, and what the Workspace Events subscription
    id is all belong with the connector's own tables.

    `None` means refused — unknown, unselected, removed, disconnected, revoked
    or expired all arrive here as "no answer", because from ingestion's point of
    view they are one decision: do not read this space.
    """

    async def subscription_for(self, space_name: str) -> SpaceSubscription | None: ...


@dataclass(frozen=True, slots=True)
class StaticSpaceRegistry:
    """A fixed mapping of space to subscription.

    Used by tests, and by any wiring that already holds the selection. Kept in
    the source tree rather than in a test file so the protocol has a real
    implementation the type checker is actually checking it against.
    """

    subscriptions: Mapping[str, SpaceSubscription]

    async def subscription_for(self, space_name: str) -> SpaceSubscription | None:
        return self.subscriptions.get(space_name)


#: The contract this module needs from the connect flow's own module, which
#: Step 33 does not own and which does not exist yet.
#:
#: ``async def resolve_space(db, *, space_name: str) -> SpaceSubscription | None``
#:
#: Resolved by name at call time rather than imported, for one reason: an import
#: of a module that is not there yet would make the *ingestion* path fail to
#: start, and an endpoint that 500s is worse than one that refuses. When the
#: module lands, this lights up with no edit here.
SUBSCRIPTIONS_MODULE: Final = "cairn_api.gchat.subscriptions"
RESOLVE_SPACE_ATTRIBUTE: Final = "resolve_space"


class _ResolveSpace(Protocol):
    async def __call__(self, db: AsyncSession, *, space_name: str) -> SpaceSubscription | None: ...


@lru_cache(maxsize=1)
def _resolve_space_hook() -> _ResolveSpace | None:
    """The connect flow's resolver, if it has landed. Cached: an import attempt
    per inbound message would pay a filesystem walk on the hot path."""
    try:
        module = importlib.import_module(SUBSCRIPTIONS_MODULE)
    except ImportError:
        return None
    hook = getattr(module, RESOLVE_SPACE_ATTRIBUTE, None)
    if not callable(hook):
        return None
    return cast("_ResolveSpace", hook)


@dataclass(frozen=True, slots=True)
class SelectionSpaceRegistry:
    """The selected-space row, which **is** the permission.

    One query, and deliberately only one table plus the connection it hangs off.
    It does not consult `google_chat_subscriptions`: a Workspace Events
    subscription that outlives a deselection would otherwise keep ingesting a
    space the customer took back, which is a consent failure rather than a
    lifecycle detail. Selection grants; the subscription only delivers.

    `space_name` is globally unique across the table (see the constraint on
    `GoogleChatSpaceSelection`), so a space resolves to exactly one tenant or to
    none — there is no ambiguity case to refuse, because the schema made it
    unrepresentable.
    """

    db: AsyncSession

    async def subscription_for(self, space_name: str) -> SpaceSubscription | None:
        from cairn_api.db.connector_models import ConnectorProvider
        from cairn_api.db.gchat_models import GoogleChatSpaceSelection

        row = (
            await self.db.execute(
                select(GoogleChatSpaceSelection, SourceConnection)
                .join(
                    SourceConnection, SourceConnection.id == GoogleChatSpaceSelection.connection_id
                )
                # Belt and braces: the selection's connection is a Chat one by
                # construction, and a provider mix-up would otherwise resolve a
                # Chat space onto a Slack or GitHub connection's tenancy.
                .where(
                    GoogleChatSpaceSelection.space_name == space_name,
                    SourceConnection.provider == ConnectorProvider.GOOGLE_CHAT,
                )
            )
        ).first()
        if row is None:
            return None

        selection, connection = row
        return SpaceSubscription(
            # From the stored row, never from the payload that asked.
            tenant_id=selection.tenant_id,
            connection_id=connection.id,
            space_name=selection.space_name,
            # Disconnected, revoked, or never confirmed. Computed on the
            # connection rather than stored, so a stale boolean cannot read as
            # live consent.
            active=connection.is_active,
        )


@dataclass(frozen=True, slots=True)
class StoredSpaceRegistry:
    """The production registry: the stored selected-space subscription.

    Prefers the connect flow's own resolver where it has landed, because that
    module owns the selection tables and may know more than one query's worth
    about them. Otherwise it reads the selection table directly — the endpoint
    has to work the day it is mounted, not the day a second module appears.

    Fails **closed** on anything it cannot answer. A missing table (the
    migration for `google_chat_space_selections` lands with the connect flow) is
    a refusal that logs a category and reads nothing, not a fallback with a
    permissive default: "we cannot tell whose space this is" has exactly one
    safe answer.
    """

    db: AsyncSession

    async def subscription_for(self, space_name: str) -> SpaceSubscription | None:
        hook = _resolve_space_hook()
        if hook is not None:
            return await hook(self.db, space_name=space_name)

        try:
            return await SelectionSpaceRegistry(db=self.db).subscription_for(space_name)
        except SQLAlchemyError:
            # The rollback matters as much as the refusal: a failed statement
            # leaves the session's transaction aborted, and every later query on
            # this request — including the one that would record the delivery —
            # would fail for a reason unrelated to what it was doing.
            await self.db.rollback()
            # Categories and identifiers only — never the space name.
            await logger.aerror("gchat.space_registry_unavailable", provider=PROVIDER)
            return None


# ---------------------------------------------------------------------------
# The fast path, and health
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RecentMessageIds:
    """Pub/Sub delivery ids seen recently, in this process.

    An **optimisation and nothing else.** Delivery is at-least-once and
    exactly-once is pull-only, so redelivery is normal and common; recognising
    the same `messageId` lets the endpoint acknowledge without a database round
    trip inside a ten-second budget that cannot be extended.

    Correctness never rests on it. It is per-process, bounded, and lost on
    restart, and the unique constraint on the derived key is what actually makes
    a redelivery one unit of work. Only *accepted* deliveries are remembered —
    remembering a refused one would acknowledge a message that was never taken.
    """

    capacity: int = 4096
    _seen: OrderedDict[str, None] = field(default_factory=OrderedDict, repr=False)

    def seen(self, message_id: str) -> bool:
        return message_id in self._seen

    def remember(self, message_id: str) -> None:
        self._seen.pop(message_id, None)
        self._seen[message_id] = None
        while len(self._seen) > self.capacity:
            self._seen.popitem(last=False)


async def record_healthy_delivery(connection: SourceConnection) -> None:
    """A verified push from a selected space was accepted for this connection.

    `last_successful_sync_at` is the number a customer means by "is it working",
    and the one a stalled-but-authorised connection cannot fake — so it is set
    only here, on the one path where data actually arrived. There is
    deliberately no second "last delivery" column: two timestamps that can
    disagree produce a UI that shows a green tick over a gap.
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
    a false negative here rejects every real delivery. Everything else —
    absent, `false`, `0`, an object — is not a claim that the address was
    verified.
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
