"""Slack event receipt: the signature, the workspace, and the channel gate.

The second unauthenticated write endpoint in the service. Everything downstream
— tenancy, storage, the queue, the record a customer reads — trusts what this
path lets through, so every forgery below is constructed the way an attacker
would rather than by patching a control out. A test that disables the control
proves the handler works when the control is absent, which is not a property
anyone wants.

Three groups carry the most weight:

* **verification runs first.** The tests assert it by *outcome*: a request with
  a bad signature and an unknown workspace is answered 401, not the 400 an
  unknown workspace gets — so verification demonstrably preceded the lookup.
* **the channel gate leaves no trace.** An event from an unselected channel is
  asserted to produce no delivery row, no job, and no log line containing the
  channel or the message.
* **an edit is an update.** Asserted end to end, over HTTP, because the identity
  rule is only useful if the endpoint actually stores it.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog
from cairn_api.api.app import create_app
from cairn_api.config import Settings
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.slack_models import SlackChannelSelection
from cairn_api.ingestion import InboundRequest, VerificationError
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.memory import InMemoryJobQueue
from cairn_api.slack.events import SLACK_EVENT_JOB, SlackDeliveryNotFoundError, handle_slack_event
from cairn_api.slack.inbound import (
    NO_RETRY_HEADER,
    REPLAY_WINDOW_SECONDS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    SlackInbound,
    sign,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

# Every secret in this file is a literal by necessity.
# ruff: noqa: S105, S106
SECRET = "slack-signing-secret-for-tests"

TEAM = "T0ACME01"
OTHER_TEAM = "T0OTHER99"
SELECTED_CHANNEL = "C0SELECTED1"
UNSELECTED_CHANNEL = "C0UNSELECTED"
USER = "U07PRIYA"
TS = "1755400000.000100"
EDIT_TS = "1755409999.000900"

#: Distinctive enough that finding it anywhere it should not be is unambiguous.
MESSAGE_TEXT = "Priya is deferring the payments migration until the audit clears."


def headers_for(
    body: bytes,
    *,
    secret: str = SECRET,
    timestamp: str | None = None,
    signature: str | None = None,
) -> dict[str, str]:
    """Sign these exact bytes, the way Slack does."""
    stamp = timestamp if timestamp is not None else str(int(time.time()))
    return {
        TIMESTAMP_HEADER: stamp,
        SIGNATURE_HEADER: signature if signature is not None else sign(body, stamp, secret),
        "Content-Type": "application/json",
    }


def request_for(payload: dict[str, Any], **kwargs: Any) -> InboundRequest:
    body = json.dumps(payload).encode("utf-8")
    return InboundRequest(body=body, headers=headers_for(body, **kwargs))


# --------------------------------------------------------------------------
# Signature verification, on its own
# --------------------------------------------------------------------------


class TestSignatureVerification:
    def test_a_correct_signature_verifies(self) -> None:
        SlackInbound(secret=SECRET).verify(request_for({"type": "event_callback"}))

    def test_a_signature_from_a_different_secret_is_rejected(self) -> None:
        with pytest.raises(VerificationError, match="does not match"):
            SlackInbound(secret=SECRET).verify(
                request_for({"type": "event_callback"}, secret="attacker-guessed-this")
            )

    def test_a_signature_for_different_bytes_is_rejected(self) -> None:
        """The realistic attack: capture a signed delivery, alter it, replay it.

        The signature covers the raw bytes, which is also why the endpoint
        verifies before anything parses — a re-serialised body is a different
        byte string however equivalent it looks.
        """
        original = b'{"type":"event_callback","team_id":"T0ACME01"}'
        tampered = b'{"type":"event_callback","team_id":"T0OTHER99"}'
        stamp = str(int(time.time()))

        with pytest.raises(VerificationError, match="does not match"):
            SlackInbound(secret=SECRET).verify(
                InboundRequest(
                    body=tampered,
                    headers={
                        TIMESTAMP_HEADER: stamp,
                        SIGNATURE_HEADER: sign(original, stamp, SECRET),
                    },
                )
            )

    def test_a_missing_signature_is_rejected(self) -> None:
        # The catastrophic implementation is `if signature: verify(...)`, which
        # accepts every request that simply omits the header.
        body = b"{}"
        stamp = str(int(time.time()))

        with pytest.raises(VerificationError, match="Missing signature"):
            SlackInbound(secret=SECRET).verify(
                InboundRequest(body=body, headers={TIMESTAMP_HEADER: stamp})
            )

    def test_a_missing_timestamp_is_rejected(self) -> None:
        body = b"{}"

        with pytest.raises(VerificationError, match="Missing request timestamp"):
            SlackInbound(secret=SECRET).verify(
                InboundRequest(
                    body=body,
                    headers={SIGNATURE_HEADER: sign(body, "1755400000", SECRET)},
                )
            )

    @pytest.mark.parametrize("timestamp", ["", "not-a-number", "1755400000.5", "0x10"])
    def test_a_malformed_timestamp_is_rejected(self, timestamp: str) -> None:
        with pytest.raises(VerificationError):
            SlackInbound(secret=SECRET).verify(request_for({"type": "x"}, timestamp=timestamp))

    def test_a_stale_timestamp_is_rejected_even_with_a_valid_signature(self) -> None:
        """Slack's documented replay window, and the reason it works.

        The timestamp is *inside* the signed string, so an attacker replaying a
        captured delivery cannot refresh it — rewriting the header invalidates
        the signature. The window is what makes the capture worthless once it
        is five minutes old.
        """
        now = 1_755_400_000.0
        stale = str(int(now - REPLAY_WINDOW_SECONDS - 1))
        provider = SlackInbound(secret=SECRET, now=lambda: now)

        with pytest.raises(VerificationError, match="replay window"):
            provider.verify(request_for({"type": "event_callback"}, timestamp=stale))

    def test_a_timestamp_just_inside_the_window_is_accepted(self) -> None:
        # The positive control: without it, the test above would pass against a
        # verifier that rejected every timestamp.
        now = 1_755_400_000.0
        recent = str(int(now - REPLAY_WINDOW_SECONDS + 1))

        SlackInbound(secret=SECRET, now=lambda: now).verify(
            request_for({"type": "event_callback"}, timestamp=recent)
        )

    def test_a_future_timestamp_is_rejected(self) -> None:
        """Skew large enough to matter is indistinguishable from a forgery.

        Checking only "too old" leaves an attacker free to stamp a capture a
        year ahead and replay it whenever they like.
        """
        now = 1_755_400_000.0
        ahead = str(int(now + REPLAY_WINDOW_SECONDS + 1))

        with pytest.raises(VerificationError, match="replay window"):
            SlackInbound(secret=SECRET, now=lambda: now).verify(
                request_for({"type": "event_callback"}, timestamp=ahead)
            )

    def test_a_signature_of_another_version_is_not_accepted(self) -> None:
        # Accepting whatever version a header claims is how a future weaker
        # scheme gets accepted by an endpoint written before it existed.
        body = b"{}"
        stamp = str(int(time.time()))
        digest = sign(body, stamp, SECRET).split("=", 1)[1]

        with pytest.raises(VerificationError, match="not v0"):
            SlackInbound(secret=SECRET).verify(
                InboundRequest(
                    body=body,
                    headers={TIMESTAMP_HEADER: stamp, SIGNATURE_HEADER: f"v1={digest}"},
                )
            )

    def test_a_blank_secret_refuses_rather_than_passing(self) -> None:
        # An empty secret makes every signature verifiable. Failing here turns a
        # misconfiguration into an outage instead of an open door.
        with pytest.raises(VerificationError, match="No Slack signing secret"):
            SlackInbound(secret="").verify(request_for({"type": "event_callback"}, secret=""))


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _clean_slack_workspaces(platform: AsyncSession) -> AsyncIterator[None]:
    """Remove the workspaces a test created, afterwards.

    `platform` commits for real, so without this the second test to run would
    find two connections claiming `TEAM` — and the resolver would (correctly)
    refuse the ambiguity, failing tests for a reason that has nothing to do with
    what they assert. Deleting the tenant cascades to its connections,
    selections and deliveries.
    """
    yield
    # A test that deliberately triggers an integrity error leaves this session's
    # transaction aborted, and every statement below would then be ignored.
    await platform.rollback()
    owners = (
        await platform.scalars(
            select(SourceConnection.tenant_id).where(
                SourceConnection.provider == ConnectorProvider.SLACK,
                SourceConnection.external_account_id.in_([TEAM, OTHER_TEAM]),
            )
        )
    ).all()
    if owners:
        await platform.execute(delete(Tenant).where(Tenant.id.in_(list(owners))))
        await platform.commit()


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def slack_app(queue: InMemoryJobQueue) -> FastAPI:
    """An app with a known signing secret and an inspectable queue."""
    app = create_app(Settings(environment="test", cors_allowed_origins=("http://localhost:3000",)))
    app.state.queue = queue
    app.state.slack_signing_secret = SECRET
    return app


async def _workspace(
    platform: AsyncSession, *, team_id: str, state: ConnectionState = ConnectionState.CONNECTED
) -> tuple[SourceConnection, User]:
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name=f"Acme {suffix}", slug=f"acme-{suffix}")
    user = User(email=f"owner-{suffix}@example.com")
    platform.add_all([tenant, user])
    await platform.flush()
    platform.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.OWNER))

    connection = SourceConnection(
        tenant_id=tenant.id,
        provider=ConnectorProvider.SLACK,
        external_account_id=team_id,
        # Globally unique per provider: a shared value would make these tests
        # pass or fail by execution order.
        installation_id=f"slack-install-{suffix}",
        scopes=["channels:history", "channels:read"],
        state=state,
        connected_at=datetime.now(UTC) - timedelta(days=1),
        authorised_by_user_id=user.id,
        authorised_at=datetime.now(UTC) - timedelta(days=1),
    )
    platform.add(connection)
    await platform.commit()
    return connection, user


@pytest.fixture
async def connection(platform: AsyncSession) -> SourceConnection:
    """A connected Slack workspace with exactly one selected channel."""
    record, user = await _workspace(platform, team_id=TEAM)
    platform.add(
        SlackChannelSelection(
            tenant_id=record.tenant_id,
            connection_id=record.id,
            channel_id=SELECTED_CHANNEL,
            selected_by_user_id=user.id,
        )
    )
    await platform.commit()
    return record


def event_id() -> str:
    """Slack's shape: `Ev` and an opaque suffix. Unique per call."""
    return f"Ev{uuid.uuid4().hex[:12].upper()}"


