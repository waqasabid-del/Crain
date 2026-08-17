"""The restore, rehearsed.

The gap this closes is not "there is no backup script". It is that a backup
nobody has restored from is a hypothesis — and the sharper version, which is
what most of this file is about: a *verifier* nobody has watched fail is also a
hypothesis.

So the load-bearing tests here are the negative ones.
`test_an_empty_dump_restores_successfully_and_fails_verification` restores a
file containing nothing, which `psql` accepts with exit code zero, and asserts
the verifier refuses it. `test_a_truncated_dump_is_caught_by_the_row_counts`
restores a schema with no data. A verifier that only passes on the happy path
would pass on both, and would have told an operator their empty database was a
successful recovery.

These run against a throwaway database whose name has to contain "restore" or
"rehearsal" — the same rule the tool enforces on an operator, asserted here
rather than exempted for tests.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from cairn_api.ops import backup
from cairn_api.ops.backup import BackupError, Target

pytestmark = pytest.mark.integration

API_DIR = Path(__file__).parents[1]

#: The database the rehearsal restores into. Distinct from the name the CLI
#: defaults to, so a test run cannot destroy an operator's rehearsal copy while
#: they are looking at it.
REHEARSAL_DATABASE = "cairn_restore_rehearsal_test"

#: The source this file dumps from — its own, built by migrations here.
#:
#: Not `cairn_test`. Verification compares row counts between the source and the
#: copy, and the rest of the suite is inserting into `cairn_test` the whole time
#: a dump is running: the counts would drift between the dump and the reading,
#: and this file would fail for a reason that has nothing to do with backups.
#: A source nobody else writes to is the only way these assertions mean what
#: they say. (It is also two orders of magnitude smaller, so the cycle is
#: seconds rather than minutes.)
SOURCE_DATABASE = "cairn_restore_source_test"

#: Connection parameters. Only the host, port and credentials are used — the
#: database name is replaced by the two above.
SERVER_URL = os.environ.get(
    "CAIRN_TEST_MIGRATION_URL",
    "postgresql+asyncpg://cairn:cairn_local_dev@localhost:5432/cairn_test",
)


def _drop(target: Target) -> None:
    connected = backup._connect(target.named("postgres"), autocommit=True)
    with connected as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (target.database,),
        )
        cursor.execute(f'DROP DATABASE IF EXISTS "{target.database}"')


@pytest.fixture(scope="module")
def source() -> Iterator[Target]:
    """A migrated, private source database.

    Built by running the migrations, exactly as `conftest.py` builds the test
    schema and for the same reason: a schema assembled any other way is not the
    schema that ships, and a backup test asserting on the wrong schema proves
    nothing about restoring the real one.
    """
    server = Target.from_url(SERVER_URL)
    target = server.named(SOURCE_DATABASE)
    backup._recreate_database(target)

    url = f"postgresql+asyncpg://{target.user}:{target.password}@{target.host}:{target.port}/{target.database}"
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],  # noqa: S607
        cwd=API_DIR,
        env={**os.environ, "CAIRN_PLATFORM_DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"could not migrate the backup source:\n{result.stdout}\n{result.stderr}")

    yield target

    _drop(target)
    _drop(server.named(REHEARSAL_DATABASE))


@pytest.fixture
def seeded(source: Target) -> Iterator[Target]:
    """A workspace in the source, so a restore of it has something to prove.

    Written through psycopg rather than the ORM: this test is about a database
    being copied byte for byte, and going through the application's session
    machinery would only add ways for the fixture to be the thing that failed.
    """
    slug = f"restore-{uuid.uuid4().hex[:8]}"
    with backup._connect(source, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (name, slug, region) VALUES (%s, %s, %s) RETURNING id",
            ("Rehearsal Workspace", slug, "us-central1"),
        )
        row = cursor.fetchone()
        assert row is not None
        tenant_id = row[0]

    yield source

    with backup._connect(source, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


@pytest.fixture
def source_url(source: Target) -> str:
    return f"postgresql://{source.user}:{source.password}@{source.host}:{source.port}/{source.database}"


@pytest.fixture
def dump_path(tmp_path: Path) -> Path:
    return tmp_path / "rehearsal.sql"


# --------------------------------------------------------------------------
# The cycle
# --------------------------------------------------------------------------


def test_the_whole_cycle_verifies(seeded: Target, source_url: str, dump_path: Path) -> None:
    """Dump, restore into a separate database, verify. The rehearsal itself.

    Asserts on the individual checks rather than only on `ok`, so a future
    verification that silently stopped running one of them fails here instead
    of passing with two thirds of the evidence.
    """
    result = backup.rehearse(
        source_url, target_database=REHEARSAL_DATABASE, dump_path=dump_path, keep_dump=True
    )

    assert result.ok, [str(check) for check in result.verification.failures]
    assert result.dump_bytes > 0
    assert result.target_database == REHEARSAL_DATABASE

    names = {check.name for check in result.verification.checks}
    assert "alembic revision" in names
    assert "sample workspace" in names
    assert {f"rows in {table}" for table in backup.KEY_TABLES} <= names


def test_the_restore_does_not_touch_the_source(
    seeded: Target, source_url: str, dump_path: Path
) -> None:
    """The property that makes this safe to run on a schedule.

    A rehearsal that dropped its source would be a data-loss incident caused by
    the tool meant to prevent one.
    """
    before = backup.expectation_for(seeded)

    backup.rehearse(
        source_url, target_database=REHEARSAL_DATABASE, dump_path=dump_path, keep_dump=True
    )

    after = backup.expectation_for(seeded)
    assert after.row_counts == before.row_counts
    assert after.revision == before.revision
    assert after.sample_tenant == before.sample_tenant


# --------------------------------------------------------------------------
# The verifier has to fail
# --------------------------------------------------------------------------


def test_an_empty_dump_restores_successfully_and_fails_verification(
    seeded: Target, dump_path: Path
) -> None:
    """The case the whole module exists for.

    `psql` reads an empty file, runs no statements and exits zero. Every
    "restore completed successfully" message is true; the database has no
    tables. A verifier that trusted the exit code would report a recovery that
    recovered nothing.
    """
    expectation = backup.expectation_for(seeded)
    dump_path.write_text("", encoding="utf-8")

    # The restore itself succeeds — that is the point.
    backup.restore(dump_path, seeded, seeded.named(REHEARSAL_DATABASE))

    verification = backup.verify(seeded.named(REHEARSAL_DATABASE), expectation)

    assert not verification.ok
    failures = {check.name for check in verification.failures}
    assert "alembic revision" in failures, "a schema-less restore passed the revision check"
    assert "rows in tenants" in failures
    assert "sample workspace" in failures


def test_a_truncated_dump_is_caught_by_the_row_counts(seeded: Target, dump_path: Path) -> None:
    """Schema restored, data lost — the failure a revision check alone misses.

    Truncating at the first COPY reproduces a dump cut off by a full disk or a
    killed process. The alembic revision may well be present; the rows are not,
    and the row counts are the only check that notices.
    """
    backup.dump(seeded, dump_path)
    expectation = backup.expectation_for(seeded)

    full = dump_path.read_text(encoding="utf-8")
    cut = full.find("COPY public.")
    assert cut > 0, "the dump has no COPY section; this test is asserting nothing"
    dump_path.write_text(full[:cut], encoding="utf-8")

    backup.restore(dump_path, seeded, seeded.named(REHEARSAL_DATABASE))
    verification = backup.verify(seeded.named(REHEARSAL_DATABASE), expectation)

    assert not verification.ok
    assert "rows in tenants" in {check.name for check in verification.failures}


def test_a_verification_with_no_checks_is_not_a_pass() -> None:
    """`all([])` is `True`, and a verifier that ran nothing would report success.

    Not hypothetical: it is the state a refactor that moves the checks behind a
    condition arrives at.
    """
    assert not backup.Verification(()).ok


def test_a_source_with_no_workspaces_cannot_be_verified(seeded: Target) -> None:
    """Restoring an empty database proves nothing, and must not read as proof.

    The sample-row check is the one that reads real data. With no row to sample
    it fails rather than being skipped — skipping would make an empty source the
    easiest way to get a green rehearsal.
    """
    expectation = backup.Expectation(revision="x", row_counts={}, sample_tenant=None)
    check = backup._check_real_query(seeded, expectation)

    assert not check.ok
    assert "proves nothing" in check.detail


# --------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["cairn_production", "cairn_prod", "cairn-live", "CAIRN_PROD"])
def test_it_refuses_a_source_that_looks_like_production(source: Target, name: str) -> None:
    with pytest.raises(BackupError, match="suggests production"):
        backup.guard_source(source.named(name))


@pytest.mark.parametrize("name", ["cairn_production", "cairn_restore_live"])
def test_it_refuses_a_target_that_looks_like_production(source: Target, name: str) -> None:
    with pytest.raises(BackupError, match="suggests production"):
        backup.guard_target(source, source.named(name))


def test_it_refuses_to_restore_over_its_own_source(source: Target) -> None:
    """The mistake with no undo.

    One transposed argument, and the rehearsal overwrites the database it was
    rehearsing for with a copy of that database as it was an hour ago.
    """
    with pytest.raises(BackupError, match="over itself"):
        backup.guard_target(source, source)


def test_it_refuses_a_target_that_is_not_named_as_disposable(source: Target) -> None:
    """A rehearsal copy has to announce itself.

    Otherwise it is a database on a server that nobody can tell from a real one,
    and the safe thing to do with it forever is nothing.
    """
    with pytest.raises(BackupError, match="say so in its name"):
        backup.guard_target(source, source.named("cairn_spare"))


def test_the_guards_run_before_anything_is_dropped(source: Target, tmp_path: Path) -> None:
    """A refusal must come from the guard, not from a later failure.

    `restore` drops and recreates its target. If the guard ran after that, a
    refused rehearsal would still have destroyed a database — which is the
    entire failure the guard exists to prevent, arriving through the guard.
    """
    dump = tmp_path / "unused.sql"
    dump.write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(BackupError, match="suggests production"):
        backup.restore(dump, source, source.named("cairn_production_restore"))

    # Nothing was created: the maintenance database still does not know it.
    with backup._connect(source.named("postgres")) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_database WHERE datname = %s", ("cairn_production_restore",)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == 0


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_a_sqlalchemy_url_loses_its_driver() -> None:
    """`pg_dump` has never heard of `+asyncpg`."""
    target = Target.from_url("postgresql+asyncpg://user:pw@db.example:6543/cairn_dev")

    assert (target.host, target.port, target.user, target.database) == (
        "db.example",
        6543,
        "user",
        "cairn_dev",
    )


def test_a_percent_encoded_password_is_decoded() -> None:
    """A password containing `@` or `/` is encoded in a URL. Passing the encoded
    form to libpq is an authentication failure that reads like a firewall
    problem."""
    target = Target.from_url("postgresql://user:p%40ss%2Fword@localhost:5432/cairn_dev")
    assert target.password == "p@ss/word"  # noqa: S105 — a parsing fixture, not a credential


def test_a_url_with_no_database_is_refused() -> None:
    with pytest.raises(BackupError, match="cannot read a host and database"):
        Target.from_url("postgresql://localhost")
