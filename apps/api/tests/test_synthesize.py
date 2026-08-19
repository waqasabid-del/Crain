"""Stage 4 — synthesis, span verification, and hedged language.

Step 18's exit criterion, in three parts: *a brief is generated with every claim
cited; unsupported claims are suppressed; meeting-derived claims read as hedged.*

The tests are mostly about the second one. Generating prose is what the model
does and a scripted provider proves little about it — what this stage owes the
product is the guarantee that **nothing reaches a reader that the facts do not
carry.** So the provider here plays the adversary: it cites facts that were
never supplied, claims things the evidence does not say, states meeting
inferences flatly, and writes a sentence that appraises a person. What matters is
what comes out the other side.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.domain import Certainty
from cairn_api.pipeline import hedging, verify
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from cairn_api.pipeline.provider import ModelError, ModelRequest, ModelResponse, ScriptedProvider
from cairn_api.pipeline.synthesize import MAX_FACTS, synthesize

pytestmark = pytest.mark.anyio

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def fact(
    statement: str,
    *,
    kind: FactKind = FactKind.DELIVERY,
    certainty: Certainty = Certainty.VERIFIED,
    source: str = "github",
    evidence_id: str = "ev-1",
    people: list[str] | None = None,
) -> Fact:
    return Fact(
        kind=kind,
        statement=statement,
        sources=[SourceRef(source=source, evidence_id=evidence_id)],
        certainty=certainty,
        people=people or [],
        occurred_at=MONDAY,
    )


def brief_payload(*claims: dict[str, object], narrative: str = "") -> str:
    return json.dumps({"narrative": narrative, "claims": list(claims)})


def claim(text: str, *facts: Fact) -> dict[str, object]:
    return {"text": text, "fact_ids": [str(f.id) for f in facts]}


# --------------------------------------------------------------------------
# Every claim cited
# --------------------------------------------------------------------------


class TestCitation:
    async def test_a_brief_is_produced_with_every_claim_cited(self) -> None:
        shipped = fact("Priya shipped rate limiting to production.")
        blocked = fact(
            "The staging database credentials are blocking verification.",
            kind=FactKind.BLOCKER,
            evidence_id="ev-2",
            source="chat",
        )
        provider = ScriptedProvider(
            default=brief_payload(
                claim("Priya shipped rate limiting to production.", shipped),
                claim("The staging database credentials are blocking verification.", blocked),
                narrative="Rate limiting shipped; staging credentials are blocking verification.",
            )
        )

        brief = await synthesize(provider, facts=[shipped, blocked])

        assert not brief.abstained
        assert len(brief.claims) == 2
        assert all(item.citations for item in brief.claims)
        assert brief.claims[0].citations == ("ev-1",)
        assert brief.claims[1].citations == ("ev-2",)
        assert brief.narrative

    async def test_citations_are_resolved_from_facts_not_taken_from_the_model(self) -> None:
        """The model references fact ids; the evidence links come from the facts.

        A citation the model wrote is a citation the model could invent, and an
        invented one that happens to look plausible is worse than none — "open
        the source" then leads somewhere that does not exist.
        """
        shipped = fact("Priya shipped rate limiting.", evidence_id="ev-real")
        provider = ScriptedProvider(
            default=json.dumps(
                {
                    "claims": [
                        {
                            "text": "Priya shipped rate limiting.",
                            "fact_ids": [str(shipped.id)],
                            "citations": ["ev-invented"],
                        }
                    ]
                }
            )
        )

        brief = await synthesize(provider, facts=[shipped])
        assert brief.claims[0].citations == ("ev-real",)

    async def test_a_claim_citing_nothing_is_suppressed(self) -> None:
        shipped = fact("Priya shipped rate limiting.")
        provider = ScriptedProvider(
            default=brief_payload({"text": "The team had a productive week.", "fact_ids": []})
        )

        brief = await synthesize(provider, facts=[shipped])

        assert brief.claims == []
        assert "cited no facts" in brief.suppressed[0].reason

    async def test_a_claim_citing_a_fact_that_was_never_supplied_is_suppressed(self) -> None:
        """The convincing shape of fabrication: a real-looking reference.

        The model is told to reference only what it was given, so an id from
        nowhere means either a hallucination or an injection that worked.
        """
        shipped = fact("Priya shipped rate limiting.")
        provider = ScriptedProvider(
            default=brief_payload(
                {
                    "text": "The payments migration completed successfully.",
                    "fact_ids": [str(uuid.uuid4())],
                }
            )
        )

        brief = await synthesize(provider, facts=[shipped])

        assert brief.claims == []
        assert "not supplied" in brief.suppressed[0].reason


# --------------------------------------------------------------------------
# Unsupported claims suppressed
# --------------------------------------------------------------------------


class TestSuppression:
    async def test_a_claim_the_facts_do_not_carry_is_suppressed(self) -> None:
        """Suppressed, not caveated (md/09 §5.2).

        A caveat still puts the sentence in front of a reader, and readers
        remember sentences rather than the qualifications attached to them.
        """
        shipped = fact("Priya shipped rate limiting to production.")
        provider = ScriptedProvider(
            default=brief_payload(
                claim(
                    "Priya shipped rate limiting and completed the payments migration "
                    "ahead of the quarterly deadline.",
                    shipped,
                )
            )
        )

        brief = await synthesize(provider, facts=[shipped])

        assert brief.claims == []
        assert "not supported" in brief.suppressed[0].reason

    async def test_paraphrase_is_allowed(self) -> None:
        """Synthesis is supposed to write, not to quote.

        A verifier demanding full coverage would suppress every well-written
        sentence and leave a bulleted list of fact statements.
        """
        shipped = fact("Priya merged the rate limiting pull request to production.")
        provider = ScriptedProvider(
            default=brief_payload(claim("Priya merged rate limiting to production.", shipped))
        )

        brief = await synthesize(provider, facts=[shipped])
        assert len(brief.claims) == 1

    async def test_suppression_is_recorded_with_a_reason(self) -> None:
        """A brief that quietly lost half its claims looks like a quiet week."""
        shipped = fact("Priya shipped rate limiting.")
        provider = ScriptedProvider(
            default=brief_payload(
                claim("Priya shipped rate limiting.", shipped),
                claim("Revenue grew forty percent this quarter.", shipped),
            )
        )

        brief = await synthesize(provider, facts=[shipped])

        assert len(brief.claims) == 1
        assert len(brief.suppressed) == 1
        assert brief.suppressed[0].reason
        assert "revenue" in brief.suppressed[0].text.lower()

    async def test_an_appraisal_of_a_person_is_suppressed(self) -> None:
        """The zero-tolerance rules, applied where the product runs.

        These patterns block a release (md/05 §A.5). A claim that blocks a
        release must not be shippable at runtime, which is why the patterns live
        with the product and the grader imports them.

        The fact here is one Stage 2's own guardrail would have refused, which
        is the case worth testing: **facts do not all come from Stage 2.** A
        human correction (`FactOrigin.CORRECTION`) is written by a person who can
        type whatever they like, and this is the gate standing between that and
        a brief. The claim is fully supported by its fact — span verification
        passes it — so only the boundary check can stop it.
        """
        appraisal = fact("Tom struggled with the payments migration.", people=["tom"])
        provider = ScriptedProvider(
            default=brief_payload(claim("Tom struggled with the payments migration.", appraisal))
        )

        brief = await synthesize(provider, facts=[appraisal])

        assert brief.claims == []
        assert "evaluative" in brief.suppressed[0].reason

    async def test_a_claim_that_ranks_people_is_suppressed(self) -> None:
        ranked = fact("Tom was the top performer in the review queue this week.", people=["tom"])
        provider = ScriptedProvider(
            default=brief_payload(
                claim("Tom was the top performer in the review queue this week.", ranked)
            )
        )

        brief = await synthesize(provider, facts=[ranked])

        assert brief.claims == []
        assert "ranks people" in brief.suppressed[0].reason

    async def test_a_narrative_that_trips_a_guardrail_is_replaced(self) -> None:
        """The narrative is the part a reader actually reads.

        It cannot be edited to remove a violation without writing a paragraph
        nobody approved, so it is replaced wholesale by the surviving claims.
        """
        shipped = fact("Tom shipped three pull requests.", people=["tom"])
        provider = ScriptedProvider(
            default=brief_payload(
                claim("Tom shipped three pull requests.", shipped),
                narrative="Tom was underperforming relative to the rest of the team.",
            )
        )

        brief = await synthesize(provider, facts=[shipped])

        assert "underperforming" not in brief.narrative
        assert brief.narrative == brief.claims[0].text
        assert any("narrative" in item.reason for item in brief.suppressed)

    async def test_output_that_is_not_json_abstains_rather_than_guessing(self) -> None:
        provider = ScriptedProvider(default="Here is your brief! Everything went well.")
        brief = await synthesize(provider, facts=[fact("Priya shipped rate limiting.")])

        assert brief.abstained
        assert brief.claims == []

    async def test_a_provider_outage_abstains_rather_than_assembling_prose(self) -> None:
        """No fallback brief stitched together from fact statements.

        It would reach the reader looking exactly like one the model wrote, and
        "the expensive stage is down" would go unnoticed for as long as the
        sentences stayed plausible.
        """

        class Broken:
            async def complete(self, request: ModelRequest) -> ModelResponse:
                raise ModelError("quota exhausted")

        brief = await synthesize(Broken(), facts=[fact("Priya shipped rate limiting.")])

        assert brief.abstained
        assert brief.claims == []
        assert "could not be generated" in brief.narrative

    async def test_no_facts_means_an_explicit_abstention(self) -> None:
        provider = ScriptedProvider(default=brief_payload())
        brief = await synthesize(provider, facts=[])

        assert brief.abstained
        assert provider.calls == [], "called the premium model with nothing to summarise"

    async def test_the_fact_count_offered_to_the_model_is_bounded(self) -> None:
        """Retrieval bounds tokens; this bounds items.

        Past a few dozen statements the model starts summarising the list rather
        than the work.
        """
        facts = [fact(f"Change number {n} was merged.", evidence_id=f"ev-{n}") for n in range(60)]
        provider = ScriptedProvider(default=brief_payload())

        await synthesize(provider, facts=facts)

        rendered = provider.calls[0].untrusted_data
        assert rendered.count("was merged") == MAX_FACTS

    async def test_the_bound_can_be_overridden_without_changing_the_default(self) -> None:
        """The constant stays the documented default; a caller may lower it.

        Both halves are asserted, because the finding was that the number was
        unreachable configuration — and the fix that would quietly break every
        existing caller is one that made `max_facts` required.
        """
        facts = [fact(f"Change number {n} was merged.", evidence_id=f"ev-{n}") for n in range(60)]
        provider = ScriptedProvider(default=brief_payload())

        await synthesize(provider, facts=facts, max_facts=5)
        assert provider.calls[0].untrusted_data.count("was merged") == 5

        await synthesize(provider, facts=facts)
        assert provider.calls[1].untrusted_data.count("was merged") == MAX_FACTS


# --------------------------------------------------------------------------
# Hedged language by certainty tier
# --------------------------------------------------------------------------


class TestHedging:
    async def test_a_meeting_derived_claim_reads_as_hedged(self) -> None:
        """The exit criterion's third part.

        A badge saying "suggested" beside a flat sentence does not undo the
        sentence — people read prose and skim chrome.
        """
        inferred = fact(
            "Ali agreed to take the authentication work.",
            certainty=Certainty.SUGGESTED,
            source="meeting",
            evidence_id="ev-standup",
        )
        provider = ScriptedProvider(
            default=brief_payload(claim("Ali agreed to take the authentication work.", inferred))
        )

        brief = await synthesize(provider, facts=[inferred])

        [only] = brief.claims
        assert only.certainty is Certainty.SUGGESTED
        assert hedging.is_hedged(only.text), only.text
        assert only.hedged_by_system

    async def test_a_model_that_hedges_properly_is_left_alone(self) -> None:
        """The prefix is a fallback, not the product's voice."""
        inferred = fact(
            "Ali agreed to take the authentication work.",
            certainty=Certainty.SUGGESTED,
            source="meeting",
        )
        provider = ScriptedProvider(
            default=brief_payload(
                claim("It sounded like Ali agreed to take the authentication work.", inferred)
            )
        )

        brief = await synthesize(provider, facts=[inferred])

        assert brief.claims[0].text.startswith("It sounded like Ali")
        assert not brief.claims[0].hedged_by_system

    async def test_a_verified_claim_is_stated_plainly(self) -> None:
        """Hedging everything makes hedging mean nothing.

        A merged pull request is not "apparently" merged, and a reader who
        cannot tell what the system knows from what it inferred has lost the
        only thing the tiers provide.
        """
        merged = fact("Priya merged the rate limiting pull request.")
        provider = ScriptedProvider(
            default=brief_payload(claim("Priya merged the rate limiting pull request.", merged))
        )

        brief = await synthesize(provider, facts=[merged])

        assert not brief.claims[0].hedged_by_system
        assert not hedging.is_hedged(brief.claims[0].text)

    async def test_a_claim_is_no_more_certain_than_its_weakest_fact(self) -> None:
        """One verified fact must not launder a meeting inference.

        Taking the strongest tier would let a claim citing both assert flatly
        what only a transcript supports — the overconfidence the tiers exist to
        prevent, arriving through the citation list.
        """
        merged = fact("Priya merged the rate limiting pull request.")
        inferred = fact(
            "Priya said rate limiting would ship before the migration.",
            certainty=Certainty.SUGGESTED,
            source="meeting",
            evidence_id="ev-2",
        )
        provider = ScriptedProvider(
            default=brief_payload(
                claim(
                    "Priya merged rate limiting and said it would ship before the migration.",
                    merged,
                    inferred,
                )
            )
        )

        brief = await synthesize(provider, facts=[merged, inferred])

        [only] = brief.claims
        assert only.certainty is Certainty.SUGGESTED
        assert hedging.is_hedged(only.text)

    def test_hedging_is_idempotent(self) -> None:
        once = hedging.apply("The migration slipped.", Certainty.SUGGESTED)
        twice = hedging.apply(once, Certainty.SUGGESTED)
        assert once == twice

    def test_hedging_never_lowercases_a_name(self) -> None:
        """ "it appears that ali shipped it" reads as carelessness about a person."""
        hedged = hedging.apply("Ali shipped the auth rewrite.", Certainty.OBSERVED)
        assert "Ali" in hedged
        assert "ali shipped" not in hedged

    def test_verified_is_not_in_the_tiers_that_must_hedge(self) -> None:
        assert Certainty.VERIFIED not in hedging.MUST_HEDGE


