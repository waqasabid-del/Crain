"""Support sessions: what staff asked for, what the customer allowed, what was read."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _values(enum_class: type[enum.Enum]) -> list[str]:
    """Store the enum's values, not its member names."""
    return [member.value for member in enum_class]


class SupportScope(enum.StrEnum):
    """How far a support session reaches.

    A closed set, never a free string: a scope the database would accept but
    nobody decided on is an access level nobody approved.
    """

    #: Settings, integration state, ingestion health. The default, and the only
    #: scope an ordinary request should need (md/15 §5.2).
    CONFIGURATION_DIAGNOSTICS = "configuration_diagnostics"

    #: The team's actual work — statements, briefs, citations. Requires its own
    #: request and its own approval; a configuration session never widens to it.
    ACTIVITY_CONTENT = "activity_content"


class SupportSessionStatus(enum.StrEnum):
    """Where a request has got to.

    There is deliberately no `expired` value. Expiry is a fact about the clock,
    and a stored status would be wrong between the moment a session lapses and
    whatever job got around to updating it — during which `status == 'approved'`
    would read as live access. `SupportSession.is_active` computes it instead.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


class SupportSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One request by CAIRN staff to look at one workspace."""

    __tablename__ = "support_sessions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    #: Shown to the customer. What makes an approval a decision rather than a
    #: reflex.
    reason: Mapped[str] = mapped_column(String(500), nullable=False)

    # `native_enum=False` keeps the column VARCHAR with a CHECK, matching the
    # migration, while round-tripping as the enum. A plain String returns `str`,
    # and every `is` comparison against a member is then quietly False.
    requested_scope: Mapped[SupportScope] = mapped_column(
        Enum(SupportScope, native_enum=False, length=32, values_callable=_values), nullable=False
    )

    #: Null until approved, and recorded separately from the request so that
    #: "they asked for content and were given configuration" stays visible.
    approved_scope: Mapped[SupportScope | None] = mapped_column(
        Enum(SupportScope, native_enum=False, length=32, values_callable=_values), nullable=True
    )

    status: Mapped[SupportSessionStatus] = mapped_column(
        Enum(SupportSessionStatus, native_enum=False, length=16, values_callable=_values),
        nullable=False,
    )

    requested_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    #: Set at approval from the server clock, never from a caller.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Reserved. No break-glass path exists — see `internal/support.py`.
    break_glass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    events: Mapped[list[SupportAccessEvent]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_support_sessions_tenant_id", "tenant_id"),
        Index("ix_support_sessions_requested_by", "requested_by_user_id"),
    )

    def is_active(self, *, now: datetime | None = None) -> bool:
        """Whether this session grants access at this moment.

        Computed rather than stored, so an expiry that has passed cannot be
        reported as live access by a status column nobody has updated yet.
        """
        moment = now or datetime.now(UTC)
        return (
            self.status is SupportSessionStatus.APPROVED
            and self.revoked_at is None
            and self.expires_at is not None
            and self.expires_at > moment
        )


class SupportAccessEvent(UUIDPrimaryKeyMixin, Base):
    """One thing staff actually opened during a session.

    Separate from the session: an approval is permission, and this is use. A
    customer asking "did they actually look" is asking about these rows.
    """

    __tablename__ = "support_access_events"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("support_sessions.id", ondelete="CASCADE"), nullable=False
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    scope: Mapped[SupportScope] = mapped_column(
        Enum(SupportScope, native_enum=False, length=32, values_callable=_values), nullable=False
    )

    #: What was opened, in the customer's terms rather than as a route path.
    description: Mapped[str] = mapped_column(String(200), nullable=False)

    session: Mapped[SupportSession] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_support_access_events_tenant_id", "tenant_id"),
        Index("ix_support_access_events_session", "session_id"),
    )
