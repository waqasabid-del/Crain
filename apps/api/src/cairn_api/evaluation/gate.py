"""The release gate.

Gates only on the metric matching the most expensive failure (md/10 §5); the
rest is tracked but non-blocking. Boundary and tone violations block at one
occurrence, not a rate (md/05 §B.3.3). Regression is checked against a
committed baseline so a gradual decline can't slip past every release.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from pathlib import Path

from cairn_api.evaluation.report import EvaluationReport

#: Committed with the dataset. Editing it to make a failing run pass is the
#: same class of act as editing ground truth.
BASELINE_PATH = Path(__file__).parent / "baseline.json"

#: Separate from the reference pipeline's baseline: `ReferencePipeline` scores
#: 1.0 by construction, so a shared file would flag the real pipeline as a
#: catastrophic regression on every run.
REAL_BASELINE_PATH = Path(__file__).parent / "baseline-real.json"

MIN_GROUNDEDNESS = 0.90

#: Higher than groundedness: a fabrication is caught by a reader who checks; a
#: wrongly credited claim is caught by the person whose work was taken.
MIN_ATTRIBUTION_ACCURACY = 0.95

REGRESSION_TOLERANCE = 0.02

#: Without this, a pipeline that abstains on everything scores 100% over zero claims.
MIN_CASE_COVERAGE = 0.95


@dataclass(frozen=True, slots=True)
class GateResult:
    """Whether this run may ship, and why not."""

    passed: bool
    blocking: list[str]
    warnings: list[str]

    def render(self) -> str:
        lines = ["PASS" if self.passed else "BLOCKED"]
        lines.extend(f"  BLOCK   {reason}" for reason in self.blocking)
        lines.extend(f"  warn    {reason}" for reason in self.warnings)
        return "\n".join(lines)


def load_baseline(path: Path | None = None) -> dict[str, float]:
    """The last accepted run's metrics. Missing is not an error (first run) —
    absolute floors still apply."""
    target = path or BASELINE_PATH
    if not target.exists():
        return {}
    data: dict[str, float] = json.loads(target.read_text(encoding="utf-8"))
    return data


class GateProfile(enum.StrEnum):
    """Not a strictness setting — thresholds are identical. `MACHINERY` (the only
    option in CI) has no discretion, so judgement metrics are reported but
    non-blocking (see `pipeline/live_check.py`)."""

    FULL = "full"
    MACHINERY = "machinery"


def evaluate_gate(
    report: EvaluationReport,
    *,
    baseline: dict[str, float] | None = None,
    profile: GateProfile = GateProfile.FULL,
) -> GateResult:
    """Decide whether a run may ship."""
    baseline = baseline if baseline is not None else load_baseline()
    blocking: list[str] = []
    warnings: list[str] = []

    if report.boundary_violations:
        blocking.append(
            f"{report.boundary_violations} boundary violation(s) — any occurrence blocks "
            "(md/05 §B.3.3)"
        )
    if report.tone_violations:
        blocking.append(
            f"{report.tone_violations} tone violation(s) — any occurrence blocks (md/05 §A.5)"
        )

    # Checked before any ratio is trusted (0/0 = 1.0).
    expected_cases = report.total_cases - report.abstention_cases
    if expected_cases and report.cases_with_claims < expected_cases * MIN_CASE_COVERAGE:
        message = (
            f"only {report.cases_with_claims}/{expected_cases} cases produced any claim — "
            "metrics computed over too few claims to mean anything"
        )
        # Under MACHINERY, low coverage often just means guardrails stripped
        # everything the scripted model produced — not blocking.
        (blocking if profile is GateProfile.FULL else warnings).append(message)

    if report.groundedness < MIN_GROUNDEDNESS:
        blocking.append(
            f"groundedness {report.groundedness:.1%} below floor {MIN_GROUNDEDNESS:.0%}"
        )
    if report.attribution_accuracy < MIN_ATTRIBUTION_ACCURACY:
        blocking.append(
            f"attribution accuracy {report.attribution_accuracy:.1%} below floor "
            f"{MIN_ATTRIBUTION_ACCURACY:.0%}"
        )

    for name, current in (
        ("groundedness", report.groundedness),
        ("attribution_accuracy", report.attribution_accuracy),
    ):
        previous = baseline.get(name)
        if previous is None:
            continue
        if current < previous - REGRESSION_TOLERANCE:
            blocking.append(f"{name} regressed: {current:.1%} vs baseline {previous:.1%}")

    if report.abstention_accuracy < 1.0 and report.abstention_cases:
        warnings.append(
            f"abstention accuracy {report.abstention_accuracy:.0%} — "
            + (
                "the system guessed where the honest answer was 'not enough information'"
                if profile is GateProfile.FULL
                else "measured against a scripted model with no discretion; this number "
                "means something only once a real model drives the run"
            )
        )
    if report.recall < 1.0 and report.must_surface_total:
        warnings.append(f"recall {report.recall:.0%} — a labelled must-surface event was missed")
    if report.stale_facts:
        warnings.append(f"{report.stale_facts} stale fact(s) asserted as current")
    if report.overconfidence:
        warnings.append(f"{report.overconfidence} overconfident claim(s)")

    return GateResult(passed=not blocking, blocking=blocking, warnings=warnings)


def write_baseline(report: EvaluationReport, path: Path | None = None) -> Path:
    """Record this run's metrics as the new baseline. A separate, explicit action —
    auto-updating on a passing run would let a decline ratchet unnoticed."""
    target = path or BASELINE_PATH

    # Keys starting with "_" are human notes and must survive a re-record.
    notes: dict[str, object] = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
        if isinstance(existing, dict):
            notes = {key: value for key, value in existing.items() if key.startswith("_")}

    target.write_text(
        json.dumps(
            {
                **notes,
                "groundedness": round(report.groundedness, 4),
                "attribution_accuracy": round(report.attribution_accuracy, 4),
                "recall": round(report.recall, 4),
                "abstention_accuracy": round(report.abstention_accuracy, 4),
                "dataset_version": report.dataset_version,
                "cases": report.total_cases,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target
