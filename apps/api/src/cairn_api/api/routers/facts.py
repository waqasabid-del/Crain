"""Reading what the pipeline understood.

Every way anything the understanding layer produces leaves the database: the
list, the facets that describe it, search, and the brief with its archive. Until
this router existed, facts were extracted, resolved, stored, embedded and
connected, and no caller could read one — which is the same finding as the
pipeline having no production caller, one layer up.

**They are all reads, and they all declare `CONTENT_READ` anyway.** Every role
holds it, including Viewer, so the check refuses nobody today. It is declared
because the permission model is the place that decision is recorded, and an
endpoint with no declared requirement is one whose requirement gets decided later
by whoever adds the next parameter. It also states the rule these endpoints must
never break: what a person can see is decided by the symmetry rule, not by their
role (md/15 §2.2) — an Owner reading this workspace's facts sees exactly what a
Viewer sees.

**The query layer is `api/feed.py`, not this module.** Filters are shared between
the list and search from one object, because a filter that reached one and not
the other would let a reader narrow the screen to a project, type a word, and be
shown somebody else's.

**Superseded facts are excluded by default, in the query.** "Ali is working on
authentication", three weeks after he moved to billing, is the failure that
destroys trust (md/09 §3.2), and it reaches a reader through a list endpoint
just as easily as through a brief. `includeSuperseded` exists because history is
a real question — "what did we think last Tuesday" — and it is opt-in because
the default has to be the safe answer for a caller who never thought about it.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import ColumnElement, Select, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api import briefs, feed
from cairn_api.api.dependencies import (
    RateLimiterDep,
    TenantDb,
    WorkspaceContext,
    enforce_rate_limit,
    requires,
)
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.ratelimit import RateLimit
from cairn_api.api.schemas import (
    BriefArchive,
    BriefClaimResponse,
    BriefResponse,
    CitationResponse,
    FacetPerson,
    FacetsResponse,
    FactPage,
    FactPersonResponse,
    FactResponse,
    FactSourceResponse,
    SearchHit,
    SearchResults,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.brief_models import Brief as BriefRow
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.domain import Certainty
from cairn_api.pipeline import store
from cairn_api.pipeline.facts import FactKind
from cairn_api.pipeline.jobs import build_providers
from cairn_api.pipeline.retrieval import retrieve
from cairn_api.pipeline.synthesize import synthesize

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["facts"])

#: Facts returned by one request when the caller does not say.
DEFAULT_PAGE_SIZE = 50

#: The most facts one request may ask for.
#:
#: Each fact carries its sources and its people, both loaded eagerly, so a page
#: is several rows per item. 200 keeps the largest response in the low hundreds
#: of kilobytes; an unbounded `limit` would let one query materialise a
#: workspace's entire history into memory.
MAX_PAGE_SIZE = 200

#: Search results returned when the caller does not say.
#:
#: A screenful and then some. Search is a ranked answer rather than a stream, and
#: the result a reader wants is nearly always in the first ten — a larger default
#: mostly buys a longer page of things that matched weakly.
DEFAULT_SEARCH_RESULTS = 25

#: The most results one search may ask for.
#:
#: Lower than `MAX_PAGE_SIZE`, because relevance has a tail and the tail is not
#: useful: a hundredth-ranked result for a two-word query is noise with a
#: citation attached. A caller who genuinely wants everything wants the list
#: endpoint with filters, which paginates honestly.
MAX_SEARCH_RESULTS = 100

#: Searches per workspace per minute.
#:
#: Per workspace rather than per address, matching the brief limit and for the
#: same reason: a query that runs vector search embeds its text, which is a model
#: call charged to the tenant. Sixty a minute is far above a person typing into a
#: search box and far below a script walking the fact graph.
SEARCH_PER_WORKSPACE = RateLimit(limit=60, window_seconds=60)

#: The period a brief covers when the caller does not say.
DEFAULT_BRIEF_DAYS = 7

#: The longest period a brief may be asked to cover.
#:
#: Not a performance bound — retrieval has its own token budget and would simply
#: truncate. It is an honesty bound: a "brief" over a year is a document, and
#: silently returning the same forty facts (`synthesize.MAX_FACTS`) for a year
#: as for a week would present a bounded sample as a summary of the whole.
MAX_BRIEF_DAYS = 92

#: What a brief is retrieved against.
#:
#: A fixed question, because a brief is not a search: the period *is* the query,
#: and the graph traversal from these entry points is what actually assembles
#: the set (md/09 §3.1). Accepting a caller-supplied question here was the
#: rejected alternative — it would make the brief endpoint an answer endpoint
#: with a time filter, and those want different prompts, different caching and a
#: different rate limit.
BRIEF_QUESTION = (
    "What happened in this period: what was delivered, what was decided, "
    "what is blocked, and what questions are open?"
)

#: Brief *generations* per workspace per hour.
#:
#: Reads served from the cache do not count, which is what keeps a team of
#: readers from exhausting it (see `briefs.CACHE_TTL_SECONDS`).
#:
#: Kept next to the endpoint rather than in `ratelimit.py`, where the auth
#: limits live because two routers share them. This one has exactly one caller
#: and its number is a consequence of what the endpoint does: every request is a
#: premium-model call over retrieved facts (md/09 §7.1), so an unbounded read
#: endpoint is an unbounded bill. Twelve an hour is far above a person refreshing
#: a daily brief and far below a script.
#:
#: Per workspace, not per address: the cost is charged to the tenant, so the
#: budget belongs to the tenant. A per-address limit would let one workspace
#: spend without bound from ten laptops.
BRIEF_PER_WORKSPACE = RateLimit(limit=12, window_seconds=60 * 60)


# --------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/facts",
    response_model=FactPage,
    summary="List the facts CAIRN holds for this workspace",
    responses={
        400: {"description": "The pagination cursor could not be read."},
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def list_facts(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    kind: Annotated[
        list[FactKind] | None,
        Query(description="Restrict to these fact kinds. Repeat the parameter to pass several."),
    ] = None,
    person: Annotated[
        list[uuid.UUID] | None,
        Query(description="Only facts concerning these people. Repeat to pass several."),
    ] = None,
    project: Annotated[
        list[str] | None,
        Query(description="Only facts whose evidence names these projects."),
    ] = None,
    source: Annotated[
        list[str] | None,
        Query(description="Only facts with evidence from these sources."),
    ] = None,
    since: Annotated[
        datetime | None, Query(description="Only activity that happened at or after this time.")
    ] = None,
    until: Annotated[
        datetime | None, Query(description="Only activity that happened at or before this time.")
    ] = None,
    include_superseded: Annotated[
        bool,
        Query(
            alias="includeSuperseded",
            description="Include facts that have been replaced. Off by default.",
        ),
    ] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[
        str | None, Query(description="The `nextCursor` from a previous page.")
    ] = None,
) -> FactPage:
    """Return a page of facts, newest activity first.

    **Keyset pagination, not limit/offset**, and the choice is forced by what
    this list is. Facts arrive continuously — every webhook can insert into the
    middle of the ordering, because a fact is ordered by when the activity
    *happened*, not by when it was stored. Under `OFFSET 50` a fact inserted
    while someone reads page one is a fact that shifts every later page by a
    row: the reader sees one item twice and never sees another at all, with
    nothing in the response to indicate it. A keyset cursor names the last row
    of the previous page, so an insertion behind the cursor is simply invisible
    and an insertion ahead of it appears on a later page. It is also the version
    that stays fast: `OFFSET 10000` reads and discards ten thousand rows, on a
    table that only grows.

    The cursor is opaque on purpose. It encodes `(occurred_at, id)`, and a
    client that parsed it would be depending on the sort key — which is exactly
    the thing a later "sort by relevance" would change.

    **Undated facts sort last and page consistently.** `occurred_at` is nullable
    — some sources do not timestamp reliably — so the ordering is
    `occurred_at DESC NULLS LAST, id DESC`, and the cursor predicate has a
    matching branch for a null. Dropping undated facts from the list instead
    would silently hide whole sources.
    """
    # Every filter lives in `feed.conditions`, shared with search. A filter that
    # reached this list but not the search would let a reader narrow to one
    # project, type a word, and be shown another project's work.
    conditions = feed.conditions(
        context.tenant_id,
        _filters(
            kind=kind,
            person=person,
            project=project,
            source=source,
            since=since,
            until=until,
            include_superseded=include_superseded,
        ),
    )

    if cursor is not None:
        conditions.append(_cursor_condition(_decode_cursor(cursor)))

    statement: Select[tuple[FactRow]] = (
        select(FactRow)
        .where(*conditions)
        .order_by(FactRow.occurred_at.desc().nullslast(), FactRow.id.desc())
        # One more than asked for, so "is there another page" is answered
        # without a second count query — and answered correctly, which a count
        # taken at a different instant would not be.
        .limit(limit + 1)
    )

    rows = list(await db.scalars(statement))
    has_more = len(rows) > limit
    page = rows[:limit]

    return FactPage(
        items=[_fact_response(row) for row in page],
        next_cursor=_encode_cursor(page[-1]) if has_more and page else None,
    )


def _filters(
    *,
    kind: list[FactKind] | None,
    person: list[uuid.UUID] | None,
    project: list[str] | None,
    source: list[str] | None,
    since: datetime | None,
    until: datetime | None,
    include_superseded: bool = False,
) -> feed.FeedFilters:
    """FastAPI's query parameters as the object the query layer takes.

    One conversion, used by both endpoints, so that adding a filter is a change
    in two places rather than a change in one and a bug in the other.
    """
    return feed.FeedFilters(
        kinds=tuple(item.value for item in kind or ()),
        people=tuple(person or ()),
        projects=tuple(project or ()),
        sources=tuple(source or ()),
        since=since,
        until=until,
        include_superseded=include_superseded,
    )


@router.get(
    "/{workspace_id}/facets",
    response_model=FacetsResponse,
    summary="What this workspace can be filtered by",
    responses={
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def get_facets(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
) -> FacetsResponse:
    """The people, projects and sources that appear in this workspace's facts.

    Read from the facts, not from a list of what CAIRN can hold. A filter menu is
    a description of what is there — offering a value that matches nothing
    teaches a reader that the filters are broken, and they are right to conclude
    it.
    """
    found = await feed.facets(db, tenant_id=context.tenant_id)
    return FacetsResponse(
        people=[FacetPerson(id=person_id, name=name) for person_id, name in found.people],
        projects=found.projects,
        sources=found.sources,
    )


@router.get(
    "/{workspace_id}/search",
    response_model=SearchResults,
    summary="Search the facts CAIRN holds",
    responses={
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
        429: {"description": "Too many searches for this workspace."},
    },
)
async def search_facts(
    request: Request,
    response: Response,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    limiter: RateLimiterDep,
    q: Annotated[str, Query(min_length=1, max_length=200, description="What to look for.")],
    kind: Annotated[list[FactKind] | None, Query()] = None,
    person: Annotated[list[uuid.UUID] | None, Query()] = None,
    project: Annotated[list[str] | None, Query()] = None,
    source: Annotated[list[str] | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_RESULTS)] = DEFAULT_SEARCH_RESULTS,
) -> SearchResults:
    """Facts matching a query, most relevant first, each with its evidence.

    **Results are stored facts and nothing else.** No model is called on this
    path, and the response has no field for prose. That is what "grounded" means
    here: the reader is looking at what CAIRN recorded, with the citation
    attached, rather than at a summary of it. A generated answer with sources
    listed underneath is the failure md/09 §5 exists to prevent — the prose is
    what gets believed and the citations are what nobody opens.

    **The same filters as the feed**, from the same object, so narrowing the
    screen and then searching cannot widen it again.

    Rate limited per workspace because a query with vector search enabled embeds
    the text, which is a model call. Far above a person typing and far below a
    script.
    """
    await enforce_rate_limit(
        request,
        response,
        limiter,
        key=f"search:{context.tenant_id}",
        limit=SEARCH_PER_WORKSPACE,
    )

    providers = build_providers()

    hits = await feed.search(
        db,
        tenant_id=context.tenant_id,
        query=q,
        filters=_filters(
            kind=kind,
            person=person,
            project=project,
            source=source,
            since=since,
            until=until,
        ),
        # One more than asked for, so "was anything left behind" is answered by
        # the surplus rather than by comparing the count to the limit — which
        # claims truncation whenever the corpus holds exactly `limit` matches.
        limit=limit + 1,
        # Offline, the embedder returns hashed vectors: real, deterministic and
        # semantically meaningless. Passing it anyway would fill the results
        # with confident noise, and a bad semantic hit is indistinguishable from
        # a good one to the person reading it.
        embedder=providers.embedder if providers.live else None,
    )

    return SearchResults(
        items=[
            SearchHit(fact=_fact_response(hit.fact), matched_on=hit.matched_on)
            for hit in hits[:limit]
        ],
        truncated=len(hits) > limit,
        semantic=providers.live,
    )


# --------------------------------------------------------------------------
# Brief
# --------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/brief",
    response_model=BriefResponse,
    summary="Generate a brief for a period",
    responses={
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
        422: {"description": "The requested period is inverted or too long."},
        429: {"description": "Too many briefs generated for this workspace."},
    },
)
async def get_brief(
    request: Request,
    response: Response,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    limiter: RateLimiterDep,
    since: Annotated[
        datetime | None,
        Query(description=f"Start of the period. Defaults to {DEFAULT_BRIEF_DAYS} days ago."),
    ] = None,
    until: Annotated[datetime | None, Query(description="End of the period. Defaults to now.")] = (
        None
    ),
) -> BriefResponse:
    """Serve the period's brief: from the archive if it is a record, else fresh.

    A finished period is generated once and kept; the current one is generated
    live, never stored, and reused from `briefs.BriefCache` for a few minutes so
    a morning's readers share one model call. Every claim carries the facts and
    the evidence it rests on, and claims failing synthesis' four gates are
    dropped rather than caveated — the count is reported instead.

    The rate limit is applied only when something is actually generated, so
    neither reading the archive nor reading a cached brief is rationed: reading
    is not what costs money.
    """
    end = until or datetime.now(UTC)
    start = since or (end - timedelta(days=DEFAULT_BRIEF_DAYS))
    _validate_period(start, end)

    complete = briefs.is_complete(end)
    if complete:
        existing = await briefs.load_stored(db, tenant_id=context.tenant_id, start=start, end=end)
        if existing is not None:
            return await _stored_response(db, context.tenant_id, existing)

    cache = briefs.cache_for(request.app)
    # Boundaries the caller left to us default to "now" and would otherwise
    # differ by microseconds between two readers, missing the cache every time.
    cache_key: briefs.CacheKey = (
        context.tenant_id,
        start if since is not None else briefs.round_to_window(start),
        end if until is not None else briefs.round_to_window(end),
    )
    marker = None if complete else await briefs.retraction_marker(db, tenant_id=context.tenant_id)
    if marker is not None:
        cached = cache.get(cache_key, marker=marker)
        if cached is not None:
            return cached

    await enforce_rate_limit(
        request,
        response,
        limiter,
        key=f"brief:{context.tenant_id}",
        limit=BRIEF_PER_WORKSPACE,
    )

    providers = build_providers()

    retrieval = await retrieve(
        db,
        tenant_id=context.tenant_id,
        question=BRIEF_QUESTION,
        embedder=providers.embedder,
        since=start,
        until=end,
    )

    # `for_context()` orders for placement: entry points last, closest to the
    # request, because attention concentrates at the edges of a long context
    # (md/09 §4.3). Re-sorting here would undo that silently.
    facts = [store.to_domain(item.fact) for item in retrieval.for_context()]
    brief = await synthesize(providers.model, facts=facts, period=_period_label(start, end))

    await logger.ainfo(
        "brief.generated",
        tenant_id=str(context.tenant_id),
        retrieved=len(facts),
        claims=len(brief.claims),
        suppressed=len(brief.suppressed),
        truncated=retrieval.truncated,
        live_model=providers.live,
        stored=complete,
    )

    if complete:
        written = await briefs.store(
            db,
            tenant_id=context.tenant_id,
            start=start,
            end=end,
            brief=brief,
            model="live" if providers.live else "offline",
            truncated=retrieval.truncated,
        )
        if written is None:
            # Another request stored this period first. Re-read rather than
            # returning what we just generated, so two readers opening the same
            # day are shown the same words.
            written = await briefs.load_stored(
                db, tenant_id=context.tenant_id, start=start, end=end
            )
        if written is not None:
            await db.commit()
            return await _stored_response(db, context.tenant_id, written)

    # The live path. Citations come from the facts already in hand rather than
    # from a second query: retrieval loaded them a moment ago.
    # Counted from the stored rows, which are what carry the actor links —
    # `facts` above is the domain mapping, and the domain fact deliberately
    # holds names only.
    actors_by_fact = {
        item.fact.id: (
            sum(
                1
                for link in item.fact.people
                if link.provider_account_id is not None and link.person_id is not None
            ),
            sum(
                1
                for link in item.fact.people
                if link.provider_account_id is not None and link.person_id is None
            ),
        )
        for item in retrieval.facts
    }
    by_fact = {
        fact.id: [
            CitationResponse(
                evidence_id=ref.evidence_id, source=ref.source, url=ref.url, quote=ref.quote
            )
            for ref in fact.sources
        ]
        for fact in facts
    }

    live = BriefResponse(
        period_start=start,
        period_end=end,
        generated_at=datetime.now(UTC),
        stored=False,
        narrative=brief.narrative,
        claims=[
            BriefClaimResponse(
                text=claim.text,
                certainty=claim.certainty,
                fact_ids=list(claim.fact_ids),
                citations=briefs.citations_for(list(claim.fact_ids), by_fact),
                credits=list(claim.credits),
                # Summed across the facts this sentence rests on. A brief claim
                # can draw on several facts, and a reader deciding whether the
                # sentence names everyone involved needs the total rather than
                # one fact's share.
                resolved_actors=sum(
                    actors_by_fact.get(fact_id, (0, 0))[0] for fact_id in claim.fact_ids
                ),
                unresolved_actors=sum(
                    actors_by_fact.get(fact_id, (0, 0))[1] for fact_id in claim.fact_ids
                ),
                hedged_by_system=claim.hedged_by_system,
            )
            for claim in brief.claims
        ],
        abstained=brief.abstained,
        suppressed_count=len(brief.suppressed),
        truncated=retrieval.truncated,
    )

    if marker is not None:
        # `stored` stays false: this is a live brief, and the client is told
        # when it was generated by `generatedAt` rather than by a cache flag.
        cache.put(cache_key, live, marker=marker)

    return live


async def _stored_response(
    db: AsyncSession, tenant_id: uuid.UUID, stored: BriefRow
) -> BriefResponse:
    """A stored brief with its citations resolved from the evidence.

    Resolved at read time rather than written alongside the claim, so a
    permalink corrected in the source system appears in an old brief too — the
    citation points at evidence, which is stable, not at a URL recorded months
    ago.
    """
    fact_ids = {fact_id for claim in stored.claims for fact_id in claim.fact_ids}
    citations = await briefs.resolve_citations(db, tenant_id=tenant_id, fact_ids=fact_ids)
    return briefs.to_response(stored, citations)


@router.get(
    "/{workspace_id}/briefs",
    response_model=BriefArchive,
    summary="Past briefs, newest first",
    responses={
        400: {"description": "The pagination cursor could not be read."},
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def list_briefs(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[
        str | None, Query(description="The `nextCursor` from a previous page.")
    ] = None,
) -> BriefArchive:
    """The archive.

    Summaries, not whole briefs: an archive is a list to scan, and sending every
    claim of every period to render a list of dates is the request that makes
    this screen slow exactly as a workspace accumulates history.

    Keyset pagination on `period_end`, matching `/facts`. Offset pagination on a
    list that grows at the newest end shifts every row down as briefs are
    written, so a reader paging backwards sees one period twice and never sees
    another.
    """
    statement = (
        select(BriefRow)
        .where(BriefRow.tenant_id == context.tenant_id)
        .order_by(BriefRow.period_end.desc(), BriefRow.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(
            tuple_(BriefRow.period_end, BriefRow.id) < _decode_brief_cursor(cursor)
        )

    rows = list(await db.scalars(statement))
    has_more = len(rows) > limit
    page = rows[:limit]

    return BriefArchive(
        items=[briefs.summarise(row) for row in page],
        next_cursor=_encode_brief_cursor(page[-1]) if has_more and page else None,
    )


@router.get(
    "/{workspace_id}/briefs/{brief_id}",
    response_model=BriefResponse,
    summary="One brief from the archive",
    responses={
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such brief in this workspace."},
    },
)
async def get_archived_brief(
    brief_id: uuid.UUID,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
) -> BriefResponse:
    """A stored brief by id — the permalink the archive links to.

    A stable address matters more here than it looks: "you told us on Tuesday
    that payments had shipped" needs something a person can send to somebody
    else. A URL that reconstructs the period as query parameters would be that
    address only until the period boundaries were computed differently.

    Reads only stored briefs. There is deliberately no fallback that generates
    one for a missing id: an archive entry that appears when it is asked for is
    not a record of anything.
    """
    stored = await db.scalar(
        select(BriefRow).where(BriefRow.tenant_id == context.tenant_id, BriefRow.id == brief_id)
    )
    if stored is None:
        # The tenant filter is redundant behind row-level security and stated
        # anyway: a 404 that depends on RLS alone becomes a 200 the day someone
        # runs this query on a platform connection.
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such brief",
            detail="This workspace has no brief with that identifier.",
            problem_type="brief-not-found",
        )

    return await _stored_response(db, context.tenant_id, stored)


def _encode_brief_cursor(row: BriefRow) -> str:
    return base64.urlsafe_b64encode(f"{row.period_end.isoformat()}|{row.id}".encode()).decode()


def _decode_brief_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Read a cursor, refusing anything malformed.

    A cursor is opaque to the caller and therefore attacker-supplied. Failing
    with a 400 that names the parameter beats a 500 from a parse error deeper in
    — and beats silently starting from the beginning, which loops a paging
    client forever.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        timestamp, identifier = raw.split("|", 1)
        return datetime.fromisoformat(timestamp), uuid.UUID(identifier)
    except (ValueError, binascii.Error) as exc:
        raise ProblemDetailError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Unreadable cursor",
            detail="The `cursor` parameter is not one this endpoint issued.",
            problem_type="unreadable-cursor",
        ) from exc


def _validate_period(start: datetime, end: datetime) -> None:
    """Refuse a period that cannot mean what it says.

    Raised as a problem document rather than silently swapped or clamped. A
    caller who inverted their dates has a bug, and answering a question they did
    not ask hides it.
    """
    if start >= end:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Invalid period",
            detail="`since` must be earlier than `until`.",
            problem_type="invalid-period",
        )
    if end - start > timedelta(days=MAX_BRIEF_DAYS):
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Period too long",
            detail=f"A brief covers at most {MAX_BRIEF_DAYS} days.",
            problem_type="period-too-long",
        )


def _period_label(start: datetime, end: datetime) -> str:
    """How the period is described to the model.

    Days rather than dates. The instruction is prompt-cached scaffolding
    (md/09 §7.1) and a literal date in it changes on every request, which would
    turn a cache hit into a miss for no gain in the output.
    """
    days = max(1, round((end - start).total_seconds() / 86400))
    return "day" if days == 1 else f"{days} days"


# --------------------------------------------------------------------------
# Serialisation and cursors
# --------------------------------------------------------------------------


def _fact_response(row: FactRow) -> FactResponse:
    """One stored fact, as a reader sees it.

    Built field by field rather than by serialising the ORM object. Every column
    added to `facts` would otherwise appear in the API by default — which is how
    an internal flag, or `corrected_by_user_id`, reaches a client nobody meant
    to give it to.
    """
    return FactResponse(
        id=row.id,
        kind=row.kind,
        statement=row.statement,
        certainty=Certainty(row.certainty),
        origin=row.origin,
        occurred_at=row.occurred_at,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        superseded_by_id=row.superseded_by_id,
        supersession_reason=row.supersession_reason,
        sources=[
            FactSourceResponse(
                source=source.source,
                evidence_id=source.evidence_id,
                quote=source.quote,
                url=source.url,
                project=source.project,
            )
            for source in row.sources
        ],
        # **Actor rows are excluded, and this is the boundary that guarantees it.**
        # A row carrying a provider account id has no `mention`, and a Slack `U…`
        # or a Chat `users/…` is a private provider identifier: publishing one to
        # every colleague in the workspace, on the line that names who a fact
        # concerns, would be a disclosure. `FactPersonResponse` has no field it
        # could travel in, and `test_actor_privacy.py` fails if one is added.
        people=[
            FactPersonResponse(mention=link.mention, person_id=link.person_id)
            for link in row.people
            if link.mention is not None
        ],
        # Counts, not rows. The actor links are excluded above because they
        # carry a private provider account id; these two numbers are what a
        # reader needs to tell "nobody was involved" from "somebody was and
        # CAIRN cannot yet say who", and they name nobody.
        unresolved_actors=sum(
            1
            for link in row.people
            if link.provider_account_id is not None and link.person_id is None
        ),
        resolved_actors=sum(
            1
            for link in row.people
            if link.provider_account_id is not None and link.person_id is not None
        ),
    )


#: Separates the two halves of a cursor.
#:
#: A vertical bar cannot appear in either half: one is an ISO timestamp, the
#: other a UUID.
_CURSOR_SEPARATOR = "|"


def _encode_cursor(row: FactRow) -> str:
    """The position of the last row on a page.

    Base64url without padding, so the value is safe in a query string without
    escaping and does not invite a client to read it.
    """
    occurred = row.occurred_at.isoformat() if row.occurred_at is not None else ""
    raw = f"{occurred}{_CURSOR_SEPARATOR}{row.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime | None, uuid.UUID]:
    """Read a cursor, or refuse it.

    400 rather than "start from the beginning". A malformed cursor means the
    client is confused about where it is, and silently restarting the list would
    give it the first page forever while looking like it was paginating.
    """
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        occurred, _, identifier = raw.partition(_CURSOR_SEPARATOR)
        return (
            datetime.fromisoformat(occurred) if occurred else None,
            uuid.UUID(identifier),
        )
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ProblemDetailError(
            status_code=status.HTTP_400_BAD_REQUEST,
            title="Invalid cursor",
            detail="That pagination cursor could not be read. Start from the first page.",
            problem_type="invalid-cursor",
        ) from exc


def _cursor_condition(position: tuple[datetime | None, uuid.UUID]) -> ColumnElement[bool]:
    """Everything strictly after a position, in the list's own ordering.

    The ordering is `occurred_at DESC NULLS LAST, id DESC`, so "after" means
    older, and undated facts come after every dated one. Written as two branches
    because a null does not compare: a single `<` predicate would silently
    return nothing once the cursor reached the undated tail, and the list would
    appear to end early.
    """
    occurred, identifier = position

    if occurred is None:
        # Already inside the undated tail. Only undated facts remain, ordered by
        # id alone.
        return (FactRow.occurred_at.is_(None)) & (FactRow.id < identifier)

    return or_(
        FactRow.occurred_at < occurred,
        (FactRow.occurred_at == occurred) & (FactRow.id < identifier),
        # The undated tail follows every dated fact, so it is always ahead of a
        # dated cursor.
        FactRow.occurred_at.is_(None),
    )
