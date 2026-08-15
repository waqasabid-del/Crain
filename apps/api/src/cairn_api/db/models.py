"""Core schema — tenants, users, and the membership that binds them. Users are
global, memberships are tenant-scoped, so a contractor at several companies
isn't fragmented into unrelated people (md/15 §2, §3).
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
    """A person's role within one workspace. Deliberately four (md/15 §2.2).
    ``ADMIN`` governs configuration, never visibility depth."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class WorkRole(enum.StrEnum):
    """What somebody does, self-described. Not a permission — decides what
    CAIRN opens on (md/08 §A, md/11 §6)."""

    FOUNDER = "founder"
    DEVELOPER = "developer"
    DESIGNER = "designer"
    PRODUCT = "product"
    OPERATIONS = "operations"


class Region(enum.StrEnum):
    """Where a tenant's data is stored (only ``US_CENTRAL1`` is live so far,
    md/06 §6.3)."""

    US_CENTRAL1 = "us-central1"
    EUROPE_WEST1 = "europe-west1"


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer workspace. The unit of isolation for everything in CAIRN."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)

    region: Mapped[Region] = mapped_column(
        Enum(Region, name="region", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        server_default=Region.US_CENTRAL1.value,
    )

    #: Default 12 months (md/05 §B.4).
    retention_days: Mapped[int] = mapped_column(nullable=False, server_default=text("365"))

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("ix_tenants_slug_lower", text("lower(slug)"), unique=True),)


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person. Global, not tenant-scoped, and not subject to RLS."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False)

    display_name: Mapped[str | None] = mapped_column(String(200))

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    #: Closes a squatting gap — redeeming an invitation verifies the address.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def email_is_verified(self) -> bool:
        return self.email_verified_at is not None

    __table_args__ = (Index("ix_users_email_lower", text("lower(email)"), unique=True),)


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user's role within one tenant. Carries ``tenant_id`` explicitly since
    RLS policies filter on it directly."""

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

    work_role: Mapped[WorkRole | None] = mapped_column(String(32), nullable=True)

    #: Legally required before capture begins (md/05 §B.3.5); ``NULL`` means
    #: no capture.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
        Index("ix_memberships_tenant_id", "tenant_id"),
        Index("ix_memberships_user_id", "user_id"),
    )
