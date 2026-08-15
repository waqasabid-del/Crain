"""Applying a resolution plan to the fact graph.

`resolve.py` decides; this module writes — kept separate so the rules are testable as pure functions. Supersession must be atomic: `ck_facts_supersession_is_complete` requires `valid_until` and `superseded_by_id` together, so the successor is flushed first. Nothing here deletes (tenant removal cascades). `apply` fetches only candidates a predicate proven to be a *superset* of `resolve()`'s rules could match (`_candidates`) — every choice there errs wide.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import ColumnElement, Select, and_, any_, false, literal, or_, select, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactOrigin, FactPerson, FactSource
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Membership
from cairn_api.domain import Certainty
from cairn_api.pipeline import mentions
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from cairn_api.pipeline.resolve import (
    MERGE_WINDOW,
    SUPERSEDES,
    Decision,
    Outcome,
    ResolutionPlan,
    resolve,
    subject_key,
    tokens,
)

logger = structlog.get_logger(__name__)

#: Most candidate facts one batch may pull into memory; a trip is logged
#: (`resolve.candidates_truncated`) rather than silently losing merges.
MAX_CANDIDATES = 5_000


async def load_current(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Fact]:
    """Currently-valid facts, as resolution understands them; superseded rows
    are excluded, not filtered later."""
    rows = await session.scalars(_current(tenant_id))
    return [_to_domain(row) for row in rows]


def _current(tenant_id: uuid.UUID) -> Select[tuple[FactRow]]:
    """Currently-valid facts for one workspace, oldest first — `resolve()`
    breaks ties by position, so order must be deterministic."""
    return (
        select(FactRow)
        .where(FactRow.tenant_id == tenant_id, FactRow.valid_until.is_(None))
        .order_by(FactRow.occurred_at.nullsfirst(), FactRow.id)
    )


async def _candidates(
    session: AsyncSession, *, tenant_id: uuid.UUID, incoming: list[Fact]
) -> list[Fact]:
    """Currently-valid facts `resolve()` could possibly match this batch to.

    Must be a superset of `resolve()`'s rules — too narrow silently breaks
    merging/supersession (md/09 §3.2). Merge: kind + window + ≥1 shared token
    (real rule ≥3). Supersession: kind + ≥1 shared subject token, no time
    window. `ILIKE '%t%'` safely over-approximates "shares token".
    """
    if not incoming:
        return []

    branches: list[ColumnElement[bool]] = []
    for fact in incoming:
        window: ColumnElement[bool] = true()
        if fact.occurred_at is not None:
            window = or_(
                FactRow.occurred_at.is_(None),
                FactRow.occurred_at.between(
                    fact.occurred_at - MERGE_WINDOW, fact.occurred_at + MERGE_WINDOW
                ),
            )
        branches.append(
            and_(
                FactRow.kind == fact.kind.value,
                window,
                _mentions_any(tokens(fact.statement)),
            )
        )

        supersedable = SUPERSEDES.get(fact.kind, frozenset())
        if supersedable:
            branches.append(
                and_(
                    FactRow.kind.in_([kind.value for kind in supersedable]),
                    _mentions_any(subject_key(fact.statement)),
                )
            )

    # Newest first for the cut only; re-sorted below.
    statement = (
        _current(tenant_id)
        .where(or_(*branches))
        .order_by(None)
        .order_by(FactRow.occurred_at.desc().nullslast(), FactRow.id)
        .limit(MAX_CANDIDATES + 1)
    )
    rows = list(await session.scalars(statement))

    if len(rows) > MAX_CANDIDATES:
        rows = rows[:MAX_CANDIDATES]
        await logger.awarning(
            "resolve.candidates_truncated",
            tenant_id=str(tenant_id),
            incoming=len(incoming),
            ceiling=MAX_CANDIDATES,
        )

    # Back into `_current`'s order; datetime.min stands in for undated (NULLS FIRST).
    epoch = datetime.min.replace(tzinfo=UTC)
    rows.sort(key=lambda row: (row.occurred_at or epoch, row.id))
    return [_to_domain(row) for row in rows]


def _mentions_any(candidate_tokens: frozenset[str]) -> ColumnElement[bool]:
    """`statement ILIKE ANY (ARRAY[...])` for one fact's tokens: one array
    parameter per fact rather than one `OR` per token. An empty token set
    matches nothing, matching what `resolve()` would do."""
    if not candidate_tokens:
        return false()
    patterns = [f"%{token}%" for token in sorted(candidate_tokens)]
    return FactRow.statement.ilike(any_(literal(patterns, ARRAY(Text))))


async def apply(
    session: AsyncSession, *, tenant_id: uuid.UUID, incoming: list[Fact]
) -> ResolutionPlan:
    """Resolve a batch against the store and persist the outcome. Returns the
    plan as the audit trail behind a disputed brief."""
    current = await _candidates(session, tenant_id=tenant_id, incoming=incoming)
    plan = resolve(incoming, current)

    for decision in plan.decisions:
        if decision.outcome is Outcome.MERGED:
            await _apply_merge(session, tenant_id, decision)
        elif decision.outcome is Outcome.SUPERSEDES:
            await _apply_supersession(session, tenant_id, decision)
        else:
            await _insert(session, tenant_id, decision.fact)

        # Flushed per decision: a later decision may merge into a fact this loop just created.
        await session.flush()

    await logger.ainfo(
        "resolve.applied",
        tenant_id=str(tenant_id),
        **{
            outcome.value: sum(1 for d in plan.decisions if d.outcome is outcome)
            for outcome in Outcome
        },
    )
    return plan


async def _apply_merge(session: AsyncSession, tenant_id: uuid.UUID, decision: Decision) -> None:
    """Fold a duplicate into the fact already on record — no new row."""
    row = await session.get(FactRow, decision.merged_into)
    if row is None:
        # Resolved against a stale snapshot; insert rather than fail (a race duplicate beats a lost fact).
        await logger.awarning("resolve.merge_target_missing", fact_id=str(decision.merged_into))
        await _insert(session, tenant_id, decision.fact)
        return

    known = {(s.source, s.evidence_id) for s in row.sources}
    for ref in decision.fact.sources:
        if (ref.source, ref.evidence_id) not in known:
            row.sources.append(
                FactSource(
                    tenant_id=tenant_id,
                    source=ref.source,
                    evidence_id=ref.evidence_id,
                    quote=ref.quote,
                    url=ref.url,
                )
            )

    mentioned = {p.mention for p in row.people}
    for mention in decision.fact.people:
        if mention not in mentioned:
            row.people.append(FactPerson(tenant_id=tenant_id, mention=mention))

    row.certainty = decision.fact.certainty.value
    row.occurred_at = decision.fact.occurred_at


async def _apply_supersession(
    session: AsyncSession, tenant_id: uuid.UUID, decision: Decision
) -> None:
    """Store the new fact and close the one it replaces. The successor is
    flushed first so `superseded_by_id` points at a real row."""
    successor = await _insert(session, tenant_id, decision.fact)
    await session.flush()

    predecessor = await session.get(FactRow, decision.supersedes)
    if predecessor is None:
        await logger.awarning("resolve.supersede_target_missing", fact_id=str(decision.supersedes))
        return

    # Marked, never deleted (md/12 §6) — only the validity window closes.
    predecessor.valid_until = decision.fact.occurred_at or datetime.now(UTC)
    predecessor.superseded_by_id = successor.id
    predecessor.supersession_reason = decision.reason[:500]


async def _insert(session: AsyncSession, tenant_id: uuid.UUID, fact: Fact) -> FactRow:
    row = FactRow(
        id=fact.id,
        tenant_id=tenant_id,
        kind=fact.kind.value,
        statement=fact.statement,
        certainty=fact.certainty.value,
        origin=FactOrigin.EXTRACTED,
        occurred_at=fact.occurred_at,
        valid_from=fact.occurred_at or datetime.now(UTC),
        sources=[
            FactSource(
                tenant_id=tenant_id,
                source=ref.source,
                evidence_id=ref.evidence_id,
                quote=ref.quote,
                url=ref.url,
                project=ref.project,
            )
            for ref in fact.sources
        ],
        people=[FactPerson(tenant_id=tenant_id, mention=name) for name in fact.people],
    )
    session.add(row)
    return row


async def attach_people(session: AsyncSession, *, tenant_id: uuid.UUID, fact_id: uuid.UUID) -> None:
    """Resolve one stored fact's mentions to people; delegates to
    `attach_people_bulk` for a single implementation."""
    await attach_people_bulk(session, tenant_id=tenant_id, fact_ids=[fact_id])


async def attach_people_bulk(
    session: AsyncSession, *, tenant_id: uuid.UUID, fact_ids: Sequence[uuid.UUID]
) -> None:
    """Resolve a whole batch of facts' mentions in one pass; replaces an N+1
    by loading facts in one `IN` query and deduplicating mentions first."""
    if not fact_ids:
        return

    rows = list(
        await session.scalars(
            select(FactRow).where(FactRow.tenant_id == tenant_id, FactRow.id.in_(fact_ids))
        )
    )
    links = [link for row in rows for link in row.people]
    if not links:
        return

    names = sorted({link.mention for link in links})  # sorted for deterministic logs
    resolution = await mentions.resolve_mentions(session, tenant_id=tenant_id, names=names)

    sources_by_fact = {row.id: {source.source for source in row.sources} for row in rows}
    opted_out = await _opt_outs_for(session, tenant_id, sources_by_fact)
    unnotified = await _unnotified_people(session, tenant_id)

    by_mention = {m.raw: m for m in resolution.mentions}
    for link in links:
        match = by_mention.get(link.mention)
        # Only ever set, never cleared — a human-confirmed link must survive an automatic pass.
        if match is None or match.person_id is None or link.person_id is not None:
            continue

        # Opt-out enforced at attribution time, not read time, so nothing depends on remembering to filter later.
        blocked = opted_out.get(match.person_id, set())
        if blocked & sources_by_fact.get(link.fact_id, set()):
            continue

        # Legal obligation, no regional exception (md/05 §B.3.5): no attribution before first-capture notification.
        if match.person_id in unnotified:
            continue

        link.person_id = match.person_id


async def _unnotified_people(session: AsyncSession, tenant_id: uuid.UUID) -> set[uuid.UUID]:
    """People whose worker notification has not been served. Members only —
    a row with no linked user has no one CAIRN could notify."""
    rows = await session.scalars(
        select(Person.id)
        .join(Membership, Membership.user_id == Person.user_id)
        .where(
            Person.tenant_id == tenant_id,
            Membership.tenant_id == tenant_id,
            Membership.notified_at.is_(None),
        )
    )
    return set(rows)


async def _opt_outs_for(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    sources_by_fact: dict[uuid.UUID, set[str]],
) -> dict[uuid.UUID, set[str]]:
    """Opt-outs relevant to this batch, keyed by person; scoped to the
    sources the batch touches rather than loading the workspace's full history."""
    sources = {source for values in sources_by_fact.values() for source in values}
    if not sources:
        return {}

    rows = await session.execute(
        select(SourceOptOut.person_id, SourceOptOut.source).where(
            SourceOptOut.tenant_id == tenant_id, SourceOptOut.source.in_(sources)
        )
    )

    blocked: dict[uuid.UUID, set[str]] = {}
    for person_id, source in rows:
        blocked.setdefault(person_id, set()).add(source)
    return blocked


def _to_domain(row: FactRow) -> Fact:
    """A stored row as resolution sees it."""
    return Fact(
        id=row.id,
        kind=FactKind(row.kind),
        statement=row.statement,
        sources=[
            SourceRef(
                evidence_id=source.evidence_id,
                source=source.source,
                quote=source.quote,
                url=source.url,
                project=source.project,
            )
            for source in row.sources
        ],
        certainty=Certainty(row.certainty),
        people=[p.mention for p in row.people],
        occurred_at=row.occurred_at,
    )


#: Public alias: the API's brief endpoint needs the same row→domain mapping.
to_domain = _to_domain
