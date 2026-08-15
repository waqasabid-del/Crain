"""Authentication endpoints.

**The session is an `HttpOnly` cookie, not a bearer token in a JSON body.**

A token the frontend has to store is a token JavaScript can read, which means
any cross-site scripting bug anywhere on the page — including in a dependency —
exfiltrates it. `HttpOnly` puts the credential where script cannot reach it at
all. The cost is that cookies are attached automatically, which is what CSRF
exploits; that is answered by `SameSite=Lax` plus the origin check in
`middleware.py`, and it is a far better trade than making every dependency in
the bundle part of the auth threat model.

`SameSite=Lax` rather than `Strict`: `Strict` withholds the cookie when a user
arrives by clicking a link from anywhere else — including the invitation email
this product depends on — so they land signed out on a page that should have
recognised them.

The API and the app are different hosts under one registrable domain
(`api.cairn.dev`, `app.cairn.dev`). `SameSite` is scoped to the site rather than
the origin, so `Lax` still sends the cookie between them.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from cairn_api.api.dependencies import (
    ClientAddress,
    CurrentUser,
    EmailSenderDep,
    PlatformDb,
    RateLimiterDep,
    SettingsDep,
    enforce_rate_limit,
)
from cairn_api.api.ratelimit import (
    LOGIN_PER_ADDRESS,
    LOGIN_PER_IDENTIFIER,
    SIGNUP_PER_ADDRESS,
)
from cairn_api.api.schemas import (
    LoginRequest,
    SessionResponse,
    SignupRequest,
    UserResponse,
    VerifyEmailRequest,
    WorkspaceMembershipResponse,
    WorkspaceResponse,
)
from cairn_api.auth.service import (
    SESSION_LIFETIME,
    authenticate,
    create_session,
    issue_email_verification,
    revoke_all_sessions_for_user,
    revoke_session,
    sign_up,
    verify_email,
)
from cairn_api.auth.tokens import hash_token
from cairn_api.config import SESSION_COOKIE_NAME, Settings
from cairn_api.db.auth_models import Session
from cairn_api.db.models import Membership, User
from cairn_api.email import send_best_effort, verification_message

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_session_cookie(response: Response, *, token: str, settings: Settings) -> None:
    """Attach the session cookie.

    `max_age` matches the session's own lifetime so the browser discards it at
    the same moment the server stops honouring it. A cookie that outlives its
    session produces a user who appears signed in until the first request fails.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        # Unreadable by script. The single most important flag here.
        httponly=True,
        # HTTPS only, everywhere except local development, where a browser would
        # refuse the cookie over plain HTTP and make sign-in impossible.
        secure=settings.cookies_are_secure,
        samesite="lax",
        domain=settings.session_cookie_domain,
        path="/",
    )


def _clear_session_cookie(response: Response, *, settings: Settings) -> None:
    """Remove the cookie.

    Every attribute must match the cookie that was set — a mismatched `domain`
    or `path` writes a *second*, empty cookie and leaves the original in place,
    so the user stays signed in after clicking sign out.
    """
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.cookies_are_secure,
        samesite="lax",
        domain=settings.session_cookie_domain,
        path="/",
    )


async def _session_payload(db: PlatformDb, user: User) -> SessionResponse:
    """Build the "who am I" document.

    One query with a join rather than one per workspace: a person in a dozen
    workspaces would otherwise cost a dozen round trips on the request every
    page load makes first.
    """
    memberships = (
        await db.scalars(
            select(Membership)
            .options(joinedload(Membership.tenant))
            .where(Membership.user_id == user.id)
            .order_by(Membership.created_at)
        )
    ).all()

    return SessionResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_is_verified,
        ),
        workspaces=[
            WorkspaceMembershipResponse(
                workspace=WorkspaceResponse.model_validate(membership.tenant),
                role=membership.role,
                work_role=membership.work_role,
            )
            for membership in memberships
        ],
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionResponse,
    summary="Create an account and its first workspace",
    responses={
        409: {"description": "The email address already has an account."},
        422: {"description": "The password is too short, or a field is malformed."},
        429: {"description": "Too many signups from this address."},
    },
)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: PlatformDb,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    address: ClientAddress,
    sender: EmailSenderDep,
) -> SessionResponse:
    """Create a user, a workspace and the owner membership joining them.

    All three or none — the transaction is the caller's, and a partial signup
    leaves an account that cannot do anything and cannot be recovered without
    manual intervention.

    Signing in immediately is deliberate: making someone who just chose a
    password type it again is friction with no security benefit, on the one
    screen where abandonment costs the most.
    """
    await enforce_rate_limit(
        request, response, limiter, key=f"signup:{address}", limit=SIGNUP_PER_ADDRESS
    )

    result = await sign_up(
        db,
        email=body.email,
        password=body.password,
        workspace_name=body.workspace_name,
        workspace_slug=body.workspace_slug,
        display_name=body.display_name,
    )
    issued = await create_session(db, user=result.user)
    await db.commit()

    _issue_session_cookie(response, token=issued.token, settings=settings)
    # After the commit, and deliberately not part of it: a relay that is briefly
    # unreachable must not cost somebody their account.
    await send_best_effort(
        sender,
        verification_message(settings, to=result.user.email, token=result.verification.token),
        event="signup",
    )
    await logger.ainfo(
        "signup_completed",
        # UUIDs only. An email address in the log store escapes the erasure
        # path the product promises, because logs have their own retention.
        user_id=str(result.user.id),
        tenant_id=str(result.tenant.id),
    )

    return await _session_payload(db, result.user)


