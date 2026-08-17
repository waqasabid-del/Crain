"""The Google Chat subscription lifecycle: one lease per space, kept alive.

A Chat subscription is a four-hour lease that Google **deletes** when it lapses,
and the events published while no subscription existed are gone — there is no
backfill scope, no history call and no second chance. Almost every test here
exists because the natural implementation of one of those facts is subtly wrong
in a way nothing else in the system would notice.

What each group protects:

- **Exactly one lease per selected space.** Re-asserting a selection must not
  accumulate leases: the second one would renew nothing, deliver forever, and be
  invisible.
- **Renewal happens well before expiry**, with a margin computed from the
  maintenance interval rather than chosen by feel — so shortening that loop or
  widening the jitter fails here rather than in a customer's feed.
- **Two workers do not double-renew.** Asserted against real PostgreSQL row
  locks with two real sessions interleaved, not against a mock: an in-process
  lock or an "already renewing" flag passes a mocked test and fails in
  production, which is the only place two workers exist.
- **A failure marks the precise space.** One healthy space and one failed one is
  a *degraded* connection, never a healthy one — a green tick over a permanent
  hole in a customer's record is the claim md/05 forbids.
- **Expired is recreated, never patched.** A ``PATCH`` against a lapsed lease is
  a 404 forever, and a loop that keeps trying is a space that never comes back.
- **Every suspension reason maps to a bounded category**, and reactivation is
  attempted only where it can work.
- **Deleting blocks locally first.** A deselection or a disconnect stops CAIRN
  reading the space even when the call to Google fails — the local record is the
  authority, not the third party.
- **No Google text anywhere.** Not in a column, not in a log line, not on a
  span. Google's messages quote the space and the person.

No test here opens a socket to Google: `FakeEvents` and `FakeTokens` satisfy the
protocols structurally, exactly as the Slack suite's double does.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.config import get_settings
from cairn_api.connectors.credentials import SecretValue, store_secret
from cairn_api.db.base import Base
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.gchat_models import (
    GoogleChatSpaceSelection,
    GoogleChatSubscription,
    GoogleChatSubscriptionState,
)
from cairn_api.db.models import Tenant, User
from cairn_api.gchat import oauth, subscriptions
from cairn_api.gchat.oauth import REQUIRED_SCOPES, GoogleAccessToken
from cairn_api.gchat.subscriptions import (
    EVENT_TYPES,
    MINIMUM_RENEWAL_MARGIN,
    PASS_INTERVAL,
    REACTIVATABLE_REASONS,
    RENEWAL_JITTER,
    RENEWAL_LEAD,
    TTL,
    RemoteSubscription,
    SubscriptionClient,
    SubscriptionError,
    SubscriptionFailure,
)
from cairn_api.jobs.main import MAINTENANCE_INTERVAL_SECONDS
from cairn_api.logging import configure_logging
from cairn_api.ops.connectors import (
    SUSPENSION_REASON_CATEGORY,
    SuspensionReason,
    subscription_health,
)
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.integration]

TOPIC = "projects/cairn-test/topics/gchat-events"
ENGINEERING = "spaces/AAAAENGINEER"
DESIGN = "spaces/AAAADESIGN01"

#: A Google error body of the kind this connector must never repeat. The display
#: name and the address are the whole point of it: both are customer data, both
#: are what Google puts in `error.message`, and neither may reach a column, a log
#: line or a span.
GOOGLE_LEAK = (
    'Permission denied on resource //chat.googleapis.com/spaces/AAAAENGINEER "Acme x '
    'Northwind M&A" for user priya@acme.example'
)


# ---------------------------------------------------------------------------
# The doubles
# ---------------------------------------------------------------------------


class FakeTokens:
    """A `GoogleChatApi` that never opens a socket.

    Structural typing, so this class inherits nothing from the package it stands
    in for — and it counts refreshes, which is how a caching claim could be
    checked without asking the network whether it was called.
    """

    def __init__(self, *, error: oauth.GoogleChatInstallError | None = None) -> None:
        self.error = error
        self.refreshes = 0

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> oauth.GoogleTokenGrant:
        msg = "the subscription engine never exchanges a code"
        raise AssertionError(msg)

    async def refresh_access_token(self, *, refresh_token: SecretValue) -> GoogleAccessToken:
        self.refreshes += 1
        if self.error is not None:
            raise self.error
        return GoogleAccessToken(
            access_token=SecretValue("an-access-token"),
            granted_scopes=frozenset(REQUIRED_SCOPES),
            expires_in=3600,
        )

    async def list_spaces(self, *, access_token: SecretValue) -> tuple[oauth.GoogleChatSpace, ...]:
        return ()


@dataclass
class FakeEvents:
    """A `WorkspaceEventsApi` that records what it was asked to do.

    Every method is scriptable with an error and with a state, because the
    interesting half of this connector is what happens when Google says
    something other than "fine".
    """

    now: datetime = field(default_factory=lambda: datetime.now(UTC))
    create_error: SubscriptionError | None = None
    renew_error: SubscriptionError | None = None
    reactivate_error: SubscriptionError | None = None
    delete_error: SubscriptionError | None = None

    #: What the next create/renew/reactivate reports back.
    state: GoogleChatSubscriptionState = GoogleChatSubscriptionState.ACTIVE
    reason: SuspensionReason | None = None

    #: Reactivation always succeeds into ACTIVE unless this says otherwise.
    reactivated_state: GoogleChatSubscriptionState = GoogleChatSubscriptionState.ACTIVE

    #: ``None`` from a call means "the long-running operation is not finished".
    incomplete: bool = False

    #: Set to pause inside `renew`, which is how the concurrency test proves two
    #: passes overlap rather than merely running one after the other.
    entered: asyncio.Event | None = None
    release: asyncio.Event | None = None

    creates: list[tuple[str, str]] = field(default_factory=list)
    renews: list[str] = field(default_factory=list)
    reactivates: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    issued: int = 0

    def _remote(self, name: str | None = None) -> RemoteSubscription | None:
        if self.incomplete:
            return None
        self.issued += 1
        return RemoteSubscription(
            name=name or f"subscriptions/s{self.issued}",
            expire_time=self.now + TTL,
            state=self.state,
            suspension_reason=(
                self.reason if self.state is GoogleChatSubscriptionState.SUSPENDED else None
            ),
        )

    async def create(
        self, *, access_token: SecretValue, space_name: str, topic: str
    ) -> RemoteSubscription | None:
        self.creates.append((space_name, topic))
        if self.create_error is not None:
            raise self.create_error
        return self._remote()

    async def renew(
        self, *, access_token: SecretValue, subscription_name: str
    ) -> RemoteSubscription | None:
        self.renews.append(subscription_name)
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.renew_error is not None:
            raise self.renew_error
        return self._remote(subscription_name)

    async def reactivate(
        self, *, access_token: SecretValue, subscription_name: str
    ) -> RemoteSubscription | None:
        self.reactivates.append(subscription_name)
        if self.reactivate_error is not None:
            raise self.reactivate_error
        if self.incomplete:
            return None
        return RemoteSubscription(
            name=subscription_name,
            expire_time=self.now + TTL,
            state=self.reactivated_state,
            suspension_reason=(
                self.reason
                if self.reactivated_state is GoogleChatSubscriptionState.SUSPENDED
                else None
            ),
        )

    async def delete(self, *, access_token: SecretValue, subscription_name: str) -> None:
        self.deletes.append(subscription_name)
        if self.delete_error is not None:
            raise self.delete_error


def a_client(events: FakeEvents | None = None, *, topic: str = TOPIC) -> SubscriptionClient:
    return SubscriptionClient(tokens=FakeTokens(), events=events or FakeEvents(), topic=topic)


# ---------------------------------------------------------------------------
# The scenario
# ---------------------------------------------------------------------------


@dataclass
class Workspace:
    """One workspace with Google Chat connected, and nothing selected yet."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    connection: SourceConnection


