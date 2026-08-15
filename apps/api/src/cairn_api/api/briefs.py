"""Reading, caching and keeping briefs.

**A finished period is a record.** It is written once and served from storage;
the current period is never written, because an archive that regenerates would
quietly rewrite what a team was already told. That rule is unconditional, and
the cache below sits entirely on the other side of it: it holds the *current*
period only, in memory, for minutes.

**Citations are resolved from `fact_sources` at read time**, by the fact ids a
claim recorded, so a permalink corrected in the source system appears in an old
brief too — the citation points at evidence rather than at a stored URL.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.schemas import (
    BriefClaimResponse,
    BriefResponse,
    BriefSummary,
    CitationResponse,
)
from cairn_api.db.brief_models import Brief, BriefClaim
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource
from cairn_api.domain import Certainty
from cairn_api.pipeline.synthesize import Brief as SynthesisedBrief

logger = structlog.get_logger(__name__)

#: How much of the narrative the archive list carries. Truncated server-side: a
#: line clipped in CSS still ships every paragraph of five hundred briefs.
EXCERPT_CHARS = 200


def is_complete(period_end: datetime, *, now: datetime | None = None) -> bool:
    """Whether a period has finished and its brief is therefore a record.

    No grace window: a late event changes tomorrow's brief, not yesterday's.
    """
    return period_end <= (now or datetime.now(UTC))


#: How long one generation of the current period is reused, per workspace. Five
#: minutes absorbs a morning's readers, keeps a correction visible almost at
#: once, and is exactly the rate `BRIEF_PER_WORKSPACE` allows — twelve an hour.
CACHE_TTL_SECONDS = 300.0

#: Periods held per process before the oldest goes, bounding memory as the
#: rate limiter does.
MAX_CACHED_PERIODS = 1_000

#: Workspace and period. The tenant is part of the key rather than a filter
#: applied afterwards, so no lookup can reach another workspace's text.
CacheKey = tuple[uuid.UUID, datetime, datetime]


def round_to_window(moment: datetime) -> datetime:
    """A moment, rounded down to the freshness window.

    A brief asked for without dates ends "now" — different by microseconds for
    every reader, and a miss every time. Applied only to the boundaries the
    caller left to us, so a narrow question never gets a wider answer.
    """
    seconds = moment.timestamp()
    return datetime.fromtimestamp(seconds - (seconds % CACHE_TTL_SECONDS), tz=UTC)


#: What a cached brief was generated against: how much this workspace has
#: retracted, and when.
Marker = tuple[int, datetime | None]


@dataclass(frozen=True, slots=True)
class _Entry:
    response: BriefResponse
    marker: Marker
    expires_at: float


class BriefCache:
    """Current-period briefs, reused for a few minutes per workspace.

    In process rather than in a table: a live brief already differs between two
    generations, so an instance-local copy is no less consistent than what this
    endpoint returns today — and a stored one would be a second place where
    "what CAIRN said" lives, one convenience from being served as a record.
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[CacheKey, _Entry] = {}

    def get(
        self, key: CacheKey, *, marker: Marker, now: float | None = None
    ) -> BriefResponse | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= (now if now is not None else time.monotonic()):
            del self._entries[key]
            return None
        if entry.marker != marker:
            # Something this workspace believed has since been retracted, so the
            # cached text may assert it.
            del self._entries[key]
            return None
        return entry.response.model_copy(deep=True)

    def put(
        self, key: CacheKey, response: BriefResponse, *, marker: Marker, now: float | None = None
    ) -> None:
        started = now if now is not None else time.monotonic()
        if key not in self._entries and len(self._entries) >= MAX_CACHED_PERIODS:
            self._prune(started)
        if key not in self._entries and len(self._entries) >= MAX_CACHED_PERIODS:
            self._entries.pop(next(iter(self._entries)))
        self._entries[key] = _Entry(
            response=response.model_copy(deep=True),
            marker=marker,
            expires_at=started + self._ttl,
        )

    def _prune(self, now: float) -> None:
        for key in [key for key, entry in self._entries.items() if entry.expires_at <= now]:
            del self._entries[key]

    def clear(self) -> None:
        self._entries.clear()


def cache_for(app: FastAPI) -> BriefCache:
    """The cache belonging to this application instance, as the limiter is."""
    cache: BriefCache | None = getattr(app.state, "brief_cache", None)
    if cache is None:
        cache = BriefCache()
        app.state.brief_cache = cache
    return cache


async def retraction_marker(session: AsyncSession, *, tenant_id: uuid.UUID) -> Marker:
    """What this workspace has stopped believing, cheap enough to ask often.

    Every correction closes the corrected fact's validity window, so a change
    here means a cached claim may now be denied. New facts do not move it.
    """
    count, latest = (
        await session.execute(
            select(func.count(), func.max(FactRow.valid_until)).where(
                FactRow.tenant_id == tenant_id, FactRow.valid_until.is_not(None)
            )
        )
    ).one()
    return (count, latest)


