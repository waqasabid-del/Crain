"""The Slack install flow, attacked rather than demonstrated.

Every test here is written so that removing the protection it names makes it
fail. That is the difference between a suite that proves the happy path works and
one that proves the flow is safe: connecting Slack hands CAIRN a standing grant
to read a company's conversations, and the defects that matter are the ones where
it still *looks* connected.

The attacks, in the order the flow meets them:

- A **forged, expired, replayed or borrowed state** must not complete an install.
  Each is separately reproduced, and each fails.
- A **Member or Viewer** must not be able to start one. Connecting an integration
  is configuration, and configuration is Owner and Admin.
- A **denial** and a **provider failure** must be categorised into the bounded
  `ConnectorErrorCategory` set, with no Slack string reaching the response.
- A **scope shortfall** must fail closed. Slack can grant less than was asked for
  without failing, and the result is a connection that reports success and
  delivers nothing.
- A **token** must not appear in a response, a log, or a repr.
- **Disconnecting** must destroy the credential, not merely set a flag.

**No test here reaches slack.com.** The network lives behind `SlackApi`, and the
double below satisfies it structurally — it imports no base class from the
package, so nothing about the double can drift into production code. A test that
called the real API would be slow, flaky and, on a scope-shortfall case,
impossible to write at all.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from cairn_api.api.app import create_app
from cairn_api.api.routers.slack import slack_api
from cairn_api.config import Settings
from cairn_api.connectors.credentials import REDACTED, SecretValue, read_secret
from cairn_api.db.connector_models import (
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.session import platform_session
from cairn_api.db.slack_models import SlackOAuthState
from cairn_api.slack import channels as channel_selection
from cairn_api.slack import oauth
from cairn_api.slack.oauth import (
    REQUIRED_BOT_SCOPES,
    SlackChannel,
    SlackInstallError,
    SlackInstallFailure,
    SlackTokenGrant,
)
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine
from test_api_workspaces import Actor, join_as, new_actor

pytestmark = [pytest.mark.integration]

TEST_ORIGIN = "http://localhost:3000"
CALLBACK = "http://localhost:8000/v1/integrations/slack/callback"

#: A token shaped like a real one, so a test asserting "this string is not in the
#: response" is asserting about something that could plausibly have leaked.
# Not token-shaped on purpose — see the note in `test_credentials.py`.
BOT_TOKEN = "stand-in-bot-credential-8888"  # noqa: S105


class FakeSlack:
    """A `SlackApi` that never opens a socket.

    Structural typing, so this class inherits nothing from the package it stands
    in for. It also records its calls, which is how the caching test proves a
    second request did not reach Slack rather than merely returning the right
    answer twice.
    """

    def __init__(
        self,
        *,
        grant: SlackTokenGrant | None = None,
        error: SlackInstallError | None = None,
        channels: tuple[SlackChannel, ...] = (),
    ) -> None:
        self.grant = grant
        self.error = error
        self.channels = channels
        self.exchanges = 0
        self.listings = 0

    async def exchange_code(self, *, code: str, redirect_uri: str) -> SlackTokenGrant:
        self.exchanges += 1
        if self.error is not None:
            raise self.error
        assert self.grant is not None, "the double was built with neither a grant nor an error"
        return self.grant

    async def list_public_channels(self, *, token: SecretValue) -> tuple[SlackChannel, ...]:
        self.listings += 1
        if self.error is not None:
            raise self.error
        return self.channels


def a_grant(
    *,
    scopes: tuple[str, ...] = REQUIRED_BOT_SCOPES,
    team_id: str = "T0FAKE0001",
    token: str = BOT_TOKEN,
) -> SlackTokenGrant:
    return SlackTokenGrant(
        bot_token=SecretValue(token),
        team_id=team_id,
        team_label="Acme Slack",
        granted_scopes=frozenset(scopes),
        app_id="A0FAKE0001",
    )


@pytest_asyncio.fixture
async def slack_app(engine: AsyncEngine) -> AsyncIterator[FastAPI]:
    """An app with Slack configured.

    The shared `app` fixture leaves Slack unconfigured, which is the correct
    default and makes the install endpoint refuse — so these tests build their
    own instance rather than reaching into another fixture's settings.

    Depends on `engine` purely for ordering. That fixture is what builds the test
    schema by running migrations, and these tests reach the database through the
    application's own session factory rather than through a database fixture — so
    without this the file passes only when some other module happened to run
    first, and fails with "relation does not exist" when run alone.
    """
    channel_selection.clear_channel_cache()
    instance = create_app(
        Settings(
            environment="test",
            cors_allowed_origins=(TEST_ORIGIN,),
            slack_client_id="A0FAKE0001.1234",
            slack_client_secret=SecretStr("not-a-real-client-secret"),
            slack_redirect_uri=CALLBACK,
        )
    )
    async with LifespanManager(instance):
        yield instance
    channel_selection.clear_channel_cache()


def use(app: FastAPI, api: FakeSlack) -> FakeSlack:
    """Serve every route in the file from this double.

    A dependency override rather than a monkeypatched module attribute: nothing
    to restore, and it cannot leak into another test's app because each test
    builds its own.
    """
    app.dependency_overrides[slack_api] = lambda: api
    return api


async def start_install(actor: Actor) -> str:
    """Press Connect, and return the state Slack would hand back."""
    response = await actor.client.post(
        f"/v1/workspaces/{actor.workspace_id}/integrations/slack/install"
    )
    assert response.status_code == 200, response.text
    authorize_url: str = response.json()["authorizeUrl"]
    query = parse_qs(urlparse(authorize_url).query)
    return query["state"][0]


async def finish_install(
    actor: Actor, *, state: str, code: str = "an-install-code"
) -> httpx.Response:
    return await actor.client.get(
        "/v1/integrations/slack/callback",
        params={"code": code, "state": state},
        follow_redirects=False,
    )


def cairn_log(caplog: pytest.LogCaptureFixture) -> str:
    """Everything CAIRN itself logged, and nothing the test harness did.

    Filtered to our own loggers deliberately. At DEBUG, `httpx` logs the full
    request URL — query string included — so an unfiltered `caplog.text` would
    fail these assertions on the test client's own output rather than on
    anything the application wrote. The property under test is what *CAIRN*
    records, which is what ends up in a log store with its own retention.
    """
    return "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("cairn_api")
    )


def outcome(response: httpx.Response) -> dict[str, str]:
    """The bounded result the callback redirected with."""
    assert response.status_code == 303, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    return {key: value[0] for key, value in query.items()}


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
                SourceConnection.provider == ConnectorProvider.SLACK,
            )
        )
        return connection


class TestTheScopesAsked:
    """What CAIRN requests of a customer's Slack, pinned.

    Not a style test. Every scope here is a standing capability over a company's
    conversations, and the way an over-broad one arrives is as a character added
    to a string during a debugging session.
    """

    def test_exactly_three_scopes_and_they_are_the_documented_ones(self) -> None:
        assert set(REQUIRED_BOT_SCOPES) == {
            # Receive public-channel message events.
            "channels:history",
            # List public channels, so the picker exists.
            "channels:read",
            # Resolve an author id to a person, which is all of attribution.
            "users:read",
        }

    def test_no_forbidden_scope_is_requested(self) -> None:
        """Writing, private channels, DMs, joining, files and search.

        Each would be defensible in isolation and each changes what this product
        is. `chat:write` in particular turns a coordination tool into something
        that speaks in a channel, which is a tool people manage their appearance
        in front of.
        """
        for scope in REQUIRED_BOT_SCOPES:
            for forbidden in oauth.FORBIDDEN_SCOPE_PREFIXES:
                assert not scope.startswith(forbidden), f"{scope} is forbidden"

    async def test_the_authorise_url_asks_for_those_and_no_user_scope(
        self, slack_app: FastAPI
    ) -> None:
        """`user_scope` must be absent, not empty.

        An empty `user_scope` is harmless and is one character away from
        requesting permissions in a *person's* name rather than the app's.
        """
        owner = await new_actor(slack_app, role_label="scopes-owner")
        response = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/integrations/slack/install"
        )

        query = parse_qs(urlparse(response.json()["authorizeUrl"]).query)
        assert query["scope"][0].split(",") == list(REQUIRED_BOT_SCOPES)
        assert "user_scope" not in query
        assert response.json()["requestedScopes"] == list(REQUIRED_BOT_SCOPES)


class TestWhoMayConnect:
    async def test_a_member_is_refused(self, slack_app: FastAPI) -> None:
        owner = await new_actor(slack_app, role_label="member-owner")
        member = await join_as(slack_app, owner, "member")

        # Positive control: without it this passes against an endpoint that is
        # simply broken for everybody.
        assert (
            await owner.client.post(
                f"/v1/workspaces/{owner.workspace_id}/integrations/slack/install"
            )
        ).status_code == 200

        response = await member.client.post(
            f"/v1/workspaces/{member.workspace_id}/integrations/slack/install"
        )
        assert response.status_code == 403

    async def test_a_viewer_is_refused(self, slack_app: FastAPI) -> None:
        owner = await new_actor(slack_app, role_label="viewer-owner")
        viewer = await join_as(slack_app, owner, "viewer")

        response = await viewer.client.post(
            f"/v1/workspaces/{viewer.workspace_id}/integrations/slack/install"
        )
        assert response.status_code == 403

    async def test_a_member_cannot_disconnect(self, slack_app: FastAPI) -> None:
        owner = await new_actor(slack_app, role_label="disc-owner")
        member = await join_as(slack_app, owner, "member")

        response = await member.client.post(
            f"/v1/workspaces/{member.workspace_id}/integrations/slack/disconnect"
        )
        assert response.status_code == 403


class TestTheStateParameter:
    """The CSRF boundary. Four attacks, four refusals."""

    async def test_a_forged_state_is_refused(self, slack_app: FastAPI) -> None:
        """The attack this whole mechanism exists for.

        Without a server-side state, an attacker hands a victim a callback URL
        carrying the attacker's own install code. The victim's workspace ends up
        bound to the attacker's Slack, and from then on the attacker's channels
        feed the victim's briefs.
        """
        owner = await new_actor(slack_app, role_label="forged")
        api = use(slack_app, FakeSlack(grant=a_grant()))

        response = await finish_install(owner, state="a-state-nobody-issued")

        assert outcome(response)["reason"] == SlackInstallFailure.STATE_REJECTED.value
        assert api.exchanges == 0, "the code was exchanged despite an invalid state"
        assert await connection_for(owner.workspace_id) is None

    async def test_an_expired_state_is_refused(self, slack_app: FastAPI) -> None:
        """Aged in the database rather than by sleeping.

        Sleeping for the real TTL would make the suite ten minutes slower and
        would test the clock. Rewriting `expires_at` tests the predicate.
        """
        owner = await new_actor(slack_app, role_label="expired")
        api = use(slack_app, FakeSlack(grant=a_grant()))
        state = await start_install(owner)

        async with platform_session() as db:
            # Scoped to this workspace. A blanket UPDATE would expire states
            # another test in the same session is still holding, and the failure
            # would surface in that test rather than in this one.
            await db.execute(
                update(SlackOAuthState)
                .where(SlackOAuthState.tenant_id == uuid.UUID(owner.workspace_id))
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()

        response = await finish_install(owner, state=state)

        assert outcome(response)["reason"] == SlackInstallFailure.STATE_REJECTED.value
        assert api.exchanges == 0
        assert await connection_for(owner.workspace_id) is None

    async def test_a_replayed_state_is_refused_the_second_time(self, slack_app: FastAPI) -> None:
        """Single-use, and the first use having succeeded is not a defence.

        A callback URL sits in browser history, in a referrer, and in any proxy
        log between the customer and us. Replaying it must not re-run an install.
        """
        owner = await new_actor(slack_app, role_label="replay")
        api = use(slack_app, FakeSlack(grant=a_grant(team_id="T0REPLAY01")))
        state = await start_install(owner)

        first = await finish_install(owner, state=state)
        assert outcome(first) == {"slack": "connected"}

        second = await finish_install(owner, state=state)

        assert outcome(second)["reason"] == SlackInstallFailure.STATE_REJECTED.value
        assert api.exchanges == 1, "the replayed callback reached Slack"

    async def test_a_failed_exchange_still_consumes_the_state(self, slack_app: FastAPI) -> None:
        """Consumed before the exchange, not after.

        Otherwise "retry the callback until it works" is available, and it is
        indistinguishable from an attacker replaying one.
        """
        owner = await new_actor(slack_app, role_label="consume-first")
        use(
            slack_app,
            FakeSlack(
                error=SlackInstallError(
                    SlackInstallFailure.EXCHANGE_REJECTED, "Slack refused to complete the install."
                )
            ),
        )
        state = await start_install(owner)

        assert outcome(await finish_install(owner, state=state))["reason"] == (
            SlackInstallFailure.EXCHANGE_REJECTED.value
        )
        assert outcome(await finish_install(owner, state=state))["reason"] == (
            SlackInstallFailure.STATE_REJECTED.value
        )

    async def test_another_persons_state_is_refused(self, slack_app: FastAPI) -> None:
        """Being an Owner of the same workspace is not enough.

        The person who finishes an install must be the person who started it. A
        state that leaked through a shared screen, a chat message or a proxy log
        must be worthless to whoever picked it up — including a colleague who
        would have been allowed to start their own.
        """
        owner = await new_actor(slack_app, role_label="state-owner")
        colleague = await join_as(slack_app, owner, "admin")
        api = use(slack_app, FakeSlack(grant=a_grant(team_id="T0BORROW01")))

        state = await start_install(owner)
        response = await finish_install(colleague, state=state)

        assert outcome(response)["reason"] == SlackInstallFailure.STATE_REJECTED.value
        assert api.exchanges == 0
        assert await connection_for(owner.workspace_id) is None

    async def test_a_state_from_another_workspace_is_refused(self, slack_app: FastAPI) -> None:
        """A stranger's state, presented by a stranger.

        The user check does the work here, and the point of asserting it
        separately is that it must not depend on the two workspaces being
        distinguishable at the callback — which they are not, because the
        callback URL carries no workspace.
        """
        alice = await new_actor(slack_app, role_label="alice-slack")
        mallory = await new_actor(slack_app, role_label="mallory-slack")
        api = use(slack_app, FakeSlack(grant=a_grant(team_id="T0CROSS001")))

        state = await start_install(alice)
        response = await finish_install(mallory, state=state)

        assert outcome(response)["reason"] == SlackInstallFailure.STATE_REJECTED.value
        assert api.exchanges == 0
        assert await connection_for(alice.workspace_id) is None
        assert await connection_for(mallory.workspace_id) is None

    async def test_the_state_is_stored_hashed_and_never_in_the_clear(
        self, slack_app: FastAPI
    ) -> None:
        """A database dump must not let a reader finish somebody's install."""
        owner = await new_actor(slack_app, role_label="hashed")
        state = await start_install(owner)

        async with platform_session() as db:
            rows = list(await db.scalars(select(SlackOAuthState.state_hash)))

        assert rows, "no state row was written"
        assert state not in rows
        assert all(len(row) == 64 for row in rows), "not a SHA-256 hex digest"

    async def test_a_state_is_not_guessable(self, slack_app: FastAPI) -> None:
        """Two installs must not produce related values.

        Blunt on purpose. The precise property — a CSPRNG — is not observable
        from here; what is observable is that the values differ and are long, and
        a sequential or timestamp-derived state fails both.
        """
        owner = await new_actor(slack_app, role_label="entropy")
        first = await start_install(owner)
        second = await start_install(owner)

        assert first != second
        assert len(first) >= 32