@pytest.fixture(scope="session", autouse=True)
async def gchat_tables(platform_engine: AsyncEngine) -> None:
    """Create the Google Chat tables if the migration has not landed yet.

    The suite builds its schema from migrations on purpose, and this does not
    change that: ``checkfirst`` means the day the Google Chat migration lands
    this becomes a no-op and the tables under test are the ones production gets.
    Until then the alternative is a lifecycle nobody can run at all, which is how
    a step ships with its tests written against a mock of its own storage.
    """
    tables = [
        Base.metadata.tables[name]
        for name in (
            "google_chat_oauth_states",
            "google_chat_space_selections",
            "google_chat_subscriptions",
        )
    ]
    async with platform_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=tables, checkfirst=True)


@pytest.fixture(autouse=True)
def _forget_tokens() -> None:
    """No test inherits another's cached access token."""
    oauth.clear_access_token_cache()


@pytest.fixture(scope="session", autouse=True)
def _logging_through_the_standard_library() -> None:
    """Route structlog through `logging`, as every deployed process does.

    Without it structlog prints straight to stdout and `caplog` records nothing —
    so the "no space name in a log line" assertions below would pass against an
    empty string, which is the most misleading way for a leak test to be green.
    """
    configure_logging(get_settings())


@pytest.fixture
async def workspace(platform: AsyncSession) -> AsyncIterator[Workspace]:
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name="Acme", slug=f"acme-gchat-{suffix}")
    user = User(email=f"owner-{suffix}@acme.example", display_name="Owner")
    platform.add_all([tenant, user])
    await platform.flush()

    connection = SourceConnection(
        tenant_id=tenant.id,
        provider=ConnectorProvider.GOOGLE_CHAT,
        external_account_id=f"client:{suffix}",
        installation_id=f"client:{suffix}",
        scopes=sorted(REQUIRED_SCOPES),
        state=ConnectionState.CONNECTED,
        health=ConnectionHealth.UNKNOWN,
        connected_at=datetime.now(UTC),
        authorised_by_user_id=user.id,
        authorised_at=datetime.now(UTC),
    )
    store_secret(connection, SecretValue("a-refresh-token"))
    platform.add(connection)
    await platform.commit()

    tenant_id, user_id = tenant.id, user.id
    yield Workspace(tenant_id=tenant_id, user_id=user_id, connection=connection)

    for table in (GoogleChatSubscription, GoogleChatSpaceSelection):
        await platform.execute(delete(table).where(table.tenant_id == tenant_id))
    await platform.execute(delete(SourceConnection).where(SourceConnection.tenant_id == tenant_id))
    await platform.execute(delete(Tenant).where(Tenant.id == tenant_id))
    await platform.execute(delete(User).where(User.id == user_id))
    await platform.commit()


