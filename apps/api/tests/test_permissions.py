"""Permission model tests.

Two kinds of test here, and the second kind matters more.

The first checks the permission matrix — that an Admin cannot change billing,
that a Viewer cannot invite people. Ordinary, and would be true of any product.

The second checks the *invariants*: that no role grants deeper visibility into a
person than that person has, and that no permission implying such a thing has
been added. These guard a product commitment, a regulatory position, and an
adoption requirement simultaneously, and they are written to fail loudly if
someone builds the conventional thing by reflex.
"""

from __future__ import annotations

import pytest
from cairn_api.auth.permissions import (
    Permission,
    PermissionDeniedError,
    can_view_person_record,
    has_permission,
    permissions_for,
    require,
)
from cairn_api.db.models import TenantRole


class TestPermissionMatrix:
    @pytest.mark.parametrize(
        ("role", "permission", "expected"),
        [
            # Only an Owner touches money or ends the workspace.
            (TenantRole.OWNER, Permission.BILLING_MANAGE, True),
            (TenantRole.ADMIN, Permission.BILLING_MANAGE, False),
            (TenantRole.MEMBER, Permission.BILLING_MANAGE, False),
            (TenantRole.VIEWER, Permission.BILLING_MANAGE, False),
            (TenantRole.OWNER, Permission.WORKSPACE_DELETE, True),
            (TenantRole.ADMIN, Permission.WORKSPACE_DELETE, False),
            (TenantRole.OWNER, Permission.WORKSPACE_TRANSFER, True),
            (TenantRole.ADMIN, Permission.WORKSPACE_TRANSFER, False),
            # Admins run the workspace day to day.
            (TenantRole.OWNER, Permission.MEMBERS_INVITE, True),
            (TenantRole.ADMIN, Permission.MEMBERS_INVITE, True),
            (TenantRole.MEMBER, Permission.MEMBERS_INVITE, False),
            (TenantRole.VIEWER, Permission.MEMBERS_INVITE, False),
            (TenantRole.ADMIN, Permission.INTEGRATIONS_CONNECT, True),
            (TenantRole.MEMBER, Permission.INTEGRATIONS_CONNECT, False),
            (TenantRole.ADMIN, Permission.WORKSPACE_SETTINGS, True),
            (TenantRole.MEMBER, Permission.WORKSPACE_SETTINGS, False),
            # Everyone reads, and everyone owns their own record.
            (TenantRole.OWNER, Permission.CONTENT_READ, True),
            (TenantRole.ADMIN, Permission.CONTENT_READ, True),
            (TenantRole.MEMBER, Permission.CONTENT_READ, True),
            (TenantRole.VIEWER, Permission.CONTENT_READ, True),
            (TenantRole.VIEWER, Permission.OWN_RECORD_CORRECT, True),
        ],
    )
    def test_matrix(self, role: TenantRole, permission: Permission, expected: bool) -> None:
        assert has_permission(role, permission) is expected

    def test_require_passes_when_permitted(self) -> None:
        require(TenantRole.OWNER, Permission.BILLING_MANAGE)

    def test_require_raises_when_denied(self) -> None:
        # Raising rather than returning False: an ignored return value is a
        # silent authorisation bypass, an ignored exception is impossible.
        with pytest.raises(PermissionDeniedError, match="does not have permission"):
            require(TenantRole.MEMBER, Permission.BILLING_MANAGE)

    def test_denial_names_the_role_and_permission(self) -> None:
        # A denial that does not say what was denied costs an hour to diagnose.
        with pytest.raises(PermissionDeniedError) as exc:
            require(TenantRole.VIEWER, Permission.MEMBERS_INVITE)
        assert exc.value.role is TenantRole.VIEWER
        assert exc.value.permission is Permission.MEMBERS_INVITE


