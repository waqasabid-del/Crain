"""Shared test fixtures.

Database tests run against real PostgreSQL rather than SQLite. The differences
that matter to CAIRN — row-level security, ``timestamptz`` semantics, native
UUID generation, pgvector — do not exist in SQLite, so a suite using it would
pass while proving nothing about the mechanisms carrying the most risk.

**The schema is built by running migrations, not ``create_all``.**

That distinction caused a real failure. ``Base.metadata.create_all`` builds
tables from the models, but row-level security policies live in a migration and
have no model representation — so the test database had no isolation while
production did. Every isolation test passed for the wrong reason.

More generally, ``create_all`` and the migration history drift apart silently:
one describes the models as they are now, the other describes how production
actually got built. Testing against migrations means the migration itself is
exercised on every run, and the schema under test is the schema that ships.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

API_DIR = Path(__file__).parents[1]

#: Migrations run as the owner — they need DDL, and creating roles needs
#: superuser. Alembic uses this URL.
MIGRATION_DATABASE_URL = os.environ.get(
    "CAIRN_TEST_MIGRATION_URL",
    "postgresql+asyncpg://cairn:cairn_local_dev@localhost:5432/cairn_test",
)

#: Tests connect as the *application* role, because row-level security does not
#: apply to superusers. Running tests as the owner would make every isolation
#: test pass while proving nothing — see migration c8b2f5a41e77.
TEST_DATABASE_URL = os.environ.get(
    "CAIRN_TEST_DATABASE_URL",
    "postgresql+asyncpg://cairn_app:cairn_local_dev@localhost:5432/cairn_test",
)


# Point application settings at the test database *before* anything imports
# them. `get_settings`, `get_engine` and the session factories are all cached,
# so a late override would be ignored and code under test would quietly connect
# to the development database — which is how a test suite ends up asserting
# against data it never created.
os.environ["CAIRN_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["CAIRN_PLATFORM_DATABASE_URL"] = MIGRATION_DATABASE_URL


# HTTP fixtures live in their own module so the database fixtures above stay
# readable. Re-exported here because pytest only discovers fixtures in conftest.
from conftest_api import app, client, limiter  # noqa: E402, F401


def _database_available() -> bool:
    """Whether a test database can be reached.

    Locally, integration tests skip rather than fail when PostgreSQL is absent,
    so a contributor without Docker running still gets signal from the rest of
    the suite. In CI they must never skip — see
    :func:`pytest_collection_modifyitems`.
    """
    import socket

    host_port = TEST_DATABASE_URL.split("@")[-1].split("/")[0]
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host, int(port or 5432)), timeout=1):
            return True
    except OSError:
        return False


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip integration tests locally when no database is reachable — never in CI.

    Skipping is a convenience for a contributor without Docker running, so the
    rest of the suite still gives signal. In CI the same behaviour is a
    disaster: an unreachable database silently skips every isolation, schema and
    migration test while the run reports green.

    That is not hypothetical — this project shipped exactly that state. CI had no
    PostgreSQL service, so 59 of 150 tests never executed, including all 13
    tenant-isolation tests. Every run was green and the most important safety net
    in the system was not running at all.

    So when ``CI`` is set, an unreachable database is a hard failure.

    A hook rather than an importable marker, so test modules need only declare
    ``pytest.mark.integration`` — no cross-module import, and no ``__init__.py``
    turning the test directory into a package.
    """
    if _database_available():
        return

    integration_items = [item for item in items if "integration" in item.keywords]

    if os.environ.get("CI") and integration_items:
        target = TEST_DATABASE_URL.split("@")[-1]
        pytest.exit(
            f"PostgreSQL unreachable at {target}. CI must never skip integration "
            f"tests — {len(integration_items)} would have been skipped silently, "
            "including the tenant-isolation suite. Check the `services:` block in "
            ".github/workflows/ci.yml.",
            returncode=1,
        )

    skip = pytest.mark.skip(reason="PostgreSQL not reachable — run `make db-up`")
    for item in integration_items:
        item.add_marker(skip)


def _run_migrations() -> None:
    """Build the test schema by applying migrations, exactly as production does."""
    # Alembic derives its URL from the *platform* setting, because migrations
    # need DDL privileges the application role deliberately does not hold.
    env = {**os.environ, "CAIRN_PLATFORM_DATABASE_URL": MIGRATION_DATABASE_URL}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],  # noqa: S607
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"Test schema migration failed:\n{result.stdout}\n{result.stderr}")


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Session-wide engine against a freshly migrated schema."""
    admin = create_async_engine(MIGRATION_DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        # Start from nothing, so a half-applied schema from an earlier run
        # cannot produce confusing failures.
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await admin.dispose()

    _run_migrations()

    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def platform_engine(engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Privileged engine, mirroring production's platform connection.

    Depends on ``engine`` purely for ordering: that fixture rebuilds the schema,
    and a privileged connection opened before it would find no tables.

    Creating a workspace or a user account happens before any tenant context can
    exist, so those operations bypass row-level security in production too. Test
    fixtures that build a scenario use this for exactly the same reason.
    """
    eng = create_async_engine(MIGRATION_DATABASE_URL, echo=False)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def platform(platform_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A privileged session for building test scenarios.

    Unlike ``session``, this one commits for real and is **not** wrapped in a
    rolled-back transaction. It has to be: the application session runs on a
    separate connection, so uncommitted rows would be invisible to it and every
    isolation test would pass by seeing nothing at all — the most misleading
    possible outcome for tests whose entire purpose is proving that data is
    hidden correctly.

    Fixtures using this are responsible for cleaning up what they create.
    """
    factory = async_sessionmaker(bind=platform_engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A session in a transaction that is always rolled back.

    Rolling back rather than truncating keeps tests fast and, more importantly,
    means a test that leaves data behind cannot affect the next one — the
    hardest class of flakiness to diagnose.
    """
    connection: AsyncConnection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False)

    try:
        async with factory() as sess:
            yield sess
    finally:
        # A test that deliberately triggers an IntegrityError leaves the
        # transaction aborted, so rolling back again warns. Checking first keeps
        # the suite warning-free — warnings that are normal become warnings
        # nobody reads.
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
