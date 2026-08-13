"""Schema tests.

These assert the constraints that protect data integrity — the ones where a
regression would be silent rather than loud, and would surface later as
mis-attributed work or a duplicated person.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.db.models import Membership, Region, Tenant, TenantRole, User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _tenant(session: AsyncSession, slug: str = "acme") -> Tenant:
    tenant = Tenant(name=slug.title(), slug=slug)
    session.add(tenant)
    await session.flush()
    return tenant


async def _user(session: AsyncSession, email: str) -> User:
    user = User(email=email)
    session.add(user)
    await session.flush()
    return user


class TestTenant:
    async def test_defaults_to_the_live_region(self, session: AsyncSession) -> None:
        tenant = await _tenant(session)
        await session.refresh(tenant)
        assert tenant.region == Region.US_CENTRAL1

    async def test_defaults_to_twelve_month_retention(self, session: AsyncSession) -> None:
        # md/05 §B.4 — 12 months of raw activity, configurable per tenant.
        tenant = await _tenant(session)
        await session.refresh(tenant)
        assert tenant.retention_days == 365

    async def test_generates_its_own_id(self, session: AsyncSession) -> None:
        tenant = await _tenant(session)
        assert isinstance(tenant.id, uuid.UUID)

    async def test_rejects_a_duplicate_slug(self, session: AsyncSession) -> None:
        await _tenant(session, "acme")
        session.add(Tenant(name="Impostor", slug="acme"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_rejects_a_slug_differing_only_by_case(self, session: AsyncSession) -> None:
        # Slugs appear in URLs. "Acme" and "acme" resolving to different
        # workspaces would be a genuine tenant-confusion hazard.
        await _tenant(session, "acme")
        session.add(Tenant(name="Impostor", slug="ACME"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_timestamps_are_timezone_aware(self, session: AsyncSession) -> None:
        # A naive timestamp would silently misorder activity across regions and
        # daylight-saving boundaries, surfacing as a brief reporting the wrong
        # day's work (md/12 §3.2).
        tenant = await _tenant(session)
        await session.refresh(tenant)
        assert tenant.created_at.tzinfo is not None


class TestUser:
    async def test_rejects_a_duplicate_email(self, session: AsyncSession) -> None:
        await _user(session, "ali@acme.test")
        session.add(User(email="ali@acme.test"))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_rejects_an_email_differing_only_by_case(self, session: AsyncSession) -> None:
        # Treating Ali@ and ali@ as different people would fragment one person's
        # contribution record — the failure the product exists to prevent.
        await _user(session, "ali@acme.test")
        session.add(User(email="Ali@Acme.test"))
        with pytest.raises(IntegrityError):
            await session.flush()


class TestMembership:
    async def test_defaults_to_member_role(self, session: AsyncSession) -> None:
        # Least privilege: a membership created without an explicit role must
        # not silently confer administrative access.
        tenant = await _tenant(session)
        user = await _user(session, "ali@acme.test")
        membership = Membership(tenant_id=tenant.id, user_id=user.id)
        session.add(membership)
        await session.flush()
        await session.refresh(membership)
        assert membership.role == TenantRole.MEMBER

    async def test_is_not_notified_by_default(self, session: AsyncSession) -> None:
        # md/05 §B.3.5 — no capture before notification, enforced at the data
        # layer rather than left to application diligence.
        tenant = await _tenant(session)
        user = await _user(session, "ali@acme.test")
        membership = Membership(tenant_id=tenant.id, user_id=user.id)
        session.add(membership)
        await session.flush()
        assert membership.notified_at is None

    async def test_rejects_a_duplicate_membership(self, session: AsyncSession) -> None:
        tenant = await _tenant(session)
        user = await _user(session, "ali@acme.test")
        session.add(Membership(tenant_id=tenant.id, user_id=user.id))
        await session.flush()

        session.add(Membership(tenant_id=tenant.id, user_id=user.id))
        with pytest.raises(IntegrityError):
            await session.flush()

    async def test_one_person_holds_different_roles_in_different_tenants(
        self, session: AsyncSession
    ) -> None:
        """The case a naive permission check gets wrong.

        Contractors and agency staff are common in the target market. Role must
        be resolved per tenant, never per user — otherwise someone who is an
        Owner of their own workspace would inherit Owner rights in a client's.
        """
        acme = await _tenant(session, "acme")
        globex = await _tenant(session, "globex")
        contractor = await _user(session, "sam@freelance.test")

        session.add_all(
            [
                Membership(tenant_id=acme.id, user_id=contractor.id, role=TenantRole.VIEWER),
                Membership(tenant_id=globex.id, user_id=contractor.id, role=TenantRole.ADMIN),
            ]
        )
        await session.flush()

        roles = {
            m.tenant_id: m.role
            for m in (
                await session.scalars(select(Membership).where(Membership.user_id == contractor.id))
            ).all()
        }

        assert roles[acme.id] == TenantRole.VIEWER
        assert roles[globex.id] == TenantRole.ADMIN

    async def test_deleting_a_tenant_removes_its_memberships(self, session: AsyncSession) -> None:
        # Required for GDPR Article 17 erasure — a deletion that leaves orphaned
        # membership rows has not actually erased the relationship.
        tenant = await _tenant(session)
        user = await _user(session, "ali@acme.test")
        session.add(Membership(tenant_id=tenant.id, user_id=user.id))
        await session.flush()

        await session.delete(tenant)
        await session.flush()

        remaining = (
            await session.scalars(select(Membership).where(Membership.tenant_id == tenant.id))
        ).all()
        assert remaining == []

    async def test_notified_at_round_trips_as_timezone_aware(self, session: AsyncSession) -> None:
        tenant = await _tenant(session)
        user = await _user(session, "ali@acme.test")
        when = datetime.now(UTC)
        membership = Membership(tenant_id=tenant.id, user_id=user.id, notified_at=when)
        session.add(membership)
        await session.flush()
        await session.refresh(membership)

        assert membership.notified_at is not None
        assert membership.notified_at.tzinfo is not None
