"""Complexity, asserted as a property rather than measured as a duration.

Two audit findings came from the same blind spot: the pipeline was correct and
did not scale, and nothing in the suite could tell the difference. `graph.build`
compared every currently-valid fact against every other, and `store.apply`
loaded the whole workspace and walked it once per incoming fact. Both passed
every test in the suite, because every other test uses four facts.

**These tests count operations, not seconds.** A wall-clock assertion on shared
CI hardware fails when a neighbouring job is noisy, and a test that fails for
reasons unrelated to the change is a defect in the suite — it trains everyone to
re-run rather than to read. Counts are deterministic: the number of subject
comparisons a build performs, and the number of similarity computations
resolution performs, are functions of the data alone.

**The shape of the assertion is a doubling.** Absolute thresholds encode today's
constants and have to be re-tuned whenever anything changes. Doubling the
workspace and asserting the work does not quadruple tests the *exponent*, which
is the thing that was actually wrong. A quadratic implementation multiplies its
work by four across the doubling and cannot pass; a linear one multiplies by
about two.

**The corpus grows in projects, not in density.** Facts about one project share
a subject; the number of facts per project is held constant as the workspace
doubles, because that is how a workspace actually grows — more things happening,
not an ever-denser single thing. Doubling the density instead would make
quadratic output the *correct* answer and the test meaningless.

Two loose wall-clock bounds survive, and they are smoke tests rather than
benchmarks: they exist to fail if a regression reintroduces something so slow
that the pipeline cannot finish, and they are set an order of magnitude above
the real figure so that a busy runner never trips them.

Marked `slow` as well as `integration` so the fast gate can exclude it with
`-m "not slow"` — the markers registered in `pyproject.toml`, the same pair
`test_migrations.py` uses.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.domain import Certainty
from cairn_api.pipeline import graph, resolve, store
from cairn_api.pipeline.embeddings import HashingEmbedder
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.integration, pytest.mark.slow]

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)

#: Facts in the smaller of the two workspaces. The larger is twice this.
#:
#: Big enough that a quadratic implementation is unmistakable — 600 facts is
#: 180,000 pairs — and small enough that seeding stays a few seconds. The
#: assertions are ratios between the two sizes, so neither number is
#: load-bearing on its own.
CORPUS = 600

#: Facts sharing one project, and therefore one subject neighbourhood.
#:
#: Held constant while the corpus doubles: the workspace acquires more projects,
#: not a denser one. This is the number an incremental build's cost should
#: depend on, and the whole point of the assertions below is that it is.
FACTS_PER_PROJECT = 20

#: Facts extracted from one artefact. Well under `MAX_GROUP_FANOUT`, so the
#: ordinary corpus never trips the ceiling — that path has its own test.
FACTS_PER_ARTEFACT = 20


def statements(count: int) -> Iterator[tuple[int, str]]:
    """A corpus with a bounded, realistic subject neighbourhood.

    Each fact carries two project tokens and one unique one, and nothing else
    that survives `subject_key` — the filler is all stopwords. That matters:
    a template where every fact shares a filler word would put that word in
    every posting list, and the test would end up measuring
    `MAX_SUBJECT_POSTINGS` rather than the inverted index it is aimed at.
    """
    projects = max(1, count // FACTS_PER_PROJECT)
    for index in range(count):
        project = index % projects
        yield index, f"Shipped atlas{project} c{index} to atlas{project}-billing."


async def seed_corpus(session: AsyncSession, tenant_id: uuid.UUID, count: int) -> None:
    """Insert facts directly, bypassing resolution.

    `store.apply` is the subject of half these tests; using it to build their
    fixture would fold the cost being measured into the setup, and would take
    minutes. The rows it writes are the same rows.

    Spaced a day apart rather than an hour, so that `MERGE_WINDOW` selects a
    handful of neighbours rather than most of the corpus — otherwise the
    candidate query would look narrow for a reason that has nothing to do with
    the workspace growing.
    """
    facts = []
    sources = []
    for index, statement in statements(count):
        fact_id = uuid.uuid4()
        occurred = MONDAY + timedelta(days=index)
        facts.append(
            {
                "id": fact_id,
                "tenant_id": tenant_id,
                "kind": FactKind.DELIVERY.value,
                "statement": statement,
                "certainty": "verified",
                "origin": "extracted",
                "occurred_at": occurred,
                "valid_from": occurred,
            }
        )
        sources.append(
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "fact_id": fact_id,
                "source": "github",
                "evidence_id": f"ev-{index // FACTS_PER_ARTEFACT}",
            }
        )

    await session.execute(insert(FactRow), facts)
    await session.execute(insert(FactSource), sources)
    await session.flush()


@pytest.fixture
async def workspaces(platform: AsyncSession) -> dict[int, uuid.UUID]:
    """Two fresh workspaces, one twice the size of the other.

    Function-scoped, and each test gets brand-new tenants. A module-scoped
    corpus would seed once rather than once per test, and was tried — but
    `tenant_session` commits on a clean exit, so the tests would share written
    state and an incremental-build assertion would quietly become a test of the
    running order. Re-seeding is a bulk insert; a suite whose tests depend on
    each other is a permanent tax.

    Nothing is torn down, matching every other tenant fixture in this suite: the
    schema is rebuilt from migrations at the start of each session, and
    cascading a delete over a workspace's facts, edges and embeddings would cost
    more than the tests do.
    """
    created: dict[int, uuid.UUID] = {}
    for size in (CORPUS, CORPUS * 2):
        tenant = Tenant(name=f"Perf {size}", slug=f"perf-{uuid.uuid4().hex[:10]}")
        platform.add(tenant)
        await platform.commit()
        created[size] = tenant.id

        async with tenant_session(tenant.id) as session:
            await seed_corpus(session, tenant.id, size)

    return created


class TestGraphBuildComplexity:
    async def test_subject_comparisons_do_not_grow_quadratically(
        self, workspaces: dict[int, uuid.UUID]
    ) -> None:
        """The H1 finding, stated as an assertion.

        The old `_same_subject` compared every pair: `n(n-1)/2`, which is
        180,000 comparisons at 600 facts and 720,000 at 1,200 — a factor of four
        across the doubling. The inverted index compares only facts that
        share a subject token, so the cost is `facts times neighbourhood`, and the
        neighbourhood is a property of the workspace rather than of its size.
        """
        embedder = HashingEmbedder()
        counts: dict[int, int] = {}
        for size, tenant_id in workspaces.items():
            async with tenant_session(tenant_id) as session:
                update = await graph.build(session, tenant_id=tenant_id, embedder=embedder)
            assert update.facts_considered == size
            counts[size] = update.subject_comparisons

        small, large = counts[CORPUS], counts[CORPUS * 2]
        assert small > 0, "nothing was compared; the corpus has no subject overlap"
        # Comfortably under the all-pairs floor, rather than marginally under —
        # a margin would make this a benchmark of today's constants.
        assert small < CORPUS * (CORPUS - 1) / 2 / 5
        # And the exponent itself: doubling the corpus must not quadruple the
        # work. 2.5 rather than 2.0 leaves room for the neighbourhoods being
        # slightly uneven at the edges of the corpus.
        assert large < small * 2.5, f"{small} -> {large} comparisons across a doubling"

    async def test_a_second_build_over_unchanged_facts_does_nothing(
        self, workspaces: dict[int, uuid.UUID]
    ) -> None:
        """Incremental, not merely fast.

        The old build re-derived every edge in the workspace on every pass and
        relied on `ON CONFLICT DO NOTHING` to throw the work away at the
        database — so it read every fact and compared every pair to write
        nothing. Re-running must now cost one indexed query.
        """
        embedder = HashingEmbedder()
        tenant_id = workspaces[CORPUS]
        async with tenant_session(tenant_id) as session:
            await graph.build(session, tenant_id=tenant_id, embedder=embedder)
            second = await graph.build(session, tenant_id=tenant_id, embedder=embedder)

        assert second.facts_considered == 0
        assert second.subject_comparisons == 0
        assert second.edges_written == 0
        assert second.embeddings_written == 0

    async def test_one_new_fact_costs_a_neighbourhood_not_a_workspace(
        self, workspaces: dict[int, uuid.UUID]
    ) -> None:
        """The case the pipeline actually runs: facts arrive a few at a time.

        The comparison count for one arriving fact must be a function of how
        many facts share its subject — and the two workspaces are identical in
        that respect and differ only in total size.
        """
        embedder = HashingEmbedder()
        arriving: dict[int, int] = {}
        for size, tenant_id in workspaces.items():
            async with tenant_session(tenant_id) as session:
                await graph.build(session, tenant_id=tenant_id, embedder=embedder)
                await store.apply(
                    session,
                    tenant_id=tenant_id,
                    incoming=[
                        Fact(
                            kind=FactKind.DELIVERY,
                            statement="Shipped atlas7 cnew to atlas7-billing.",
                            sources=[SourceRef(source="github", evidence_id="ev-new")],
                            certainty=Certainty.VERIFIED,
                            # Far outside `MERGE_WINDOW`, so this arrives as a
                            # new fact rather than merging into a sibling and
                            # leaving nothing for the build to do.
                            occurred_at=MONDAY + timedelta(days=5_000),
                        )
                    ],
                )
                update = await graph.build(session, tenant_id=tenant_id, embedder=embedder)

            assert update.facts_considered == 1
            arriving[size] = update.subject_comparisons

        assert arriving[CORPUS] > 0, "the fact was linked to nothing; the test proves nothing"
        assert arriving[CORPUS * 2] < arriving[CORPUS] * 2.5

    async def test_the_fan_out_ceiling_bounds_a_hub_and_reports_itself(
        self, platform: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One artefact cited by every fact must not link every fact to every other.

        The ceiling is lowered for the test rather than the corpus raised to
        meet it: what is under test is the mechanism, and a fixture large enough
        to exceed the production constant would spend a minute writing edges to
        prove something a small one proves exactly as well.

        Both halves of the contract are asserted — the edges are capped, *and*
        the build says so. Silent truncation is forbidden here for the same
        reason it is in retrieval: afterwards, a truncated result is
        indistinguishable from a complete one.
        """
        monkeypatch.setattr(graph, "MAX_GROUP_FANOUT", 5)

        tenant = Tenant(name="Hub", slug=f"hub-{uuid.uuid4().hex[:10]}")
        platform.add(tenant)
        await platform.commit()

        size = 30
        async with tenant_session(tenant.id) as session:
            facts = []
            sources = []
            for index in range(size):
                fact_id = uuid.uuid4()
                occurred = MONDAY + timedelta(days=index)
                facts.append(
                    {
                        "id": fact_id,
                        "tenant_id": tenant.id,
                        "kind": FactKind.DELIVERY.value,
                        "statement": f"Reviewed s{index}.",
                        "certainty": "verified",
                        "origin": "extracted",
                        "occurred_at": occurred,
                        "valid_from": occurred,
                    }
                )
                sources.append(
                    {
                        "id": uuid.uuid4(),
                        "tenant_id": tenant.id,
                        "fact_id": fact_id,
                        "source": "document",
                        "evidence_id": "ev-the-one-doc",
                    }
                )
            await session.execute(insert(FactRow), facts)
            await session.execute(insert(FactSource), sources)

            update = await graph.build(session, tenant_id=tenant.id, embedder=HashingEmbedder())

        assert update.truncated, "a fan-out ceiling was hit and nothing said so"
        assert 0 < update.edges_written <= size * graph.MAX_GROUP_FANOUT * 2
        # Uncapped, one artefact cited by thirty facts is 870 directed edges.
        assert update.edges_written < size * (size - 1)

    async def test_a_full_build_finishes(self, workspaces: dict[int, uuid.UUID]) -> None:
        """The first of two wall-clock assertions, and deliberately a bad benchmark.

        Set roughly an order of magnitude above the observed figure. It cannot
        tell a fast build from a slow one and is not meant to; it fails when a
        regression makes the build not finish, which is the failure mode a
        count-based assertion cannot express.
        """
        tenant_id = workspaces[CORPUS * 2]
        started = time.monotonic()
        async with tenant_session(tenant_id) as session:
            await graph.build(session, tenant_id=tenant_id, embedder=HashingEmbedder())
        assert time.monotonic() - started < 180


