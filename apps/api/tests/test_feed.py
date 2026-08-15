"""The Team Feed: filtering the fact graph, and searching it.

Step 24's exit criterion is two claims — *filter by person, project, source and
date*, and *search returns grounded results* — and the second is the one that
needs defining before it can be tested.

**Grounded means every result is a stored fact with its evidence attached, and
nothing on the path composes prose.** So the tests here assert on the negative as
well as the positive: a search result's statement must be byte-identical to a row
in `facts`, and the response must have nowhere for a generated sentence to live.
A search endpoint that summarised its results would pass a naive "did it return
something relevant" test and fail the thing the criterion is actually about.

The filter tests each carry a **positive control** — the fact that should be
excluded is first shown to be visible without the filter. Asserting that a
filtered response omits something proves nothing on its own, because a filter
that matches nothing omits everything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.api import feed
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.identity_models import Identity, IdentityKind, Person
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.domain import Certainty
from cairn_api.pipeline import graph, store
from cairn_api.pipeline.embeddings import HashingEmbedder
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from conftest_api import TEST_ORIGIN
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
TUESDAY = MONDAY + timedelta(days=1)
WEDNESDAY = MONDAY + timedelta(days=2)


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


class Workspace:
    """A workspace with facts in it, and the people they concern."""

    def __init__(self, tenant_id: uuid.UUID, priya: uuid.UUID, ali: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.priya = priya
        self.ali = ali


def _fact(
    statement: str,
    *,
    kind: FactKind = FactKind.DELIVERY,
    evidence: list[tuple[str, str, str | None]] | None = None,
    people: list[str] | None = None,
    at: datetime | None = MONDAY,
) -> Fact:
    """One fact. Evidence entries are `(source, evidence_id, project)`."""
    refs = evidence or [("github", f"ev-{uuid.uuid4().hex[:8]}", "acme/payments")]
    return Fact(
        kind=kind,
        statement=statement,
        sources=[
            SourceRef(source=source, evidence_id=evidence_id, project=project)
            for source, evidence_id, project in refs
        ],
        certainty=Certainty.VERIFIED,
        people=people or [],
        occurred_at=at,
    )


@pytest.fixture
async def workspace(platform: AsyncSession, embedder: HashingEmbedder) -> Workspace:
    """Three current facts, one superseded, two people, two projects."""
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name="Acme", slug=f"feed-{suffix}")
    platform.add(tenant)
    await platform.flush()

    priya = Person(tenant_id=tenant.id, display_name="Priya Nair")
    ali = Person(tenant_id=tenant.id, display_name="Ali Hassan")
    platform.add_all([priya, ali])
    await platform.flush()
    platform.add_all(
        [
            Identity(
                tenant_id=tenant.id,
                person_id=priya.id,
                kind=IdentityKind.GITHUB_LOGIN,
                value=f"priya-{suffix}",
            ),
            Identity(
                tenant_id=tenant.id,
                person_id=ali.id,
                kind=IdentityKind.GITHUB_LOGIN,
                value=f"ali-{suffix}",
            ),
        ]
    )
    await platform.commit()

    facts = [
        _fact(
            "Priya shipped rate limiting to production.",
            evidence=[("github", f"ev-pr-{suffix}", "acme/payments")],
            people=["Priya Nair"],
            at=MONDAY,
        ),
        _fact(
            "Ali is blocked on the staging certificate.",
            kind=FactKind.BLOCKER,
            evidence=[("chat", f"ev-msg-{suffix}", None)],
            people=["Ali Hassan"],
            at=TUESDAY,
        ),
        _fact(
            "The team chose to throttle write endpoints at the gateway.",
            kind=FactKind.DECISION,
            evidence=[("github", f"ev-issue-{suffix}", "acme/gateway")],
            people=["Priya Nair"],
            at=WEDNESDAY,
        ),
    ]

    async with tenant_session(tenant.id) as session:
        await store.apply(session, tenant_id=tenant.id, incoming=facts)
        for stored in facts:
            await store.attach_people(session, tenant_id=tenant.id, fact_id=stored.id)
        await graph.build(session, tenant_id=tenant.id, embedder=embedder)
        await session.commit()

    return Workspace(tenant.id, priya.id, ali.id)


async def statements(tenant_id: uuid.UUID, filters: feed.FeedFilters) -> set[str]:
    async with tenant_session(tenant_id) as session:
        rows = await session.scalars(select(FactRow).where(*feed.conditions(tenant_id, filters)))
        return {row.statement for row in rows}


async def found(
    tenant_id: uuid.UUID,
    query: str,
    *,
    filters: feed.FeedFilters | None = None,
    embedder: HashingEmbedder | None = None,
    limit: int = 25,
) -> list[feed.Hit]:
    async with tenant_session(tenant_id) as session:
        return await feed.search(
            session,
            tenant_id=tenant_id,
            query=query,
            filters=filters or feed.FeedFilters(),
            limit=limit,
            embedder=embedder,
        )


# --------------------------------------------------------------------------
# Filtering
# --------------------------------------------------------------------------


class TestFilters:
    """The first half of the exit criterion: person, project, source, date."""

    async def test_filtering_by_person_returns_only_their_facts(self, workspace: Workspace) -> None:
        everything = await statements(workspace.tenant_id, feed.FeedFilters())
        assert "Ali is blocked on the staging certificate." in everything, "positive control"

        mine = await statements(workspace.tenant_id, feed.FeedFilters(people=(workspace.priya,)))
        assert "Priya shipped rate limiting to production." in mine
        assert "Ali is blocked on the staging certificate." not in mine

    async def test_filtering_by_project_uses_the_evidence_not_the_statement(
        self, workspace: Workspace
    ) -> None:
        """The project is a property of the citation, so this is checkable.

        A reader who filters to `acme/gateway` and opens the source sees a
        gateway artefact. Had the project been inferred from the wording of the
        statement, the filter would be an opinion about text.
        """
        gateway = await statements(
            workspace.tenant_id, feed.FeedFilters(projects=("acme/gateway",))
        )
        assert gateway == {"The team chose to throttle write endpoints at the gateway."}

    async def test_evidence_with_no_project_is_not_swept_into_one(
        self, workspace: Workspace
    ) -> None:
        """Null means "this source names no project", not "unknown, assume the
        main one". A chat message filed under a repository nobody linked it to is
        a citation that fails when a reader opens it."""
        payments = await statements(
            workspace.tenant_id, feed.FeedFilters(projects=("acme/payments",))
        )
        assert "Ali is blocked on the staging certificate." not in payments

    async def test_filtering_by_source_returns_only_that_source(self, workspace: Workspace) -> None:
        chat = await statements(workspace.tenant_id, feed.FeedFilters(sources=("chat",)))
        assert chat == {"Ali is blocked on the staging certificate."}

    async def test_filtering_by_date_uses_when_the_work_happened(
        self, workspace: Workspace
    ) -> None:
        """`occurred_at`, not `created_at`. A backfill ingested today must not
        appear as today's activity — the distinction the fact table exists to
        keep."""
        window = await statements(
            workspace.tenant_id,
            feed.FeedFilters(since=TUESDAY, until=TUESDAY + timedelta(hours=1)),
        )
        assert window == {"Ali is blocked on the staging certificate."}

    async def test_an_undated_fact_survives_a_date_filter(self, workspace: Workspace) -> None:
        """Its date is unknown, not "outside the window".

        Dropping it would silently remove every fact from a source that does not
        timestamp reliably — a whole integration disappearing the moment somebody
        touches a date control.
        """
        undated = _fact("Nobody recorded when the runbook was rewritten.", at=None)
        async with tenant_session(workspace.tenant_id) as session:
            await store.apply(session, tenant_id=workspace.tenant_id, incoming=[undated])
            await session.commit()

        window = await statements(workspace.tenant_id, feed.FeedFilters(since=MONDAY, until=MONDAY))
        assert "Nobody recorded when the runbook was rewritten." in window

    async def test_filters_intersect_rather_than_accumulate(self, workspace: Workspace) -> None:
        """Two filters mean *and*. Union would be the behaviour where narrowing a
        feed makes it longer, which nobody has ever wanted from a filter."""
        both = await statements(
            workspace.tenant_id,
            feed.FeedFilters(people=(workspace.priya,), projects=("acme/gateway",)),
        )
        assert both == {"The team chose to throttle write endpoints at the gateway."}

    async def test_a_fact_with_two_matching_sources_is_returned_once(
        self, workspace: Workspace
    ) -> None:
        """The reason the filters are `EXISTS` subqueries and not joins.

        A fact citing two GitHub artefacts appears twice under a join, which
        double-counts it against `limit` and gives a reader a page with a
        duplicate on it — the kind of defect that only shows up on the facts that
        are best corroborated.
        """
        suffix = uuid.uuid4().hex[:8]
        twice = _fact(
            "The migration was reviewed in two places.",
            evidence=[
                ("github", f"ev-a-{suffix}", "acme/payments"),
                ("github", f"ev-b-{suffix}", "acme/payments"),
            ],
        )
        async with tenant_session(workspace.tenant_id) as session:
            await store.apply(session, tenant_id=workspace.tenant_id, incoming=[twice])
            await session.commit()

        async with tenant_session(workspace.tenant_id) as session:
            rows = list(
                await session.scalars(
                    select(FactRow).where(
                        *feed.conditions(
                            workspace.tenant_id,
                            feed.FeedFilters(sources=("github",), projects=("acme/payments",)),
                        )
                    )
                )
            )

        matching = [
            row for row in rows if row.statement == "The migration was reviewed in two places."
        ]
        assert len(matching) == 1

    async def test_superseded_facts_are_excluded_unless_asked_for(
        self, workspace: Workspace
    ) -> None:
        """ "Ali is working on authentication", three weeks after he moved to
        billing, is the failure that destroys trust (md/09 §3.2) — and it reaches
        a reader through a feed as easily as through a brief."""
        async with tenant_session(workspace.tenant_id) as session:
            await store.apply(
                session,
                tenant_id=workspace.tenant_id,
                incoming=[
                    _fact("Ali is no longer blocked on the staging certificate.", at=WEDNESDAY)
                ],
            )
            row = await session.scalar(
                select(FactRow).where(
                    FactRow.statement == "Ali is blocked on the staging certificate."
                )
            )
            assert row is not None
            successor = await session.scalar(
                select(FactRow).where(
                    FactRow.statement == "Ali is no longer blocked on the staging certificate."
                )
            )
            assert successor is not None
            row.valid_until = WEDNESDAY
            row.superseded_by_id = successor.id
            await session.commit()

        current = await statements(workspace.tenant_id, feed.FeedFilters())
        assert "Ali is blocked on the staging certificate." not in current

        history = await statements(workspace.tenant_id, feed.FeedFilters(include_superseded=True))
        assert "Ali is blocked on the staging certificate." in history

    def test_an_unfiltered_feed_knows_it_is_unfiltered(self) -> None:
        """What the empty state branches on.

        "Nothing matches these filters" and "nothing has been recorded yet" are
        different situations, and telling somebody with an empty workspace to try
        clearing filters they never set wastes their time.
        """
        assert not feed.FeedFilters().is_narrowed
        assert feed.FeedFilters(sources=("github",)).is_narrowed
        assert feed.FeedFilters(since=MONDAY).is_narrowed


# --------------------------------------------------------------------------
# Facets
# --------------------------------------------------------------------------


class TestFacets:
    async def test_only_values_that_actually_match_something_are_offered(
        self, workspace: Workspace
    ) -> None:
        """A menu offering "Meetings" to a workspace that never connected one
        produces an empty result the reader blames on the product — and they are
        right to, because the product offered it."""
        async with tenant_session(workspace.tenant_id) as session:
            found_facets = await feed.facets(session, tenant_id=workspace.tenant_id)

        assert set(found_facets.sources) == {"github", "chat"}
        assert set(found_facets.projects) == {"acme/payments", "acme/gateway"}
        assert {name for _, name in found_facets.people} == {"Priya Nair", "Ali Hassan"}

    async def test_a_person_with_nothing_current_is_not_offered(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        """Somebody who joined and has no activity yet is not a filter value.

        Offering their name and returning nothing reads as "CAIRN has nothing on
        them", which is a statement about a person the feed has no business
        making from an empty query.
        """
        newcomer = Person(tenant_id=workspace.tenant_id, display_name="Sam Okafor")
        platform.add(newcomer)
        await platform.commit()

        async with tenant_session(workspace.tenant_id) as session:
            found_facets = await feed.facets(session, tenant_id=workspace.tenant_id)

        assert "Sam Okafor" not in {name for _, name in found_facets.people}

    async def test_one_workspace_s_facets_do_not_describe_another_s(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        other = Tenant(name="Other", slug=f"feed-other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(other.id) as session:
            theirs = await feed.facets(session, tenant_id=other.id)

        assert theirs.projects == []
        assert theirs.sources == []
        assert theirs.people == []


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------


class TestSearchIsGrounded:
    """The second half of the exit criterion, and the half with a definition."""

    async def test_every_result_is_a_stored_fact_carrying_its_evidence(
        self, workspace: Workspace
    ) -> None:
        hits = await found(workspace.tenant_id, "rate limiting")

        assert hits, "search found nothing for words that are in a stored statement"
        async with tenant_session(workspace.tenant_id) as session:
            stored = {row.statement for row in await session.scalars(select(FactRow))}

        for hit in hits:
            # Byte-identical to what is in the table. A summarised or reworded
            # result is one nobody can check against the source.
            assert hit.fact.statement in stored
            assert hit.fact.sources, "a search result reached a reader without provenance"
            for source in hit.fact.sources:
                assert source.evidence_id

    async def test_the_response_has_nowhere_for_generated_prose_to_live(self) -> None:
        """Structure, because behaviour cannot see this one.

        Nothing on the search path calls a model today. The way that changes is
        somebody adding an `answer` field and filling it in later, so the shape
        of the result is asserted directly: a search result is a fact and a label
        for how it was matched, and there is no third thing.
        """
        assert set(feed.Hit.__slots__) == {"fact", "matched_on"}

    async def test_search_finds_by_words_and_says_so(self, workspace: Workspace) -> None:
        hits = await found(workspace.tenant_id, "throttle")

        assert [hit.fact.statement for hit in hits] == [
            "The team chose to throttle write endpoints at the gateway."
        ]
        assert hits[0].matched_on == "words"

    async def test_a_result_found_only_by_meaning_is_labelled_as_such(
        self, workspace: Workspace, embedder: HashingEmbedder
    ) -> None:
        """The label is the honesty, not the ranking.

        No assertion is made about *which* fact similarity returns —
        `HashingEmbedder` has no notion of meaning, and a trained model's
        ranking is not a fixed quantity to write assertions against. What must
        hold either way is that a result containing none of the reader's words is
        never presented as though it contained them.
        """
        hits = await found(workspace.tenant_id, "throttle", embedder=embedder)

        for hit in hits:
            if "throttle" not in hit.fact.statement.lower():
                assert hit.matched_on == "meaning"

    async def test_search_without_an_embedder_still_works(self, workspace: Workspace) -> None:
        """Offline, embeddings are hashes: real, deterministic, meaningless.

        Passing them into a result list would fill it with confident noise, and a
        bad semantic hit is indistinguishable from a good one to the person
        reading it. So the lexical half runs alone rather than the endpoint
        failing or degrading silently.
        """
        hits = await found(workspace.tenant_id, "staging certificate", embedder=None)

        assert [hit.fact.statement for hit in hits] == [
            "Ali is blocked on the staging certificate."
        ]

    async def test_search_applies_the_feed_s_filters(self, workspace: Workspace) -> None:
        """Narrowing the screen and then typing must not widen it again."""
        hits = await found(
            workspace.tenant_id,
            "rate limiting",
            filters=feed.FeedFilters(projects=("acme/gateway",)),
        )
        assert hits == []

        unfiltered = await found(workspace.tenant_id, "rate limiting")
        assert unfiltered, "positive control: the fact is findable without the filter"

    async def test_search_never_returns_a_superseded_fact(self, workspace: Workspace) -> None:
        async with tenant_session(workspace.tenant_id) as session:
            row = await session.scalar(
                select(FactRow).where(
                    FactRow.statement == "Priya shipped rate limiting to production."
                )
            )
            assert row is not None
            successor = _fact("Priya reverted rate limiting.", at=WEDNESDAY)
            await store.apply(session, tenant_id=workspace.tenant_id, incoming=[successor])
            row.valid_until = WEDNESDAY
            row.superseded_by_id = successor.id
            await session.commit()

        hits = await found(workspace.tenant_id, "rate limiting")
        assert "Priya shipped rate limiting to production." not in {
            hit.fact.statement for hit in hits
        }

    @pytest.mark.parametrize(
        "query",
        [
            'an "unbalanced quote',
            "& | ! ( )",
            "-",
            "a" * 200,
            "café ünïcode",
        ],
    )
    async def test_a_query_a_person_could_type_never_raises(
        self, workspace: Workspace, query: str
    ) -> None:
        """`websearch_to_tsquery`, not `to_tsquery`.

        The latter raises a syntax error on ordinary input — a stray ampersand,
        an unbalanced quote — which turns somebody's typing into a 500. This is
        the test that pins the choice, because both functions look identical on
        well-formed input.
        """
        assert await found(workspace.tenant_id, query) is not None

    async def test_one_workspace_cannot_search_another_s_facts(
        self, platform: AsyncSession, workspace: Workspace
    ) -> None:
        assert await found(workspace.tenant_id, "rate limiting"), "positive control"

        other = Tenant(name="Other", slug=f"feed-x-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        assert await found(other.id, "rate limiting") == []

    async def test_relevance_beats_recency(self, workspace: Workspace) -> None:
        """A feed is chronological; a search is not.

        Ranking search by date would make it a filter with a text box, and the
        thing a reader is looking for is nearly always the one that matches best
        rather than the one that happened last.
        """
        hits = await found(workspace.tenant_id, "rate limiting")
        assert hits[0].fact.statement == "Priya shipped rate limiting to production."


class TestOverHttp:
    """The endpoints, over the real ASGI stack.

    The query layer above is where the logic lives; these prove a reader can
    reach it. A filter that works in `feed.py` and is not wired to a route is
    the "unreachable layer" failure this project has already had once.
    """

    async def test_a_reader_can_filter_the_feed_by_source(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        workspace_id = await _signed_in_workspace(client)
        await _seed_over_http(uuid.UUID(workspace_id))

        everything = await client.get(f"/v1/workspaces/{workspace_id}/facts")
        assert everything.status_code == 200, everything.text
        assert len(everything.json()["items"]) == 2, "positive control"

        filtered = await client.get(
            f"/v1/workspaces/{workspace_id}/facts", params={"source": "chat"}
        )
        assert filtered.status_code == 200, filtered.text
        [item] = filtered.json()["items"]
        assert item["statement"] == "Ali is blocked on the staging certificate."

    async def test_the_facets_endpoint_describes_the_workspace(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        workspace_id = await _signed_in_workspace(client)
        await _seed_over_http(uuid.UUID(workspace_id))

        response = await client.get(f"/v1/workspaces/{workspace_id}/facets")
        assert response.status_code == 200, response.text
        body = response.json()

        assert set(body["sources"]) == {"github", "chat"}
        assert body["projects"] == ["acme/payments"]
        assert [person["name"] for person in body["people"]] == []

    async def test_search_returns_facts_with_citations_and_no_prose(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """The exit criterion over HTTP.

        The assertion about *absent* fields is the load-bearing one: a response
        with an `answer` or a `summary` on it would mean the endpoint had started
        composing, and every result below it would be decoration.
        """
        workspace_id = await _signed_in_workspace(client)
        await _seed_over_http(uuid.UUID(workspace_id))

        response = await client.get(
            f"/v1/workspaces/{workspace_id}/search", params={"q": "rate limiting"}
        )
        assert response.status_code == 200, response.text
        body = response.json()

        assert set(body) == {"items", "truncated", "semantic"}
        [hit] = body["items"]
        assert hit["fact"]["statement"] == "Priya shipped rate limiting to production."
        assert hit["matchedOn"] == "words"
        assert hit["fact"]["sources"][0]["evidenceId"]
        assert hit["fact"]["sources"][0]["project"] == "acme/payments"
        # Offline, the embedder is a hash. Reported rather than hidden, so a
        # reader comparing environments can see that one of the two ways of
        # matching was not running.
        assert body["semantic"] is False

    async def test_a_full_page_is_not_reported_as_truncated(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """`truncated` answers "was anything left behind", not "is the page full".

        Comparing the count to the limit reports truncation whenever the corpus
        holds exactly `limit` matches — telling a reader to narrow a search that
        already returned everything.
        """
        workspace_id = await _signed_in_workspace(client)
        await _seed_over_http(uuid.UUID(workspace_id))

        exact = await client.get(
            f"/v1/workspaces/{workspace_id}/search", params={"q": "rate limiting", "limit": 1}
        )
        assert exact.status_code == 200, exact.text
        body = exact.json()
        assert len(body["items"]) == 1
        assert body["truncated"] is False, "a page holding every match claimed it was cut short"

    async def test_more_matches_than_asked_for_are_reported_as_truncated(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """The positive control: a search that genuinely stopped short says so.

        A search quietly returning its first results of many looks identical to
        one that found only those.
        """
        workspace_id = await _signed_in_workspace(client)
        tenant_id = uuid.UUID(workspace_id)
        suffix = uuid.uuid4().hex[:8]

        # Distinct subjects, not numbered variants of one sentence: resolution
        # merges near-duplicates on the way in, which is correct and would leave
        # this test asserting against a single stored fact.
        statements = [
            "Rate limiting reached the payments service.",
            "The runbook now documents rate limiting for on-call.",
            "Security reviewed rate limiting before the release.",
        ]
        async with tenant_session(tenant_id) as session:
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    _fact(
                        statement,
                        evidence=[("github", f"ev-{suffix}-{index}", "acme/payments")],
                    )
                    for index, statement in enumerate(statements)
                ],
            )
            await session.commit()

        response = await client.get(
            f"/v1/workspaces/{workspace_id}/search", params={"q": "rate limiting", "limit": 2}
        )
        body = response.json()
        assert len(body["items"]) == 2
        assert body["truncated"] is True

    async def test_search_refuses_an_empty_query_rather_than_returning_everything(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        """`?q=` returning the whole workspace would look like search working."""
        workspace_id = await _signed_in_workspace(client)
        response = await client.get(f"/v1/workspaces/{workspace_id}/search", params={"q": ""})
        assert response.status_code == 422

    async def test_a_stranger_can_neither_search_nor_read_the_facets(
        self, app: FastAPI, client: AsyncClient
    ) -> None:
        workspace_id = await _signed_in_workspace(client)
        await _seed_over_http(uuid.UUID(workspace_id))

        assert (
            await client.get(f"/v1/workspaces/{workspace_id}/search", params={"q": "rate"})
        ).status_code == 200, "positive control"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": TEST_ORIGIN},
        ) as stranger:
            await _signed_in_workspace(stranger)
            for path in ("search", "facets"):
                response = await stranger.get(
                    f"/v1/workspaces/{workspace_id}/{path}", params={"q": "rate"}
                )
                assert response.status_code == 404, f"{path}: {response.text}"


async def _signed_in_workspace(client: AsyncClient) -> str:
    suffix = uuid.uuid4().hex[:10]
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"feed-{suffix}@example.com",
            "password": "correct-horse-battery",
            "workspaceName": "Acme",
            "workspaceSlug": f"feed-http-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    workspace_id: str = response.json()["workspaces"][0]["workspace"]["id"]
    return workspace_id


async def _seed_over_http(tenant_id: uuid.UUID) -> None:
    """Two facts, written the way the pipeline writes them."""
    suffix = uuid.uuid4().hex[:8]
    async with tenant_session(tenant_id) as session:
        await store.apply(
            session,
            tenant_id=tenant_id,
            incoming=[
                _fact(
                    "Priya shipped rate limiting to production.",
                    evidence=[("github", f"ev-pr-{suffix}", "acme/payments")],
                    at=MONDAY,
                ),
                _fact(
                    "Ali is blocked on the staging certificate.",
                    kind=FactKind.BLOCKER,
                    evidence=[("chat", f"ev-msg-{suffix}", None)],
                    at=TUESDAY,
                ),
            ],
        )
        await session.commit()


class TestFusion:
    """Merging two rankings, tested without a database.

    Rank fusion is arithmetic over positions, and the properties worth pinning
    are about the labels rather than the scores.
    """

    def _row(self, statement: str) -> FactRow:
        return FactRow(id=uuid.uuid4(), statement=statement, kind="delivery", certainty="verified")

    def test_a_fact_found_both_ways_is_labelled_by_its_words(self) -> None:
        """It genuinely contains what the reader typed, which is the stronger
        statement to make about it. The label exists to warn about results that
        contain none of their words."""
        row = self._row("Shipped the limiter.")
        [hit] = feed._fuse([row], [row])
        assert hit.matched_on == "words"

    def test_agreement_between_the_two_rankers_wins(self) -> None:
        """A fact both rankers found outranks one that only appeared in a single
        list — which is the entire reason to fuse rather than concatenate."""
        both = self._row("Rate limiting shipped.")
        lexical_only = self._row("Rate limits were discussed.")
        semantic_only = self._row("Throttling was introduced.")

        hits = feed._fuse([lexical_only, both], [both, semantic_only])
        assert hits[0].fact is both

    def test_an_empty_side_is_not_an_empty_result(self) -> None:
        row = self._row("Shipped the limiter.")
        assert [hit.fact for hit in feed._fuse([row], [])] == [row]
        assert [hit.fact for hit in feed._fuse([], [row])] == [row]
