"""What the pipeline must produce for the harness to grade it.

Two invariants: every claim must carry citations, and certainty is
categorical — no confidence float, since the UI may never display a
percentage (md/05 §A.2.1).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from cairn_api.domain import Certainty
from cairn_api.evaluation.cases import Evidence, GoldenCase


class Claim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)

    #: Required, no default — a claim citing nothing is a fabrication.
    citations: list[str] = Field(min_length=1)

    credits: list[str] = Field(default_factory=list)

    certainty: Certainty


class PipelineOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: list[Claim] = Field(default_factory=list)

    #: Explicit, not inferred from an empty claim list: "nothing to say" != "found nothing".
    abstained: bool = False

    #: Graded for tone/boundary compliance, which live in prose.
    narrative: str = ""


class Pipeline(Protocol):
    """Evidence in, claims out — narrow so the harness grades output, not internals."""

    async def run(self, case: GoldenCase) -> PipelineOutput: ...


class EvidenceIndex:
    def __init__(self, evidence: list[Evidence]) -> None:
        self._by_id = {item.id: item for item in evidence}

    def get(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id)

    def exists(self, evidence_id: str) -> bool:
        return evidence_id in self._by_id

    def people_for(self, evidence_ids: list[str]) -> set[str]:
        people: set[str] = set()
        for evidence_id in evidence_ids:
            item = self._by_id.get(evidence_id)
            if item is not None:
                people.update(item.people)
        return people

    def any_superseded(self, evidence_ids: list[str]) -> bool:
        return any(
            (item := self._by_id.get(evidence_id)) is not None and item.superseded
            for evidence_id in evidence_ids
        )
