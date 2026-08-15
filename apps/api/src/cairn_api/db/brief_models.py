"""Briefs, kept so that yesterday's brief is still yesterday's brief.

A finished period's brief is a record, not a view — generated once and kept,
so corrected facts can't rewrite what was already said. Citations aren't
stored here: a claim keeps its fact ids, resolved from `fact_sources`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Brief(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One period's brief, as it was written."""

    __tablename__ = "briefs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    narrative: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: "Nothing to say responsibly" vs "nothing happened" — different answers.
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Count, never the text — avoids storing rejected content.
    suppressed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: Provenance (md/09 §8).
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")

    claims: Mapped[list[BriefClaim]] = relationship(
        back_populates="brief",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BriefClaim.ordinal",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "period_start", "period_end", name="uq_briefs_period"),
        CheckConstraint("period_end > period_start", name="period_is_forwards"),
        Index("ix_briefs_tenant_period", "tenant_id", "period_end"),
    )


class BriefClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One sentence of a brief, with the facts it rests on."""

    __tablename__ = "brief_claims"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("briefs.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The order is the writing.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)

    #: `verified`, `observed`, `suggested` (md/05 §A.2.1).
    certainty: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Array, not a join table — no FK, so a fact superseded later doesn't
    #: take the citation with it.
    fact_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )

    credits: Mapped[list[str]] = mapped_column(ARRAY(String(255)), nullable=False, default=list)

    hedged_by_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    brief: Mapped[Brief] = relationship(back_populates="claims")

    __table_args__ = (
        UniqueConstraint("brief_id", "ordinal", name="uq_brief_claims_ordinal"),
        Index("ix_brief_claims_tenant_id", "tenant_id"),
        Index("ix_brief_claims_brief_id", "brief_id"),
    )
