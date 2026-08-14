"""Startup preflight tests.

These exist because the first version of ``preflight.py`` was written, described
in the audit as protection, and then **never called and never tested** — the
exact false confidence the module is meant to prevent, reproduced in the fix for
it. Tests are the minimum bar; the API layer wires the call at startup.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cairn_api.db.preflight import (
    PreflightError,
    check_application_role,
    check_platform_role,
    run_preflight_checks,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

pytestmark = [pytest.mark.integration, pytest.mark.isolation]


class TestRoleAttributes:
    async def test_application_role_is_subject_to_rls(self) -> None:
        """The property every isolation guarantee rests on.

        If the application connects as a superuser or a BYPASSRLS role, every
        policy in the schema is inert while ``pg_policies`` stays populated and
        the tests stay green.
        """
        role = await check_application_role()

        assert not role.is_superuser
        assert not role.bypasses_rls

    async def test_platform_role_can_bypass_rls(self) -> None:
        """Otherwise signup and login silently return nothing.

        Every table is FORCE ROW LEVEL SECURITY, so a platform role without
        BYPASSRLS reads zero rows — presenting as "no such user" for every
        account rather than as an error.
        """
        role = await check_platform_role()

        assert role.is_superuser or role.bypasses_rls

    async def test_run_preflight_checks_passes_on_a_correct_setup(self) -> None:
        await run_preflight_checks()


class TestFailureModes:
    """The checks must actually fail when the property is violated.

    The first version of these tests asserted on ``pg_roles`` columns and never
    called the functions — so deleting the body of ``check_application_role``
    would have left them green. That is the precise pattern this whole audit
    exists to catch, reproduced in the fix for it.

    These build a real engine for a deliberately-wrong role and assert the check
    raises.
    """

    @pytest_asyncio.fixture
    async def bypassrls_engine(self, platform: AsyncSession) -> AsyncIterator[AsyncEngine]:
        """A login role that is not superuser but does hold BYPASSRLS.

        The dangerous configuration: it looks ordinary in every listing, and
        every row-level security policy is skipped.
        """
        # REVOKE before DROP — a granted privilege is a dependent object and
        # PostgreSQL refuses to drop a role while any remain — but only if the
        # role exists, since REVOKE on a missing role is an error rather than a
        # no-op.
        await platform.execute(
            text("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'preflight_probe') THEN
                        REVOKE ALL ON DATABASE cairn_test FROM preflight_probe;
                        DROP ROLE preflight_probe;
                    END IF;
                END
                $$;
            """)
        )
        await platform.commit()
        await platform.execute(
            text("CREATE ROLE preflight_probe LOGIN PASSWORD 'probe_only' NOSUPERUSER BYPASSRLS")
        )
        await platform.execute(text("GRANT CONNECT ON DATABASE cairn_test TO preflight_probe"))
        await platform.commit()

        engine = create_async_engine(
            "postgresql+asyncpg://preflight_probe:probe_only@localhost:5432/cairn_test"
        )
        try:
            yield engine
        finally:
            await engine.dispose()
            await platform.execute(
                text("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'preflight_probe') THEN
                        REVOKE ALL ON DATABASE cairn_test FROM preflight_probe;
                        DROP ROLE preflight_probe;
                    END IF;
                END
                $$;
            """)
            )
            await platform.commit()

    async def test_application_check_rejects_a_bypassrls_role(
        self, bypassrls_engine: AsyncEngine
    ) -> None:
        with pytest.raises(PreflightError, match="BYPASSRLS"):
            await check_application_role(bypassrls_engine)

    async def test_the_error_names_the_consequence(self, bypassrls_engine: AsyncEngine) -> None:
        # An error that says only "check failed" costs an hour. This one should
        # say what breaks and what to do.
        with pytest.raises(PreflightError) as exc:
            await check_application_role(bypassrls_engine)

        message = str(exc.value)
        assert "isolation" in message
        assert "CAIRN_DATABASE_URL" in message

    async def test_platform_check_accepts_a_bypassrls_role(
        self, bypassrls_engine: AsyncEngine
    ) -> None:
        # The same role that is wrong for the application is right for the
        # platform connection — the two checks are genuinely different, not one
        # check called twice.
        role = await check_platform_role(bypassrls_engine)
        assert role.bypasses_rls
