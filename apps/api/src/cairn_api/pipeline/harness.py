"""The pipeline, as the Step 14 harness grades it: joins
`evaluation.contract.Pipeline` to the real Stages 1-4. Certainty passes
through unchanged, since the harness has an overconfidence metric.
"""

from __future__ import annotations

import structlog

from cairn_api.evaluation.cases import GoldenCase
from cairn_api.evaluation.contract import Claim, PipelineOutput
from cairn_api.pipeline.classify import classify
from cairn_api.pipeline.extract import extract
from cairn_api.pipeline.provider import ModelProvider
from cairn_api.pipeline.resolve import Outcome, resolve
from cairn_api.pipeline.synthesize import synthesize

logger = structlog.get_logger(__name__)


class UnderstandingPipeline:
    """Stages 1 to 4, wired for evaluation. Retrieval (Step 17) isn't in this
    path: a golden case already supplies the evidence under test."""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def run(self, case: GoldenCase) -> PipelineOutput:
        known = {item.id: item.source.value for item in case.evidence}
        content = "\n".join(
            f"[{item.id}] ({item.source.value}) {item.content}" for item in case.evidence
        )

        classification = await classify(self._provider, content=content)
        if not classification.event_class.should_extract:
            return PipelineOutput(
                abstained=True,
                narrative="Nothing in this period requires a summary.",
            )

        result = await extract(self._provider, content=content, known_evidence=known)
        if result.abstained or not result.facts:
            return PipelineOutput(
                abstained=True,
                narrative="There is not enough information to summarise this period.",
            )

        # Merged facts dropped, not reported: their sources moved to the merge target.
        plan = resolve(result.facts)
        resolved = [d.fact for d in plan.decisions if d.outcome is not Outcome.MERGED] + [
            fact for _, fact in plan.merges
        ]

        brief = await synthesize(self._provider, facts=resolved)
        if brief.abstained or not brief.claims:
            return PipelineOutput(abstained=True, narrative=brief.narrative)

        claims = [
            Claim(
                text=claim.text,
                citations=list(claim.citations),
                credits=list(claim.credits),
                certainty=claim.certainty,
            )
            for claim in brief.claims
        ]
        return PipelineOutput(claims=claims, narrative=brief.narrative)
