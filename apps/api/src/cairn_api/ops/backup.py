"""Backup, restore, and the verification that makes the rehearsal worth doing.

A backup nobody has restored from is a hypothesis. So is a restore that
"completed": `psql` exits zero on an empty file, and a database with no tables
in it is a successful restore by every measure except the only one that matters.

The verifier therefore asks three independent questions of the restored copy,
and all three have to be answered before a rehearsal passes:

1. **Is it the same schema?** `alembic_version.version_num` must match the
   source. A restore one migration behind will accept writes and then fail on
   the first column it does not have.
2. **Is the data there?** Row counts on the tables that carry the product's
   state, compared against the source. Zero rows in `tenants` is the shape of
   every failed restore this exists to catch.
3. **Does a real query return the expected answer?** One tenant, chosen from
   the source, looked up in the copy by primary key and compared field by
   field. Counts can be right while the rows are garbage; this is the check
   that reads one.

**Two refusals are structural.** The tool will not touch a database whose name
suggests production, and it will not restore over its own source. Both are
checked before anything is created or dropped, because the failure mode is not
"the rehearsal did not run" — it is "the rehearsal ran over the thing it was
rehearsing for".

This is a **logical dump**, not point-in-time recovery: it restores the database
as it was when `pg_dump` started, and nothing between then and the incident.
docs/BACKUP-RESTORE.md says so, along with what production still has to arrange.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import structlog

logger = structlog.get_logger(__name__)

#: Database names this tool refuses to read from or write to.
#:
#: A deny-list, unusually for this codebase, and deliberately: the allow-list
#: version would be a list of development database names, which is exactly the
#: list somebody extends with the production one when the rehearsal will not
#: run. A false positive here costs a rename; a false negative costs the
#: company.
PRODUCTION_NAMES = re.compile(r"prod|live|customer", re.IGNORECASE)

#: The restore target has to say what it is in its own name.
#:
#: An operator who finds `cairn_restore_rehearsal` on a server knows what it is
#: and that it can be dropped. One who finds `cairn2` does not, and leaves it
#: there for a year.
REHEARSAL_NAMES = re.compile(r"restore|rehears", re.IGNORECASE)

#: The tables a verification counts.
#:
#: Not every table: the point is a representative spread across the product's
#: state — tenancy, identity, ingestion, the understanding layer, and the audit
#: log whose absence would be the most serious. A count on all forty would fail
#: on any schema change and be deleted within a month.
KEY_TABLES: tuple[str, ...] = (
    "tenants",
    "users",
    "memberships",
    "webhook_deliveries",
    "facts",
    "briefs",
    "internal_audit_log",
)

#: Container name from docker-compose.yml, used when the client binaries are
#: not on the PATH — which is the normal case on a developer machine, since
#: PostgreSQL runs in Docker and nobody installed a second copy locally.
DEFAULT_CONTAINER = os.environ.get("CAIRN_PG_CONTAINER", "cairn-postgres")

#: Where dumps go by default: outside the repository, deliberately.
#:
#: A dump is a complete copy of every row in the database. Defaulting it into
#: the source tree is how one ends up in a commit, and no `.gitignore` entry is
#: as reliable as never writing it there.
DEFAULT_DUMP_DIR = Path(
    os.environ.get("CAIRN_BACKUP_DIR") or Path(tempfile.gettempdir()) / "cairn-backups"
)


class BackupError(RuntimeError):
    """A refusal or a failure. Never raised for a database that verified."""


@dataclass(frozen=True, slots=True)
class Target:
    """Where a database is and who connects to it."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_url(cls, url: str) -> Target:
        """Parse a SQLAlchemy or libpq URL.

        The driver suffix (`+asyncpg`, `+psycopg`) is dropped: this module talks
        to `pg_dump`, which has never heard of either.
        """
        parsed = urlparse(url.replace("+asyncpg", "").replace("+psycopg", ""))
        if not parsed.hostname or not parsed.path.lstrip("/"):
            msg = f"cannot read a host and database out of {url!r}"
            raise BackupError(msg)

        return cls(
            host=parsed.hostname,
            port=parsed.port or 5432,
            # Credentials in a URL are percent-encoded; a password containing a
            # `@` or `/` silently becomes the wrong password without this.
            user=unquote(parsed.username or "postgres"),
            password=unquote(parsed.password or ""),
            database=parsed.path.lstrip("/"),
        )

    def named(self, database: str) -> Target:
        """The same server, a different database."""
        return Target(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=database,
        )


