"""Mirroring the audit chain into a second trust domain.

`internal/audit.py` makes the record tamper-evident inside one database; this
module makes erasure detectable across two. Every entry is shipped,
byte-faithful, to a separate PostgreSQL instance whose credentials the primary
database's owner does not hold, and whose one application role can INSERT and
SELECT and nothing else — the sink's entire schema is
`infra/audit-sink-init.sql`, short enough to audit by reading.

**The primary write never waits.** A staff action's audit entry commits to the
primary chain exactly as before; shipping runs later, on the worker's
maintenance loop. The cursor is the chain's own ``sequence``, read as
``MAX(sequence)`` *from the sink* — no outbox table, because an outbox would
duplicate what the sequence already provides (a total order, durability) while
adding the one failure the sink-side cursor cannot have: a cursor that ran
ahead of what actually landed. A batch either commits to the sink whole or the
cursor does not move.

**Byte-faithful, deliberately.** Rows go across with the same id, sequence,
hashes and payload, so cross-verification is pure comparison and any
transformation en route would be a place for a bug — or an editor — to hide.

**Failure honesty.** A down sink delays mirroring and never blocks, fails, or
degrades the audited action; the lag (highest primary vs highest shipped) is
logged and counted every pass. Unconfigured, everything behaves as before this
module existed, and the release gate stays red — there is no silent mode that
looks configured.

No log line here carries an action, a reason, or a detail payload — sequences
and counts only, the same discipline as the rest of the audit surface.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from opentelemetry import metrics
from sqlalchemy import BigInteger, Column, MetaData, Table, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.types import DateTime, String

from cairn_api.config import Settings, get_settings
from cairn_api.db.staff_models import InternalAuditEntry

logger = structlog.get_logger(__name__)

meter = metrics.get_meter("cairn.audit")

#: How far the mirror is behind the primary, in entries. Zero is the healthy
#: steady state; a persistently rising value is a down sink being honest.
sink_lag = meter.create_gauge(
    "cairn.audit.sink_lag_entries",
    description="Audit entries committed to the primary chain and not yet mirrored",
)

#: Entries shipped per maintenance pass. Bounded so a first run against a long
#: chain drains steadily rather than in one giant transaction.
SHIP_BATCH = 500

_metadata = MetaData()

#: The mirror table, declared here rather than in `db/` models: it lives in a
#: different database with a different lifecycle, and giving it a model beside
#: the primary's would invite a join that can never exist.
mirror_table = Table(
    "internal_audit_mirror",
    _metadata,
    Column("id", PG_UUID(as_uuid=True), primary_key=True),
    Column("sequence", BigInteger, nullable=False, unique=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("actor_user_id", PG_UUID(as_uuid=True), nullable=False),
    Column("action", String(64), nullable=False),
    Column("tenant_id", PG_UUID(as_uuid=True), nullable=True),
    Column("reason", String(500), nullable=False),
    Column("detail", JSONB, nullable=False),
    Column("previous_hash", String(64), nullable=False),
    Column("entry_hash", String(64), nullable=False),
)

_engine: AsyncEngine | None = None
_engine_url: str | None = None


def configured(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).audit_sink_url is not None


def sink_engine(settings: Settings | None = None) -> AsyncEngine:
    """The sink's engine, created once per DSN.

    A separate engine on a separate DSN is the entire point: the primary's
    credentials must not work here, and `config.py` refuses a sink URL that
    matches either primary connection, so pointing this at the same database
    cannot be configured quietly.
    """
    global _engine, _engine_url
    resolved = settings or get_settings()
    url = str(resolved.audit_sink_url)
    if _engine is None or _engine_url != url:
        _engine = create_async_engine(url, pool_size=2, max_overflow=0)
        _engine_url = url
    return _engine


@dataclass(frozen=True, slots=True)
class ShipOutcome:
    """One pass, in counts."""

    shipped: int = 0
    highest_primary: int = 0
    highest_shipped: int = 0
    failed: bool = False

    @property
    def lag(self) -> int:
        return max(0, self.highest_primary - self.highest_shipped)


async def ship_pending(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    limit: int = SHIP_BATCH,
) -> ShipOutcome:
    """Mirror every primary entry the sink does not yet hold, oldest first.

    `session` is the primary platform session, read-only here. The sink write
    is one transaction per pass: it commits whole or the cursor — the sink's
    own MAX(sequence) — does not move, so a crash mid-batch re-ships rows the
    unique constraint then refuses, and nothing is ever skipped past.
    """
    resolved = settings or get_settings()
    highest_primary = (await session.scalar(select(func.max(InternalAuditEntry.sequence)))) or 0

    if not configured(resolved):
        # Unconfigured is not an error and not a warning on every pass — the
        # release gate is what says this loudly, once, in the right place.
        return ShipOutcome(highest_primary=highest_primary)

    try:
        engine = sink_engine(resolved)
        async with engine.begin() as sink:
            cursor = (await sink.scalar(select(func.max(mirror_table.c.sequence)))) or 0

            entries = list(
                await session.scalars(
                    select(InternalAuditEntry)
                    .where(InternalAuditEntry.sequence > cursor)
                    .order_by(InternalAuditEntry.sequence)
                    .limit(limit)
                )
            )
            for entry in entries:
                await sink.execute(
                    mirror_table.insert().values(
                        id=entry.id,
                        sequence=entry.sequence,
                        occurred_at=entry.occurred_at,
                        actor_user_id=entry.actor_user_id,
                        action=entry.action,
                        tenant_id=entry.tenant_id,
                        reason=entry.reason,
                        detail=entry.detail,
                        previous_hash=entry.previous_hash,
                        entry_hash=entry.entry_hash,
                    )
                )
            highest_shipped = entries[-1].sequence if entries else cursor
    except Exception as exc:
        # The retry is the next maintenance pass — the cursor lives in the sink,
        # so a failed pass moves nothing and skips nothing. Category only: an
        # exception string from a database driver can carry a DSN.
        await logger.awarning("audit_sink.ship_failed", error=type(exc).__name__)
        outcome = ShipOutcome(highest_primary=highest_primary, failed=True)
        sink_lag.set(outcome.lag)
        return outcome

    outcome = ShipOutcome(
        shipped=len(entries),
        highest_primary=highest_primary,
        highest_shipped=highest_shipped,
    )
    sink_lag.set(outcome.lag)
    if outcome.shipped or outcome.lag:
        await logger.ainfo(
            "audit_sink.shipped",
            shipped=outcome.shipped,
            highest_primary=outcome.highest_primary,
            highest_shipped=outcome.highest_shipped,
            lag=outcome.lag,
        )
    return outcome


@dataclass(frozen=True, slots=True)
class SinkVerification:
    """The two chains, compared entry by entry.

    Three findings are possible, and they mean different things:

    - ``sink_gap``: the primary holds a sequence the sink does not. Shipping
      lag if it is at the tail, loss if it is not — the lag number says which.
    - ``mismatch``: both hold the sequence with different content. One side was
      altered, and the hashes say nothing about which — that is what having
      two trust domains is *for*: the investigation now has two records to
      weigh instead of one to believe.
    - ``primary_missing``: the sink holds a sequence the primary does not.
      The gravest shape — the primary's history has been truncated or edited
      away, and the sink is the surviving witness.
    """

    primary_entries: int
    sink_entries: int
    primary_intact: bool
    intact: bool
    broken_at: int | None = None
    reason: str | None = None


async def verify_against_sink(
    session: AsyncSession, *, settings: Settings | None = None
) -> SinkVerification:
    """The primary's internal check, then divergence against the mirror.

    Names the first sequence where the two disagree and which shape the
    disagreement takes, exactly as `audit.verify` distinguishes edited from
    removed. Divergence is a security finding, not an operational hiccup.
    """
    from cairn_api.internal.audit import compute_hash, verify

    internal = await verify(session)

    primary_rows = {
        entry.sequence: entry.entry_hash
        for entry in await session.scalars(
            select(InternalAuditEntry).order_by(InternalAuditEntry.sequence)
        )
    }

    # The hash is RECOMPUTED over the sink's own bytes, never read from its
    # hash column. The live proof caught the difference: an owner who edited
    # the mirror's content while leaving `entry_hash` untouched verified clean
    # against a column-to-column comparison. The stored hash is a claim, and
    # this is where claims get checked.
    engine = sink_engine(settings)
    async with engine.connect() as sink:
        fetched = await sink.execute(select(mirror_table).order_by(mirror_table.c.sequence))
        sink_rows = {}
        sink_claimed = {}
        for row in fetched:
            sink_claimed[row.sequence] = row.entry_hash
            sink_rows[row.sequence] = compute_hash(
                previous_hash=row.previous_hash,
                occurred_at=row.occurred_at,
                actor_user_id=row.actor_user_id,
                action=row.action,
                tenant_id=row.tenant_id,
                reason=row.reason,
                detail=row.detail,
            )

    primary_entries = len(primary_rows)
    sink_entries = len(sink_rows)

    def result(
        *, intact: bool, broken_at: int | None = None, reason: str | None = None
    ) -> SinkVerification:
        return SinkVerification(
            primary_entries=primary_entries,
            sink_entries=sink_entries,
            primary_intact=internal.intact,
            intact=intact,
            broken_at=broken_at,
            reason=reason,
        )

    if not internal.intact:
        return result(
            intact=False,
            broken_at=internal.broken_at,
            reason=f"primary chain: {internal.reason}",
        )

    for sequence in sorted(primary_rows.keys() | sink_rows.keys()):
        in_primary = sequence in primary_rows
        in_sink = sequence in sink_rows
        if in_primary and not in_sink:
            return result(
                intact=False,
                broken_at=sequence,
                reason=(
                    "sink_gap: the primary holds this sequence and the sink does "
                    "not - shipping lag if at the tail, loss if not"
                ),
            )
        if in_sink and not in_primary:
            return result(
                intact=False,
                broken_at=sequence,
                reason=(
                    "primary_missing: the sink holds this sequence and the "
                    "primary does not - the primary's history was truncated or "
                    "edited away, and the sink is the surviving witness"
                ),
            )
        if primary_rows[sequence] != sink_rows[sequence]:
            return result(
                intact=False,
                broken_at=sequence,
                reason=(
                    "mismatch: both chains hold this sequence with different "
                    "content - one side was altered"
                ),
            )
        if sink_claimed[sequence] != sink_rows[sequence]:
            # Content matches the primary, but the mirror's own hash column
            # does not match its content: somebody edited the mirror's hash.
            # The record is still recoverable; the tampering is still named.
            return result(
                intact=False,
                broken_at=sequence,
                reason=(
                    "mismatch: the sink row's stored hash disagrees with its "
                    "own content - the mirror's hash column was edited"
                ),
            )

    return result(intact=True)


async def _main() -> int:
    """The round trip an operator closes the gate with: ship, then verify."""
    import sys

    from cairn_api.db.session import platform_session

    if not configured():
        print("CAIRN_AUDIT_SINK_URL is not set. Nothing to verify against.", file=sys.stderr)
        return 2

    async with platform_session() as session:
        outcome = await ship_pending(session)
        print(
            f"shipped={outcome.shipped} highest_primary={outcome.highest_primary} "
            f"highest_shipped={outcome.highest_shipped} lag={outcome.lag}"
        )
        if outcome.failed:
            print("FAILED: the sink was unreachable. Nothing was lost; retry.", file=sys.stderr)
            return 1

        verification = await verify_against_sink(session)
        print(
            f"primary_entries={verification.primary_entries} "
            f"sink_entries={verification.sink_entries} "
            f"primary_intact={verification.primary_intact}"
        )
        if verification.intact:
            print("INTACT: both chains agree, entry for entry.")
            return 0
        print(
            f"DIVERGED at sequence {verification.broken_at}: {verification.reason}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    import asyncio
    import sys

    sys.exit(asyncio.run(_main()))
