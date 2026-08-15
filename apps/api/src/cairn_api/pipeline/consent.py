"""Opting out of a source, and what that actually does.

Retroactive: existing attributions unlink immediately, not just future data.
Removes the attribution, not the work — facts and briefs keep their text
(md/01 §5.2). `fact_people` keeps the raw mention and drops `person_id`: an
opted-out person becomes a name nobody has matched.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource

logger = structlog.get_logger(__name__)

#: Listed rather than derived from connected integrations (md/11 §4.1).
SOURCES: tuple[str, ...] = ("github", "chat", "meeting", "document")


async def opt_out(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID, source: str
) -> int:
    """Record an opt-out; returns the number of attributions unlinked."""
    if source not in SOURCES:
        msg = f"Unknown source: {source}"
        raise ValueError(msg)

    await session.execute(
        insert(SourceOptOut)
        .values(tenant_id=tenant_id, person_id=person_id, source=source)
        .on_conflict_do_nothing(constraint="uq_source_opt_outs_person_source")
    )

    removed = await _unlink_existing(
        session, tenant_id=tenant_id, person_id=person_id, source=source
    )
    await session.flush()

    await logger.ainfo(
        "consent.opted_out",
        tenant_id=str(tenant_id),
        source=source,
        unlinked=removed,
    )
    return removed


async def opt_in(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID, source: str
) -> None:
    """Withdraw an opt-out. Nothing is restored: only future activity is
    attributed again."""
    await session.execute(
        delete(SourceOptOut).where(
            SourceOptOut.tenant_id == tenant_id,
            SourceOptOut.person_id == person_id,
            SourceOptOut.source == source,
        )
    )
    await session.flush()

    await logger.ainfo("consent.opted_in", tenant_id=str(tenant_id), source=source)


async def opted_out_sources(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID
) -> set[str]:
    rows = await session.scalars(
        select(SourceOptOut.source).where(
            SourceOptOut.tenant_id == tenant_id, SourceOptOut.person_id == person_id
        )
    )
    return set(rows)


async def opted_out_people(
    session: AsyncSession, *, tenant_id: uuid.UUID, source: str
) -> set[uuid.UUID]:
    """Read once per batch rather than per fact."""
    rows = await session.scalars(
        select(SourceOptOut.person_id).where(
            SourceOptOut.tenant_id == tenant_id, SourceOptOut.source == source
        )
    )
    return set(rows)


async def _unlink_existing(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID, source: str
) -> int:
    """The row and mention stay; `person_id` becomes null. A fact citing
    multiple sources unlinks if *any* matches."""
    matching = (
        select(FactRow.id)
        .join(FactSource, FactSource.fact_id == FactRow.id)
        .where(FactRow.tenant_id == tenant_id, FactSource.source == source)
    )

    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(FactPerson)
            .where(
                FactPerson.tenant_id == tenant_id,
                FactPerson.person_id == person_id,
                FactPerson.fact_id.in_(matching),
            )
            .values(person_id=None)
        ),
    )
    return int(result.rowcount or 0)
