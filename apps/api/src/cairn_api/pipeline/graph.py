"""Building the graph: edges and embeddings for stored facts.

Every edge is derived from something checkable — shared evidence, person, or subject — never proposed by a model, since edges decide what reaches synthesis (md/09 §6.2). Edges are undirected in meaning but written both directions; `SUPERSEDES` is the exception, directional from replacement to replaced. The focus set is facts with no embedding row for `model_name` (`since`/`fact_ids` override); candidates come from an inverted subject-token index rather than a pairwise sweep. Fan-out is capped (`MAX_GROUP_FANOUT`) and reported via `GraphUpdate.truncated`.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, Select, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api import telemetry
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource
from cairn_api.db.graph_models import EdgeKind, FactEdge, FactEmbedding
from cairn_api.pipeline.embeddings import DEFAULT_EMBEDDING_MODEL, EmbeddingProvider
from cairn_api.pipeline.resolve import MIN_SHARED_SUBJECT_TOKENS, subject_key

logger = structlog.get_logger(__name__)

#: Time window linking two facts about the same person (md/09 §4.2, context rot).
PERSON_WINDOW = timedelta(days=14)

#: Min subject overlap for a `SAME_SUBJECT` edge; below the supersession bar
#: since a missing edge is worse than an over-wide one.
SUBJECT_EDGE_OVERLAP = 0.5

#: Relative traversal cost per edge kind. Higher is stronger.
EDGE_WEIGHTS = {
    EdgeKind.SHARED_EVIDENCE: 1.0,
    EdgeKind.SUPERSEDES: 0.9,
    EdgeKind.SHARED_PERSON: 0.6,
    EdgeKind.SAME_SUBJECT: 0.4,
}

#: Max partners one fact may link to via one grouping; caps hub fan-out (md/09 §4.2).
MAX_GROUP_FANOUT = 200

#: A subject token above this many facts stops generating candidates (de
#: facto stopword). Loss is reported via `truncated`.
MAX_SUBJECT_POSTINGS = 500

#: Rows per INSERT (asyncpg/PostgreSQL cap ~65,535 bound params; an edge costs six).
EDGE_INSERT_CHUNK = 5_000


@dataclass(frozen=True, slots=True)
class GraphUpdate:
    """What a build pass wrote."""

    edges_written: int = 0
    embeddings_written: int = 0

    #: Facts this pass derived edges for (focus set, not the workspace).
    facts_considered: int = 0

    #: Candidate pairs scored; watches for quadratic regression.
    subject_comparisons: int = 0

    #: True when a fan-out ceiling stopped edges being derived.
    truncated: bool = False


async def build(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    embedder: EmbeddingProvider,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    since: datetime | None = None,
    fact_ids: list[uuid.UUID] | None = None,
) -> GraphUpdate:
    """Derive edges and embeddings for a workspace's newly-arrived facts.

    Superseded facts keep existing edges but get no new ones. `since` filters
    on `created_at`, not `occurred_at`. Both args narrow which facts get new
    edges; candidates are always the whole currently-valid graph.
    """
    with telemetry.stage("graph", tenant_id=str(tenant_id)):
        # autoflush=False (db/session.py): flush so a caller's pending writes are visible below.
        await session.flush()

        focus = await _focus(
            session, tenant_id=tenant_id, model_name=model_name, since=since, fact_ids=fact_ids
        )
        if not focus:
            await logger.ainfo(
                "graph.built", tenant_id=str(tenant_id), facts=0, edges=0, embeddings=0
            )
            return GraphUpdate()

        candidates = await _candidates(session, tenant_id=tenant_id, focus=focus)
        derivation = _derive(focus, candidates)
        written = await _write_edges(session, tenant_id, derivation.edges)
        embedded = await _write_embeddings(
            session, tenant_id, focus, embedder=embedder, model_name=model_name
        )

        if derivation.truncated_groups:
            await logger.awarning(
                "graph.fanout_truncated",
                tenant_id=str(tenant_id),
                groups=len(derivation.truncated_groups),
                ceiling=MAX_GROUP_FANOUT,
                sample=derivation.truncated_groups[:5],
            )

        await logger.ainfo(
            "graph.built",
            tenant_id=str(tenant_id),
            facts=len(focus),
            candidates=len(candidates.subjects),
            edges=written,
            embeddings=embedded,
            subject_comparisons=derivation.subject_comparisons,
            truncated=bool(derivation.truncated_groups),
        )
        return GraphUpdate(
            edges_written=written,
            embeddings_written=embedded,
            facts_considered=len(focus),
            subject_comparisons=derivation.subject_comparisons,
            truncated=bool(derivation.truncated_groups),
        )


# --- What the rules operate on ---


@dataclass(frozen=True, slots=True)
class _Edge:
    source: uuid.UUID
    target: uuid.UUID
    kind: EdgeKind
    detail: str


@dataclass(frozen=True, slots=True)
class _Member:
    """An id and a timestamp, not a full `FactRow` (memory)."""

    id: uuid.UUID
    occurred_at: datetime | None


@dataclass(frozen=True, slots=True)
class _Candidates:
    """What a focus fact could plausibly link to, assembled by the database
    from the focus set's own keys so the rules stay pure and testable."""

    #: `(source, evidence_id)` → the currently-valid facts citing it.
    by_evidence: dict[tuple[str, str], list[_Member]]

    #: Resolved person id → the currently-valid facts concerning them.
    by_person: dict[uuid.UUID, list[_Member]]

    #: Every currently-valid fact's subject key.
    subjects: dict[uuid.UUID, frozenset[str]]

    #: Inverted index: subject token → facts whose subject contains it.
    postings: dict[str, list[uuid.UUID]]


