"""The durable half of the spend ceiling: counters that survive restarts.

`pipeline/spend.py`'s `TokenLedger` stays exactly what it was — one unit of
work's view, carrying per-job stage attribution, the once-per-job warning
claims, and the numbers `understand.applied` logs. What it never was is a
memory: every restart reset every tenant to zero, and two replicas would each
have granted a full ceiling. This module is the memory. The ledger reports;
the store remembers and refuses.

**The atomic counter, chosen over a flush window.** Each model call costs one
short transaction here: an advisory lock on the tenant, a SUM over its period
rows, and an upsert. The honest cost: a database round-trip per model call —
bounded and small, because the live sessions measured 2-4 model calls per
understood event at 300ms-30s of model latency each, so a sub-millisecond
statement is noise on the path it guards. The flush window's honest cost was
the reason it lost: a crash inside the window over-grants by everything the
window held, and "cannot over-grant" is worth more than the millisecond.

**What the atomic reservation guarantees, and what it does not.** The *call*
ceiling cannot be jointly exceeded by any number of replicas: the call is
counted inside the same lock that checks it, so the N+1th concurrent reservation
observes N and refuses — provable, and proven by the concurrency test. The
*token* ceiling is checked pre-dispatch but a call's cost is unknowable until
it returns, so token overshoot is bounded by the calls in flight at the moment
the ceiling is crossed — the same one-call overshoot the in-process ledger
always had, now multiplied by concurrency rather than by replicas-times-restarts.

**The period is the UTC calendar month, computed in exactly one place.** UTC
because every timestamp in this system is UTC and a tenant-local billing month
would need a per-tenant timezone nobody has declared; calendar month because
that is what an invoice and an operator's mental model share. When billing
grows a real cycle, `current_period_start` is the one function to change.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

import structlog
from sqlalchemy import text

from cairn_api.config import Settings, get_settings
from cairn_api.pipeline.spend import SpendCeilingError

logger = structlog.get_logger(__name__)

#: Advisory-lock namespace for per-tenant spend serialisation. Distinct from
#: the audit chain's key; collisions between namespaces would serialise
#: unrelated writes.
_SPEND_LOCK_NAMESPACE = 741_902_336


def current_period_start(now: datetime | None = None) -> datetime:
    """The first instant of the current UTC calendar month.

    The single source of the period boundary — the migration, the store, and
    the operations read all point here. See the module docstring for the
    timezone decision.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    return moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True, slots=True)
class PeriodTotals:
    """One tenant's spend so far this period, after a reservation."""

    calls: int
    tokens: int


class SpendStore(Protocol):
    """Durable spend counters. Implementations must make `reserve_call` atomic:
    the call is counted in the same operation that checks the ceiling."""

    async def reserve_call(
        self,
        tenant_id: uuid.UUID,
        *,
        stage: str,
        max_tokens: int | None,
        max_calls: int | None,
    ) -> PeriodTotals: ...

    async def record_tokens(self, tenant_id: uuid.UUID, *, stage: str, tokens: int) -> None: ...

    async def totals(self, tenant_id: uuid.UUID) -> PeriodTotals: ...


