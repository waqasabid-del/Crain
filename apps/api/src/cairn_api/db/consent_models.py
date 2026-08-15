"""Per-source opt-out, held per person (md/11 §4.1, §7).

One row means "don't attribute this source's activity to me" — activity isn't
deleted, only attribution (bot precedent, md/01 §5.2). Retroactive: unlinks
existing attributions on write; see `pipeline/consent.py`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SourceOptOut(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person, one source they have opted out of."""

    __tablename__ = "source_opt_outs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The person, not the user (md/01 §5.3) — must work before an account exists.
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: `github`, `chat`, `meeting`, `document`. String, matching `facts.kind`.
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("person_id", "source", name="uq_source_opt_outs_person_source"),
        Index("ix_source_opt_outs_tenant_id", "tenant_id"),
        Index("ix_source_opt_outs_person_id", "person_id"),
    )
