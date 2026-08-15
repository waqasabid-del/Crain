"""Human correction as an input, not a UI affordance (md/09 §9 / md/05 §B.2.3).

Supersedes rather than overwrites: the original keeps its row and gains
`valid_until` plus a pointer to its replacement. The correction inherits the
original's sources and is `verified` certainty — the one place certainty is
set by something other than the extractor.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactOrigin, FactPerson, FactSource
from cairn_api.domain import Certainty

logger = structlog.get_logger(__name__)


class CorrectionKind(enum.StrEnum):
    """What the person is saying is wrong. Four options, not free text, so
    each maps onto the existing failure taxonomy (md/10 §1)."""

    REWORDED = "reworded"
    DID_NOT_HAPPEN = "did_not_happen"

    #: Misattribution: it happened, but not to this person.
    WRONG_PERSON = "wrong_person"

    NO_LONGER_TRUE = "no_longer_true"

    @property
    def requires_replacement(self) -> bool:
        return self is CorrectionKind.REWORDED

    @property
    def accepts_replacement(self) -> bool:
        """Wider than `requires_replacement`: `wrong_person` accepts an
        optional replacement ("it was Tom, not me")."""
        return self in {CorrectionKind.REWORDED, CorrectionKind.WRONG_PERSON}


class CorrectionError(ValueError):
    pass


async def apply_correction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    fact_id: uuid.UUID,
    kind: CorrectionKind,
    user_id: uuid.UUID,
    statement: str | None = None,
    note: str | None = None,
) -> FactRow | None:
    """Record a person's correction of one fact.

    Returns `None` when the correction retires the original without replacing
    it (e.g. "this did not happen").
    """
    original = await session.get(FactRow, fact_id)
    if original is None or original.tenant_id != tenant_id:
        # Redundant behind row-level security, but stated anyway.
        msg = "No such fact in this workspace"
        raise CorrectionError(msg)

    if original.valid_until is not None:
        msg = "That fact has already been superseded"
        raise CorrectionError(msg)

    if kind.requires_replacement and not (statement or "").strip():
        msg = "A reworded correction needs the corrected sentence"
        raise CorrectionError(msg)

    supplied = (statement or "").strip()
    if supplied and not kind.accepts_replacement:
        msg = f"A '{kind.value}' correction does not take a replacement sentence"
        raise CorrectionError(msg)

    now = datetime.now(UTC)
    replacement: FactRow | None = None

    if supplied:
        replacement = FactRow(
            tenant_id=tenant_id,
            kind=original.kind,
            statement=supplied,
            certainty=Certainty.VERIFIED.value,
            origin=FactOrigin.CORRECTION,
            corrected_by_user_id=user_id,
            occurred_at=original.occurred_at,
            valid_from=now,
            sources=[
                FactSource(
                    tenant_id=tenant_id,
                    source=source.source,
                    evidence_id=source.evidence_id,
                    quote=source.quote,
                    url=source.url,
                )
                for source in original.sources
            ],
            people=[
                FactPerson(
                    tenant_id=tenant_id,
                    person_id=link.person_id,
                    mention=link.mention,
                )
                for link in original.people
            ],
        )
        session.add(replacement)
        await session.flush()

    original.valid_until = now
    original.superseded_by_id = replacement.id if replacement is not None else None
    original.supersession_reason = _reason(kind, note)

    if replacement is None:
        # Check constraint requires a named person here, so retirement always has an author.
        original.origin = FactOrigin.CORRECTION
        original.corrected_by_user_id = user_id

    await session.flush()

    await logger.ainfo(
        "fact.corrected",
        tenant_id=str(tenant_id),
        fact_id=str(fact_id),
        kind=kind.value,
        replaced=replacement is not None,
    )
    return replacement


def _reason(kind: CorrectionKind, note: str | None) -> str:
    """Written for an audit-trail reader, not a machine."""
    base = {
        CorrectionKind.REWORDED: "Corrected by the person it concerns",
        CorrectionKind.DID_NOT_HAPPEN: "Denied by the person it concerns — this did not happen",
        CorrectionKind.WRONG_PERSON: "The wrong person was credited",
        CorrectionKind.NO_LONGER_TRUE: "No longer true",
    }[kind]
    trimmed = (note or "").strip()
    return f"{base}: {trimmed}"[:500] if trimmed else base