async def select_space(platform: AsyncSession, workspace: Workspace, space_name: str) -> None:
    """Record the customer's selection — the thing that actually permits reading."""
    platform.add(
        GoogleChatSpaceSelection(
            tenant_id=workspace.tenant_id,
            connection_id=workspace.connection.id,
            space_name=space_name,
            selected_by_user_id=workspace.user_id,
        )
    )
    await platform.flush()


async def a_lease(
    platform: AsyncSession,
    workspace: Workspace,
    space_name: str,
    *,
    state: GoogleChatSubscriptionState = GoogleChatSubscriptionState.ACTIVE,
    expires_in: timedelta | None = None,
    name: str | None = "subscriptions/existing",
    category: ConnectorErrorCategory | None = None,
    now: datetime | None = None,
) -> GoogleChatSubscription:
    """A subscription row in a chosen state, committed."""
    moment = now or datetime.now(UTC)
    row = GoogleChatSubscription(
        tenant_id=workspace.tenant_id,
        connection_id=workspace.connection.id,
        space_name=space_name,
        subscription_name=name,
        expire_time=None if expires_in is None else moment + expires_in,
        state=state,
        suspension_category=category,
        state_changed_at=moment,
    )
    platform.add(row)
    await platform.commit()
    return row


async def lease_for(
    session: AsyncSession, workspace: Workspace, space_name: str
) -> GoogleChatSubscription:
    row = await session.scalar(
        select(GoogleChatSubscription).where(
            GoogleChatSubscription.tenant_id == workspace.tenant_id,
            GoogleChatSubscription.space_name == space_name,
        )
    )
    assert row is not None
    return row


def cairn_log(caplog: pytest.LogCaptureFixture) -> str:
    """Everything CAIRN itself logged, fields included, and nothing the harness did.

    ``str(record.msg)`` rather than ``getMessage()``: structlog hands the whole
    event dictionary to the standard library, and the rendered message alone is
    just the event name — so an assertion built on it would never see the field
    where an identifier actually leaks.
    """
    return "\n".join(
        f"{record.msg} {record.args}"
        for record in caplog.records
        if record.name.startswith("cairn_api")
    )


# ---------------------------------------------------------------------------


