"""Core schema — tenants, users, and the membership that binds them.

The central modelling decision is that **users are global and memberships are
tenant-scoped**. A person has one identity across CAIRN and a separate role in
each workspace they belong to.

That matters more than it first appears. Contractors and agency staff routinely
work with several companies, and the naive alternative — a user row per tenant —
would mean the same human being appears as several unrelated people, each with a
partial contribution record. Since CAIRN's whole proposition is an honest
picture of who did what, fragmenting identity at the schema level would
undermine the product at its foundation.

See md/15-system-roles-and-surfaces.md §2 and §3.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantRole(enum.StrEnum):
    """A person's role within one workspace.

    Deliberately four. Role explosion is a documented trap — 500 customers with
    ten custom roles each produces 5,000 roles nobody can reason about — so
    custom roles wait until an enterprise customer genuinely needs them.

    Critically, ``ADMIN`` governs *configuration*, never *visibility depth*. No
    role grants deeper insight into an individual than that individual has of
    themselves. This inverts the usual SaaS assumption and is enforced in the
    permission layer (Step 8), not here.

    See md/15 §2.2 and §2.3.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Region(enum.StrEnum):
    """Where a tenant's data is stored.

    Present from the first migration even though only ``US_CENTRAL1`` is live.
    Retrofitting per-tenant region assignment once tenants exist is a data
    migration under compliance pressure — one of the most expensive corrections
    available (md/06 §6.3).
    """

    US_CENTRAL1 = "us-central1"
    EUROPE_WEST1 = "europe-west1"


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer workspace. The unit of isolation for everything in CAIRN."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: URL-safe identifier, unique across the platform.
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)

    region: Mapped[Region] = mapped_column(
        Enum(Region, name="region", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=Region.US_CENTRAL1.value,
    )

    #: Retention period for raw activity data. Default 12 months (md/05 §B.4).
    retention_days: Mapped[int] = mapped_column(nullable=False, server_default=text("365"))

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # Slugs appear in URLs, so the constraint is case-insensitive to prevent
        # "Acme" and "acme" resolving to different workspaces.
        Index("ix_tenants_slug_lower", text("lower(slug)"), unique=True),
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person. Global, not tenant-scoped — see the module docstring.

    Note this table is deliberately **not** subject to row-level security: a
    user exists independently of any workspace. Access control happens through
    ``Membership``, which is tenant-scoped.
    """

    __tablename__ = "users"

    #: Stored lower-cased. Uniqueness is enforced case-insensitively below,
    #: because treating Ali@x.com and ali@x.com as different people would
    #: silently fragment one person's contribution record.
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(200))

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_users_email_lower", text("lower(email)"), unique=True),)


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's role within one tenant.

    Carries ``tenant_id`` explicitly because row-level security policies filter
    on it directly (Step 4). Deriving the tenant through a join would make those
    policies both slower and considerably harder to reason about.
    """

    __tablename__ = "memberships"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[TenantRole] = mapped_column(
        Enum(TenantRole, name="tenant_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=TenantRole.MEMBER.value,
    )

    #: When this person was told their activity may be captured.
    #:
    #: Worker notification is legally required *before* any capture begins
    #: (md/05 §B.3.5), so it lives at the data layer rather than depending on
    #: application diligence. Ingestion checks this column; ``NULL`` means no
    #: capture, with no exception path.
    #:
    #: A timestamp rather than a boolean because "when were they told" is the
    #: question an auditor asks, and a boolean cannot answer it.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

    __table_args__ = (
        # One membership per person per workspace.
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        # RLS policies filter on tenant_id on essentially every query.
        Index("ix_memberships_tenant_id", "tenant_id"),
        Index("ix_memberships_user_id", "user_id"),
    )
