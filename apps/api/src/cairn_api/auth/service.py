"""Authentication and workspace-membership services.

Platform operations run on the privileged connection, not a tenant-scoped one
(``db/session.py``): signup creates a user and workspace before either exists,
and session lookup must identify a person before the tenant is known.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.auth.permissions import Permission, require
from cairn_api.auth.tokens import (
    generate_token,
    hash_password_async,
    hash_token,
    needs_rehash,
    verify_password_async,
)
from cairn_api.db.auth_models import (
    EmailVerification,
    Invitation,
    PasswordCredential,
    PasswordReset,
    Session,
)
from cairn_api.db.models import Membership, Tenant, TenantRole, User

#: Long-lived: CAIRN is a daily-habit product; forcing weekly re-login works against that.
SESSION_LIFETIME = timedelta(days=30)

#: Idle expiry well before the absolute lifetime above — two untouched weeks reads
#: as a forgotten laptop or stolen cookie, not a returning user.
SESSION_IDLE_TIMEOUT = timedelta(days=14)

INVITATION_LIFETIME = timedelta(days=7)

MIN_PASSWORD_LENGTH = 12

#: Role seniority, used only to cap invitations at the inviter's own role — never
#: for permission checks (those are explicit per-role sets in auth/permissions.py).
_RANK: dict[TenantRole, int] = {
    TenantRole.VIEWER: 0,
    TenantRole.MEMBER: 1,
    TenantRole.ADMIN: 2,
    TenantRole.OWNER: 3,
}


class AuthError(Exception):
    pass


class InvalidCredentialsError(AuthError):
    """Login failed. Same error for unknown email or wrong password (no enumeration)."""


class EmailAlreadyRegisteredError(AuthError):
    pass


class WeakPasswordError(AuthError):
    pass


class InvitationError(AuthError):
    pass


class EmailNotVerifiedError(AuthError):
    """An action requires proof of address control and the account has none."""


class PasswordResetTokenError(AuthError):
    """Unknown, expired, or already-used reset link. One error for all three
    — as with `InvalidCredentialsError`, distinguishing them would tell
    whoever is holding the link more than the response should."""


@dataclass(frozen=True, slots=True)
class SignupResult:
    user: User
    tenant: Tenant
    membership: Membership

    #: The plaintext exists exactly once, here — only the caller can deliver it.
    verification: IssuedVerification


def _normalize_email(email: str) -> str:
    """Lower-case and strip so "Ali@Acme.com" and "ali@acme.com" are one person."""
    return email.strip().lower()


async def _find_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Filters on ``lower(email)`` to match the expression index."""
    result: User | None = await session.scalar(
        select(User).where(func.lower(User.email) == _normalize_email(email))
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
    """Create a user, a workspace, and the owner membership joining them. All
    three or none — the caller's transaction provides atomicity; this function
    never commits."""
    if len(password) < MIN_PASSWORD_LENGTH:
        msg = f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        raise WeakPasswordError(msg)

    normalized = _normalize_email(email)
    if await _find_user_by_email(session, normalized) is not None:
        raise EmailAlreadyRegisteredError(normalized)

    # The check above is advisory; the unique index is the real guard.
    password_hash = await hash_password_async(password)
    user = User(email=normalized, display_name=display_name)
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise EmailAlreadyRegisteredError(normalized) from exc

    session.add(PasswordCredential(user_id=user.id, password_hash=password_hash))

    tenant = Tenant(name=workspace_name, slug=workspace_slug.strip().lower())
    session.add(tenant)
    await session.flush()

    # Every *other* member must be notified before capture begins (md/05 §B.3.5).
    membership = Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.OWNER)
    session.add(membership)
    await session.flush()

    # Signup does not require verification; it instead gates claiming an invitation.
    verification = await issue_email_verification(session, user=user)

    return SignupResult(user=user, tenant=tenant, membership=membership, verification=verification)


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Verify an email and password, returning the user."""
    user = await _find_user_by_email(session, email)
    if user is None:
        # Hash anyway so response time doesn't leak account existence.
        await hash_password_async(password)
        raise InvalidCredentialsError

    credential = await session.scalar(
        select(PasswordCredential).where(PasswordCredential.user_id == user.id)
    )
    if credential is None:
        # OAuth-only account; hash anyway for the same timing reason.
        await hash_password_async(password)
        raise InvalidCredentialsError

    if not await verify_password_async(password, credential.password_hash):
        raise InvalidCredentialsError

    if needs_rehash(credential.password_hash):
        credential.password_hash = await hash_password_async(password)

    return user


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session, plus the token to return to the client (only its hash is persisted)."""

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
    """Return the user for a session token, or ``None`` — for expired and revoked
    sessions alike, so no response reveals whether a token was ever valid."""
    row = await session.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        return None
    now = datetime.now(UTC)
    if row.expires_at <= now:
        return None

    # Falls back to `created_at` so a session issued and never used still ages out.
    last_active = row.last_used_at or row.created_at
    if now - last_active > SESSION_IDLE_TIMEOUT:
        row.revoked_at = now
        return None

    row.last_used_at = now
    return await session.get(User, row.user_id)