def message_event(
    *,
    channel: str = SELECTED_CHANNEL,
    channel_type: str = "channel",
    text: str = MESSAGE_TEXT,
    ts: str = TS,
    user: str | None = USER,
    subtype: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "message",
        "channel": channel,
        "channel_type": channel_type,
        "ts": ts,
        "text": text,
    }
    if user is not None:
        event["user"] = user
    if subtype is not None:
        event["subtype"] = subtype
    if extra:
        event.update(extra)
    return event


def envelope(
    event: dict[str, Any] | None = None,
    *,
    team_id: str | None = TEAM,
    delivery: str | None = None,
    **top_level: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "event_callback", "event_id": delivery or event_id()}
    if team_id is not None:
        payload["team_id"] = team_id
    payload["event"] = event if event is not None else message_event()
    payload.update(top_level)
    return payload


async def deliver(app: FastAPI, payload: dict[str, Any], **signing: Any) -> Response:
    """Send an event the way Slack would.

    The body is serialised once and *that byte string* is both signed and sent;
    re-serialising in between would fail verification for reasons unrelated to
    the test.
    """
    body = json.dumps(payload).encode("utf-8")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        return await http.post(
            "/v1/webhooks/slack", content=body, headers=headers_for(body, **signing)
        )


async def deliveries(platform: AsyncSession, delivery_id: str) -> list[WebhookDelivery]:
    return list(
        (
            await platform.scalars(
                select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
            )
        ).all()
    )


