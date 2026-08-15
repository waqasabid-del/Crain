"""Request-scoped dependencies.

This module is where an HTTP request becomes a *person in a workspace*, and it
is the only place that conversion happens. Every authenticated route depends on
`CurrentMembership`, so no route can accidentally skip the check by forgetting
to call something — the parameter is the check.

**Three levels, each strictly narrower than the last.**

1. `CurrentSession` — a valid session. Knows who, not where.
2. `CurrentMembership` — that person, in a named workspace, with a role. This is
   the authorisation boundary.
3. `TenantDb` — a database session bound to that workspace, subject to
   row-level security.

The order is not decorative. A tenant-scoped connection is opened only after
membership is proven, so a caller who is not a member never reaches a session
that could query the workspace at all.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Annotated

from fastapi import Cookie, Depends, Path, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.ratelimit import RateLimit, RateLimiter
from cairn_api.auth.permissions import Permission, require
from cairn_api.auth.service import resolve_session
from cairn_api.config import SESSION_COOKIE_NAME, Settings
from cairn_api.db.models import Membership, TenantRole, User
from cairn_api.db.session import platform_session
from cairn_api.db.tenancy import tenant_session
from cairn_api.email import EmailSender


def settings_dependency(request: Request) -> Settings:
    """The settings this application was built with.

    Read from app state, not from `get_settings()`.

    `get_settings()` is `lru_cache`d and reads the process environment, so a
    handler calling it directly ignores whatever was passed to `create_app()`.
    That made the factory's `settings` parameter decorative: it configured
    startup — CORS, middleware, the queue — and every request handler then
    consulted a different object.

    The gap was invisible because the two agree whenever the environment is the
    source of truth, which is every deployment. It surfaced only when a test
    built an app with a webhook secret and the endpoint reported having none.
    """
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(settings_dependency)]


async def platform_db() -> AsyncIterator[AsyncSession]:
    """A privileged session, for operations that precede tenant context.

    Signup, login and invitation acceptance only. Every other route takes
    `TenantDb`, so `grep platform_db` stays a short list a reviewer can check.
    """
    async with platform_session() as session:
        yield session


PlatformDb = Annotated[AsyncSession, Depends(platform_db)]


def email_sender(request: Request) -> EmailSender:
    """The sender, taken from app state.

    Built once at startup so the backend decision and its log line happen once,
    and so a test can substitute a recording sender on its own app instance.
    """
    sender: EmailSender = request.app.state.email_sender
    return sender


EmailSenderDep = Annotated[EmailSender, Depends(email_sender)]


def rate_limiter(request: Request) -> RateLimiter:
    """The limiter, taken from app state.

    Held on the app rather than module-level so tests get a clean one per app
    instance — a shared module global would leak counts between tests and make
    them order-dependent, which is how a rate-limit test starts failing only in
    CI.
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


RateLimiterDep = Annotated[RateLimiter, Depends(rate_limiter)]


def client_address(request: Request) -> str:
    """The caller's address, counted back from the right by trusted hop count.

    `X-Forwarded-For` grows left to right: each proxy appends the address it
    received the request *from*. So the rightmost entry is written by the last
    proxy and names the second-to-last hop — not the client.

    **Both naive readings are wrong, in opposite and equally damaging ways.**

    Taking the leftmost entry trusts a value the client supplied, so an attacker
    sets one header and gets a fresh rate-limit bucket per request.

    Taking the rightmost — which this function did until an audit caught it —
    reads the address the platform's own front end appended. On Cloud Run that
    is Google's infrastructure, identical for effectively all traffic, so every
    caller in the world shares one bucket. The per-address login limit becomes a
    *global* limit: fifty failed logins anywhere lock out every customer, and
    the whole product accepts five signups an hour. The limiter looks correct,
    the store is shared, the tests pass, and the key is wrong.

    The only correct reading is to count back a known number of hops, which is a
    property of the deployment rather than of the code — hence a setting.
    """
    settings = request.app.state.settings
    hops: int = settings.trusted_proxy_hops

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        chain = [part.strip() for part in forwarded.split(",") if part.strip()]
        if chain:
            # Index from the right past the proxies we know appended. Clamped to
            # the leftmost entry rather than wrapping: a chain shorter than the
            # configured hop count means the request did not come through the
            # expected path, and the client-supplied head is the safest of the
            # bad options — it is at worst spoofable, where a negative index
            # would silently select a proxy.
            index = max(0, len(chain) - 1 - hops)
            return chain[index]

    return request.client.host if request.client else "unknown"


ClientAddress = Annotated[str, Depends(client_address)]


async def enforce_rate_limit(
    request: Request,
    response: Response,
    limiter: RateLimiter,
    *,
    key: str,
    limit: RateLimit,
) -> None:
    """Consume one unit of budget, or raise 429.

    Raises:
        ProblemDetailError: Budget exhausted, carrying `Retry-After`.
    """
    result = await limiter.check(key, limit)
    if result.allowed:
        return

    retry_after = max(1, int(result.retry_after) + 1)
    raise ProblemDetailError(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        title="Too many requests",
        # Deliberately vague about which limit fired. Telling a caller whether
        # they hit the per-address or the per-account budget tells them how to
        # spread their traffic to avoid it.
        detail="Too many attempts. Please wait before trying again.",
        problem_type="rate-limited",
        headers={"Retry-After": str(retry_after)},
    )


