"""Running the harness.

Run with ``make eval``, or ``uv run python -m cairn_api.evaluation.runner``.

Three pipelines: ``reference`` (correct by construction) and ``broken`` (fails
on purpose) verify the harness itself; ``real`` grades
`pipeline.harness.UnderstandingPipeline`, the actual product. CI has no model
credentials, so ``real`` is driven by a deterministic scripted provider
(bound documented in `scripted.py`).

The md/10 §4 local/PR/nightly/production rhythm is a matter of where this
runs — one runner serves all four, so results are comparable.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from cairn_api import telemetry
from cairn_api.evaluation.cases import GoldenDataset, load_dataset
from cairn_api.evaluation.contract import Pipeline
from cairn_api.evaluation.gate import (
    BASELINE_PATH,
    REAL_BASELINE_PATH,
    GateProfile,
    evaluate_gate,
    load_baseline,
    write_baseline,
)
from cairn_api.evaluation.metrics import grade
from cairn_api.evaluation.report import EvaluationReport

#: Which pipelines can be graded, and which baseline each is measured against.
#: A table, not an `if` chain, so a new pipeline forces "compared to what?"
#: to be answered at the same time.
PIPELINES: dict[str, Path] = {
    "reference": BASELINE_PATH,
    "broken": BASELINE_PATH,
    "real": REAL_BASELINE_PATH,
}


async def run(dataset: GoldenDataset, pipeline: Pipeline) -> EvaluationReport:
    """Grade a pipeline against every case.

    Sequential, not concurrent: the harness isn't the bottleneck, and
    parallel cases would interleave a failure's log lines with others'.
    """
    report = EvaluationReport(dataset_version=dataset.version)
    for case in dataset:
        output = await pipeline.run(case)
        result = grade(case, output)
        report.results.append(result)
        # One counter per case, by outcome and by the mode that blocked it.
        # `blocked` is the release-gate question; a case with softer findings
        # still counts as a pass here, as it does in the gate.
        telemetry.record_evaluation(
            result="blocked" if result.blocked else "ok",
            failure_mode=next(
                (finding.mode.value for finding in result.findings if result.blocked), None
            ),
        )
    return report


def build_pipeline(name: str) -> Pipeline:
    """Construct one of the gradeable pipelines.

    Imports are local so ``--pipeline reference`` doesn't pay for (or break
    on) an import error in a stage it isn't grading.
    """
    if name == "reference":
        from cairn_api.evaluation.reference import ReferencePipeline

        return ReferencePipeline()
    if name == "broken":
        from cairn_api.evaluation.reference import BrokenPipeline

        return BrokenPipeline()
    if name == "real":
        from cairn_api.evaluation.scripted import build_scripted_provider
        from cairn_api.pipeline.harness import UnderstandingPipeline

        # Built here, not accepted as an argument, so CI and a laptop can't
        # grade against different scripts and call the numbers comparable.
        return UnderstandingPipeline(build_scripted_provider())

    msg = f"Unknown pipeline {name!r}. Choose one of: {', '.join(sorted(PIPELINES))}."
    raise SystemExit(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CAIRN evaluation harness.")
    parser.add_argument(
        "--pipeline",
        default="reference",
        choices=sorted(PIPELINES),
        help=(
            "Which pipeline to grade. 'real' is the product; 'reference' passes "
            "by construction and 'broken' fails on purpose, and both grade the "
            "harness rather than the product."
        ),
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help=(
            "Baseline to compare against. Defaults to the one belonging to the "
            "chosen pipeline; override only to inspect a comparison, never to "
            "find a baseline a failing run passes."
        ),
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Record this run's metrics as the new baseline. Deliberately manual: "
            "auto-updating lets a decline ratchet, because each run sets the bar "
            "wherever it landed."
        ),
    )
    args = parser.parse_args(argv)

    baseline_path = args.baseline or PIPELINES[args.pipeline]

    dataset = load_dataset(args.dataset)
    report = asyncio.run(run(dataset, build_pipeline(args.pipeline)))
    # "real" is judgement-free in CI, so it's graded on machinery only (see
    # GateProfile).
    profile = GateProfile.MACHINERY if args.pipeline == "real" else GateProfile.FULL
    gate = evaluate_gate(report, baseline=load_baseline(baseline_path), profile=profile)

    print(f"pipeline: {args.pipeline}    baseline: {baseline_path.name}")
    print()
    print(report.render())
    print()
    print(gate.render())

    if args.update_baseline:
        if not gate.passed:
            print("\nRefusing to update the baseline from a blocked run.")
            return 1
        print(f"\nBaseline updated: {write_baseline(report, baseline_path)}")

    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
