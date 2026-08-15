"""The Founder Brief: provenance you can click, and an archive that keeps its word.

Step 21's exit criterion is **every claim links to its source in one click**, and
the first test here is the one that would have failed before this step: citations
used to be bare evidence identifiers. `ev-pr-482` satisfies "every claim carries
a citation" and fails the thing a citation is *for* — a reader cannot check it.

The rest is about the archive, and one property in particular. A brief is
something the product *said* to a team. If opening Tuesday re-runs the model over
facts that have since been corrected, the archive rewrites what was said, and
"you told us on Tuesday that payments had shipped" stops being answerable. So a
finished period is written once and served from storage; the current period is
never written — only reused for a few minutes, which is what the last class here
holds the line on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cairn_api.api import briefs
from cairn_api.api.ratelimit import InMemoryRateLimiter
from cairn_api.api.routers.facts import BRIEF_PER_WORKSPACE
from cairn_api.api.schemas import BriefResponse
from cairn_api.db.brief_models import Brief, BriefClaim
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.domain import Certainty
from cairn_api.pipeline.corrections import CorrectionKind, apply_correction
from cairn_api.pipeline.synthesize import Brief as SynthesisedBrief
from cairn_api.pipeline.synthesize import BriefClaim as SynthesisedClaim
from cairn_api.pipeline.synthesize import Suppression
from conftest_api import TEST_ORIGIN
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
TUESDAY = MONDAY + timedelta(days=1)


@pytest.fixture
async def tenant_id(platform: AsyncSession) -> uuid.UUID:
    tenant = Tenant(name="Acme", slug=f"brief-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.commit()
    return tenant.id


async def add_fact(
    tenant_id: uuid.UUID,
    *,
    statement: str = "Priya shipped rate limiting.",
    url: str | None = "https://github.com/acme/api/pull/482",
    evidence_id: str = "ev-pr-482",
    source: str = "github",
    quote: str | None = None,
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        row = FactRow(
            tenant_id=tenant_id,
            kind="delivery",
            statement=statement,
            certainty="verified",
            occurred_at=MONDAY,
            valid_from=MONDAY,
            sources=[
                FactSource(
                    tenant_id=tenant_id,
                    source=source,
                    evidence_id=evidence_id,
                    url=url,
                    quote=quote,
                )
            ],
        )
        session.add(row)
        await session.commit()
        return row.id


def synthesised(*claims: SynthesisedClaim, suppressed: int = 0) -> SynthesisedBrief:
    return SynthesisedBrief(
        narrative=" ".join(claim.text for claim in claims),
        claims=list(claims),
        suppressed=[Suppression(text="dropped", reason="not supported") for _ in range(suppressed)],
        abstained=not claims,
    )


def claim(fact_id: uuid.UUID, *, text: str = "Priya shipped rate limiting.") -> SynthesisedClaim:
    return SynthesisedClaim(
        text=text,
        certainty=Certainty.VERIFIED,
        fact_ids=(fact_id,),
        citations=("ev-pr-482",),
        credits=("priya",),
    )


class TestOneClickToTheSource:
    """The exit criterion."""

    async def test_every_claim_carries_a_resolvable_link(self, tenant_id: uuid.UUID) -> None:
        fact_id = await add_fact(tenant_id)

        async with tenant_session(tenant_id) as session:
            stored = await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=synthesised(claim(fact_id)),
                model="offline",
                truncated=False,
            )
            assert stored is not None
            await session.commit()

        async with tenant_session(tenant_id) as session:
            reloaded = await briefs.load_stored(
                session, tenant_id=tenant_id, start=MONDAY, end=TUESDAY
            )
            assert reloaded is not None
            citations = await briefs.resolve_citations(
                session,
                tenant_id=tenant_id,
                fact_ids={fact_id},
            )
            response = briefs.to_response(reloaded, citations)

        [only] = response.claims
        assert only.citations, "a claim reached the reader with nothing to open"
        assert only.citations[0].url == "https://github.com/acme/api/pull/482"
        assert only.citations[0].evidence_id == "ev-pr-482"

    async def test_evidence_without_a_permalink_is_still_shown(self, tenant_id: uuid.UUID) -> None:
        """A meeting transcript has no URL, and hiding the citation is worse.

        An unlinked citation is provenance a person can go and check; a hidden
        one silently breaks the promise the whole feature rests on.
        """
        fact_id = await add_fact(
            tenant_id,
            source="meeting",
            evidence_id="ev-standup-11",
            url=None,
            quote="We agreed to stage the payments cutover.",
        )

        async with tenant_session(tenant_id) as session:
            citations = await briefs.resolve_citations(
                session, tenant_id=tenant_id, fact_ids={fact_id}
            )

        [citation] = citations[fact_id]
        assert citation.url is None
        assert citation.source == "meeting"
        assert citation.quote == "We agreed to stage the payments cutover."

    async def test_two_facts_from_one_pull_request_cite_it_once(self, tenant_id: uuid.UUID) -> None:
        """Printing the same source twice makes provenance look padded.

        Which is the opposite of what it is for — a reader counts links to
        gauge how much is behind a sentence.
        """
        first = await add_fact(tenant_id, statement="Priya shipped rate limiting.")
        second = await add_fact(tenant_id, statement="Rate limiting removed the legacy throttle.")

        async with tenant_session(tenant_id) as session:
            citations = await briefs.resolve_citations(
                session, tenant_id=tenant_id, fact_ids={first, second}
            )

        merged = briefs.citations_for([first, second], citations)
        assert len(merged) == 1

    async def test_a_link_corrected_in_the_source_appears_in_an_old_brief(
        self, tenant_id: uuid.UUID
    ) -> None:
        """Citations are resolved at read time, not frozen into the brief.

        The citation points at *evidence*, which is stable, rather than at a URL
        recorded months ago — so a repository renamed after Tuesday's brief was
        written does not leave Tuesday linking into nothing.
        """
        fact_id = await add_fact(tenant_id, url="https://github.com/acme/old-name/pull/482")

        async with tenant_session(tenant_id) as session:
            stored = await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=synthesised(claim(fact_id)),
                model="offline",
                truncated=False,
            )
            assert stored is not None
            await session.commit()

        async with tenant_session(tenant_id) as session:
            source = await session.scalar(select(FactSource).where(FactSource.fact_id == fact_id))
            assert source is not None
            source.url = "https://github.com/acme/api/pull/482"
            await session.commit()

        async with tenant_session(tenant_id) as session:
            reloaded = await briefs.load_stored(
                session, tenant_id=tenant_id, start=MONDAY, end=TUESDAY
            )
            assert reloaded is not None
            citations = await briefs.resolve_citations(
                session, tenant_id=tenant_id, fact_ids={fact_id}
            )
            response = briefs.to_response(reloaded, citations)

        assert response.claims[0].citations[0].url == "https://github.com/acme/api/pull/482"


class TestTheArchiveIsARecord:
    def test_a_finished_period_is_a_record_and_the_current_one_is_not(self) -> None:
        now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

        assert briefs.is_complete(now - timedelta(seconds=1), now=now) is True
        assert briefs.is_complete(now + timedelta(hours=1), now=now) is False

    async def test_storing_the_same_period_twice_keeps_the_first_words(
        self, tenant_id: uuid.UUID
    ) -> None:
        """Two readers opening the same day both generate a brief.

        The loser of that race must keep the winner's words. Which of the two is
        kept does not matter; that the archive holds *one* of them, permanently,
        does — an archive that changes when it is read is not an archive.
        """
        fact_id = await add_fact(tenant_id)

        async with tenant_session(tenant_id) as session:
            first = await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=synthesised(claim(fact_id, text="The first version.")),
                model="offline",
                truncated=False,
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            second = await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=synthesised(claim(fact_id, text="A different second version.")),
                model="offline",
                truncated=False,
            )
            await session.commit()

        assert first is not None
        assert second is None, "the second write should have been refused, not applied"

        async with tenant_session(tenant_id) as session:
            reloaded = await briefs.load_stored(
                session, tenant_id=tenant_id, start=MONDAY, end=TUESDAY
            )
            assert reloaded is not None
            assert reloaded.claims[0].text == "The first version."

    async def test_claims_keep_the_order_they_were_written_in(self, tenant_id: uuid.UUID) -> None:
        """The order is the writing.

        Claims reordered by whatever the database returned would read as a
        different brief every time it was opened.
        """
        fact_id = await add_fact(tenant_id)
        texts = ["First sentence.", "Second sentence.", "Third sentence."]

        async with tenant_session(tenant_id) as session:
            await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=synthesised(*(claim(fact_id, text=text) for text in texts)),
                model="offline",
                truncated=False,
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            reloaded = await briefs.load_stored(
                session, tenant_id=tenant_id, start=MONDAY, end=TUESDAY
            )
            assert reloaded is not None
            assert [item.text for item in reloaded.claims] == texts

    async def test_a_superseded_fact_does_not_erase_the_brief_that_cited_it(
        self, tenant_id: uuid.UUID
    ) -> None:
        """No foreign key on `fact_ids`, and this is why.

        A correction should change tomorrow's brief. It must not reach back and
        delete the citation from the record of what was already read.
        """
        fact_id = await add_fact(tenant_id)

        async with tenant_session(tenant_id) as session:
            await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=synthesised(claim(fact_id)),
                model="offline",
                truncated=False,
            )
            await session.commit()

        # Supersede the fact the brief rests on, the way a correction would.
        async with tenant_session(tenant_id) as session:
            successor = FactRow(
                tenant_id=tenant_id,
                kind="delivery",
                statement="Priya shipped rate limiting to staging, not production.",
                certainty="verified",
                occurred_at=TUESDAY,
                valid_from=TUESDAY,
                sources=[FactSource(tenant_id=tenant_id, source="github", evidence_id="ev-pr-511")],
            )
            session.add(successor)
            await session.flush()

            original = await session.get(FactRow, fact_id)
            assert original is not None
            original.valid_until = TUESDAY
            original.superseded_by_id = successor.id
            await session.commit()

        async with tenant_session(tenant_id) as session:
            reloaded = await briefs.load_stored(
                session, tenant_id=tenant_id, start=MONDAY, end=TUESDAY
            )
            assert reloaded is not None
            citations = await briefs.resolve_citations(
                session, tenant_id=tenant_id, fact_ids={fact_id}
            )
            response = briefs.to_response(reloaded, citations)

        assert response.claims[0].text == "Priya shipped rate limiting."
        assert response.claims[0].citations[0].evidence_id == "ev-pr-482"

    async def test_the_archive_summary_is_scannable_and_bounded(self, tenant_id: uuid.UUID) -> None:
        """A clipped line in CSS still ships the whole paragraph.

        An archive of five hundred briefs would send all of it to render a list
        of dates.
        """
        fact_id = await add_fact(tenant_id)
        long_narrative = "The team shipped a great deal this week. " * 20

        async with tenant_session(tenant_id) as session:
            stored = await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=SynthesisedBrief(
                    narrative=long_narrative,
                    claims=[claim(fact_id)],
                    suppressed=[],
                ),
                model="offline",
                truncated=False,
            )
            assert stored is not None
            summary = briefs.summarise(stored)

        assert len(summary.excerpt) <= briefs.EXCERPT_CHARS + 1
        assert summary.excerpt.endswith("…")
        assert summary.claim_count == 1

    async def test_another_workspace_sees_no_briefs(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        fact_id = await add_fact(tenant_id)
        async with tenant_session(tenant_id) as session:
            await briefs.store(
                session,
                tenant_id=tenant_id,
                start=MONDAY,
                end=TUESDAY,
                brief=synthesised(claim(fact_id)),
                model="offline",
                truncated=False,
            )
            await session.commit()

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(other.id) as session:
            assert (await session.scalars(select(Brief))).all() == []
            assert (await session.scalars(select(BriefClaim))).all() == []


class Generations:
    """Counts model calls, and gives each one words a test can tell apart."""

    def __init__(self) -> None:
        self.count = 0

    async def synthesize(self, provider: Any, *, facts: Any, period: str) -> SynthesisedBrief:
        self.count += 1
        return SynthesisedBrief(narrative=f"generation {self.count}", claims=[], suppressed=[])


@pytest.fixture
def generations(monkeypatch: pytest.MonkeyPatch) -> Generations:
    counted = Generations()
    monkeypatch.setattr("cairn_api.api.routers.facts.synthesize", counted.synthesize)
    return counted


def current_period() -> dict[str, str]:
    """A period that has not ended, with both ends stated.

    Stated rather than defaulted so the cache key is exact: a defaulted period
    ends "now" and is rounded to the freshness window, which is right in
    production and the wrong thing to hang a timing-sensitive test on.
    """
    now = datetime.now(UTC)
    return {
        "since": (now - timedelta(days=1)).isoformat(),
        "until": (now + timedelta(minutes=10)).isoformat(),
    }


def finished_period() -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "since": (now - timedelta(days=2)).isoformat(),
        "until": (now - timedelta(days=1)).isoformat(),
    }


async def signed_in_workspace(client: AsyncClient) -> tuple[str, uuid.UUID]:
    suffix = uuid.uuid4().hex[:10]
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"brief-{suffix}@example.com",
            "password": "correct-horse-battery",
            "workspaceName": "Acme",
            "workspaceSlug": f"brief-http-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["workspaces"][0]["workspace"]["id"], uuid.UUID(body["user"]["id"])


class TestTheCurrentPeriodIsReusedForAFewMinutes:
    """P2-4: twelve briefs an hour is a budget five readers exhaust by lunchtime.

    The endpoint charges the budget for *generating* a brief, so a read that
    reuses one must neither call the model nor spend a unit â€” and must still be
    an ordinary brief to whoever asked for it.
    """

    async def test_two_reads_of_the_current_period_generate_one_brief(
        self, app: FastAPI, client: AsyncClient, generations: Generations
    ) -> None:
        workspace_id, _ = await signed_in_workspace(client)
        period = current_period()

        first = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)
        second = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert generations.count == 1, "the second reader paid for the same paragraph again"
        assert second.json() == first.json()
        # `stored` distinguishes an archived record from a live generation, and
        # a reused brief is still the second of those.
        assert second.json()["stored"] is False

    async def test_a_reused_brief_costs_no_rate_limit_budget(
        self,
        app: FastAPI,
        client: AsyncClient,
        limiter: InMemoryRateLimiter,
        generations: Generations,
    ) -> None:
        """The point of the fix: reading is not what costs money.

        The budget is drained to its last unit first, so the assertion is about
        the units themselves rather than about a counter nobody spends.
        """
        workspace_id, _ = await signed_in_workspace(client)
        for _ in range(BRIEF_PER_WORKSPACE.limit - 1):
            await limiter.check(f"brief:{workspace_id}", BRIEF_PER_WORKSPACE)

        period = current_period()
        first = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)
        assert first.status_code == 200, "the last unit of budget"

        for _ in range(3):
            repeat = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)
            assert repeat.status_code == 200, repeat.text

        # The positive control: the budget really was exhausted, so those reads
        # were free rather than the limit being absent.
        another = {**period, "since": (datetime.now(UTC) - timedelta(days=2)).isoformat()}
        exhausted = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=another)
        assert exhausted.status_code == 429
        assert generations.count == 1

    async def test_a_finished_period_is_still_stored_and_still_archived(
        self, app: FastAPI, client: AsyncClient, generations: Generations
    ) -> None:
        """The existing rule, unweakened.

        A record is written once and served from the archive afterwards. Had the
        cache swallowed it, the archive would be empty and the second read would
        be a live brief wearing a record's clothes.
        """
        workspace_id, _ = await signed_in_workspace(client)
        period = finished_period()

        first = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)
        second = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)

        assert first.status_code == 200, first.text
        assert first.json()["stored"] is True
        assert second.json()["stored"] is True
        assert second.json()["id"] == first.json()["id"]
        assert generations.count == 1

        archive = await client.get(f"/v1/workspaces/{workspace_id}/briefs")
        assert archive.status_code == 200, archive.text
        [entry] = archive.json()["items"]
        assert entry["id"] == first.json()["id"]

    async def test_one_workspace_never_receives_another_s_reused_brief(
        self, app: FastAPI, client: AsyncClient, generations: Generations
    ) -> None:
        """Two workspaces reading the same period at the same moment.

        The periods are identical, so a cache keyed on anything less than the
        workspace would hand one team's morning to another.
        """
        acme, _ = await signed_in_workspace(client)
        period = current_period()

        mine = await client.get(f"/v1/workspaces/{acme}/brief", params=period)
        assert mine.json()["narrative"] == "generation 1"

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": TEST_ORIGIN},
        ) as stranger:
            other, _ = await signed_in_workspace(stranger)
            theirs = await stranger.get(f"/v1/workspaces/{other}/brief", params=period)

        assert theirs.status_code == 200, theirs.text
        assert theirs.json()["narrative"] == "generation 2", "served another workspace's brief"

        again = await client.get(f"/v1/workspaces/{acme}/brief", params=period)
        assert again.json()["narrative"] == "generation 1", "positive control"

    async def test_a_correction_drops_the_reused_brief(
        self, app: FastAPI, client: AsyncClient, generations: Generations
    ) -> None:
        """Somebody who was there disagreed, and waiting five minutes is wrong.

        A correction closes the corrected fact's validity window, which is what
        a reused brief is checked against â€” so the next read regenerates rather
        than repeating a sentence that has just been denied.
        """
        workspace_id, user_id = await signed_in_workspace(client)
        tenant_id = uuid.UUID(workspace_id)
        fact_id = await add_fact(tenant_id, evidence_id=f"ev-{uuid.uuid4().hex[:8]}")
        period = current_period()

        before = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)
        assert before.json()["narrative"] == "generation 1"

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.DID_NOT_HAPPEN,
                user_id=user_id,
            )
            await session.commit()

        corrected = await client.get(f"/v1/workspaces/{workspace_id}/brief", params=period)
        assert corrected.json()["narrative"] == "generation 2"
        assert generations.count == 2


class TestTheFreshnessWindow:
    """The cache itself, without a database or an HTTP stack."""

    def _key(self) -> briefs.CacheKey:
        return (uuid.uuid4(), MONDAY, TUESDAY)

    def _response(self, narrative: str = "words") -> BriefResponse:
        return BriefResponse(
            period_start=MONDAY,
            period_end=TUESDAY,
            generated_at=MONDAY,
            stored=False,
            narrative=narrative,
            claims=[],
            abstained=False,
            suppressed_count=0,
            truncated=False,
        )

    def test_a_brief_is_forgotten_once_the_window_has_passed(self) -> None:
        cache = briefs.BriefCache(ttl_seconds=60)
        key = self._key()
        cache.put(key, self._response(), marker=(0, None), now=0.0)

        assert cache.get(key, marker=(0, None), now=59.0) is not None, "positive control"
        assert cache.get(key, marker=(0, None), now=60.0) is None

    def test_a_retraction_since_the_brief_was_written_drops_it(self) -> None:
        cache = briefs.BriefCache()
        key = self._key()
        cache.put(key, self._response(), marker=(0, None), now=0.0)

        assert cache.get(key, marker=(1, MONDAY), now=1.0) is None

    def test_a_defaulted_period_rounds_so_two_readers_share_one_key(self) -> None:
        """Two people opening the brief seconds apart ask for different periods.

        Their `until` is "now" to the microsecond, and an unrounded key would
        make every read a miss â€” the failure this whole class exists to prevent.
        """
        first = datetime(2026, 8, 15, 9, 1, 3, tzinfo=UTC)
        second = datetime(2026, 8, 15, 9, 4, 59, tzinfo=UTC)

        assert briefs.round_to_window(first) == briefs.round_to_window(second)
        assert briefs.round_to_window(first) == datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        assert briefs.round_to_window(second + timedelta(seconds=1)) != briefs.round_to_window(
            second
        )

    def test_a_reused_brief_cannot_be_mutated_by_whoever_read_it(self) -> None:
        """Every reader gets a copy, not the entry.

        A handler that edited the response it was handed would otherwise edit
        what the next reader is shown.
        """
        cache = briefs.BriefCache()
        key = self._key()
        cache.put(key, self._response("original"), marker=(0, None), now=0.0)

        served = cache.get(key, marker=(0, None), now=1.0)
        assert served is not None
        served.narrative = "tampered"

        again = cache.get(key, marker=(0, None), now=2.0)
        assert again is not None
        assert again.narrative == "original"
