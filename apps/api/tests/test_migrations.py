"""Migration tests.

A migration that applies cleanly but cannot be reversed is only half a
migration. The reverse path is exercised precisely when something has gone
wrong in production — the worst possible moment to discover it does not work.

These tests were written after a real failure: the initial migration dropped its
tables on downgrade but left the PostgreSQL enum types behind, so
``downgrade`` followed by ``upgrade`` failed with "type already exists". That is
exactly the sequence a rollback performs.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration, pytest.mark.slow]

API_DIR = Path(__file__).parents[1]

# A dedicated database, so a downgrade cannot destroy the schema other tests use.
MIGRATION_DB_URL = os.environ.get(
    "CAIRN_MIGRATION_TEST_DATABASE_URL",
    "postgresql+psycopg://cairn:cairn_local_dev@localhost:5432/cairn_migrations",
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Run an Alembic command against the migration test database."""
    env = {**os.environ, "CAIRN_DATABASE_URL": MIGRATION_DB_URL.replace("+psycopg", "+asyncpg")}
    return subprocess.run(  # noqa: S603
        ["uv", "run", "alembic", *args],  # noqa: S607
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def migration_db() -> str:
    """Create an empty database for migration round-trip testing."""
    admin_url = MIGRATION_DB_URL.rsplit("/", 1)[0] + "/postgres"
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = MIGRATION_DB_URL.rsplit("/", 1)[1]

    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine.dispose()

    return MIGRATION_DB_URL


def test_upgrade_applies_cleanly(migration_db: str) -> None:
    result = _alembic("upgrade", "head")
    assert result.returncode == 0, f"upgrade failed:\n{result.stderr}"


def test_downgrade_reverses_cleanly(migration_db: str) -> None:
    result = _alembic("downgrade", "base")
    assert result.returncode == 0, f"downgrade failed:\n{result.stderr}"


def test_upgrade_downgrade_upgrade_round_trips(migration_db: str) -> None:
    """The sequence a production rollback actually performs.

    This is the test that would have caught the leftover-enum bug.
    """
    assert _alembic("upgrade", "head").returncode == 0
    assert _alembic("downgrade", "base").returncode == 0

    second = _alembic("upgrade", "head")
    assert second.returncode == 0, (
        "Re-applying after a downgrade failed. Something the downgrade should "
        f"have dropped was left behind:\n{second.stderr}"
    )

    engine = create_engine(migration_db)
    with engine.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            )
        }
    engine.dispose()

    assert {"tenants", "users", "memberships"} <= tables


def test_downgrade_leaves_no_orphaned_types(migration_db: str) -> None:
    """Enum types must be dropped alongside the tables that used them.

    ``op.drop_table`` does not drop the enum type it referenced, which is the
    specific trap this migration originally fell into.
    """
    assert _alembic("upgrade", "head").returncode == 0
    assert _alembic("downgrade", "base").returncode == 0

    engine = create_engine(migration_db)
    with engine.connect() as conn:
        leftover = {
            row[0]
            for row in conn.execute(
                text("SELECT typname FROM pg_type WHERE typname IN ('region', 'tenant_role')")
            )
        }
    engine.dispose()

    assert leftover == set(), f"Downgrade left enum types behind: {leftover}"
