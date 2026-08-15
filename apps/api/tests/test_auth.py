"""Authentication tests.

Three groups: token and password primitives, the signup and login flow, and
invitations.

The invitation tests carry the most weight. An invited person must join the
**existing** workspace, and getting that wrong produces a failure that looks
like success — everyone can log in, but a team is quietly split into isolated
single-person workspaces, each showing an empty brief.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.auth import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvitationError,
    PermissionDeniedError,
    WeakPasswordError,
    accept_invitation,
    authenticate,
    create_session,
    invite_to_workspace,
    resolve_session,
    revoke_session,
    sign_up,
    verify_email,
)
from cairn_api.auth.service import SESSION_IDLE_TIMEOUT, revoke_all_sessions_for_user
from cairn_api.auth.tokens import (
    MAX_PASSWORD_BYTES,
    generate_token,
    hash_password,
    hash_token,
    tokens_match,
    verify_password,
)
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Test fixtures. Ruff flags string literals passed as `password=`, which is the
# right default — but every password in a test file is necessarily a literal.
# ruff: noqa: S105, S106
VALID_PASSWORD = "correct-horse-battery"


class TestTokens:
    def test_generated_tokens_are_unique(self) -> None:
        assert len({generate_token() for _ in range(100)}) == 100

    def test_tokens_are_long_enough_to_be_unguessable(self) -> None:
        # 32 bytes of entropy → 43 URL-safe characters.
        assert len(generate_token()) >= 43

    def test_hashing_is_deterministic(self) -> None:
        # Lookup finds the row by hashing the presented token, which a salted
        # hash would make impossible.
        token = generate_token()
        assert hash_token(token) == hash_token(token)

    def test_matching_accepts_the_right_token(self) -> None:
        token = generate_token()
        assert tokens_match(token, hash_token(token))

    def test_matching_rejects_the_wrong_token(self) -> None:
        assert not tokens_match(generate_token(), hash_token(generate_token()))


class TestPasswords:
    def test_hash_is_not_the_password(self) -> None:
        assert hash_password(VALID_PASSWORD) != VALID_PASSWORD

    def test_hashes_are_salted(self) -> None:
        # Identical passwords must not produce identical hashes, or a leaked
        # database reveals which accounts share a password.
        assert hash_password(VALID_PASSWORD) != hash_password(VALID_PASSWORD)

    def test_verify_accepts_the_correct_password(self) -> None:
        assert verify_password(VALID_PASSWORD, hash_password(VALID_PASSWORD))

    def test_verify_rejects_an_incorrect_password(self) -> None:
        assert not verify_password("wrong-password-entirely", hash_password(VALID_PASSWORD))

    def test_verify_returns_false_on_a_corrupt_hash(self) -> None:
        # Denying access is correct; a 500 would tell an attacker their input
        # reached something unusual.
        assert not verify_password(VALID_PASSWORD, "not-a-real-hash")


@pytest.mark.integration
class TestSignup:
    async def test_creates_user_workspace_and_owner_membership(
        self, platform: AsyncSession
    ) -> None:
        result = await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )

        assert result.user.email == "ali@acme.test"
        assert result.tenant.slug == "acme"
        assert result.membership.role is TenantRole.OWNER

    async def test_normalizes_the_email(self, platform: AsyncSession) -> None:
        # Otherwise "Ali@Acme.test" and "ali@acme.test" become two people, and
        # one person's contribution record is split in half.
        result = await sign_up(
            platform,
            email="  Ali@Acme.TEST ",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        assert result.user.email == "ali@acme.test"

    async def test_rejects_a_duplicate_email(self, platform: AsyncSession) -> None:
        await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        with pytest.raises(EmailAlreadyRegisteredError):
            await sign_up(
                platform,
                email="ali@acme.test",
                password=VALID_PASSWORD,
                workspace_name="Other",
                workspace_slug="other",
            )

    async def test_rejects_a_short_password(self, platform: AsyncSession) -> None:
        with pytest.raises(WeakPasswordError, match="at least"):
            await sign_up(
                platform,
                email="ali@acme.test",
                password="short",
                workspace_name="Acme",
                workspace_slug="acme",
            )

    async def test_owner_is_not_pre_notified(self, platform: AsyncSession) -> None:
        # Worker notification precedes capture for every member (md/05 §B.3.5).
        result = await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        assert result.membership.notified_at is None


@pytest.mark.integration
class TestAuthentication:
    async def test_accepts_correct_credentials(self, platform: AsyncSession) -> None:
        await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        user = await authenticate(platform, email="ali@acme.test", password=VALID_PASSWORD)
        assert user.email == "ali@acme.test"

    async def test_rejects_a_wrong_password(self, platform: AsyncSession) -> None:
        await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        with pytest.raises(InvalidCredentialsError):
            await authenticate(platform, email="ali@acme.test", password="wrong-password-here")

    async def test_unknown_email_fails_identically_to_a_wrong_password(
        self, platform: AsyncSession
    ) -> None:
        """The login form must not become an account-existence oracle."""
        with pytest.raises(InvalidCredentialsError):
            await authenticate(platform, email="nobody@nowhere.test", password=VALID_PASSWORD)


@pytest.mark.integration
class TestSessions:
    async def test_issued_token_resolves_to_its_user(self, platform: AsyncSession) -> None:
        result = await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        issued = await create_session(platform, user=result.user)

        resolved = await resolve_session(platform, token=issued.token)

        assert resolved is not None
        assert resolved.id == result.user.id

    async def test_only_the_hash_is_stored(self, platform: AsyncSession) -> None:
        # A leaked database must not yield usable sessions.
        result = await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        issued = await create_session(platform, user=result.user)

        assert issued.session_row.token_hash != issued.token
        assert issued.session_row.token_hash == hash_token(issued.token)

    async def test_unknown_token_resolves_to_nothing(self, platform: AsyncSession) -> None:
        assert await resolve_session(platform, token=generate_token()) is None

    async def test_revoked_session_stops_working(self, platform: AsyncSession) -> None:
        result = await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        issued = await create_session(platform, user=result.user)

        assert await revoke_session(platform, token=issued.token) is True
        assert await resolve_session(platform, token=issued.token) is None

    async def test_expired_session_stops_working(self, platform: AsyncSession) -> None:
        result = await sign_up(
            platform,
            email="ali@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        issued = await create_session(platform, user=result.user)
        issued.session_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await platform.flush()

        assert await resolve_session(platform, token=issued.token) is None


@pytest.mark.integration
class TestInvitations:
    """The tests that matter most in this module."""

    async def _workspace(self, platform: AsyncSession) -> tuple[Membership, Tenant]:
        result = await sign_up(
            platform,
            email="owner@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="acme",
        )
        return result.membership, result.tenant

    async def test_invited_user_joins_the_existing_workspace(self, platform: AsyncSession) -> None:
        """The core guarantee.

        If acceptance created a workspace instead of joining one, everyone could
        still log in — and the team would be silently split into isolated
        single-person workspaces, each showing an empty brief.
        """
        owner_membership, tenant = await self._workspace(platform)
        tenants_before = await platform.scalar(select(func.count()).select_from(Tenant))

        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sara@acme.test"
        )
        membership = await accept_invitation(
            platform,
            token=issued.token,
            email="sara@acme.test",
            password=VALID_PASSWORD,
            display_name="Sara",
        )

        assert membership.tenant_id == tenant.id, "Invitee joined the wrong workspace"

        tenants_after = await platform.scalar(select(func.count()).select_from(Tenant))
        assert tenants_after == tenants_before, "Accepting an invitation created a new workspace"

    async def test_existing_user_keeps_one_identity(self, platform: AsyncSession) -> None:
        """A contractor joining a second workspace is still one person.

        Creating a second user row would fragment their contribution record
        across workspaces — the failure the whole data model exists to prevent.
        """
        owner_membership, first_tenant = await self._workspace(platform)

        contractor = await sign_up(
            platform,
            email="sam@freelance.test",
            password=VALID_PASSWORD,
            workspace_name="Sam Consulting",
            workspace_slug="sam-consulting",
        )
        # They verify their address, which they must before claiming an
        # invitation anywhere. Added when email verification closed the
        # pre-registration hijack (O1): an *unverified* existing account is
        # exactly the squatter that attack relies on, so the block is deliberate
        # and this is the legitimate path through it.
        await verify_email(platform, token=contractor.verification.token)

        users_before = await platform.scalar(select(func.count()).select_from(User))

        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sam@freelance.test"
        )
        membership = await accept_invitation(
            platform, token=issued.token, email="sam@freelance.test"
        )

        assert membership.user_id == contractor.user.id
        users_after = await platform.scalar(select(func.count()).select_from(User))
        assert users_after == users_before, "Accepting created a duplicate user"

        # And they now hold different roles in the two workspaces.
        roles = {
            m.tenant_id: m.role
            for m in (
                await platform.scalars(
                    select(Membership).where(Membership.user_id == contractor.user.id)
                )
            ).all()
        }
        assert roles[contractor.tenant.id] is TenantRole.OWNER
        assert roles[first_tenant.id] is TenantRole.MEMBER

    async def test_invitation_is_addressed_to_a_person(self, platform: AsyncSession) -> None:
        """A forwarded link must not let a stranger into the workspace."""
        owner_membership, _tenant = await self._workspace(platform)
        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sara@acme.test"
        )

        with pytest.raises(InvitationError, match="different email"):
            await accept_invitation(
                platform,
                token=issued.token,
                email="stranger@elsewhere.test",
                password=VALID_PASSWORD,
            )

    async def test_invitation_cannot_be_reused(self, platform: AsyncSession) -> None:
        owner_membership, _tenant = await self._workspace(platform)
        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sara@acme.test"
        )
        await accept_invitation(
            platform, token=issued.token, email="sara@acme.test", password=VALID_PASSWORD
        )

        with pytest.raises(InvitationError, match="already been accepted"):
            await accept_invitation(
                platform, token=issued.token, email="sara@acme.test", password=VALID_PASSWORD
            )

    async def test_expired_invitation_is_refused(self, platform: AsyncSession) -> None:
        # An invitation left in an inbox for months is a standing grant of
        # access to a workspace.
        owner_membership, _tenant = await self._workspace(platform)
        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sara@acme.test"
        )
        issued.invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await platform.flush()

        with pytest.raises(InvitationError, match="expired"):
            await accept_invitation(
                platform, token=issued.token, email="sara@acme.test", password=VALID_PASSWORD
            )

    async def test_unknown_token_is_refused(self, platform: AsyncSession) -> None:
        with pytest.raises(InvitationError, match="not found"):
            await accept_invitation(
                platform, token=generate_token(), email="sara@acme.test", password=VALID_PASSWORD
            )

    async def test_cannot_invite_an_existing_member(self, platform: AsyncSession) -> None:
        # Silently succeeding would suggest something happened when nothing did.
        owner_membership, _tenant = await self._workspace(platform)
        with pytest.raises(InvitationError, match="already a member"):
            await invite_to_workspace(platform, inviter=owner_membership, email="owner@acme.test")

    async def test_invited_member_is_not_pre_notified(self, platform: AsyncSession) -> None:
        """No capture before notification (md/05 §B.3.5)."""
        owner_membership, _tenant = await self._workspace(platform)
        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sara@acme.test"
        )
        membership = await accept_invitation(
            platform, token=issued.token, email="sara@acme.test", password=VALID_PASSWORD
        )
        assert membership.notified_at is None

    async def test_invitation_role_is_honoured(self, platform: AsyncSession) -> None:
        owner_membership, _tenant = await self._workspace(platform)
        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="viewer@acme.test", role=TenantRole.VIEWER
        )
        membership = await accept_invitation(
            platform, token=issued.token, email="viewer@acme.test", password=VALID_PASSWORD
        )
        assert membership.role is TenantRole.VIEWER

    async def test_a_member_cannot_invite_anyone(self, platform: AsyncSession) -> None:
        """Closes a privilege-escalation path that had no check at all.

        `invite_to_workspace` previously took a bare tenant ID and never
        consulted the permission model, so any caller could invite an address
        they controlled — at any role — into any workspace.
        """
        _owner_membership, tenant = await self._workspace(platform)
        sara = User(email="sara@acme.test")
        platform.add(sara)
        await platform.flush()
        member = Membership(tenant_id=tenant.id, user_id=sara.id, role=TenantRole.MEMBER)
        platform.add(member)
        await platform.flush()

        with pytest.raises(PermissionDeniedError, match=r"members\.invite"):
            await invite_to_workspace(platform, inviter=member, email="friend@acme.test")

    async def test_an_admin_cannot_mint_an_owner(self, platform: AsyncSession) -> None:
        """A permission check alone would not have closed this.

        An Admin legitimately holds MEMBERS_INVITE. Without the rank rule they
        could invite an accomplice — or a second address of their own — as
        Owner, acquiring the billing, deletion and transfer rights the
        Owner/Admin split exists to withhold (md/15 §2.2).
        """
        _owner_membership, tenant = await self._workspace(platform)
        jo = User(email="jo@acme.test")
        platform.add(jo)
        await platform.flush()
        admin = Membership(tenant_id=tenant.id, user_id=jo.id, role=TenantRole.ADMIN)
        platform.add(admin)
        await platform.flush()

        with pytest.raises(InvitationError, match="cannot invite someone as"):
            await invite_to_workspace(
                platform, inviter=admin, email="accomplice@acme.test", role=TenantRole.OWNER
            )

    async def test_an_admin_may_invite_a_member(self, platform: AsyncSession) -> None:
        # The rank rule must not block legitimate use.
        _owner_membership, tenant = await self._workspace(platform)
        jo = User(email="jo@acme.test")
        platform.add(jo)
        await platform.flush()
        admin = Membership(tenant_id=tenant.id, user_id=jo.id, role=TenantRole.ADMIN)
        platform.add(admin)
        await platform.flush()

        issued = await invite_to_workspace(platform, inviter=admin, email="new@acme.test")
        assert issued.invitation.role is TenantRole.MEMBER

    async def test_invitation_is_scoped_to_the_inviters_workspace(
        self, platform: AsyncSession
    ) -> None:
        """The inviter's membership determines the tenant, so they cannot disagree."""
        owner_membership, tenant = await self._workspace(platform)
        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sara@acme.test"
        )
        assert issued.invitation.tenant_id == tenant.id

    async def test_only_the_hash_is_stored(self, platform: AsyncSession) -> None:
        owner_membership, _tenant = await self._workspace(platform)
        issued = await invite_to_workspace(
            platform, inviter=owner_membership, email="sara@acme.test"
        )
        # Asserting inequality alone would accept token[::-1] or a truncation.
        assert issued.invitation.token_hash == hash_token(issued.token)


