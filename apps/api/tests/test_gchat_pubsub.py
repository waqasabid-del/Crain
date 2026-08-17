"""Google Chat push receipt: the token, the space, and what a refusal costs.

The third unauthenticated write endpoint in the service, and the one where a
verified request says the *least*: Pub/Sub's OIDC token authenticates the caller
and covers none of the body. Everything downstream — tenancy, storage, the queue,
the record a customer reads — trusts what this path lets through, so every
forgery below is constructed the way an attacker would rather than by patching a
control out. A test that disables the control proves the handler works when the
control is absent, which is not a property anyone wants.

The keys are generated here and the tokens are minted here. No network: the
verifier's `SigningKeys` seam hands it a real RSA public key, so signature
checking, `aud`, `iss`, `exp`, `email` and `email_verified` are all exercised
against a genuine RS256 token rather than against a stub that says yes.

Four groups carry the most weight:

* **verification runs first.** Asserted by *outcome*: a request with a bad token
  and an unknown space is answered 401, not the 200 an unknown space gets — so
  verification demonstrably preceded the space lookup.
* **the space gate leaves no trace.** An event from an unselected space is
  asserted to produce no delivery row, no job, and no log line containing the
  space or the message.
* **a re-publish still dedupes.** Not just a redelivery: a *different*
  `messageId` carrying the same `ce-id` and message resource name is one unit of
  work, which is the property keying on `messageId` would lose.
* **the status code is the whole retry vocabulary.** Permanent refusals ack;
  transient ones do not.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
import structlog
from cairn_api.api.app import create_app
from cairn_api.config import Settings
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.gchat_models import GoogleChatSpaceSelection
from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.gchat.events import GCHAT_EVENT_JOB
from cairn_api.gchat.pubsub import (
    ACCEPTED_ISSUERS,
    CE_ID_ATTRIBUTE,
    CE_TYPE_ATTRIBUTE,
    GoogleChatPush,
    PushEnvelope,
    RecentMessageIds,
    SigningKeys,
    SigningKeyUnavailableError,
    SpaceSubscription,
    StaticSpaceRegistry,
    message_name_of,
    read_push,
)
from cairn_api.ingestion import InboundRequest, SourceMetadataError, VerificationError
from cairn_api.jobs.memory import InMemoryJobQueue
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

AUDIENCE = "https://cairn.example/v1/webhooks/google-chat"
SERVICE_ACCOUNT = "cairn-push@cairn-project.iam.gserviceaccount.com"
SUBSCRIPTION = "projects/cairn-project/subscriptions/chat-events"

SPACE = "spaces/AAAASELECTED"
OTHER_SPACE = "spaces/AAAAOTHER99"
UNSELECTED_SPACE = "spaces/AAAAUNSELECT"
SENDER = "users/107700770077007700770"

CREATED = "google.workspace.chat.message.v1.created"
UPDATED = "google.workspace.chat.message.v1.updated"
DELETED = "google.workspace.chat.message.v1.deleted"

#: Distinctive enough that finding it anywhere it should not be is unambiguous.
MESSAGE_TEXT = "Priya is deferring the payments migration until the audit clears."

#: Generated once. Real RS256, so the signature check is genuinely exercised.
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeys:
    """A fixed public key, standing in for Google's JWKS.

    Returns the key *regardless of the token*, on purpose: a forgery signed with
    another key must then fail at the signature check rather than at key
    lookup, which is the failure an attacker would actually meet.
    """

    def __init__(self, key: RSAPublicKey | None = None) -> None:
        self._key = key or _KEY.public_key()

    def public_key(self, token: str) -> RSAPublicKey:
        return self._key


class UnavailableKeys:
    """Google's key set is unreachable. The one transient refusal."""

    def public_key(self, token: str) -> RSAPublicKey:
        msg = "Google's key set could not be fetched"
        raise SigningKeyUnavailableError(msg)


def mint(
    *,
    audience: str | None = AUDIENCE,
    issuer: str | None = "https://accounts.google.com",
    email: str | None = SERVICE_ACCOUNT,
    email_verified: object = True,
    expires_in: int = 3600,
    issued_ago: int = 0,
    key: rsa.RSAPrivateKey | None = None,
) -> str:
    """One Pub/Sub OIDC token, minted the way Google mints them.

    Every claim is a parameter so a forgery can differ from a real token in
    exactly one way — which is what makes a rejection attributable to the control
    under test rather than to the token being generally wrong.
    """
    now = int(time.time())
    claims: dict[str, Any] = {"sub": "115000000000000000000", "iat": now - issued_ago}
    if expires_in is not None:
        claims["exp"] = now + expires_in
    if audience is not None:
        claims["aud"] = audience
    if issuer is not None:
        claims["iss"] = issuer
    if email is not None:
        claims["email"] = email
    if email_verified is not None:
        claims["email_verified"] = email_verified
    return jwt.encode(claims, key or _KEY, algorithm="RS256")


def chat_message(
    *,
    space: str = SPACE,
    message_id: str = "MESSAGE1",
    text: str | None = MESSAGE_TEXT,
    sender: str | None = SENDER,
    sender_type: str = "HUMAN",
    stated_space: str | None = None,
    create_time: str = "2026-08-17T09:30:00Z",
) -> dict[str, Any]:
    """Chat's `includeResource: true` payload, as documented."""
    message: dict[str, Any] = {
        "name": f"{space}/messages/{message_id}",
        "createTime": create_time,
        "space": {"name": stated_space if stated_space is not None else space},
    }
    if sender is not None:
        message["sender"] = {"name": sender, "type": sender_type}
    if text is not None:
        message["text"] = text
    return {"message": message}


