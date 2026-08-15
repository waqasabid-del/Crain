"""Fixtures for HTTP-level tests.

Kept in its own module and imported by `conftest.py` so the database fixtures
stay readable — they are the ones people reach for most often.

**These tests drive the real application over ASGI**, not the route functions
directly. Calling a handler as a Python function skips middleware, dependency
resolution, the exception handlers and the cookie plumbing — which is to say, it
skips almost everything Step 9 added. A test that calls `login()` directly would
pass with the session cookie broken.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from cairn_api.api.app import create_app
from cairn_api.api.ratelimit import InMemoryRateLimiter
from cairn_api.config import Settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

#: The origin tests present. Must appear in the app's CORS allowlist, or the
#: origin check rejects every state-changing request.
TEST_ORIGIN = "http://localhost:3000"


@pytest_asyncio.fixture
async def app() -> AsyncIterator[FastAPI]:
    """A fresh application per test.

    Fresh matters for the rate limiter: it is in-process state, so a shared app
    would carry login counts between tests and make them pass or fail depending
    on execution order — the hardest kind of flakiness to diagnose.

    `environment="test"` skips the startup preflight, which asserts the database
    role lacks BYPASSRLS. Not because the property does not matter, but because
    `test_preflight.py` asserts it directly, against deliberately misconfigured
    roles — a far stronger check than a startup call that only proves the happy
    path.
    """
    instance = create_app(Settings(environment="test", cors_allowed_origins=(TEST_ORIGIN,)))
    async with LifespanManager(instance):
        yield instance


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired to the app in-process.

    No socket, no port. The whole ASGI stack runs — middleware, dependencies,
    exception handlers — with none of the flakiness of binding a port in CI.

    Cookies persist across requests on this client, exactly as a browser's would,
    so a test can sign in and then make authenticated calls without threading a
    token through by hand. That is also what makes the session cookie's own
    behaviour testable: if `HttpOnly` or the path were wrong, the follow-up
    request would fail here.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        # Sent on every request so the CSRF origin check sees a legitimate
        # browser origin. A test that needs to exercise a *rejected* origin
        # overrides it per request.
        headers={"Origin": TEST_ORIGIN},
    ) as http_client:
        yield http_client


@pytest.fixture
def limiter(app: FastAPI) -> InMemoryRateLimiter:
    """The app's rate limiter, for tests that need to exhaust or reset it."""
    instance: InMemoryRateLimiter = app.state.rate_limiter
    return instance
