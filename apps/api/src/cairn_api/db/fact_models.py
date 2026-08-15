"""The fact graph: what the system believes, when it believed it, and why.

Facts are superseded, never overwritten (md/12 §6, md/09 §3.2): `valid_until`
closes and `superseded_by_id` points at the replacement, nothing is deleted —
keeps history answerable and corrections retained as evaluation data (md/10
§2.1). Mentions are separate from people: `fact_people.mention` keeps the raw
string even when unresolved.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FactOrigin(enum.StrEnum):
    """Who asserted this — a human correction outranks an extracted fact."""

    EXTRACTED = "extracted"
    CORRECTION = "correction"


class Fact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One statement, with a validity interval."""

    __tablename__ = "facts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: `delivery`, `decision`, `blocker`, `in_progress`, `open_question`. String,
    #: not a DB enum, so a new kind is a code change.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)

    statement: Mapped[str] = mapped_column(Text, nullable=False)

    #: `verified`, `observed`, `suggested` (md/05 §A.2.1).
    certainty: Mapped[str] = mapped_column(String(16), nullable=False)

    origin: Mapped[FactOrigin] = mapped_column(
        Enum(FactOrigin, name="fact_origin", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=FactOrigin.EXTRACTED,
    )

    #: Distinct from `created_at`: a backfill ingested today mustn't supersede
    #: this morning's state.
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Null means currently valid (md/09 §3.2).
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: `SET NULL`, not CASCADE — deleting a superseding fact mustn't take the
    #: history it replaced with it.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facts.id", ondelete="SET NULL"),
        nullable=True,
    )

    supersession_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    corrected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    sources: Mapped[list[FactSource]] = relationship(
        back_populates="fact",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    people: Mapped[list[FactPerson]] = relationship(
        back_populates="fact",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        # A closed window needs a successor unless a person closed it —
        # denials have no replacement.
        CheckConstraint(
            "(valid_until IS NULL AND superseded_by_id IS NULL) "
            "OR superseded_by_id IS NOT NULL "
            "OR (origin = 'correction' AND corrected_by_user_id IS NOT NULL)",
            name="supersession_is_complete",
        ),
        CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="no_self_supersession",
        ),
        Index("ix_facts_tenant_id", "tenant_id"),
        # Synthesis's query; partial on `valid_until IS NULL`.
        Index(
            "ix_facts_tenant_valid",
            "tenant_id",
            "occurred_at",
            postgresql_where=text("valid_until IS NULL"),
        ),
        Index("ix_facts_superseded_by_id", "superseded_by_id"),
    )


class FactSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Where a fact came from, precisely enough to check it."""

    __tablename__ = "fact_sources"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facts.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: `github`, `chat`, `meeting`, `document`.
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    evidence_id: Mapped[str] = mapped_column(String(255), nullable=False)

    #: Step 18 verifies quoted text appears in the source.
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    #: On the citation, not the fact — a fact reconciled from a PR and the
    #: meeting discussing it belongs to both.
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)

    fact: Mapped[Fact] = relationship(back_populates="sources")

    __table_args__ = (
        UniqueConstraint(
            "fact_id", "source", "evidence_id", name="uq_fact_sources_fact_source_evidence"
        ),
        Index("ix_fact_sources_tenant_id", "tenant_id"),
        Index("ix_fact_sources_fact_id", "fact_id"),
        Index(
            "ix_fact_sources_tenant_project",
            "tenant_id",
            "project",
            postgresql_where=text("project IS NOT NULL"),
        ),
    )


class FactPerson(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person a fact concerns, resolved or not."""

    __tablename__ = "fact_people"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facts.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Null when unresolved; kept as a row, not dropped.
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=True,
    )

    mention: Mapped[str] = mapped_column(String(255), nullable=False)

    fact: Mapped[Fact] = relationship(back_populates="people")

    __table_args__ = (
        UniqueConstraint("fact_id", "mention", name="uq_fact_people_fact_mention"),
        Index("ix_fact_people_tenant_id", "tenant_id"),
        Index("ix_fact_people_person_id", "person_id"),
    )
