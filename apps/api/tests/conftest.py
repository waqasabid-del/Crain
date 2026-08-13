"""Shared test fixtures.

Database tests run against a real PostgreSQL instance rather than SQLite. The
differences that matter to CAIRN — row-level security, ``timestamptz``
semantics, native UUID generation, pgvector — do not exist in SQLite, so a
suite that passed there would give false confidence about exactly the areas
carrying the most risk.

Each test gets a transaction that is rolled back afterwards, so tests are
isolated without the cost of recreating the schema between them.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from cairn_api.db.base import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "CAIRN_TEST_DATABASE_URL",
    "postgresql+asyncpg://cairn:cairn_local_dev@localhost:5432/cairn_test",
)


def _database_available() -> bool:
    """Whether a test database can be reached.

    Integration tests skip rather than fail when Postgres is absent, so that a
    contributor without Docker running still gets useful signal from the rest of
    the suite. CI always has the database, so coverage is never silently lost.
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
    """Skip integration tests when no database is reachable.

    Implemented as a hook rather than an importable marker so that test modules
    need only declare ``pytest.mark.integration`` — no cross-module import, and
    no `__init__.py` turning the test directory into a package.
    """
    if _database_available():
        return

    skip = pytest.mark.skip(reason="PostgreSQL not reachable — run `docker compose up -d`")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[object]:
    """Session-wide engine with a freshly created schema."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=None)

    async with eng.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield eng

    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: object) -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is always rolled back.

    Rolling back rather than truncating keeps tests fast and, more importantly,
    means a test that leaves data behind cannot affect the next one — the class
    of flakiness that is hardest to diagnose.
    """
    from sqlalchemy.ext.asyncio import AsyncEngine

    assert isinstance(engine, AsyncEngine)

    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False)

    try:
        async with factory() as sess:
            yield sess
    finally:
        # A test that deliberately triggers an IntegrityError leaves the
        # transaction already aborted, so rolling back again warns. Checking
        # first keeps the suite warning-free — warnings that are normal become
        # warnings nobody reads.
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