@dataclass
class _Derivation:
    """The edges one pass implied, and what it cost."""

    edges: list[_Edge] = field(default_factory=list)
    subject_comparisons: int = 0

    #: Groups that hit a ceiling, named (not counted) for the operator.
    truncated_groups: list[str] = field(default_factory=list)

    #: Dedup set for `truncated_groups`; kept separate to preserve list order.
    _truncated_seen: set[str] = field(default_factory=set)

    def truncate(self, name: str) -> None:
        if name not in self._truncated_seen:
            self._truncated_seen.add(name)
            self.truncated_groups.append(name)


# --- Loading ---


async def _focus(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    model_name: str,
    since: datetime | None,
    fact_ids: list[uuid.UUID] | None,
) -> list[FactRow]:
    """Currently-valid facts to derive edges for: default is those with no
    vector from `model_name`, so a model change re-derives the workspace."""
    statement = select(FactRow).where(
        FactRow.tenant_id == tenant_id,
        FactRow.valid_until.is_(None),
    )

    if fact_ids is not None:
        statement = statement.where(FactRow.id.in_(fact_ids))
    else:
        statement = statement.where(
            ~select(FactEmbedding.id)
            .where(
                FactEmbedding.tenant_id == tenant_id,
                FactEmbedding.fact_id == FactRow.id,
                FactEmbedding.model == model_name,
            )
            .exists()
        )
        if since is not None:
            statement = statement.where(FactRow.created_at >= since)

    return list(await session.scalars(_ordered(statement)))


