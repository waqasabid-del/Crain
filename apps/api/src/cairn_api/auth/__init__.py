"""Authentication — credentials, sessions, invitations."""

from cairn_api.auth.service import (
    AuthError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvitationError,
    SignupResult,
    WeakPasswordError,
    accept_invitation,
    authenticate,
    create_session,
    invite_to_workspace,
    resolve_session,
    revoke_session,
    sign_up,
)

__all__ = [
    "AuthError",
    "EmailAlreadyRegisteredError",
    "InvalidCredentialsError",
    "InvitationError",
    "SignupResult",
    "WeakPasswordError",
    "accept_invitation",
    "authenticate",
    "create_session",
    "invite_to_workspace",
    "resolve_session",
    "revoke_session",
    "sign_up",
]
