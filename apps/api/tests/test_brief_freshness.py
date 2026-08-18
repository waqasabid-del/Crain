"""Why the daily brief kept serving last week.

Three layers were suspected; the evidence convicted two.

**The archive-first path (convicted).** `is_complete(end)` is `end <= now`, and
the endpoint defaults `end` to `now` — so the *current* period was "complete" by
definition on every default request. Each read generated, stored a new "record"
(206 junk archive rows accumulated in one workspace), and reported
`stored: true` for a brief the docstring promises is live. The off-by-one is not
the fix; the semantics are: a period is a record only when the caller *named* a
finished boundary. A default request is by construction about the present.

**The window (acquitted).** Boundaries computed correctly, every fact dated,
live facts inside. Quoted at diagnosis: window 2026-08-11 → 2026-08-18, live
commits dated 2026-08-18, all within.

**Ranking (convicted).** Entry points are nearest-by-cosine to one generic
question, limit 8, and expansion only walks from them. The ranked list for a
real generation was eight seed-week facts and zero of the twenty-two live
commits sitting inside the same window — seed facts written in
"delivered/decided/blocked" vocabulary occupy the entry points forever, and
recency never gets a vote. Retrieval exists for *questions*; a brief is a *time
slice*, and conflating the paths is the defect, so they are separated rather
than reweighted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.api import briefs
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource as FactSourceRow
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.pipeline.retrieval import retrieve_window
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class TestOnlyANamedBoundaryIsARecord:
    """`stored: true` on a live brief was the lie that hid everything else."""

    def test_a_default_request_is_never_a_finished_period(self) -> None:
        """The caller asked about the present; the present is not an archive."""
        assert briefs.is_record(until=None, now=NOW) is False

    def test_an_explicit_past_boundary_is_a_record(self) -> None:
        assert briefs.is_record(until=NOW - timedelta(days=1), now=NOW) is True

    def test_an_explicit_boundary_still_in_progress_is_not(self) -> None:
        """Asking for a period that has not ended yet is asking about the
        present, however explicit the boundary."""
        assert briefs.is_record(until=NOW + timedelta(hours=2), now=NOW) is False

    def test_a_boundary_of_exactly_now_counts_as_finished(self) -> None:
        """The instant a period ends, its brief may become the record — the
        old `<=` was right about this half; it was the default that lied."""
        assert briefs.is_record(until=NOW, now=NOW) is True


class TestABriefIsATimeSliceNotAQuestion:
    """`retrieve_window`: the brief's candidate set, recency-bounded first."""

    @staticmethod
    async def _seed(platform: AsyncSession, count: int, *, spread_days: int = 10) -> uuid.UUID:
        tenant = Tenant(name="Fresh", slug=f"fresh-{uuid.uuid4().hex[:10]}")
        platform.add(tenant)
        await platform.commit()
        async with tenant_session(tenant.id) as session:
            for index in range(count):
                fact = FactRow(
                    tenant_id=tenant.id,
                    kind="delivery",
                    statement=f"Delivered change number {index}.",
                    certainty="verified",
                    occurred_at=NOW - timedelta(days=spread_days) + timedelta(hours=index * 2),
                    valid_from=NOW - timedelta(days=spread_days),
                )
                session.add(fact)
                await session.flush()
                session.add(
                    FactSourceRow(
                        tenant_id=tenant.id,
                        fact_id=fact.id,
                        evidence_id=f"github:commit:{index:040x}",
                        source="github",
                    )
                )
            await session.commit()
        return tenant.id

    async def test_the_newest_facts_in_the_window_survive_the_cap(
        self, platform: AsyncSession
    ) -> None:
        """**The conviction, inverted.** When candidates exceed the budget, the
        ones dropped must be the *oldest*, never the least similar to a
        question nobody asked."""
        tenant_id = await self._seed(platform, 30)

        async with tenant_session(tenant_id) as session:
            result = await retrieve_window(
                session,
                tenant_id=tenant_id,
                since=NOW - timedelta(days=30),
                until=NOW,
                limit=10,
            )

        statements = [item.fact.statement for item in result.for_context()]
        assert len(statements) == 10
        # The newest ten are numbers 20..29; number 0..19 are the sacrifice.
        surviving = {int(s.split()[-1].rstrip(".")) for s in statements}
        assert surviving == set(range(20, 30)), f"recency did not decide survival: {surviving}"
        assert result.truncated is True

    async def test_survivors_are_ordered_chronologically_for_the_prompt(
        self, platform: AsyncSession
    ) -> None:
        """Oldest first, newest nearest the request — the narrative reads in
        order and attention lands on the freshest work (md/09 §4.3)."""
        tenant_id = await self._seed(platform, 6)

        async with tenant_session(tenant_id) as session:
            result = await retrieve_window(
                session, tenant_id=tenant_id, since=NOW - timedelta(days=30), until=NOW, limit=10
            )

        occurred = [item.fact.occurred_at for item in result.for_context()]
        assert occurred == sorted(o for o in occurred if o is not None)
        assert result.truncated is False

    async def test_facts_outside_the_window_are_not_candidates(
        self, platform: AsyncSession
    ) -> None:
        tenant_id = await self._seed(platform, 5, spread_days=60)

        async with tenant_session(tenant_id) as session:
            result = await retrieve_window(
                session, tenant_id=tenant_id, since=NOW - timedelta(days=7), until=NOW, limit=10
            )

        assert result.for_context() == []

    async def test_superseded_facts_stay_excluded(self, platform: AsyncSession) -> None:
        """The gate that must stay byte-identical, exercised on the new path."""
        tenant_id = await self._seed(platform, 3)
        async with tenant_session(tenant_id) as session:
            from sqlalchemy import select

            rows = list(await session.scalars(select(FactRow).limit(2)))
            fact, newer = rows
            # Supersession must be complete: the schema refuses a fact ended
            # without a successor named, which is the gate working.
            fact.valid_until = NOW - timedelta(days=1)
            fact.superseded_by_id = newer.id
            superseded_id = fact.id
            await session.commit()

        async with tenant_session(tenant_id) as session:
            result = await retrieve_window(
                session, tenant_id=tenant_id, since=NOW - timedelta(days=30), until=NOW, limit=10
            )

        assert superseded_id not in {item.fact.id for item in result.for_context()}