async def _candidates(
    session: AsyncSession, *, tenant_id: uuid.UUID, focus: list[FactRow]
) -> _Candidates:
    """Fetch only what the focus set could link to: evidence and people keyed
    off the focus set, plus a subject-index projection kept in Python (not a
    SQL token index) so `subject_key` stays a single definition.
    """
    evidence_keys = sorted({(ref.source, ref.evidence_id) for row in focus for ref in row.sources})
    person_ids = sorted({link.person_id for row in focus for link in row.people if link.person_id})

    by_evidence: dict[tuple[str, str], list[_Member]] = defaultdict(list)
    if evidence_keys:
        rows = await session.execute(
            _ordered(
                select(FactRow.id, FactRow.occurred_at, FactSource.source, FactSource.evidence_id)
                .join(FactSource, FactSource.fact_id == FactRow.id)
                .where(
                    FactRow.tenant_id == tenant_id,
                    FactRow.valid_until.is_(None),
                    tuple_(FactSource.source, FactSource.evidence_id).in_(evidence_keys),
                )
            )
        )
        for fact_id, occurred_at, source_name, evidence_id in rows:
            by_evidence[(source_name, evidence_id)].append(_Member(fact_id, occurred_at))

    by_person: dict[uuid.UUID, list[_Member]] = defaultdict(list)
    if person_ids:
        rows = await session.execute(
            _ordered(
                select(FactRow.id, FactRow.occurred_at, FactPerson.person_id)
                .join(FactPerson, FactPerson.fact_id == FactRow.id)
                .where(
                    FactRow.tenant_id == tenant_id,
                    FactRow.valid_until.is_(None),
                    FactPerson.person_id.in_(person_ids),
                )
            )
        )
        for fact_id, occurred_at, person_id in rows:
            by_person[person_id].append(_Member(fact_id, occurred_at))

    subjects: dict[uuid.UUID, frozenset[str]] = {}
    postings: dict[str, list[uuid.UUID]] = defaultdict(list)
    statements = await session.execute(
        select(FactRow.id, FactRow.statement).where(
            FactRow.tenant_id == tenant_id,
            FactRow.valid_until.is_(None),
        )
    )
    for fact_id, statement in statements:
        subject = subject_key(statement)
        subjects[fact_id] = subject
        for token in subject:
            postings[token].append(fact_id)

    return _Candidates(
        by_evidence=dict(by_evidence),
        by_person=dict(by_person),
        subjects=subjects,
        postings=dict(postings),
    )


def _ordered(statement: Select[Any]) -> Select[Any]:
    """Stable order (oldest first, then id) for anything a fan-out ceiling may cut."""
    return statement.order_by(FactRow.occurred_at.nullsfirst(), FactRow.id)


# --- The rules ---


def _derive(focus: list[FactRow], candidates: _Candidates) -> _Derivation:
    """Every edge implied by the focus set. Pure and testable; deduplicates
    here rather than via the unique constraint."""
    derivation = _Derivation()
    seen: set[tuple[uuid.UUID, uuid.UUID, EdgeKind]] = set()

    def link(left: uuid.UUID, right: uuid.UUID, kind: EdgeKind, detail: str) -> None:
        for source, target in ((left, right), (right, left)):
            key = (source, target, kind)
            if key in seen:
                continue
            seen.add(key)
            derivation.edges.append(_Edge(source, target, kind, detail))

    _shared_evidence(focus, candidates, derivation, link)
    _shared_people(focus, candidates, derivation, link)
    _same_subject(focus, candidates, derivation, link)
    _supersession(focus, candidates, derivation)
    return derivation


_Link = Callable[[uuid.UUID, uuid.UUID, EdgeKind, str], None]


def _shared_evidence(
    focus: list[FactRow], candidates: _Candidates, derivation: _Derivation, link: _Link
) -> None:
    """Facts extracted from the same artefact, grouped rather than compared
    pairwise. Only pairs with a focus fact at one end are derived."""
    focus_ids = {row.id for row in focus}
    for row in focus:
        for ref in row.sources:
            group = candidates.by_evidence.get((ref.source, ref.evidence_id), [])
            detail = f"{ref.source}:{ref.evidence_id}"
            for other in _capped(group, detail, derivation):
                if other.id == row.id:
                    continue
                if other.id in focus_ids and other.id < row.id:
                    continue  # both ends new: derive from the lower id only
                link(row.id, other.id, EdgeKind.SHARED_EVIDENCE, detail)


def _shared_people(
    focus: list[FactRow], candidates: _Candidates, derivation: _Derivation, link: _Link
) -> None:
    """Facts about the same person, close in time. Resolved people only —
    the candidate query joins on `person_id`."""
    focus_ids = {row.id for row in focus}
    for row in focus:
        for mention in row.people:
            if mention.person_id is None:
                continue
            group = candidates.by_person.get(mention.person_id, [])
            detail = f"person:{mention.person_id}"
            for other in _capped(group, detail, derivation):
                if other.id == row.id:
                    continue
                if other.id in focus_ids and other.id < row.id:
                    continue
                if not _close_in_time(row.occurred_at, other.occurred_at):
                    continue
                link(row.id, other.id, EdgeKind.SHARED_PERSON, detail)