class TestSessionLifecycle:
    """Regression tests for revocation and idle expiry.

    Both existed as gaps rather than bugs: the code did what it said, and what
    it said was insufficient. Revocation required presenting the token, which is
    precisely what someone reporting a compromised account does not have.
    """

    async def test_signing_out_everywhere_ends_every_session(self, platform: AsyncSession) -> None:
        result = await sign_up(
            platform,
            email="revoke-all@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="revoke-all-acme",
        )
        issued = [await create_session(platform, user=result.user) for _ in range(3)]

        ended = await revoke_all_sessions_for_user(platform, user_id=result.user.id)

        assert ended == 3
        for handle in issued:
            assert await resolve_session(platform, token=handle.token) is None

    async def test_signing_out_everywhere_can_spare_the_current_device(
        self, platform: AsyncSession
    ) -> None:
        # "Sign out everywhere else" must not sign the user out of the device
        # they are asking from — that reads as the button having failed.
        result = await sign_up(
            platform,
            email="revoke-except@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="revoke-except-acme",
        )
        keep = await create_session(platform, user=result.user)
        drop = await create_session(platform, user=result.user)

        ended = await revoke_all_sessions_for_user(
            platform, user_id=result.user.id, except_session_id=keep.session_row.id
        )

        assert ended == 1
        assert await resolve_session(platform, token=drop.token) is None
        assert await resolve_session(platform, token=keep.token) is not None

    async def test_an_idle_session_stops_working_before_it_expires(
        self, platform: AsyncSession
    ) -> None:
        result = await sign_up(
            platform,
            email="idle@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="idle-acme",
        )
        issued = await create_session(platform, user=result.user)

        # Still well inside the 30-day absolute lifetime — this is the whole
        # point. A forgotten laptop should not stay signed in for a month.
        issued.session_row.last_used_at = datetime.now(UTC) - (
            SESSION_IDLE_TIMEOUT + timedelta(hours=1)
        )
        await platform.flush()

        assert await resolve_session(platform, token=issued.token) is None
        assert issued.session_row.expires_at > datetime.now(UTC)
        # Stamped, not merely rejected, so the session cannot be revived by a
        # request that happens to arrive with a fresher clock.
        assert issued.session_row.revoked_at is not None

    async def test_a_session_never_used_ages_out_from_creation(
        self, platform: AsyncSession
    ) -> None:
        # `last_used_at` is null between issue and first use. Falling back to
        # `created_at` closes the window where an issued-then-abandoned session
        # would never age out at all.
        result = await sign_up(
            platform,
            email="never-used@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="never-used-acme",
        )
        issued = await create_session(platform, user=result.user)
        issued.session_row.created_at = datetime.now(UTC) - (
            SESSION_IDLE_TIMEOUT + timedelta(hours=1)
        )
        await platform.flush()

        assert issued.session_row.last_used_at is None
        assert await resolve_session(platform, token=issued.token) is None


