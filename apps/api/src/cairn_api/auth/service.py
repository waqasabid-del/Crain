"""Authentication and workspace-membership services.

These are platform operations. Signup creates a user and a workspace before
either exists, and session lookup must identify a person *before* the tenant is
known — so both run on the privileged connection rather than a tenant-scoped
one (``db/session.py``).

The most consequential function here is :func:`accept_invitation`. An invited
person must join the **existing** workspace, not get a new one of their own.
Getting that wrong produces a product that appears to work — everyone can log
in — while quietly splitting a team into isolated single-person workspaces, each
seeing an empty brief and no colleagues. It is a documented and easy mistake
(md/15 §3), so it has its own tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.auth.tokens import (
    generate_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from cairn_api.db.auth_models import Invitation, PasswordCredential, Session
from cairn_api.db.models import Membership, Tenant, TenantRole, User

#: Sessions are long-lived because CAIRN is a daily-habit product; forcing a
#: weekly re-login would work against the habit the product depends on.
SESSION_LIFETIME = timedelta(days=30)

#: Invitations expire quickly. An invitation link forwarded, archived, or left
#: in an inbox for months is a standing grant of access to a workspace.
INVITATION_LIFETIME = timedelta(days=7)

MIN_PASSWORD_LENGTH = 12


class AuthError(Exception):
    """Base class for authentication failures."""


class InvalidCredentialsError(AuthError):
    """Login failed.

    Deliberately identical whether the email is unknown or the password is
    wrong. Distinguishing them turns the login form into an oracle for which
    addresses have accounts.
    """


class EmailAlreadyRegisteredError(AuthError):
    """Signup attempted with an address that already has an account."""


class WeakPasswordError(AuthError):
    """Password does not meet the minimum length."""


class InvitationError(AuthError):
    """An invitation could not be accepted."""


@dataclass(frozen=True, slots=True)
class SignupResult:
    user: User
    tenant: Tenant
    membership: Membership


def _normalize_email(email: str) -> str:
    """Lower-case and strip.

    Case-insensitive matching is enforced by a database index too, but doing it
    here means the stored value is canonical rather than merely unique — so
    "Ali@Acme.com" and "ali@acme.com" are one person throughout the system, not
    two records that happen to collide.
    """
    return email.strip().lower()


async def _find_user_by_email(session: AsyncSession, email: str) -> User | None:
    result: User | None = await session.scalar(
        select(User).where(User.email == _normalize_email(email))
    )
    return result


async def sign_up(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    workspace_name: str,
    workspace_slug: str,
    display_name: str | None = None,
) -> SignupResult:
    """Create a user, a workspace, and the owner membership joining them.

    All three or none. A partial signup — a user with no workspace, or a
    workspace with no owner — leaves an account that cannot do anything and
    cannot be recovered without manual intervention. The caller's transaction
    provides the atomicity; this function never commits.

    Raises:
        WeakPasswordError: Password below the minimum length.
        EmailAlreadyRegisteredError: The address already has an account.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        msg = f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        raise WeakPasswordError(msg)

    normalized = _normalize_email(email)
    if await _find_user_by_email(session, normalized) is not None:
        raise EmailAlreadyRegisteredError(normalized)

    user = User(email=normalized, display_name=display_name)
    session.add(user)
    await session.flush()

    session.add(PasswordCredential(user_id=user.id, password_hash=hash_password(password)))

    tenant = Tenant(name=workspace_name, slug=workspace_slug.strip().lower())
    session.add(tenant)
    await session.flush()

    # The person who creates a workspace owns it. Notification is not set here:
    # the owner is told what CAIRN does during onboarding, and every *other*
    # member must be notified before any capture begins (md/05 §B.3.5).
    membership = Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.OWNER)
    session.add(membership)
    await session.flush()

    return SignupResult(user=user, tenant=tenant, membership=membership)


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Verify an email and password, returning the user.

    Raises:
        InvalidCredentialsError: Whatever went wrong. The failure is
            deliberately indistinguishable between "no such account" and "wrong
            password".
    """
    user = await _find_user_by_email(session, email)
    if user is None:
        # Hash anyway, so a request for a non-existent account takes about as
        # long as one for a real account. Returning early here would leak
        # account existence through response time alone.
        hash_password(password)
        raise InvalidCredentialsError

    credential = await session.scalar(
        select(PasswordCredential).where(PasswordCredential.user_id == user.id)
    )
    if credential is None:
        # OAuth-only account. Same opaque failure.
        raise InvalidCredentialsError

    if not verify_password(password, credential.password_hash):
        raise InvalidCredentialsError

    if needs_rehash(credential.password_hash):
        credential.password_hash = hash_password(password)

    return user


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session, plus the token to return to the client.

    The token appears exactly once, here. Only its hash is persisted, so it
    cannot be recovered afterwards — including by us.
    """

    session_row: Session
    token: str