def push_body(
    payload: dict[str, Any] | None = None,
    *,
    ce_type: str = CREATED,
    ce_id: str | None = None,
    message_id: str | None = None,
    subscription: str = SUBSCRIPTION,
    data: str | None = None,
    snake_case: bool = False,
    **extra: Any,
) -> bytes:
    """One Pub/Sub push envelope, as the REST push format documents it."""
    encoded = (
        data
        if data is not None
        else base64.b64encode(json.dumps(payload or chat_message()).encode("utf-8")).decode("ascii")
    )
    attributes: dict[str, str] = {CE_ID_ATTRIBUTE: ce_id or f"ce-{uuid.uuid4().hex[:12]}"}
    if ce_type:
        attributes[CE_TYPE_ATTRIBUTE] = ce_type

    message: dict[str, Any] = {"attributes": attributes, "data": encoded}
    if snake_case:
        message["message_id"] = message_id or uuid.uuid4().hex[:16]
        message["publish_time"] = "2026-08-17T09:30:01Z"
    else:
        message["messageId"] = message_id or uuid.uuid4().hex[:16]
        message["publishTime"] = "2026-08-17T09:30:01Z"

    body: dict[str, Any] = {"message": message, "subscription": subscription}
    body.update(extra)
    return json.dumps(body).encode("utf-8")


def verifier(
    keys: SigningKeys | None = None,
    *,
    audience: str = AUDIENCE,
    service_account_email: str = SERVICE_ACCOUNT,
    subscription: str = SUBSCRIPTION,
) -> GoogleChatPush:
    return GoogleChatPush(
        audience=audience,
        service_account_email=service_account_email,
        subscription=subscription,
        keys=keys or StaticKeys(),
    )


def request_for(
    body: bytes | None = None, *, token: str | None = None, **mint_args: Any
) -> InboundRequest:
    headers = {"Content-Type": "application/json"}
    bearer = token if token is not None else mint(**mint_args)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return InboundRequest(body=body if body is not None else push_body(), headers=headers)


# --------------------------------------------------------------------------
# The envelope, on its own
# --------------------------------------------------------------------------


class TestThePushEnvelope:
    def test_a_documented_envelope_decodes(self) -> None:
        envelope = read_push(push_body(message_id="2070443601311540"))

        assert isinstance(envelope, PushEnvelope)
        assert envelope.subscription == SUBSCRIPTION
        assert envelope.message_id == "2070443601311540"
        assert envelope.attribute(CE_TYPE_ATTRIBUTE) == CREATED
        assert json.loads(envelope.data)["message"]["text"] == MESSAGE_TEXT

    def test_the_snake_case_spelling_is_read_too(self) -> None:
        """Both spellings are real. Reading only `messageId` loses the delivery
        id on every emulator and client-library path that emits the other."""
        envelope = read_push(push_body(message_id="42", snake_case=True))

        assert envelope.message_id == "42"
        assert envelope.publish_time == "2026-08-17T09:30:01Z"

    def test_data_that_is_not_base64_is_refused(self) -> None:
        # `validate=True` matters: the permissive default silently discards
        # characters outside the alphabet, turning a corrupted payload into a
        # different, well-formed one.
        with pytest.raises(SourceMetadataError, match="base64"):
            read_push(push_body(data="not!valid!base64!"))

    @pytest.mark.parametrize(
        "body",
        [
            b"{this is not json",
            b"[]",
            b'{"subscription":"projects/p/subscriptions/s"}',
            b'{"message":{"messageId":"1"}}',
            b'{"message":{},"subscription":"projects/p/subscriptions/s"}',
        ],
        ids=["not-json", "not-an-object", "no-message", "no-subscription", "no-message-id"],
    )
    def test_a_malformed_envelope_is_refused(self, body: bytes) -> None:
        with pytest.raises(SourceMetadataError):
            read_push(body)

    def test_an_attributes_only_message_is_an_empty_payload(self) -> None:
        # Pub/Sub allows it, and it is a drop where event types are understood
        # rather than a refusal here.
        envelope = read_push(
            json.dumps(
                {
                    "message": {"messageId": "1", "attributes": {CE_TYPE_ATTRIBUTE: CREATED}},
                    "subscription": SUBSCRIPTION,
                }
            ).encode("utf-8")
        )

        assert envelope.data == b""

    def test_non_string_attributes_are_dropped_rather_than_coerced(self) -> None:
        """`ce-type` decides what an event *is*.

        `str(value)` on an object would produce a type matching nothing and drop
        the event for a reason nobody could read.
        """
        envelope = read_push(
            json.dumps(
                {
                    "message": {"messageId": "1", "attributes": {CE_TYPE_ATTRIBUTE: {"a": 1}}},
                    "subscription": SUBSCRIPTION,
                }
            ).encode("utf-8")
        )

        assert envelope.attribute(CE_TYPE_ATTRIBUTE) is None

    def test_the_message_name_is_readable_without_interpreting_the_event(self) -> None:
        assert (
            message_name_of(json.dumps(chat_message()).encode("utf-8"))
            == f"{SPACE}/messages/MESSAGE1"
        )
        assert message_name_of(b"not json") is None
        assert message_name_of(b'{"message":{}}') is None


# --------------------------------------------------------------------------
# The token: all six claims
# --------------------------------------------------------------------------