async def revoke_session(session: AsyncSession, *, token: str) -> bool:
    """End a session. Returns whether one was found and revoked."""
    row = await session.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = datetime.now(UTC)
    return True


async def revoke_all_sessions_for_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    except_session_id: uuid.UUID | None = None,
) -> int:
    """Revoke every live session for a user. Returns how many were ended.

    The account-recovery primitive: every other revocation path requires
    presenting the session token, which a compromised-account holder doesn't have.
    ``except_session_id`` keeps the caller's own session alive for "sign out
    everywhere else"; pass it too after a password change.
    """
    statement = (
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    if except_session_id is not None:
        statement = statement.where(Session.id != except_session_id)
    # Bulk UPDATE bypasses the identity map by default; keep loaded objects consistent.
    statement = statement.execution_options(synchronize_session="fetch")
    result = await session.execute(statement)
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


@dataclass(frozen=True, slots=True)
class IssuedInvitation:
    invitation: Invitation
    token: str


async def invite_to_workspace(
    session: AsyncSession,
    *,
    inviter: Membership,
    email: str,
    role: TenantRole = TenantRole.MEMBER,
) -> IssuedInvitation:
    """Create an invitation to the inviter's workspace.

    Takes the inviter's ``Membership``, not a bare user/tenant ID pair, so
    person/workspace/role cannot disagree. Closes two escalation paths: a
    Member self-inviting as Owner (permission check), and an Admin minting an
    Owner invitation for billing/deletion/transfer rights (rank check below;
    md/15 §2.2).
    """
    require(inviter.role, Permission.MEMBERS_INVITE)

    # Nobody may grant a role above their own; ownership moves only via explicit transfer.
    if _RANK[role] > _RANK[inviter.role]:
        msg = (
            f"A {inviter.role} cannot invite someone as {role}. "
            "Ownership is transferred explicitly, not granted by invitation."
        )
        raise InvitationError(msg)

    tenant_id = inviter.tenant_id
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

    now = datetime.now(UTC)

    # Supersede any outstanding invitation first (else it blocks re-invitation
    # forever via the partial unique index). `FOR UPDATE` serialises concurrent
    # invites so the second supersedes the first instead of dying on that index.
    outstanding = await session.scalar(
        select(Invitation)
        .where(
            Invitation.tenant_id == tenant_id,
            Invitation.email == normalized,
            Invitation.accepted_at.is_(None),
            Invitation.superseded_at.is_(None),
        )
        .with_for_update()
    )
    if outstanding is not None:
        outstanding.superseded_at = now
        await session.flush()

    token = generate_token()
    invitation = Invitation(
        tenant_id=tenant_id,
        email=normalized,
        role=role,
        token_hash=hash_token(token),
        expires_at=now + INVITATION_LIFETIME,
        invited_by_user_id=inviter.user_id,
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

    **The invited person joins the existing tenant** — no workspace is created
    (md/15 §3). An account is created if the person doesn't have one;
    otherwise the existing account is used.
    """
    # `FOR UPDATE`: check-then-act below. Without the lock, a double-click
    # redemption inserts two memberships on a row meant to be single-use.
    invitation = await session.scalar(
        select(Invitation).where(Invitation.token_hash == hash_token(token)).with_for_update()
    )
    if invitation is None:
        msg = "Invitation not found"
        raise InvitationError(msg)
    if invitation.accepted_at is not None:
        msg = "Invitation has already been accepted"
        raise InvitationError(msg)
    if invitation.superseded_at is not None:
        # Distinguished from expiry: the remedy differs (find the newer email vs. ask for another).
        msg = "Invitation has been replaced by a more recent one"
        raise InvitationError(msg)
    if invitation.expires_at <= datetime.now(UTC):
        msg = "Invitation has expired"
        raise InvitationError(msg)

    normalized = _normalize_email(email)
    if normalized != invitation.email:
        # An invitation is addressed to a person, not a bearer token — else a
        # forwarded link would let anyone join.
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
        session.add(
            PasswordCredential(user_id=user.id, password_hash=await hash_password_async(password))
        )
        # Redeeming an invitation is proof of address control, so the new account
        # is verified immediately.
        user.email_verified_at = datetime.now(UTC)
    elif not user.email_is_verified:
        # Blocks pre-registration hijack: someone registers victim@company.com
        # unverified and waits for an invitation to squat on. Only blocks
        # existing unverified accounts — first-time invitees are unaffected.
        msg = (
            "An unverified account already exists for this address. "
            "Verify it from the email we sent before accepting an invitation."
        )
        raise EmailNotVerifiedError(msg)

    membership = Membership(
        tenant_id=invitation.tenant_id,
        user_id=user.id,
        role=invitation.role,
    )
    try:
        async with session.begin_nested():
            session.add(membership)
            await session.flush()
    except IntegrityError as exc:
        # Already a member (e.g. added directly since) — desired end state already holds.
        msg = "You are already a member of this workspace"
        raise InvitationError(msg) from exc

    invitation.accepted_at = datetime.now(UTC)
    await session.flush()

    return membership


@dataclass(frozen=True, slots=True)
class InvitationPreview:
    """What the approved design shows before anyone accepts anything: who is
    inviting whom, to where, as what — read-only, no lock, no mutation."""

    email: str
    role: TenantRole
    workspace_name: str
    invited_by_name: str


async def preview_invitation(session: AsyncSession, *, token: str) -> InvitationPreview:
    """Look up an invitation by token without redeeming it.

    Same validity checks as `accept_invitation`, and the same distinct
    messages per cause — this table already treats "expired" and
    "superseded" as different enough to tell apart (unlike a password-reset
    or verification token), so a preview keeps that rather than flattening
    it back to one generic answer.
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
    if invitation.superseded_at is not None:
        msg = "Invitation has been replaced by a more recent one"
        raise InvitationError(msg)
    if invitation.expires_at <= datetime.now(UTC):
        msg = "Invitation has expired"
        raise InvitationError(msg)

    tenant = await session.get(Tenant, invitation.tenant_id)
    if tenant is None:  # pragma: no cover — the foreign key guarantees this
        msg = "Invitation not found"
        raise InvitationError(msg)

    invited_by_name = "A teammate"
    if invitation.invited_by_user_id is not None:
        inviter = await session.get(User, invitation.invited_by_user_id)
        if inviter is not None:
            # Falls back to the address's local part rather than the address
            # itself — the reader is not owed the inviter's full email, only
            # enough to recognise who this is.
            invited_by_name = inviter.display_name or inviter.email.split("@")[0]

    return InvitationPreview(
        email=invitation.email,
        role=invitation.role,
        workspace_name=tenant.name,
        invited_by_name=invited_by_name,
    )


# ---------------------------------------------------------------------------
# Email verification
# ---------------------------------------------------------------------------

#: Longer than an invitation (verification often happens later the same day),
#: but short enough that an archived link isn't a standing grant.
VERIFICATION_LIFETIME = timedelta(hours=48)


@dataclass(frozen=True, slots=True)
class IssuedVerification:
    """A verification token, plus the row recording it (token appears only here)."""

    verification: EmailVerification
    token: str


async def issue_email_verification(session: AsyncSession, *, user: User) -> IssuedVerification:
    """Create a verification token; consumes any outstanding one first so an
    older forwarded/intercepted link stops working."""
    now = datetime.now(UTC)
    await session.execute(
        update(EmailVerification)
        .where(
            EmailVerification.user_id == user.id,
            EmailVerification.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session="fetch")
    )

    token = generate_token()
    verification = EmailVerification(
        user_id=user.id,
        email=user.email,
        token_hash=hash_token(token),
        expires_at=now + VERIFICATION_LIFETIME,
    )
    session.add(verification)
    await session.flush()
    return IssuedVerification(verification=verification, token=token)


async def verify_email(session: AsyncSession, *, token: str) -> User:
    """Redeem a verification token. One error for all failure cases (unknown,
    expired, used, or address changed) so a response never reveals whether a
    token was ever valid."""
    verification = await session.scalar(
        select(EmailVerification)
        .where(EmailVerification.token_hash == hash_token(token))
        .with_for_update()
    )
    now = datetime.now(UTC)

    if (
        verification is None
        or verification.consumed_at is not None
        or verification.expires_at <= now
    ):
        msg = "Verification link is not valid"
        raise InvitationError(msg)

    user = await session.get(User, verification.user_id)
    if user is None or user.email != verification.email:
        # Address changed since issue — else this proves the new address via a
        # link sent to the old one (a takeover primitive).
        msg = "Verification link is not valid"
        raise InvitationError(msg)

    verification.consumed_at = now
    user.email_verified_at = now
    await session.flush()
    return user


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

#: Short — a reset link is meant to be used within minutes of asking for it,
#: and a shorter window bounds how long a link sitting in an inbox stays
#: dangerous if that inbox is compromised.
PASSWORD_RESET_LIFETIME = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class IssuedPasswordReset:
    """A new reset token, the row recording it, and the address to mail it
    to. The address is not a column on `PasswordReset` — it exists only here,
    for the one caller that needs it in the same request it was issued."""

    reset: PasswordReset
    token: str
    email: str


async def issue_password_reset(session: AsyncSession, *, user: User) -> IssuedPasswordReset:
    """Create a reset token for a known user; consumes any outstanding one
    first so an older forwarded/intercepted link stops working."""
    now = datetime.now(UTC)
    await session.execute(
        update(PasswordReset)
        .where(
            PasswordReset.user_id == user.id,
            PasswordReset.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session="fetch")
    )

    token = generate_token()
    reset = PasswordReset(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now + PASSWORD_RESET_LIFETIME,
    )
    session.add(reset)
    await session.flush()
    return IssuedPasswordReset(reset=reset, token=token, email=user.email)


async def request_password_reset(
    session: AsyncSession, *, email: str
) -> IssuedPasswordReset | None:
    """Issue a reset token for the account at this address, or ``None`` if
    there is no such account.

    Returns ``None`` rather than raising: whether an address has an account
    is exactly what the caller must not reveal, so there is no error to
    surface — the endpoint sends the same response either way.
    """
    user = await _find_user_by_email(session, email)
    if user is None:
        # Hash anyway so response time doesn't leak account existence — same
        # reasoning as `authenticate()`'s unknown-email path.
        await hash_password_async(email)
        return None
    return await issue_password_reset(session, user=user)


async def reset_password(session: AsyncSession, *, token: str, new_password: str) -> User:
    """Redeem a reset token, replacing the account's password.

    Revokes every session for the account: a password reset is the moment a
    holder of a stolen session is most likely to still be logged in, and
    leaving them signed in through it would make the reset pointless.
    """
    if len(new_password) < MIN_PASSWORD_LENGTH:
        msg = f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        raise WeakPasswordError(msg)

    # `FOR UPDATE`: check-then-act below. Without the lock, two concurrent
    # redemptions of the same link could both pass the consumed-at check.
    reset = await session.scalar(
        select(PasswordReset).where(PasswordReset.token_hash == hash_token(token)).with_for_update()
    )
    now = datetime.now(UTC)

    if reset is None or reset.consumed_at is not None or reset.expires_at <= now:
        msg = "Password reset link is not valid"
        raise PasswordResetTokenError(msg)

    user = await session.get(User, reset.user_id)
    if user is None:
        msg = "Password reset link is not valid"
        raise PasswordResetTokenError(msg)

    credential = await session.scalar(
        select(PasswordCredential).where(PasswordCredential.user_id == user.id)
    )
    password_hash = await hash_password_async(new_password)
    if credential is None:
        # An OAuth-only account, redeeming proof of address control to add a
        # password — the same trust the invitation flow already extends to a
        # brand-new account.
        session.add(PasswordCredential(user_id=user.id, password_hash=password_hash))
    else:
        credential.password_hash = password_hash

    reset.consumed_at = now
    await revoke_all_sessions_for_user(session, user_id=user.id)
    await session.flush()
    return user
