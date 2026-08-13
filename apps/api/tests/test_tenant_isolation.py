"""Tenant isolation tests.

The most important tests in the codebase. Everything else protects against a
bug; these protect against the failure that would end the product.

They are written as **attacks**. Each one tries to reach another tenant's data
the way a real mistake would — a forgotten filter, a raw query, a leaked
session — and asserts the attempt returns nothing. A test that merely confirms
the happy path proves only that the feature works when used correctly, which is
never the case that leaks data.

Note these run against real PostgreSQL. Row-level security does not exist in
SQLite, so a suite that used it would pass while proving nothing about the
mechanism carrying the most risk.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import (
    MissingTenantContextError,
    get_tenant_context,
    set_tenant_context,
    tenant_session,
)
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


@pytest.fixture
async def two_tenants(platform: AsyncSession) -> AsyncIterator[tuple[Tenant, Tenant]]:
    """Two tenants with deliberately similar data.

    Similar rather than distinct on purpose: if Acme and Globex both have a user
    called "Ali" with the same role, a leak shows up as a wrong *count* rather
    than requiring someone to notice an unfamiliar name.

    Built through the *platform* session because that is genuinely how signup
    works — creating a workspace precedes any tenant context, so it cannot be
    done from a scoped session. The data is committed so that the separate,
    RLS-subject application session can see it.
    """
    acme = Tenant(name="Acme", slug="acme")
    globex = Tenant(name="Globex", slug="globex")
    platform.add_all([acme, globex])
    await platform.flush()

    acme_user = User(email="ali@acme.test", display_name="Ali")
    globex_user = User(email="ali@globex.test", display_name="Ali")
    platform.add_all([acme_user, globex_user])
    await platform.flush()

    platform.add_all(
        [
            Membership(tenant_id=acme.id, user_id=acme_user.id, role=TenantRole.OWNER),
            Membership(tenant_id=globex.id, user_id=globex_user.id, role=TenantRole.OWNER),
        ]
    )
    await platform.commit()

    yield acme, globex

    # The application session runs on its own connection, so this data is not
    # covered by that session's rollback and must be removed explicitly.
    await platform.execute(delete(Membership))
    await platform.execute(delete(User))
    await platform.execute(delete(Tenant))
    await platform.commit()


class TestRowLevelSecurity:
    """Database-level isolation. The safety net."""

    async def test_scoped_session_sees_only_its_own_memberships(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        count = await session.scalar(select(func.count()).select_from(Membership))

        assert count == 1, "A scoped session must not see another tenant's memberships"

    async def test_scoped_session_sees_only_its_own_tenant_row(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        visible = (await session.scalars(select(Tenant.id))).all()

        assert list(visible) == [acme.id]
        assert globex.id not in visible

    async def test_users_are_filtered_by_shared_membership(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """Without this, any context could enumerate every email on the platform."""
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        emails = set((await session.scalars(select(User.email))).all())

        assert emails == {"ali@acme.test"}

    async def test_unscoped_session_sees_nothing(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """A query with no tenant context returns no rows rather than everything.

        This is the case that matters most. A raw query, a forgotten filter, or a
        library opening its own session all arrive here. Returning zero rows is
        safe; returning every row is the failure this whole step exists to
        prevent.
        """
        _ = two_tenants

        assert await session.scalar(select(func.count()).select_from(Membership)) == 0
        assert await session.scalar(select(func.count()).select_from(Tenant)) == 0
        assert await session.scalar(select(func.count()).select_from(User)) == 0

    async def test_context_does_not_leak_between_transactions(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """``SET LOCAL`` must not survive its transaction.

        If context were set with plain ``SET``, a pooled connection would carry
        one tenant's scope into the next request that borrowed it — a
        cross-tenant leak caused by a single missing keyword, visible only under
        concurrency.
        """
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)
        assert await get_tenant_context(session) == acme.id

        await session.rollback()

        assert await get_tenant_context(session) is None, (
            "Tenant context survived its transaction — check SET LOCAL is used"
        )

    async def test_cannot_write_into_another_tenant(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """WITH CHECK must block a scoped session from writing across the boundary."""
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        # A membership row aimed at another tenant must be refused, even though
        # this session is legitimately authenticated for its own.
        session.add(Membership(tenant_id=globex.id, user_id=uuid.uuid4()))

        with pytest.raises(DBAPIError, match="row-level security"):
            await session.flush()

    async def test_cannot_move_a_row_across_the_boundary(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """An UPDATE must not reassign a row to another tenant."""
        acme, globex = two_tenants
        await set_tenant_context(session, acme.id)

        with pytest.raises(DBAPIError, match="row-level security"):
            await session.execute(
                text("UPDATE memberships SET tenant_id = :other"),
                {"other": str(globex.id)},
            )

    async def test_raw_sql_is_also_filtered(
        self, session: AsyncSession, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """RLS applies below the ORM.

        The ORM can be bypassed — by a raw query, a reporting script, or a
        library. Isolation that lived only in application code would not survive
        any of those.
        """
        acme, _ = two_tenants
        await set_tenant_context(session, acme.id)

        count = await session.scalar(text("SELECT count(*) FROM memberships"))

        assert count == 1

    async def test_force_row_level_security_is_enabled(self, session: AsyncSession) -> None:
        """The misconfiguration that silently disables everything above.

        ``ENABLE ROW LEVEL SECURITY`` does not apply to a table's owner, and the
        application connects as the owner. Without ``FORCE``, every policy is
        inert while still appearing correct in psql output.
        """
        rows = (
            await session.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname IN ('tenants','users','memberships')"
                )
            )
        ).all()

        assert len(rows) == 3
        for name, enabled, forced in rows:
            assert enabled, f"RLS not enabled on {name}"
            assert forced, f"RLS not FORCED on {name} — policies are inert for the table owner"


class TestApplicationLayer:
    """Application-level isolation. Fails loudly, so mistakes are caught early."""

    async def test_tenant_session_requires_a_tenant(self) -> None:
        with pytest.raises(MissingTenantContextError, match="requires a tenant ID"):
            async with tenant_session(None):
                pass  # pragma: no cover — the context manager must not open

    async def test_missing_context_error_is_not_a_value_error(self) -> None:
        """It must not be swallowed by generic input-validation handling.

        A broad ``except ValueError`` written for bad user input would otherwise
        hide a data-isolation defect.
        """
        assert not issubclass(MissingTenantContextError, ValueError)

    async def test_set_and_read_context_round_trip(self, session: AsyncSession) -> None:
        tenant_id = uuid.uuid4()
        await set_tenant_context(session, tenant_id)
        assert await get_tenant_context(session) == tenant_id

    async def test_context_is_empty_by_default(self, session: AsyncSession) -> None:
        assert await get_tenant_context(session) is None
