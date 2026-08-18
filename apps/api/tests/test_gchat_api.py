"""The Google Chat product surface, attacked rather than demonstrated.

Every test here drives the **real routers** over ASGI — middleware, dependency
resolution, permission checks, exception handlers and the session cookie — and
each is written so that removing the protection it names makes it fail.
Connecting Google Chat hands CAIRN a standing grant to read a company's
conversations, and the defects that matter are the ones where it still *looks*
connected.

The attacks, in the order the flow meets them:

- A **forged, expired, replayed, borrowed or cross-tenant state** must not
  complete an install. Each is separately reproduced, and each fails.
- A person **demoted between pressing Connect and coming back** must not complete
  one. Minutes pass in an OAuth round trip, and an install that lands on a
  permission that no longer exists is one nobody currently authorised.
- A **Member or Viewer** must not start an install, see the picker, change a
  selection, or disconnect. Configuration is Owner and Admin.
- The picker must **exclude direct messages, app DMs and unnamed spaces**.
- **Selecting must create a subscription and unselecting must tear it down**,
  because a checkbox that does not move a lease is a checkbox that reports
  success and delivers silence — and unselecting must block the space even when
  Google refuses the delete.
- **One workspace's spaces and leases must be unreachable from another.**
- **Disconnecting must destroy the refresh token**, not merely set a flag, and
  must stop ingestion immediately.
- **No token, Google error string or space display name** may appear in a
  response outside the Owner/Admin picker, or in a log line at all.

**No test here reaches Google.** The three dependencies — the OAuth/Chat client,
the space directory and the Workspace Events client — are overridden with doubles
that satisfy the protocols structurally, so nothing about a double can drift into
production code and nothing has to be restored afterwards.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from cairn_api.api.app import create_app
from cairn_api.api.routers.gchat import google_chat_api, space_directory, subscription_client
from cairn_api.config import Settings
from cairn_api.connectors.credentials import REDACTED, SecretValue, read_secret
from cairn_api.db.connector_models import ConnectionState, ConnectorProvider, SourceConnection
from cairn_api.db.gchat_models import (
    GoogleChatOAuthState,
    GoogleChatSpaceSelection,
    GoogleChatSubscription,
    GoogleChatSubscriptionState,
)
from cairn_api.db.models import Membership, TenantRole, User
from cairn_api.db.session import platform_session
from cairn_api.db.tenancy import tenant_session
from cairn_api.gchat import oauth, spaces
from cairn_api.gchat.oauth import (
    REQUIRED_SCOPES,
    GoogleAccessToken,
    GoogleChatInstallError,
    GoogleChatInstallFailure,
    GoogleChatSpace,
    GoogleTokenGrant,
)
from cairn_api.gchat.spaces import AvailableSpace
from cairn_api.gchat.subscriptions import SubscriptionClient, SubscriptionError, SubscriptionFailure
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from test_api_workspaces import Actor, join_as, new_actor
from test_gchat_spaces import APP_DM, DIRECT_MESSAGE, GROUP_CHAT, SENSITIVE, UNNAMED, FakeDirectory
from test_gchat_subscriptions import (  # noqa: F401 — a fixture, re-exported by importing it
    FakeEvents,
    gchat_tables,
)

pytestmark = [pytest.mark.integration]

TEST_ORIGIN = "http://localhost:3000"
APP_URL = "http://localhost:3000"
CALLBACK = "http://localhost:8000/v1/integrations/google-chat/callback"
TOPIC = "projects/cairn-test/topics/gchat-events"

#: Not token-shaped on purpose — see the note in `test_credentials.py`. Shaped
#: enough that "this string is not in the response" asserts about something that
#: could plausibly have leaked.
REFRESH_TOKEN = "stand-in-refresh-credential-9999"  # noqa: S105

#: A Google error body of the kind this connector must never repeat. The display
#: name and the address are the whole point of it: both are customer data, both
#: are what Google puts in `error.message`, and neither may reach a column, a log
#: line or a response.
GOOGLE_LEAK = (
    'Permission denied on resource //chat.googleapis.com/spaces/AAAAENGINEER "Acme x '
    'Northwind M&A" for user priya@acme.example'
)


def a_space() -> str:
    """A space resource name nothing else in the suite can collide with.

    Unique per call, deliberately. ``uq_google_chat_space_selections_space_name``
    is **global** — one Chat space feeds at most one CAIRN workspace — so two
    tests reusing one literal name would fail on each other rather than on the
    property under test, and the failure would look exactly like the isolation
    bug this file exists to catch.
    """
    return f"spaces/{uuid.uuid4().hex[:16]}"


class FakeGoogle:
    """A `GoogleChatApi` that never opens a socket.

    Structural typing, so this class inherits nothing from the package it stands
    in for. It counts its calls, which is how a test proves a request did *not*
    reach Google rather than merely returning the right answer.
    """

    def __init__(
        self,
        *,
        grant: GoogleTokenGrant | None = None,
        error: GoogleChatInstallError | None = None,
        probe_error: GoogleChatInstallError | None = None,
    ) -> None:
        self.grant = grant
        self.error = error
        self.probe_error = probe_error
        self.exchanges = 0
        self.refreshes = 0
        self.listings = 0

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> GoogleTokenGrant:
        self.exchanges += 1
        if self.error is not None:
            raise self.error
        assert self.grant is not None, "the double was built with neither a grant nor an error"
        return self.grant

    async def refresh_access_token(self, *, refresh_token: SecretValue) -> GoogleAccessToken:
        self.refreshes += 1
        if self.error is not None:
            raise self.error
        return GoogleAccessToken(
            access_token=SecretValue("an-access-token"),
            granted_scopes=frozenset(REQUIRED_SCOPES),
            expires_in=3600,
        )

    async def list_spaces(self, *, access_token: SecretValue) -> tuple[GoogleChatSpace, ...]:
        """The connect-time probe only. The picker goes through `SpaceDirectory`."""
        self.listings += 1
        if self.probe_error is not None:
            raise self.probe_error
        return ()


def a_grant(*, scopes: tuple[str, ...] = REQUIRED_SCOPES) -> GoogleTokenGrant:
    return GoogleTokenGrant(
        access_token=SecretValue("an-access-token"),
        refresh_token=SecretValue(REFRESH_TOKEN),
        granted_scopes=frozenset(scopes),
        expires_in=3600,
    )


def a_listing(engineering: str, design: str) -> tuple[AvailableSpace, ...]:
    """What Google would report: two named spaces and four things to exclude."""
    return (
        AvailableSpace(
            name=engineering,
            display_name="Engineering",
            space_type="SPACE",
            single_user_bot_dm=False,
        ),
        DIRECT_MESSAGE,
        GROUP_CHAT,
        APP_DM,
        UNNAMED,
        AvailableSpace(
            name=design, display_name=SENSITIVE, space_type="SPACE", single_user_bot_dm=False
        ),
    )


@pytest_asyncio.fixture
async def gchat_app(engine: AsyncEngine) -> AsyncIterator[FastAPI]:
    """An app with Google Chat configured.

    The shared `app` fixture leaves it unconfigured, which is the correct default
    and makes the install endpoint refuse — so these tests build their own
    instance rather than reaching into another fixture's settings.

    Depends on `engine` purely for ordering: that fixture is what builds the test
    schema by running migrations, and these tests reach the database through the
    application's own session factory rather than through a database fixture.
    """
    oauth.clear_access_token_cache()
    instance = create_app(
        Settings(
            environment="test",
            cors_allowed_origins=(TEST_ORIGIN,),
            public_app_url=APP_URL,
            google_chat_client_id="1234.apps.googleusercontent.com",
            google_chat_client_secret=SecretStr("not-a-real-client-secret"),
            google_chat_redirect_uri=CALLBACK,
            google_chat_project_id="cairn-test",
            google_chat_pubsub_topic=TOPIC,
        )
    )
    async with LifespanManager(instance):
        yield instance
    oauth.clear_access_token_cache()


@dataclass
class Doubles:
    """Everything the Google Chat routes reach the network through."""

    google: FakeGoogle
    directory: FakeDirectory
    events: FakeEvents


def use(
    app: FastAPI,
    *,
    google: FakeGoogle | None = None,
    directory: FakeDirectory | None = None,
    events: FakeEvents | None = None,
    client: bool = True,
) -> Doubles:
    """Serve every route in the file from these doubles.

    Dependency overrides rather than monkeypatched module attributes: nothing to
    restore, and they cannot leak into another test's app because each test
    builds its own.

    ``client=False`` is a deployment with no Pub/Sub topic, which is exactly what
    `subscription_client` returns ``None`` for.
    """
    resolved = Doubles(
        google=google or FakeGoogle(grant=a_grant()),
        directory=directory or FakeDirectory(listing=()),
        events=events or FakeEvents(),
    )
    app.dependency_overrides[google_chat_api] = lambda: resolved.google
    app.dependency_overrides[space_directory] = lambda: resolved.directory
    app.dependency_overrides[subscription_client] = lambda: (
        SubscriptionClient(tokens=resolved.google, events=resolved.events, topic=TOPIC)
        if client
        else None
    )
    return resolved


@dataclass
class Scenario:
    """One connected workspace, and the two spaces its picker offers."""

    owner: Actor
    doubles: Doubles
    engineering: str
    design: str

    @property
    def client(self) -> httpx.AsyncClient:
        return self.owner.client

    @property
    def workspace_id(self) -> str:
        return self.owner.workspace_id

    @property
    def base(self) -> str:
        return base(self.owner)


def base(actor: Actor) -> str:
    return f"/v1/workspaces/{actor.workspace_id}/integrations/google-chat"


async def start_install(actor: Actor) -> str:
    """Press Connect, and return the state Google would hand back."""
    response = await actor.client.post(f"{base(actor)}/install")
    assert response.status_code == 200, response.text
    authorize_url: str = response.json()["authorizeUrl"]
    query = parse_qs(urlparse(authorize_url).query)
    return query["state"][0]


async def finish_install(
    actor: Actor, *, state: str, code: str = "an-install-code"
) -> httpx.Response:
    return await actor.client.get(
        "/v1/integrations/google-chat/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def outcome(response: httpx.Response) -> str:
    """The bounded result the callback redirected with."""
    assert response.status_code == 303, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["googleChat"][0]


async def connected(
    app: FastAPI,
    *,
    label: str = "owner",
    engineering: str | None = None,
    design: str | None = None,
    google: FakeGoogle | None = None,
    events: FakeEvents | None = None,
    client: bool = True,
) -> Scenario:
    """An Owner with Google Chat connected and a picker ready to serve."""
    owner = await new_actor(app, role_label=label)
    first = engineering or a_space()
    second = design or a_space()
    doubles = use(
        app,
        google=google,
        directory=FakeDirectory(listing=a_listing(first, second)),
        events=events,
        client=client,
    )
    assert outcome(await finish_install(owner, state=await start_install(owner))) == "connected"
    doubles.google.exchanges = 0
    doubles.google.listings = 0
    return Scenario(owner=owner, doubles=doubles, engineering=first, design=second)


async def connection_for(workspace_id: str) -> SourceConnection | None:
    """Read the connection out of the database, past every response model.

    Deliberately not through the API. A response model can be correct while the
    row is wrong — a token stored in the clear, a state left connected — and the
    row is what a later request, a worker and an attacker actually see.
    """
    async with platform_session() as db:
        connection: SourceConnection | None = await db.scalar(
            select(SourceConnection).where(
                SourceConnection.tenant_id == uuid.UUID(workspace_id),
                SourceConnection.provider == ConnectorProvider.GOOGLE_CHAT,
            )
        )
        return connection


async def permitted(workspace_id: str, space_name: str) -> bool:
    """Ask the ingestion contract through a **tenant-scoped** session.

    Through the scoped session rather than the platform one, because that is how
    a worker calls it — so row-level security is exercised on the same path
    production uses rather than only on the one a test found convenient.
    """
    async with tenant_session(uuid.UUID(workspace_id)) as db:
        return await spaces.is_space_permitted(
            db, tenant_id=uuid.UUID(workspace_id), space_name=space_name
        )


async def leases(workspace_id: str) -> dict[str, GoogleChatSubscriptionState]:
    async with platform_session() as db:
        rows = await db.scalars(
            select(GoogleChatSubscription).where(
                GoogleChatSubscription.tenant_id == uuid.UUID(workspace_id)
            )
        )
        return {row.space_name: row.state for row in rows.all()}


async def selections(workspace_id: str) -> list[str]:
    async with platform_session() as db:
        rows = await db.scalars(
            select(GoogleChatSpaceSelection.space_name).where(
                GoogleChatSpaceSelection.tenant_id == uuid.UUID(workspace_id)
            )
        )
        return sorted(rows.all())


async def demote(workspace_id: str, email: str, role: TenantRole) -> None:
    """Change somebody's role behind the API's back.

    Directly, because there is no role-change endpoint to go through and the
    property under test is about the *callback*, not about how the demotion
    happened. What matters is that the role changed after the state was issued.
    """
    async with platform_session() as db:
        user_id = await db.scalar(select(User.id).where(User.email == email))
        await db.execute(
            update(Membership)
            .where(
                Membership.tenant_id == uuid.UUID(workspace_id),
                Membership.user_id == user_id,
            )
            .values(role=role)
        )
        await db.commit()


def cairn_log(caplog: pytest.LogCaptureFixture) -> str:
    """Everything CAIRN itself logged, and nothing the test harness did.

    Filtered to our own loggers deliberately. At DEBUG, `httpx` logs the full
    request URL — query string included — so an unfiltered `caplog.text` would
    fail these assertions on the test client's own output rather than on anything
    the application wrote. The property under test is what *CAIRN* records.
    """
    return "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("cairn_api")
    )


class TestConnecting:
    """The happy path, and the thing it must deliberately not have done."""

    async def test_an_owner_can_connect_and_the_connection_is_live(
        self, gchat_app: FastAPI
    ) -> None:
        scenario = await connected(gchat_app, label="connects")

        connection = await connection_for(scenario.workspace_id)
        assert connection is not None
        assert connection.state is ConnectionState.CONNECTED
        assert connection.is_active

    async def test_the_refresh_token_is_stored_encrypted_and_never_returned(
        self, gchat_app: FastAPI, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The credential must exist, be usable, and appear nowhere else."""
        with caplog.at_level(logging.DEBUG):
            scenario = await connected(gchat_app, label="token")
            response = await scenario.client.get(f"{scenario.base}/spaces")

        connection = await connection_for(scenario.workspace_id)
        assert connection is not None
        stored = read_secret(connection)
        assert stored is not None
        assert stored.reveal() == REFRESH_TOKEN
        # The ciphertext, not the token: the column a database dump exposes.
        assert REFRESH_TOKEN not in str(connection._secret_ciphertext)
        assert REDACTED in repr(stored)
        assert REFRESH_TOKEN not in response.text
        assert REFRESH_TOKEN not in cairn_log(caplog)

    async def test_connecting_alone_permits_no_space(self, gchat_app: FastAPI) -> None:
        """The rule the whole feature rests on.

        A connected account with no selection is an account CAIRN reads nothing
        from, and no lease exists for anything.
        """
        scenario = await connected(gchat_app, label="grants-nothing")

        assert await permitted(scenario.workspace_id, scenario.engineering) is False
        assert await leases(scenario.workspace_id) == {}

    async def test_the_authorise_url_carries_pkce_and_offline_consent(
        self, gchat_app: FastAPI
    ) -> None:
        """Dropping any one of these produces a connection that dies in an hour."""
        owner = await new_actor(gchat_app, role_label="pkce")
        use(gchat_app)

        response = await owner.client.post(f"{base(owner)}/install")

        query = parse_qs(urlparse(response.json()["authorizeUrl"]).query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"][0]
        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]

    async def test_the_install_response_states_the_add_the_app_requirement(
        self, gchat_app: FastAPI
    ) -> None:
        """Before the consent screen, not after the feed is found empty."""
        owner = await new_actor(gchat_app, role_label="notice")
        use(gchat_app)

        response = await owner.client.post(f"{base(owner)}/install")

        assert response.json()["notice"] == spaces.APP_ADDED_NOTICE

    async def test_the_install_nonce_is_never_logged(
        self, gchat_app: FastAPI, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A log line carrying it is one an install can be completed from."""
        owner = await new_actor(gchat_app, role_label="quiet")
        use(gchat_app)

        with caplog.at_level(logging.DEBUG):
            state = await start_install(owner)

        assert state not in cairn_log(caplog)


class TestTheCallbackRefusesEverythingItShould:
    """Where a leaked, stale or borrowed state is spent."""

    async def test_a_forged_state_is_refused(self, gchat_app: FastAPI) -> None:
        owner = await new_actor(gchat_app, role_label="forged")
        doubles = use(gchat_app)

        response = await finish_install(owner, state="a-state-nobody-issued")

        assert outcome(response) == "error"
        assert doubles.google.exchanges == 0
        assert await connection_for(owner.workspace_id) is None

    async def test_a_replayed_state_is_refused_the_second_time(self, gchat_app: FastAPI) -> None:
        """Single-use is what separates a retry from a replay."""
        owner = await new_actor(gchat_app, role_label="replay")
        doubles = use(gchat_app)
        state = await start_install(owner)
        assert outcome(await finish_install(owner, state=state)) == "connected"

        response = await finish_install(owner, state=state)

        assert outcome(response) == "error"
        assert doubles.google.exchanges == 1

    async def test_an_expired_state_is_refused(self, gchat_app: FastAPI) -> None:
        owner = await new_actor(gchat_app, role_label="expired")
        doubles = use(gchat_app)
        state = await start_install(owner)
        async with platform_session() as db:
            await db.execute(
                update(GoogleChatOAuthState)
                .where(GoogleChatOAuthState.tenant_id == uuid.UUID(owner.workspace_id))
                .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await db.commit()

        response = await finish_install(owner, state=state)

        assert outcome(response) == "error"
        assert doubles.google.exchanges == 0

    async def test_another_persons_state_is_refused(self, gchat_app: FastAPI) -> None:
        """Being a member of the same workspace is not enough.

        A state leaked through a shared screen or a proxy log must not be
        redeemable by whoever picked it up — including a colleague who is
        themselves an Admin.
        """
        owner = await new_actor(gchat_app, role_label="issuer")
        admin = await join_as(gchat_app, owner, "admin")
        doubles = use(gchat_app)
        state = await start_install(owner)

        response = await finish_install(admin, state=state)

        assert outcome(response) == "error"
        assert doubles.google.exchanges == 0
        assert await connection_for(owner.workspace_id) is None

    async def test_a_state_from_another_workspace_is_refused(self, gchat_app: FastAPI) -> None:
        """A stranger's state must not bind their Google account to us.

        The state carries the tenant, so redeeming somebody else's is the exact
        shape of "connect my Chat to your workspace". The user check is what
        stops it, because the two people are different.
        """
        acme = await new_actor(gchat_app, role_label="acme-state")
        northwind = await new_actor(gchat_app, role_label="northwind-state")
        doubles = use(gchat_app)
        state = await start_install(acme)

        response = await finish_install(northwind, state=state)

        assert outcome(response) == "error"
        assert doubles.google.exchanges == 0
        assert await connection_for(acme.workspace_id) is None
        assert await connection_for(northwind.workspace_id) is None

    async def test_a_person_demoted_mid_install_cannot_finish_it(self, gchat_app: FastAPI) -> None:
        """Minutes pass inside an OAuth round trip.

        An install that completes on a permission that no longer exists is one
        nobody currently authorised — so the callback re-checks membership *and*
        the permission rather than trusting the state's own word for it.
        """
        owner = await new_actor(gchat_app, role_label="demoted")
        admin = await join_as(gchat_app, owner, "admin")
        doubles = use(gchat_app)
        state = await start_install(admin)

        await demote(owner.workspace_id, admin.email, TenantRole.VIEWER)

        response = await finish_install(admin, state=state)

        assert outcome(response) == "error"
        assert doubles.google.exchanges == 0
        assert await connection_for(owner.workspace_id) is None

    async def test_a_declined_consent_screen_reports_denied(self, gchat_app: FastAPI) -> None:
        """ "You said no" and "something broke" are different sentences."""
        owner = await new_actor(gchat_app, role_label="declined")
        doubles = use(gchat_app)
        await start_install(owner)

        response = await owner.client.get(
            "/v1/integrations/google-chat/callback",
            params={"error": "access_denied"},
            follow_redirects=False,
        )

        assert outcome(response) == "denied"
        assert doubles.google.exchanges == 0

    async def test_an_admin_policy_refusal_also_reports_denied(self, gchat_app: FastAPI) -> None:
        """The person who can fix it is a different person, and the copy says so."""
        owner = await new_actor(gchat_app, role_label="policy")
        use(gchat_app)
        await start_install(owner)

        response = await owner.client.get(
            "/v1/integrations/google-chat/callback",
            params={"error": "admin_policy_enforced"},
            follow_redirects=False,
        )

        assert outcome(response) == "denied"

    async def test_a_provider_failure_leaves_nothing_half_written(
        self, gchat_app: FastAPI, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A connection that reads as connected with no usable token is worse than none."""
        owner = await new_actor(gchat_app, role_label="halfway")
        use(
            gchat_app,
            google=FakeGoogle(
                error=GoogleChatInstallError(
                    GoogleChatInstallFailure.PROVIDER_UNAVAILABLE, GOOGLE_LEAK
                )
            ),
        )

        with caplog.at_level(logging.DEBUG):
            response = await finish_install(owner, state=await start_install(owner))

        assert outcome(response) == "error"
        assert await connection_for(owner.workspace_id) is None
        assert GOOGLE_LEAK not in response.headers["location"]
        assert GOOGLE_LEAK not in cairn_log(caplog)

    async def test_a_personal_google_account_is_refused_before_anything_is_stored(
        self, gchat_app: FastAPI
    ) -> None:
        """The probe exists so the symptom is not an empty picker forever.

        A personal Gmail account completes the whole OAuth flow and is then
        refused by every Chat call. Without the probe the customer gets a
        connection that reports success and explains nothing.
        """
        owner = await new_actor(gchat_app, role_label="personal")
        use(
            gchat_app,
            google=FakeGoogle(
                grant=a_grant(),
                probe_error=GoogleChatInstallError(GoogleChatInstallFailure.ACCESS_FORBIDDEN),
            ),
        )

        response = await finish_install(owner, state=await start_install(owner))

        assert outcome(response) == "error"
        assert await connection_for(owner.workspace_id) is None

    async def test_the_redirect_never_carries_a_google_word(self, gchat_app: FastAPI) -> None:
        """Three outcomes and nothing else.

        The URL bar is also browser history and any referrer that follows, so
        every value in this query string is one we chose.
        """
        owner = await new_actor(gchat_app, role_label="bounded")
        use(gchat_app)

        response = await owner.client.get(
            "/v1/integrations/google-chat/callback",
            params={"error": "some_google_string_we_do_not_enumerate"},
            follow_redirects=False,
        )

        location = response.headers["location"]
        assert location.startswith(f"{APP_URL}/admin?")
        assert "some_google_string" not in location
        assert outcome(response) in {"connected", "denied", "error"}


class TestOnlyOwnersAndAdminsMayConfigureIt:
    """Connecting an integration is configuration, and configuration is Owner and Admin."""

    async def test_a_member_cannot_start_an_install(self, gchat_app: FastAPI) -> None:
        owner = await new_actor(gchat_app, role_label="member-install")
        member = await join_as(gchat_app, owner, "member")
        use(gchat_app)

        response = await member.client.post(f"{base(owner)}/install")

        assert response.status_code == 403

    async def test_a_viewer_cannot_start_an_install(self, gchat_app: FastAPI) -> None:
        owner = await new_actor(gchat_app, role_label="viewer-install")
        viewer = await join_as(gchat_app, owner, "viewer")
        use(gchat_app)

        response = await viewer.client.post(f"{base(owner)}/install")

        assert response.status_code == 403

    async def test_a_member_cannot_see_the_picker(self, gchat_app: FastAPI) -> None:
        """The one endpoint returning display names is the one that may change them."""
        scenario = await connected(gchat_app, label="member-picker")
        member = await join_as(gchat_app, scenario.owner, "member")

        response = await member.client.get(f"{scenario.base}/spaces")

        assert response.status_code == 403
        assert SENSITIVE not in response.text

    async def test_a_member_cannot_change_the_selection(self, gchat_app: FastAPI) -> None:
        scenario = await connected(gchat_app, label="member-save")
        member = await join_as(gchat_app, scenario.owner, "member")

        response = await member.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        assert response.status_code == 403
        assert scenario.doubles.events.creates == []
        assert await permitted(scenario.workspace_id, scenario.engineering) is False

    async def test_a_viewer_cannot_change_the_selection(self, gchat_app: FastAPI) -> None:
        scenario = await connected(gchat_app, label="viewer-save")
        viewer = await join_as(gchat_app, scenario.owner, "viewer")

        response = await viewer.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        assert response.status_code == 403

    async def test_a_member_cannot_disconnect(self, gchat_app: FastAPI) -> None:
        scenario = await connected(gchat_app, label="member-disconnect")
        member = await join_as(gchat_app, scenario.owner, "member")

        response = await member.client.post(f"{scenario.base}/disconnect")

        assert response.status_code == 403
        connection = await connection_for(scenario.workspace_id)
        assert connection is not None
        assert connection.is_active

    async def test_an_admin_can_do_all_three(self, gchat_app: FastAPI) -> None:
        """The positive control. Without it every refusal above could be a broken route."""
        scenario = await connected(gchat_app, label="admin-can")
        admin = await join_as(gchat_app, scenario.owner, "admin")

        assert (await admin.client.get(f"{scenario.base}/spaces")).status_code == 200
        saved = await admin.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )
        assert saved.status_code == 200, saved.text
        assert (await admin.client.post(f"{scenario.base}/disconnect")).status_code == 200