# --------------------------------------------------------------------------
# Span verification, on its own
# --------------------------------------------------------------------------


class TestSpanVerification:
    def test_a_claim_with_no_evidence_is_unsupported_not_vacuously_true(self) -> None:
        """The exact case the check exists for must not pass by default."""
        support = verify.check("Anything at all.", [])
        assert not support.supported
        assert support.coverage == 0.0

    def test_an_invented_clause_is_named_in_the_report(self) -> None:
        """ "Unsupported" is not actionable; "it mentioned a deadline" is."""
        support = verify.check(
            "Priya shipped rate limiting before the quarterly deadline.",
            ["Priya shipped rate limiting."],
        )
        assert not support.supported
        assert "deadline" in support.unsupported_terms

    def test_a_supported_claim_reports_full_coverage(self) -> None:
        support = verify.check(
            "Priya shipped rate limiting.", ["Priya shipped rate limiting to production."]
        )
        assert support.supported
        assert support.coverage == 1.0

    def test_evidence_from_several_facts_is_pooled(self) -> None:
        support = verify.check(
            "Priya shipped rate limiting and Tom reviewed it.",
            ["Priya shipped rate limiting.", "Tom reviewed the change."],
        )
        assert support.supported

    def test_a_claim_of_pure_filler_is_not_supported(self) -> None:
        assert not verify.check("It was a week.", ["Priya shipped rate limiting."]).supported


