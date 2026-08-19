"""Spend that survives: restarts forget nothing, replicas share one ceiling.

The in-process ledger flagged itself as Stage E debt - every restart reset
every tenant's counters, and two replicas would each have granted a full
ceiling. Locally that hides overruns; hosted it is a billing hole. These tests
are the two sentences that matter, made executable: the restart test (a new
store instance against the same database remembers) and the concurrency test
(N reservations against one ceiling admit exactly ceiling-many, provably,
because the call is counted inside the same lock that checks it).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.config import Settings
from cairn_api.db.session import platform_session
from cairn_api.pipeline.spend import SpendCeilingError
from cairn_api.pipeline.spend_store import (
    InMemorySpendStore,
    PostgresSpendStore,
    build_spend_store,
    current_period_start,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _schema(engine: object) -> None:
    """Migrations run inside the session-scoped engine fixture; a module whose
    tests build their own sessions still needs to request it, or the table
    this file exists to test never comes into being."""
    _ = engine


def store() -> PostgresSpendStore:
    """A fresh instance - "fresh" is the point in the restart tests."""
    return PostgresSpendStore(session_factory=platform_session)


def tenant() -> uuid.UUID:
    """A new tenant id per test: period rows persist deliberately, so tests
    must not share a counter."""
    return uuid.uuid4()


class TestThePeriodBoundary:
    def test_it_is_the_utc_month_computed_in_one_place(self) -> None:
        """The explicit timezone decision, asserted: UTC calendar month,
        tz-aware, first instant. Billing cycles change here and only here."""
        moment = datetime(2026, 8, 19, 23, 59, 59, tzinfo=UTC)
        start = current_period_start(moment)
        assert start == datetime(2026, 8, 1, tzinfo=UTC)
        assert start.tzinfo is not None

    def test_a_local_time_is_normalised_to_utc_first(self) -> None:
        """23:30 on the 31st in UTC+5 is the next month's first day in UTC -
        the boundary follows the system's clock discipline, not the wall."""
        from datetime import timedelta, timezone

        plus_five = timezone(timedelta(hours=5))
        moment = datetime(2026, 9, 1, 3, 0, tzinfo=plus_five)  # 22:00 Aug 31 UTC
        assert current_period_start(moment) == datetime(2026, 8, 1, tzinfo=UTC)


class TestRestartsForgetNothing:
    async def test_a_new_store_instance_remembers_the_period(self) -> None:
        """**The point of the session.** Spend through one instance, then build
        a fresh one - a restart, as far as the process is concerned - and the
        totals are still there."""
        who = tenant()
        first = store()
        for _ in range(3):
            await first.reserve_call(who, stage="extract", max_tokens=None, max_calls=None)
        await first.record_tokens(who, stage="extract", tokens=1_000)

        restarted = store()
        totals = await restarted.totals(who)

        assert totals.calls == 3
        assert totals.tokens == 1_000

    async def test_the_ceiling_remembers_across_the_restart(self) -> None:
        """Spend to the ceiling, restart, and the very next reservation is
        refused - the counter did not reset to a fresh grant."""
        who = tenant()
        first = store()
        for _ in range(2):
            await first.reserve_call(who, stage="extract", max_tokens=None, max_calls=2)

        restarted = store()
        with pytest.raises(SpendCeilingError, match="2 calls made of 2"):
            await restarted.reserve_call(who, stage="extract", max_tokens=None, max_calls=2)

    async def test_the_token_ceiling_is_durable_too(self) -> None:
        """The call ceiling is the backstop; the token ceiling is the bill.
        Both move, or the backstop quietly becomes the only fence."""
        who = tenant()
        first = store()
        await first.reserve_call(who, stage="synthesize", max_tokens=500, max_calls=None)
        await first.record_tokens(who, stage="synthesize", tokens=600)

        restarted = store()
        with pytest.raises(SpendCeilingError, match="600 tokens used of 500"):
            await restarted.reserve_call(who, stage="synthesize", max_tokens=500, max_calls=None)