class TestThePicker:
    """What a customer is shown, and what they are deliberately not shown."""

    async def test_only_eligible_named_spaces_are_listed(self, gchat_app: FastAPI) -> None:
        scenario = await connected(gchat_app, label="picker")

        response = await scenario.client.get(f"{scenario.base}/spaces")

        assert response.status_code == 200, response.text
        listed = {space["name"] for space in response.json()["spaces"]}
        assert listed == {scenario.engineering, scenario.design}

    async def test_direct_messages_and_app_dms_never_reach_the_response_body(
        self, gchat_app: FastAPI
    ) -> None:
        """Asserted on the whole body, not only on the parsed list.

        A field added later that carried the raw listing would pass a test that
        only inspected `spaces`.
        """
        scenario = await connected(gchat_app, label="no-dms")

        response = await scenario.client.get(f"{scenario.base}/spaces")

        for excluded in (DIRECT_MESSAGE, GROUP_CHAT, APP_DM, UNNAMED):
            assert excluded.name not in response.text

    async def test_the_picker_reports_selection_and_lease_state(self, gchat_app: FastAPI) -> None:
        """ "Selected" and "delivering" are different facts.

        A screen that conflates them tells a customer their feed is fine while it
        has a hole in it.
        """
        scenario = await connected(gchat_app, label="lease-state")
        saved = await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )
        assert saved.status_code == 200, saved.text

        response = await scenario.client.get(f"{scenario.base}/spaces")

        by_name = {space["name"]: space for space in response.json()["spaces"]}
        assert by_name[scenario.engineering]["selected"] is True
        assert by_name[scenario.engineering]["subscriptionState"] == "active"
        assert by_name[scenario.engineering]["expireTime"] is not None
        assert by_name[scenario.engineering]["errorCategory"] is None
        # Unselected: no lease at all, which stays distinguishable from "pending".
        assert by_name[scenario.design]["selected"] is False
        assert by_name[scenario.design]["subscriptionState"] is None

    async def test_the_picker_carries_the_add_the_app_notice(self, gchat_app: FastAPI) -> None:
        scenario = await connected(gchat_app, label="picker-notice")

        response = await scenario.client.get(f"{scenario.base}/spaces")

        assert response.json()["notice"] == spaces.APP_ADDED_NOTICE

    async def test_a_display_name_is_never_logged(
        self, gchat_app: FastAPI, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The picker may render it. Nothing may record it."""
        scenario = await connected(gchat_app, label="no-name-log")

        with caplog.at_level(logging.DEBUG):
            await scenario.client.get(f"{scenario.base}/spaces")
            await scenario.client.put(
                f"{scenario.base}/spaces", json={"spaceNames": [scenario.design]}
            )

        assert SENSITIVE not in cairn_log(caplog)

    async def test_an_unconnected_workspace_gets_a_404_not_an_empty_picker(
        self, gchat_app: FastAPI
    ) -> None:
        """An empty list would imply the organisation has no spaces."""
        owner = await new_actor(gchat_app, role_label="unconnected")
        use(gchat_app)

        response = await owner.client.get(f"{base(owner)}/spaces")

        assert response.status_code == 404

    async def test_a_google_failure_becomes_a_bounded_category(self, gchat_app: FastAPI) -> None:
        """Never Google's words, and never a 500."""
        scenario = await connected(gchat_app, label="picker-fails")
        scenario.doubles.google.error = GoogleChatInstallError(
            GoogleChatInstallFailure.RATE_LIMITED, GOOGLE_LEAK
        )
        oauth.clear_access_token_cache()

        response = await scenario.client.get(f"{scenario.base}/spaces")

        assert response.status_code == 502
        assert response.json()["category"] == "rate_limited"
        assert GOOGLE_LEAK not in response.text


class TestSavingASelectionMovesTheSubscriptions:
    """The vertical slice. A checkbox that moves no lease delivers silence."""

    async def test_selecting_creates_a_subscription_and_permits_the_space(
        self, gchat_app: FastAPI
    ) -> None:
        scenario = await connected(gchat_app, label="save-creates")

        response = await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        assert response.status_code == 200, response.text
        assert response.json()["spaceNames"] == [scenario.engineering]
        assert [space for space, _ in scenario.doubles.events.creates] == [scenario.engineering]
        assert await leases(scenario.workspace_id) == {
            scenario.engineering: GoogleChatSubscriptionState.ACTIVE
        }
        assert await permitted(scenario.workspace_id, scenario.engineering) is True

    async def test_the_subscription_is_pointed_at_this_deployments_topic(
        self, gchat_app: FastAPI
    ) -> None:
        """A lease pointed nowhere reads as connected and produces nothing."""
        scenario = await connected(gchat_app, label="save-topic")

        await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        assert scenario.doubles.events.creates == [(scenario.engineering, TOPIC)]

    async def test_unselecting_tears_the_subscription_down_and_blocks_the_space(
        self, gchat_app: FastAPI
    ) -> None:
        scenario = await connected(gchat_app, label="save-removes")
        await scenario.client.put(
            f"{scenario.base}/spaces",
            json={"spaceNames": [scenario.engineering, scenario.design]},
        )

        response = await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.design]}
        )

        assert response.status_code == 200, response.text
        assert response.json()["spaceNames"] == [scenario.design]
        assert len(scenario.doubles.events.deletes) == 1
        assert await permitted(scenario.workspace_id, scenario.engineering) is False
        assert await permitted(scenario.workspace_id, scenario.design) is True

    async def test_unselecting_blocks_even_when_google_refuses_the_delete(
        self, gchat_app: FastAPI
    ) -> None:
        """The failure this product cannot have.

        A withdrawn permission that keeps taking data because a third party was
        unreachable is the opposite of the promise, not a smaller version of it.
        """
        scenario = await connected(gchat_app, label="delete-fails")
        await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )
        scenario.doubles.events.delete_error = SubscriptionError(
            SubscriptionFailure.PROVIDER_UNAVAILABLE
        )

        response = await scenario.client.put(f"{scenario.base}/spaces", json={"spaceNames": []})

        assert response.status_code == 200, response.text
        assert await permitted(scenario.workspace_id, scenario.engineering) is False
        assert await selections(scenario.workspace_id) == []

    async def test_an_empty_selection_is_valid_and_means_read_nothing(
        self, gchat_app: FastAPI
    ) -> None:
        scenario = await connected(gchat_app, label="empty-save")

        response = await scenario.client.put(f"{scenario.base}/spaces", json={"spaceNames": []})

        assert response.status_code == 200, response.text
        assert response.json()["spaceNames"] == []

    async def test_the_body_is_the_full_state_not_a_delta(self, gchat_app: FastAPI) -> None:
        """A merge would make unchecking a box do nothing."""
        scenario = await connected(gchat_app, label="full-state")
        await scenario.client.put(
            f"{scenario.base}/spaces",
            json={"spaceNames": [scenario.engineering, scenario.design]},
        )

        await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        assert await selections(scenario.workspace_id) == [scenario.engineering]

    async def test_a_display_name_in_the_body_is_refused_with_422(self, gchat_app: FastAPI) -> None:
        scenario = await connected(gchat_app, label="name-refused")

        response = await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [SENSITIVE]}
        )

        assert response.status_code == 422
        assert SENSITIVE not in response.text
        assert scenario.doubles.events.creates == []

    async def test_a_failed_subscription_keeps_the_selection_and_reports_the_category(
        self, gchat_app: FastAPI
    ) -> None:
        """A throttled space must not discard the customer's decision.

        The row carries the category, which is what the picker renders — a space
        that failed to subscribe with a reason on it is worth more than a space
        with no row at all.
        """
        scenario = await connected(
            gchat_app,
            label="subscribe-fails",
            events=FakeEvents(create_error=SubscriptionError(SubscriptionFailure.RATE_LIMITED)),
        )

        response = await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        assert response.status_code == 200, response.text
        listed = await scenario.client.get(f"{scenario.base}/spaces")
        row = next(
            space for space in listed.json()["spaces"] if space["name"] == scenario.engineering
        )
        assert row["selected"] is True
        assert row["subscriptionState"] == "error"
        assert row["errorCategory"] == "rate_limited"

    async def test_saving_on_a_deployment_with_no_topic_still_records_the_decision(
        self, gchat_app: FastAPI
    ) -> None:
        """A missing topic must not stop somebody granting or withdrawing consent."""
        scenario = await connected(gchat_app, label="no-topic", client=False)

        response = await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        assert response.status_code == 200, response.text
        assert await permitted(scenario.workspace_id, scenario.engineering) is True


