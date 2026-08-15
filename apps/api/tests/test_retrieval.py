"""The temporal graph and retrieval.

Step 17's exit criterion: *a multi-hop question retrieves the correct chain;
superseded facts are excluded.* Both are tested against PostgreSQL with pgvector,
because both are properties of a query — a chain assembled in Python would prove
nothing about the one that runs.

**The chain under test is the one the spec names** (md/09 §3.1): *"why is
payments late?"* — a decision, the work it blocked, the person holding it, the
thread that raised it. It is built as four facts linked only by derived edges,
and the assertion is that retrieval reaches the far end from a question that
mentions none of it.

The embedder is `HashingEmbedder`, which has no notion of meaning. That is
deliberate: no test asserts on semantic ranking, because a trained model's
ranking is not a fixed quantity to write assertions against. Everything else —
the temporal filter, the traversal, the budget, tenant scoping — behaves
identically either way, and those are the parts that can be wrong.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.graph_models import EdgeKind, FactEdge, FactEmbedding
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.domain import Certainty
from cairn_api.pipeline import graph, store
from cairn_api.pipeline.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    DIMENSIONS,
    HNSW_DIMENSION_LIMIT,
    HashingEmbedder,
    VertexEmbeddingProvider,
)
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from cairn_api.pipeline.retrieval import CURRENT_EDGE_KINDS, retrieve
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
MODEL = DEFAULT_EMBEDDING_MODEL


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture
async def tenant_id(platform: AsyncSession) -> uuid.UUID:
    tenant = Tenant(name="Acme", slug=f"ret-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.commit()
    return tenant.id


def fact(
    statement: str,
    *,
    kind: FactKind = FactKind.DELIVERY,
    evidence: list[tuple[str, str]] | None = None,
    people: list[str] | None = None,
    certainty: Certainty = Certainty.VERIFIED,
    at: datetime | None = MONDAY,
) -> Fact:
    refs = evidence or [("github", f"ev-{uuid.uuid4().hex[:8]}")]
    return Fact(
        kind=kind,
        statement=statement,
        sources=[SourceRef(source=s, evidence_id=e) for s, e in refs],
        certainty=certainty,
        people=people or [],
        occurred_at=at,
    )


async def seed(tenant_id: uuid.UUID, facts: list[Fact], embedder: HashingEmbedder) -> None:
    """Store facts, then build the graph over them."""
    async with tenant_session(tenant_id) as session:
        await store.apply(session, tenant_id=tenant_id, incoming=facts)
        for stored in facts:
            await store.attach_people(session, tenant_id=tenant_id, fact_id=stored.id)
        await graph.build(session, tenant_id=tenant_id, embedder=embedder)
        await session.commit()


# --------------------------------------------------------------------------
# The embedding boundary
# --------------------------------------------------------------------------


class TestEmbeddings:
    def test_the_dimension_fits_the_index_it_will_be_stored_in(self) -> None:
        """Checked before the model is chosen, not after (md/06 §4.4).

        pgvector's HNSW index refuses more than 2,000 dimensions. Discovering
        that from a migration failing in staging is the avoidable version of
        this problem.
        """
        assert DIMENSIONS <= HNSW_DIMENSION_LIMIT

    async def test_vectors_are_deterministic(self, embedder: HashingEmbedder) -> None:
        """The same statement embeds identically every time.

        Without it, a re-embed would move every fact in the space and change
        what retrieval returns for reasons nobody could trace.
        """
        first = await embedder.embed(["Shipped the rate limiter."])
        second = await embedder.embed(["Shipped the rate limiter."])
        assert first == second

    async def test_vectors_are_normalised_to_the_configured_width(
        self, embedder: HashingEmbedder
    ) -> None:
        [vector] = await embedder.embed(["Shipped the rate limiter."])
        assert len(vector) == DIMENSIONS
        assert abs(sum(value * value for value in vector) - 1.0) < 1e-9

    async def test_word_order_changes_the_vector(self, embedder: HashingEmbedder) -> None:
        """Bigrams, so a negation does not land on top of its opposite."""
        [with_not] = await embedder.embed(["The migration is not blocked"])
        [without] = await embedder.embed(["The migration is blocked"])
        assert with_not != without

    async def test_an_empty_statement_gives_a_zero_vector_rather_than_raising(
        self, embedder: HashingEmbedder
    ) -> None:
        [vector] = await embedder.embed(["..."])
        assert set(vector) == {0.0}

    def test_the_embedding_adapter_will_not_be_constructed_without_a_project(self) -> None:
        """The adapter is implemented now; "it raises" is no longer the property.

        Batching, dimensionality, the count-mismatch guard and error handling
        are covered in `test_model_adapters.py` against a real transport. What
        remains here is the constructor check, because an empty project id
        otherwise surfaces as an opaque 404 at the first embed call.
        """
        with pytest.raises(ValueError, match="project id"):
            VertexEmbeddingProvider(project_id="")


# --------------------------------------------------------------------------
# Edge derivation
# --------------------------------------------------------------------------


class TestGraphBuilding:
    async def test_facts_from_one_artefact_are_linked(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        shared = [("github", "ev-pr-482")]
        await seed(
            tenant_id,
            [
                fact("Merged the token refactor.", evidence=shared),
                fact("The token refactor removed the legacy session path.", evidence=shared),
            ],
            embedder,
        )

        async with tenant_session(tenant_id) as session:
            edges = list(
                await session.scalars(
                    select(FactEdge).where(FactEdge.kind == EdgeKind.SHARED_EVIDENCE)
                )
            )
        # Both directions. Traversal expands from a frontier, so a single row
        # would make reachability depend on extraction order.
        assert len(edges) == 2
        assert edges[0].detail == "github:ev-pr-482"

    async def test_unresolved_mentions_never_create_a_person_edge(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        """Two mentions of "Sam" may be two people.

        Linking on the raw string builds the chain that credits one person's
        work to another — the identity failure, arriving through retrieval.
        """
        await seed(
            tenant_id,
            [
                fact("Sam reviewed the payments migration.", people=["Sam"]),
                fact("Sam raised a question about the schema.", people=["Sam"]),
            ],
            embedder,
        )

        async with tenant_session(tenant_id) as session:
            count = await session.scalar(
                select(func.count())
                .select_from(FactEdge)
                .where(FactEdge.kind == EdgeKind.SHARED_PERSON)
            )
        assert count == 0

    async def test_resolved_people_do_create_an_edge(
        self, platform: AsyncSession, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        person = Person(tenant_id=tenant_id, display_name="Ali Hassan")
        platform.add(person)
        await platform.commit()

        await seed(
            tenant_id,
            [
                fact("Reviewed the payments migration.", people=["Ali Hassan"]),
                fact("Raised a question about the billing schema.", people=["Ali Hassan"]),
            ],
            embedder,
        )

        async with tenant_session(tenant_id) as session:
            edges = list(
                await session.scalars(
                    select(FactEdge).where(FactEdge.kind == EdgeKind.SHARED_PERSON)
                )
            )
        assert len(edges) == 2
        assert edges[0].detail == f"person:{person.id}"

    async def test_building_twice_writes_nothing_the_second_time(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        """The build runs continuously as facts arrive."""
        shared = [("github", "ev-pr-1")]
        await seed(
            tenant_id,
            [fact("Merged A.", evidence=shared), fact("Merged B.", evidence=shared)],
            embedder,
        )

        async with tenant_session(tenant_id) as session:
            update = await graph.build(session, tenant_id=tenant_id, embedder=embedder)
            await session.commit()

        assert update.edges_written == 0
        assert update.embeddings_written == 0

    async def test_a_fact_is_embedded_once_per_model(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        """Re-embedding an unchanged statement pays for an identical vector.

        A statement never changes after storage — a correction supersedes it
        rather than editing it — so anything already embedded is final.
        """
        await seed(tenant_id, [fact("Shipped the rate limiter.")], embedder)

        async with tenant_session(tenant_id) as session:
            count = await session.scalar(select(func.count()).select_from(FactEmbedding))
        assert count == 1

    async def test_a_fact_cannot_link_to_itself(self, tenant_id: uuid.UUID) -> None:
        """A self-edge is a traversal that never terminates."""
        async with tenant_session(tenant_id) as session:
            row = FactRow(
                tenant_id=tenant_id,
                kind="delivery",
                statement="Shipped it.",
                certainty="verified",
                valid_from=MONDAY,
            )
            session.add(row)
            await session.flush()

            session.add(
                FactEdge(
                    tenant_id=tenant_id,
                    source_fact_id=row.id,
                    target_fact_id=row.id,
                    kind=EdgeKind.SAME_SUBJECT,
                )
            )
            with pytest.raises(IntegrityError, match="no_self_edge"):
                await session.flush()
            await session.rollback()


# --------------------------------------------------------------------------
# The exit criterion
# --------------------------------------------------------------------------


class TestMultiHopRetrieval:
    """ "A multi-hop question retrieves the correct chain."""

    @pytest.fixture
    async def payments_chain(
        self, platform: AsyncSession, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> dict[str, Fact]:
        """The question from md/09 §3.1, built as four linked facts.

        decision --shared evidence--> blocked PR --shared person--> reviewer
        --shared evidence--> the thread that raised it

        No single fact contains the whole answer, and no pair of them is
        adjacent by similarity alone. Only traversal connects the ends.
        """
        reviewer = Person(tenant_id=tenant_id, display_name="Dana Whitfield")
        platform.add(reviewer)
        await platform.commit()

        decision = fact(
            "The team decided the payments cutover needs a staged rollout.",
            kind=FactKind.DECISION,
            evidence=[("meeting", "ev-planning-01")],
        )
        blocked = fact(
            "The staged rollout pull request is waiting on review.",
            kind=FactKind.BLOCKER,
            evidence=[("meeting", "ev-planning-01"), ("github", "ev-pr-77")],
            people=["Dana Whitfield"],
            at=MONDAY + timedelta(days=1),
        )
        reviewer_fact = fact(
            "Dana is on leave until the end of the month.",
            kind=FactKind.IN_PROGRESS,
            evidence=[("chat", "ev-thread-9")],
            people=["Dana Whitfield"],
            at=MONDAY + timedelta(days=2),
        )
        thread = fact(
            "Someone asked in chat whether anyone else can approve reviews.",
            kind=FactKind.OPEN_QUESTION,
            evidence=[("chat", "ev-thread-9")],
            at=MONDAY + timedelta(days=3),
        )

        await seed(tenant_id, [decision, blocked, reviewer_fact, thread], embedder)
        return {
            "decision": decision,
            "blocked": blocked,
            "reviewer": reviewer_fact,
            "thread": thread,
        }

    async def test_the_whole_chain_is_reached_from_one_end(
        self,
        tenant_id: uuid.UUID,
        embedder: HashingEmbedder,
        payments_chain: dict[str, Fact],
    ) -> None:
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="the payments cutover staged rollout decision",
                embedder=embedder,
                # One entry point, so every other fact must be *walked to*.
                # Leaving the default of eight would let similarity return all
                # four directly and the test would pass with traversal deleted.
                entry_points=1,
                max_hops=3,
            )

        retrieved = set(result.fact_ids)
        for name, item in payments_chain.items():
            assert item.id in retrieved, f"traversal never reached the {name} fact"

        # And it was genuinely walked, not returned. Exactly one fact was an
        # entry point and something was reached two hops out.
        #
        # Which fact similarity picks is deliberately not asserted: the hashing
        # embedder has no notion of meaning, and pinning the entry point would
        # be a test of the stand-in rather than of the traversal.
        assert sum(1 for item in result.facts if item.hops == 0) == 1
        assert max(item.hops for item in result.facts) >= 2

    async def test_each_hop_can_explain_itself(
        self,
        tenant_id: uuid.UUID,
        embedder: HashingEmbedder,
        payments_chain: dict[str, Fact],
    ) -> None:
        """ "Why am I being shown this" must be answerable for every fact.

        A chain nobody can explain is a chain nobody can dispute, which is the
        same problem as a claim with no citation.
        """
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="the payments cutover staged rollout decision",
                embedder=embedder,
                max_hops=3,
            )

        for item in result.facts:
            if item.hops == 0:
                assert item.via is None
                assert item.distance is not None
            else:
                assert item.via is not None
                assert item.because

    async def test_a_single_hop_stops_short_of_the_far_end(
        self,
        tenant_id: uuid.UUID,
        embedder: HashingEmbedder,
        payments_chain: dict[str, Fact],
    ) -> None:
        """The depth bound is real, not decorative.

        Without this, "it retrieved everything" and "it traversed correctly"
        look identical — a retriever returning the whole workspace passes every
        reachability assertion.
        """
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="the payments cutover staged rollout decision",
                embedder=embedder,
                entry_points=1,
                max_hops=1,
            )

        assert len(result.facts) < 4

    async def test_the_budget_stops_expansion_and_says_so(
        self,
        tenant_id: uuid.UUID,
        embedder: HashingEmbedder,
        payments_chain: dict[str, Fact],
    ) -> None:
        """A silently truncated retrieval reads exactly like a complete one."""
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="the payments cutover staged rollout decision",
                embedder=embedder,
                max_hops=3,
                budget_chars=80,
            )

        assert result.truncated
        assert len(result.facts) <= 2

    async def test_context_ordering_puts_entry_points_last(
        self,
        tenant_id: uuid.UUID,
        embedder: HashingEmbedder,
        payments_chain: dict[str, Fact],
    ) -> None:
        """Attention concentrates at the edges (md/09 §4.3).

        The most relevant facts belong nearest the request; background hops go
        in the middle, where recall is weakest and costs least.
        """
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="the payments cutover staged rollout decision",
                embedder=embedder,
                max_hops=3,
            )

        ordered = result.for_context()
        assert [item.hops for item in ordered] == sorted(
            (item.hops for item in result.facts), reverse=True
        )
        assert ordered[-1].hops == 0


