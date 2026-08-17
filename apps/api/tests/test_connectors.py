"""The connector foundation.

Three things are being proved here, and only the first is about new code.

**The record is honest.** ``is_active`` and ``is_collecting`` are computed, so a
connection cannot report live consent from a column nobody updated — the same
rule ``SupportSession.is_active`` exists for.

**The isolation is real.** Row-level security against actual PostgreSQL, written
as attacks in the style of ``test_tenant_isolation``: one workspace tries to see
another's connections, and a scoped session tries to create one.

**GitHub actually uses it.** A framework with no production caller is a
framework nobody has tested, and this repository has been bitten by exactly that
before — see ``test_audit_regressions.TestInstallationsCanBeCreated``, where
three build steps were unreachable end to end because only fixtures created the
row they needed. The last class below writes a ``GitHubInstallation`` through the
same platform connection production uses and asserts a ``SourceConnection``
exists as a result. If the projection is removed, that class fails.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.github_models import GitHubInstallation
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import set_tenant_context
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


def _connection(
    tenant_id: uuid.UUID, installation_id: str, **overrides: object
) -> SourceConnection:
    values: dict[str, object] = {
        "tenant_id": tenant_id,
        "provider": ConnectorProvider.GITHUB,
        "external_account_id": "acme",
        "external_account_label": "Acme",
        "installation_id": installation_id,
        "scopes": ["contents:read"],
        "state": ConnectionState.CONNECTED,
        "health": ConnectionHealth.HEALTHY,
        "connected_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SourceConnection(**values)


class TestTheRecordIsHonest:
    """No database. State that is derived must not be storable."""

    def test_a_connected_connection_is_active(self) -> None:
        assert _connection(uuid.uuid4(), "1").is_active

    def test_a_pending_connection_is_not_active(self) -> None:
        # Authorised in our UI, not yet confirmed by the provider. Showing it
        # as connected is how a customer waits for data that was never coming.
        assert not _connection(uuid.uuid4(), "1", state=ConnectionState.PENDING).is_active

    @pytest.mark.parametrize("field", ["disconnected_at", "revoked_at"])
    def test_a_timestamped_ending_beats_a_stale_state(self, field: str) -> None:
        """The property this whole design turns on.

        A row can carry ``state = 'connected'`` and a ``revoked_at`` in the
        past, because the job that reconciles the two has not run. A stored
        boolean would say the connection is live. This does not.
        """
        connection = _connection(
            uuid.uuid4(), "1", **{field: datetime.now(UTC) - timedelta(days=1)}
        )

        assert not connection.is_active

    def test_a_failing_connection_is_active_but_not_collecting(self) -> None:
        # Authorised and broken. The distinction the UI needs: "reconnect" is
        # the wrong instruction for a connection whose permission is fine.
        connection = _connection(uuid.uuid4(), "1", health=ConnectionHealth.FAILING)

        assert connection.is_active
        assert not connection.is_collecting

    def test_a_disconnected_connection_is_not_collecting_either(self) -> None:
        connection = _connection(uuid.uuid4(), "1", state=ConnectionState.DISCONNECTED)

        assert not connection.is_collecting

    def test_health_starts_unknown_rather_than_healthy(self) -> None:
        # A connection that has never synced has not proved anything, and a
        # green tick it did not earn is the claim md/05 forbids.
        assert SourceConnection.__table__.c.health.default.arg is ConnectionHealth.UNKNOWN

    def test_the_error_category_is_a_closed_set(self) -> None:
        # Never a provider message: those quote the failed request, which for a
        # chat connector means channel names and message fragments in a column
        # both staff and the customer read.
        assert ConnectorErrorCategory.UNKNOWN.value == "unknown"
        assert len(set(ConnectorErrorCategory)) == 6


@pytest.mark.integration
@pytest.mark.isolation
class TestDatabaseBoundaries:
    """Real PostgreSQL. RLS does not exist in SQLite, so nothing else proves this."""

    async def test_a_scoped_session_sees_only_its_own_connections(
        self, session: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        acme, globex = two_workspaces
        await set_tenant_context(session, acme.id)

        visible = (await session.scalars(select(SourceConnection.tenant_id))).all()

        assert list(visible) == [acme.id]
        assert globex.id not in visible

    async def test_an_unscoped_session_sees_nothing(
        self, session: AsyncSession, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        """Zero rows, not every row.

        A raw query, a forgotten filter or a library opening its own session all
        arrive here. The positive control first, because "sees no rows" is also
        what a fixture that wrote nothing looks like.
        """
        acme, globex = two_workspaces
        assert (
            await platform.scalar(
                select(func.count())
                .select_from(SourceConnection)
                .where(SourceConnection.tenant_id.in_([acme.id, globex.id]))
            )
            == 2
        )

        assert await session.scalar(select(func.count()).select_from(SourceConnection)) == 0

    async def test_the_same_installation_cannot_be_bound_to_two_workspaces(
        self, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        """The uniqueness rule, attacked directly.

        Two workspaces claiming one installation would each receive the other's
        activity — a cross-tenant leak with no bug anywhere in the application,
        just two rows. The constraint is global rather than per-tenant for
        exactly this reason.
        """
        acme, globex = two_workspaces
        contested = f"contested-{uuid.uuid4().hex[:8]}"
        platform.add(_connection(acme.id, contested))
        await platform.commit()

        platform.add(_connection(globex.id, contested))
        with pytest.raises(IntegrityError, match="uq_source_connections_provider_installation"):
            await platform.commit()
        await platform.rollback()

    async def test_a_scoped_session_cannot_create_a_connection(
        self, session: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        """INSERT is not granted, so this is refused before policies are read.

        Connecting an integration is a platform operation: the endpoint that
        does it runs on the platform connection because the webhook path
        resolves installations before tenant context exists. A scoped session
        that could insert here could register a connection for an installation
        it does not own and start receiving another organisation's activity.
        """
        acme, _ = two_workspaces
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(
                text("""
                    INSERT INTO source_connections
                        (tenant_id, provider, external_account_id, installation_id, state)
                    VALUES (:t, 'github', 'rogue', 'rogue-1', 'connected')
                """),
                {"t": str(acme.id)},
            )

    async def test_a_scoped_session_cannot_rewrite_one(
        self, session: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        """UPDATE is not granted either.

        Without that, a scoped session could point its own connection's
        `installation_id` at another workspace's installation — a takeover by
        UPDATE rather than by INSERT, which a grant set that only withheld
        INSERT would miss.
        """
        acme, _ = two_workspaces
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="permission denied"):
            await session.execute(text("UPDATE source_connections SET installation_id = 'taken'"))

    async def test_an_error_state_must_carry_a_category(
        self, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        # An error nobody can act on produces a support ticket that begins "it
        # says error", which is the whole conversation.
        acme, _ = two_workspaces
        platform.add(
            _connection(acme.id, f"broken-{uuid.uuid4().hex[:8]}", state=ConnectionState.ERROR)
        )

        with pytest.raises(IntegrityError, match="error_has_category"):
            await platform.commit()
        await platform.rollback()

    async def test_consent_is_recorded_whole_or_not_at_all(
        self, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        # Half of it — a user with no timestamp — is the shape that makes an
        # audit unanswerable while looking populated.
        acme, _ = two_workspaces
        platform.add(
            _connection(acme.id, f"half-{uuid.uuid4().hex[:8]}", authorised_by_user_id=uuid.uuid4())
        )

        with pytest.raises(IntegrityError, match="consent_is_whole"):
            await platform.commit()
        await platform.rollback()


@pytest.mark.integration
class TestGitHubUsesIt:
    """The vertical slice: production traffic, not a fixture, fills this table.

    Every assertion below runs against ``github_installations`` only. Nothing
    here writes a ``SourceConnection`` — if one exists afterwards, the existing
    GitHub integration put it there.
    """

    @staticmethod
    async def _connection_for(session: AsyncSession, installation_id: int) -> SourceConnection:
        # `populate_existing`, because the row is written by a trigger the ORM
        # knows nothing about. Without it the identity map answers from the
        # state it last saw and the projection appears not to have run.
        found = await session.scalar(
            select(SourceConnection)
            .where(
                SourceConnection.provider == ConnectorProvider.GITHUB,
                SourceConnection.installation_id == str(installation_id),
            )
            .execution_options(populate_existing=True)
        )
        assert found is not None, "Connecting GitHub produced no SourceConnection"
        return found

    async def test_connecting_an_installation_produces_a_connection(
        self, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        acme, _ = two_workspaces
        installation_id = uuid.uuid4().int % 10_000_000

        platform.add(
            GitHubInstallation(
                tenant_id=acme.id,
                installation_id=installation_id,
                account_login="acme-eng",
                account_type="Organization",
            )
        )
        await platform.commit()

        connection = await self._connection_for(platform, installation_id)

        assert connection.tenant_id == acme.id
        assert connection.provider is ConnectorProvider.GITHUB
        assert connection.state is ConnectionState.CONNECTED
        assert connection.external_account_id == "acme-eng"
        assert connection.is_active
        # Not healthy. Nothing measures GitHub ingestion health yet, and a
        # connection reporting health it never checked is the exact failure the
        # column exists to prevent.
        assert connection.health is ConnectionHealth.UNKNOWN
        # `github_installations` never recorded who pressed connect, so an
        # honest blank beats a plausible invented user id.
        assert connection.authorised_by_user_id is None

    async def test_suspension_and_uninstall_are_distinguishable(
        self, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        """Suspended is not revoked.

        Suspension is reversible without re-authorising; an uninstall is the
        customer withdrawing at GitHub and needs a fresh grant. Collapsing them
        produces the support ticket where a customer keeps pressing a reconnect
        button that cannot work.
        """
        acme, _ = two_workspaces
        installation_id = uuid.uuid4().int % 10_000_000
        installation = GitHubInstallation(
            tenant_id=acme.id,
            installation_id=installation_id,
            account_login="acme-eng",
            account_type="Organization",
        )
        platform.add(installation)
        await platform.commit()

        installation.suspended_at = datetime.now(UTC)
        await platform.commit()
        assert (await self._connection_for(platform, installation_id)).state is (
            ConnectionState.DISCONNECTED
        )

        installation.uninstalled_at = datetime.now(UTC)
        await platform.commit()
        revoked = await self._connection_for(platform, installation_id)
        assert revoked.state is ConnectionState.REVOKED
        assert revoked.revoked_at is not None
        assert not revoked.is_active

    async def test_reconnecting_revives_the_same_connection(
        self, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        """The connect endpoint clears the timestamps rather than inserting.

        The row is retained across an uninstall precisely so this is a revival
        with its history intact — a second connection row would make the same
        installation look like two customers.
        """
        acme, _ = two_workspaces
        installation_id = uuid.uuid4().int % 10_000_000
        installation = GitHubInstallation(
            tenant_id=acme.id,
            installation_id=installation_id,
            account_login="acme-eng",
            account_type="Organization",
            uninstalled_at=datetime.now(UTC),
        )
        platform.add(installation)
        await platform.commit()
        original = (await self._connection_for(platform, installation_id)).id

        installation.uninstalled_at = None
        installation.suspended_at = None
        await platform.commit()

        revived = await self._connection_for(platform, installation_id)
        assert revived.id == original
        assert revived.state is ConnectionState.CONNECTED
        assert revived.revoked_at is None

    async def test_the_projection_respects_the_uniqueness_rule(
        self, platform: AsyncSession, two_workspaces: tuple[Tenant, Tenant]
    ) -> None:
        """The generalised constraint must not be looser than GitHub's own.

        `github_installations.installation_id` is globally unique today. If the
        projection collapsed two installations onto one connection, or allowed
        two connections for one installation, the guarantee the connect
        endpoint's 409 depends on would be gone.
        """
        acme, globex = two_workspaces
        installation_id = uuid.uuid4().int % 10_000_000
        platform.add(
            GitHubInstallation(
                tenant_id=acme.id,
                installation_id=installation_id,
                account_login="acme-eng",
                account_type="Organization",
            )
        )
        await platform.commit()

        platform.add(
            GitHubInstallation(
                tenant_id=globex.id,
                installation_id=installation_id,
                account_login="globex-eng",
                account_type="Organization",
            )
        )
        with pytest.raises(IntegrityError):
            await platform.commit()
        await platform.rollback()

        assert (
            await platform.scalar(
                select(func.count())
                .select_from(SourceConnection)
                .where(SourceConnection.installation_id == str(installation_id))
            )
            == 1
        )


@pytest.fixture
async def two_workspaces(platform: AsyncSession) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two workspaces, each with one connection, committed for real.

    Committed because the application session runs on its own connection: rows
    left uncommitted would be invisible to it, and every isolation test would
    pass by seeing nothing at all — the most misleading possible outcome for a
    test whose purpose is proving data is hidden.
    """
    suffix = uuid.uuid4().hex[:8]
    acme = Tenant(name="Acme", slug=f"acme-conn-{suffix}")
    globex = Tenant(name="Globex", slug=f"globex-conn-{suffix}")
    platform.add_all([acme, globex])
    await platform.flush()

    # Deliberately similar, so a leak shows up as a wrong count rather than
    # requiring someone to notice an unfamiliar name.
    platform.add_all(
        [
            _connection(acme.id, f"acme-{suffix}"),
            _connection(globex.id, f"globex-{suffix}"),
        ]
    )
    await platform.commit()

    # Captured before the test runs, not after. Several tests below deliberately
    # provoke a constraint violation and roll back, which expires every instance
    # in the session — so reading `acme.id` during teardown would trigger a lazy
    # refresh from a synchronous context and fail with `MissingGreenlet`, in the
    # fixture rather than in the test that caused it.
    ids = [acme.id, globex.id]

    yield acme, globex

    # Scoped to what this fixture created. A blanket delete would remove
    # workspaces another module committed and is still using, and the symptom
    # surfaces at the *setup* of an unrelated test.
    await platform.execute(delete(SourceConnection).where(SourceConnection.tenant_id.in_(ids)))
    await platform.execute(delete(GitHubInstallation).where(GitHubInstallation.tenant_id.in_(ids)))
    await platform.execute(delete(Tenant).where(Tenant.id.in_(ids)))
    await platform.commit()