class TestOneLeasePerSelectedSpace:
    """One space, one subscription. The property the whole table is shaped for."""

    async def test_selecting_a_space_creates_exactly_one_subscription(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        events = FakeEvents()

        await subscriptions.ensure_subscription(
            platform, a_client(events), workspace.connection, space_name=ENGINEERING
        )
        await platform.commit()

        assert events.creates == [(ENGINEERING, TOPIC)]
        row = await lease_for(platform, workspace, ENGINEERING)
        assert row.state is GoogleChatSubscriptionState.ACTIVE
        assert row.subscription_name == "subscriptions/s1"
        assert row.expire_time is not None

    async def test_re_asserting_a_selection_does_not_create_a_second_lease(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The picker submits the whole selected set on every save.

        A create per assertion accumulates leases that renew nothing and deliver
        forever, and nothing on any screen would show it.
        """
        events = FakeEvents()
        client = a_client(events)

        for _ in range(3):
            await subscriptions.ensure_subscription(
                platform, client, workspace.connection, space_name=ENGINEERING
            )
        await platform.commit()

        assert len(events.creates) == 1
        count = await platform.scalar(
            select(func.count())
            .select_from(GoogleChatSubscription)
            .where(GoogleChatSubscription.tenant_id == workspace.tenant_id)
        )
        assert count == 1

    async def test_two_spaces_are_two_leases(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The positive control. Without it, "one row" is also what a helper
        that silently does nothing produces."""
        client = a_client()

        for space in (ENGINEERING, DESIGN):
            await subscriptions.ensure_subscription(
                platform, client, workspace.connection, space_name=space
            )
        await platform.commit()

        count = await platform.scalar(
            select(func.count())
            .select_from(GoogleChatSubscription)
            .where(GoogleChatSubscription.tenant_id == workspace.tenant_id)
        )
        assert count == 2

    async def test_a_second_row_for_one_space_is_refused_by_the_database(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Attacked directly, past the helper.

        Two rows would mean two renewal schedules for one space and, when they
        disagree, a space that stops delivering while a row still says active.
        """
        await a_lease(platform, workspace, ENGINEERING)

        platform.add(
            GoogleChatSubscription(
                tenant_id=workspace.tenant_id,
                connection_id=workspace.connection.id,
                space_name=ENGINEERING,
                state=GoogleChatSubscriptionState.PENDING,
            )
        )
        with pytest.raises(IntegrityError, match="uq_google_chat_subscriptions_connection_space"):
            await platform.commit()
        await platform.rollback()

    async def test_a_display_name_is_refused(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """A lease on a name that is not a resource name delivers nothing, ever."""
        events = FakeEvents()

        with pytest.raises(SubscriptionError) as raised:
            await subscriptions.ensure_subscription(
                platform, a_client(events), workspace.connection, space_name="Engineering"
            )

        assert raised.value.failure is SubscriptionFailure.REQUEST_REJECTED
        assert events.creates == []
        await platform.rollback()

    def test_exactly_the_three_message_event_types(self) -> None:
        """Not two, not four, and not a membership event.

        An extra type is traffic through the ingestion path carrying material
        nobody selected a space for; a missing ``updated`` is a record that
        quotes an edited message as it was first posted.
        """
        assert EVENT_TYPES == (
            "google.workspace.chat.message.v1.created",
            "google.workspace.chat.message.v1.updated",
            "google.workspace.chat.message.v1.deleted",
        )


class TestRenewalHappensLongBeforeExpiry:
    """Arithmetic, no database. A lapse cannot be retried."""

    def test_the_margin_is_positive(self) -> None:
        assert timedelta(0) < MINIMUM_RENEWAL_MARGIN

    def test_the_pass_interval_matches_the_maintenance_loop(self) -> None:
        """Coupled deliberately.

        The margin is computed from how often the loop runs, so halving that
        interval must fail here rather than quietly eating the slack.
        """
        assert PASS_INTERVAL.total_seconds() == MAINTENANCE_INTERVAL_SECONDS

    def test_every_lease_is_due_with_the_full_margin_to_spare(self) -> None:
        """Over many ids, because the offset is derived from the id.

        A jitter that could reach past ``expire_time - lead`` would let a lease
        lapse on a slow pass, and the failure would look like a Google problem.
        """
        expiry = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
        for _ in range(500):
            lease = GoogleChatSubscription(
                id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                connection_id=uuid.uuid4(),
                space_name=ENGINEERING,
                expire_time=expiry,
                state=GoogleChatSubscriptionState.ACTIVE,
            )
            due = subscriptions.renewal_due_at(lease)
            assert due is not None
            assert due >= expiry - RENEWAL_LEAD
            assert due <= expiry - RENEWAL_LEAD + RENEWAL_JITTER
            # The worst case: due immediately after a pass, renewed on the next.
            assert expiry - (due + PASS_INTERVAL) >= MINIMUM_RENEWAL_MARGIN

    def test_a_fresh_lease_is_not_renewed(self) -> None:
        now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
        lease = GoogleChatSubscription(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            space_name=ENGINEERING,
            expire_time=now + TTL,
            state=GoogleChatSubscriptionState.ACTIVE,
        )

        assert subscriptions.is_due(lease, now=now) is False

    def test_a_lease_inside_its_window_is_renewed(self) -> None:
        now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
        lease = GoogleChatSubscription(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            space_name=ENGINEERING,
            # Inside the window even for the largest possible offset.
            expire_time=now + RENEWAL_LEAD - RENEWAL_JITTER,
            state=GoogleChatSubscriptionState.ACTIVE,
        )

        assert subscriptions.is_due(lease, now=now) is True

    def test_the_renewal_pass_leaves_a_fresh_lease_alone(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Placeholder for the database half, asserted below in
        `TestTheRenewalPass.test_a_fresh_lease_is_not_touched`."""


class TestTheRenewalPass:
    """The loop itself, against real rows."""

    async def test_a_due_lease_is_renewed_and_its_expiry_moves(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        events = FakeEvents(now=now)

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        assert outcome.renewed == 1
        assert events.renews == ["subscriptions/existing"]
        row = await lease_for(platform, workspace, ENGINEERING)
        assert row.expire_time is not None
        assert row.expire_time > now + timedelta(hours=3)

    async def test_every_lease_the_pass_touches_is_counted(
        self,
        platform: AsyncSession,
        workspace: Workspace,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The renewal counter is reached from production, per lease.

        `record_subscription_renewal` is the only way to see this loop failing
        *before* a lease lapses, and a lapse costs a customer's record rather
        than a retry. A counter defined, exported and tested but never called
        from the loop it measures is indistinguishable, on a dashboard, from a
        loop that is renewing everything perfectly — which is why this asserts
        the call site exists rather than trusting that it does.

        The outcome is asserted verbatim: it must be a `RenewalAction` value, so
        the attribute stays the closed set the telemetry allow-list assumes and
        no space name can arrive through it.
        """
        recorded: list[dict[str, object]] = []
        monkeypatch.setattr(
            subscriptions,
            "record_subscription_renewal",
            lambda **kwargs: recorded.append(kwargs),
        )
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)

        await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(FakeEvents(now=now)),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )

        assert recorded == [
            {
                "source": ConnectorProvider.GOOGLE_CHAT,
                "outcome": subscriptions.RenewalAction.RENEWED.value,
            }
        ]

    async def test_a_fresh_lease_is_not_touched(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=TTL, now=now)
        events = FakeEvents(now=now)

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )

        assert events.renews == []
        assert outcome.changed == 0

    async def test_the_pass_is_idempotent(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Running it twice renews once.

        The maintenance loop runs on every worker; a pass that renewed whatever
        it found would multiply calls by the number of workers, against an API
        with no published rate limit.
        """
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        events = FakeEvents(now=now)
        client = a_client(events)

        first = await subscriptions.renew_tenant_subscriptions(
            platform, client, tenant_id=workspace.tenant_id, now=now, stagger_seconds=0.0
        )
        await platform.commit()
        second = await subscriptions.renew_tenant_subscriptions(
            platform, client, tenant_id=workspace.tenant_id, now=now, stagger_seconds=0.0
        )
        await platform.commit()

        assert first.renewed == 1
        assert second.changed == 0
        assert len(events.renews) == 1

    async def test_another_workspace_is_not_touched(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Tenant-scoped, asserted rather than assumed."""
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        events = FakeEvents(now=now)

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=uuid.uuid4(),
            now=now,
            stagger_seconds=0.0,
        )

        assert outcome.considered == 0
        assert events.renews == []

    async def test_an_unconfigured_deployment_renews_nothing_quietly(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The maintenance loop runs everywhere, including where Chat is off."""
        outcome = await subscriptions.renew_expiring_subscriptions(platform)

        assert outcome.considered == 0


class TestTwoWorkersDoNotDoubleRenew:
    """Real concurrency: two sessions, two transactions, one lock.

    The mechanism under test is ``FOR UPDATE SKIP LOCKED``, and a mock cannot
    exercise it — an in-process lock, a module-level flag or a check-then-act
    read would all pass a mocked version of this test and fail in production,
    which is the only place two workers exist.
    """

    async def test_the_second_pass_renews_nothing_and_does_not_block(
        self, platform: AsyncSession, platform_engine: AsyncEngine, workspace: Workspace
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)

        events = FakeEvents(now=now, entered=asyncio.Event(), release=asyncio.Event())
        client = a_client(events)
        factory = async_sessionmaker(bind=platform_engine, expire_on_commit=False)

        async def one_pass() -> subscriptions.RenewalPass:
            async with factory() as session:
                outcome = await subscriptions.renew_tenant_subscriptions(
                    session,
                    client,
                    tenant_id=workspace.tenant_id,
                    now=now,
                    stagger_seconds=0.0,
                )
                await session.commit()
                return outcome

        first = asyncio.create_task(one_pass())
        # The first worker is now inside its call to Google, holding the row.
        assert events.entered is not None
        await asyncio.wait_for(events.entered.wait(), timeout=10)

        # The timeout is the assertion: without SKIP LOCKED this waits for the
        # first transaction instead of passing over the row.
        second = await asyncio.wait_for(one_pass(), timeout=10)

        assert events.release is not None
        events.release.set()
        first_outcome = await asyncio.wait_for(first, timeout=10)

        assert first_outcome.renewed == 1
        assert second.considered == 0
        assert second.changed == 0
        assert len(events.renews) == 1


class TestAFailureMarksThePreciseSpace:
    """One broken space is not one broken connection, and not a healthy one."""

    async def test_one_failed_space_leaves_the_connection_degraded(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(
            platform,
            workspace,
            ENGINEERING,
            expires_in=timedelta(minutes=30),
            name="subscriptions/eng",
            now=now,
        )
        await a_lease(
            platform, workspace, DESIGN, expires_in=TTL, name="subscriptions/des", now=now
        )
        events = FakeEvents(
            now=now, renew_error=SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE)
        )

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        assert outcome.failed == 1
        broken = await lease_for(platform, workspace, ENGINEERING)
        healthy = await lease_for(platform, workspace, DESIGN)
        assert broken.state is GoogleChatSubscriptionState.ERROR
        assert broken.suspension_category is ConnectorErrorCategory.PROVIDER_UNAVAILABLE
        assert healthy.state is GoogleChatSubscriptionState.ACTIVE

        await platform.refresh(workspace.connection)
        assert workspace.connection.health is ConnectionHealth.DEGRADED
        assert (
            workspace.connection.last_error_category is ConnectorErrorCategory.PROVIDER_UNAVAILABLE
        )

    async def test_the_failed_space_stops_reading_as_delivering(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        await a_lease(
            platform, workspace, DESIGN, expires_in=TTL, name="subscriptions/des", now=now
        )
        events = FakeEvents(
            now=now, renew_error=SubscriptionError(SubscriptionFailure.RATE_LIMITED)
        )

        await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        assert await subscriptions.is_space_delivering(platform, space_name=ENGINEERING) is False
        assert await subscriptions.is_space_delivering(platform, space_name=DESIGN) is True

    async def test_the_operator_view_does_not_read_as_wholly_healthy(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Two spaces, one broken: the aggregate has to show both.

        A count that collapsed to "connected" is precisely the green tick over a
        gap this product refuses to draw.
        """
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        await a_lease(
            platform, workspace, DESIGN, expires_in=TTL, name="subscriptions/des", now=now
        )
        events = FakeEvents(
            now=now, renew_error=SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE)
        )

        await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        health = subscription_health(
            await subscriptions.subscription_records(platform, tenant_id=workspace.tenant_id),
            expected=2,
        )

        assert health.subscriptions_live == 1
        assert health.subscriptions_missing == 1
        assert health.subscriptions_by_error_category == {
            ConnectorErrorCategory.PROVIDER_UNAVAILABLE.value: 1
        }

    async def test_a_recovery_does_not_invent_a_green_tick(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Health returns to ``UNKNOWN`` when nothing has ever arrived.

        A subscription that exists proves nothing about delivery, and only
        `pubsub.record_healthy_delivery` may say otherwise.
        """
        now = datetime.now(UTC)
        await a_lease(
            platform,
            workspace,
            ENGINEERING,
            state=GoogleChatSubscriptionState.ERROR,
            category=ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
            expires_in=timedelta(minutes=30),
            now=now,
        )
        events = FakeEvents(now=now)

        await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()
        await platform.refresh(workspace.connection)

        assert workspace.connection.health is ConnectionHealth.UNKNOWN
        assert workspace.connection.last_error_category is None


class TestExpiredIsRecreated:
    """A lapsed lease is deleted at Google. Patching it is a 404 forever."""

    async def test_an_expired_lease_is_created_rather_than_patched(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(
            platform,
            workspace,
            ENGINEERING,
            state=GoogleChatSubscriptionState.EXPIRED,
            expires_in=timedelta(hours=-1),
            now=now,
        )
        events = FakeEvents(now=now)

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        assert outcome.recreated == 1
        assert events.renews == []
        assert events.creates == [(ENGINEERING, TOPIC)]
        row = await lease_for(platform, workspace, ENGINEERING)
        assert row.state is GoogleChatSubscriptionState.ACTIVE
        assert row.subscription_name == "subscriptions/s1"

    async def test_a_lease_whose_expiry_has_passed_is_also_recreated(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The case a renewal loop misses: nothing marked it expired.

        The state still reads ``ACTIVE``, no failure was ever recorded, and the
        lease is gone all the same.
        """
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=-5), now=now)
        events = FakeEvents(now=now)

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        assert outcome.recreated == 1
        assert events.renews == []
        assert len(events.creates) == 1

    async def test_a_renewal_that_finds_it_gone_recreates_it(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """A 404 mid-renewal is the lease having lapsed since the last pass."""
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        events = FakeEvents(now=now, renew_error=SubscriptionError(SubscriptionFailure.GONE))

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        assert outcome.recreated == 1
        assert len(events.creates) == 1
        row = await lease_for(platform, workspace, ENGINEERING)
        assert row.state is GoogleChatSubscriptionState.ACTIVE

    def test_expiry_is_documented_as_unrecoverable(self) -> None:
        """The constant the whole path depends on."""
        from cairn_api.ops.connectors import GOOGLE_CHAT_SUBSCRIPTION

        assert GOOGLE_CHAT_SUBSCRIPTION.expired_subscription_is_recoverable is False


class TestSuspension:
    """Nine reasons, three responses, and one category vocabulary."""

    def test_every_reason_maps_to_a_category(self) -> None:
        assert set(SUSPENSION_REASON_CATEGORY) == set(SuspensionReason)

    @pytest.mark.parametrize("reason", list(SuspensionReason))
    async def test_a_suspension_records_its_category_and_never_its_reason(
        self,
        platform: AsyncSession,
        workspace: Workspace,
        caplog: pytest.LogCaptureFixture,
        reason: SuspensionReason,
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        events = FakeEvents(
            now=now,
            state=GoogleChatSubscriptionState.SUSPENDED,
            reason=reason,
            # The reactivation, where it is attempted, finds it still suspended.
            reactivated_state=GoogleChatSubscriptionState.SUSPENDED,
        )

        with caplog.at_level("DEBUG"):
            await subscriptions.renew_tenant_subscriptions(
                platform,
                a_client(events),
                tenant_id=workspace.tenant_id,
                now=now,
                stagger_seconds=0.0,
            )
        await platform.commit()

        row = await lease_for(platform, workspace, ENGINEERING)
        assert row.state is GoogleChatSubscriptionState.SUSPENDED
        assert row.suspension_category is SUSPENSION_REASON_CATEGORY[reason]
        # The reason itself is Google's word for what failed, and it names the
        # resource. It reaches neither the row nor the log.
        assert reason.value not in cairn_log(caplog)
        assert reason.value not in str(row.suspension_category)

    @pytest.mark.parametrize("reason", list(SuspensionReason))
    async def test_reactivation_is_attempted_only_where_it_can_work(
        self,
        platform: AsyncSession,
        workspace: Workspace,
        reason: SuspensionReason,
    ) -> None:
        """A deleted space and a withdrawn scope cannot be reactivated.

        Trying anyway re-suspends within seconds and hides the reason behind a
        churn of state changes, while an endpoint problem an operator has just
        fixed recovers on the next pass with nobody touching CAIRN.
        """
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        events = FakeEvents(
            now=now,
            state=GoogleChatSubscriptionState.SUSPENDED,
            reason=reason,
            reactivated_state=GoogleChatSubscriptionState.SUSPENDED,
        )

        await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        attempted = bool(events.reactivates)
        assert attempted is (reason in REACTIVATABLE_REASONS)

    async def test_a_reactivation_that_works_brings_the_space_back(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        now = datetime.now(UTC)
        await a_lease(
            platform,
            workspace,
            ENGINEERING,
            state=GoogleChatSubscriptionState.SUSPENDED,
            category=ConnectorErrorCategory.CONFIGURATION_INVALID,
            expires_in=timedelta(hours=3),
            now=now,
        )
        events = FakeEvents(now=now)

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform,
            a_client(events),
            tenant_id=workspace.tenant_id,
            now=now,
            stagger_seconds=0.0,
        )
        await platform.commit()

        assert outcome.reactivated == 1
        assert events.reactivates == ["subscriptions/existing"]
        assert events.renews == []
        row = await lease_for(platform, workspace, ENGINEERING)
        assert row.state is GoogleChatSubscriptionState.ACTIVE
        assert row.suspension_category is None


class TestDeletingBlocksLocallyFirst:
    """Consent, and what happens when the third party is unreachable."""

    async def test_unselecting_deletes_the_lease(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        await select_space(platform, workspace, ENGINEERING)
        await a_lease(platform, workspace, ENGINEERING)
        events = FakeEvents()

        outcome = await subscriptions.remove_subscription(
            platform, a_client(events), workspace.connection, space_name=ENGINEERING
        )
        await platform.commit()

        assert outcome.blocked is True
        assert outcome.remote_deleted is True
        assert events.deletes == ["subscriptions/existing"]
        row = await lease_for(platform, workspace, ENGINEERING)
        assert row.state is GoogleChatSubscriptionState.DELETED

    async def test_a_failed_remote_delete_still_blocks_ingestion(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The property this whole ordering exists for.

        Google being unreachable must not keep a withdrawn permission alive. The
        local record is what ingestion reads, and it is written first.
        """
        await select_space(platform, workspace, ENGINEERING)
        await a_lease(platform, workspace, ENGINEERING)
        events = FakeEvents(
            delete_error=SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE)
        )

        outcome = await subscriptions.remove_subscription(
            platform, a_client(events), workspace.connection, space_name=ENGINEERING
        )
        await platform.commit()

        assert outcome.blocked is True
        assert outcome.remote_deleted is False
        assert outcome.error_category is ConnectorErrorCategory.PROVIDER_UNAVAILABLE

        resolved = await subscriptions.resolve_space(platform, space_name=ENGINEERING)
        assert resolved is not None
        assert resolved.active is False

    async def test_disconnecting_deletes_every_space_even_when_google_fails(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The loop does not stop at the first refusal.

        A disconnect that gave up halfway would leave the remaining spaces
        readable for the sake of tidy error handling.
        """
        for space in (ENGINEERING, DESIGN):
            await select_space(platform, workspace, space)
        await a_lease(platform, workspace, ENGINEERING, name="subscriptions/eng")
        await a_lease(platform, workspace, DESIGN, name="subscriptions/des")
        events = FakeEvents(
            delete_error=SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE)
        )

        outcomes = await subscriptions.remove_all_subscriptions(
            platform, a_client(events), workspace.connection
        )
        await oauth.disconnect(workspace.connection)
        await platform.commit()

        assert len(outcomes) == 2
        assert all(item.blocked for item in outcomes)
        assert not any(item.remote_deleted for item in outcomes)
        for space in (ENGINEERING, DESIGN):
            resolved = await subscriptions.resolve_space(platform, space_name=space)
            assert resolved is not None
            assert resolved.active is False

    async def test_a_deleted_lease_is_not_renewed_afterwards(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Deselection is permanent until the customer selects again.

        A renewal pass that revived a deleted lease would be CAIRN re-arming a
        feed somebody switched off.
        """
        now = datetime.now(UTC)
        await a_lease(platform, workspace, ENGINEERING, expires_in=timedelta(minutes=30), now=now)
        events = FakeEvents(now=now)
        client = a_client(events)

        await subscriptions.remove_subscription(
            platform, client, workspace.connection, space_name=ENGINEERING
        )
        await platform.commit()

        outcome = await subscriptions.renew_tenant_subscriptions(
            platform, client, tenant_id=workspace.tenant_id, now=now, stagger_seconds=0.0
        )

        assert outcome.considered == 0
        assert events.renews == []
        assert events.creates == []

    async def test_an_unselected_space_is_refused_outright(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The selection is the permission; a lease is not.

        Without the selection row there is no answer at all — not an inactive
        one — because unknown and never-selected are one decision.
        """
        await a_lease(platform, workspace, ENGINEERING)

        assert await subscriptions.resolve_space(platform, space_name=ENGINEERING) is None

    async def test_a_selected_space_on_a_live_connection_is_readable(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """The positive control for every refusal above."""
        await select_space(platform, workspace, ENGINEERING)
        await a_lease(platform, workspace, ENGINEERING)
        await platform.commit()

        resolved = await subscriptions.resolve_space(platform, space_name=ENGINEERING)

        assert resolved is not None
        assert resolved.active is True
        assert resolved.tenant_id == workspace.tenant_id


class TestNoGoogleTextEscapes:
    """Categories, never messages. Google's words name the space and the person."""

    def test_every_failure_has_a_bounded_category(self) -> None:
        for failure in SubscriptionFailure:
            assert isinstance(subscriptions.category_for(failure), ConnectorErrorCategory)

    def test_a_google_error_body_is_discarded_at_the_boundary(self) -> None:
        """The status code decides; the body is never read."""
        import httpx

        response = httpx.Response(403, json={"error": {"message": GOOGLE_LEAK}})

        with pytest.raises(SubscriptionError) as raised:
            subscriptions._body(response)

        assert raised.value.failure is SubscriptionFailure.PERMISSION_DENIED
        assert "Acme" not in str(raised.value)
        assert "priya" not in str(raised.value)

    def test_an_unknown_suspension_reason_becomes_other(self) -> None:
        """A reason Google adds tomorrow is a category, not a new string."""
        remote = subscriptions._remote_from(
            {
                "name": "subscriptions/s1",
                "state": "SUSPENDED",
                "suspensionReason": "A_REASON_INVENTED_LATER",
            }
        )

        assert remote is not None
        assert remote.suspension_reason is SuspensionReason.OTHER

    async def test_no_space_name_reaches_a_log_line(
        self, platform: AsyncSession, workspace: Workspace, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Across create, renew, failure and delete.

        A space resource name is not itself a display name, but it is the key a
        support session is required to resolve — and once one identifier is in a
        log line the next one is an easy edit.
        """
        now = datetime.now(UTC)
        events = FakeEvents(now=now)
        client = a_client(events)

        with caplog.at_level("DEBUG"):
            await subscriptions.ensure_subscription(
                platform, client, workspace.connection, space_name=ENGINEERING, now=now
            )
            await platform.commit()

            events.renew_error = SubscriptionError(SubscriptionFailure.PERMISSION_DENIED)
            await subscriptions.renew_tenant_subscriptions(
                platform,
                client,
                tenant_id=workspace.tenant_id,
                now=now + TTL - timedelta(minutes=1),
                stagger_seconds=0.0,
            )
            await platform.commit()

            await subscriptions.remove_all_subscriptions(platform, client, workspace.connection)
            await platform.commit()

        recorded = cairn_log(caplog)
        assert ENGINEERING not in recorded
        assert "chat.googleapis.com" not in recorded
        assert "subscriptions/" not in recorded
        # The positive control: something was logged, so the assertions above are
        # not passing over an empty string.
        assert "gchat.subscription" in recorded