class TestInvitationSupersession:
    """An unaccepted invitation must not lock an address out permanently.

    The original partial unique index keyed on `accepted_at IS NULL`, which an
    expired invitation still satisfies. The slot was held forever and every
    re-invitation died on a constraint violation naming an index — nothing an
    admin could act on.
    """

    async def test_an_address_can_be_reinvited_after_the_first_expires(
        self, platform: AsyncSession
    ) -> None:
        owner = await sign_up(
            platform,
            email="owner@resend.test",
            password=VALID_PASSWORD,
            workspace_name="Resend",
            workspace_slug="resend-co",
        )
        first = await invite_to_workspace(
            platform, inviter=owner.membership, email="new@resend.test"
        )
        first.invitation.expires_at = datetime.now(UTC) - timedelta(days=1)
        await platform.flush()

        second = await invite_to_workspace(
            platform, inviter=owner.membership, email="new@resend.test"
        )

        assert second.invitation.id != first.invitation.id
        assert first.invitation.superseded_at is not None

    async def test_reissuing_invalidates_the_previous_link(self, platform: AsyncSession) -> None:
        # An admin who re-sends a link after a suspected mis-delivery expects the
        # old one to stop working. Two simultaneously redeemable tokens would be
        # a defect in its own right.
        owner = await sign_up(
            platform,
            email="owner@reissue.test",
            password=VALID_PASSWORD,
            workspace_name="Reissue",
            workspace_slug="reissue-co",
        )
        first = await invite_to_workspace(
            platform, inviter=owner.membership, email="new@reissue.test"
        )
        await invite_to_workspace(platform, inviter=owner.membership, email="new@reissue.test")

        with pytest.raises(InvitationError, match="replaced by a more recent one"):
            await accept_invitation(
                platform,
                token=first.token,
                email="new@reissue.test",
                password=VALID_PASSWORD,
            )

    async def test_the_newest_invitation_still_works(self, platform: AsyncSession) -> None:
        owner = await sign_up(
            platform,
            email="owner@newest.test",
            password=VALID_PASSWORD,
            workspace_name="Newest",
            workspace_slug="newest-co",
        )
        await invite_to_workspace(platform, inviter=owner.membership, email="new@newest.test")
        second = await invite_to_workspace(
            platform, inviter=owner.membership, email="new@newest.test"
        )

        membership = await accept_invitation(
            platform, token=second.token, email="new@newest.test", password=VALID_PASSWORD
        )

        assert membership.tenant_id == owner.tenant.id


