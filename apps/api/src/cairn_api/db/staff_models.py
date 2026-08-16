"""Staff identity and the internal audit log.

Neither table is tenant-scoped. Staff are not members of a workspace, and the
log exists precisely to span workspaces — a record that could be read only from
inside one tenant could not answer "which customers did this person open".
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StaffRole(enum.StrEnum):
    """What a member of CAIRN staff may do in the back-office.

    The four roles md/15 §6 defines, and no catch-all: least privilege applies
    internally too, so a billing operator has no route to product data and a
    support engineer has none to the audit log. None of them reaches customer
    content — that needs an approved support session (Step 28), which no role
    can grant itself.
    """

    #: Tenant list, health and the subscription inspector.
    SUPPORT = "support"

    #: Subscription and billing actions. No product data (md/15 §6).
    BILLING = "billing"

    #: Pipeline health, cost and evaluation dashboards.
    ENGINEERING = "engineering"

    #: The full internal audit log, break-glass review, and — because access
    #: control is a security function rather than an operational convenience —
    #: staff management.
    SECURITY = "security"


class StaffMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A CAIRN employee with back-office access."""

    __tablename__ = "staff_members"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    role: Mapped[StaffRole] = mapped_column(String(32), nullable=False)

    #: Revoked rather than deleted, so "was this person staff in March" stays
    #: answerable after they leave.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class InternalAuditEntry(UUIDPrimaryKeyMixin, Base):
    """One staff action, chained to the one before it.

    `entry_hash` covers this entry's content *and* `previous_hash`, so altering
    or removing any entry invalidates every hash after it. The application role
    holds INSERT and SELECT only — there is no UPDATE or DELETE to abuse.
    """

    __tablename__ = "internal_audit_log"

    #: The order the chain is verified in. A timestamp cannot serve: two entries
    #: can share one, and clocks move backwards.
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    action: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Null for actions that concern the platform rather than one customer.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    #: Why, in the operator's own words. Required, because an action with no
    #: stated reason is one nobody can review.
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (
        Index("ix_internal_audit_log_tenant_id", "tenant_id"),
        Index("ix_internal_audit_log_actor", "actor_user_id"),
        Index("ix_internal_audit_log_sequence", "sequence"),
    )