async def load_stored(
    session: AsyncSession, *, tenant_id: uuid.UUID, start: datetime, end: datetime
) -> Brief | None:
    stored: Brief | None = await session.scalar(
        select(Brief).where(
            Brief.tenant_id == tenant_id,
            Brief.period_start == start,
            Brief.period_end == end,
        )
    )
    return stored


async def store(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: datetime,
    end: datetime,
    brief: SynthesisedBrief,
    model: str,
    truncated: bool,
) -> Brief | None:
    """Write a finished period's brief, or leave the existing one alone.

    `ON CONFLICT DO NOTHING`: two readers opening the same day both generate
    one, and the loser must keep the winner's words. Returns `None` when another
    request stored it first, so the caller re-reads rather than trust its own.
    """
    result = await session.execute(
        insert(Brief)
        .values(
            tenant_id=tenant_id,
            period_start=start,
            period_end=end,
            narrative=brief.narrative,
            abstained=brief.abstained,
            suppressed_count=len(brief.suppressed),
            truncated=truncated,
            model=model,
        )
        .on_conflict_do_nothing(constraint="uq_briefs_period")
        .returning(Brief.id)
    )
    brief_id = result.scalar_one_or_none()
    if brief_id is None:
        return None

    session.add_all(
        BriefClaim(
            tenant_id=tenant_id,
            brief_id=brief_id,
            ordinal=ordinal,
            text=claim.text,
            certainty=claim.certainty.value,
            fact_ids=list(claim.fact_ids),
            credits=list(claim.credits),
            hedged_by_system=claim.hedged_by_system,
        )
        for ordinal, claim in enumerate(brief.claims)
    )
    await session.flush()

    await logger.ainfo(
        "brief.stored",
        tenant_id=str(tenant_id),
        period_start=start.isoformat(),
        claims=len(brief.claims),
    )
    return await session.get(Brief, brief_id)


async def resolve_citations(
    session: AsyncSession, *, tenant_id: uuid.UUID, fact_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[CitationResponse]]:
    """Look up where each fact came from, so every claim can be checked.

    One query for the whole brief rather than one per claim. A fact that no
    longer exists yields no citations rather than an error: a claim without its
    links is a smaller failure than a brief that will not load.
    """
    if not fact_ids:
        return {}

    rows = await session.execute(
        select(FactSource, FactRow.id)
        .join(FactRow, FactRow.id == FactSource.fact_id)
        .where(FactSource.tenant_id == tenant_id, FactRow.id.in_(fact_ids))
    )

    by_fact: dict[uuid.UUID, list[CitationResponse]] = {}
    for source, fact_id in rows:
        by_fact.setdefault(fact_id, []).append(
            CitationResponse(
                evidence_id=source.evidence_id,
                source=source.source,
                url=source.url,
                quote=source.quote,
            )
        )
    return by_fact


def to_response(stored: Brief, citations: dict[uuid.UUID, list[CitationResponse]]) -> BriefResponse:
    """A stored brief, with its citations resolved."""
    return BriefResponse(
        id=stored.id,
        period_start=stored.period_start,
        period_end=stored.period_end,
        generated_at=stored.created_at,
        stored=True,
        narrative=stored.narrative,
        claims=[
            BriefClaimResponse(
                text=claim.text,
                certainty=Certainty(claim.certainty),
                fact_ids=list(claim.fact_ids),
                citations=citations_for(claim.fact_ids, citations),
                credits=list(claim.credits),
                hedged_by_system=claim.hedged_by_system,
            )
            for claim in stored.claims
        ],
        abstained=stored.abstained,
        suppressed_count=stored.suppressed_count,
        truncated=stored.truncated,
    )


def citations_for(
    fact_ids: list[uuid.UUID], citations: dict[uuid.UUID, list[CitationResponse]]
) -> list[CitationResponse]:
    """Every citation of every fact behind one claim, deduplicated.

    Two facts from one pull request cite the same evidence, and printing it
    twice makes provenance look padded — the opposite of what it is for.
    """
    seen: set[tuple[str, str]] = set()
    resolved: list[CitationResponse] = []
    for fact_id in fact_ids:
        for citation in citations.get(fact_id, []):
            key = (citation.source, citation.evidence_id)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(citation)
    return resolved


def summarise(stored: Brief) -> BriefSummary:
    excerpt = stored.narrative.strip()
    if len(excerpt) > EXCERPT_CHARS:
        # Cut at a word boundary: mid-word reads as a rendering bug.
        excerpt = excerpt[:EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"

    return BriefSummary(
        id=stored.id,
        period_start=stored.period_start,
        period_end=stored.period_end,
        generated_at=stored.created_at,
        excerpt=excerpt,
        claim_count=len(stored.claims),
        abstained=stored.abstained,
    )