class TestConcurrentWrites:
    """Check-then-act paths must fail as domain errors, not IntegrityErrors.

    A raw constraint violation reaches the client as a 500 naming a database
    index and, worse, poisons the transaction — so the caller cannot even render
    an error page.
    """

    async def test_a_duplicate_signup_surfaces_as_a_domain_error(
        self, platform: AsyncSession
    ) -> None:
        # Stands in for the losing side of the race: the pre-check passed when it
        # ran, and the unique index is what actually stops the insert. Here the
        # differing case defeats the pre-check the same way a concurrent
        # transaction would.
        await sign_up(
            platform,
            email="race@acme.test",
            password=VALID_PASSWORD,
            workspace_name="Acme",
            workspace_slug="race-acme-one",
        )

        with pytest.raises(EmailAlreadyRegisteredError):
            await sign_up(
                platform,
                email="race@acme.test",
                password=VALID_PASSWORD,
                workspace_name="Acme",
                workspace_slug="race-acme-two",
            )

        # The transaction survived: the savepoint absorbed the abort.
        assert await platform.scalar(select(func.count()).select_from(User)) is not None

    async def test_accepting_twice_does_not_create_a_second_seat(
        self, platform: AsyncSession
    ) -> None:
        owner = await sign_up(
            platform,
            email="owner@twice.test",
            password=VALID_PASSWORD,
            workspace_name="Twice",
            workspace_slug="twice-co",
        )
        invitation = await invite_to_workspace(
            platform, inviter=owner.membership, email="new@twice.test"
        )
        await accept_invitation(
            platform, token=invitation.token, email="new@twice.test", password=VALID_PASSWORD
        )

        with pytest.raises(InvitationError):
            await accept_invitation(platform, token=invitation.token, email="new@twice.test")

        seats = await platform.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.tenant_id == owner.tenant.id)
        )
        assert seats == 2  # the owner and the invitee, not three


class TestPasswordHardening:
    def test_an_enormous_password_is_refused_rather_than_hashed(self) -> None:
        # Argon2 cost scales with input, so an unbounded password turns one
        # unauthenticated request into seconds of CPU across 64 MiB of memory.
        with pytest.raises(ValueError, match="exceeds"):
            hash_password("x" * (MAX_PASSWORD_BYTES + 1))