class TestTheNarrativeDoesNotLeakIdentifiers:
    """**Found in the first brief generated from real ingested activity.**

    The narrative read: "The team made a decision to throttle write endpoints at
    the gateway rather than per service (a4956a67-7998-4422-a12b-ddd66d436503)."

    Claims carry their citations structurally, so the model has no reason to put
    identifiers in prose - but it is shown fact ids in the data block and asked
    to reference them, and prose is where a model puts a reference when it is
    not told otherwise. The result is the one screen a founder reads, with a
    database key in the middle of a sentence.

    Stripped rather than re-prompted: an instruction reduces the rate, and this
    is a thing that must not happen rather than a thing that should be rare.
    """

    @staticmethod
    def _brief(narrative: str) -> str:
        from cairn_api.pipeline.synthesize import Brief, _narrative

        return _narrative(narrative, Brief())

    def test_a_trailing_parenthesised_id_goes(self) -> None:
        cleaned = self._brief(
            "The team moved throttling to the gateway (a4956a67-7998-4422-a12b-ddd66d436503)."
        )
        assert "a4956a67" not in cleaned
        assert cleaned == "The team moved throttling to the gateway."

    def test_several_ids_in_one_sentence_go(self) -> None:
        cleaned = self._brief(
            "Priya shipped rate limiting (fcfc0f55-ad29-4a55-a340-5c3750a2ddd3) "
            "and documented it (d7cc43c5-e81f-4300-95fc-bd824cab5527)."
        )
        assert "-" not in cleaned or "fcfc0f55" not in cleaned
        assert cleaned == "Priya shipped rate limiting and documented it."

    def test_a_bare_id_goes_too(self) -> None:
        """Not every leak arrives in brackets."""
        cleaned = self._brief("See a4956a67-7998-4422-a12b-ddd66d436503 for the decision.")
        assert "a4956a67" not in cleaned

    def test_ordinary_prose_is_untouched(self) -> None:
        """The cost of over-eager stripping is a mangled sentence, which is the
        failure this is meant to prevent."""
        original = "Sara is redesigning the onboarding flow (after the review)."
        assert self._brief(original) == original

    def test_a_narrative_that_was_only_an_id_does_not_become_empty_prose(self) -> None:
        """Stripping everything leaves nothing to say, and an empty narrative
        must fall back rather than render as a blank screen."""
        assert self._brief("a4956a67-7998-4422-a12b-ddd66d436503") == ""


