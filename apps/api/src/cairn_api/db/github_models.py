"""GitHub integration schema. ``GitHubInstallation`` maps an App installation to
a workspace — the only way an unauthenticated webhook is attributed to a
tenant. ``WebhookDelivery`` is the idempotency record (md/01 §4.1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DeliveryStatus(enum.StrEnum):
    """Where a delivery is in its lifecycle."""

    ACCEPTED = "accepted"
    PROCESSED = "processed"
    FAILED = "failed"

    #: For an unknown or suspended installation.
    UNCLAIMED = "unclaimed"


class GitHubInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A GitHub App installation, bound to one workspace."""

    __tablename__ = "github_installations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: `BigInteger`: GitHub's ids are already past `Integer` range.
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)

    account_login: Mapped[str] = mapped_column(String(255), nullable=False)
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)

    #: Suspended installations still deliver webhooks; processing them is a
    #: consent problem, not a bug.
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    uninstalled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant = relationship("Tenant")

    __table_args__ = (Index("ix_github_installations_tenant_id", "tenant_id"),)

    @property
    def is_active(self) -> bool:
        return self.suspended_at is None and self.uninstalled_at is None


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One webhook delivery — the idempotency record."""

    __tablename__ = "webhook_deliveries"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: `X-GitHub-Delivery` header — the idempotency key.
    delivery_id: Mapped[str] = mapped_column(String(255), nullable=False)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str | None] = mapped_column(String(64), nullable=True)

    installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(
            DeliveryStatus, name="delivery_status", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=DeliveryStatus.ACCEPTED,
    )

    #: Stored whole for reprocessing. Customer data: RLS applies.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    __table_args__ = (
        UniqueConstraint("delivery_id", name="uq_webhook_deliveries_delivery_id"),
        Index("ix_webhook_deliveries_tenant_id", "tenant_id"),
        Index("ix_webhook_deliveries_created_at", "created_at"),
    )
