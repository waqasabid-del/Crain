"""The golden dataset: what correct output looks like.

Production code, not test fixtures (md/10 §2.2), validated on load so a
quietly edited ground-truth label can't vanish a regression from the metrics.
`expects_abstention` is first-class, not an edge case (md/10 §2.3).
"""

from __future__ import annotations

import enum
import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cairn_api.domain import Certainty

DATASET_DIR = Path(__file__).parent / "dataset"


class Source(enum.StrEnum):
    """Where an evidence item came from. Must span all four (md/10 §2.3)."""

    GITHUB = "github"
    CHAT = "chat"
    MEETING = "meeting"
    DOCUMENT = "document"


#: Re-exported from `cairn_api.domain`, the canonical definition — kept importable
#: from this module since production code used to import it from here.
__all_certainty__ = Certainty


class FailureMode(enum.StrEnum):
    """The taxonomy from md/10 §1."""

    FABRICATION = "fabrication"
    MISATTRIBUTION = "misattribution"
    STALE_FACT = "stale_fact"
    OVERCONFIDENCE = "overconfidence"
    MISSED_SIGNAL = "missed_signal"
    TONE_VIOLATION = "tone_violation"
    BOUNDARY_VIOLATION = "boundary_violation"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    source: Source
    #: What groundedness is checked against — an unsupported citation is fabrication.
    content: str = Field(min_length=1)

    people: list[str] = Field(default_factory=list)

    #: "Ali is on auth" is correct in March, stale in April.
    occurred_at: str | None = None

    #: A claim resting on superseded evidence asserts a stale fact (md/09 §3.2).
    superseded: bool = False


class ExpectedClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Matched loosely — checked for being made and grounded, not exact wording.
    summary: str = Field(min_length=1)

    must_cite: list[str] = Field(min_length=1)

    #: Measured against exactly this set — extra credit is as wrong as missing one.
    credits: list[str] = Field(default_factory=list)

    certainty: Certainty = Certainty.OBSERVED


class GoldenCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)

    #: Required: a case whose purpose nobody recorded can't safely be changed.
    rationale: str = Field(min_length=10)

    evidence: list[Evidence] = Field(min_length=1)
    expected_claims: list[ExpectedClaim] = Field(default_factory=list)

    #: The correct answer is "not enough information" (md/10 §2.3).
    expects_abstention: bool = False

    #: Events the output must surface — measured against a labelled list.
    must_surface: list[str] = Field(default_factory=list)

    targets: list[FailureMode] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_internal_consistency(self) -> GoldenCase:
        """Reject a case that cannot be satisfied, so a bad edit fails on load
        instead of showing up as an unexplained metric shift."""
        evidence_ids = {item.id for item in self.evidence}

        for claim in self.expected_claims:
            missing = set(claim.must_cite) - evidence_ids
            if missing:
                msg = (
                    f"Case {self.id!r}: claim cites evidence that is not in the "
                    f"case: {sorted(missing)}"
                )
                raise ValueError(msg)

        missing_surface = set(self.must_surface) - evidence_ids
        if missing_surface:
            msg = f"Case {self.id!r}: must_surface names unknown evidence {sorted(missing_surface)}"
            raise ValueError(msg)

        if self.expects_abstention and self.expected_claims:
            # Can't require both silence and claims.
            msg = f"Case {self.id!r}: expects abstention but also lists expected claims"
            raise ValueError(msg)

        if not self.expects_abstention and not self.expected_claims:
            # Otherwise any output scores perfect, inflating metrics.
            msg = f"Case {self.id!r}: has no expected claims and does not expect abstention"
            raise ValueError(msg)

        return self


class GoldenDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    cases: list[GoldenCase] = Field(min_length=1)

    @model_validator(mode="after")
    def check_ids_are_unique(self) -> GoldenDataset:
        seen: set[str] = set()
        for case in self.cases:
            if case.id in seen:
                # Duplicate IDs make a case silently unreportable.
                msg = f"Duplicate case id {case.id!r}"
                raise ValueError(msg)
            seen.add(case.id)
        return self

    def __iter__(self) -> Iterator[GoldenCase]:  # type: ignore[override]
        return iter(self.cases)

    def __len__(self) -> int:
        return len(self.cases)

    @property
    def sources_covered(self) -> set[Source]:
        return {item.source for case in self.cases for item in case.evidence}

    @property
    def abstention_cases(self) -> int:
        return sum(1 for case in self.cases if case.expects_abstention)


def load_dataset(directory: Path | None = None) -> GoldenDataset:
    """Load and validate the committed dataset. Raises on the first malformed
    case rather than skipping it — silently dropping cases would report
    improving metrics as coverage shrinks."""
    root = directory or DATASET_DIR
    files = sorted(root.glob("*.json"))
    if not files:
        msg = f"No evaluation cases found in {root}"
        raise FileNotFoundError(msg)

    cases: list[GoldenCase] = []
    version = "unknown"
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = payload.get("version", version)
        for raw in payload.get("cases", []):
            cases.append(GoldenCase.model_validate(raw))

    return GoldenDataset(version=version, cases=cases)
