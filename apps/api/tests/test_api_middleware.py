"""Cross-cutting request handling, and the rate limiter beneath it.

These are the controls most likely to appear to work without working. A security
header nobody asserts is a header someone removes while refactoring; a CSRF
check with no test is a check that can be disabled by a typo in an allowlist.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

import pytest
from cairn_api.api.middleware import REQUEST_ID_HEADER
from cairn_api.api.ratelimit import InMemoryRateLimiter, RateLimit
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

TEST_ORIGIN = "http://localhost:3000"


class TestRequestCorrelation:
    async def test_every_response_carries_a_request_id(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")

        # Must parse as a UUID: this value is echoed into log fields and headers,
        # so an arbitrary string would be a log-injection vector.
        uuid.UUID(response.headers[REQUEST_ID_HEADER])

    async def test_a_caller_supplied_id_is_honoured(self, client: AsyncClient) -> None:
        # So a trace survives the hop from the frontend rather than the two
        # halves of one request having separate IDs.
        supplied = str(uuid.uuid4())

        response = await client.get("/healthz", headers={REQUEST_ID_HEADER: supplied})

        assert response.headers[REQUEST_ID_HEADER] == supplied

    async def test_a_malformed_id_is_replaced_rather_than_reflected(
        self, client: AsyncClient
    ) -> None:
        # Reflecting attacker-controlled text into a response header is how
        # header-splitting starts, and into a log field is how log injection
        # starts. Neither is worth the convenience of honouring any string.
        response = await client.get(
            "/healthz", headers={REQUEST_ID_HEADER: "not-a-uuid\r\nX-Injected: yes"}
        )

        assert "X-Injected" not in response.headers
        uuid.UUID(response.headers[REQUEST_ID_HEADER])

    async def test_errors_quote_the_same_id_as_the_header(self, client: AsyncClient) -> None:
        # The whole point of returning anything on a failure: it turns "it broke
        # this afternoon" into a single log query. A body and header that
        # disagree would send support looking for the wrong request.
        response = await client.get("/v1/auth/session")

        assert response.status_code == 401
        assert response.json()["requestId"] == response.headers[REQUEST_ID_HEADER]


class TestSecurityHeaders:
    async def test_responses_refuse_content_sniffing_and_caching(self, client: AsyncClient) -> None:
        response = await client.get("/healthz")

        # nosniff: without it, a JSON response containing attacker-influenced
        # text can be sniffed as HTML and executed as same-origin script.
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        # no-store: every authenticated response here is per-user, and a shared
        # cache serving one user's data to the next is a breach caused by a
        # missing header.
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"

    async def test_hsts_is_absent_locally(self, client: AsyncClient) -> None:
        # A browser that receives HSTS for localhost caches it across every
        # project on that host, and the developer who then cannot load an HTTP
        # site has no idea why.
        response = await client.get("/healthz")

        assert "Strict-Transport-Security" not in response.headers

    async def test_error_responses_are_hardened_too(self, client: AsyncClient) -> None:
        # Middleware ordering makes this true; a reordering that put the
        # security headers outside the exception handlers would silently
        # un-harden every failure response.
        response = await client.get("/v1/auth/session")

        assert response.status_code == 401
        assert response.headers["X-Content-Type-Options"] == "nosniff"


class TestCsrfOriginCheck:
    async def test_a_foreign_origin_cannot_change_state(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/login",
            json={"email": "a@example.com", "password": "irrelevant-here"},
            headers={"Origin": "https://evil.example"},
        )

        assert response.status_code == 403
        assert response.json()["type"].endswith("/cross-origin-rejected")

    async def test_a_foreign_origin_may_still_read(self, client: AsyncClient) -> None:
        # Safe methods cannot change state, so blocking them would break
        # legitimate cross-origin reads for no security benefit. CORS, not this,
        # is what governs whether the browser hands over the response.
        response = await client.get("/healthz", headers={"Origin": "https://evil.example"})

        assert response.status_code == 200

    async def test_a_request_with_no_origin_is_allowed(self, app: FastAPI) -> None:
        # Browsers always send Origin on cross-origin state-changing requests, so
        # absence means a non-browser client — curl, a server-to-server call —
        # which is not a CSRF vector, because CSRF depends on a browser
        # attaching cookies automatically.
        #
        # A separate client because the shared fixture sets Origin on every
        # request; blanking the header instead would send `Origin: ""`, which is
        # a *present* header and tests something different.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as headless:
            response = await headless.post(
                "/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong-password-here"},
            )

        assert response.status_code == 401  # rejected on credentials, not origin

    async def test_an_opaque_origin_cannot_change_state(self, client: AsyncClient) -> None:
        # A sandboxed iframe or a privacy-restricted context sends
        # `Origin: null`. It is a real origin header naming no origin, so it
        # must not be mistaken for the absent-header case above.
        response = await client.post(
            "/v1/auth/login",
            json={"email": "a@example.com", "password": "irrelevant-here"},
            headers={"Origin": "null"},
        )

        assert response.status_code == 403


class TestReadiness:
    async def test_a_database_failure_reports_unavailable(self, client: AsyncClient) -> None:
        # Readiness takes the instance out of rotation; liveness would restart
        # it. Conflating them turns a brief database blip into a full outage
        # with a thundering herd of reconnects behind it.
        with patch(
            "cairn_api.api.routers.health.get_engine",
            side_effect=OSError("connection refused"),
        ):
            response = await client.get("/readyz")

        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"
        # The error is logged, not returned: this endpoint is unauthenticated and
        # reachable from wherever the load balancer is, so a connection error in
        # the body would publish the database host and driver.
        assert "connection refused" not in response.text

    async def test_liveness_never_touches_the_database(self, client: AsyncClient) -> None:
        with patch(
            "cairn_api.api.routers.health.get_engine",
            side_effect=AssertionError("liveness must not open a connection"),
        ):
            response = await client.get("/healthz")

        assert response.status_code == 200


class TestInMemoryRateLimiter:
    async def test_allows_up_to_the_limit_then_refuses(self) -> None:
        limiter = InMemoryRateLimiter()
        limit = RateLimit(limit=3, window_seconds=60)

        results = [await limiter.check("k", limit) for _ in range(4)]

        assert [r.allowed for r in results] == [True, True, True, False]

    async def test_keys_are_independent(self) -> None:
        # Otherwise one noisy address would lock out everyone.
        limiter = InMemoryRateLimiter()
        limit = RateLimit(limit=1, window_seconds=60)

        await limiter.check("a", limit)

        assert (await limiter.check("b", limit)).allowed is True

    async def test_the_window_slides(self) -> None:
        limiter = InMemoryRateLimiter()
        limit = RateLimit(limit=2, window_seconds=0.05)

        await limiter.check("k", limit)
        await limiter.check("k", limit)
        assert (await limiter.check("k", limit)).allowed is False

        await asyncio.sleep(0.06)

        assert (await limiter.check("k", limit)).allowed is True

    async def test_refusal_reports_when_to_retry(self) -> None:
        # Without this a well-behaved client has to guess, and guessing means
        # retrying immediately.
        limiter = InMemoryRateLimiter()
        limit = RateLimit(limit=1, window_seconds=60)

        await limiter.check("k", limit)
        result = await limiter.check("k", limit)

        assert 0 < result.retry_after <= 60

    async def test_concurrent_checks_cannot_exceed_the_limit(self) -> None:
        # The read-modify-write spans an await, so without the lock two
        # concurrent requests could both observe a below-threshold count and
        # both proceed — which is precisely the burst a limiter exists to stop.
        limiter = InMemoryRateLimiter()
        limit = RateLimit(limit=5, window_seconds=60)

        results = await asyncio.gather(*(limiter.check("k", limit) for _ in range(20)))

        assert sum(r.allowed for r in results) == 5

    async def test_tracked_keys_are_bounded(self) -> None:
        # Without a cap, an attacker cycling through addresses turns the defence
        # into an unbounded allocation — a denial of service delivered through
        # the thing meant to prevent one.
        limiter = InMemoryRateLimiter()
        limit = RateLimit(limit=1, window_seconds=60)

        with patch.object(InMemoryRateLimiter, "MAX_TRACKED_KEYS", 10):
            for index in range(50):
                await limiter.check(f"key-{index}", limit)

            # Reaching into private state is right here: the cap is an
            # internal invariant with no public accessor, and adding one
            # would widen the API for a test's benefit.
            assert len(limiter._hits) <= 11

    @pytest.mark.parametrize(("limit", "window"), [(0, 60), (-1, 60), (1, 0), (1, -1)])
    def test_a_nonsensical_budget_is_refused_at_construction(
        self, limit: int, window: float
    ) -> None:
        # A limit of zero would refuse every request; a window of zero would
        # allow every request. Both are configuration mistakes that should fail
        # at import rather than in production.
        with pytest.raises(ValueError, match="must be"):
            RateLimit(limit=limit, window_seconds=window)