class TestReplicasShareOneCeiling:
    async def test_concurrent_reservations_admit_exactly_the_ceiling(self) -> None:
        """Two "replicas" (independent store instances), ten concurrent
        reservations, a ceiling of five: exactly five succeed. Provable, not
        probable - the per-tenant advisory lock counts the call in the same
        transaction that checks it, so the sixth observes five and refuses."""
        who = tenant()
        replica_a, replica_b = store(), store()

        async def attempt(replica: PostgresSpendStore) -> bool:
            try:
                await replica.reserve_call(who, stage="extract", max_tokens=None, max_calls=5)
            except SpendCeilingError:
                return False
            return True

        outcomes = await asyncio.gather(
            *(attempt(replica_a if index % 2 == 0 else replica_b) for index in range(10))
        )

        assert sum(outcomes) == 5, f"the replicas jointly over-granted: {outcomes}"
        assert (await store().totals(who)).calls == 5

    async def test_stage_attribution_survives_into_the_durable_rows(self) -> None:
        who = tenant()
        durable = store()
        await durable.reserve_call(who, stage="classify", max_tokens=None, max_calls=None)
        await durable.reserve_call(who, stage="extract", max_tokens=None, max_calls=None)
        await durable.record_tokens(who, stage="extract", tokens=250)

        totals = await durable.totals(who)
        assert totals.calls == 2
        assert totals.tokens == 250


class TestTheBackendChoiceMirrorsTheQueue:
    def test_a_deployed_environment_refuses_the_in_memory_store(self) -> None:
        """Same wording, same shape as the queue factory: memory in a deployed
        environment re-creates the exact defect the durable store fixes."""
        from test_release_gates import deployed

        settings = deployed(spend_backend="memory", queue_backend="postgres")
        with pytest.raises(RuntimeError, match="CAIRN_SPEND_BACKEND=postgres"):
            build_spend_store(settings)

    def test_memory_is_allowed_locally(self) -> None:
        settings = Settings(environment="local", spend_backend="memory")
        assert isinstance(build_spend_store(settings), InMemorySpendStore)

    def test_postgres_is_the_default(self) -> None:
        settings = Settings(environment="local")
        assert isinstance(build_spend_store(settings), PostgresSpendStore)

    async def test_the_in_memory_store_enforces_the_same_semantics(self) -> None:
        """Unit tests run against this one; it must refuse identically."""
        who = tenant()
        memory = InMemorySpendStore()
        await memory.reserve_call(who, stage="extract", max_tokens=None, max_calls=1)
        with pytest.raises(SpendCeilingError, match="1 calls made of 1"):
            await memory.reserve_call(who, stage="extract", max_tokens=None, max_calls=1)


class TestTheProviderPathUsesTheStore:
    """Refusal semantics unchanged, memory added: the same SpendCeilingError,
    pre-dispatch, with the durable counter doing the remembering."""

    async def test_a_stored_ceiling_refuses_before_the_model_is_called(self) -> None:
        from cairn_api.pipeline.provider import ScriptedProvider
        from cairn_api.pipeline.spend import BudgetedProvider, TokenLedger
        from cairn_api.pipeline.spend_store import InMemorySpendStore

        who = tenant()
        memory = InMemorySpendStore()
        inner = ScriptedProvider(default='{"class": "substantive"}')
        provider = BudgetedProvider(
            inner=inner,
            ledger=TokenLedger(tenant=str(who), max_tokens=None, max_calls=2),
            store=memory,
            tenant_id=who,
        ).for_stage("classify")

        from cairn_api.pipeline.prompts import build

        request = build("Classify the activity", "data")
        await provider.complete(request)
        await provider.complete(request)

        calls_before = len(inner.calls)
        with pytest.raises(SpendCeilingError):
            await provider.complete(request)
        assert len(inner.calls) == calls_before, "the refused call reached the model"

        # And the memory is the store's, not the ledger's: a fresh ledger (a
        # new unit of work, a restarted process) is still refused.
        fresh = BudgetedProvider(
            inner=inner,
            ledger=TokenLedger(tenant=str(who), max_tokens=None, max_calls=2),
            store=memory,
            tenant_id=who,
        ).for_stage("classify")
        with pytest.raises(SpendCeilingError):
            await fresh.complete(request)
