"""What the pipeline produces: facts with provenance.

`sources` is required and non-empty, so a fact without provenance cannot be
constructed. Certainty is categorical, never numeric (md/05 §A.2.1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from cairn_api.domain import Certainty


class FactKind(enum.StrEnum):
    """What sort of statement this is. Deliberately few and glossary-free."""

    DELIVERY = "delivery"

    DECISION = "decision"

    #: The one whose absence nobody reports (md/10 §1).
    BLOCKER = "blocker"

    IN_PROGRESS = "in_progress"

    OPEN_QUESTION = "open_question"


class SourceRef(BaseModel):
    """Where a fact came from: resolvable to the thing itself (Step 21)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(min_length=1)

    #: `github`, `chat`, `meeting`, `document`.
    source: str = Field(min_length=1)

    quote: str | None = Field(default=None, max_length=2000)

    url: str | None = None

    #: Never asked of the model — read from the delivery, not invented.
    project: str | None = Field(default=None, max_length=200)


class Fact(BaseModel):
    """One statement the pipeline asserts, with everything needed to check it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID = Field(default_factory=uuid.uuid4)

    kind: FactKind

    #: Bounded: this is model output from attacker-influenceable text.
    statement: str = Field(min_length=1, max_length=1000)

    sources: list[SourceRef] = Field(min_length=1)

    certainty: Certainty

    #: Empty is legitimate here, unlike empty `sources`.
    people: list[str] = Field(default_factory=list)

    #: When the event happened, not when extracted: supersession (Step 16) orders
    #: by occurrence so a backfill cannot overwrite current state.
    occurred_at: datetime | None = None

    @field_validator("statement")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        """Reject rather than strip: a stripped string is a statement nobody wrote."""
        if any(char < " " and char not in "\n\t" for char in value):
            msg = "statement contains control characters"
            raise ValueError(msg)
        return value

    @property
    def evidence_ids(self) -> list[str]:
        return [ref.evidence_id for ref in self.sources]


class ExtractionResult(BaseModel):
    """Everything Stage 2 produced for one event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: list[Fact] = Field(default_factory=list)

    #: Explicit: "nothing to say" and "found nothing" differ.
    abstained: bool = False

    #: Notes for the operator, never the user — kept off `Fact` itself.
    diagnostics: list[str] = Field(default_factory=list)