# --------------------------------------------------------------------------
# Verification runs before anything else
# --------------------------------------------------------------------------


class TestVerificationComesFirst:
    async def test_a_verified_message_is_recorded_and_enqueued(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """The happy path, and the baseline every refusal below is measured
        against."""
        delivery_id = event_id()

        response = await deliver(slack_app, envelope(delivery=delivery_id))

        assert response.status_code == 202
        assert response.json() == {"status": "accepted"}

        [row] = await deliveries(platform, delivery_id)
        assert row.tenant_id == connection.tenant_id
        assert row.status is DeliveryStatus.ACCEPTED

        [claimed] = await queue.receive(max_messages=5)
        assert claimed.envelope.job_type == SLACK_EVENT_JOB
        # The tenant is on the envelope, which is what makes the worker's
        # session scoped. A job without one cannot be constructed at all.
        assert claimed.envelope.tenant_id == connection.tenant_id
        assert claimed.envelope.payload == {"delivery_id": delivery_id}

    async def test_acknowledgement_is_far_inside_slacks_three_second_budget(
        self, slack_app: FastAPI, connection: SourceConnection
    ) -> None:
        # Miss the 3s budget and Slack retries, so slow processing becomes
        # duplicate processing — load causing more load.
        started = time.perf_counter()
        response = await deliver(slack_app, envelope())
        elapsed = time.perf_counter() - started

        assert response.status_code == 202
        assert elapsed < 1.0, f"took {elapsed:.2f}s; Slack allows 3s"

    async def test_a_forged_signature_is_refused_before_the_workspace_is_looked_up(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Asserted by outcome, not by reading the source.

        This payload names a workspace that does not exist. If tenant resolution
        ran first the answer would be the 400 an unknown workspace gets; it is a
        401, so verification demonstrably ran before the lookup.
        """
        delivery_id = event_id()

        response = await deliver(
            slack_app,
            envelope(team_id="T0NOBODY", delivery=delivery_id),
            secret="attacker-guessed-this",
        )

        assert response.status_code == 401
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_a_stale_delivery_is_refused_before_the_workspace_is_looked_up(
        self, slack_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        stale = str(int(time.time()) - REPLAY_WINDOW_SECONDS - 60)

        response = await deliver(slack_app, envelope(), timestamp=stale)

        assert response.status_code == 401
        assert await queue.receive(max_messages=5) == []

    async def test_a_future_skewed_delivery_is_refused(
        self, slack_app: FastAPI, connection: SourceConnection
    ) -> None:
        ahead = str(int(time.time()) + REPLAY_WINDOW_SECONDS + 60)

        response = await deliver(slack_app, envelope(), timestamp=ahead)

        assert response.status_code == 401

    async def test_a_malformed_signature_header_is_refused(
        self, slack_app: FastAPI, connection: SourceConnection
    ) -> None:
        response = await deliver(slack_app, envelope(), signature="not-a-signature")

        assert response.status_code == 401

    async def test_an_unsigned_request_is_refused(
        self, slack_app: FastAPI, connection: SourceConnection
    ) -> None:
        body = json.dumps(envelope()).encode("utf-8")
        async with AsyncClient(
            transport=ASGITransport(app=slack_app), base_url="http://testserver"
        ) as http:
            response = await http.post("/v1/webhooks/slack", content=body)

        assert response.status_code == 401

    async def test_a_malformed_body_is_refused_after_verification(
        self, slack_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        """Correctly signed, and not JSON. Refused identically to a forgery.

        Rejected *after* the signature check rather than before, so a malformed
        body cannot be used to probe which requests get further.
        """
        body = b"{this is not json"
        async with AsyncClient(
            transport=ASGITransport(app=slack_app), base_url="http://testserver"
        ) as http:
            response = await http.post(
                "/v1/webhooks/slack", content=body, headers=headers_for(body)
            )

        assert response.status_code == 401
        assert await queue.receive(max_messages=5) == []

    async def test_the_rejection_does_not_say_what_was_wrong(
        self, slack_app: FastAPI, connection: SourceConnection
    ) -> None:
        # Telling a forger which part of their forgery failed tells them how to
        # fix it — including whether a timestamp or a signature was the problem.
        forged = await deliver(slack_app, envelope(), secret="wrong")
        stale = await deliver(slack_app, envelope(), timestamp=str(int(time.time()) - 10_000))
        unsigned = await deliver(slack_app, envelope(), signature="")

        assert forged.json()["detail"] == stale.json()["detail"] == unsigned.json()["detail"]

    async def test_an_oversized_payload_is_refused(self, slack_app: FastAPI) -> None:
        # An unauthenticated endpoint that will hash megabytes on demand is an
        # amplification vector. Size is checked before the HMAC, so the cost is
        # never paid.
        body = b'{"padding":"' + b"x" * (2 * 1024 * 1024) + b'"}'
        async with AsyncClient(
            transport=ASGITransport(app=slack_app), base_url="http://testserver"
        ) as http:
            response = await http.post(
                "/v1/webhooks/slack", content=body, headers=headers_for(body)
            )

        assert response.status_code == 413


class TestUrlVerification:
    async def test_a_challenge_with_a_bad_signature_is_refused(self, slack_app: FastAPI) -> None:
        """Slack signs `url_verification` like everything else.

        Special-casing it to answer before verification — which is the shape of
        every "just get the endpoint verified" fix — leaves an unauthenticated
        endpoint that echoes an attacker's chosen string back to them.
        """
        challenge = "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P"

        response = await deliver(
            slack_app,
            {"type": "url_verification", "token": "legacy", "challenge": challenge},
            secret="attacker-guessed-this",
        )

        assert response.status_code == 401
        assert challenge not in response.text

    async def test_a_signed_challenge_is_answered(self, slack_app: FastAPI) -> None:
        challenge = "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P"

        response = await deliver(
            slack_app, {"type": "url_verification", "token": "legacy", "challenge": challenge}
        )

        assert response.status_code == 200
        assert response.json() == {"challenge": challenge}


# --------------------------------------------------------------------------
# Which workspace, and which channel
# --------------------------------------------------------------------------


class TestTenancyFailsClosed:
    async def test_an_unknown_workspace_is_refused_permanently(
        self, slack_app: FastAPI, queue: InMemoryJobQueue, platform: AsyncSession
    ) -> None:
        """No default workspace, no first row, and no three retries of it.

        Slack retries a non-200 three times; an unknown workspace will still be
        unknown in five minutes, so the no-retry header turns three deliveries
        of a stranger's messages into one.
        """
        delivery_id = event_id()

        response = await deliver(slack_app, envelope(team_id="T0NOBODY", delivery=delivery_id))

        assert response.status_code == 400
        assert response.headers[NO_RETRY_HEADER] == "1"
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_a_disconnected_workspace_stops_being_captured(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Disconnection is a consent boundary, not a technical one.

        Slack keeps delivering until the app is removed. Processing those events
        means capturing activity for a customer who switched the integration
        off, which for this product is a consent failure rather than a bug.
        """
        connection.state = ConnectionState.DISCONNECTED
        connection.disconnected_at = datetime.now(UTC)
        await platform.commit()

        delivery_id = event_id()
        response = await deliver(slack_app, envelope(delivery=delivery_id))

        assert response.status_code == 400
        assert response.headers[NO_RETRY_HEADER] == "1"
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_a_crafted_payload_cannot_move_an_event_to_another_workspace(
        self, slack_app: FastAPI, connection: SourceConnection, platform: AsyncSession
    ) -> None:
        """A payload field is data, not authority.

        The body here claims another workspace's tenant id, a `team` and an
        `enterprise_id`. The event still lands where the *connection* says,
        because the tenant comes from `team_id` resolved against a mapping only
        an authenticated connect flow may write.
        """
        victim, _ = await _workspace(platform, team_id=OTHER_TEAM)
        delivery_id = event_id()

        response = await deliver(
            slack_app,
            envelope(
                delivery=delivery_id,
                tenant_id=str(victim.tenant_id),
                team=OTHER_TEAM,
                enterprise_id="E0EVIL",
            ),
        )

        assert response.status_code == 202
        [row] = await deliveries(platform, delivery_id)
        assert row.tenant_id == connection.tenant_id
        assert row.tenant_id != victim.tenant_id

    async def test_two_connections_claiming_one_team_resolve_to_neither(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Ambiguity is a refusal, never "take the first".

        Two workspaces claiming one Slack team means either could be handed the
        other's messages, and whichever the query happened to order first would
        start the leak silently.
        """
        await _workspace(platform, team_id=TEAM)
        delivery_id = event_id()

        response = await deliver(slack_app, envelope(delivery=delivery_id))

        assert response.status_code == 400
        assert response.headers[NO_RETRY_HEADER] == "1"
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []


class TestChannelSelectionIsTheGate:
    async def test_an_unselected_channel_leaves_no_trace(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Not stored, not queued, not logged, not retained.

        Every one of those is asserted, because "we do not read that channel" is
        only true if the message never lands anywhere — a row written and then
        ignored is still a row of content nobody consented to.
        """
        delivery_id = event_id()

        with structlog.testing.capture_logs() as captured:
            response = await deliver(
                slack_app,
                envelope(message_event(channel=UNSELECTED_CHANNEL), delivery=delivery_id),
            )

        assert response.status_code == 400
        assert response.headers[NO_RETRY_HEADER] == "1"
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []

        rendered = json.dumps(captured, default=str)
        assert MESSAGE_TEXT not in rendered
        assert UNSELECTED_CHANNEL not in rendered
        assert USER not in rendered

    async def test_a_selection_on_another_connection_grants_nothing(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Channel ids are unique per Slack workspace, not globally.

        A tenant-scoped check would let a channel selected on one connection
        permit an identically-numbered channel on another — which is a
        cross-workspace read with no attacker required.
        """
        other, other_user = await _workspace(platform, team_id=OTHER_TEAM)
        platform.add(
            SlackChannelSelection(
                tenant_id=other.tenant_id,
                connection_id=other.id,
                channel_id=UNSELECTED_CHANNEL,
                selected_by_user_id=other_user.id,
            )
        )
        await platform.commit()

        delivery_id = event_id()
        response = await deliver(
            slack_app, envelope(message_event(channel=UNSELECTED_CHANNEL), delivery=delivery_id)
        )

        assert response.status_code == 400
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []


class TestWhatIsNeverIngested:
    @pytest.mark.parametrize("channel_type", ["im", "mpim", "group"])
    async def test_direct_and_private_conversations_are_never_ingested(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
        channel_type: str,
    ) -> None:
        # Even claiming the selected channel id: the conversation type is
        # checked on its own, so a payload cannot smuggle a DM in under a
        # selected channel's id.
        delivery_id = event_id()

        response = await deliver(
            slack_app,
            envelope(message_event(channel_type=channel_type), delivery=delivery_id),
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []

    async def test_a_bot_message_is_dropped(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Including our own output — which is how the loop stays closed.

        The payload has no `user` field, exactly as Slack sends it, so an
        implementation reading the author before filtering raises rather than
        dropping.
        """
        delivery_id = event_id()

        response = await deliver(
            slack_app,
            envelope(
                message_event(user=None, subtype="bot_message", extra={"bot_id": "B0CAIRN01"}),
                delivery=delivery_id,
            ),
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ignored"}
        assert await deliveries(platform, delivery_id) == []
        assert await queue.receive(max_messages=5) == []


# --------------------------------------------------------------------------
# Idempotency, edits and deletes
# --------------------------------------------------------------------------


class TestIdempotency:
    async def test_a_retried_event_is_one_unit_of_work(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Slack retries three times — immediately, at a minute, at five.

        Without the unique constraint the same message is counted three times,
        which for a product whose output is "what happened this week" is a
        correctness failure a customer notices before we do.
        """
        delivery_id = event_id()
        payload = envelope(delivery=delivery_id)

        first = await deliver(slack_app, payload)
        second = await deliver(slack_app, payload)
        third = await deliver(slack_app, payload)

        assert first.status_code == 202
        # 200 rather than 202: acknowledged, but nothing new was accepted.
        assert second.status_code == third.status_code == 200
        assert second.json() == {"status": "duplicate"}

        assert len(await deliveries(platform, delivery_id)) == 1
        assert len(await queue.receive(max_messages=10)) == 1

    async def test_distinct_events_are_both_accepted(
        self, slack_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        # The positive control. Without it the test above would pass against an
        # endpoint that rejected every event after the first.
        await deliver(slack_app, envelope(delivery=event_id()))
        await deliver(
            slack_app, envelope(message_event(ts="1755400001.000200"), delivery=event_id())
        )

        assert len(await queue.receive(max_messages=10)) == 2

    async def test_the_key_is_the_top_level_event_id(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """`event_id` is a sibling of `type`, not a field of `event`.

        A nested `event.event_id` — which Slack does not send — must not become
        the key: this payload carries a decoy there, and the delivery is
        recorded under the real one.
        """
        delivery_id = event_id()
        payload = envelope(message_event(extra={"event_id": "EvDECOY000000"}), delivery=delivery_id)

        await deliver(slack_app, payload)

        assert len(await deliveries(platform, delivery_id)) == 1
        assert await deliveries(platform, "EvDECOY000000") == []


class TestEditsAndDeletes:
    async def test_an_edit_is_stored_against_the_original_message(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """End to end, because the identity rule only matters if it is stored.

        The edit's own `event.ts` is `EDIT_TS`; the record keeps the original
        `TS`, so downstream the edit updates one statement instead of creating a
        second one and leaving the stale claim standing as current.
        """
        from cairn_api.slack.events import SlackMessage as ParsedMessage
        from cairn_api.slack.events import normalise, read_envelope, read_message

        created_id = event_id()
        edited_id = event_id()
        await deliver(slack_app, envelope(delivery=created_id))
        response = await deliver(
            slack_app,
            envelope(
                {
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": SELECTED_CHANNEL,
                    "channel_type": "channel",
                    "ts": EDIT_TS,
                    "message": {"user": USER, "text": "Actually it ships Monday.", "ts": TS},
                },
                delivery=edited_id,
            ),
        )

        assert response.status_code == 202
        [created] = await deliveries(platform, created_id)
        [edited] = await deliveries(platform, edited_id)
        assert created.action == "created"
        assert edited.action == "edited"

        # Both stored payloads normalise onto one identity.
        identities = set()
        for row in (created, edited):
            parsed = read_envelope(json.dumps(row.payload).encode("utf-8"))
            assert parsed is not None
            message = read_message(parsed)
            assert isinstance(message, ParsedMessage)
            identities.add(normalise(message, tenant_id=row.tenant_id).id)

        assert identities == {f"{TEAM}:{SELECTED_CHANNEL}:{TS}"}

    async def test_a_delete_is_accepted_and_names_the_deleted_message(
        self, slack_app: FastAPI, connection: SourceConnection, platform: AsyncSession
    ) -> None:
        delivery_id = event_id()

        response = await deliver(
            slack_app,
            envelope(
                {
                    "type": "message",
                    "subtype": "message_deleted",
                    "channel": SELECTED_CHANNEL,
                    "channel_type": "channel",
                    "ts": EDIT_TS,
                    "deleted_ts": TS,
                },
                delivery=delivery_id,
            ),
        )

        assert response.status_code == 202
        [row] = await deliveries(platform, delivery_id)
        assert row.action == "deleted"


class TestTheWorkerSide:
    async def test_processing_marks_the_delivery_done(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        from cairn_api.db.tenancy import tenant_session

        delivery_id = event_id()
        await deliver(slack_app, envelope(delivery=delivery_id))

        job = JobEnvelope(
            job_type=SLACK_EVENT_JOB,
            tenant_id=connection.tenant_id,
            payload={"delivery_id": delivery_id},
        )
        async with tenant_session(connection.tenant_id) as session:
            await handle_slack_event(session, job)
        # At-least-once delivery guarantees a second run happens eventually;
        # treating it as an error would fill the dead-letter queue with
        # successful work.
        async with tenant_session(connection.tenant_id) as session:
            await handle_slack_event(session, job)

        [row] = await deliveries(platform, delivery_id)
        await platform.refresh(row)
        assert row.status is DeliveryStatus.PROCESSED
        assert row.processed_at is not None

    async def test_a_handler_cannot_reach_another_workspaces_delivery(
        self,
        slack_app: FastAPI,
        connection: SourceConnection,
        platform: AsyncSession,
    ) -> None:
        """Row-level security, asserted where new data enters the system.

        A job naming a real delivery id but the wrong tenant must find nothing —
        not the row.
        """
        from cairn_api.db.tenancy import tenant_session

        delivery_id = event_id()
        await deliver(slack_app, envelope(delivery=delivery_id))
        other, _ = await _workspace(platform, team_id=OTHER_TEAM)

        job = JobEnvelope(
            job_type=SLACK_EVENT_JOB,
            tenant_id=other.tenant_id,
            payload={"delivery_id": delivery_id},
        )
        async with tenant_session(other.tenant_id) as session:
            with pytest.raises(SlackDeliveryNotFoundError):
                await handle_slack_event(session, job)


# --------------------------------------------------------------------------
# Honest health, and teardown
# --------------------------------------------------------------------------


class TestHealthIsHonest:
    async def test_an_accepted_delivery_records_a_successful_sync(
        self, slack_app: FastAPI, connection: SourceConnection, platform: AsyncSession
    ) -> None:
        # Read into a local: asserting on the attribute would narrow it for the
        # rest of the test, and the refresh below is what changes it.
        before = connection.last_successful_sync_at
        assert before is None

        await deliver(slack_app, envelope())

        await platform.refresh(connection)
        assert connection.health is ConnectionHealth.HEALTHY
        assert connection.last_successful_sync_at is not None
        assert connection.last_error_category is None

    async def test_app_rate_limited_is_never_healthy(
        self, slack_app: FastAPI, connection: SourceConnection, platform: AsyncSession
    ) -> None:
        """Slack is *dropping* this workspace's events, not delaying them.

        The events discarded during the rate-limited minute are never re-sent,
        so the record has a hole in it. A green tick over a hole is the failure
        md/05 calls worse than an honest one.
        """
        await deliver(slack_app, envelope())  # healthy first, so the change is visible

        response = await deliver(
            slack_app,
            {
                "type": "app_rate_limited",
                "team_id": TEAM,
                "token": "legacy",
                "minute_rate_limited": 1_755_400_000,
            },
        )

        assert response.status_code == 200
        await platform.refresh(connection)
        assert connection.health is not ConnectionHealth.HEALTHY
        assert connection.health is ConnectionHealth.DEGRADED
        assert connection.last_error_category is ConnectorErrorCategory.RATE_LIMITED
        assert connection.last_error_at is not None

    async def test_a_rate_limit_notice_does_not_crash_on_its_missing_event(
        self, slack_app: FastAPI, queue: InMemoryJobQueue, connection: SourceConnection
    ) -> None:
        # It is not an `event_callback`: no nested `event`, no `event_id`. Code
        # assuming `payload["event"]["type"]` 500s here.
        response = await deliver(
            slack_app,
            {"type": "app_rate_limited", "team_id": TEAM, "minute_rate_limited": 1_755_400_000},
        )

        assert response.status_code == 200
        assert await queue.receive(max_messages=5) == []


class TestTeardown:
    @pytest.mark.parametrize(
        ("first", "second"),
        [("app_uninstalled", "tokens_revoked"), ("tokens_revoked", "app_uninstalled")],
    )
    async def test_either_order_stops_ingest_and_the_second_is_a_no_op(
        self,
        slack_app: FastAPI,
        queue: InMemoryJobQueue,
        connection: SourceConnection,
        platform: AsyncSession,
        first: str,
        second: str,
    ) -> None:
        """Slack guarantees no order between the two.

        Whichever arrives first disconnects; the second must not undo it,
        double-stamp it, or fail.
        """
        for name in (first, second):
            response = await deliver(
                slack_app,
                {"type": "event_callback", "team_id": TEAM, "event": {"type": name}},
            )
            assert response.status_code == 200

        await platform.refresh(connection)
        assert not connection.is_active
        stopped_at = connection.revoked_at or connection.disconnected_at
        assert stopped_at is not None

        # And ingest has actually stopped, which is the point of the teardown.
        after = await deliver(slack_app, envelope())
        assert after.status_code == 400
        assert await queue.receive(max_messages=5) == []


# --------------------------------------------------------------------------
# Nothing customer-shaped escapes into telemetry
# --------------------------------------------------------------------------


class TestTelemetryCarriesNoContent:
    async def test_no_message_channel_or_author_reaches_a_span_or_a_log(
        self, slack_app: FastAPI, connection: SourceConnection
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
                accepted = await deliver(slack_app, envelope())
                # A refusal too: rejected paths log more, and are the ones most
                # likely to quote what was wrong with the request.
                await deliver(slack_app, envelope(), secret="wrong")
                await deliver(slack_app, envelope(message_event(channel=UNSELECTED_CHANNEL)))
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
            assert MESSAGE_TEXT not in str(attributes)

        rendered = json.dumps(captured, default=str)
        for forbidden in (MESSAGE_TEXT, USER, SELECTED_CHANNEL, UNSELECTED_CHANNEL, SECRET):
            assert forbidden not in rendered

    async def test_a_rejected_delivery_does_not_log_the_payload(
        self, slack_app: FastAPI, connection: SourceConnection
    ) -> None:
        # The verification-failure log is the one most likely to quote the
        # request, and it is written before any tenant is known — so it has the
        # fewest reasons to be careful and the most need to be.
        with structlog.testing.capture_logs() as captured:
            await deliver(slack_app, envelope(), secret="wrong")

        rendered = json.dumps(captured, default=str)
        assert MESSAGE_TEXT not in rendered
        assert USER not in rendered
