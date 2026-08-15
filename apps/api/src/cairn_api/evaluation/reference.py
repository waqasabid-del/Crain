"""Two stand-in pipelines, so the harness itself is verified.

`ReferencePipeline` reads a case's own expectations and returns them —
circular by construction, which proves the harness passes what it should.
`BrokenPipeline` fails on purpose, one failure mode at a time, so each metric
in `metrics.py` is shown to actually catch what it claims to.

Neither should be deleted once the real pipeline (Steps 15-18) exists: a
harness regression would otherwise be indistinguishable from a product one.
"""

from __future__ import annotations

from cairn_api.domain import Certainty
from cairn_api.evaluation.cases import GoldenCase
from cairn_api.evaluation.contract import Claim, PipelineOutput


class ReferencePipeline:
    """Returns exactly what each case expects; scores perfectly by
    construction, to prove a correct pipeline passes."""

    async def run(self, case: GoldenCase) -> PipelineOutput:
        if case.expects_abstention:
            return PipelineOutput(
                abstained=True,
                narrative="There is not enough information to summarise this period.",
            )

        claims = [
            Claim(
                text=expected.summary,
                citations=list(expected.must_cite),
                credits=list(expected.credits),
                certainty=expected.certainty,
            )
            for expected in case.expected_claims
        ]
        return PipelineOutput(
            claims=claims,
            narrative=" ".join(claim.text for claim in claims),
        )


class BrokenPipeline:
    """Fails one way per case, chosen by the failure mode the case targets —
    plausible mistakes, not random noise."""

    async def run(self, case: GoldenCase) -> PipelineOutput:
        if case.expects_abstention:
            return PipelineOutput(
                claims=[
                    Claim(
                        text="The team made steady progress this week.",
                        citations=[case.evidence[0].id],
                        credits=["priya"],
                        certainty=Certainty.VERIFIED,
                    )
                ],
                narrative="The team made steady progress this week.",
            )

        if case.id == "no-ranking-of-people":
            return PipelineOutput(
                claims=[
                    Claim(
                        text="Priya was the top performer this week.",
                        citations=[case.evidence[0].id],
                        credits=["priya"],
                        certainty=Certainty.VERIFIED,
                    )
                ],
                narrative="Priya was the top performer this week; Tom is underperforming.",
            )

        if case.id == "no-evaluative-tone":
            return PipelineOutput(
                claims=[
                    Claim(
                        text="Tom only managed one draft pull request.",
                        citations=[case.evidence[0].id],
                        credits=["tom"],
                        certainty=Certainty.VERIFIED,
                    )
                ],
                narrative="Tom fell behind this week and struggled with delivery.",
            )

        if case.id == "stale-fact-not-asserted-as-current":
            superseded = next(item for item in case.evidence if item.superseded)
            return PipelineOutput(
                claims=[
                    Claim(
                        text="Ali is picking up the auth work.",
                        citations=[superseded.id],
                        credits=["ali"],
                        certainty=Certainty.VERIFIED,
                    )
                ],
                narrative="Ali is picking up the auth work.",
            )

        if case.id == "meeting-inference-is-hedged":
            return PipelineOutput(
                claims=[
                    Claim(
                        text="The billing migration will slip to next sprint.",
                        citations=[case.evidence[0].id],
                        credits=["sam"],
                        certainty=Certainty.VERIFIED,
                    )
                ],
                narrative="The billing migration will slip to next sprint.",
            )

        if case.id == "github-bot-not-a-contributor":
            return PipelineOutput(
                claims=[
                    Claim(
                        text="Priya updated 40 dependencies.",
                        citations=[case.evidence[0].id],
                        credits=["priya"],
                        certainty=Certainty.VERIFIED,
                    )
                ],
                narrative="Priya updated 40 dependencies.",
            )

        if case.must_surface:
            # Summarise the trivia, omit the blocker.
            other = [item for item in case.evidence if item.id not in case.must_surface]
            if other:
                return PipelineOutput(
                    claims=[
                        Claim(
                            text=other[0].content,
                            citations=[other[0].id],
                            credits=list(other[0].people),
                            certainty=Certainty.VERIFIED,
                        )
                    ],
                    narrative=other[0].content,
                )

        # Default: cite evidence that does not exist.
        return PipelineOutput(
            claims=[
                Claim(
                    text="An invented summary of work nobody did.",
                    citations=["ev-does-not-exist"],
                    credits=["nobody"],
                    certainty=Certainty.VERIFIED,
                )
            ],
            narrative="An invented summary of work nobody did.",
        )
