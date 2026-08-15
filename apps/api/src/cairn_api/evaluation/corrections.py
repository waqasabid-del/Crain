"""Turning production corrections into evaluation cases.

md/10 §2.1: every human correction becomes an evaluation case — it's already a
labelled example (evidence in, expected claim out, failure mode named); the
only work here is translation.

Export is explicit, never automatic — nothing here writes to the repository.
A case needs review, the dataset gates releases (a write path into it is an
attack surface), and corrections contain customer content (md/10 §5). This
produces cases and prints them; a human commits them.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactOrigin
from cairn_api.domain import Certainty
from cairn_api.evaluation.cases import Evidence, ExpectedClaim, FailureMode, GoldenCase, Source

logger = structlog.get_logger(__name__)

#: The failure each correction kind is evidence of (md/10 §1 taxonomy).
#: `no_longer_true` is a stale fact, not a fabrication — the system was right
#: when it said it.
FAILURE_MODES: dict[str, FailureMode] = {
    "reworded": FailureMode.FABRICATION,
    "did_not_happen": FailureMode.FABRICATION,
    "wrong_person": FailureMode.MISATTRIBUTION,
    "no_longer_true": FailureMode.STALE_FACT,
}

_SOURCES = {source.value for source in Source}


class SkipReason(enum.StrEnum):
    """Why a correction did not become a case."""

    #: No quoted span — the only text is the sentence under test, a circular case.
    NO_EVIDENCE_TEXT = "no_evidence_text"

    #: Same thing in different words — a style preference, not a defect.
    WORDING_ONLY = "wording_only"

    UNKNOWN_SOURCE = "unknown_source"


@dataclass(frozen=True, slots=True)
class Skipped:
    """One correction that produced no case, and why."""

    fact_id: uuid.UUID
    reason: SkipReason


@dataclass
class Harvest:
    """Everything one export pass found."""

    cases: list[GoldenCase]
    skipped: list[Skipped]


async def harvest(session: AsyncSession, *, tenant_id: uuid.UUID) -> Harvest:
    """Build golden cases from this workspace's corrections (`origin = 'correction'`
    rows and the facts they replaced)."""
    corrections = list(
        await session.scalars(
            select(FactRow).where(
                FactRow.tenant_id == tenant_id,
                FactRow.origin == FactOrigin.CORRECTION,
            )
        )
    )

    cases: list[GoldenCase] = []
    skipped: list[Skipped] = []

    for correction in corrections:
        original = await _original_of(session, correction)
        built = _build_case(correction, original)
        if isinstance(built, Skipped):
            skipped.append(built)
            continue
        cases.append(built)

    await logger.ainfo(
        "corrections.harvested",
        tenant_id=str(tenant_id),
        corrections=len(corrections),
        cases=len(cases),
        skipped=len(skipped),
    )
    return Harvest(cases=cases, skipped=skipped)


async def _original_of(session: AsyncSession, correction: FactRow) -> FactRow | None:
    """The fact this correction replaced, if it replaced one. A denial marks the
    original row as a correction rather than creating a new one, so it is its
    own original."""
    if correction.valid_until is not None:
        return correction

    original: FactRow | None = await session.scalar(
        select(FactRow).where(FactRow.superseded_by_id == correction.id)
    )
    return original


def _build_case(correction: FactRow, original: FactRow | None) -> GoldenCase | Skipped:
    """One case, or the reason there is not one."""
    if original is None:
        return Skipped(fact_id=correction.id, reason=SkipReason.NO_EVIDENCE_TEXT)

    denied = original.id == correction.id
    reason = original.supersession_reason or ""
    kind = _kind_from(reason)

    evidence: list[Evidence] = []
    for index, source in enumerate(original.sources):
        if source.source not in _SOURCES:
            return Skipped(fact_id=correction.id, reason=SkipReason.UNKNOWN_SOURCE)
        if not source.quote:
            # Without a retained span, the only text is the fact's own statement
            # — a circular case. Fix is upstream, not worked around here.
            return Skipped(fact_id=correction.id, reason=SkipReason.NO_EVIDENCE_TEXT)

        evidence.append(
            Evidence(
                id=f"{source.source}-{index}",
                source=Source(source.source),
                content=source.quote,
                people=[link.mention for link in original.people],
                occurred_at=original.occurred_at.isoformat() if original.occurred_at else None,
            )
        )

    if not evidence:
        return Skipped(fact_id=correction.id, reason=SkipReason.NO_EVIDENCE_TEXT)

    if not denied and _same_meaning(original.statement, correction.statement):
        return Skipped(fact_id=correction.id, reason=SkipReason.WORDING_ONLY)

    return GoldenCase(
        id=f"correction-{correction.id}",
        rationale=(
            f"A person corrected this in production. CAIRN said: "
            f'"{original.statement}". '
            + (
                "They said it did not happen."
                if denied
                else f'They said: "{correction.statement}".'
            )
            + f" Recorded as {kind}."
        ),
        evidence=evidence,
        expects_abstention=denied,
        expected_claims=(
            []
            if denied
            else [
                ExpectedClaim(
                    summary=correction.statement,
                    must_cite=[item.id for item in evidence],
                    credits=[link.mention for link in original.people],
                    certainty=Certainty.VERIFIED,
                )
            ]
        ),
        targets=[FAILURE_MODES.get(kind, FailureMode.FABRICATION)],
        tags=["origin:correction", f"correction:{kind}"],
    )


def _kind_from(reason: str) -> str:
    """Recover the correction kind from the stored reason (not a second column
    that could drift from it)."""
    lowered = reason.lower()
    if "did not happen" in lowered:
        return "did_not_happen"
    if "wrong person" in lowered:
        return "wrong_person"
    if "no longer true" in lowered:
        return "no_longer_true"
    return "reworded"


def _same_meaning(original: str, corrected: str) -> bool:
    """Whether a correction only changed the wording. Deliberately crude — errs
    toward keeping a case, since a false positive would drop a real failure."""
    return _words(original) == _words(corrected)


def _words(text: str) -> frozenset[str]:
    return frozenset(word.strip(".,;:!?'\"").lower() for word in text.split() if len(word) > 2)