class TestTokenVerification:
    def test_a_valid_token_is_accepted(self) -> None:
        # The positive control. Without it every rejection below would pass
        # against a verifier that refused everything.
        verifier().verify(request_for())

    def test_a_signature_from_another_key_is_rejected(self) -> None:
        # (1) The signature. The realistic forgery: correct claims, wrong key.
        with pytest.raises(VerificationError, match="did not verify"):
            verifier().verify(request_for(key=_OTHER_KEY))

    def test_an_unsigned_token_is_rejected(self) -> None:
        """`alg: none` is unrepresentable because RS256 is pinned.

        A verifier that took the algorithm from the token accepts this.
        """
        claims = {
            "iss": "https://accounts.google.com",
            "aud": AUDIENCE,
            "email": SERVICE_ACCOUNT,
            "email_verified": True,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        unsigned = jwt.encode(claims, key="", algorithm="none")

        with pytest.raises(VerificationError):
            verifier().verify(request_for(token=unsigned))

    def test_a_token_for_another_audience_is_rejected(self) -> None:
        # (2) `aud`. Without it, a token minted for somebody else's endpoint and
        # replayed at ours is accepted.
        with pytest.raises(VerificationError, match="did not verify"):
            verifier().verify(request_for(audience="https://attacker.example/push"))

    def test_a_token_with_no_audience_is_rejected(self) -> None:
        # An absence, not a mismatch — the class of failure a verifier misses
        # unless it is told to *require* the claim.
        with pytest.raises(VerificationError):
            verifier().verify(request_for(audience=None))

    def test_an_expired_token_is_rejected(self) -> None:
        # (3) `exp`. Tokens are valid for up to an hour; a capture older than
        # that is worthless, and only because this check exists.
        with pytest.raises(VerificationError, match="did not verify"):
            verifier().verify(request_for(expires_in=-1))

    def test_a_token_nearly_an_hour_old_is_still_accepted(self) -> None:
        # The positive control for the check above: Google's tokens live an
        # hour, so rejecting a 55-minute-old one would drop real traffic.
        verifier().verify(request_for(issued_ago=3300, expires_in=300))

    @pytest.mark.parametrize("issuer", sorted(ACCEPTED_ISSUERS))
    def test_both_forms_google_issues_are_accepted(self, issuer: str) -> None:
        verifier().verify(request_for(issuer=issuer))

    def test_a_token_from_another_issuer_is_rejected(self) -> None:
        # (4) `iss`.
        with pytest.raises(VerificationError, match="unexpected issuer"):
            verifier().verify(request_for(issuer="https://accounts.attacker.example"))

    def test_a_token_from_another_service_account_is_rejected(self) -> None:
        # (5) `email`. Without it, any service account in any Google project
        # that happens to be pointed here is accepted.
        with pytest.raises(VerificationError, match="unexpected service account"):
            verifier().verify(
                request_for(email="someone-else@other-project.iam.gserviceaccount.com")
            )

    def test_the_service_account_comparison_ignores_case(self) -> None:
        # Addresses are not case-sensitive, and a configuration written with
        # different capitalisation would otherwise reject every real delivery.
        verifier().verify(request_for(email=SERVICE_ACCOUNT.upper()))

    @pytest.mark.parametrize("claim", [False, None, "false", 0, {}])
    def test_an_unverified_service_account_address_is_rejected(self, claim: object) -> None:
        # (6) `email_verified`. Without it, a token carrying an address the
        # issuer itself would not vouch for is accepted.
        with pytest.raises(VerificationError, match="not verified"):
            verifier().verify(request_for(email_verified=claim))

    def test_a_missing_authorization_header_is_rejected(self) -> None:
        # The catastrophic implementation is `if token: verify(token)`, which
        # accepts every request that simply omits the header.
        with pytest.raises(VerificationError, match="Missing authorization"):
            verifier().verify(InboundRequest(body=push_body(), headers={}))

    @pytest.mark.parametrize("header", ["", "Bearer", "Bearer ", "Basic abc", mint()])
    def test_a_header_that_is_not_a_bearer_token_is_rejected(self, header: str) -> None:
        with pytest.raises(VerificationError):
            verifier().verify(InboundRequest(body=push_body(), headers={"Authorization": header}))

    def test_the_bearer_scheme_is_matched_case_insensitively(self) -> None:
        # HTTP auth schemes are case-insensitive; rejecting `bearer` would fail
        # against a proxy that normalises it.
        verifier().verify(
            InboundRequest(body=push_body(), headers={"Authorization": f"bearer {mint()}"})
        )

    @pytest.mark.parametrize(
        "misconfigured",
        [
            verifier(audience=""),
            verifier(service_account_email=""),
            verifier(subscription=""),
        ],
        ids=["no-audience", "no-service-account", "no-subscription"],
    )
    def test_an_unconfigured_verifier_refuses_everything(
        self, misconfigured: GoogleChatPush
    ) -> None:
        """A blank audience makes every token's audience acceptable.

        So a misconfigured deployment must reject Google rather than accept
        everyone — the difference between an outage and an open door.
        """
        with pytest.raises(VerificationError, match="No Google Chat push"):
            misconfigured.verify(request_for())

    def test_an_unreachable_key_set_is_a_distinct_transient_failure(self) -> None:
        """Distinguishable from a forgery, and only here.

        The token may well be perfect; answering a Google outage the way a
        forgery is answered would silently drop real messages for its duration.
        """
        with pytest.raises(SigningKeyUnavailableError):
            verifier(UnavailableKeys()).verify(request_for())


# --------------------------------------------------------------------------
# Naming the delivery
# --------------------------------------------------------------------------


class TestSourceMetadata:
    def test_the_event_type_is_the_cloudevent_type(self) -> None:
        # And not anything from the body: the three payload shapes are
        # identical, so a "type" read out of the body cannot tell a delete from
        # a create.
        source = verifier().read_source(request_for(push_body(ce_type=DELETED)))

        assert source.provider == "google_chat"
        assert source.event_type == DELETED

    def test_a_push_from_another_subscription_is_refused(self) -> None:
        """Google signed it, but not for us.

        Somebody else's subscription pointed at our endpoint would otherwise
        deliver their traffic into our tenancy lookup.
        """
        with pytest.raises(SourceMetadataError, match="unexpected subscription"):
            verifier().read_source(
                request_for(push_body(subscription="projects/theirs/subscriptions/theirs"))
            )

    @pytest.mark.parametrize("attribute", [CE_TYPE_ATTRIBUTE, CE_ID_ATTRIBUTE])
    def test_a_push_that_cannot_name_itself_is_refused(self, attribute: str) -> None:
        body = json.loads(push_body())
        del body["message"]["attributes"][attribute]

        with pytest.raises(SourceMetadataError, match="ce-type and ce-id"):
            verifier().read_source(request_for(json.dumps(body).encode("utf-8")))


class TestTheIdempotencyKey:
    def _key(self, body: bytes) -> str:
        request = request_for(body)
        provider = verifier()
        return provider.idempotency_key(request, provider.read_source(request)).value

    def test_a_redelivery_produces_the_same_key(self) -> None:
        body = push_body(ce_id="ce-1", message_id="delivery-1")

        assert self._key(body) == self._key(body)

    def test_a_republish_under_a_new_message_id_produces_the_same_key(self) -> None:
        """The property `messageId` cannot give.

        `messageId` is stable across redeliveries of one publish and unstable
        across a re-publish of the same event, so keying on it counts a
        republished message twice — which in a product whose output is "what
        happened this week" is a correctness failure a customer notices first.
        """
        first = push_body(ce_id="ce-1", message_id="delivery-1")
        republished = push_body(ce_id="ce-1", message_id="delivery-2")

        assert self._key(first) == self._key(republished)

    def test_two_different_messages_produce_different_keys(self) -> None:
        # The positive control: without it the test above would pass against a
        # constant.
        first = push_body(chat_message(message_id="M1"), ce_id="ce-1")
        second = push_body(chat_message(message_id="M2"), ce_id="ce-1")

        assert self._key(first) != self._key(second)

    def test_two_events_about_one_message_produce_different_keys(self) -> None:
        # An edit and the create it edits are two events about one message, and
        # collapsing them would silently discard the correction.
        created = push_body(ce_id="ce-1", ce_type=CREATED)
        edited = push_body(ce_id="ce-2", ce_type=UPDATED)

        assert self._key(created) != self._key(edited)

    def test_the_key_is_a_digest_and_names_no_space(self) -> None:
        """`delivery_id` is on the telemetry allow-list and reaches spans.

        A Chat message resource name contains the space id, so the key being a
        digest is what keeps "no space name in telemetry" true by construction.
        """
        key = self._key(push_body())

        assert key.startswith("sha256:")
        assert SPACE not in key
        assert "MESSAGE1" not in key


class TestTheFastPath:
    def test_it_is_bounded_and_remembers_the_most_recent(self) -> None:
        """An optimisation and nothing else — correctness rests on the unique
        constraint, so this being lossy is by design."""
        recent = RecentMessageIds(capacity=2)
        for identifier in ("a", "b", "c"):
            recent.remember(identifier)

        assert not recent.seen("a")
        assert recent.seen("b")
        assert recent.seen("c")


# --------------------------------------------------------------------------
# Fixtures for the endpoint
# --------------------------------------------------------------------------


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def chat_app(queue: InMemoryJobQueue) -> FastAPI:
    """An app with a known audience, a known key, and an inspectable queue."""
    app = create_app(Settings(environment="test", cors_allowed_origins=("http://localhost:3000",)))
    app.state.queue = queue
    app.state.gchat_push_audience = AUDIENCE
    app.state.gchat_push_service_account = SERVICE_ACCOUNT
    app.state.gchat_push_subscription = SUBSCRIPTION
    app.state.gchat_signing_keys = StaticKeys()
    app.state.gchat_space_registry = StaticSpaceRegistry(subscriptions={})
    return app


@pytest.fixture
async def _clean_workspaces(platform: AsyncSession) -> AsyncIterator[None]:
    """Remove the workspaces a test created, afterwards.

    `platform` commits for real, so without this the second test to run would
    find two connections claiming one space. Deleting the tenant cascades to its
    connections and deliveries.
    """
    yield
    await platform.rollback()
    owners = (
        await platform.scalars(
            select(SourceConnection.tenant_id).where(
                SourceConnection.provider == ConnectorProvider.GOOGLE_CHAT,
                SourceConnection.external_account_id.in_([SPACE, OTHER_SPACE]),
            )
        )
    ).all()
    if owners:
        await platform.execute(delete(Tenant).where(Tenant.id.in_(list(owners))))
        await platform.commit()


async def _workspace(
    platform: AsyncSession,
    *,
    account: str,
    state: ConnectionState = ConnectionState.CONNECTED,
) -> SourceConnection:
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name=f"Acme {suffix}", slug=f"gchat-{suffix}")
    user = User(email=f"owner-{suffix}@example.com")
    platform.add_all([tenant, user])
    await platform.flush()
    platform.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.OWNER))

    connection = SourceConnection(
        tenant_id=tenant.id,
        provider=ConnectorProvider.GOOGLE_CHAT,
        external_account_id=account,
        installation_id=f"gchat-install-{suffix}",
        scopes=["chat.messages.readonly"],
        state=state,
        connected_at=datetime.now(UTC) - timedelta(days=1),
        authorised_by_user_id=user.id,
        authorised_at=datetime.now(UTC) - timedelta(days=1),
    )
    platform.add(connection)
    await platform.commit()
    return connection