# -- Authentication ---------------------------------------------------------


class AuthenticatedUser:
    """A resolved session: who is calling, and with which token."""

    __slots__ = ("token", "user")

    def __init__(self, user: User, token: str) -> None:
        self.user = user
        self.token = token


async def current_user(
    db: PlatformDb,
    settings: SettingsDep,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> AuthenticatedUser:
    """Resolve the session cookie to a user.

    Runs on the platform connection by necessity: a session identifies a person
    before any workspace is known, so there is no tenant to scope to yet. This
    is the one authenticated read that legitimately precedes tenant context.

    Raises:
        ProblemDetailError: No cookie, or a token that is unknown, expired, idle or
            revoked. All four are one response — which of them applied is not
            the caller's business and distinguishing them tells an attacker
            whether a stolen token was ever valid.
    """
    if session_token is None:
        raise _not_authenticated()

    user = await resolve_session(db, token=session_token)
    if user is None:
        raise _not_authenticated()

    # `resolve_session` stamps `last_used_at`, which is what the idle timeout
    # measures. Without this commit the stamp is discarded and every session
    # ages from its creation instead.
    await db.commit()

    _ = settings  # Reserved for per-environment session policy.
    return AuthenticatedUser(user=user, token=session_token)


CurrentUser = Annotated[AuthenticatedUser, Depends(current_user)]


def _not_authenticated() -> ProblemDetailError:
    return ProblemDetailError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        title="Not authenticated",
        detail="Sign in to continue.",
        problem_type="not-authenticated",
    )


# -- Authorisation ----------------------------------------------------------


class WorkspaceContext:
    """Proof that this caller belongs to this workspace, in this role.

    Carries the `Membership` itself rather than a role string, so anything
    downstream that needs to act as this member — issuing an invitation, for
    instance — receives an object whose tenant, user and role cannot disagree.
    """

    __slots__ = ("membership", "user")

    def __init__(self, user: User, membership: Membership) -> None:
        self.user = user
        self.membership = membership

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.membership.tenant_id

    @property
    def role(self) -> TenantRole:
        return self.membership.role


async def current_membership(
    caller: CurrentUser,
    db: PlatformDb,
    workspace_id: Annotated[uuid.UUID, Path()],
) -> WorkspaceContext:
    """Resolve the caller's membership of the workspace in the path.

    **404, not 403, when there is no membership.** A 403 would confirm the
    workspace exists, letting anyone enumerate customers by guessing IDs. From
    outside, a workspace you do not belong to is indistinguishable from one that
    does not exist — which is also true at the database layer, where row-level
    security means the row cannot be read at all.

    Raises:
        ProblemDetailError: 404 if the caller is not a member.
    """
    membership = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == workspace_id,
            Membership.user_id == caller.user.id,
        )
    )
    if membership is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Workspace not found",
            detail="No workspace with that ID is available to you.",
            problem_type="workspace-not-found",
        )

    return WorkspaceContext(user=caller.user, membership=membership)


CurrentMembership = Annotated[WorkspaceContext, Depends(current_membership)]


def requires(permission: Permission) -> Callable[[WorkspaceContext], WorkspaceContext]:
    """Build a dependency that enforces one permission.

    Closes audit finding O4: the permission model was fully tested and called
    from exactly one place. Written as a dependency rather than a call inside
    each handler for two reasons — it appears in the route signature, so a
    reviewer sees the requirement without reading the body, and it cannot be
    forgotten halfway down a function that already started doing work.

    Usage::

        @router.post("/members")
        async def invite(
            context: Annotated[WorkspaceContext, Depends(requires(Permission.MEMBERS_INVITE))],
        ) -> ...:

    `require()` raises `PermissionDeniedError`, which the error handlers render
    as 403. Note it raises rather than returning a boolean: an ignored return
    value is a silent authorisation bypass, an ignored exception is impossible.
    """

    def dependency(context: CurrentMembership) -> WorkspaceContext:
        require(context.role, permission)
        return context

    return dependency


# -- Tenant-scoped data access ----------------------------------------------


async def tenant_db(context: CurrentMembership) -> AsyncIterator[AsyncSession]:
    """A database session bound to the caller's workspace.

    Depends on `CurrentMembership`, so the connection cannot be opened before
    membership is proven — the ordering is enforced by the dependency graph
    rather than by remembering to check first.

    Every query on this session is filtered by row-level security to the bound
    tenant. That is the safety net, not the primary control: application code is
    still expected to be correct.
    """
    async with tenant_session(context.tenant_id) as session:
        yield session


TenantDb = Annotated[AsyncSession, Depends(tenant_db)]