class TestIsolation:
    """One workspace's spaces and leases never reach another's."""

    async def test_a_stranger_cannot_read_another_workspaces_picker(
        self, gchat_app: FastAPI
    ) -> None:
        """404, not 403 — a 403 would confirm the workspace exists."""
        acme = await connected(gchat_app, label="acme-picker")
        northwind = await new_actor(gchat_app, role_label="northwind-picker")

        response = await northwind.client.get(f"{acme.base}/spaces")

        assert response.status_code == 404
        assert SENSITIVE not in response.text

    async def test_a_stranger_cannot_select_spaces_in_another_workspace(
        self, gchat_app: FastAPI
    ) -> None:
        acme = await connected(gchat_app, label="acme-save")
        northwind = await new_actor(gchat_app, role_label="northwind-save")

        response = await northwind.client.put(
            f"{acme.base}/spaces", json={"spaceNames": [acme.engineering]}
        )

        assert response.status_code == 404
        assert acme.doubles.events.creates == []
        assert await permitted(acme.workspace_id, acme.engineering) is False

    async def test_a_stranger_cannot_disconnect_another_workspace(self, gchat_app: FastAPI) -> None:
        acme = await connected(gchat_app, label="acme-disconnect")
        northwind = await new_actor(gchat_app, role_label="northwind-disconnect")

        response = await northwind.client.post(f"{acme.base}/disconnect")

        assert response.status_code == 404
        connection = await connection_for(acme.workspace_id)
        assert connection is not None
        assert connection.is_active

    async def test_one_workspaces_selection_never_permits_another(self, gchat_app: FastAPI) -> None:
        """Asserted against a second real workspace with real rows in it."""
        acme = await connected(gchat_app, label="acme-permits")
        await acme.client.put(f"{acme.base}/spaces", json={"spaceNames": [acme.engineering]})
        northwind = await connected(gchat_app, label="northwind-permits")

        assert await permitted(acme.workspace_id, acme.engineering) is True
        assert await permitted(northwind.workspace_id, acme.engineering) is False

    async def test_one_workspaces_leases_are_invisible_to_another(self, gchat_app: FastAPI) -> None:
        acme = await connected(gchat_app, label="acme-leases")
        await acme.client.put(f"{acme.base}/spaces", json={"spaceNames": [acme.engineering]})
        northwind = await connected(gchat_app, label="northwind-leases")

        assert await leases(northwind.workspace_id) == {}
        assert await selections(northwind.workspace_id) == []

    async def test_a_space_another_workspace_already_reads_cannot_be_claimed(
        self, gchat_app: FastAPI
    ) -> None:
        """One space feeds at most one CAIRN workspace.

        Enforced by a **global** unique constraint on the resource name, because
        that is the one identifier here that genuinely is globally unique. The
        endpoint refuses with a 409 rather than letting an `IntegrityError` reach
        an Owner as a 500 — and the refusal names no space, because telling one
        organisation which of its spaces another CAIRN customer reads is a
        disclosure across the boundary this product cannot leak across.
        """
        contested = a_space()
        acme = await connected(gchat_app, label="acme-claim", engineering=contested)
        await acme.client.put(f"{acme.base}/spaces", json={"spaceNames": [contested]})
        northwind = await connected(gchat_app, label="northwind-claim", engineering=contested)

        response = await northwind.client.put(
            f"{northwind.base}/spaces", json={"spaceNames": [contested]}
        )

        assert response.status_code == 409, response.text
        assert contested not in response.text
        assert await permitted(northwind.workspace_id, contested) is False
        assert await permitted(acme.workspace_id, contested) is True


