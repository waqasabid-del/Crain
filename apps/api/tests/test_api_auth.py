"""HTTP tests for authentication.

Driven over the real ASGI stack, so middleware, dependency resolution, exception
handlers and cookie plumbing are all exercised. Calling the route functions
directly would skip every one of those, which is to say it would skip almost
everything this layer adds.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from cairn_api.config import SESSION_COOKIE_NAME
from httpx import AsyncClient

# Every password here is a literal by necessity.
# ruff: noqa: S105
PASSWORD = "correct-horse-battery"


#: `.test` is a reserved TLD and `email-validator` refuses it, so HTTP tests
#: cannot reuse the `@acme.test` addresses the service-layer tests use — those
#: never pass through `EmailStr`. `example.com` is reserved for documentation and
#: guaranteed never to route.
EMAIL_DOMAIN = "example.com"


def _unique(prefix: str) -> str:
    """A suffix unique per test.

    HTTP tests commit for real — the request opens its own session, so the
    rolled-back `session` fixture cannot reach it. Unique identifiers are how
    tests stay independent without truncating tables between them.
    """
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def signup(client: AsyncClient, *, email: str | None = None) -> dict[str, Any]:
    """Create an account and leave the client signed in."""
    slug = _unique("ws")
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": email or f"{_unique('user')}@example.com",
            "password": PASSWORD,
            "workspaceName": "Acme",
            "workspaceSlug": slug,
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


class TestSignup:
    async def test_creates_an_account_and_signs_in(self, client: AsyncClient) -> None:
        body = await signup(client)

        assert body["workspaces"][0]["role"] == "owner"
        # Signed in immediately: making someone who just chose a password type
        # it again is friction with no security benefit, on the screen where
        # abandonment costs most.
        assert SESSION_COOKIE_NAME in client.cookies

    async def test_the_session_cookie_is_not_readable_by_script(self, client: AsyncClient) -> None:
        # The reason for a cookie rather than a token in the response body. If
        # HttpOnly were ever dropped, any XSS bug anywhere on the page — including
        # in a dependency — would exfiltrate the session.
        response = await client.post(
            "/v1/auth/signup",
            json={
                "email": f"{_unique('httponly')}@example.com",
                "password": PASSWORD,
                "workspaceName": "Acme",
                "workspaceSlug": _unique("ws"),
            },
        )

        cookie_header = response.headers["set-cookie"].lower()
        assert "httponly" in cookie_header
        assert "samesite=lax" in cookie_header

    async def test_the_password_is_never_echoed(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/signup",
            json={
                "email": f"{_unique('echo')}@example.com",
                "password": PASSWORD,
                "workspaceName": "Acme",
                "workspaceSlug": _unique("ws"),
            },
        )

        assert PASSWORD not in response.text

    async def test_a_short_password_is_a_422_naming_the_field(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/signup",
            json={
                "email": f"{_unique('short')}@example.com",
                "password": "short",
                "workspaceName": "Acme",
                "workspaceSlug": _unique("ws"),
            },
        )

        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")
        assert any(error["field"] == "password" for error in response.json()["errors"])

    async def test_a_duplicate_address_is_a_409(self, client: AsyncClient) -> None:
        email = f"{_unique('dupe')}@example.com"
        await signup(client, email=email)

        response = await client.post(
            "/v1/auth/signup",
            json={
                "email": email,
                "password": PASSWORD,
                "workspaceName": "Acme",
                "workspaceSlug": _unique("ws"),
            },
        )

        assert response.status_code == 409
        assert response.json()["type"].endswith("/email-already-registered")

    async def test_an_unknown_field_is_rejected(self, client: AsyncClient) -> None:
        # `extra="forbid"`. A client sending `displayname` for `displayName`
        # should be told, not silently given an account with no name.
        response = await client.post(
            "/v1/auth/signup",
            json={
                "email": f"{_unique('extra')}@example.com",
                "password": PASSWORD,
                "workspaceName": "Acme",
                "workspaceSlug": _unique("ws"),
                "isAdmin": True,
            },
        )

        assert response.status_code == 422


class TestLogin:
    async def test_correct_credentials_issue_a_session(self, client: AsyncClient) -> None:
        email = f"{_unique('login')}@example.com"
        await signup(client, email=email)
        client.cookies.clear()

        response = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})

        assert response.status_code == 200
        assert SESSION_COOKIE_NAME in client.cookies

    @pytest.mark.parametrize("scenario", ["wrong-password", "unknown-address"])
    async def test_failures_are_indistinguishable(self, client: AsyncClient, scenario: str) -> None:
        # The login form must not become an account-existence oracle. The
        # service layer equalises timing; this asserts the response body and
        # status say nothing either.
        email = f"{_unique('oracle')}@example.com"
        await signup(client, email=email)
        client.cookies.clear()

        target = email if scenario == "wrong-password" else f"{_unique('nobody')}@example.com"
        response = await client.post(
            "/v1/auth/login", json={"email": target, "password": "definitely-wrong-here"}
        )

        assert response.status_code == 401
        assert response.json()["detail"] == "That email and password combination is not correct."

    async def test_email_matching_ignores_case(self, client: AsyncClient) -> None:
        email = f"{_unique('case')}@example.com"
        await signup(client, email=email)
        client.cookies.clear()

        response = await client.post(
            "/v1/auth/login", json={"email": email.upper(), "password": PASSWORD}
        )

        assert response.status_code == 200


class TestSessionEndpoint:
    async def test_returns_the_caller_and_their_workspaces(self, client: AsyncClient) -> None:
        await signup(client)

        response = await client.get("/v1/auth/session")

        assert response.status_code == 200
        assert len(response.json()["workspaces"]) == 1

    async def test_without_a_cookie_it_is_401(self, client: AsyncClient) -> None:
        response = await client.get("/v1/auth/session")

        assert response.status_code == 401
        assert response.json()["type"].endswith("/not-authenticated")

    async def test_a_forged_token_is_401(self, client: AsyncClient) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, "not-a-real-token")

        response = await client.get("/v1/auth/session")

        assert response.status_code == 401


class TestLogout:
    async def test_ends_the_session_server_side(self, client: AsyncClient) -> None:
        session = await signup(client)
        token = client.cookies[SESSION_COOKIE_NAME]

        assert (await client.post("/v1/auth/logout")).status_code == 204

        # Re-presenting the captured token must fail. Clearing the cookie alone
        # would leave a credential that still works if it was ever intercepted.
        client.cookies.set(SESSION_COOKIE_NAME, token)
        assert (await client.get("/v1/auth/session")).status_code == 401
        assert session["user"]["id"]

    async def test_logging_out_everywhere_keeps_the_current_device(
        self, client: AsyncClient
    ) -> None:
        # "Sign out everywhere else" must not sign the user out of the device
        # they are asking from — that reads as the button having failed.
        email = f"{_unique('everywhere')}@example.com"
        await signup(client, email=email)
        current = client.cookies[SESSION_COOKIE_NAME]

        client.cookies.clear()
        await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
        other = client.cookies[SESSION_COOKIE_NAME]

        assert (await client.post("/v1/auth/logout-everywhere")).status_code == 204

        client.cookies.set(SESSION_COOKIE_NAME, other)
        assert (await client.get("/v1/auth/session")).status_code == 200
        client.cookies.set(SESSION_COOKIE_NAME, current)
        assert (await client.get("/v1/auth/session")).status_code == 401
