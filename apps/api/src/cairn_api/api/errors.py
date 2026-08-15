"""The HTTP error contract.

Every failure leaves this service in one shape: RFC 9457 `application/problem+json`.
One shape means the generated TypeScript client has one error type to narrow on,
rather than a per-endpoint guess at what a failure looks like.

**Domain errors are translated here, in one place.** The alternative — each route
catching `InvitationError` and choosing a status code — guarantees drift: the
same failure becomes a 400 on one endpoint and a 409 on another, and a new route
forgets entirely and returns 500. The service layer raises domain errors and
knows nothing about HTTP; this module owns the mapping.

**No internal detail crosses the boundary.** An unhandled exception becomes a
flat 500 with a correlation ID and nothing else. A stack trace in a response
body tells an attacker the framework, the file layout, and often the query that
failed; the same trace belongs in the log, where the correlation ID finds it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from cairn_api.auth.permissions import PermissionDeniedError
from cairn_api.auth.service import (
    EmailAlreadyRegisteredError,
    EmailNotVerifiedError,
    InvalidCredentialsError,
    InvitationError,
    WeakPasswordError,
)
from cairn_api.db.tenancy import MissingTenantContextError

logger = structlog.get_logger(__name__)

#: RFC 9457 media type. Not `application/json`: the distinct type is what lets a
#: client tell "this is a structured problem" from "this is your payload"
#: without inspecting the body.
PROBLEM_MEDIA_TYPE = "application/problem+json"

#: Problem type URIs. Stable identifiers a client may branch on — unlike the
#: human-readable `detail`, which is free to change without breaking anyone.
TYPE_PREFIX = "https://cairn.dev/problems/"


class ProblemDetailError(Exception):
    """An error already expressed in the terms the client will see.

    Raised by route code for failures that have no domain-level meaning —
    "this workspace does not exist", "you are not a member of it". Domain errors
    from the service layer are translated by the handlers below instead, so that
    business rules never have to know about status codes.
    """

    def __init__(
        self,
        *,
        status_code: int,
        title: str,
        detail: str,
        problem_type: str = "about:blank",
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.title = title
        self.detail = detail
        self.problem_type = problem_type
        self.headers = headers or {}
        self.extra = extra


def problem_response(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str,
    problem_type: str = "about:blank",
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """Render a problem document."""
    body: dict[str, Any] = {
        "type": (
            problem_type
            if problem_type.startswith(("http", "about:"))
            else TYPE_PREFIX + problem_type
        ),
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": request.url.path,
    }
    # The correlation ID is the whole point of returning anything at all on a
    # 500: it is what turns "it broke" from a support ticket into a log query.
    request_id = getattr(request.state, "request_id", None)
    if request_id is not None:
        body["requestId"] = request_id
    body.update(extra)

    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the handlers. Called once by the app factory.

    Order does not matter — Starlette dispatches on exception type, most
    specific first — but the grouping below is by intent, not by status code.
    """

    @app.exception_handler(ProblemDetailError)
    async def _handle_problem(request: Request, exc: ProblemDetailError) -> Response:
        return problem_response(
            request,
            status_code=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            problem_type=exc.problem_type,
            headers=exc.headers,
            **exc.extra,
        )

    # -- Authentication ----------------------------------------------------

    @app.exception_handler(InvalidCredentialsError)
    async def _handle_invalid_credentials(
        request: Request,
        exc: InvalidCredentialsError,
    ) -> Response:
        # One message for "no such account" and for "wrong password". The
        # service layer already equalises the *timing* of these two paths;
        # distinguishing them here would hand back the account-existence oracle
        # that work exists to close.
        return problem_response(
            request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            title="Invalid credentials",
            detail="That email and password combination is not correct.",
            problem_type="invalid-credentials",
        )

    @app.exception_handler(PermissionDeniedError)
    async def _handle_permission_denied(
        request: Request,
        exc: PermissionDeniedError,
    ) -> Response:
        # 403, not 404. Hiding the existence of a resource the caller cannot
        # act on is defensible for cross-tenant reads — and those are already
        # 404 by construction, because row-level security means the row is not
        # visible to query at all. Here the caller is a member of the workspace
        # and simply lacks the role, where "not found" would be a lie that costs
        # a support ticket.
        return problem_response(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            title="Insufficient permissions",
            detail=str(exc),
            problem_type="permission-denied",
        )

    # -- Domain rules ------------------------------------------------------

    @app.exception_handler(EmailAlreadyRegisteredError)
    async def _handle_email_taken(
        request: Request,
        exc: EmailAlreadyRegisteredError,
    ) -> Response:
        # 409 rather than 422: the request is well-formed, it conflicts with
        # existing state.
        #
        # This does disclose that an address has an account — unavoidable on a
        # signup form, which must tell the user something actionable. The
        # exposure is bounded by rate limiting; the login form, where it would
        # be an unbounded oracle, discloses nothing.
        return problem_response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            title="Email already registered",
            detail="An account already exists for that email address.",
            problem_type="email-already-registered",
        )

    @app.exception_handler(EmailNotVerifiedError)
    async def _handle_unverified(request: Request, exc: EmailNotVerifiedError) -> Response:
        # 403 rather than 401: the caller is understood and the request is
        # refused on account state, not on missing credentials. A 401 would tell
        # a client to prompt for a password, which would not help.
        return problem_response(
            request,
            status_code=status.HTTP_403_FORBIDDEN,
            title="Email not verified",
            detail=str(exc),
            problem_type="email-not-verified",
        )

    @app.exception_handler(WeakPasswordError)
    async def _handle_weak_password(request: Request, exc: WeakPasswordError) -> Response:
        return problem_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Password too weak",
            detail=str(exc),
            problem_type="weak-password",
        )

    @app.exception_handler(InvitationError)
    async def _handle_invitation(request: Request, exc: InvitationError) -> Response:
        return problem_response(
            request,
            status_code=status.HTTP_409_CONFLICT,
            title="Invitation cannot be used",
            detail=str(exc),
            problem_type="invitation-invalid",
        )

    # -- Programming errors ------------------------------------------------

    @app.exception_handler(MissingTenantContextError)
    async def _handle_missing_tenant(
        request: Request,
        exc: MissingTenantContextError,
    ) -> Response:
        # Never the caller's fault, and never something to explain to them.
        # Reaching here means a route opened a session without resolving a
        # workspace — a bug with data-isolation consequences, so it is logged at
        # error level with the full exception and returned as a flat 500.
        await logger.aerror(
            "missing_tenant_context",
            path=request.url.path,
            request_id=getattr(request.state, "request_id", None),
            exc_info=exc,
        )
        return _internal_error(request)

    # -- Framework ---------------------------------------------------------

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError) -> Response:
        # FastAPI's default returns a bare list under `detail`, which is neither
        # problem+json nor the same shape as anything else here. Reshaped so a
        # client has exactly one error type.
        return problem_response(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Invalid request",
            detail="The request body or parameters did not validate.",
            problem_type="validation-failed",
            errors=[
                {
                    "field": ".".join(str(part) for part in error["loc"][1:]),
                    "message": error["msg"],
                }
                for error in exc.errors()
            ],
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> Response:
        # Covers 404s from unmatched routes and 405s from wrong methods, which
        # Starlette raises before any of our code runs.
        return problem_response(
            request,
            status_code=exc.status_code,
            title=_TITLES.get(exc.status_code, "Request failed"),
            detail=str(exc.detail),
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> Response:
        await logger.aexception(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            request_id=getattr(request.state, "request_id", None),
            exc_info=exc,
        )
        return _internal_error(request)


_TITLES: dict[int, str] = {
    status.HTTP_401_UNAUTHORIZED: "Not authenticated",
    status.HTTP_403_FORBIDDEN: "Insufficient permissions",
    status.HTTP_404_NOT_FOUND: "Not found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "Method not allowed",
    status.HTTP_429_TOO_MANY_REQUESTS: "Too many requests",
}


def _internal_error(request: Request) -> JSONResponse:
    """A 500 that says nothing except how to find the log entry."""
    return problem_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal server error",
        detail=("Something went wrong on our side. Quote the request ID if you contact support."),
        problem_type="internal-error",
    )


#: Type alias for the middleware call chain, used by `app.py`.
CallNext = Callable[[Request], Awaitable[Response]]