class TestDenialAndProviderFailure:
    """Every failure is categorised, and none of them quotes Slack."""

    @pytest.mark.parametrize(
        "slack_error",
        [
            # The value Slack's docs use.
            "access_denied",
            # A value they do not document. Denial is under-documented, so the
            # callback branches on the *presence* of `error` rather than on this
            # string — and this case is what proves it.
            "user_cancelled_the_thing",
        ],
    )
    async def test_a_denial_is_categorised_without_branching_on_the_word(
        self, slack_app: FastAPI, slack_error: str
    ) -> None:
        owner = await new_actor(slack_app, role_label=f"denied-{slack_error[:6]}")
        api = use(slack_app, FakeSlack(grant=a_grant()))
        state = await start_install(owner)

        response = await owner.client.get(
            "/v1/integrations/slack/callback",
            params={"error": slack_error, "state": state},
            follow_redirects=False,
        )

        result = outcome(response)
        assert result["reason"] == SlackInstallFailure.DECLINED.value
        assert result["category"] == ConnectorErrorCategory.PERMISSION_REVOKED.value
        assert api.exchanges == 0
        assert await connection_for(owner.workspace_id) is None

    async def test_no_slack_error_string_reaches_the_redirect(self, slack_app: FastAPI) -> None:
        """Slack's words never reach the URL bar.

        Which matters more here than in a response body: a query string is in
        browser history and in every referrer that follows it.
        """
        owner = await new_actor(slack_app, role_label="no-echo")
        use(slack_app, FakeSlack(grant=a_grant()))
        state = await start_install(owner)
        secret_looking_error = "team_not_found_for_acme_layoffs"  # noqa: S105

        response = await owner.client.get(
            "/v1/integrations/slack/callback",
            params={"error": secret_looking_error, "state": state},
            follow_redirects=False,
        )

        assert secret_looking_error not in response.headers["location"]

    @pytest.mark.parametrize(
        ("failure", "category"),
        [
            (
                SlackInstallFailure.PROVIDER_UNAVAILABLE,
                ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
            ),
            (SlackInstallFailure.RATE_LIMITED, ConnectorErrorCategory.RATE_LIMITED),
            (
                SlackInstallFailure.EXCHANGE_REJECTED,
                ConnectorErrorCategory.CONFIGURATION_INVALID,
            ),
        ],
    )
    async def test_a_provider_failure_maps_to_a_bounded_category(
        self,
        slack_app: FastAPI,
        failure: SlackInstallFailure,
        category: ConnectorErrorCategory,
    ) -> None:
        """Three causes that look identical from a screen showing "not connected"
        and have completely different responses: wait, wait longer, or fix the
        configuration."""
        owner = await new_actor(slack_app, role_label=f"fail-{failure.value[:6]}")
        use(slack_app, FakeSlack(error=SlackInstallError(failure, "A sentence we wrote.")))
        state = await start_install(owner)

        result = outcome(await finish_install(owner, state=state))

        assert result["reason"] == failure.value
        assert result["category"] == category.value
        assert await connection_for(owner.workspace_id) is None

    def test_every_failure_has_a_category(self) -> None:
        """Derived from the enum, so a new failure cannot be added without one.

        A failure with no category reaches a customer as "error" and reaches an
        operator as a support ticket that starts with "it says error".
        """
        for failure in SlackInstallFailure:
            assert isinstance(oauth.category_for(failure), ConnectorErrorCategory)