async def create_session(session: AsyncSession, *, user: User) -> IssuedSession:
    """Issue a session for a user."""
    token = generate_token()
    row = Session(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + SESSION_LIFETIME,
    )
    session.add(row)
    await session.flush()
    return IssuedSession(session_row=row, token=token)


async def resolve_session(session: AsyncSession, *, token: str) -> User | None:
    """Return the user for a session token, or ``None``.

    Returns ``None`` for expired and revoked sessions alike. The caller does not
    need to distinguish them, and a message that did would tell an attacker
    whether a token was ever valid.
    """
    row = await session.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= datetime.now(UTC):
        return None

    row.last_used_at = datetime.now(UTC)
    return await session.get(User, row.user_id)


async def revoke_session(session: AsyncSession, *, token: str) -> bool:
    """End a session. Returns whether one was found and revoked."""
    row = await session.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    return True


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation: Invitation
    token: str


async def invite_to_workspace(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    email: str,
    role: TenantRole = TenantRole.MEMBER,
    invited_by: uuid.UUID | None = None,
) -> IssuedInvitation:
    """Create an invitation to an existing workspace.

    Raises:
        InvitationError: If the address is already a member. Re-inviting an
            existing member is almost always a mistake, and silently succeeding
            would suggest something happened when nothing did.
    """
    normalized = _normalize_email(email)

    existing_user = await _find_user_by_email(session, normalized)
    if existing_user is not None:
        already = await session.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == existing_user.id,
            )
        )
        if already is not None:
            msg = f"{normalized} is already a member of this workspace"
            raise InvitationError(msg)

    token = generate_token()
    invitation = Invitation(
        tenant_id=tenant_id,
        email=normalized,
        role=role,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + INVITATION_LIFETIME,
        invited_by_user_id=invited_by,
    )
    session.add(invitation)
    await session.flush()
    return IssuedInvitation(invitation=invitation, token=token)


async def accept_invitation(
    session: AsyncSession,
    *,
    token: str,
    email: str,
    password: str | None = None,
    display_name: str | None = None,
) -> Membership:
    """Join the workspace an invitation belongs to.

    **The invited person joins the existing tenant.** No workspace is created.
    That is the entire point of this function, and the mistake it exists to
    prevent: a signup path that creates a workspace for every new account turns
    one team into several isolated single-person workspaces, each showing an
    empty brief. Everyone can log in, so it looks like it works.

    An account is created if the person does not have one; otherwise the
    existing account is used, so someone already in another workspace keeps one
    identity rather than acquiring a second (md/15 §3).

    Raises:
        InvitationError: Unknown, expired, already-accepted, or addressed to a
            different person.
        WeakPasswordError: A new account was required and the password is too
            short.
    """
    invitation = await session.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(token))
    )
    if invitation is None:
        msg = "Invitation not found"
        raise InvitationError(msg)
    if invitation.accepted_at is not None:
        msg = "Invitation has already been accepted"
        raise InvitationError(msg)
    if invitation.expires_at <= datetime.now(UTC):
        msg = "Invitation has expired"
        raise InvitationError(msg)

    normalized = _normalize_email(email)
    if normalized != invitation.email:
        # An invitation is addressed to a person, not a bearer token. Without
        # this check, a forwarded link would let anyone join the workspace.
        msg = "Invitation was issued to a different email address"
        raise InvitationError(msg)

    user = await _find_user_by_email(session, normalized)
    if user is None:
        if password is None or len(password) < MIN_PASSWORD_LENGTH:
            msg = f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
            raise WeakPasswordError(msg)
        user = User(email=normalized, display_name=display_name)
        session.add(user)
        await session.flush()
        session.add(PasswordCredential(user_id=user.id, password_hash=hash_password(password)))

    # Joining the tenant the invitation names — not a new one.
    membership = Membership(
        tenant_id=invitation.tenant_id,
        user_id=user.id,
        role=invitation.role,
    )
    session.add(membership)

    invitation.accepted_at = datetime.now(UTC)
    await session.flush()

    return membership