class TestSupersededFactsAreExcluded:
    """ "Superseded facts are excluded." The other half of the criterion."""

    @pytest.fixture
    async def moved_on(self, tenant_id: uuid.UUID, embedder: HashingEmbedder) -> dict[str, Fact]:
        """The canonical trust-destroying failure (md/09 §3.2).

        "Ali is working on authentication", three weeks after he moved to
        billing.
        """
        old = fact(
            "Ali is working on the authentication rewrite.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
        )
        await seed(tenant_id, [old], embedder)

        new = fact(
            "Ali is working on the billing rewrite.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
            at=MONDAY + timedelta(days=21),
        )
        await seed(tenant_id, [new], embedder)
        return {"old": old, "new": new}

    async def test_a_superseded_fact_does_not_come_back(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder, moved_on: dict[str, Fact]
    ) -> None:
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="what is Ali working on",
                embedder=embedder,
                max_hops=3,
            )

        assert moved_on["new"].id in result.fact_ids
        assert moved_on["old"].id not in result.fact_ids

    async def test_history_is_reachable_when_asked_for_explicitly(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder, moved_on: dict[str, Fact]
    ) -> None:
        """Superseded, not deleted — so "what did we think" stays answerable.

        `as_of` is the right axis for it: the fact was valid then, and the
        question is about then.
        """
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="what is Ali working on",
                embedder=embedder,
                as_of=MONDAY + timedelta(days=1),
                max_hops=3,
            )

        assert moved_on["old"].id in result.fact_ids
        assert moved_on["new"].id not in result.fact_ids

    async def test_as_of_excludes_what_had_already_been_replaced(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        """Three states, and the middle one is the answer.

        A fact superseded *before* the moment asked about must not come back.
        Checking only that a fact had started being valid — without checking it
        had not already ended — returns every belief the workspace ever held up
        to that date, which is not a point in time at all.
        """
        first = fact(
            "Ali is working on the authentication rewrite.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
        )
        await seed(tenant_id, [first], embedder)

        second = fact(
            "Ali is working on the billing rewrite.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
            at=MONDAY + timedelta(days=7),
        )
        await seed(tenant_id, [second], embedder)

        third = fact(
            "Ali is working on the search rewrite.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
            at=MONDAY + timedelta(days=21),
        )
        await seed(tenant_id, [third], embedder)

        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="what is Ali working on",
                embedder=embedder,
                as_of=MONDAY + timedelta(days=14),
                max_hops=3,
            )

        assert second.id in result.fact_ids
        assert first.id not in result.fact_ids, "returned a belief already replaced by then"
        assert third.id not in result.fact_ids, "returned a belief not yet held"

    def test_supersession_edges_are_not_traversed_by_default(self) -> None:
        """Asserted structurally, because behaviour cannot see it.

        The temporal filter already excludes superseded facts on every hop, so
        removing this gate changes no observable outcome today — which is
        exactly why deleting it would go unnoticed until the filter changed and
        the second layer turned out not to be there.
        """
        assert EdgeKind.SUPERSEDES not in CURRENT_EDGE_KINDS

    async def test_the_activity_window_does_not_leak_into_validity(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder, moved_on: dict[str, Fact]
    ) -> None:
        """ "What happened last Tuesday" is not "what did we think last Tuesday".

        Answering the first with the second turns a retrospective into a
        rewrite of history, so a `since`/`until` window must not resurrect a
        fact whose validity has ended.
        """
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,
                question="what is Ali working on",
                embedder=embedder,
                since=MONDAY - timedelta(days=1),
                until=MONDAY + timedelta(days=2),
                max_hops=3,
            )

        assert moved_on["old"].id not in result.fact_ids


class TestScoping:
    async def test_retrieval_never_crosses_a_workspace(
        self, platform: AsyncSession, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        """The check every new table needs, on the path most likely to skip it.

        Retrieval joins three tables and filters on the embedding's tenant. A
        query that filtered on only one of them would work perfectly in every
        single-tenant test.
        """
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        await seed(tenant_id, [fact("Shipped the rate limiter to production.")], embedder)

        async with tenant_session(other.id) as session:
            result = await retrieve(
                session,
                tenant_id=tenant_id,  # deliberately the wrong tenant's id
                question="rate limiter",
                embedder=embedder,
            )
        assert result.facts == []

    async def test_a_question_matching_nothing_returns_nothing(
        self, tenant_id: uuid.UUID, embedder: HashingEmbedder
    ) -> None:
        """An empty workspace retrieves an empty set rather than failing."""
        async with tenant_session(tenant_id) as session:
            result = await retrieve(
                session, tenant_id=tenant_id, question="anything", embedder=embedder
            )
        assert result.facts == []
        assert not result.truncated
