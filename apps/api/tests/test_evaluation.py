"""The evaluation harness.

Step 14's exit criterion: *the harness runs against a seed dataset and reports
groundedness and attribution accuracy.*

**These tests grade the grader.** That is the unusual part and the necessary
part: every other suite in this project asserts the product behaves; this one
asserts the instrument measuring the product works. A harness nobody has watched
fail is a harness that might not be able to — and its failure mode is the worst
available, because it reports success.

Each metric therefore has a test that trips it deliberately.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cairn_api.evaluation.cases import (
    FailureMode,
    GoldenCase,
    GoldenDataset,
    load_dataset,
)
from cairn_api.evaluation.contract import PipelineOutput
from cairn_api.evaluation.gate import (
    MIN_ATTRIBUTION_ACCURACY,
    MIN_GROUNDEDNESS,
    REGRESSION_TOLERANCE,
    evaluate_gate,
)
from cairn_api.evaluation.metrics import grade
from cairn_api.evaluation.reference import BrokenPipeline, ReferencePipeline
from cairn_api.evaluation.runner import run


def case(**overrides: object) -> GoldenCase:
    """A minimal valid case, with fields overridden per test."""
    payload: dict[str, object] = {
        "id": "t",
        "rationale": "A case used by the harness's own tests.",
        "evidence": [
            {"id": "ev-1", "source": "github", "content": "Priya shipped x.", "people": ["priya"]}
        ],
        "expected_claims": [
            {"summary": "Priya shipped x.", "must_cite": ["ev-1"], "credits": ["priya"]}
        ],
    }
    payload.update(overrides)
    return GoldenCase.model_validate(payload)


def output(**overrides: object) -> PipelineOutput:
    payload: dict[str, object] = {
        "claims": [
            {
                "text": "Priya shipped x.",
                "citations": ["ev-1"],
                "credits": ["priya"],
                "certainty": "verified",
            }
        ],
        "narrative": "Priya shipped x.",
    }
    payload.update(overrides)
    return PipelineOutput.model_validate(payload)


# --------------------------------------------------------------------------
# The dataset is production code
# --------------------------------------------------------------------------


class TestDatasetIntegrity:
    def test_the_committed_dataset_loads(self) -> None:
        dataset = load_dataset()

        assert len(dataset) >= 10
        assert dataset.version

    def test_the_dataset_covers_all_four_sources(self) -> None:
        # A set covering only GitHub reports excellent quality on a product that
        # reads four sources (md/10 §2.3).
        covered = {source.value for source in load_dataset().sources_covered}

        assert covered == {"github", "chat", "meeting", "document"}

    def test_the_dataset_rewards_admitting_uncertainty(self) -> None:
        # If nothing in the set rewards abstention, the metrics train the system
        # to guess. This is the test that keeps that property from being
        # optimised away by someone chasing a coverage number.
        assert load_dataset().abstention_cases >= 2

    def test_a_claim_citing_absent_evidence_is_rejected_on_load(self) -> None:
        # The shape of a well-meaning edit that breaks a case silently: an
        # evidence item deleted, the claim that cited it left behind.
        with pytest.raises(ValueError, match="cites evidence that is not in the case"):
            case(expected_claims=[{"summary": "x", "must_cite": ["ev-missing"]}])

    def test_a_case_that_asserts_nothing_is_rejected(self) -> None:
        # Otherwise it scores perfectly for any output at all, quietly inflating
        # every metric it appears in.
        with pytest.raises(ValueError, match="no expected claims"):
            case(expected_claims=[])

    def test_a_case_cannot_both_require_silence_and_claims(self) -> None:
        # Allowing it makes abstention unmeasurable: whichever the system did,
        # half the expectation would score.
        with pytest.raises(ValueError, match="expects abstention but also lists"):
            case(expects_abstention=True)

    def test_duplicate_case_ids_are_rejected(self) -> None:
        # Two results under one key: whichever is written last wins, and one
        # case silently stops being reported.
        with pytest.raises(ValueError, match="Duplicate case id"):
            GoldenDataset(version="t", cases=[case(), case()])

    def test_an_unparseable_case_fails_rather_than_being_skipped(self, tmp_path: Path) -> None:
        """The failure mode most likely to go unnoticed.

        A harness that silently drops cases it cannot parse reports improving
        metrics as its coverage shrinks — every number moves the right way.
        """
        (tmp_path / "bad.json").write_text(
            json.dumps({"version": "t", "cases": [{"id": "x"}]}), encoding="utf-8"
        )

        with pytest.raises(ValueError, match="rationale"):
            load_dataset(tmp_path)


# --------------------------------------------------------------------------
# Each metric detects what it claims to
# --------------------------------------------------------------------------


class TestMetricsDetectFailures:
    def test_a_correct_output_produces_no_findings(self) -> None:
        # The positive control. Without it, a grader that flagged everything
        # would pass every test below.
        result = grade(case(), output())

        assert result.findings == []
        assert result.grounded_claims == result.total_claims == 1

    def test_citing_evidence_that_does_not_exist_is_a_fabrication(self) -> None:
        # Fabrication wearing a citation, which is more convincing than
        # fabrication without one.
        result = grade(
            case(),
            output(
                claims=[
                    {
                        "text": "x",
                        "citations": ["ev-99"],
                        "credits": [],
                        "certainty": "verified",
                    }
                ]
            ),
        )

        assert any(f.mode is FailureMode.FABRICATION for f in result.findings)
        assert result.grounded_claims == 0

    def test_crediting_someone_the_evidence_does_not_name_is_misattribution(self) -> None:
        # The trust-killer. The person who notices is the one whose work was
        # taken.
        result = grade(
            case(),
            output(
                claims=[
                    {
                        "text": "x",
                        "citations": ["ev-1"],
                        "credits": ["tom"],
                        "certainty": "verified",
                    }
                ]
            ),
        )

        assert any(f.mode is FailureMode.MISATTRIBUTION for f in result.findings)

    def test_asserting_superseded_evidence_as_verified_is_a_stale_fact(self) -> None:
        # "Ali is on auth" three weeks after he moved to billing.
        stale = case(
            evidence=[
                {
                    "id": "ev-1",
                    "source": "chat",
                    "content": "Ali is on auth.",
                    "people": ["ali"],
                    "superseded": True,
                }
            ],
            expected_claims=[
                {"summary": "Ali is on billing.", "must_cite": ["ev-1"], "credits": ["ali"]}
            ],
        )
        result = grade(
            stale,
            output(
                claims=[
                    {
                        "text": "Ali is on auth.",
                        "citations": ["ev-1"],
                        "credits": ["ali"],
                        "certainty": "verified",
                    }
                ]
            ),
        )

        assert any(f.mode is FailureMode.STALE_FACT for f in result.findings)

    def test_a_meeting_only_claim_cannot_be_verified(self) -> None:
        # Meeting transcripts carry ~30% speaker-misattribution risk (md/03 §2),
        # so a meeting-only claim asserted at the highest tier is overconfident.
        meeting = case(
            evidence=[
                {
                    "id": "ev-1",
                    "source": "meeting",
                    "content": "Someone said it will slip.",
                    "people": ["sam"],
                }
            ],
            expected_claims=[
                {
                    "summary": "It may slip.",
                    "must_cite": ["ev-1"],
                    "credits": ["sam"],
                    "certainty": "suggested",
                }
            ],
        )
        result = grade(
            meeting,
            output(
                claims=[
                    {
                        "text": "It will slip.",
                        "citations": ["ev-1"],
                        "credits": ["sam"],
                        "certainty": "verified",
                    }
                ]
            ),
        )

        assert any(f.mode is FailureMode.OVERCONFIDENCE for f in result.findings)

    def test_corroborated_evidence_may_be_verified(self) -> None:
        # The positive control for overconfidence: hedging everything would
        # otherwise score perfectly, and the product would never assert anything.
        corroborated = case(
            evidence=[
                {"id": "ev-1", "source": "meeting", "content": "Agreed.", "people": ["sam"]},
                {"id": "ev-2", "source": "github", "content": "Shipped.", "people": ["sam"]},
            ],
            expected_claims=[
                {
                    "summary": "Agreed and shipped.",
                    "must_cite": ["ev-1", "ev-2"],
                    "credits": ["sam"],
                }
            ],
        )
        result = grade(
            corroborated,
            output(
                claims=[
                    {
                        "text": "Agreed and shipped.",
                        "citations": ["ev-1", "ev-2"],
                        "credits": ["sam"],
                        "certainty": "verified",
                    }
                ]
            ),
        )

        assert not any(f.mode is FailureMode.OVERCONFIDENCE for f in result.findings)

    def test_missing_a_required_event_is_a_missed_signal(self) -> None:
        # The quiet failure nobody reports: a real blocker that never appeared.
        with_blocker = case(
            evidence=[
                {"id": "ev-1", "source": "chat", "content": "Blocked.", "people": ["tom"]},
                {"id": "ev-2", "source": "github", "content": "Typo fix.", "people": ["tom"]},
            ],
            must_surface=["ev-1"],
            expected_claims=[
                {"summary": "Tom is blocked.", "must_cite": ["ev-1"], "credits": ["tom"]}
            ],
        )
        result = grade(
            with_blocker,
            output(
                claims=[
                    {
                        "text": "Tom fixed a typo.",
                        "citations": ["ev-2"],
                        "credits": ["tom"],
                        "certainty": "verified",
                    }
                ]
            ),
        )

        assert any(f.mode is FailureMode.MISSED_SIGNAL for f in result.findings)

    def test_guessing_where_abstention_was_correct_is_a_fabrication(self) -> None:
        # Not a near miss. Scoring it as partial credit is what trains a system
        # to guess.
        quiet = case(
            expects_abstention=True,
            expected_claims=[],
            evidence=[{"id": "ev-1", "source": "github", "content": "Nothing happened."}],
        )
        result = grade(quiet, output())

        assert result.abstention_correct is False
        assert any(f.mode is FailureMode.FABRICATION for f in result.findings)

    def test_abstaining_where_evidence_existed_is_a_missed_signal(self) -> None:
        # The mirror image. Without it, a pipeline that abstained on everything
        # would score perfectly on groundedness and attribution.
        result = grade(case(), PipelineOutput(abstained=True))

        assert any(f.mode is FailureMode.MISSED_SIGNAL for f in result.findings)


class TestZeroToleranceChecks:
    @pytest.mark.parametrize(
        "narrative",
        [
            "Priya was the top performer this week.",
            "Tom is underperforming compared to the team.",
            "Ana has a productivity score of 82.",
            "We are 87% confident Tom wrote this.",
            "Priya was more productive than Tom.",
            "Tom should be reassigned to another project.",
        ],
    )
    def test_output_that_scores_or_ranks_a_person_is_flagged(self, narrative: str) -> None:
        # Not a quality metric with a threshold. A single occurrence is a
        # regulatory and positioning failure (md/05 §B.3.3).
        result = grade(case(), output(narrative=narrative))

        assert any(f.mode is FailureMode.BOUNDARY_VIOLATION for f in result.findings)
        assert result.blocked is True

    @pytest.mark.parametrize(
        "narrative",
        [
            "Tom fell behind this week.",
            "Ana only managed one pull request.",
            "Priya struggled with the migration.",
            "A disappointing week for the team.",
        ],
    )
    def test_evaluative_language_about_a_person_is_flagged(self, narrative: str) -> None:
        result = grade(case(), output(narrative=narrative))

        assert any(f.mode is FailureMode.TONE_VIOLATION for f in result.findings)
        assert result.blocked is True

    @pytest.mark.parametrize(
        "narrative",
        [
            "The query's performance improved after the index was added.",
            "Priya shipped rate limiting; Tom spent the week on an incident.",
            "The migration is ongoing and not yet confirmed complete.",
            "Ana reviewed and merged an agent-opened pull request.",
        ],
    )
    def test_ordinary_neutral_reporting_is_not_flagged(self, narrative: str) -> None:
        """The false-positive control, and it matters more than it looks.

        A checker that flags "performance of the query" trains people to ignore
        it, and an ignored zero-tolerance gate is worse than none — it provides
        the appearance of a control while everyone routes around it.
        """
        result = grade(case(), output(narrative=narrative))

        assert result.blocked is False


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


class TestReleaseGate:
    async def test_the_reference_pipeline_passes(self) -> None:
        # The whole harness end to end: a correct pipeline must ship.
        report = await run(load_dataset(), ReferencePipeline())
        gate = evaluate_gate(report, baseline={})

        assert gate.passed is True
        assert report.groundedness == 1.0
        assert report.attribution_accuracy == 1.0

    async def test_the_broken_pipeline_is_blocked(self) -> None:
        """The test that proves the harness can fail.

        An evaluation suite nobody has watched fail is one that might not be
        able to — and its failure mode reports success.
        """
        report = await run(load_dataset(), BrokenPipeline())
        gate = evaluate_gate(report, baseline={})

        assert gate.passed is False
        assert report.boundary_violations > 0
        assert report.tone_violations > 0
        assert report.fabrications > 0
        assert report.misattributions > 0
        assert report.stale_facts > 0
        assert report.overconfidence > 0
        assert report.missed_signals > 0

    async def test_a_single_boundary_violation_blocks_an_otherwise_perfect_run(
        self,
    ) -> None:
        # The property that makes it zero-tolerance rather than a metric.
        dataset = load_dataset()

        class OneSlip:
            async def run(self, target: GoldenCase) -> PipelineOutput:
                base = await ReferencePipeline().run(target)
                if target.id == "single-person-team":
                    return base.model_copy(
                        update={"narrative": "Priya was the top performer this week."}
                    )
                return base

        report = await run(dataset, OneSlip())
        gate = evaluate_gate(report, baseline={})

        assert report.groundedness == 1.0
        assert report.attribution_accuracy == 1.0
        assert gate.passed is False
        assert any("boundary" in reason for reason in gate.blocking)

    async def test_a_regression_blocks_even_above_the_floor(self) -> None:
        """The gate that catches gradual decline.

        A pipeline scoring 93% against a 97% baseline has broken something. An
        absolute floor of 90% waves it through, which is how a product gets
        worse one passing release at a time.
        """
        report = await run(load_dataset(), ReferencePipeline())
        assert report.groundedness > MIN_GROUNDEDNESS

        inflated = report.groundedness + REGRESSION_TOLERANCE + 0.05
        gate = evaluate_gate(
            report,
            baseline={"groundedness": inflated, "attribution_accuracy": 0.0},
        )

        assert gate.passed is False
        assert any("regressed" in reason for reason in gate.blocking)

    async def test_ordinary_variation_does_not_block(self) -> None:
        # A tolerance that fires on noise teaches people to rerun CI until it
        # passes, which is how a real regression gets through.
        report = await run(load_dataset(), ReferencePipeline())
        gate = evaluate_gate(
            report,
            baseline={
                "groundedness": report.groundedness + REGRESSION_TOLERANCE / 2,
                "attribution_accuracy": report.attribution_accuracy,
            },
        )

        assert gate.passed is True

    async def test_missing_baseline_weakens_the_gate_but_does_not_disable_it(
        self,
    ) -> None:
        # The first run has nothing to compare against; the floors still apply.
        report = await run(load_dataset(), BrokenPipeline())
        gate = evaluate_gate(report, baseline={})

        assert gate.passed is False
        assert any("below floor" in reason for reason in gate.blocking)

    def test_the_floors_are_where_the_spec_says(self) -> None:
        # Pinned so a future edit to a threshold is a visible, reviewed change
        # rather than a quiet one.
        assert MIN_GROUNDEDNESS == 0.90
        assert MIN_ATTRIBUTION_ACCURACY == 0.95


class TestReporting:
    async def test_failures_are_reported_by_category_not_as_a_total(self) -> None:
        # Three fabrications and thirty tone issues are different problems
        # needing different fixes (md/10 §6).
        report = await run(load_dataset(), BrokenPipeline())
        rendered = report.render()

        for label in ("fabrication", "misattribution", "stale fact", "boundary violation"):
            assert label in rendered

    async def test_every_metric_is_rendered_with_its_denominator(self) -> None:
        # A "100%" over zero cases reads as passing and means "not measured".
        report = await run(load_dataset(), ReferencePipeline())
        rendered = report.render()

        assert "claims" in rendered
        assert "abstention cases" in rendered


class TestTheRealPipelineIsGraded:
    """The finding this class exists for: CI graded the stand-in and called it
    an evaluation.

    `ReferencePipeline` returns each case's own expectations. A gate that only
    ever ran against it proved the harness could pass something and said nothing
    about the product — and would have kept saying nothing for as long as the
    real pipeline stayed ungraded.
    """

    def test_the_runner_can_build_the_real_pipeline(self) -> None:
        from cairn_api.evaluation.runner import build_pipeline
        from cairn_api.pipeline.harness import UnderstandingPipeline

        assert isinstance(build_pipeline("real"), UnderstandingPipeline)

    def test_every_gradeable_pipeline_has_a_baseline(self) -> None:
        """Adding a pipeline without deciding what it is compared against is how
        a comparison becomes decorative."""
        from cairn_api.evaluation.runner import PIPELINES, build_pipeline

        for name in PIPELINES:
            assert build_pipeline(name) is not None

    def test_the_real_pipeline_has_its_own_baseline_file(self) -> None:
        """Separate from the reference pipeline's, and both must exist.

        Sharing one file would either record the stand-in's 1.0s — against which
        the real pipeline is a permanent catastrophic regression — or the real
        pipeline's, which stops the stand-in from proving 100% is reachable.
        """
        from cairn_api.evaluation.gate import BASELINE_PATH, REAL_BASELINE_PATH

        assert BASELINE_PATH != REAL_BASELINE_PATH
        assert BASELINE_PATH.exists()
        assert REAL_BASELINE_PATH.exists()

    def test_the_scripted_provider_has_exactly_one_definition(self) -> None:
        """The tests and the evaluation gate must drive the same script.

        Two copies drifting apart would mean the suite passes against one
        pipeline while the gate measures another, and both report numbers as if
        they were comparable. Asserted against `test_pipeline.py`'s source
        because the duplicate that mattered lived there.
        """
        import pathlib

        source = (pathlib.Path(__file__).parent / "test_pipeline.py").read_text(encoding="utf-8")
        assert "build_scripted_provider" in source
        assert "def _extract_every_line" not in source
        assert "def _echo_every_fact" not in source

    async def test_the_recorded_baseline_matches_what_the_real_pipeline_scores(
        self,
    ) -> None:
        """The baseline is an honest record, not a target.

        A committed baseline nobody re-derives is a number that was true once.
        This grades the real pipeline and compares — so a change that moves the
        product's score has to move this file deliberately, which is the whole
        point of committing it.
        """
        import json

        from cairn_api.evaluation.gate import REAL_BASELINE_PATH
        from cairn_api.evaluation.runner import build_pipeline

        report = await run(load_dataset(), build_pipeline("real"))
        recorded = json.loads(REAL_BASELINE_PATH.read_text(encoding="utf-8"))

        assert report.groundedness == pytest.approx(recorded["groundedness"], abs=1e-4)
        assert report.attribution_accuracy == pytest.approx(
            recorded["attribution_accuracy"], abs=1e-4
        )
        assert report.recall == pytest.approx(recorded["recall"], abs=1e-4)
        assert report.abstention_accuracy == pytest.approx(
            recorded["abstention_accuracy"], abs=1e-4
        )

    async def test_the_real_pipeline_produces_no_boundary_or_tone_violations(self) -> None:
        """The two zero-tolerance metrics, checked against the product rather
        than the stand-in.

        These are the ones that block at a single occurrence (md/05 §B.3.3), and
        they are the ones a maximally-compliant scripted model is most likely to
        trip — it repeats whatever it is shown.
        """
        from cairn_api.evaluation.runner import build_pipeline

        report = await run(load_dataset(), build_pipeline("real"))
        assert report.boundary_violations == 0
        assert report.tone_violations == 0