class TestTheClaimBudgetIsExplicit:
    """The editorial lottery: forty candidates, "a short brief", ~6 claims of
    the model's choosing. Six consecutive generations missed the newest commit
    while repeating the same vivid stories, because nothing said how many
    claims to write or what must not be omitted."""

    def test_the_target_scales_with_candidates(self) -> None:
        from cairn_api.pipeline.synthesize import claim_target

        assert claim_target(3) == 4, "a quiet day is floored, not padded"
        assert claim_target(12) == 4
        assert claim_target(24) == 8
        assert claim_target(40) == 14, "a dense week gets coverage, not six"

    def test_the_target_never_exceeds_what_could_be_cited(self) -> None:
        from cairn_api.pipeline.synthesize import MAX_FACTS, claim_target

        assert claim_target(10_000) <= 15 < MAX_FACTS

    def test_the_instruction_names_the_three_sections(self) -> None:
        """The screen groups claims by certainty into Shipped / In motion /
        Worth a look (md/05 A.2.2). A model that does not know the sections
        exist can spend every claim on one of them, hiding the hedged tiers -
        which are where correction happens."""
        from cairn_api.pipeline.synthesize import INSTRUCTION

        for section in ("Shipped", "In motion", "Worth a look"):
            assert section in INSTRUCTION
        assert "Cover every tier" in INSTRUCTION

    async def test_the_built_request_carries_the_computed_budget(self) -> None:
        """Stated per-request, from the actual candidate count - a constant in
        the instruction would drift from what was retrieved."""
        from cairn_api.pipeline.provider import ScriptedProvider
        from cairn_api.pipeline.synthesize import synthesize

        provider = ScriptedProvider(default='{"narrative": "", "claims": []}')
        facts = [fact(statement=f"Delivered change number {i}.") for i in range(24)]
        await synthesize(provider, facts=facts)

        request = provider.calls[-1]
        assert "There are 24 facts" in request.instruction
        assert "about 8 claims" in request.instruction
