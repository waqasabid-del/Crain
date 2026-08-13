"""Schema tests.

These assert the constraints that protect data integrity — the ones where a
regression would be silent rather than loud, and would surface later as
mis-attributed work or a duplicated person.

They use the ``platform`` fixture rather than ``session``. Creating a workspace
or a user account is a platform operation that precedes any tenant context, so
row-level security correctly refuses to do it from a scoped session — see
``test_tenant_isolation.py``. These tests are about table constraints, not
about isolation.
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


async def _tenant(platform: AsyncSession, slug: str = "acme") -> Tenant:
    tenant = Tenant(name=slug.title(), slug=slug)
    platform.add(tenant)
    await platform.flush()
    return tenant


async def _user(platform: AsyncSession, email: str) -> User:
    user = User(email=email)
    platform.add(user)
    await platform.flush()
    return user


class TestTenant:
    async def test_defaults_to_the_live_region(self, platform: AsyncSession) -> None:
        tenant = await _tenant(platform)
        await platform.refresh(tenant)
        assert tenant.region == Region.US_CENTRAL1

    async def test_defaults_to_twelve_month_retention(self, platform: AsyncSession) -> None:
        # md/05 §B.4 — 12 months of raw activity, configurable per tenant.
        tenant = await _tenant(platform)
        await platform.refresh(tenant)
        assert tenant.retention_days == 365

    async def test_generates_its_own_id(self, platform: AsyncSession) -> None:
        tenant = await _tenant(platform)
        assert isinstance(tenant.id, uuid.UUID)

    async def test_rejects_a_duplicate_slug(self, platform: AsyncSession) -> None:
        await _tenant(platform, "acme")
        platform.add(Tenant(name="Impostor", slug="acme"))
        with pytest.raises(IntegrityError):
            await platform.flush()

    async def test_rejects_a_slug_differing_only_by_case(self, platform: AsyncSession) -> None:
        # Slugs appear in URLs. "Acme" and "acme" resolving to different
        # workspaces would be a genuine tenant-confusion hazard.
        await _tenant(platform, "acme")
        platform.add(Tenant(name="Impostor", slug="ACME"))
        with pytest.raises(IntegrityError):
            await platform.flush()

    async def test_timestamps_are_timezone_aware(self, platform: AsyncSession) -> None:
        # A naive timestamp would silently misorder activity across regions and
        # daylight-saving boundaries, surfacing as a brief reporting the wrong
        # day's work (md/12 §3.2).
        tenant = await _tenant(platform)
        await platform.refresh(tenant)
        assert tenant.created_at.tzinfo is not None


class TestUser:
    async def test_rejects_a_duplicate_email(self, platform: AsyncSession) -> None:
        await _user(platform, "ali@acme.test")
        platform.add(User(email="ali@acme.test"))
        with pytest.raises(IntegrityError):
            await platform.flush()

    async def test_rejects_an_email_differing_only_by_case(self, platform: AsyncSession) -> None:
        # Treating Ali@ and ali@ as different people would fragment one person's
        # contribution record — the failure the product exists to prevent.
        await _user(platform, "ali@acme.test")
        platform.add(User(email="Ali@Acme.test"))
        with pytest.raises(IntegrityError):
            await platform.flush()


class TestMembership:
    async def test_defaults_to_member_role(self, platform: AsyncSession) -> None:
        # Least privilege: a membership created without an explicit role must
        # not silently confer administrative access.
        tenant = await _tenant(platform)
        user = await _user(platform, "ali@acme.test")
        membership = Membership(tenant_id=tenant.id, user_id=user.id)
        platform.add(membership)
        await platform.flush()
        await platform.refresh(membership)
        assert membership.role == TenantRole.MEMBER

    async def test_is_not_notified_by_default(self, platform: AsyncSession) -> None:
        # md/05 §B.3.5 — no capture before notification, enforced at the data
        # layer rather than left to application diligence.
        tenant = await _tenant(platform)
        user = await _user(platform, "ali@acme.test")
        membership = Membership(tenant_id=tenant.id, user_id=user.id)
        platform.add(membership)
        await platform.flush()
        assert membership.notified_at is None

    async def test_rejects_a_duplicate_membership(self, platform: AsyncSession) -> None:
        tenant = await _tenant(platform)
        user = await _user(platform, "ali@acme.test")
        platform.add(Membership(tenant_id=tenant.id, user_id=user.id))
        await platform.flush()

        platform.add(Membership(tenant_id=tenant.id, user_id=user.id))
        with pytest.raises(IntegrityError):
            await platform.flush()

    async def test_one_person_holds_different_roles_in_different_tenants(
        self, platform: AsyncSession
    ) -> None:
        """The case a naive permission check gets wrong.

        Contractors and agency staff are common in the target market. Role must
        be resolved per tenant, never per user — otherwise someone who is an
        Owner of their own workspace would inherit Owner rights in a client's.
        """
        acme = await _tenant(platform, "acme")
        globex = await _tenant(platform, "globex")
        contractor = await _user(platform, "sam@freelance.test")

        platform.add_all(
            [
                Membership(tenant_id=acme.id, user_id=contractor.id, role=TenantRole.VIEWER),
                Membership(tenant_id=globex.id, user_id=contractor.id, role=TenantRole.ADMIN),
            ]
        )
        await platform.flush()

        roles = {
            m.tenant_id: m.role
            for m in (
                await platform.scalars(
                    select(Membership).where(Membership.user_id == contractor.id)
                )
            ).all()
        }

        assert roles[acme.id] == TenantRole.VIEWER
        assert roles[globex.id] == TenantRole.ADMIN

    async def test_deleting_a_tenant_removes_its_memberships(self, platform: AsyncSession) -> None:
        # Required for GDPR Article 17 erasure — a deletion that leaves orphaned
        # membership rows has not actually erased the relationship.
        tenant = await _tenant(platform)
        user = await _user(platform, "ali@acme.test")
        platform.add(Membership(tenant_id=tenant.id, user_id=user.id))
        await platform.flush()

        await platform.delete(tenant)
        await platform.flush()

        remaining = (
            await platform.scalars(select(Membership).where(Membership.tenant_id == tenant.id))
        ).all()
        assert remaining == []

    async def test_notified_at_round_trips_as_timezone_aware(self, platform: AsyncSession) -> None:
        tenant = await _tenant(platform)
        user = await _user(platform, "ali@acme.test")
        when = datetime.now(UTC)
        membership = Membership(tenant_id=tenant.id, user_id=user.id, notified_at=when)
        platform.add(membership)
        await platform.flush()
        await platform.refresh(membership)

        assert membership.notified_at is not None
        assert membership.notified_at.tzinfo is not None
