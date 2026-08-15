"""Cross-cutting request handling.

Four concerns, deliberately separate: correlation, access logging, browser
security headers, and cross-site request forgery.

**Order is load-bearing** and set in `app.py`. Starlette runs middleware in the
order added, outermost first — so correlation must be added first, or the
access log and every error handler beneath it record a request with no ID.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from cairn_api.api.errors import problem_response

logger = structlog.get_logger(__name__)

CallNext = Callable[[Request], Awaitable[Response]]

#: Inbound header carrying a caller-supplied correlation ID.
REQUEST_ID_HEADER = "X-Request-ID"

#: Methods that cannot change state, and so need no CSRF protection.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign every request an ID and bind it to the logging context.

    The ID is echoed in the response and in error bodies, which is what makes a
    user's "it failed at about 2pm" into a single log query.

    A caller-supplied `X-Request-ID` is honoured so a trace survives the hop
    from the frontend, but it is validated as a UUID first. Reflecting an
    arbitrary attacker-controlled string into log fields and response headers is
    how log-injection and header-splitting bugs start.
    """

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        request_id = _incoming_request_id(request) or str(uuid.uuid4())
        request.state.request_id = request_id

        # `clear_contextvars` rather than merely binding: contextvars are copied
        # into the task, and without a clear a value can survive from a previous
        # request handled by the same worker task — which would attribute one
        # tenant's log lines to another.
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        try:
            response = await call_next(request)
        finally:
            # Set even on the error path: the exception handler's problem
            # document quotes this ID, and support needs the header to match.
            structlog.contextvars.unbind_contextvars("request_id")

        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _incoming_request_id(request: Request) -> str | None:
    raw = request.headers.get(REQUEST_ID_HEADER)
    if raw is None:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return None


class AccessLogMiddleware(BaseHTTPMiddleware):
    """One structured line per request.

    Deliberately not uvicorn's access log, which writes a formatted string with
    no correlation ID and no duration — neither queryable nor useful for finding
    the slow endpoint.

    The path is the *route template* (`/v1/workspaces/{workspace_id}/members`),
    never the resolved URL. Logging resolved paths makes every request a unique
    string, so "how slow is this endpoint" becomes unanswerable, and it writes
    identifiers into the log store for no benefit.
    """

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started) * 1000

        await logger.ainfo(
            "http_request",
            method=request.method,
            path=_route_template(request),
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        return response


def _route_template(request: Request) -> str:
    """The matched route pattern, with its mount prefix restored.

    FastAPI mounts included routers rather than flattening them, so the `route`
    a middleware observes carries the path *relative to its mount* — the access
    log recorded `/auth/signup` for a request to `/v1/auth/signup`. Prefixing
    `root_path` puts the version back.

    Falls back to the resolved URL when nothing matched, which is the 404 case.
    That does log a concrete path, but an unmatched request has no template to
    log, and knowing what was requested is the point of recording a 404 at all.
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template is None:
        return request.url.path
    return f"{request.scope.get('root_path', '')}{template}"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Browser hardening headers.

    Modest for a JSON API — most of the header vocabulary defends HTML — but the
    two that matter here are absolute.

    `X-Content-Type-Options: nosniff` stops a browser second-guessing the content
    type. Without it, a JSON response containing attacker-influenced text can be
    sniffed as HTML and executed as same-origin script.

    `Cache-Control: no-store` because every authenticated response here is
    per-user. A shared cache that keeps one user's workspace listing and serves
    it to the next is a data breach produced by a missing header.
    """

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # This API serves JSON, never a document. A restrictive CSP costs
        # nothing and closes the gap if a future endpoint ever returns HTML.
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
        response.headers.setdefault("Cache-Control", "no-store")

        if self._hsts:
            # Omitted locally: a browser that receives HSTS for localhost caches
            # it across every project on that host, and the developer who then
            # cannot load an HTTP site has no idea why.
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return response


class CsrfOriginMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests from unrecognised origins.

    The session lives in a `SameSite=Lax` cookie, which already blocks the
    classic cross-site form post. This is the second layer, and it covers what
    `Lax` does not: `SameSite` is scoped to the *site*, so any subdomain under
    the registrable domain — including one a customer controls, or one lost to a
    dangling DNS record — is same-site and gets the cookie sent for it.

    Checking `Origin` against the same allowlist CORS uses closes that. It is
    also why this is a token-free design: a double-submit cookie would add a
    token endpoint, client-side plumbing and a failure mode, to defend the same
    request an origin check already refuses.

    A request with no `Origin` at all is allowed. Browsers always send it on
    cross-origin state-changing requests, so absence means a non-browser client
    — curl, a server-to-server call — which is not a CSRF vector, because CSRF
    depends on a browser attaching cookies automatically.
    """

    def __init__(self, app: ASGIApp, *, allowed_origins: frozenset[str]) -> None:
        super().__init__(app)
        self._allowed = allowed_origins

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        if request.method in SAFE_METHODS:
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin is not None and origin not in self._allowed:
            await logger.awarning(
                "csrf_origin_rejected",
                origin=origin,
                path=request.url.path,
                method=request.method,
            )
            return problem_response(
                request,
                status_code=status.HTTP_403_FORBIDDEN,
                title="Cross-origin request rejected",
                detail="This origin is not permitted to make state-changing requests.",
                problem_type="cross-origin-rejected",
            )

        return await call_next(request)