@dataclass(frozen=True, slots=True)
class Expectation:
    """What the source held, captured so the copy can be compared to it."""

    revision: str
    row_counts: dict[str, int]

    #: One real row, to be looked up in the restored copy. `None` only when the
    #: source has no tenants at all — which the verifier treats as a failure,
    #: because restoring an empty database proves nothing.
    sample_tenant: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class Check:
    """One question the verifier asked and the answer it got."""

    name: str
    ok: bool
    detail: str

    def __str__(self) -> str:
        return f"[{'ok' if self.ok else 'FAIL'}] {self.name}: {self.detail}"


@dataclass(frozen=True, slots=True)
class Verification:
    """Every check, and whether the restore may be believed."""

    checks: tuple[Check, ...] = ()

    @property
    def ok(self) -> bool:
        """All of them, not most of them.

        A verification that passes on a majority is a verification that passes
        on a restore missing the audit log.
        """
        return bool(self.checks) and all(check.ok for check in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if not check.ok)


@dataclass(frozen=True, slots=True)
class Rehearsal:
    """One complete cycle, and how long each half of it took.

    The timings are reported because "how long does a restore take" is the
    question an incident asks first, and an answer measured once is worth more
    than an estimate.
    """

    dump_path: Path
    dump_bytes: int
    dump_seconds: float
    restore_seconds: float
    verification: Verification
    target_database: str

    @property
    def ok(self) -> bool:
        return self.verification.ok


# --------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------


def guard_source(target: Target) -> None:
    """Refuse to read from anything that looks like production.

    Dumping production is a legitimate operation — it is just not this tool's.
    Managed backups do it with a snapshot, without a client connection, and
    without a developer's laptop in the path. This module exists to rehearse the
    restore, and a rehearsal that starts by connecting to production has
    imported the risk it was supposed to retire.
    """
    if PRODUCTION_NAMES.search(target.database):
        msg = (
            f"refusing to dump {target.database!r}: the name suggests production. "
            "Rehearse against a development or staging copy; production backups "
            "are the managed provider's, not this script's."
        )
        raise BackupError(msg)


def guard_target(source: Target, target: Target) -> None:
    """Refuse to write anywhere unsafe.

    Three conditions, checked together. The restore drops and recreates its
    target, so each of them is the difference between a rehearsal and an
    incident.
    """
    if PRODUCTION_NAMES.search(target.database):
        msg = f"refusing to restore into {target.database!r}: the name suggests production."
        raise BackupError(msg)

    if target.database == source.database and (target.host, target.port) == (
        source.host,
        source.port,
    ):
        msg = (
            f"refusing to restore {source.database!r} over itself. A restore that "
            "overwrites its own source destroys the evidence of whatever it was "
            "rehearsing for."
        )
        raise BackupError(msg)

    if not REHEARSAL_NAMES.search(target.database):
        msg = (
            f"refusing to restore into {target.database!r}: a rehearsal target must "
            "say so in its name (contain 'restore' or 'rehearsal'), so that "
            "whoever finds it later knows it is disposable."
        )
        raise BackupError(msg)


# --------------------------------------------------------------------------
# Talking to PostgreSQL
# --------------------------------------------------------------------------


def _client(tool: str, target: Target) -> tuple[list[str], dict[str, str]]:
    """The argv and environment for `pg_dump` or `psql`.

    Prefers a local binary and falls back to the compose container, because a
    developer machine normally has PostgreSQL in Docker and no client installed
    — and a rehearsal that requires an unrelated install is a rehearsal nobody
    performs. The container path connects over its own loopback, so the host and
    port are dropped there rather than pointed at the host from inside.
    """
    if shutil.which(tool):
        argv = [tool, "-h", target.host, "-p", str(target.port), "-U", target.user]
        return argv, {**os.environ, "PGPASSWORD": target.password}

    if not shutil.which("docker"):
        msg = (
            f"neither {tool} nor docker is on the PATH. Install the PostgreSQL "
            "client tools, or start the compose stack with `make db-up`."
        )
        raise BackupError(msg)

    argv = [
        "docker",
        "exec",
        "-i",
        "-e",
        f"PGPASSWORD={target.password}",
        DEFAULT_CONTAINER,
        tool,
        "-U",
        target.user,
    ]
    return argv, dict(os.environ)