def _same_subject(
    focus: list[FactRow], candidates: _Candidates, derivation: _Derivation, link: _Link
) -> None:
    """Facts about the same feature, service or migration, via the inverted
    subject-token index."""
    for row in focus:
        subject = candidates.subjects.get(row.id) or subject_key(row.statement)
        if not subject:
            continue

        shared_counts: Counter[uuid.UUID] = Counter()
        for token in subject:
            postings = candidates.postings.get(token, ())
            if len(postings) > MAX_SUBJECT_POSTINGS:
                derivation.truncate(f"subject:{token}")
                continue
            shared_counts.update(postings)

        scored: list[tuple[float, uuid.UUID, str]] = []
        for other_id, shared_tokens in shared_counts.items():
            if other_id == row.id or shared_tokens < MIN_SHARED_SUBJECT_TOKENS:
                continue
            other_subject = candidates.subjects.get(other_id)
            if not other_subject:
                continue

            derivation.subject_comparisons += 1
            shared = subject & other_subject
            overlap = len(shared) / min(len(subject), len(other_subject))
            if overlap < SUBJECT_EDGE_OVERLAP:
                continue
            scored.append((overlap, other_id, " ".join(sorted(shared)[:5])))

        if len(scored) > MAX_GROUP_FANOUT:
            derivation.truncate(f"subject-fanout:{row.id}")
        scored.sort(key=lambda item: (-item[0], item[1]))  # strongest overlap first
        for _, other_id, detail in scored[:MAX_GROUP_FANOUT]:
            link(row.id, other_id, EdgeKind.SAME_SUBJECT, detail)


def _supersession(focus: list[FactRow], candidates: _Candidates, derivation: _Derivation) -> None:
    """The temporal edge: replacement to replaced, one direction only.

    Currently unreachable — `ck_facts_supersession_is_complete` plus the
    `valid_until IS NULL` filter mean a fact with a successor is never in
    scope. Kept so the edge returns if that scope changes.
    """
    known = candidates.subjects.keys()
    derivation.edges.extend(
        _Edge(row.id, row.superseded_by_id, EdgeKind.SUPERSEDES, "supersession")
        for row in focus
        if row.superseded_by_id is not None and row.superseded_by_id in known
    )


def _capped(group: list[_Member], name: str, derivation: _Derivation) -> list[_Member]:
    """A group, trimmed to the fan-out ceiling, loudly. Takes the prefix of a
    deterministically ordered group (see `_ordered`)."""
    if len(group) <= MAX_GROUP_FANOUT:
        return group
    derivation.truncate(name)
    return group[:MAX_GROUP_FANOUT]


def _close_in_time(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return True
    return abs(left - right) <= PERSON_WINDOW


# --- Writing ---


async def _write_edges(session: AsyncSession, tenant_id: uuid.UUID, edges: list[_Edge]) -> int:
    """Insert edges, skipping ones already present via `ON CONFLICT DO
    NOTHING` rather than a read-then-write (avoids a round trip and a race)."""
    if not edges:
        return 0

    written = 0
    for start in range(0, len(edges), EDGE_INSERT_CHUNK):
        rows = [
            {
                "tenant_id": tenant_id,
                "source_fact_id": edge.source,
                "target_fact_id": edge.target,
                "kind": edge.kind,
                "weight": EDGE_WEIGHTS[edge.kind],
                "detail": edge.detail[:255],
            }
            for edge in edges[start : start + EDGE_INSERT_CHUNK]
        ]
        statement = (
            insert(FactEdge)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_fact_edges_source_target_kind")
        )
        result = cast("CursorResult[Any]", await session.execute(statement))
        written += int(result.rowcount or 0)  # what was written, not offered
    return written


async def _write_embeddings(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    pending: list[FactRow],
    *,
    embedder: EmbeddingProvider,
    model_name: str,
) -> int:
    """Embed the facts that do not yet have a vector from this model.
    `pending` is the focus set, already filtered by the selecting query."""
    if not pending:
        return 0

    vectors = await embedder.embed([fact.statement for fact in pending])
    if len(vectors) != len(pending):
        msg = f"embedder returned {len(vectors)} vectors for {len(pending)} facts"
        raise ValueError(msg)

    session.add_all(
        FactEmbedding(
            tenant_id=tenant_id,
            fact_id=fact.id,
            embedding=vector,
            model=model_name,
        )
        for fact, vector in zip(pending, vectors, strict=True)
    )
    await session.flush()
    return len(pending)
