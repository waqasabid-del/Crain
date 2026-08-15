"""Backfill: resumable ninety-day imports that never starve live events.

Step 13's exit criterion: *90 days imported without breaching secondary rate
limits; live events continue processing during backfill.*

The GraphQL client is driven by a fake transport rather than the network. That
is not a compromise — it is the only way to assert what happens when GitHub
returns a secondary rate limit, an expired token, or a 200 carrying an `errors`
array, none of which can be produced on demand against the real API.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cairn_api.db.backfill_models import BackfillRun, BackfillState
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.github.auth import InstallationTokenCache, mint_app_jwt
from cairn_api.github.backfill import (
    LEASE_SECONDS,
    claim,
    claimable_runs,
    create_run,
    process_batch,
)
from cairn_api.github.budget import (
    RESERVED_POINT_FRACTION,
    BudgetExhaustedError,
    RateBudget,
    parse_rate_limit,
)
from cairn_api.github.client import (
    PAGE_SIZE,
    GitHubApiError,
    GitHubGraphQLClient,
    SecondaryRateLimitError,
    to_commit_payload,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: Fresh per test. A shared installation ID collides on the partial unique
#: index that keeps one live run per repository, so tests would pass alone and
#: fail together — the flakiness that trains people to re-run CI.
_INSTALLATION_IDS = itertools.count(424_242)


@pytest.fixture
def installation_id() -> int:
    return next(_INSTALLATION_IDS)


#: For the client tests, which never touch the database.
INSTALLATION = 999_000_001


# --------------------------------------------------------------------------
# Rate budget
# --------------------------------------------------------------------------


class TestRateBudget:
    def test_a_reserve_is_held_back_for_live_traffic(self) -> None:
        # A backfill that drains the budget to zero leaves the customer's
        # *current* activity unprocessable until the window refreshes — the
        # product going quiet exactly when someone is watching it work.
        budget = RateBudget(limit=5000, remaining=1200)

        assert budget.reserve == int(5000 * RESERVED_POINT_FRACTION)
        assert budget.usable == 1200 - budget.reserve

    def test_the_next_page_is_priced_at_the_worst_case(self) -> None:
        # Averaging means the run discovers it cannot afford a page only after
        # spending the points to find out.
        budget = RateBudget(limit=1000, remaining=250)
        for cost in (1, 1, 60):
            budget.observe(limit=1000, remaining=250, reset_at=0, cost=cost)

        # usable = 250 - 200 = 50, and the worst page seen cost 60.
        assert budget.usable == 50
        assert budget.can_afford_next() is False

    def test_an_affordable_page_is_allowed(self) -> None:
        # The positive control: without it, a budget that refused everything
        # would pass the test above.
        budget = RateBudget(limit=1000, remaining=900)
        budget.observe(limit=1000, remaining=900, reset_at=0, cost=5)

        assert budget.can_afford_next() is True

    def test_cost_is_read_from_githubs_own_block(self) -> None:
        # Measured, not estimated. A guessed budget drifts in whichever
        # direction is least convenient, and the symptom is a 403 with no local
        # record of why.
        limit, remaining, reset_at, cost = parse_rate_limit(
            {"limit": 5000, "remaining": 4321, "cost": 17, "resetAt": "2026-08-14T15:00:00Z"}
        )

        assert (limit, remaining, cost) == (5000, 4321, 17)
        assert reset_at > 0

    def test_a_malformed_rate_block_does_not_crash_the_walk(self) -> None:
        # The shape is GitHub's to change. A KeyError here would fail a backfill
        # that was otherwise succeeding, discarding the page it had just paid for.
        limit, remaining, reset_at, cost = parse_rate_limit({"unexpected": True})

        assert (limit, remaining, reset_at, cost) == (5000, 0, 0.0, 1)


# --------------------------------------------------------------------------
# App authentication
# --------------------------------------------------------------------------


# Generated per test run rather than committed.
#
# A PEM in the repository is a PEM the secret scanner has to be taught to
# ignore, and an exception in that scanner is the thing that later hides a real
# key. Generated once per module import.
def _throwaway_private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


TEST_PRIVATE_KEY = _throwaway_private_key()


class TestAppAuth:
    def test_a_jwt_is_backdated_to_absorb_clock_skew(self) -> None:
        # GitHub rejects a JWT whose `iat` is in the future, and a second of
        # skew is enough to trigger an intermittent 401 that reads as a
        # credential problem.
        import jwt

        now = 1_800_000_000
        token = mint_app_jwt(app_id="12345", private_key=TEST_PRIVATE_KEY, now=now)
        claims = jwt.decode(token, options={"verify_signature": False})

        assert claims["iat"] < now
        assert claims["exp"] > now
        assert claims["iss"] == "12345"

    async def test_a_token_is_minted_once_and_reused(self) -> None:
        # Not caching means an extra authenticated round trip before every page
        # — thousands of avoidable requests against the ceiling the backfill is
        # trying to respect.
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                201,
                json={
                    "token": "ghs_secret",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        cache = InstallationTokenCache(app_id="1", private_key=TEST_PRIVATE_KEY, client=client)

        assert await cache.token_for(INSTALLATION) == "ghs_secret"
        assert await cache.token_for(INSTALLATION) == "ghs_secret"
        assert calls == 1

        await client.aclose()

    async def test_an_expiring_token_is_re_minted(self) -> None:
        # A token that expires mid-request produces a 401 on a page that was
        # otherwise fine, and the retry costs rate budget.
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                201,
                json={
                    "token": f"ghs_{calls}",
                    # Inside the refresh margin, so it is never considered usable.
                    "expires_at": (datetime.now(UTC) + timedelta(seconds=30)).isoformat(),
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        cache = InstallationTokenCache(app_id="1", private_key=TEST_PRIVATE_KEY, client=client)

        assert await cache.token_for(INSTALLATION) == "ghs_1"
        assert await cache.token_for(INSTALLATION) == "ghs_2"

        await client.aclose()


# --------------------------------------------------------------------------
# The GraphQL client
# --------------------------------------------------------------------------


def commit_node(
    oid: str,
    *,
    email: str = "priya@acme.com",
    login: str = "priyas",
    name: str = "Priya",
    message: str = "Work",
) -> dict[str, Any]:
    """A GraphQL commit node.

    The login is a parameter, not a constant. An earlier version hard-coded it,
    so two commits with different addresses still carried one GitHub account —
    and identity resolution correctly collapsed them into one person, which the
    test then read as a bug. The fixture was wrong, not the resolver.
    """
    return {
        "oid": oid,
        "message": message,
        "committedDate": "2026-08-01T10:00:00Z",
        "author": {"name": name, "email": email, "user": {"login": login}},
    }


def graphql_page(
    nodes: list[dict[str, Any]], *, has_next: bool, cursor: str | None, cost: int = 1
) -> dict[str, Any]:
    return {
        "data": {
            "rateLimit": {
                "limit": 5000,
                "cost": cost,
                "remaining": 4900,
                "resetAt": "2026-08-14T15:00:00Z",
            },
            "repository": {
                "defaultBranchRef": {
                    "target": {
                        "history": {
                            "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                            "nodes": nodes,
                        }
                    }
                }
            },
        }
    }


def client_returning(
    responses: list[httpx.Response],
) -> tuple[GitHubGraphQLClient, list[httpx.Request]]:
    """A client backed by a scripted transport. Returns it and the request log."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("access_tokens"):
            return httpx.Response(
                201,
                json={
                    "token": "ghs_x",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
            )
        return (
            queue.pop(0)
            if queue
            else httpx.Response(200, json=graphql_page([], has_next=False, cursor=None))
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = InstallationTokenCache(app_id="1", private_key=TEST_PRIVATE_KEY, client=http)
    return GitHubGraphQLClient(tokens=cache, client=http), seen


class TestGraphQLClient:
    async def test_pages_are_requested_at_one_hundred(self) -> None:
        # The default is 30. Roughly a threefold reduction in round trips on
        # every paginated walk, at no extra point cost.
        client, seen = client_returning(
            [httpx.Response(200, json=graphql_page([], has_next=False, cursor=None))]
        )

        await client.fetch_commits(
            installation_id=INSTALLATION, owner="acme", name="api", since="2026-05-01T00:00:00Z"
        )

        graphql = [r for r in seen if r.url.path.endswith("/graphql")]
        import json as jsonlib

        variables = jsonlib.loads(graphql[0].content)["variables"]
        assert variables["pageSize"] == PAGE_SIZE == 100

    async def test_cost_is_recorded_from_the_response(self) -> None:
        client, _ = client_returning(
            [
                httpx.Response(
                    200, json=graphql_page([commit_node("a")], has_next=False, cursor=None, cost=42)
                )
            ]
        )

        await client.fetch_commits(
            installation_id=INSTALLATION, owner="acme", name="api", since="2026-05-01T00:00:00Z"
        )

        assert client.budget_for(INSTALLATION).spent == 42

    async def test_a_200_carrying_errors_is_a_failure(self) -> None:
        """The classic GraphQL client bug.

        GraphQL returns 200 with an `errors` array. Treating the status alone as
        success makes the walk appear to work while importing nothing — and the
        cursor never advances, so it does it forever.
        """
        client, _ = client_returning(
            [
                httpx.Response(
                    200, json={"errors": [{"message": "Could not resolve to a Repository"}]}
                )
            ]
        )

        with pytest.raises(GitHubApiError, match="Could not resolve"):
            await client.fetch_commits(
                installation_id=INSTALLATION,
                owner="acme",
                name="gone",
                since="2026-05-01T00:00:00Z",
            )

    async def test_a_secondary_limit_is_distinct_from_budget_exhaustion(self) -> None:
        # Different responses: points exhaustion is a schedule, a secondary
        # limit means slow down now and is what GitHub escalates against.
        client, _ = client_returning([httpx.Response(403, headers={"retry-after": "45"}, json={})])

        with pytest.raises(SecondaryRateLimitError) as raised:
            await client.fetch_commits(
                installation_id=INSTALLATION, owner="acme", name="api", since="2026-05-01T00:00:00Z"
            )

        assert raised.value.retry_after_seconds == 45

    async def test_an_exhausted_budget_is_refused_before_the_request(self) -> None:
        # Checked before, not after. Asking anyway spends the reserve live
        # traffic is holding: the run finishes slightly sooner and the customer's
        # current activity stops being processed.
        client, seen = client_returning([])
        budget = client.budget_for(INSTALLATION)
        budget.observe(limit=5000, remaining=1000, reset_at=0, cost=200)
        budget.remaining = 1000  # usable = 1000 - 1000 reserve = 0

        with pytest.raises(BudgetExhaustedError):
            await client.fetch_commits(
                installation_id=INSTALLATION, owner="acme", name="api", since="2026-05-01T00:00:00Z"
            )

        assert [r for r in seen if r.url.path.endswith("/graphql")] == []

    async def test_an_empty_repository_is_not_an_error(self) -> None:
        # `defaultBranchRef: null` is what an empty repository returns, and
        # customers have them. A TypeError here would fail the whole backfill.
        client, _ = client_returning(
            [httpx.Response(200, json={"data": {"repository": {"defaultBranchRef": None}}})]
        )

        page = await client.fetch_commits(
            installation_id=INSTALLATION, owner="acme", name="empty", since="2026-05-01T00:00:00Z"
        )

        assert page.commits == []
        assert page.has_next_page is False

    def test_a_graphql_commit_is_reshaped_into_the_webhook_shape(self) -> None:
        """One attribution implementation, not two.

        The same commit arriving by a different route must not acquire a second
        parser — the one used less often is the one that drifts.
        """
        from cairn_api.github.trailers import contributors_of

        node = commit_node("abc", message="Fix (#1)\n\nCo-authored-by: Tom <tom@acme.com>\n")

        credited = contributors_of(to_commit_payload(node))

        assert [c.email for c in credited] == ["priya@acme.com", "tom@acme.com"]


# --------------------------------------------------------------------------
# Run lifecycle
# --------------------------------------------------------------------------


@pytest.fixture
async def tenant_id(platform: AsyncSession) -> uuid.UUID:
    tenant = Tenant(name="Acme", slug=f"bf-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.commit()
    return tenant.id


class TestRunLifecycle:
    async def test_a_second_run_for_the_same_repository_is_refused(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        # Two concurrent onboarding triggers would otherwise walk the same
        # repository twice, spending an installation's rate budget to import the
        # same history in duplicate.
        async with tenant_session(tenant_id) as session:
            first = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            second = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )

        assert first is not None
        assert second is None

    async def test_a_claimed_run_cannot_be_taken_by_another_worker(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        # Both workers would fetch the same pages against one rate budget.
        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None
            run_id = run.id

        async with tenant_session(tenant_id) as session:
            assert await claim(session, run_id, worker="worker-a") is not None

        async with tenant_session(tenant_id) as session:
            assert await claim(session, run_id, worker="worker-b") is None

    async def test_an_expired_lease_is_reclaimable(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        """The reason it is a lease and not a lock.

        A lock held by a process that no longer exists is a run that never
        resumes. A worker killed rather than shut down leaves exactly that.
        """
        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None
            run_id = run.id

        async with tenant_session(tenant_id) as session:
            claimed = await claim(session, run_id, worker="worker-a")
            assert claimed is not None
            # The worker is killed; its lease ages out.
            claimed.leased_until = datetime.now(UTC) - timedelta(seconds=1)

        async with tenant_session(tenant_id) as session:
            assert await claim(session, run_id, worker="worker-b") is not None

    async def test_the_same_worker_may_renew_its_own_lease(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None
            run_id = run.id

        async with tenant_session(tenant_id) as session:
            first = await claim(session, run_id, worker="worker-a")
            assert first is not None
            renewed = await claim(session, run_id, worker="worker-a")
            assert renewed is not None
            assert renewed.leased_until is not None
            assert renewed.leased_until > datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS - 60)

    async def test_a_throttled_run_is_not_offered_until_its_resume_time(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        # Otherwise a scheduler re-offers it immediately and the retry spends
        # the reserve live traffic is holding.
        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None
            run.state = BackfillState.THROTTLED
            run.resume_after = datetime.now(UTC) + timedelta(hours=1)

        async with tenant_session(tenant_id) as session:
            assert await claimable_runs(session, limit=10) == []

        async with tenant_session(tenant_id) as session:
            parked = await session.scalar(select(BackfillRun))
            assert parked is not None
            parked.resume_after = datetime.now(UTC) - timedelta(seconds=1)

        async with tenant_session(tenant_id) as session:
            assert len(await claimable_runs(session, limit=10)) == 1


# --------------------------------------------------------------------------
# Walking history
# --------------------------------------------------------------------------


class TestBackfillWalk:
    async def test_a_walk_imports_history_and_completes(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        client, _ = client_returning(
            [
                httpx.Response(
                    200,
                    json=graphql_page(
                        [
                            commit_node("a"),
                            commit_node("b", email="tom@acme.com", login="tomr", name="Tom"),
                        ],
                        has_next=True,
                        cursor="cursor-1",
                    ),
                ),
                httpx.Response(
                    200,
                    json=graphql_page([commit_node("c")], has_next=False, cursor="cursor-2"),
                ),
            ]
        )

        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None
            progress = await process_batch(session, run, client)

            assert progress.finished is True
            assert run.state is BackfillState.COMPLETED
            assert run.commits_imported == 3
            assert run.pages_fetched == 2

            # The identity graph was populated by the same pipeline live
            # webhooks use — two people, not three commits' worth of fragments.
            people = (await session.scalars(select(Person))).all()
            assert len(people) == 2

    async def test_a_walk_resumes_from_its_cursor(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        """The reason progress is checkpointed.

        A worker killed at page 400 must resume at page 400. Restarting would
        re-spend four hundred pages of rate budget to reach the same place.
        """
        import json as jsonlib

        client, seen = client_returning(
            [
                httpx.Response(
                    200, json=graphql_page([commit_node("d")], has_next=False, cursor="cursor-9")
                )
            ]
        )

        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None
            # Stand in for a previous batch that stopped here.
            run.cursor = "cursor-8"
            run.pages_fetched = 400

            await process_batch(session, run, client)

            assert run.pages_fetched == 401

        graphql = [r for r in seen if r.url.path.endswith("/graphql")]
        assert jsonlib.loads(graphql[0].content)["variables"]["after"] == "cursor-8"

    async def test_a_batch_yields_the_worker_rather_than_running_to_completion(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        """BULK priority only helps if the worker is actually released.

        Ninety days of a busy repository is thousands of pages. Occupying one
        worker slot for all of them would starve the live stream in exactly the
        way BULK priority exists to prevent.
        """
        pages = [
            httpx.Response(
                200, json=graphql_page([commit_node(str(i))], has_next=True, cursor=f"c{i}")
            )
            for i in range(10)
        ]
        client, _ = client_returning(pages)

        async with tenant_session(tenant_id) as session:
            created = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert created is not None
            # Through `claim`, because that is the real path: create, claim,
            # process. Calling process_batch directly would test a sequence no
            # worker performs.
            run = await claim(session, created.id, worker="worker-a")
            assert run is not None

            progress = await process_batch(session, run, client, max_pages=3)

            assert progress.pages == 3
            assert progress.finished is False
            # Still claimable, so the next batch resumes where this one stopped.
            assert run.state is BackfillState.RUNNING
            assert run.is_claimable is True
            assert run.cursor == "c2"
            # And the lease is released, so *any* worker can take the next
            # batch. Holding it would leave the run unclaimable for the rest of
            # the lease period — minutes of a customer's onboarding spent
            # waiting on a timer.
            assert run.leased_until is None

        async with tenant_session(tenant_id) as session:
            assert await claim(session, created.id, worker="a-different-worker") is not None

    async def test_an_exhausted_budget_parks_the_run_rather_than_failing_it(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        # Not a failure. Distinguishing "stalled" from "broken" is what stops
        # support chasing a run that will resume on its own.
        client, _ = client_returning([])
        budget = client.budget_for(installation_id)
        budget.observe(limit=5000, remaining=1000, reset_at=0, cost=500)
        budget.remaining = 1000

        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None

            progress = await process_batch(session, run, client)

            assert progress.finished is False
            assert progress.throttled_for is not None
            assert run.state is BackfillState.THROTTLED
            assert run.error is None  # not a failure

    async def test_a_malformed_repository_name_fails_the_run_immediately(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        # No amount of retrying fixes it, and burning a rate budget to discover
        # that would be the expensive way to find out.
        client, _ = client_returning([])

        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session,
                tenant_id=tenant_id,
                installation_id=installation_id,
                repository="not-a-path",
            )
            assert run is not None

            progress = await process_batch(session, run, client)

            assert progress.finished is True
            assert run.state is BackfillState.FAILED
            assert run.error is not None

    async def test_the_cursor_only_advances_after_a_page_is_processed(
        self, tenant_id: uuid.UUID, installation_id: int
    ) -> None:
        """Ordering that loses data silently if reversed.

        Writing the cursor first loses a page on every crash — and invisibly,
        because an advancing cursor looks exactly like progress.
        """
        client, _ = client_returning(
            [
                httpx.Response(
                    200, json=graphql_page([commit_node("x")], has_next=True, cursor="c1")
                ),
                # The next page fails outright.
                httpx.Response(200, json={"errors": [{"message": "boom"}]}),
            ]
        )

        async with tenant_session(tenant_id) as session:
            run = await create_run(
                session, tenant_id=tenant_id, installation_id=installation_id, repository="acme/api"
            )
            assert run is not None

            await process_batch(session, run, client)

            # The first page's cursor was committed; the failed page's was not.
            assert run.cursor == "c1"
            assert run.commits_imported == 1
            assert run.state is BackfillState.FAILED


class TestBackfillIsolation:
    async def test_a_run_cannot_be_seen_from_another_workspace(
        self, platform: AsyncSession
    ) -> None:
        a = Tenant(name="A", slug=f"bfa-{uuid.uuid4().hex[:8]}")
        b = Tenant(name="B", slug=f"bfb-{uuid.uuid4().hex[:8]}")
        platform.add_all([a, b])
        await platform.commit()

        async with tenant_session(a.id) as session:
            run = await create_run(
                session, tenant_id=a.id, installation_id=INSTALLATION + 1, repository="a/secret"
            )
            assert run is not None
            run_id = run.id

        # Positive control: visible to its own workspace.
        async with tenant_session(a.id) as session:
            assert await session.get(BackfillRun, run_id) is not None

        async with tenant_session(b.id) as session:
            assert await session.get(BackfillRun, run_id) is None
            assert await claimable_runs(session, limit=10) == []