def _connect(target: Target, *, autocommit: bool = False) -> Any:
    """A psycopg connection. Imported late so the CLI's `--help` needs no driver."""
    import psycopg

    return psycopg.connect(
        host=target.host,
        port=target.port,
        user=target.user,
        password=target.password,
        dbname=target.database,
        autocommit=autocommit,
    )


def _query(target: Target, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
    with _connect(target) as connection, connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


# --------------------------------------------------------------------------
# Dump
# --------------------------------------------------------------------------


def dump(source: Target, path: Path) -> tuple[int, float]:
    """Write a plain-SQL dump of `source` to `path`. Returns bytes and seconds.

    Plain SQL rather than the custom format: it restores with `psql` alone, it
    can be read by a person during an incident, and it diffs. The custom
    format's parallel restore matters at a scale this has not reached and would
    require `pg_restore` to be present as well.
    """
    guard_source(source)
    path.parent.mkdir(parents=True, exist_ok=True)

    argv, env = _client("pg_dump", source)
    argv += [
        "--dbname",
        source.database,
        # Owners and privileges are recreated by migrations and by the roles
        # that already exist on the server. Keeping them in the dump makes the
        # restore fail on any server whose role names differ, which is every
        # server that is not the one it came from.
        "--no-owner",
        "--no-privileges",
    ]

    started = time.perf_counter()
    with path.open("wb") as handle:
        result = subprocess.run(  # noqa: S603 — argv is built here, never from a shell string
            argv, stdout=handle, stderr=subprocess.PIPE, env=env, check=False
        )
    seconds = time.perf_counter() - started

    if result.returncode != 0:
        msg = f"pg_dump failed: {result.stderr.decode(errors='replace').strip()}"
        raise BackupError(msg)

    size = path.stat().st_size
    logger.info("backup.dumped", database=source.database, bytes=size, seconds=round(seconds, 2))
    return size, seconds


def expectation_for(source: Target) -> Expectation:
    """Capture what the source holds, for the copy to be compared against.

    Read after the dump rather than before. Between the two the source may have
    changed, and a mismatch reported against a *later* reading is a mismatch an
    operator can reason about — "three rows arrived while it ran" — whereas an
    earlier reading makes a correct restore look short.
    """
    revision = _query(source, "SELECT version_num FROM alembic_version")
    if not revision:
        msg = f"{source.database!r} has no alembic_version row — it has never been migrated."
        raise BackupError(msg)

    counts = {table: _count(source, table) for table in KEY_TABLES}

    sample = _query(
        source,
        # Ordered so the same row is chosen every time this runs against an
        # unchanged database, which makes a failure reproducible.
        "SELECT id::text, slug, name, region::text FROM tenants ORDER BY id LIMIT 1",
    )
    tenant = (
        {"id": sample[0][0], "slug": sample[0][1], "name": sample[0][2], "region": sample[0][3]}
        if sample
        else None
    )

    return Expectation(revision=str(revision[0][0]), row_counts=counts, sample_tenant=tenant)


def _count(target: Target, table: str) -> int:
    # The table name is interpolated because an identifier cannot be a bound
    # parameter. It comes from KEY_TABLES, a module constant, and never from
    # input — asserted here rather than trusted, since this is the one place in
    # the module a string reaches SQL.
    if table not in KEY_TABLES:
        msg = f"{table!r} is not a key table"
        raise BackupError(msg)
    return int(_query(target, f"SELECT count(*) FROM {table}")[0][0])  # noqa: S608


# --------------------------------------------------------------------------
# Restore
# --------------------------------------------------------------------------


def restore(dump_path: Path, source: Target, target: Target) -> float:
    """Drop, recreate and reload `target` from `dump_path`. Returns seconds.

    The target is recreated rather than emptied, so nothing from a previous
    rehearsal can be mistaken for something the dump brought.
    """
    guard_target(source, target)
    if not dump_path.exists():
        msg = f"no dump at {dump_path}"
        raise BackupError(msg)

    _recreate_database(target)

    argv, env = _client("psql", target)
    argv += [
        "--dbname",
        target.database,
        # Without this psql reports success after skipping every failed
        # statement, which is precisely the false pass this module exists to
        # prevent.
        "-v",
        "ON_ERROR_STOP=1",
        "--quiet",
    ]

    started = time.perf_counter()
    with dump_path.open("rb") as handle:
        result = subprocess.run(  # noqa: S603 — argv is built here, never from a shell string
            argv, stdin=handle, capture_output=True, env=env, check=False
        )
    seconds = time.perf_counter() - started

    if result.returncode != 0:
        msg = f"psql restore failed: {result.stderr.decode(errors='replace').strip()[:2000]}"
        raise BackupError(msg)

    logger.info("backup.restored", database=target.database, seconds=round(seconds, 2))
    return seconds


def _recreate_database(target: Target) -> None:
    """Drop and create the rehearsal database, from the maintenance database.

    `LC_COLLATE=C` matches docker-compose.yml. Ordering differs between
    collations, so a copy created under the host's locale would sort differently
    to the original and any test comparing ordered output would fail for a
    reason nobody would find quickly.
    """
    maintenance = target.named("postgres")
    with _connect(maintenance, autocommit=True) as connection, connection.cursor() as cursor:
        # Sessions left open by a previous rehearsal block the drop. Terminated
        # rather than waited for: this database is disposable by construction.
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (target.database,),
        )
        cursor.execute(f'DROP DATABASE IF EXISTS "{target.database}"')
        cursor.execute(
            f'CREATE DATABASE "{target.database}" '
            "TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
        )


# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------


def verify(target: Target, expectation: Expectation) -> Verification:
    """Ask the restored copy whether it is really the source.

    Every check is collected rather than raised on, so one run tells an operator
    everything that is wrong instead of the first thing.
    """
    checks: list[Check] = []
    checks.append(_check_schema(target, expectation))
    checks.extend(_check_counts(target, expectation))
    checks.append(_check_real_query(target, expectation))
    return Verification(tuple(checks))


def _check_schema(target: Target, expectation: Expectation) -> Check:
    try:
        rows = _query(target, "SELECT version_num FROM alembic_version")
    except Exception as error:
        return Check(
            "alembic revision",
            ok=False,
            detail=f"could not read alembic_version: {type(error).__name__}",
        )

    if not rows:
        return Check("alembic revision", ok=False, detail="alembic_version is empty")

    found = str(rows[0][0])
    return Check(
        "alembic revision",
        ok=found == expectation.revision,
        detail=f"{found} (source {expectation.revision})",
    )


def _check_counts(target: Target, expectation: Expectation) -> list[Check]:
    checks = []
    for table, expected in expectation.row_counts.items():
        try:
            found = _count(target, table)
        except Exception as error:
            checks.append(
                Check(f"rows in {table}", ok=False, detail=f"unreadable: {type(error).__name__}")
            )
            continue
        checks.append(
            Check(
                f"rows in {table}",
                ok=found == expected,
                detail=f"{found} (source {expected})",
            )
        )
    return checks


def _check_real_query(target: Target, expectation: Expectation) -> Check:
    """One row, read back and compared field by field.

    Counts can be right while the contents are wrong — a restore that ran the
    schema and then a truncated data section, or one that loaded yesterday's
    dump. This is the check that reads something.
    """
    if expectation.sample_tenant is None:
        return Check(
            "sample workspace",
            ok=False,
            detail=(
                "the source has no workspaces, so a restore of it proves nothing. "
                "Seed the source (`make seed`) and rehearse again."
            ),
        )

    expected = expectation.sample_tenant
    try:
        rows = _query(
            target,
            "SELECT id::text, slug, name, region::text FROM tenants WHERE id = %s",
            (expected["id"],),
        )
    except Exception as error:
        return Check("sample workspace", ok=False, detail=f"unreadable: {type(error).__name__}")

    if not rows:
        return Check(
            "sample workspace", ok=False, detail="the sampled workspace is not in the restore"
        )

    found = {"id": rows[0][0], "slug": rows[0][1], "name": rows[0][2], "region": rows[0][3]}
    if found != expected:
        # Field names only. The workspace's name is customer data and this
        # output is pasted into tickets.
        differing = sorted(key for key in expected if found.get(key) != expected[key])
        return Check("sample workspace", ok=False, detail=f"fields differ: {differing}")

    return Check("sample workspace", ok=True, detail="round-tripped intact")


