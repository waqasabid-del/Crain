"""Retrieval: vector entry points, graph traversal, temporal filtering.
Traversal answers multi-hop questions similarity alone can't (md/09 §3.1).
Superseded facts excluded in the query, not the result (§3.2). Bounded to
md/09 §4.1's token working set (§4.2, context rot)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import structlog
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api import telemetry
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.graph_models import EdgeKind, FactEdge, FactEmbedding
from cairn_api.pipeline.embeddings import DEFAULT_EMBEDDING_MODEL, EmbeddingProvider

logger = structlog.get_logger(__name__)

DEFAULT_ENTRY_POINTS = 8  # kept small: a starting position, not the answer

#: Two: past this, `SAME_SUBJECT` edges start returning most of the workspace.
DEFAULT_MAX_HOPS = 2

DEFAULT_BUDGET_CHARS = 60_000  # ~15K tokens, inside md/09 §4.1's window

#: `SUPERSEDES` excluded as a second layer; the temporal filter is the real control.
CURRENT_EDGE_KINDS = (
    EdgeKind.SHARED_EVIDENCE,
    EdgeKind.SHARED_PERSON,
    EdgeKind.SAME_SUBJECT,
)


@dataclass(frozen=True, slots=True)
class RetrievedFact:
    fact: FactRow

    hops: int  # 0 for an entry point, 1 for its neighbours, and so on
    via: EdgeKind | None = None  # the edge kind that led here; None for entry points

    #: Entry points only. Internal — never a confidence (md/05 §A.2.1).
    distance: float | None = None

    because: str | None = None


@dataclass
class Retrieval:
    facts: list[RetrievedFact] = field(default_factory=list)

    #: True when expansion stopped at the budget rather than running out of graph.
    truncated: bool = False

    @property
    def fact_ids(self) -> list[uuid.UUID]:
        return [item.fact.id for item in self.facts]

    def for_context(self) -> list[RetrievedFact]:
        """Ordered for placement in a prompt (md/09 §4.3): entry points last."""
        return sorted(self.facts, key=lambda item: -item.hops)


async def retrieve(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    question: str,
    embedder: EmbeddingProvider,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    since: datetime | None = None,
    until: datetime | None = None,
    as_of: datetime | None = None,
    entry_points: int = DEFAULT_ENTRY_POINTS,
    max_hops: int = DEFAULT_MAX_HOPS,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    include_history: bool = False,
) -> Retrieval:
    """Answer a question with a bounded, connected set of facts.

    Args:
        as_of: What was believed at a moment in time, distinct from the
            activity window (`since`/`until`).
        include_history: Traverse supersession edges. Off by default.
    """
    with telemetry.stage("retrieval", tenant_id=str(tenant_id)):
        vector = (await embedder.embed([question]))[0]

        entries = await _entry_points(
            session,
            tenant_id=tenant_id,
            vector=vector,
            model_name=model_name,
            since=since,
            until=until,
            as_of=as_of,
            limit=entry_points,
        )

        retrieval = Retrieval()
        seen: set[uuid.UUID] = set()
        spent = 0

        for row, distance in entries:
            cost = len(row.statement)
            if spent + cost > budget_chars:
                retrieval.truncated = True
                break
            retrieval.facts.append(RetrievedFact(fact=row, hops=0, distance=distance))
            seen.add(row.id)
            spent += cost

        frontier = list(seen)
        kinds = (
            (*CURRENT_EDGE_KINDS, EdgeKind.SUPERSEDES) if include_history else CURRENT_EDGE_KINDS
        )

        for hop in range(1, max_hops + 1):
            if not frontier or retrieval.truncated:
                break

            neighbours = await _expand(
                session,
                tenant_id=tenant_id,
                frontier=frontier,
                kinds=kinds,
                exclude=seen,
                since=since,
                until=until,
                as_of=as_of,
            )

            next_frontier: list[uuid.UUID] = []
            for row, edge in neighbours:
                cost = len(row.statement)
                if spent + cost > budget_chars:
                    retrieval.truncated = True
                    break
                retrieval.facts.append(
                    RetrievedFact(fact=row, hops=hop, via=edge.kind, because=edge.detail)
                )
                seen.add(row.id)
                next_frontier.append(row.id)
                spent += cost

            frontier = next_frontier

        await logger.ainfo(
            "retrieval.completed",
            tenant_id=str(tenant_id),
            entry_points=len(entries),
            retrieved=len(retrieval.facts),
            truncated=retrieval.truncated,
            chars=spent,
        )
        return retrieval


async def _entry_points(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    vector: list[float],
    model_name: str,
    since: datetime | None,
    until: datetime | None,
    as_of: datetime | None,
    limit: int,
) -> list[tuple[FactRow, float]]:
    """Nearest facts by cosine distance, joined against validity so a
    post-filter can't silently shrink the result set."""
    distance = FactEmbedding.embedding.cosine_distance(vector).label("distance")
    statement = (
        select(FactRow, distance)
        .join(FactEmbedding, FactEmbedding.fact_id == FactRow.id)
        .where(FactEmbedding.tenant_id == tenant_id, FactEmbedding.model == model_name)
        .order_by(distance)
        .limit(limit)
    )
    statement = statement.where(*_temporal_conditions(since=since, until=until, as_of=as_of))

    rows = await session.execute(statement)
    return [(row[0], float(row[1])) for row in rows]


async def _expand(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    frontier: list[uuid.UUID],
    kinds: tuple[EdgeKind, ...],
    exclude: set[uuid.UUID],
    since: datetime | None,
    until: datetime | None,
    as_of: datetime | None,
) -> list[tuple[FactRow, FactEdge]]:
    """One hop out from the frontier, ordered by edge weight so a budget
    cutoff mid-hop keeps the strongest connections."""
    statement = (
        select(FactRow, FactEdge)
        .join(FactEdge, FactEdge.target_fact_id == FactRow.id)
        .where(
            FactEdge.tenant_id == tenant_id,
            FactEdge.source_fact_id.in_(frontier),
            FactEdge.kind.in_(kinds),
        )
        .order_by(FactEdge.weight.desc())
    )
    statement = statement.where(*_temporal_conditions(since=since, until=until, as_of=as_of))

    seen_here: set[uuid.UUID] = set()
    results: list[tuple[FactRow, FactEdge]] = []
    for row in await session.execute(statement):
        fact, edge = row[0], row[1]
        if fact.id in exclude or fact.id in seen_here:
            continue
        seen_here.add(fact.id)
        results.append((fact, edge))
    return results


def _temporal_conditions(
    *,
    since: datetime | None,
    until: datetime | None,
    as_of: datetime | None,
) -> list[ColumnElement[bool]]:
    """Validity (believed at `as_of`, or now) and activity window
    (`since`/`until`), as conditions so every query gets the same filters."""
    conditions: list[ColumnElement[bool]] = []

    if as_of is None:
        conditions.append(FactRow.valid_until.is_(None))
    else:
        conditions.append(FactRow.valid_from <= as_of)
        conditions.append(or_(FactRow.valid_until.is_(None), FactRow.valid_until > as_of))

    # Undated facts are kept: unknown date isn't "outside the window".
    if since is not None:
        conditions.append(or_(FactRow.occurred_at.is_(None), FactRow.occurred_at >= since))
    if until is not None:
        conditions.append(or_(FactRow.occurred_at.is_(None), FactRow.occurred_at <= until))

    return conditions
