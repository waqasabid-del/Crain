"""Aggregating case results into a report.

Failures are reported by category, never as a total (md/10 §6). Every ratio
carries its own denominator, so "100%" over zero cases can't be mistaken for
a passing metric.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cairn_api.evaluation.cases import FailureMode
from cairn_api.evaluation.metrics import CaseResult, Finding


def _ratio(numerator: int, denominator: int) -> float:
    """Returns 1.0 when nothing was measured — callers must report the
    denominator alongside it."""
    return numerator / denominator if denominator else 1.0


@dataclass(slots=True)
class EvaluationReport:
    """Everything one run measured."""

    dataset_version: str
    results: list[CaseResult] = field(default_factory=list)

    # -- Denominators, kept so a metric can be told from an absent one ------

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def total_claims(self) -> int:
        return sum(r.total_claims for r in self.results)

    @property
    def attributable_claims(self) -> int:
        return sum(r.attributable_claims for r in self.results)

    @property
    def must_surface_total(self) -> int:
        return sum(r.must_surface for r in self.results)

    @property
    def abstention_cases(self) -> int:
        return sum(1 for r in self.results if r.abstention_expected)

    @property
    def cases_with_claims(self) -> int:
        """Non-abstention cases that produced at least one claim — the
        denominator the gate checks before trusting any ratio."""
        return sum(1 for r in self.results if not r.abstention_expected and r.total_claims > 0)

    # -- Metrics -----------------------------------------------------------

    @property
    def groundedness(self) -> float:
        """Claims traceable to evidence that exists, over claims made."""
        return _ratio(sum(r.grounded_claims for r in self.results), self.total_claims)

    @property
    def attribution_accuracy(self) -> float:
        return _ratio(sum(r.correct_attributions for r in self.results), self.attributable_claims)

    @property
    def recall(self) -> float:
        """Labelled must-surface events that appeared in the output."""
        return _ratio(sum(r.surfaced for r in self.results), self.must_surface_total)

    @property
    def abstention_accuracy(self) -> float:
        """Cases where the honest answer was "not enough information"."""
        return _ratio(
            sum(1 for r in self.results if r.abstention_expected and r.abstention_correct),
            self.abstention_cases,
        )

    @property
    def case_coverage(self) -> float:
        """Non-abstention cases that produced a claim — every other number is
        meaningless when this is low."""
        expected = self.total_cases - self.abstention_cases
        return _ratio(self.cases_with_claims, expected)

    # -- Failures by category ---------------------------------------------

    @property
    def findings(self) -> list[Finding]:
        return [finding for result in self.results for finding in result.findings]

    def count(self, mode: FailureMode) -> int:
        return sum(1 for finding in self.findings if finding.mode is mode)

    @property
    def boundary_violations(self) -> int:
        return self.count(FailureMode.BOUNDARY_VIOLATION)

    @property
    def tone_violations(self) -> int:
        return self.count(FailureMode.TONE_VIOLATION)

    @property
    def fabrications(self) -> int:
        return self.count(FailureMode.FABRICATION)

    @property
    def misattributions(self) -> int:
        return self.count(FailureMode.MISATTRIBUTION)

    @property
    def stale_facts(self) -> int:
        return self.count(FailureMode.STALE_FACT)

    @property
    def overconfidence(self) -> int:
        return self.count(FailureMode.OVERCONFIDENCE)

    @property
    def missed_signals(self) -> int:
        return self.count(FailureMode.MISSED_SIGNAL)

    @property
    def blocked_cases(self) -> list[str]:
        return [r.case_id for r in self.results if r.blocked]

    # -- Rendering ---------------------------------------------------------

    def render(self) -> str:
        """A report someone reads without a dashboard."""
        lines = [
            f"CAIRN evaluation — dataset {self.dataset_version}, {self.total_cases} cases",
            "",
            "  metric                  value    over",
            "  " + "-" * 44,
            f"  groundedness          {self.groundedness:>7.1%}    {self.total_claims} claims",
            f"  attribution accuracy  {self.attribution_accuracy:>7.1%}    "
            f"{self.attributable_claims} attributed claims",
            f"  recall                {self.recall:>7.1%}    {self.must_surface_total} required events",
            f"  abstention accuracy   {self.abstention_accuracy:>7.1%}    "
            f"{self.abstention_cases} abstention cases",
            f"  case coverage         {self.case_coverage:>7.1%}    "
            f"{self.cases_with_claims}/{self.total_cases - self.abstention_cases} cases produced claims",
            "",
            "  failures by category",
            "  " + "-" * 44,
        ]

        by_mode = [
            ("boundary violation", self.boundary_violations, "BLOCKS RELEASE"),
            ("tone violation", self.tone_violations, "BLOCKS RELEASE"),
            ("fabrication", self.fabrications, ""),
            ("misattribution", self.misattributions, ""),
            ("stale fact", self.stale_facts, ""),
            ("overconfidence", self.overconfidence, ""),
            ("missed signal", self.missed_signals, ""),
        ]
        for name, count, note in by_mode:
            marker = f"  <- {note}" if count and note else ""
            lines.append(f"  {name:<22}{count:>5}{marker}")

        if self.findings:
            lines.extend(["", "  findings", "  " + "-" * 44])
            for finding in self.findings[:20]:
                lines.append(f"  {finding.case_id:<28} {finding.mode.value}: {finding.detail}")
            if len(self.findings) > 20:
                lines.append(f"  ... and {len(self.findings) - 20} more")

        return "\n".join(lines)