# --------------------------------------------------------------------------
# The whole cycle
# --------------------------------------------------------------------------


def rehearse(
    source_url: str,
    *,
    target_database: str = "cairn_restore_rehearsal",
    dump_path: Path | None = None,
    keep_dump: bool = True,
) -> Rehearsal:
    """Dump, restore into a disposable copy, and verify. The one command.

    Returns rather than raises on a failed verification: a rehearsal that found
    a broken backup succeeded at its job, and the caller decides what the exit
    code should be.
    """
    source = Target.from_url(source_url)
    target = source.named(target_database)

    guard_source(source)
    guard_target(source, target)

    path = dump_path or DEFAULT_DUMP_DIR / f"{source.database}-{int(time.time())}.sql"
    size, dump_seconds = dump(source, path)
    expectation = expectation_for(source)
    restore_seconds = restore(path, source, target)
    verification = verify(target, expectation)

    if not keep_dump:
        path.unlink(missing_ok=True)

    return Rehearsal(
        dump_path=path,
        dump_bytes=size,
        dump_seconds=dump_seconds,
        restore_seconds=restore_seconds,
        verification=verification,
        target_database=target_database,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Args:
    command: str = "rehearse"
    source: str = ""
    target: str = "cairn_restore_rehearsal"
    dump: str | None = None
    keep: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


def _default_source() -> str:
    """The local development database unless the environment says otherwise.

    Read from the environment directly rather than through `Settings`, so the
    tool runs without the application's full configuration — during an incident
    it may be the only thing that has to run.
    """
    return os.environ.get(
        "CAIRN_BACKUP_SOURCE_URL",
        os.environ.get(
            "CAIRN_PLATFORM_DATABASE_URL",
            "postgresql://cairn:cairn_local_dev@localhost:5432/cairn",
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m cairn_api.ops.backup",
        description="Dump a CAIRN database, restore it into a disposable copy, and verify it.",
    )
    parser.add_argument(
        "command",
        choices=("dump", "rehearse"),
        nargs="?",
        default="rehearse",
        help="`dump` writes a backup; `rehearse` dumps, restores and verifies.",
    )
    parser.add_argument("--source", default=_default_source(), help="Source database URL.")
    parser.add_argument(
        "--target",
        default="cairn_restore_rehearsal",
        help="Database to restore into. Must contain 'restore' or 'rehearsal'.",
    )
    parser.add_argument("--dump", default=None, help="Path for the dump file.")
    parser.add_argument(
        "--discard-dump",
        action="store_true",
        help="Delete the dump once the rehearsal is done.",
    )
    parsed = parser.parse_args(argv)

    source = Target.from_url(str(parsed.source))
    dump_path = Path(parsed.dump) if parsed.dump else None

    try:
        if parsed.command == "dump":
            path = dump_path or DEFAULT_DUMP_DIR / f"{source.database}-{int(time.time())}.sql"
            size, seconds = dump(source, path)
            print(f"wrote {path} ({size:,} bytes) in {seconds:.1f}s")
            return 0

        result = rehearse(
            str(parsed.source),
            target_database=str(parsed.target),
            dump_path=dump_path,
            keep_dump=not parsed.discard_dump,
        )
    except BackupError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2

    print(f"source        {source.database}")
    print(f"restored into {result.target_database}")
    print(f"dump          {result.dump_path} ({result.dump_bytes:,} bytes)")
    print(f"dump took     {result.dump_seconds:.1f}s")
    print(f"restore took  {result.restore_seconds:.1f}s")
    print("")
    for check in result.verification.checks:
        print(f"  {check}")
    print("")

    if result.ok:
        print("VERIFIED: the restore holds the source's schema and data.")
        return 0

    print(
        f"NOT VERIFIED: {len(result.verification.failures)} check(s) failed. "
        "This backup cannot be relied on.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
