"""Development seed data.

Creates two tenants deliberately. One tenant proves nothing about isolation —
the whole point of the Step 4 tests is that data belonging to Acme is
unreachable while operating as Globex, and that requires a second tenant to
exist with overlapping-looking data.

Also creates a user who belongs to *both* tenants with *different* roles. That
case is easy to forget and common in reality (contractors, agency staff), and
it is exactly where a naive permission check breaks: role must be resolved per
tenant, never per user.

Synthetic data only. Production data never reaches a local environment
(md/17-engineering-standards.md §9.1).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from cairn_api.db.models import Membership, Region, Tenant, TenantRole, User
from cairn_api.db.session import dispose_engines, platform_session


async def seed() -> None:
    """Populate a development database. Idempotent.

    Uses a platform session because creating workspaces and user accounts
    precedes any tenant context — the same path signup takes.
    """
    async with platform_session() as session:
        existing = await session.scalar(select(Tenant).where(Tenant.slug == "acme"))
        if existing is not None:
            print("Seed data already present — nothing to do.")
            return

        acme = Tenant(name="Acme Corp", slug="acme", region=Region.US_CENTRAL1)
        globex = Tenant(name="Globex Inc", slug="globex", region=Region.US_CENTRAL1)

        ali = User(email="ali@acme.test", display_name="Ali")
        sara = User(email="sara@acme.test", display_name="Sara")
        jordan = User(email="jordan@globex.test", display_name="Jordan")
        # Belongs to both tenants — Owner in one, Viewer in the other.
        contractor = User(email="contractor@freelance.test", display_name="Sam")

        session.add_all([acme, globex, ali, sara, jordan, contractor])
        await session.flush()

        notified = datetime.now(UTC)

        session.add_all(
            [
                # Acme
                Membership(tenant=acme, user=ali, role=TenantRole.OWNER, notified_at=notified),
                Membership(tenant=acme, user=sara, role=TenantRole.MEMBER, notified_at=notified),
                # Deliberately not notified: ingestion must refuse to capture
                # this person's activity until they have been told (md/05 §B.3.5).
                Membership(tenant=acme, user=contractor, role=TenantRole.VIEWER),
                # Globex
                Membership(tenant=globex, user=jordan, role=TenantRole.OWNER, notified_at=notified),
                # Same human, different workspace, higher role.
                Membership(
                    tenant=globex, user=contractor, role=TenantRole.ADMIN, notified_at=notified
                ),
            ]
        )

    print("Seeded 2 tenants, 4 users, 5 memberships.")
    print("  acme    — Ali (owner), Sara (member), Sam (viewer, not yet notified)")
    print("  globex  — Jordan (owner), Sam (admin)")
    print("  Sam belongs to both tenants with different roles.")


async def main() -> None:
    try:
        await seed()
    finally:
        await dispose_engines()


if __name__ == "__main__":
    asyncio.run(main())