class InMemorySpendStore:
    """Counters in a dict: local development and unit tests only.

    Carries exactly the defect the Postgres store fixes — nothing survives the
    process — which is why `build_spend_store` refuses it when deployed, in the
    same breath the queue factory uses.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[uuid.UUID, datetime, str], list[int]] = {}

    def _period_rows(self, tenant_id: uuid.UUID) -> list[list[int]]:
        period = current_period_start()
        return [
            counters
            for (row_tenant, row_period, _), counters in self._rows.items()
            if row_tenant == tenant_id and row_period == period
        ]

    async def reserve_call(
        self,
        tenant_id: uuid.UUID,
        *,
        stage: str,
        max_tokens: int | None,
        max_calls: int | None,
    ) -> PeriodTotals:
        with self._lock:
            calls = sum(row[0] for row in self._period_rows(tenant_id))
            tokens = sum(row[1] for row in self._period_rows(tenant_id))
            if max_calls is not None and calls >= max_calls:
                raise SpendCeilingError(
                    str(tenant_id), f"{calls} calls made of {max_calls} permitted this period"
                )
            if max_tokens is not None and tokens >= max_tokens:
                raise SpendCeilingError(
                    str(tenant_id),
                    f"{tokens} tokens used of {max_tokens} permitted this period",
                )
            key = (tenant_id, current_period_start(), stage)
            row = self._rows.setdefault(key, [0, 0])
            row[0] += 1
            return PeriodTotals(calls=calls + 1, tokens=tokens)

    async def record_tokens(self, tenant_id: uuid.UUID, *, stage: str, tokens: int) -> None:
        with self._lock:
            key = (tenant_id, current_period_start(), stage)
            row = self._rows.setdefault(key, [0, 0])
            row[1] += tokens

    async def totals(self, tenant_id: uuid.UUID) -> PeriodTotals:
        with self._lock:
            rows = self._period_rows(tenant_id)
            return PeriodTotals(
                calls=sum(row[0] for row in rows), tokens=sum(row[1] for row in rows)
            )


@dataclass
class PostgresSpendStore:
    """The cluster-wide truth, in the same database every worker shares.

    Sessions come from a factory so this store works from the worker's platform
    session context and from a tenant-scoped request alike; every statement
    carries the tenant explicitly, and RLS holds regardless.
    """

    session_factory: object

    #: Cached last-seen totals per tenant, for cheap ratio reads between calls.
    #: Never used for the ceiling decision — that is the reservation's job.
    _last_seen: dict[uuid.UUID, PeriodTotals] = field(default_factory=dict)

    async def reserve_call(
        self,
        tenant_id: uuid.UUID,
        *,
        stage: str,
        max_tokens: int | None,
        max_calls: int | None,
    ) -> PeriodTotals:
        period = current_period_start()
        async with self.session_factory() as session:  # type: ignore[operator]
            # Serialise per tenant, not globally: the advisory lock makes the
            # SUM-then-upsert atomic against every other replica reserving for
            # the same tenant, which is what turns "cannot jointly exceed" from
            # probable into provable. Transaction-scoped, so it releases on
            # commit or rollback with no unlock path to forget.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:ns, hashtext(:tenant))"),
                {"ns": _SPEND_LOCK_NAMESPACE, "tenant": str(tenant_id)},
            )
            row = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(calls), 0), COALESCE(SUM(tokens), 0) "
                        "FROM spend_counters "
                        "WHERE tenant_id = :tenant AND period_start = :period"
                    ),
                    {"tenant": tenant_id, "period": period},
                )
            ).one()
            calls, tokens = int(row[0]), int(row[1])

            if max_calls is not None and calls >= max_calls:
                raise SpendCeilingError(
                    str(tenant_id), f"{calls} calls made of {max_calls} permitted this period"
                )
            if max_tokens is not None and tokens >= max_tokens:
                raise SpendCeilingError(
                    str(tenant_id),
                    f"{tokens} tokens used of {max_tokens} permitted this period",
                )

            await session.execute(
                text(
                    "INSERT INTO spend_counters (tenant_id, period_start, stage, calls) "
                    "VALUES (:tenant, :period, :stage, 1) "
                    "ON CONFLICT (tenant_id, period_start, stage) DO UPDATE "
                    "SET calls = spend_counters.calls + 1, updated_at = now()"
                ),
                {"tenant": tenant_id, "period": period, "stage": stage},
            )
            await session.commit()

        totals = PeriodTotals(calls=calls + 1, tokens=tokens)
        self._last_seen[tenant_id] = totals
        return totals

    async def record_tokens(self, tenant_id: uuid.UUID, *, stage: str, tokens: int) -> None:
        if tokens <= 0:
            return
        period = current_period_start()
        async with self.session_factory() as session:  # type: ignore[operator]
            await session.execute(
                text(
                    "INSERT INTO spend_counters (tenant_id, period_start, stage, tokens) "
                    "VALUES (:tenant, :period, :stage, :tokens) "
                    "ON CONFLICT (tenant_id, period_start, stage) DO UPDATE "
                    "SET tokens = spend_counters.tokens + :tokens, updated_at = now()"
                ),
                {"tenant": tenant_id, "period": period, "stage": stage, "tokens": tokens},
            )
            await session.commit()

    async def totals(self, tenant_id: uuid.UUID) -> PeriodTotals:
        period = current_period_start()
        async with self.session_factory() as session:  # type: ignore[operator]
            row = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(calls), 0), COALESCE(SUM(tokens), 0) "
                        "FROM spend_counters "
                        "WHERE tenant_id = :tenant AND period_start = :period"
                    ),
                    {"tenant": tenant_id, "period": period},
                )
            ).one()
        return PeriodTotals(calls=int(row[0]), tokens=int(row[1]))


@lru_cache(maxsize=1)
def process_spend_store() -> SpendStore:
    """The process's store, built once - the `build_providers` shape, and for
    the same reason: cached and therefore parameterless, with the selection
    itself in `build_spend_store` where a test can exercise every branch."""
    return build_spend_store(get_settings())


def build_spend_store(settings: Settings | None = None) -> SpendStore:
    """The deployment's spend store - the queue factory's shape, on purpose.

    'memory' is for local development and unit tests only: it holds counters in
    RAM and loses them on restart, silently - which is the exact defect the
    durable store exists to fix, so a deployed environment refuses to start on
    it rather than run with a ceiling that forgets.
    """
    resolved = settings or get_settings()

    if resolved.spend_backend == "memory":
        if resolved.is_deployed:
            msg = (
                "spend_backend is 'memory' but CAIRN_ENVIRONMENT is "
                f"'{resolved.environment}'. The in-memory spend store holds "
                "counters in RAM: every restart resets every tenant's ceiling "
                "and each replica grants a full one. Set "
                "CAIRN_SPEND_BACKEND=postgres."
            )
            raise RuntimeError(msg)
        logger.info("spend.using_in_memory_store", environment=resolved.environment)
        return InMemorySpendStore()

    from cairn_api.db.session import platform_session

    logger.info("spend.using_postgres_store", environment=resolved.environment)
    return PostgresSpendStore(session_factory=platform_session)
