"""The permission model.

Roles govern *configuration*, never *how much is visible about a person* — an
Owner sees exactly what a Viewer sees about any individual (md/05 §B.2, §B.3.3;
md/08 §A.2). Do not add a ``members.view_details``-style permission; a test
enforces this.
"""

from __future__ import annotations

import enum

from cairn_api.db.models import TenantRole


class Permission(enum.StrEnum):
    """Things a member may be allowed to do within a workspace. Configuration only."""

    BILLING_MANAGE = "billing.manage"

    WORKSPACE_DELETE = "workspace.delete"
    WORKSPACE_TRANSFER = "workspace.transfer"
    """Irreversible by the person doing it."""

    WORKSPACE_SETTINGS = "workspace.settings"

    MEMBERS_INVITE = "members.invite"
    MEMBERS_REMOVE = "members.remove"
    MEMBERS_CHANGE_ROLE = "members.change_role"

    INTEGRATIONS_CONNECT = "integrations.connect"
    INTEGRATIONS_DISCONNECT = "integrations.disconnect"

    PROJECTS_MANAGE = "projects.manage"

    CONTENT_READ = "content.read"

    OWN_RECORD_CORRECT = "own_record.correct"
    """Never grantable over another person (md/05 §B.2)."""

    SUPPORT_SESSION_DECIDE = "support_session.decide"
    """Approve, reject or revoke CAIRN staff access to this workspace.

    Owner and Admin only. Reading the support history needs no permission — every
    member may see who looked at their workspace (md/15 §5.2).
    """


#: Explicit per-role sets, not a hierarchy — a hierarchy would silently grant
#: Owners any future Admin permission.
_ROLE_PERMISSIONS: dict[TenantRole, frozenset[Permission]] = {
    TenantRole.OWNER: frozenset(
        {
            Permission.BILLING_MANAGE,
            Permission.WORKSPACE_DELETE,
            Permission.WORKSPACE_TRANSFER,
            Permission.WORKSPACE_SETTINGS,
            Permission.MEMBERS_INVITE,
            Permission.MEMBERS_REMOVE,
            Permission.MEMBERS_CHANGE_ROLE,
            Permission.INTEGRATIONS_CONNECT,
            Permission.INTEGRATIONS_DISCONNECT,
            Permission.PROJECTS_MANAGE,
            Permission.CONTENT_READ,
            Permission.OWN_RECORD_CORRECT,
            Permission.SUPPORT_SESSION_DECIDE,
        }
    ),
    TenantRole.ADMIN: frozenset(
        {
            Permission.WORKSPACE_SETTINGS,
            Permission.MEMBERS_INVITE,
            Permission.MEMBERS_REMOVE,
            Permission.MEMBERS_CHANGE_ROLE,
            Permission.INTEGRATIONS_CONNECT,
            Permission.INTEGRATIONS_DISCONNECT,
            Permission.PROJECTS_MANAGE,
            Permission.CONTENT_READ,
            Permission.OWN_RECORD_CORRECT,
            Permission.SUPPORT_SESSION_DECIDE,
        }
    ),
    TenantRole.MEMBER: frozenset(
        {
            Permission.CONTENT_READ,
            Permission.OWN_RECORD_CORRECT,
        }
    ),
    TenantRole.VIEWER: frozenset(
        {
            Permission.CONTENT_READ,
            Permission.OWN_RECORD_CORRECT,
        }
    ),
}


class PermissionDeniedError(PermissionError):
    """Raised when a role lacks a required permission."""

    def __init__(self, role: TenantRole, permission: Permission) -> None:
        self.role = role
        self.permission = permission
        super().__init__(f"Role '{role}' does not have permission '{permission}'")


def permissions_for(role: TenantRole) -> frozenset[Permission]:
    """Return every permission a role holds."""
    return _ROLE_PERMISSIONS[role]


def has_permission(role: TenantRole, permission: Permission) -> bool:
    """Whether a role holds a permission."""
    return permission in _ROLE_PERMISSIONS[role]


def require(role: TenantRole, permission: Permission) -> None:
    """Raise unless the role holds the permission (raises, not bool — an ignored
    return would be a silent bypass)."""
    if not has_permission(role, permission):
        raise PermissionDeniedError(role, permission)


def can_view_person_record(
    *,
    viewer_role: TenantRole,
    viewer_is_subject: bool,
) -> bool:
    """Whether a person's record is visible. Always ``True`` — visibility is symmetric
    for everyone, including leadership. Do not make this consult its arguments; that
    would convert a coordination tool into a monitoring one (md/05 §B.2, §B.3.3)."""
    return True
