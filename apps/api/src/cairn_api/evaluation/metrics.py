"""The metrics.

One per failure mode from md/10 §1 — "summary quality" is not a metric.

None of these is an LLM judge: every check is deterministic set arithmetic
(citations exist and name the credited people; credited set matches labelled
set; boundary breach against a fixed vocabulary). A judge needs calibration
against human-graded data that doesn't exist yet (md/10 §3.1); it belongs in
`judge.py`, once it does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cairn_api.domain import Certainty
from cairn_api.evaluation.cases import FailureMode, GoldenCase
from cairn_api.evaluation.contract import EvidenceIndex, PipelineOutput
from cairn_api.pipeline.guardrails import BOUNDARY_PATTERNS, TONE_PATTERNS


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing wrong with one output."""

    case_id: str
    mode: FailureMode
    detail: str


@dataclass(slots=True)
class CaseResult:
    """How one case scored."""

    case_id: str

    #: Claims traceable to evidence that exists, over claims made.
    grounded_claims: int = 0
    total_claims: int = 0

    #: Claims whose credited people match the labelled truth.
    correct_attributions: int = 0
    attributable_claims: int = 0

    #: Whether this case's ground truth credits anybody at all. Kept separate
    #: from `attributable_claims` so the gate can tell "attributed correctly"
    #: from "never attributed, scored 1.0 over nothing".
    attribution_expected: bool = False

    #: Labelled must-surface evidence that appeared in some citation.
    surfaced: int = 0
    must_surface: int = 0

    #: Whether abstention was expected and delivered.
    abstention_expected: bool = False
    abstention_correct: bool = False

    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Whether this case contains a release-blocking failure."""
        return any(
            finding.mode in {FailureMode.BOUNDARY_VIOLATION, FailureMode.TONE_VIOLATION}
            for finding in self.findings
        )


# ---------------------------------------------------------------------------
# Zero-tolerance checks
# ---------------------------------------------------------------------------


#: Imported from `pipeline.guardrails`, not redefined here: a gate checking
#: different rules from the product would pass things the product still does.
def check_boundaries(case: GoldenCase, output: PipelineOutput) -> list[Finding]:
    """Scan every word the product would show a user — narrative and claim
    text, since structured fields are rendered too."""
    return _scan(case, output, BOUNDARY_PATTERNS, FailureMode.BOUNDARY_VIOLATION)


def check_tone(case: GoldenCase, output: PipelineOutput) -> list[Finding]:
    return _scan(case, output, TONE_PATTERNS, FailureMode.TONE_VIOLATION)


def _scan(
    case: GoldenCase,
    output: PipelineOutput,
    patterns: tuple[tuple[str, str], ...],
    mode: FailureMode,
) -> list[Finding]:
    haystack = " ".join([output.narrative, *(claim.text for claim in output.claims)])
    findings: list[Finding] = []
    for pattern, reason in patterns:
        match = re.search(pattern, haystack, re.IGNORECASE)
        if match is not None:
            findings.append(
                Finding(case_id=case.id, mode=mode, detail=f"{reason}: {match.group(0)!r}")
            )
    return findings


# ---------------------------------------------------------------------------
# Scored metrics
# ---------------------------------------------------------------------------


def grade(case: GoldenCase, output: PipelineOutput) -> CaseResult:
    """Score one output against one case."""
    result = CaseResult(case_id=case.id, abstention_expected=case.expects_abstention)
    index = EvidenceIndex(case.evidence)

    result.findings.extend(check_boundaries(case, output))
    result.findings.extend(check_tone(case, output))

    if case.expects_abstention:
        result.abstention_correct = output.abstained and not output.claims
        if not result.abstention_correct:
            # A guess where the honest answer was abstention is fabrication,
            # not a near miss — no partial credit.
            result.findings.append(
                Finding(
                    case_id=case.id,
                    mode=FailureMode.FABRICATION,
                    detail=(f"expected abstention, got {len(output.claims)} claim(s)"),
                )
            )
        return result

    if output.abstained:
        # Abstaining where evidence existed is missed signal.
        result.findings.append(
            Finding(
                case_id=case.id,
                mode=FailureMode.MISSED_SIGNAL,
                detail="abstained despite sufficient evidence",
            )
        )

    _grade_claims(case, output, index, result)
    _grade_coverage(case, output, result)
    return result


#: ASCII apostrophe in most editors, which is why linters reject it in source.
#: Written as a codepoint: the literal character is indistinguishable from an
_CURLY_APOSTROPHE = chr(0x2019)


def _bare(word: str) -> str:
    """Strip trailing punctuation and the possessive, so "Priya's" gives "priya"."""
    plain = word.replace(_CURLY_APOSTROPHE, "'")
    return plain.strip(".,;:").removesuffix("'s")


def _resolve(mention: str, labelled: set[str]) -> str | None:
    """Map a model's mention of a person onto the handle the case labels them by.

    A model writes "Priya Nair"; the dataset labels her "priya". Comparing the
    two literally scored every correct attribution as a misattribution — the
    metric was measuring name formatting, not whether the right person was
    credited. In production this mapping is `identity.resolution` against a
    workspace's accounts; the harness has no account store, so it matches on
    the labelled handle appearing as the whole mention or one of its words.

    **Deliberately not fuzzy, and deliberately refuses ambiguity.** No prefix or
    substring matching, so "pri" never becomes "priya"; and a mention matching
    two labelled people resolves to neither, because crediting one of two
    candidates at random is the failure this metric exists to catch.
    """
    text = mention.strip().casefold()
    if not text:
        return None
    # Trailing punctuation and the possessive, so "Priya's" resolves to "priya".
    words = {_bare(word) for word in text.split()}
    matches = {
        handle for handle in labelled if handle.casefold() == text or handle.casefold() in words
    }
    return matches.pop() if len(matches) == 1 else None


def _grade_claims(
    case: GoldenCase,
    output: PipelineOutput,
    index: EvidenceIndex,
    result: CaseResult,
) -> None:
    expected_credits = {person for claim in case.expected_claims for person in claim.credits}
    result.attribution_expected = bool(expected_credits)

    for claim in output.claims:
        result.total_claims += 1

        unknown = [ref for ref in claim.citations if not index.exists(ref)]
        if unknown:
            # Fabrication wearing a citation — worse than fabrication alone.
            result.findings.append(
                Finding(
                    case_id=case.id,
                    mode=FailureMode.FABRICATION,
                    detail=f"cites evidence that does not exist: {unknown}",
                )
            )
            continue

        result.grounded_claims += 1

        if index.any_superseded(claim.citations) and claim.certainty is Certainty.VERIFIED:
            result.findings.append(
                Finding(
                    case_id=case.id,
                    mode=FailureMode.STALE_FACT,
                    detail=f"asserts superseded evidence as verified: {claim.citations}",
                )
            )

        if claim.credits:
            result.attributable_claims += 1
            supported = index.people_for(claim.citations)
            resolved = {credit: _resolve(credit, supported) for credit in claim.credits}
            wrong = {credit for credit, handle in resolved.items() if handle is None}
            if wrong:
                # Measured per claim, not averaged, since misattribution
                # destroys trust irrecoverably.
                result.findings.append(
                    Finding(
                        case_id=case.id,
                        mode=FailureMode.MISATTRIBUTION,
                        detail=f"credits people the cited evidence does not name: {sorted(wrong)}",
                    )
                )
            elif expected_credits and not set(resolved.values()) <= expected_credits:
                result.findings.append(
                    Finding(
                        case_id=case.id,
                        mode=FailureMode.MISATTRIBUTION,
                        detail=f"credits someone the case does not expect: {sorted(claim.credits)}",
                    )
                )
            else:
                result.correct_attributions += 1

        if _is_overconfident(case, claim.citations, claim.certainty):
            result.findings.append(
                Finding(
                    case_id=case.id,
                    mode=FailureMode.OVERCONFIDENCE,
                    detail=f"asserts meeting-derived evidence as {claim.certainty.value}",
                )
            )


def _is_overconfident(case: GoldenCase, citations: list[str], certainty: Certainty) -> bool:
    """Whether a claim asserts noisy evidence too strongly.

    Meeting transcripts carry ~30% speaker-misattribution risk (md/03 §2), so
    a claim resting only on a meeting cannot honestly be VERIFIED. Checks the
    whole citation set, since corroboration from another source earns the tier.
    """
    if certainty is not Certainty.VERIFIED:
        return False
    by_id = {item.id: item for item in case.evidence}
    cited = [by_id[ref] for ref in citations if ref in by_id]
    return bool(cited) and all(item.source.value == "meeting" for item in cited)


def _grade_coverage(case: GoldenCase, output: PipelineOutput, result: CaseResult) -> None:
    result.must_surface = len(case.must_surface)
    if not case.must_surface:
        return

    cited = {ref for claim in output.claims for ref in claim.citations}
    for required in case.must_surface:
        if required in cited:
            result.surfaced += 1
        else:
            result.findings.append(
                Finding(
                    case_id=case.id,
                    mode=FailureMode.MISSED_SIGNAL,
                    detail=f"did not surface required evidence {required!r}",
                )
            )
