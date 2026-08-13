"""The permission model.

Conventional SaaS assumes seniority implies visibility: an admin sees more about
people than a member does. **CAIRN inverts that**, and the inversion is the most
important thing in this module.

Roles here govern *configuration* — who may connect an integration, invite a
colleague, change a plan. They do **not** govern *how much is visible about a
person*. An Owner sees exactly what a Viewer sees about any individual, which is
exactly what that individual sees about themselves.

This is not decoration. It is:

- **A product commitment** (md/05 §B.2) — symmetrical visibility is what makes
  CAIRN team coordination rather than workplace monitoring, and it is the
  positioning competitors selling management dashboards structurally cannot copy.
- **Regulatory architecture** (md/05 §B.3.3) — a role that granted deeper insight
  into an individual's behaviour would move the product toward EU AI Act
  "monitoring and evaluating workers", with conformity assessment and bias
  testing attached to *everything*, not just the new feature.
- **An adoption requirement** (md/08 §A.2) — developers are the most likely
  internal blocker, and a tool where the boss sees more than you do is the tool
  they reject.

An engineer will reach for a ``members.view_details`` permission at some point,
because that is how every other product works. There is a test that fails if one
appears.
"""

from __future__ import annotations

import enum

from cairn_api.db.models import TenantRole


class Permission(enum.StrEnum):
    """Things a member may be allowed to do within a workspace.

    Every permission here concerns **configuration or membership**. None
    concerns how much is visible about a person — see the module docstring.
    """

    # ---------------------------------------------------------------- billing
    BILLING_MANAGE = "billing.manage"
    """Change plan, payment method, billing contact."""

    # -------------------------------------------------------------- workspace
    WORKSPACE_DELETE = "workspace.delete"
    WORKSPACE_TRANSFER = "workspace.transfer"
    """Hand ownership to someone else. Irreversible by the person doing it."""

    WORKSPACE_SETTINGS = "workspace.settings"
    """Name, retention period, region, privacy configuration."""

    # ------------------------------------------------------------- membership
    MEMBERS_INVITE = "members.invite"
    MEMBERS_REMOVE = "members.remove"
    MEMBERS_CHANGE_ROLE = "members.change_role"

    # ----------------------------------------------------------- integrations
    INTEGRATIONS_CONNECT = "integrations.connect"
    INTEGRATIONS_DISCONNECT = "integrations.disconnect"

    # --------------------------------------------------------------- projects
    PROJECTS_MANAGE = "projects.manage"

    # ---------------------------------------------------------------- reading
    CONTENT_READ = "content.read"
    """Read briefs, the feed, and documentation.

    Held by every role including Viewer. Note there is deliberately no
    finer-grained read permission: what a person can see is determined by the
    symmetry rule, not by their role.
    """

    OWN_RECORD_CORRECT = "own_record.correct"
    """Correct your own contribution record.

    Held by everyone, and never grantable *over another person*. This is the
    employee-owned-records commitment expressed as a permission (md/05 §B.2).
    """


#: What each role may do.
#:
#: Written as explicit sets rather than derived from a hierarchy. A hierarchy
#: invites "Owner inherits everything Admin has", which is true today and would
#: silently grant Owners any future Admin permission — including one that should
#: have been considered separately.
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
        }
    ),
    TenantRole.ADMIN: frozenset(
        {
            # Deliberately no billing, deletion or ownership transfer: an Admin
            # runs the workspace day to day but cannot end it or move money.
            Permission.WORKSPACE_SETTINGS,
            Permission.MEMBERS_INVITE,
            Permission.MEMBERS_REMOVE,
            Permission.MEMBERS_CHANGE_ROLE,
            Permission.INTEGRATIONS_CONNECT,
            Permission.INTEGRATIONS_DISCONNECT,
            Permission.PROJECTS_MANAGE,
            Permission.CONTENT_READ,
            Permission.OWN_RECORD_CORRECT,
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
    """Raised when a role lacks a required permission.

    A subclass of the built-in ``PermissionError`` so that generic handling
    treats it sensibly, while remaining distinguishable from a filesystem
    permission failure.
    """

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
    """Raise unless the role holds the permission.

    Raising rather than returning a boolean at call sites that must not proceed:
    an ignored return value is a silent authorisation bypass, whereas an ignored
    exception is impossible.
    """
    if not has_permission(role, permission):
        raise PermissionDeniedError(role, permission)


def can_view_person_record(
    *,
    viewer_role: TenantRole,
    viewer_is_subject: bool,
) -> bool:
    """Whether a person's contribution record is visible. Always ``True``.

    This function exists to *be* the answer, and to make the symmetry rule
    something a reader trips over rather than something they must know.

    Both parameters are accepted and both are ignored. That is the entire point:
    within a workspace, everyone sees the same categories of information about
    everyone, including about leadership. There is no manager view, no
    role-gated depth, and no "your own record shows more".

    If a future requirement genuinely needs asymmetric visibility, the change
    belongs in md/05 §B.2 first — not here. Editing this function to consult its
    arguments would quietly convert a coordination tool into a monitoring one,
    and would put the product's AI Act classification at risk (md/05 §B.3.3).
    """
    return True