@router.post(
    "/login",
    response_model=SessionResponse,
    summary="Exchange credentials for a session",
    responses={
        401: {"description": "Unknown address or wrong password — deliberately indistinguishable."},
        429: {"description": "Too many attempts."},
    },
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: PlatformDb,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    address: ClientAddress,
) -> SessionResponse:
    """Verify credentials and issue a session."""
    # Both budgets, before any Argon2 work. Checking after the hash would let an
    # attacker impose the CPU cost regardless of the limit, which is half of what
    # the limit is for.
    #
    # The identifier is lower-cased so that varying capitalisation does not buy
    # a fresh bucket per attempt.
    await enforce_rate_limit(
        request, response, limiter, key=f"login-addr:{address}", limit=LOGIN_PER_ADDRESS
    )
    await enforce_rate_limit(
        request,
        response,
        limiter,
        key=f"login-id:{body.email.strip().lower()}",
        limit=LOGIN_PER_IDENTIFIER,
    )

    user = await authenticate(db, email=body.email, password=body.password)
    issued = await create_session(db, user=user)
    await db.commit()

    _issue_session_cookie(response, token=issued.token, settings=settings)
    await logger.ainfo("login_succeeded", user_id=str(user.id))

    return await _session_payload(db, user)


@router.get(
    "/session",
    response_model=SessionResponse,
    summary="Identify the current caller",
    responses={401: {"description": "No valid session."}},
)
async def current_session(caller: CurrentUser, db: PlatformDb) -> SessionResponse:
    """Return the signed-in user and their workspaces.

    The request a frontend makes before rendering anything, which is why it
    returns workspaces in the same round trip rather than requiring a second
    call to decide what to draw.
    """
    return await _session_payload(db, caller.user)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End the current session",
)
async def logout(
    caller: CurrentUser,
    response: Response,
    db: PlatformDb,
    settings: SettingsDep,
) -> None:
    """Revoke this session and clear the cookie.

    Both, in that order. Clearing the cookie alone leaves a token that still
    works if it was captured; revoking alone leaves a browser presenting a dead
    credential on every request.
    """
    await revoke_session(db, token=caller.token)
    await db.commit()

    _clear_session_cookie(response, settings=settings)
    await logger.ainfo("logout", user_id=str(caller.user.id))


@router.post(
    "/logout-everywhere",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End every other session for this user",
)
async def logout_everywhere(caller: CurrentUser, db: PlatformDb) -> None:
    """Revoke every session except the one making the request.

    The account-recovery path. Until this existed, the only way to end a session
    was to present its token — which is precisely what someone reporting a
    compromised account does not have, and what the attacker does.

    The current session survives so that "sign out everywhere else" does not sign
    the user out of the device they are asking from, which reads as the button
    having failed.
    """
    current = await db.scalar(select(Session).where(Session.token_hash == hash_token(caller.token)))
    revoked = await revoke_all_sessions_for_user(
        db,
        user_id=caller.user.id,
        except_session_id=current.id if current else None,
    )
    await db.commit()

    await logger.ainfo("sessions_revoked", user_id=str(caller.user.id), revoked_count=revoked)


@router.post(
    "/verify-email",
    response_model=SessionResponse,
    summary="Prove control of an email address",
    responses={
        409: {"description": "Unknown, expired, already-used or superseded link."},
    },
)
async def verify_email_endpoint(body: VerifyEmailRequest, db: PlatformDb) -> SessionResponse:
    """Redeem a verification link.

    Deliberately unauthenticated: someone clicking a link from their inbox may
    not have a session in that browser, and requiring one would send them to a
    login screen that discards the token they arrived with.

    The token is the credential. It is 256 bits of entropy delivered only to the
    address it proves, which is a stronger claim about that address than a
    session is.
    """
    user = await verify_email(db, token=body.token)
    await db.commit()

    await logger.ainfo("email_verified", user_id=str(user.id))
    return await _session_payload(db, user)


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send a fresh verification link",
)
async def resend_verification(
    caller: CurrentUser,
    db: PlatformDb,
    settings: SettingsDep,
    sender: EmailSenderDep,
) -> dict[str, str]:
    """Issue a new verification token, invalidating any outstanding one.

    Returns the same response whether or not the account is already verified.
    Saying "already verified" would confirm account state to whoever holds the
    session, and there is no useful action either answer enables.
    """
    if not caller.user.email_is_verified:
        issued = await issue_email_verification(db, user=caller.user)
        await db.commit()
        await send_best_effort(
            sender,
            verification_message(settings, to=caller.user.email, token=issued.token),
            event="resend_verification",
        )
        await logger.ainfo("verification_resent", user_id=str(caller.user.id))

    return {"status": "sent"}