@pytest.fixture
async def connection(
    platform: AsyncSession, chat_app: FastAPI, _clean_workspaces: None
) -> SourceConnection:
    """A connected Google Chat workspace with exactly one selected space."""
    record = await _workspace(platform, account=SPACE)
    chat_app.state.gchat_space_registry = StaticSpaceRegistry(
        subscriptions={
            SPACE: SpaceSubscription(
                tenant_id=record.tenant_id, connection_id=record.id, space_name=SPACE
            )
        }
    )
    return record


async def deliver(
    app: FastAPI, body: bytes, *, token: str | None = None, **mint_args: Any
) -> Response:
    """Send a push the way Pub/Sub would."""
    headers = {"Content-Type": "application/json"}
    bearer = token if token is not None else mint(**mint_args)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        return await http.post("/v1/webhooks/google-chat", content=body, headers=headers)


async def deliveries(platform: AsyncSession, tenant_id: uuid.UUID) -> list[WebhookDelivery]:
    return list(
        (
            await platform.scalars(
                select(WebhookDelivery).where(WebhookDelivery.tenant_id == tenant_id)
            )
        ).all()
    )


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------


@pytest.mark.integration
class TestVerificationComesFirst:
    async def test_a_verified_push_is_recorded_and_enqueued(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """The happy path, and the baseline every refusal below is measured
        against."""
        response = await deliver(chat_app, push_body())

        assert response.status_code == 202
        assert response.json() == {"status": "accepted"}

        [row] = await deliveries(platform, connection.tenant_id)
        assert row.status is DeliveryStatus.ACCEPTED
        assert row.event_type == CREATED
        assert row.action == "created"
        assert row.payload["message"]["name"] == f"{SPACE}/messages/MESSAGE1"

        [claimed] = await queue.receive(max_messages=5)
        assert claimed.envelope.job_type == GCHAT_EVENT_JOB
        # The tenant is on the envelope, which is what makes the worker's
        # session scoped. A job without one cannot be constructed at all.
        assert claimed.envelope.tenant_id == connection.tenant_id
        assert claimed.envelope.payload == {"delivery_id": row.delivery_id}

    async def test_acknowledgement_is_far_inside_the_ack_deadline(
        self, chat_app: FastAPI, connection: SourceConnection
    ) -> None:
        # The push deadline is the subscription's `ackDeadlineSeconds` — 10s by
        # default — and cannot be extended per message, so slow processing
        # becomes duplicate processing: load causing more load.
        started = time.perf_counter()
        response = await deliver(chat_app, push_body())
        elapsed = time.perf_counter() - started

        assert response.status_code == 202
        # Half the default deadline. Deliberately not tighter: the endpoint does
        # one verification, two indexed statements and one publish, and a
        # threshold tuned to a quiet machine fails on a loaded one for reasons
        # that have nothing to do with the code under test.
        assert elapsed < 5.0, f"took {elapsed:.2f}s; Pub/Sub allows 10s and cannot be extended"

    async def test_a_forged_token_is_refused_before_the_space_is_looked_up(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Asserted by outcome, not by reading the source.

        This push names a space nobody selected. If the space lookup ran first
        the answer would be the 200 an unpermitted space gets; it is a 401, so
        verification demonstrably ran before the lookup.
        """
        response = await deliver(
            chat_app, push_body(chat_message(space=UNSELECTED_SPACE)), key=_OTHER_KEY
        )

        assert response.status_code == 401
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

    @pytest.mark.parametrize(
        "forgery",
        [
            {"key": _OTHER_KEY},
            {"audience": "https://attacker.example/push"},
            {"issuer": "https://accounts.attacker.example"},
            {"expires_in": -1},
            {"email": "someone-else@other-project.iam.gserviceaccount.com"},
            {"email_verified": False},
        ],
        ids=["signature", "audience", "issuer", "expiry", "service-account", "unverified-email"],
    )
    async def test_every_broken_claim_is_refused(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
        forgery: dict[str, Any],
    ) -> None:
        response = await deliver(chat_app, push_body(), **forgery)

        assert response.status_code == 401
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_an_unauthenticated_push_is_refused(
        self, chat_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=chat_app), base_url="http://testserver"
        ) as http:
            response = await http.post("/v1/webhooks/google-chat", content=push_body())

        assert response.status_code == 401
        assert await queue.receive(max_messages=5) == []

    @pytest.mark.parametrize(
        "body",
        [b"{this is not json", b"[]", b'{"message":{"messageId":"1"}}'],
        ids=["not-json", "not-an-object", "no-subscription"],
    )
    async def test_a_malformed_envelope_is_refused_after_verification(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
        body: bytes,
    ) -> None:
        """Correctly signed, and not a push envelope. Refused identically to a
        forgery, so a malformed body cannot be used to probe which requests get
        further."""
        response = await deliver(chat_app, body)

        assert response.status_code == 401
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_malformed_base64_is_refused(
        self, chat_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        response = await deliver(chat_app, push_body(data="not!valid!base64!"))

        assert response.status_code == 401
        assert await queue.receive(max_messages=5) == []

    async def test_a_push_from_another_subscription_is_refused(
        self, chat_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        response = await deliver(
            chat_app, push_body(subscription="projects/theirs/subscriptions/theirs")
        )

        assert response.status_code == 401
        assert await queue.receive(max_messages=5) == []

    async def test_the_rejection_does_not_say_what_was_wrong(
        self, chat_app: FastAPI, connection: SourceConnection
    ) -> None:
        # Telling a forger which claim failed tells them how to fix it.
        forged = await deliver(chat_app, push_body(), key=_OTHER_KEY)
        expired = await deliver(chat_app, push_body(), expires_in=-1)
        malformed = await deliver(chat_app, b"{not json")

        assert forged.json()["detail"] == expired.json()["detail"] == malformed.json()["detail"]

    async def test_an_oversized_payload_is_refused(self, chat_app: FastAPI) -> None:
        # An unauthenticated endpoint that will base64-decode megabytes on
        # demand is an amplification vector. Size is checked before the crypto,
        # so the cost is never paid.
        body = b'{"padding":"' + b"x" * (2 * 1024 * 1024) + b'"}'

        response = await deliver(chat_app, body)

        assert response.status_code == 413


@pytest.mark.integration
class TestRetryVocabulary:
    async def test_an_unreachable_key_set_returns_non_2xx_so_pubsub_redelivers(
        self, chat_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        """The one transient refusal.

        Anything outside {102, 200, 201, 202, 204} NACKs and Pub/Sub redelivers
        with backoff — which is exactly what should happen while Google's key
        set is unreachable. Answering it 2xx would silently drop the message.
        """
        chat_app.state.gchat_signing_keys = UnavailableKeys()

        response = await deliver(chat_app, push_body())

        assert response.status_code == 503
        assert response.status_code not in {102, 200, 201, 202, 204}
        assert await queue.receive(max_messages=5) == []

    @pytest.mark.parametrize(
        "case",
        ["unknown_space", "unsupported_event", "bot_sender"],
    )
    async def test_a_permanent_refusal_acknowledges(
        self, chat_app: FastAPI, connection: SourceConnection, case: str
    ) -> None:
        """The opposite failure, and the one that costs more.

        A non-2xx here would bring the same declined message back every minute
        until it dead-letters — for an unselected space, that is repeated
        arrival of content a customer asked us not to read.
        """
        bodies = {
            "unknown_space": push_body(chat_message(space=UNSELECTED_SPACE)),
            "unsupported_event": push_body(ce_type="google.workspace.chat.reaction.v1.created"),
            "bot_sender": push_body(chat_message(sender_type="BOT")),
        }

        response = await deliver(chat_app, bodies[case])

        assert response.status_code in {102, 200, 201, 202, 204}


@pytest.mark.integration
class TestSpaceSelectionIsTheGate:
    async def test_an_unselected_space_leaves_no_trace(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Not stored, not queued, not logged, not retained.

        Every one of those is asserted, because "we do not read that space" is
        only true if the message never lands anywhere — a row written and then
        ignored is still a row of content nobody consented to.
        """
        with structlog.testing.capture_logs() as captured:
            response = await deliver(chat_app, push_body(chat_message(space=UNSELECTED_SPACE)))

        assert response.status_code == 200
        assert response.json() == {"status": "rejected"}
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

        rendered = json.dumps(captured, default=str)
        assert MESSAGE_TEXT not in rendered
        assert UNSELECTED_SPACE not in rendered
        assert SENDER not in rendered

    async def test_a_disconnected_workspace_stops_being_captured(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Disconnection is a consent boundary, not a technical one.

        Google keeps delivering until the subscription lapses. Processing those
        events means capturing activity for a customer who switched the
        integration off.
        """
        chat_app.state.gchat_space_registry = StaticSpaceRegistry(
            subscriptions={
                SPACE: SpaceSubscription(
                    tenant_id=connection.tenant_id,
                    connection_id=connection.id,
                    space_name=SPACE,
                    active=False,
                )
            }
        )

        response = await deliver(chat_app, push_body())

        assert response.status_code == 200
        assert response.json() == {"status": "rejected"}
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_the_production_registry_resolves_a_real_selection_row(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """The vertical slice: no stubbed registry anywhere in this test.

        The override is removed, so tenancy comes from the row a connect flow
        writes — `google_chat_space_selections`, joined to the connection it
        hangs off — through `StoredSpaceRegistry`. A registry that works only
        when a test supplies the mapping is a layer nothing in production calls.
        """
        user = await platform.scalar(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == connection.tenant_id)
        )
        assert user is not None
        platform.add(
            GoogleChatSpaceSelection(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                space_name=SPACE,
                selected_by_user_id=user.id,
            )
        )
        await platform.commit()
        del chat_app.state.gchat_space_registry

        response = await deliver(chat_app, push_body())

        assert response.status_code == 202
        [row] = await deliveries(platform, connection.tenant_id)
        assert row.tenant_id == connection.tenant_id
        [claimed] = await queue.receive(max_messages=5)
        assert claimed.envelope.tenant_id == connection.tenant_id

    async def test_the_production_registry_refuses_a_space_nobody_selected(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """The negative control for the test above, on the same real path.

        A connected Google Chat account permits nothing by itself: selection is
        the whole permission model, and its absence is a refusal rather than a
        default.
        """
        del chat_app.state.gchat_space_registry

        response = await deliver(chat_app, push_body())

        assert response.status_code == 200
        assert response.json() == {"status": "rejected"}
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_a_selection_outliving_a_disconnect_grants_nothing(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Through the production registry, not a stated flag.

        `SpaceSubscription.active` is computed from the connection, so a
        selection row that outlives a disconnect still ingests nothing: the
        selection is the permission, and the connection is the authorisation.
        Both have to hold.
        """
        user = await platform.scalar(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == connection.tenant_id)
        )
        assert user is not None
        platform.add(
            GoogleChatSpaceSelection(
                tenant_id=connection.tenant_id,
                connection_id=connection.id,
                space_name=SPACE,
                selected_by_user_id=user.id,
            )
        )
        connection.state = ConnectionState.DISCONNECTED
        connection.disconnected_at = datetime.now(UTC)
        await platform.commit()
        del chat_app.state.gchat_space_registry

        response = await deliver(chat_app, push_body())

        assert response.status_code == 200
        assert response.json() == {"status": "rejected"}
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_a_crafted_payload_cannot_move_an_event_to_another_workspace(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """A payload field is data, not authority.

        The body claims another workspace's tenant id and names a second space
        beside the message. The event still lands where the *selection* says,
        because the tenant comes from the space resolved against a mapping only
        an authenticated connect flow may write.
        """
        victim = await _workspace(platform, account=OTHER_SPACE)
        chat_app.state.gchat_space_registry = StaticSpaceRegistry(
            subscriptions={
                SPACE: SpaceSubscription(
                    tenant_id=connection.tenant_id, connection_id=connection.id, space_name=SPACE
                ),
                OTHER_SPACE: SpaceSubscription(
                    tenant_id=victim.tenant_id, connection_id=victim.id, space_name=OTHER_SPACE
                ),
            }
        )

        response = await deliver(
            chat_app,
            push_body(
                chat_message(),
                tenantId=str(victim.tenant_id),
                tenant_id=str(victim.tenant_id),
                space=OTHER_SPACE,
            ),
        )

        assert response.status_code == 202
        [row] = await deliveries(platform, connection.tenant_id)
        assert row.tenant_id == connection.tenant_id
        assert await deliveries(platform, victim.tenant_id) == []

    async def test_a_payload_that_disagrees_with_itself_about_its_space_is_dropped(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """`message.name` contains the space and `message.space.name` repeats it.

        Reconciling them would let one field name the space the tenant lookup
        used while another named the message that was stored.
        """
        response = await deliver(
            chat_app, push_body(chat_message(space=SPACE, stated_space=OTHER_SPACE))
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []


@pytest.mark.integration
class TestWhatIsNeverIngested:
    async def test_an_app_message_is_dropped(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Including CAIRN's own output — which is how the loop stays closed."""
        response = await deliver(chat_app, push_body(chat_message(sender_type="BOT")))

        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}
        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_a_message_with_no_sender_block_is_dropped(
        self, chat_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        # A payload with no `sender` at all: code reading the author before
        # filtering raises on the one class of message it was meant to drop.
        response = await deliver(chat_app, push_body(chat_message(sender=None)))

        assert response.status_code == 200
        assert await queue.receive(max_messages=5) == []

    @pytest.mark.parametrize(
        "ce_type",
        [
            "google.workspace.chat.reaction.v1.created",
            "google.workspace.chat.membership.v1.created",
            "google.workspace.chat.space.v1.updated",
            "google.workspace.chat.message.v2.created",
            "",
        ],
    )
    async def test_event_types_cairn_does_not_ingest_are_dropped(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
        ce_type: str,
    ) -> None:
        """An exhaustive list, not a prefix match: a prefix test would quietly
        start ingesting whatever Google adds to the namespace next."""
        body = push_body(ce_type=ce_type) if ce_type else push_body(ce_type=CREATED)
        if not ce_type:
            # No `ce-type` attribute at all — refused earlier, at naming.
            decoded = json.loads(body)
            del decoded["message"]["attributes"][CE_TYPE_ATTRIBUTE]
            response = await deliver(chat_app, json.dumps(decoded).encode("utf-8"))
            assert response.status_code == 401
        else:
            response = await deliver(chat_app, body)
            assert response.status_code == 200

        assert await deliveries(platform, connection.tenant_id) == []
        assert await queue.receive(max_messages=5) == []


@pytest.mark.integration
class TestIdempotency:
    async def test_a_redelivery_is_one_unit_of_work(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """At-least-once is the contract; exactly-once is pull-only.

        Without the unique constraint the same message is counted twice, which
        for a product whose output is "what happened this week" is a correctness
        failure a customer notices before we do.
        """
        body = push_body(ce_id="ce-redelivered", message_id="delivery-1")

        first = await deliver(chat_app, body)
        second = await deliver(chat_app, body)
        third = await deliver(chat_app, body)

        assert first.status_code == 202
        assert second.status_code == third.status_code == 200
        assert second.json() == {"status": "duplicate"}

        assert len(await deliveries(platform, connection.tenant_id)) == 1
        assert len(await queue.receive(max_messages=10)) == 1

    async def test_a_republish_under_a_new_message_id_still_dedupes(
        self,
        chat_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """The reason the key is not `messageId`.

        A Workspace Events retry or a subscription rebuild republishes the same
        Chat event under a new delivery id. The in-process fast path cannot see
        it, so this is the database constraint being exercised on its own.
        """
        first = await deliver(chat_app, push_body(ce_id="ce-1", message_id="delivery-1"))
        second = await deliver(chat_app, push_body(ce_id="ce-1", message_id="delivery-2"))

        assert first.status_code == 202
        assert second.status_code == 200
        assert second.json() == {"status": "duplicate"}
        assert len(await deliveries(platform, connection.tenant_id)) == 1
        assert len(await queue.receive(max_messages=10)) == 1

    async def test_distinct_events_are_both_accepted(
        self, chat_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        # The positive control. Without it the tests above would pass against an
        # endpoint that rejected every push after the first.
        await deliver(chat_app, push_body(chat_message(message_id="M1"), ce_id="ce-1"))
        await deliver(chat_app, push_body(chat_message(message_id="M2"), ce_id="ce-2"))

        assert len(await queue.receive(max_messages=10)) == 2


@pytest.mark.integration
class TestHealthIsHonest:
    async def test_an_accepted_push_records_a_successful_sync(
        self, chat_app: FastAPI, connection: SourceConnection, platform: AsyncSession
    ) -> None:
        before = connection.last_successful_sync_at
        assert before is None

        await deliver(chat_app, push_body())

        await platform.refresh(connection)
        assert connection.health is ConnectionHealth.HEALTHY
        assert connection.last_successful_sync_at is not None
        assert connection.last_error_category is None

    async def test_a_refused_space_never_reports_health(
        self, chat_app: FastAPI, connection: SourceConnection, platform: AsyncSession
    ) -> None:
        # A green tick over a space we are not reading is worse than no tick.
        await deliver(chat_app, push_body(chat_message(space=UNSELECTED_SPACE)))

        await platform.refresh(connection)
        assert connection.last_successful_sync_at is None


@pytest.mark.integration
class TestTelemetryCarriesNoContent:
    async def test_no_space_message_sender_or_address_reaches_a_span_or_a_log(
        self, chat_app: FastAPI, connection: SourceConnection
    ) -> None:
        """Asserted over what was *recorded*, not by reading the source.

        Telemetry leaves the product — to an exporter, a vendor, a dashboard and
        a retention policy none of which are covered by md/05's promises. A
        source-reading test passes the day somebody adds a field.
        """
        from cairn_api.telemetry import spans as span_module
        from cairn_api.telemetry.attributes import ALLOWED
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        original = span_module.tracer
        span_module.tracer = provider.get_tracer("cairn.test")

        try:
            with structlog.testing.capture_logs() as captured:
                accepted = await deliver(chat_app, push_body())
                # Refusals too: rejected paths log more, and are the ones most
                # likely to quote what was wrong with the request.
                await deliver(chat_app, push_body(), key=_OTHER_KEY)
                await deliver(chat_app, push_body(chat_message(space=UNSELECTED_SPACE)))
                await deliver(chat_app, push_body(chat_message(sender_type="BOT")))
        finally:
            span_module.tracer = original

        assert accepted.status_code == 202

        recorded = exporter.get_finished_spans()
        assert recorded, "the ingest stage should have produced spans"
        for span in recorded:
            attributes = dict(span.attributes or {})
            # An allow-list, not a deny-list: a banned-word check passes the
            # first time somebody adds an attribute nobody thought to ban.
            assert set(attributes) <= ALLOWED
            assert SPACE not in str(attributes)

        rendered = json.dumps(captured, default=str)
        for forbidden in (MESSAGE_TEXT, SENDER, SPACE, UNSELECTED_SPACE, SERVICE_ACCOUNT):
            assert forbidden not in rendered, f"{forbidden} reached a log line"

    async def test_a_rejected_push_does_not_log_the_payload_or_the_token(
        self, chat_app: FastAPI, connection: SourceConnection
    ) -> None:
        # The verification-failure log is the one most likely to quote the
        # request, and it is written before any tenant is known — so it has the
        # fewest reasons to be careful and the most need to be.
        token = mint(key=_OTHER_KEY)

        with structlog.testing.capture_logs() as captured:
            await deliver(chat_app, push_body(), token=token)

        rendered = json.dumps(captured, default=str)
        assert MESSAGE_TEXT not in rendered
        assert SENDER not in rendered
        assert token not in rendered
        assert SERVICE_ACCOUNT not in rendered


@pytest.mark.integration
class TestTheRouteIsMountedOnTheApp:
    async def test_a_default_app_answers_the_endpoint_rather_than_404ing(self) -> None:
        """A router written and never included is the same defect one level up.

        Asserted against a **default** application — no fixture, no state
        overrides — because the wiring being tested is `create_app`'s, and a test
        that mounted the router itself would prove only that the test can.

        401, not 404: with nothing configured the verifier refuses every request,
        which is the failing-closed half of the same wiring.
        """
        app = create_app(
            Settings(environment="test", cors_allowed_origins=("http://localhost:3000",))
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as http:
            response = await http.post("/v1/webhooks/google-chat", content=push_body())

        assert response.status_code != 404
        assert response.status_code == 401

    def test_the_job_it_publishes_has_a_handler_a_worker_can_resolve(self) -> None:
        """A router mounted without its handler publishes a job type no worker
        can resolve, which dead-letters as "unknown" — a wiring failure that
        looks like a queue problem."""
        from cairn_api.jobs.runner import registry as job_registry

        create_app(Settings(environment="test", cors_allowed_origins=("http://localhost:3000",)))

        assert GCHAT_EVENT_JOB in job_registry.registered_types()

    def test_it_is_not_in_the_generated_client(self) -> None:
        # It is Google's interface, not the frontend's, and publishing it would
        # put an unauthenticated write path into the TypeScript surface.
        #
        # Asserted on *this* path rather than on the absence of the string
        # "google-chat" anywhere in the document, which is what it used to say.
        # That was correct while the receiver was the only Google Chat route in
        # the application; the product surface (`api/routers/gchat.py`) is
        # session-authenticated, permission-gated and deliberately published, so
        # a blanket assertion would now fail on the routes a customer is meant to
        # call. `test_gchat_api.py` pins that published set exactly, so the
        # receiver cannot rejoin it unnoticed.
        app = create_app(
            Settings(environment="test", cors_allowed_origins=("http://localhost:3000",))
        )

        published = app.openapi()["paths"]
        assert "/v1/webhooks/google-chat" not in published
        assert not any(path.endswith("/webhooks/google-chat") for path in published)
