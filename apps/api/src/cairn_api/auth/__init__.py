"""Authentication — credentials, sessions, invitations."""

from cairn_api.auth.permissions import (
    Permission,
    PermissionDeniedError,
    can_view_person_record,
    has_permission,
    permissions_for,
    require,
)
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
    "Permission",
    "PermissionDeniedError",
    "SignupResult",
    "WeakPasswordError",
    "accept_invitation",
    "authenticate",
    "can_view_person_record",
    "create_session",
    "has_permission",
    "invite_to_workspace",
    "permissions_for",
    "require",
    "resolve_session",
    "revoke_session",
    "sign_up",
]