class TestScopesAreVerifiedOnTheWayIn:
    """Slack may grant less than was asked for, and say nothing about it."""

    @pytest.mark.parametrize(
        "granted",
        [
            # The worst case: everything except the one that delivers events.
            ("channels:read", "users:read"),
            # No attribution — every fact would be by "someone".
            ("channels:history", "channels:read"),
            (),
        ],
    )
    async def test_a_shortfall_fails_closed(
        self, slack_app: FastAPI, granted: tuple[str, ...]
    ) -> None:
        """No connection, no stored token, and a category an admin can act on.

        The tempting alternative is to connect anyway and record the shortfall —
        which produces a workspace that reads "connected" with an empty feed, the
        exact failure md/05 §4 calls worse than an honest one.
        """
        owner = await new_actor(slack_app, role_label=f"scope-{len(granted)}")
        use(slack_app, FakeSlack(grant=a_grant(scopes=granted, team_id="T0SCOPE001")))
        state = await start_install(owner)

        result = outcome(await finish_install(owner, state=state))

        assert result["reason"] == SlackInstallFailure.SCOPES_INSUFFICIENT.value
        assert result["category"] == ConnectorErrorCategory.PERMISSION_REVOKED.value
        assert await connection_for(owner.workspace_id) is None

    def test_the_check_is_a_set_difference_not_a_substring(self) -> None:
        """`"channels:read" in scope_string` is also true for
        `channels:read_only`, which is a check satisfiable by a scope Slack does
        not have."""
        with pytest.raises(SlackInstallError):
            oauth.verify_granted_scopes(
                a_grant(scopes=("channels:history_x", "channels:read_only", "users:read_all"))
            )

    def test_extra_granted_scopes_do_not_block_the_install(self) -> None:
        """Slack sometimes grants a superset. Requiring equality would refuse a
        perfectly good install for having too much, which is a refusal nobody can
        act on."""
        oauth.verify_granted_scopes(a_grant(scopes=(*REQUIRED_BOT_SCOPES, "team:read")))


