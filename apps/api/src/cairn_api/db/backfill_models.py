"""Backfill state.

Progress lives here, not a worker's memory: imports are thousands of paginated
requests against a rate-limited API, and workers can be recycled mid-flight.
Resumable by cursor, not restart. Leased, not locked — a lease expires on its
own and survives a worker being killed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: How far back history is imported (md/11 §3).
BACKFILL_WINDOW_DAYS = 90


class BackfillState(enum.StrEnum):
    """Where a run has got to."""

    PENDING = "pending"
    RUNNING = "running"

    #: Rate budget spent; resumes on its own.
    THROTTLED = "throttled"

    COMPLETED = "completed"
    FAILED = "failed"


class BackfillRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One installation's historical import."""

    __tablename__ = "backfill_runs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: `owner/name`. One run per repository.
    repository: Mapped[str] = mapped_column(String(255), nullable=False)

    state: Mapped[BackfillState] = mapped_column(
        Enum(BackfillState, name="backfill_state", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=BackfillState.PENDING,
    )

    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    commits_imported: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: A lease, not a lock.
    leased_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resume_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    __table_args__ = (
        Index("ix_backfill_runs_tenant_id", "tenant_id"),
        Index("ix_backfill_runs_state", "state", "leased_until"),
    )

    @property
    def is_claimable(self) -> bool:
        return self.state in {
            BackfillState.PENDING,
            BackfillState.RUNNING,
            BackfillState.THROTTLED,
        }