class TestSymmetryInvariants:
    """The tests that encode the product's actual position.

    An engineer will eventually reach for a "view member details" permission,
    because that is how every other product works. These fail when they do.
    """

    def test_every_role_can_read_content(self) -> None:
        for role in TenantRole:
            assert has_permission(role, Permission.CONTENT_READ), (
                f"{role} cannot read content — visibility must not depend on role"
            )

    def test_every_role_can_correct_their_own_record(self) -> None:
        # Employee-owned records (md/05 §B.2), expressed as a permission.
        for role in TenantRole:
            assert has_permission(role, Permission.OWN_RECORD_CORRECT)

    def test_no_permission_grants_visibility_into_another_person(self) -> None:
        """The guard against building the conventional thing by reflex.

        If someone adds `members.view_details`, `people.inspect`, or
        `activity.view_member`, this fails and points at md/05 §B.2 — which is
        the conversation that should happen before such a permission exists.
        """
        forbidden_fragments = (
            "view_details",
            "view_member",
            "inspect",
            "monitor",
            "evaluate",
            "score",
            "rank",
            "performance",
        )

        for permission in Permission:
            for fragment in forbidden_fragments:
                assert fragment not in permission.value, (
                    f"Permission '{permission.value}' suggests visibility into a person. "
                    "CAIRN's roles govern configuration, never how much is visible about "
                    "someone. See md/05 §B.2 and §B.3.3 before adding this."
                )

    def test_admins_hold_no_read_permission_a_member_lacks(self) -> None:
        """Admin power is over settings, not over people.

        The difference between Owner/Admin and Member must be entirely
        configuration. Any read capability one has and the other lacks would be
        asymmetric visibility arriving through the back door.
        """
        read_permissions = {Permission.CONTENT_READ, Permission.OWN_RECORD_CORRECT}

        admin_reads = permissions_for(TenantRole.ADMIN) & read_permissions
        member_reads = permissions_for(TenantRole.MEMBER) & read_permissions
        owner_reads = permissions_for(TenantRole.OWNER) & read_permissions

        assert admin_reads == member_reads == owner_reads

    def test_role_difference_is_configuration_only(self) -> None:
        """Everything an Owner has beyond a Member is a configuration power."""
        extra = permissions_for(TenantRole.OWNER) - permissions_for(TenantRole.MEMBER)

        configuration_prefixes = (
            "billing.",
            "workspace.",
            "members.",
            "integrations.",
            "projects.",
        )
        for permission in extra:
            assert permission.value.startswith(configuration_prefixes), (
                f"'{permission.value}' is not a configuration permission, so it should "
                "not distinguish an Owner from a Member"
            )

    @pytest.mark.parametrize("viewer_role", list(TenantRole))
    @pytest.mark.parametrize("viewer_is_subject", [True, False])
    def test_person_records_are_visible_regardless_of_role_or_subject(
        self, viewer_role: TenantRole, viewer_is_subject: bool
    ) -> None:
        """Symmetrical visibility, asserted across every combination.

        Everyone sees the same categories of information about everyone,
        including about leadership. There is no manager view and no
        role-gated depth.
        """
        assert can_view_person_record(viewer_role=viewer_role, viewer_is_subject=viewer_is_subject)

    def test_viewer_and_member_differ_only_in_future_write_scope(self) -> None:
        # Today they are identical. Recorded so that the day they diverge is a
        # deliberate decision rather than a drift nobody noticed.
        assert permissions_for(TenantRole.VIEWER) == permissions_for(TenantRole.MEMBER)


class TestRoleCoverage:
    def test_every_role_has_an_explicit_permission_set(self) -> None:
        # A role added without an entry would otherwise raise KeyError at the
        # first authorisation check, in production.
        for role in TenantRole:
            assert permissions_for(role) is not None

    def test_there_are_exactly_four_roles(self) -> None:
        # Guards against role explosion (md/15 §2.2). A fifth role should be a
        # deliberate decision, not an accident.
        assert len(TenantRole) == 4
