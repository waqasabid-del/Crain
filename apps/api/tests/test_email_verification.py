"""Email verification, and the hijack it closes.

Audit finding O1, open since round one and marked "before any real user data".

**The attack, in order.** Anyone can register `victim@company.com` — signup
requires no proof of address control, and should not, because blocking a new
workspace owner behind an email round trip is friction on the screen where
abandonment costs most. The squatter then waits. When a colleague later invites
that address to a workspace, the squatter's account accepts the invitation, and
the real person is locked out of mail sent to their own inbox.

The address check on acceptance always passed, because the address does match.
What it never established was that the *account holder* controls it.

`TestPreRegistrationHijack` reproduces the attack against the code as it now
stands, and asserts it is refused at the step that matters.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.auth.service import (
    EmailNotVerifiedError,
    InvitationError,
    SignupResult,
    accept_invitation,
    invite_to_workspace,
    issue_email_verification,
    sign_up,
    verify_email,
)
from cairn_api.db.auth_models import EmailVerification
from cairn_api.db.models import User
from sqlalchemy.ext.asyncio import AsyncSession

# ruff: noqa: S105, S106
PASSWORD = "correct-horse-battery"


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def make_owner(platform: AsyncSession, *, email: str | None = None) -> SignupResult:
    result = await sign_up(
        platform,
        email=email or f"{unique('owner')}@example.com",
        password=PASSWORD,
        workspace_name="Acme",
        workspace_slug=unique("ws"),
    )
    await platform.commit()
    return result


class TestPreRegistrationHijack:
    """The attack finding O1 describes."""

    async def test_a_squatter_cannot_claim_an_invitation(self, platform: AsyncSession) -> None:
        victim_email = f"{unique('victim')}@company.com"

        # 1. The attacker registers the victim's address. Nothing stops this,
        #    and nothing should — an account owning only its own empty
        #    workspace has gained nothing.
        squatter = await sign_up(
            platform,
            email=victim_email,
            password=PASSWORD,
            workspace_name="Squatter",
            workspace_slug=unique("sq"),
        )
        await platform.commit()
        assert squatter.user.email_is_verified is False

        # 2. Months later, a colleague invites that address to a real workspace.
        owner = await make_owner(platform)
        invitation = await invite_to_workspace(
            platform, inviter=owner.membership, email=victim_email
        )
        await platform.commit()

        # 3. The attacker redeems it. Before this fix they joined, and the real
        #    person was locked out of an invitation sent to their own inbox.
        with pytest.raises(EmailNotVerifiedError, match="unverified account"):
            await accept_invitation(platform, token=invitation.token, email=victim_email)

    async def test_the_real_person_can_still_join_after_verifying(
        self, platform: AsyncSession
    ) -> None:
        """The positive control, and the more important half.

        A block that also stopped the legitimate owner of the address would be a
        worse defect than the hole it closed — invitation acceptance is the
        product's most important conversion point.
        """
        email = f"{unique('real')}@company.com"
        account = await sign_up(
            platform,
            email=email,
            password=PASSWORD,
            workspace_name="Personal",
            workspace_slug=unique("pers"),
        )
        await platform.commit()

        # They read the email we sent at signup and click the link.
        await verify_email(platform, token=account.verification.token)
        await platform.commit()

        owner = await make_owner(platform)
        invitation = await invite_to_workspace(platform, inviter=owner.membership, email=email)
        await platform.commit()

        membership = await accept_invitation(platform, token=invitation.token, email=email)

        assert membership.tenant_id == owner.tenant.id

    async def test_a_first_time_invitee_is_unaffected(self, platform: AsyncSession) -> None:
        """Someone with no account joins without an extra round trip.

        Redeeming an invitation *is* proof of address control — the token was
        delivered by email and nowhere else — so the new account is verified by
        the act of arriving rather than sent a second email to prove what it has
        already proven.
        """
        owner = await make_owner(platform)
        email = f"{unique('newcomer')}@company.com"
        invitation = await invite_to_workspace(platform, inviter=owner.membership, email=email)
        await platform.commit()

        membership = await accept_invitation(
            platform, token=invitation.token, email=email, password=PASSWORD
        )
        await platform.commit()

        joined = await platform.get(User, membership.user_id)
        assert joined is not None
        assert joined.email_is_verified is True


class TestVerificationTokens:
    async def test_signup_issues_a_token(self, platform: AsyncSession) -> None:
        # Issued inside `sign_up` rather than by the caller, so no signup path
        # can forget it and leave an account that can never become verified.
        result = await make_owner(platform)

        assert result.verification.token
        assert result.verification.verification.email == result.user.email

    async def test_only_the_hash_is_stored(self, platform: AsyncSession) -> None:
        # A leaked database must not yield usable verification links.
        result = await make_owner(platform)

        row = await platform.get(EmailVerification, result.verification.verification.id)
        assert row is not None
        assert result.verification.token not in row.token_hash

    async def test_verifying_marks_the_account_and_consumes_the_token(
        self, platform: AsyncSession
    ) -> None:
        result = await make_owner(platform)

        user = await verify_email(platform, token=result.verification.token)
        await platform.commit()

        assert user.email_is_verified is True
        row = await platform.get(EmailVerification, result.verification.verification.id)
        assert row is not None
        assert row.consumed_at is not None

    async def test_a_token_is_single_use(self, platform: AsyncSession) -> None:
        # A verification link left in an inbox is not a standing credential.
        result = await make_owner(platform)
        await verify_email(platform, token=result.verification.token)
        await platform.commit()

        with pytest.raises(InvitationError, match="not valid"):
            await verify_email(platform, token=result.verification.token)

    async def test_an_expired_token_is_refused(self, platform: AsyncSession) -> None:
        result = await make_owner(platform)
        result.verification.verification.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await platform.commit()

        with pytest.raises(InvitationError, match="not valid"):
            await verify_email(platform, token=result.verification.token)

    async def test_an_unknown_token_is_refused(self, platform: AsyncSession) -> None:
        with pytest.raises(InvitationError, match="not valid"):
            await verify_email(platform, token="not-a-real-token")

    async def test_reissuing_invalidates_the_previous_link(self, platform: AsyncSession) -> None:
        # Two live links means one the person did not just request still works,
        # so an intercepted older email stays usable after they asked for a
        # fresh one — the opposite of what asking again should do.
        result = await make_owner(platform)
        first = result.verification.token

        await issue_email_verification(platform, user=result.user)
        await platform.commit()

        with pytest.raises(InvitationError, match="not valid"):
            await verify_email(platform, token=first)

    async def test_a_token_does_not_verify_an_address_changed_since_issue(
        self, platform: AsyncSession
    ) -> None:
        """The takeover primitive this prevents.

        Verifying on the strength of a link sent to a *previous* address would
        let someone change their address to one they do not control and then
        prove it with mail they received earlier.
        """
        result = await make_owner(platform)
        result.user.email = f"{unique('changed')}@elsewhere.example"
        await platform.commit()

        with pytest.raises(InvitationError, match="not valid"):
            await verify_email(platform, token=result.verification.token)

    async def test_the_failure_message_is_the_same_for_every_cause(
        self, platform: AsyncSession
    ) -> None:
        # Which of unknown, expired, used or superseded applied is not the
        # caller's business, and distinguishing them tells an attacker whether a
        # token was ever valid.
        result = await make_owner(platform)
        await verify_email(platform, token=result.verification.token)
        await platform.commit()

        messages = []
        for token in (result.verification.token, "never-existed"):
            with pytest.raises(InvitationError) as raised:
                await verify_email(platform, token=token)
            messages.append(str(raised.value))

        assert len(set(messages)) == 1


class TestVerificationIsolation:
    async def test_the_application_role_cannot_write_verifications(
        self, session: AsyncSession
    ) -> None:
        """The table the application role holds no privilege on.

        A scoped session able to insert here could verify an address it does not
        control — which is the entire attack the table exists to prevent, with
        the extra step of already being inside the product.
        """
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError

        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(
                text(
                    "INSERT INTO email_verifications "
                    "(user_id, email, token_hash, expires_at) "
                    "VALUES (gen_random_uuid(), 'x@y.com', 'h', now())"
                )
            )

    async def test_the_application_role_cannot_read_them_either(
        self, session: AsyncSession
    ) -> None:
        # Reading a token hash is less useful than writing one, but a hash plus
        # a leaked wordlist is a different conversation, and this table has no
        # business being reachable from a request-scoped session at all.
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError

        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text("SELECT count(*) FROM email_verifications"))
