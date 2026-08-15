"""Filtering the fact graph, and searching it.

Search returns stored facts with their evidence. No model is called on this
path and the response has no field for prose: a generated answer with
citations underneath is the failure md/09 §5 exists to prevent, because the
prose is what gets believed and the citations are what nobody opens.

Lexical and vector search fail differently, so results carry `matched_on` and
the interface separates them. Vector search is skipped when the embedder is
not live — offline it is a hash, and a bad semantic hit is indistinguishable
from a good one to the reader.

Filters are `EXISTS` subqueries rather than joins: a fact has many sources,
and a join returns it once per match, which double-counts under `LIMIT`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import structlog
from sqlalchemy import ColumnElement, Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource
from cairn_api.db.graph_models import FactEmbedding
from cairn_api.db.identity_models import Person
from cairn_api.pipeline.embeddings import DEFAULT_EMBEDDING_MODEL, EmbeddingProvider

logger = structlog.get_logger(__name__)

#: English, which is what statements are written in today. Another language
#: gets a stemmer that mostly does not apply: degraded recall, not breakage.
FTS_CONFIG = "english"

#: Smaller than the lexical side on purpose: the semantic half catches
#: "throttling" for a search of "rate limiting", not outvotes what was typed.
SEMANTIC_CANDIDATES = 20

#: Reciprocal-rank-fusion constant, from the original paper. Untuned: with two
#: rankers it only decides how sharply each list's head is favoured.
RRF_K = 60

MatchedOn = Literal["words", "meaning"]


@dataclass(frozen=True, slots=True)
class FeedFilters:
    """What the reader narrowed the feed to.

    One object, shared by the list and both halves of search: a filter that
    reached one and not the other would let somebody narrow to a project, type
    a word, and be shown another project's work.
    """

    kinds: tuple[str, ...] = ()
    people: tuple[uuid.UUID, ...] = ()
    projects: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    since: datetime | None = None
    until: datetime | None = None

    #: History is a real question — "what did we think last Tuesday" — and it is
    #: opt-in because the default has to be the safe answer for a caller who
    #: never considered it (md/09 §3.2).
    include_superseded: bool = False

    @property
    def is_narrowed(self) -> bool:
        """Whether anything was actually filtered.

        The empty state branches on it: "nothing matches these filters" and
        "nothing recorded yet" send a reader to different places.
        """
        return bool(
            self.kinds
            or self.people
            or self.projects
            or self.sources
            or self.since is not None
            or self.until is not None
        )


def conditions(tenant_id: uuid.UUID, filters: FeedFilters) -> list[ColumnElement[bool]]:
    """The filters, as conditions for a query rather than a pass over results.

    A post-filter redefines `limit` as "before filtering", so pages shrink for
    no reason the reader can see.
    """
    where: list[ColumnElement[bool]] = [FactRow.tenant_id == tenant_id]

    if not filters.include_superseded:
        where.append(FactRow.valid_until.is_(None))

    if filters.kinds:
        where.append(FactRow.kind.in_(filters.kinds))

    # An undated fact is kept rather than filtered out, matching
    # `retrieval._temporal_conditions`. Its date is unknown, not "outside the
    # window", and excluding it would quietly drop every fact from a source that
    # does not timestamp reliably.
    if filters.since is not None:
        where.append(or_(FactRow.occurred_at.is_(None), FactRow.occurred_at >= filters.since))
    if filters.until is not None:
        where.append(or_(FactRow.occurred_at.is_(None), FactRow.occurred_at <= filters.until))

    if filters.people:
        where.append(
            exists().where(
                FactPerson.fact_id == FactRow.id,
                FactPerson.tenant_id == tenant_id,
                FactPerson.person_id.in_(filters.people),
            )
        )

    if filters.sources:
        where.append(
            exists().where(
                FactSource.fact_id == FactRow.id,
                FactSource.tenant_id == tenant_id,
                FactSource.source.in_(filters.sources),
            )
        )

    if filters.projects:
        where.append(
            exists().where(
                FactSource.fact_id == FactRow.id,
                FactSource.tenant_id == tenant_id,
                FactSource.project.in_(filters.projects),
            )
        )

    return where


# --------------------------------------------------------------------------
# Facets
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Facets:
    """What this workspace can actually be filtered by."""

    people: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


async def facets(session: AsyncSession, *, tenant_id: uuid.UUID) -> Facets:
    """The filter values that exist, read from the facts themselves.

    Every value matches at least one current fact. Offering "Meetings" to a
    workspace that never connected one returns nothing and reads as a fault in
    the product. The consent screen's source list is exhaustive for the
    opposite reason: it is a promise about the future (md/11 §4.1).

    No counts. A number beside a name is a productivity metric wearing a
    filter's clothes (md/05 §B.1).
    """
    current = select(FactRow.id).where(
        FactRow.tenant_id == tenant_id, FactRow.valid_until.is_(None)
    )

    people = await session.execute(
        select(Person.id, Person.display_name)
        .join(FactPerson, FactPerson.person_id == Person.id)
        .where(FactPerson.tenant_id == tenant_id, FactPerson.fact_id.in_(current))
        .group_by(Person.id, Person.display_name)
        .order_by(Person.display_name)
    )

    projects = await session.scalars(
        select(FactSource.project)
        .where(
            FactSource.tenant_id == tenant_id,
            FactSource.project.is_not(None),
            FactSource.fact_id.in_(current),
        )
        .group_by(FactSource.project)
        .order_by(FactSource.project)
    )

    sources = await session.scalars(
        select(FactSource.source)
        .where(FactSource.tenant_id == tenant_id, FactSource.fact_id.in_(current))
        .group_by(FactSource.source)
        .order_by(FactSource.source)
    )

    return Facets(
        people=[(row[0], row[1]) for row in people],
        # The query excludes nulls; this narrows the nullable column's type.
        projects=[value for value in projects if value is not None],
        sources=list(sources),
    )


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hit:
    """One search result, and how it was found."""

    fact: FactRow
    matched_on: MatchedOn


async def search(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    query: str,
    filters: FeedFilters,
    limit: int,
    embedder: EmbeddingProvider | None = None,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> list[Hit]:
    """Facts matching a query, most relevant first.

    Args:
        embedder: Vector search runs only when one is supplied. `None` when the
            configured embedder is the offline hash — a correctness decision,
            not a performance one.
    """
    lexical = await _lexical(
        session, tenant_id=tenant_id, query=query, filters=filters, limit=limit
    )

    semantic: list[FactRow] = []
    if embedder is not None:
        semantic = await _semantic(
            session,
            tenant_id=tenant_id,
            query=query,
            filters=filters,
            embedder=embedder,
            model_name=model_name,
        )

    hits = _fuse(lexical, semantic)[:limit]

    await logger.ainfo(
        "feed.searched",
        tenant_id=str(tenant_id),
        lexical=len(lexical),
        semantic=len(semantic),
        returned=len(hits),
        # The query is never logged: it is customer content.
        semantic_enabled=embedder is not None,
    )
    return hits


async def _lexical(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    query: str,
    filters: FeedFilters,
    limit: int,
) -> list[FactRow]:
    """Full-text search over statements.

    `websearch_to_tsquery`, not `to_tsquery`: the latter raises a syntax error
    on an unbalanced quote or a stray ampersand, turning typing into a 500.
    """
    vector = func.to_tsvector(FTS_CONFIG, FactRow.statement)
    tsquery = func.websearch_to_tsquery(FTS_CONFIG, query)

    statement: Select[tuple[FactRow]] = (
        select(FactRow)
        .where(*conditions(tenant_id, filters), vector.op("@@")(tsquery))
        # `ts_rank_cd` over `ts_rank`: cover density rewards matches that appear
        # close together, which is what makes a two-word search return the
        # statement about both words above the one that mentions each in
        # passing.
        .order_by(func.ts_rank_cd(vector, tsquery).desc(), FactRow.occurred_at.desc().nullslast())
        .limit(limit)
    )
    return list(await session.scalars(statement))


async def _semantic(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    query: str,
    filters: FeedFilters,
    embedder: EmbeddingProvider,
    model_name: str,
) -> list[FactRow]:
    """Nearest statements by meaning, under the same filters.

    Filters are joined into the search: a post-filter asks the index for twenty
    and discards most of them, returning three results with no explanation.
    """
    embedded = (await embedder.embed([query]))[0]
    distance = FactEmbedding.embedding.cosine_distance(embedded)

    statement: Select[tuple[FactRow]] = (
        select(FactRow)
        .join(FactEmbedding, FactEmbedding.fact_id == FactRow.id)
        .where(
            *conditions(tenant_id, filters),
            FactEmbedding.tenant_id == tenant_id,
            FactEmbedding.model == model_name,
        )
        .order_by(distance)
        .limit(SEMANTIC_CANDIDATES)
    )
    return list(await session.scalars(statement))


def _fuse(lexical: list[FactRow], semantic: list[FactRow]) -> list[Hit]:
    """Merge two rankings into one.

    Reciprocal rank fusion, because the scores are not comparable: a
    `ts_rank_cd` of 0.09 and a cosine distance of 0.31 share no scale, and rank
    is the only thing both rankers agree on the meaning of.

    A fact found both ways is labelled `words` — it does contain what was
    typed, and the label exists to warn about results that do not.
    """
    scores: dict[uuid.UUID, float] = {}
    rows: dict[uuid.UUID, FactRow] = {}
    lexical_ids: set[uuid.UUID] = set()

    for rank, row in enumerate(lexical):
        scores[row.id] = scores.get(row.id, 0.0) + 1 / (RRF_K + rank + 1)
        rows[row.id] = row
        lexical_ids.add(row.id)

    for rank, row in enumerate(semantic):
        scores[row.id] = scores.get(row.id, 0.0) + 1 / (RRF_K + rank + 1)
        rows.setdefault(row.id, row)

    ordered = sorted(scores, key=lambda fact_id: (-scores[fact_id], str(fact_id)))
    return [
        Hit(fact=rows[fact_id], matched_on="words" if fact_id in lexical_ids else "meaning")
        for fact_id in ordered
    ]