class TestDisconnecting:
    """Stop collecting, tear the leases down, and drop the credential."""

    async def test_disconnecting_destroys_the_refresh_token(self, gchat_app: FastAPI) -> None:
        """Not a flag. A standing grant kept after somebody said stop is the opposite."""
        scenario = await connected(gchat_app, label="disconnect-token")

        response = await scenario.client.post(f"{scenario.base}/disconnect")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["credentialCleared"] is True
        assert body["state"] == "disconnected"
        connection = await connection_for(scenario.workspace_id)
        assert connection is not None
        assert read_secret(connection) is None
        assert REFRESH_TOKEN not in str(connection._secret_ciphertext)

    async def test_disconnecting_blocks_every_selected_space_immediately(
        self, gchat_app: FastAPI
    ) -> None:
        scenario = await connected(gchat_app, label="disconnect-blocks")
        await scenario.client.put(
            f"{scenario.base}/spaces",
            json={"spaceNames": [scenario.engineering, scenario.design]},
        )
        assert await permitted(scenario.workspace_id, scenario.engineering) is True

        await scenario.client.post(f"{scenario.base}/disconnect")

        assert await permitted(scenario.workspace_id, scenario.engineering) is False
        assert await permitted(scenario.workspace_id, scenario.design) is False

    async def test_disconnecting_tears_every_lease_down(self, gchat_app: FastAPI) -> None:
        scenario = await connected(gchat_app, label="disconnect-leases")
        await scenario.client.put(
            f"{scenario.base}/spaces",
            json={"spaceNames": [scenario.engineering, scenario.design]},
        )

        await scenario.client.post(f"{scenario.base}/disconnect")

        assert len(scenario.doubles.events.deletes) == 2
        assert set((await leases(scenario.workspace_id)).values()) == {
            GoogleChatSubscriptionState.DELETED
        }

    async def test_the_selection_survives_so_reconnecting_restores_it(
        self, gchat_app: FastAPI
    ) -> None:
        """Kept deliberately, which is exactly why the connection is checked too."""
        scenario = await connected(gchat_app, label="disconnect-keeps")
        await scenario.client.put(
            f"{scenario.base}/spaces", json={"spaceNames": [scenario.engineering]}
        )

        await scenario.client.post(f"{scenario.base}/disconnect")

        assert await selections(scenario.workspace_id) == [scenario.engineering]

    async def test_the_response_states_what_disconnecting_does_not_do(
        self, gchat_app: FastAPI
    ) -> None:
        """The honest sentence is the less flattering one."""
        scenario = await connected(gchat_app, label="disconnect-notice")

        response = await scenario.client.post(f"{scenario.base}/disconnect")

        notice = response.json()["retentionNotice"]
        assert "not deleted" in notice
        assert "reconnecting restores it" in notice

    async def test_disconnecting_twice_is_a_404_not_a_second_disconnect(
        self, gchat_app: FastAPI
    ) -> None:
        scenario = await connected(gchat_app, label="disconnect-twice")
        assert (await scenario.client.post(f"{scenario.base}/disconnect")).status_code == 200

        response = await scenario.client.post(f"{scenario.base}/disconnect")

        assert response.status_code == 404


class TestThePushReceiverIsNotAProductSurface:
    """The Pub/Sub endpoint is unauthenticated by necessity and must stay invisible."""

    async def test_the_client_contract_offers_exactly_the_five_product_routes(
        self, gchat_app: FastAPI
    ) -> None:
        """The generated client must not learn the receiver exists.

        It is verified by a Google-signed token rather than a session, so a
        client that offered it would be offering an endpoint no customer can
        legitimately call and an attacker would enjoy finding. Pinned as an exact
        set, because a route added here without a decision is a route a browser
        gets to call.
        """
        schema = gchat_app.openapi()

        google_chat_paths = sorted(path for path in schema["paths"] if "google-chat" in path)
        assert google_chat_paths == [
            "/v1/integrations/google-chat/callback",
            "/v1/workspaces/{workspace_id}/integrations/google-chat/disconnect",
            "/v1/workspaces/{workspace_id}/integrations/google-chat/install",
            "/v1/workspaces/{workspace_id}/integrations/google-chat/spaces",
        ]
        methods = schema["paths"]["/v1/workspaces/{workspace_id}/integrations/google-chat/spaces"]
        assert sorted(methods) == ["get", "put"]