class TestResolutionComplexity:
    @staticmethod
    def batch(count: int = 10) -> list[Fact]:
        """A batch about one project, as an ingest of one team's activity would be."""
        return [
            Fact(
                kind=FactKind.DELIVERY,
                statement=f"Shipped atlas3 b{index} to atlas3-billing.",
                sources=[SourceRef(source="chat", evidence_id=f"ev-batch-{index}")],
                certainty=Certainty.VERIFIED,
                # Inside the corpus's span, so the merge window has something to
                # select. A batch dated outside it would produce an empty
                # candidate set and the test would pass without proving anything.
                occurred_at=MONDAY + timedelta(days=500, hours=index),
            )
            for index in range(count)
        ]

    async def test_similarity_work_is_bounded_by_candidates_not_by_the_workspace(
        self, workspaces: dict[int, uuid.UUID], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The H2 finding, stated as an assertion.

        `resolve()` walks its pool once per incoming fact, so the pool size *is*
        the complexity. Counting `similarity` calls measures that directly, and
        without touching the timer.
        """
        calls = 0
        real = resolve.similarity

        def counting(left: frozenset[str], right: frozenset[str]) -> float:
            nonlocal calls
            calls += 1
            return real(left, right)

        monkeypatch.setattr(resolve, "similarity", counting)

        counts: dict[int, int] = {}
        for size, tenant_id in workspaces.items():
            calls = 0
            async with tenant_session(tenant_id) as session:
                await store.apply(session, tenant_id=tenant_id, incoming=self.batch())
            counts[size] = calls

        small, large = counts[CORPUS], counts[CORPUS * 2]
        assert small > 0, "no comparisons happened; the batch matched nothing"
        # The full scan this replaced compared each of ten incoming facts
        # against every currently-valid fact in the workspace.
        assert small < CORPUS * len(self.batch()) / 10
        assert large < small * 2.5, f"{small} -> {large} similarity calls across a doubling"

    async def test_the_candidate_set_does_not_track_the_workspace_size(
        self, workspaces: dict[int, uuid.UUID]
    ) -> None:
        """The same property one level down, where it is easiest to read.

        Stated separately from the call count because the two can come apart: a
        future change could narrow the query and then widen the pool again in
        Python, and this is the assertion that would notice.
        """
        sizes: dict[int, int] = {}
        for size, tenant_id in workspaces.items():
            async with tenant_session(tenant_id) as session:
                candidates = await store._candidates(
                    session, tenant_id=tenant_id, incoming=self.batch()
                )
                full = await store.load_current(session, tenant_id=tenant_id)
            assert len(full) == size
            sizes[size] = len(candidates)

        assert 0 < sizes[CORPUS] < CORPUS / 10
        assert sizes[CORPUS * 2] < sizes[CORPUS] * 2.5

    async def test_a_batch_resolves_in_reasonable_time(
        self, workspaces: dict[int, uuid.UUID]
    ) -> None:
        """The second and last wall-clock bound, with the same caveats as the first."""
        tenant_id = workspaces[CORPUS * 2]
        started = time.monotonic()
        async with tenant_session(tenant_id) as session:
            await store.apply(session, tenant_id=tenant_id, incoming=self.batch())
        assert time.monotonic() - started < 30