class TestTheTokenNeverEscapes:
    async def test_a_successful_install_returns_no_token(self, slack_app: FastAPI) -> None:
        owner = await new_actor(slack_app, role_label="tok-response")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0TOKEN001")))
        state = await start_install(owner)

        response = await finish_install(owner, state=state)

        assert BOT_TOKEN not in response.text
        assert BOT_TOKEN not in response.headers["location"]

    async def test_the_stored_token_is_encrypted_and_recoverable_only_by_name(
        self, slack_app: FastAPI
    ) -> None:
        """The positive control for every "not in the response" assertion above.

        Without it, they would all pass against an install that stored no token
        at all — which is exactly what a broken exchange looks like from outside.
        """
        owner = await new_actor(slack_app, role_label="tok-stored")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0TOKEN002")))
        state = await start_install(owner)
        await finish_install(owner, state=state)

        connection = await connection_for(owner.workspace_id)
        assert connection is not None
        secret = read_secret(connection)
        assert secret is not None
        assert secret.reveal() == BOT_TOKEN
        # The ciphertext is not the plaintext with extra steps.
        assert BOT_TOKEN not in str(connection._secret_ciphertext)

    def test_a_grant_does_not_render_its_token(self) -> None:
        """The dataclass `repr` is what a traceback and a structlog rendering
        both reach for, so it is where a token leaks without anyone deciding
        to."""
        grant = a_grant()

        assert BOT_TOKEN not in repr(grant)
        assert BOT_TOKEN not in str(grant)
        assert REDACTED in repr(grant)

    async def test_no_log_line_carries_the_token_the_state_or_the_team_name(
        self, slack_app: FastAPI, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Every log record emitted during a whole install, inspected.

        Captured from the standard-library handler that `configure_logging`
        routes structlog into, rather than from a recording logger. A recording
        logger proves the one call site passed the right fields; this proves that
        nothing else in the stack — a middleware, an exception renderer, a
        SQLAlchemy echo — rendered an object that contained the token.

        `structlog.testing.capture_logs` would be the obvious tool and is the
        wrong one here: `cache_logger_on_first_use=True` means loggers bound by
        an earlier test are never re-resolved, so it captures nothing and the
        test passes vacuously depending on execution order.

        The state and the team name are asserted alongside the token. A log line
        carrying the nonce is one somebody can finish an install from; a log line
        carrying the team name is customer data in a store with its own retention
        and its own readers.
        """
        owner = await new_actor(slack_app, role_label="tok-log")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0TOKEN003")))

        with caplog.at_level(logging.DEBUG):
            state = await start_install(owner)
            await finish_install(owner, state=state)

        written = cairn_log(caplog)
        assert written, "CAIRN logged nothing — the assertions below would be vacuous"
        assert BOT_TOKEN not in written
        assert state not in written
        assert "Acme Slack" not in written

    async def test_the_install_is_logged_at_all(
        self, slack_app: FastAPI, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The positive control for the test above.

        Without it, "the token is not in the log" would also pass against a flow
        that logs nothing — and a connector that records no evidence of being
        connected is its own problem.
        """
        owner = await new_actor(slack_app, role_label="tok-log-2")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0TOKEN004")))

        with caplog.at_level(logging.DEBUG):
            await finish_install(owner, state=await start_install(owner))

        written = cairn_log(caplog)
        assert "slack.connected" in written
        # The scopes are ours, not the customer's, and they are what makes "why
        # is nothing arriving" answerable.
        assert "channels:history" in written


class TestTheConnectionThatResults:
    async def test_a_successful_install_records_consent_and_claims_no_health(
        self, slack_app: FastAPI
    ) -> None:
        """`health` stays UNKNOWN.

        Nothing has arrived yet. A connection that reports health it never
        measured is a green tick over a feed that may never start, which is the
        precise failure `ConnectionHealth.UNKNOWN` exists to prevent.
        """
        owner = await new_actor(slack_app, role_label="recorded")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0RECORD01")))
        state = await start_install(owner)
        await finish_install(owner, state=state)

        connection = await connection_for(owner.workspace_id)
        assert connection is not None
        assert connection.state is ConnectionState.CONNECTED
        assert connection.health.value == "unknown"
        assert connection.scopes == sorted(REQUIRED_BOT_SCOPES)
        assert connection.authorised_by_user_id is not None
        assert connection.authorised_at is not None

    async def test_one_slack_workspace_cannot_be_claimed_by_two_customers(
        self, slack_app: FastAPI
    ) -> None:
        """Two CAIRN workspaces sharing one Slack team would each receive the
        other's activity, and the one that arrived second would start the leak
        silently."""
        alice = await new_actor(slack_app, role_label="claim-a")
        mallory = await new_actor(slack_app, role_label="claim-b")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0SHARED01")))

        assert outcome(await finish_install(alice, state=await start_install(alice))) == {
            "slack": "connected"
        }
        result = outcome(await finish_install(mallory, state=await start_install(mallory)))

        assert result["reason"] == SlackInstallFailure.ALREADY_CONNECTED.value
        assert await connection_for(mallory.workspace_id) is None

    async def test_installing_starts_no_historical_collection(self, slack_app: FastAPI) -> None:
        """The `connect_github` rule, and it matters more here.

        Slack would happily return years of messages from every channel. Nothing
        is permitted until a channel is selected, so a freshly connected
        workspace has an empty selection and a cursor that has not moved.
        """
        owner = await new_actor(slack_app, role_label="no-backfill")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0NOBACK01")))
        await finish_install(owner, state=await start_install(owner))

        connection = await connection_for(owner.workspace_id)
        assert connection is not None
        assert connection.sync_cursor is None
        assert connection.last_successful_sync_at is None
        async with platform_session() as db:
            assert (
                await channel_selection.selected_channel_ids(db, connection_id=connection.id)
                == frozenset()
            )


class TestDisconnecting:
    async def test_it_destroys_the_credential_rather_than_flagging_the_row(
        self, slack_app: FastAPI
    ) -> None:
        """The assertion this endpoint exists for.

        A disconnect that keeps the token keeps a live grant to read a customer's
        conversations after they asked CAIRN to stop — and from outside there is
        no way to tell the two apart.
        """
        owner = await new_actor(slack_app, role_label="disc-clears")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0DISC0001")))
        await finish_install(owner, state=await start_install(owner))

        before = await connection_for(owner.workspace_id)
        assert before is not None and read_secret(before) is not None

        response = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/integrations/slack/disconnect"
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["credentialCleared"] is True
        after = await connection_for(owner.workspace_id)
        assert after is not None
        assert after.state is ConnectionState.DISCONNECTED
        assert after.disconnected_at is not None
        assert read_secret(after) is None
        assert after._secret_ciphertext is None

    async def test_it_is_truthful_about_what_it_does_not_delete(self, slack_app: FastAPI) -> None:
        """The less flattering half of the sentence is the load-bearing half.

        A product whose deletion claims are approximate is one whose deletion
        claims are worthless, so the response says plainly that disconnecting
        stops collection and does not erase what was recorded.
        """
        owner = await new_actor(slack_app, role_label="disc-truth")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0DISC0002")))
        await finish_install(owner, state=await start_install(owner))

        body = (
            await owner.client.post(
                f"/v1/workspaces/{owner.workspace_id}/integrations/slack/disconnect"
            )
        ).json()

        assert "not deleted" in body["retentionNotice"]

    async def test_a_disconnected_workspace_blocks_every_further_call(
        self, slack_app: FastAPI
    ) -> None:
        """Not merely "no new events". The configuration endpoints refuse too,
        so nothing can quietly re-enable collection without a fresh
        authorisation."""
        owner = await new_actor(slack_app, role_label="disc-blocks")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0DISC0003"), channels=()))
        await finish_install(owner, state=await start_install(owner))
        await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/integrations/slack/disconnect"
        )

        base = f"/v1/workspaces/{owner.workspace_id}/integrations/slack"
        assert (await owner.client.get(f"{base}/channels")).status_code == 404
        assert (
            await owner.client.put(f"{base}/channels", json={"channelIds": []})
        ).status_code == 404
        assert (await owner.client.post(f"{base}/disconnect")).status_code == 404

    async def test_reconnecting_revives_the_same_row(self, slack_app: FastAPI) -> None:
        """A disconnect is our side stopping, so reconnecting is a click.

        Retained rather than deleted precisely so this is a revival with its
        history intact — and so the channel selection the customer built is still
        there.
        """
        owner = await new_actor(slack_app, role_label="disc-revive")
        use(slack_app, FakeSlack(grant=a_grant(team_id="T0REVIVE01")))
        await finish_install(owner, state=await start_install(owner))
        original = await connection_for(owner.workspace_id)
        assert original is not None

        await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/integrations/slack/disconnect"
        )
        await finish_install(owner, state=await start_install(owner))

        revived = await connection_for(owner.workspace_id)
        assert revived is not None
        assert revived.id == original.id
        assert revived.state is ConnectionState.CONNECTED
        assert revived.disconnected_at is None
        assert read_secret(revived) is not None


class TestSlackIsNotConfigured:
    async def test_the_install_endpoint_refuses_rather_than_sending_a_broken_link(
        self, app: FastAPI
    ) -> None:
        """The shared `app` fixture has no Slack credentials.

        An operator problem, and it must not present to a customer as "Slack said
        no" — which is what sending them to an authorise URL Slack rejects would
        do.
        """
        owner = await new_actor(app, role_label="unconfigured")

        response = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/integrations/slack/install"
        )

        assert response.status_code == 503
        assert response.json()["category"] == ConnectorErrorCategory.CONFIGURATION_INVALID.value

    async def test_no_state_row_is_written_when_it_refuses(self, app: FastAPI) -> None:
        """Issuing a nonce for an install that cannot start leaves a live state
        behind for nothing."""
        owner = await new_actor(app, role_label="unconfigured-2")

        async with platform_session() as db:
            before = len(list(await db.scalars(select(SlackOAuthState.id))))
        await owner.client.post(f"/v1/workspaces/{owner.workspace_id}/integrations/slack/install")
        async with platform_session() as db:
            after = len(list(await db.scalars(select(SlackOAuthState.id))))

        assert before == after
