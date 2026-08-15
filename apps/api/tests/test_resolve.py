"""Stage 3 — deterministic resolution.

Two properties are the step's exit criterion and get tested first: **a decision
appearing in two sources resolves to one fact**, and **a superseded fact is
marked, not deleted**.

The rest of the file is mostly about what resolution must *refuse* to do.
Merging is destructive — the merged fact's statement is gone — so the tests that
matter are the near-misses: two deliveries that share most of their words but
concern different services, two statements that differ only by a negation, two
contradictory facts with no way to order them. A resolver that passes only the
happy path is one that quietly deletes facts in production.

The pure rules are tested without a database, because that is where the
judgement lives and in-memory tests can cover far more of it. The store is
tested against PostgreSQL, because supersession is a two-row invariant and the
constraint enforcing it is in the schema.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.domain import Certainty
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from cairn_api.pipeline.resolve import (
    MERGE_WINDOW,
    Outcome,
    resolve,
    similarity,
    subject_key,
    tokens,
)

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def fact(
    statement: str,
    *,
    kind: FactKind = FactKind.DECISION,
    source: str = "github",
    evidence_id: str = "ev-1",
    certainty: Certainty = Certainty.VERIFIED,
    people: list[str] | None = None,
    at: datetime | None = MONDAY,
) -> Fact:
    return Fact(
        kind=kind,
        statement=statement,
        sources=[SourceRef(evidence_id=evidence_id, source=source)],
        certainty=certainty,
        people=people or [],
        occurred_at=at,
    )


# --------------------------------------------------------------------------
# The exit criterion
# --------------------------------------------------------------------------


class TestOneDecisionFromTwoSources:
    """ "A decision appearing in two sources resolves to one fact." """

    def test_a_meeting_and_a_chat_thread_produce_one_fact(self) -> None:
        plan = resolve(
            [
                fact(
                    "The team decided to use Postgres for the event store rather than Kafka.",
                    source="meeting",
                    evidence_id="ev-standup",
                ),
                fact(
                    "The team decided to use Postgres for the event store rather than Kafka.",
                    source="chat",
                    evidence_id="ev-thread-12",
                    at=MONDAY + timedelta(days=2),
                ),
            ]
        )

        outcomes = [d.outcome for d in plan.decisions]
        assert outcomes == [Outcome.NEW, Outcome.MERGED]
        assert len(plan.to_store) == 1

        merged = plan.decisions[1].fact
        assert {s.source for s in merged.sources} == {"meeting", "chat"}
        assert len(merged.sources) == 2

    def test_the_merged_fact_keeps_the_earliest_occurrence(self) -> None:
        """A decision is dated when it was taken, not when it was repeated."""
        plan = resolve(
            [
                fact("Chose Postgres over Kafka for the event store.", source="meeting"),
                fact(
                    "Chose Postgres over Kafka for the event store.",
                    source="chat",
                    evidence_id="ev-2",
                    at=MONDAY + timedelta(days=3),
                ),
            ]
        )
        assert plan.decisions[1].fact.occurred_at == MONDAY

    def test_a_third_mention_merges_into_the_same_fact(self) -> None:
        """The pool must accumulate, or the third telling starts a second fact."""
        statement = "Chose Postgres over Kafka for the event store."
        plan = resolve(
            [
                fact(statement, source="meeting", evidence_id="ev-1"),
                fact(statement, source="chat", evidence_id="ev-2"),
                fact(statement, source="document", evidence_id="ev-3"),
            ]
        )
        assert [d.outcome for d in plan.decisions] == [
            Outcome.NEW,
            Outcome.MERGED,
            Outcome.MERGED,
        ]
        assert len(plan.decisions[2].fact.sources) == 3

    def test_corroboration_across_sources_promotes_suggested_to_observed(self) -> None:
        plan = resolve(
            [
                fact(
                    "Ali is leading the payments migration work.",
                    source="meeting",
                    certainty=Certainty.SUGGESTED,
                ),
                fact(
                    "Ali is leading the payments migration work.",
                    source="chat",
                    evidence_id="ev-2",
                    certainty=Certainty.SUGGESTED,
                ),
            ]
        )
        assert plan.decisions[1].fact.certainty is Certainty.OBSERVED

    def test_corroboration_never_reaches_verified(self) -> None:
        """Two systems repeating an inference is not a direct statement.

        Promoting here would manufacture the strongest certainty tier out of
        material that nobody ever stated — the exact false precision the
        categorical scale exists to avoid.
        """
        plan = resolve(
            [
                fact("Ali is leading payments.", source="meeting", certainty=Certainty.SUGGESTED),
                fact(
                    "Ali is leading payments.",
                    source="chat",
                    evidence_id="ev-2",
                    certainty=Certainty.SUGGESTED,
                ),
                fact(
                    "Ali is leading payments.",
                    source="document",
                    evidence_id="ev-3",
                    certainty=Certainty.SUGGESTED,
                ),
            ]
        )
        assert plan.decisions[-1].fact.certainty is Certainty.OBSERVED

    def test_repeating_one_source_does_not_inflate_corroboration(self) -> None:
        """Reprocessing the same event after a redeploy must change nothing.

        Without the source-level deduplication this would look like independent
        corroboration and promote certainty — the system sounding more sure
        because a worker restarted.
        """
        first = fact(
            "Ali is leading the payments migration.",
            source="chat",
            evidence_id="ev-9",
            certainty=Certainty.SUGGESTED,
        )
        second = fact(
            "Ali is leading the payments migration.",
            source="chat",
            evidence_id="ev-9",
            certainty=Certainty.SUGGESTED,
        )
        plan = resolve([first, second])

        merged = plan.decisions[1].fact
        assert len(merged.sources) == 1
        assert merged.certainty is Certainty.SUGGESTED


class TestSupersession:
    """ "A superseded fact is marked, not deleted." """

    def test_a_later_decision_supersedes_the_earlier_one(self) -> None:
        earlier = fact("The team will use Kafka for the event store.")
        later = fact(
            "The team will use Postgres for the event store instead.",
            evidence_id="ev-2",
            at=MONDAY + timedelta(days=5),
        )

        plan = resolve([later], existing=[earlier])
        decision = plan.decisions[0]

        assert decision.outcome is Outcome.SUPERSEDES
        assert decision.supersedes == earlier.id
        assert decision.reason

    def test_the_superseded_fact_is_still_in_the_plan_not_removed(self) -> None:
        """Nothing in a resolution plan ever asks for a deletion."""
        earlier = fact("Ali is working on authentication.", kind=FactKind.IN_PROGRESS)
        later = fact(
            "Ali is working on billing.",
            kind=FactKind.IN_PROGRESS,
            evidence_id="ev-2",
            at=MONDAY + timedelta(days=21),
        )

        plan = resolve([later], existing=[earlier])
        assert plan.decisions[0].outcome is Outcome.SUPERSEDES
        assert plan.to_supersede == [(earlier.id, later)]
        assert not hasattr(plan, "to_delete")

    def test_a_delivery_ends_the_blocker_it_resolves(self) -> None:
        blocker = fact(
            "Priya is blocked on the staging database credentials.",
            kind=FactKind.BLOCKER,
        )
        delivery = fact(
            "Priya shipped the staging database credentials rotation.",
            kind=FactKind.DELIVERY,
            evidence_id="ev-2",
            at=MONDAY + timedelta(days=2),
        )

        plan = resolve([delivery], existing=[blocker])
        assert plan.decisions[0].outcome is Outcome.SUPERSEDES
        assert plan.decisions[0].supersedes == blocker.id

    def test_a_decision_answers_an_open_question(self) -> None:
        question = fact(
            "Which database should back the event store?",
            kind=FactKind.OPEN_QUESTION,
        )
        answer = fact(
            "The event store database will be Postgres.",
            kind=FactKind.DECISION,
            evidence_id="ev-2",
            at=MONDAY + timedelta(days=1),
        )

        plan = resolve([answer], existing=[question])
        assert plan.decisions[0].outcome is Outcome.SUPERSEDES

    def test_nothing_supersedes_a_delivery(self) -> None:
        """A merged pull request stays merged.

        A revert is a new delivery, not an erasure of the old one — the work
        was done, and a record that unmakes it is a record nobody can reconcile
        against the repository.
        """
        delivery = fact("Shipped the rate limiter to production.", kind=FactKind.DELIVERY)
        revert = fact(
            "Reverted the rate limiter from production.",
            kind=FactKind.DELIVERY,
            evidence_id="ev-2",
            at=MONDAY + timedelta(days=1),
        )

        plan = resolve([revert], existing=[delivery])
        assert plan.decisions[0].outcome is Outcome.NEW

    def test_an_older_fact_never_supersedes_a_newer_one(self) -> None:
        """The case a backfill creates.

        Six months of history is ingested today. Ordering by ingestion time
        would let a January decision overwrite this morning's state.
        """
        current = fact(
            "Ali is working on billing.",
            kind=FactKind.IN_PROGRESS,
            at=MONDAY,
        )
        historical = fact(
            "Ali is working on authentication.",
            kind=FactKind.IN_PROGRESS,
            evidence_id="ev-old",
            at=MONDAY - timedelta(days=180),
        )

        plan = resolve([historical], existing=[current])
        assert plan.decisions[0].outcome is not Outcome.SUPERSEDES

    def test_simultaneous_contradictions_are_flagged_not_resolved(self) -> None:
        """No coin flip.

        Two contradictory statements about one subject at the same moment
        cannot be ordered. Both are kept, neither is marked, and the
        contradiction is surfaced — a guess presented as a resolved fact is
        worse than a visible disagreement.
        """
        one = fact("Ali is working on authentication.", kind=FactKind.IN_PROGRESS)
        other = fact(
            "Ali is working on billing.",
            kind=FactKind.IN_PROGRESS,
            evidence_id="ev-2",
            at=MONDAY,
        )

        plan = resolve([other], existing=[one])
        decision = plan.decisions[0]
        assert decision.outcome is Outcome.CONFLICT
        assert decision.conflicts_with == one.id
        assert decision.fact in plan.to_store


# --------------------------------------------------------------------------
# What resolution must refuse to do
# --------------------------------------------------------------------------


class TestMergingIsConservative:
    def test_similar_statements_about_different_things_stay_separate(self) -> None:
        """The unrecoverable failure: two deliveries collapsing into one."""
        plan = resolve(
            [
                fact("Migrated the auth service to Postgres.", kind=FactKind.DELIVERY),
                fact(
                    "Migrated the billing service to Postgres.",
                    kind=FactKind.DELIVERY,
                    evidence_id="ev-2",
                ),
            ]
        )
        assert [d.outcome for d in plan.decisions] == [Outcome.NEW, Outcome.NEW]

    def test_a_negation_is_not_a_duplicate(self) -> None:
        """ "Will use Postgres" and "will not use Postgres" differ by one word.

        A stoplist that swallowed "not" would merge them and store whichever
        arrived first as the team's decision.
        """
        plan = resolve(
            [
                fact("The team will use Postgres for the event store."),
                fact(
                    "The team will not use Postgres for the event store.",
                    evidence_id="ev-2",
                ),
            ]
        )
        assert plan.decisions[1].outcome is not Outcome.MERGED

    def test_facts_of_different_kinds_never_merge(self) -> None:
        """Folding a blocker into a delivery loses the blocker.

        Blockers are the highest-value fact in the product and the one whose
        absence nobody reports.
        """
        plan = resolve(
            [
                fact("The staging database migration is blocked.", kind=FactKind.BLOCKER),
                fact(
                    "The staging database migration is blocked.",
                    kind=FactKind.IN_PROGRESS,
                    evidence_id="ev-2",
                ),
            ]
        )
        assert [d.outcome for d in plan.decisions] == [Outcome.NEW, Outcome.NEW]

    def test_the_same_statement_months_apart_is_not_a_duplicate(self) -> None:
        """Revisiting a subject is a supersession question, not a merge."""
        plan = resolve(
            [
                fact("Chose Postgres over Kafka for the event store."),
                fact(
                    "Chose Postgres over Kafka for the event store.",
                    evidence_id="ev-2",
                    at=MONDAY + MERGE_WINDOW + timedelta(days=1),
                ),
            ]
        )
        assert plan.decisions[1].outcome is not Outcome.MERGED

    def test_short_statements_sharing_a_word_do_not_merge(self) -> None:
        """Proportional overlap alone collapses terse facts."""
        plan = resolve(
            [
                fact("Deployed staging.", kind=FactKind.DELIVERY),
                fact("Deployed production.", kind=FactKind.DELIVERY, evidence_id="ev-2"),
            ]
        )
        assert [d.outcome for d in plan.decisions] == [Outcome.NEW, Outcome.NEW]

    def test_two_word_facts_do_not_merge_even_when_identical(self) -> None:
        """The cost of the shared-token floor, asserted rather than hidden.

        These two *are* one fact, and the resolver keeps both. Similarity over
        a two-token statement carries almost no information — "shipped billing"
        and "shipped auth" score the same 0.5 as two genuinely related facts —
        so the floor refuses to act on it at all. The price is a visible
        duplicate; the alternative price is merging unrelated work, which
        nobody can see and nobody can recover.
        """
        plan = resolve(
            [
                fact("Billing shipped.", kind=FactKind.DELIVERY),
                fact("Shipped billing!", kind=FactKind.DELIVERY, evidence_id="ev-2"),
            ]
        )
        assert [d.outcome for d in plan.decisions] == [Outcome.NEW, Outcome.NEW]


class TestDeterminism:
    def test_the_same_batch_in_any_order_gives_the_same_result(self) -> None:
        """The property the whole stage is built for.

        A model asked which of two facts is current answers differently on
        different days. This must not.
        """
        batch = [
            fact("Chose Postgres for the event store.", source="meeting", evidence_id="ev-a"),
            fact("Chose Postgres for the event store.", source="chat", evidence_id="ev-b"),
            fact("Shipped the rate limiter.", kind=FactKind.DELIVERY, evidence_id="ev-c"),
        ]

        forward = resolve(batch)
        backward = resolve(list(reversed(batch)))

        def shape(plan: object) -> list[tuple[str, str]]:
            return sorted(
                (d.outcome.value, d.fact.statement)
                for d in plan.decisions  # type: ignore[attr-defined]
            )

        assert shape(forward) == shape(backward)

    def test_resolution_repeated_on_the_same_input_is_identical(self) -> None:
        batch = [
            fact("Chose Postgres for the event store.", source="meeting"),
            fact("Chose Postgres for the event store.", source="chat", evidence_id="ev-2"),
        ]
        first = [d.outcome for d in resolve(batch).decisions]
        second = [d.outcome for d in resolve(batch).decisions]
        assert first == second


class TestTextRules:
    def test_state_words_leave_the_subject_key_but_not_the_tokens(self) -> None:
        """The distinction supersession rests on.

        Subject keys match so the two can be recognised as one subject over
        time; full token sets differ so they are not mistaken for duplicates.
        """
        blocked = "Priya is blocked on the staging database credentials"
        rotated = "Priya resolved the staging database credentials"

        assert similarity(subject_key(blocked), subject_key(rotated)) > 0.7
        assert similarity(tokens(blocked), tokens(rotated)) < 0.7

    @pytest.mark.parametrize("word", ["not", "no", "never", "without", "instead"])
    def test_polarity_words_survive_tokenisation(self, word: str) -> None:
        assert word in tokens(f"The team will {word} adopt this approach")

    def test_similarity_of_nothing_is_zero_not_one(self) -> None:
        """Two empty token sets are not "identical".

        Treating them as a perfect match would merge every fact whose statement
        happened to be all stopwords into the first such fact.
        """
        assert similarity(frozenset(), frozenset()) == 0.0


class TestEmptyAndEdgeCases:
    def test_an_empty_batch_produces_an_empty_plan(self) -> None:
        plan = resolve([])
        assert plan.decisions == []
        assert plan.to_store == []

    def test_facts_without_timestamps_still_resolve(self) -> None:
        """An undated fact compares against everything.

        Excluding it would let undated duplicates accumulate, and duplicates
        that never merge look like real repeated activity.
        """
        plan = resolve(
            [
                fact("Chose Postgres over Kafka for the event store.", at=None),
                fact("Chose Postgres over Kafka for the event store.", evidence_id="ev-2", at=None),
            ]
        )
        assert plan.decisions[1].outcome is Outcome.MERGED

    def test_an_unrelated_fact_is_simply_new(self) -> None:
        plan = resolve(
            [fact("Shipped the rate limiter.", kind=FactKind.DELIVERY)],
            existing=[fact("Chose Postgres for the event store.")],
        )
        assert plan.decisions[0].outcome is Outcome.NEW

    def test_merging_never_loses_a_person(self) -> None:
        plan = resolve(
            [
                fact("Shipped rate limiting to production.", people=["priya"]),
                fact(
                    "Shipped rate limiting to production.",
                    evidence_id="ev-2",
                    source="chat",
                    people=["tom"],
                ),
            ]
        )
        assert set(plan.decisions[1].fact.people) == {"priya", "tom"}

    def test_a_merge_keeps_the_original_statement(self) -> None:
        """The second telling is not more accurate for being second.

        Rewriting a fact a reader may already have seen buys nothing and makes
        the record unstable.
        """
        original = "The team decided to use Postgres for the event store."
        plan = resolve(
            [
                fact(original),
                fact(
                    "The team decided to use Postgres for the event store, per Ali.",
                    evidence_id="ev-2",
                    source="chat",
                ),
            ]
        )
        assert plan.decisions[1].fact.statement == original
        assert plan.decisions[1].fact.id == plan.decisions[0].fact.id


def test_a_resolution_plan_reports_a_reason_for_every_decision() -> None:
    """A resolution nobody can explain is one nobody can defend to a customer."""
    plan = resolve(
        [
            fact("Chose Postgres for the event store.", source="meeting"),
            fact("Chose Postgres for the event store.", source="chat", evidence_id="ev-2"),
        ],
        existing=[fact("Shipped rate limiting.", kind=FactKind.DELIVERY, evidence_id="ev-0")],
    )
    assert all(d.reason for d in plan.decisions)


def test_fact_ids_are_stable_through_resolution() -> None:
    """A merged fact keeps the identity a brief may already cite."""
    first = fact("Chose Postgres for the event store.", source="meeting")
    plan = resolve(
        [fact("Chose Postgres for the event store.", source="chat", evidence_id="ev-2")],
        existing=[first],
    )
    assert plan.decisions[0].fact.id == first.id
    assert isinstance(first.id, uuid.UUID)


class TestPeopleGuardOnSupersession:
    def test_two_people_on_one_subject_do_not_supersede_each_other(self) -> None:
        """One subject, two colleagues, two facts.

        Treating the second as a state change would hide one person's work
        behind the other's — the attribution failure the identity graph exists
        to prevent, arriving through the resolution rules instead.
        """
        ali = fact(
            "Working on the authentication rewrite backend.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
        )
        priya = fact(
            "Working on the authentication rewrite frontend.",
            kind=FactKind.IN_PROGRESS,
            evidence_id="ev-2",
            people=["priya"],
            at=MONDAY + timedelta(days=1),
        )

        # NEW specifically, not merely "not superseded". Identical statements
        # would be caught by deduplication first and the assertion would hold
        # with the people rule deleted — a test that passes for the wrong
        # reason is indistinguishable from one that does not run.
        plan = resolve([priya], existing=[ali])
        assert plan.decisions[0].outcome is Outcome.NEW

    def test_the_same_person_moving_on_does_supersede(self) -> None:
        before = fact(
            "Ali is working on the authentication rewrite.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
        )
        after = fact(
            "Ali is working on the billing rewrite.",
            kind=FactKind.IN_PROGRESS,
            evidence_id="ev-2",
            people=["ali"],
            at=MONDAY + timedelta(days=21),
        )

        plan = resolve([after], existing=[before])
        assert plan.decisions[0].outcome is Outcome.SUPERSEDES
