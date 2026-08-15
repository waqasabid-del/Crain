"""The temporal graph: edges between facts, and vectors to enter it by.

md/09 §3.3: relational tables with explicit edges, plus pgvector — not a
separate graph database. Edges are derived, never asserted by a model — the
trust boundary (md/09 §6.2) sits below this table. Embeddings live in their
own table so a re-embed doesn't rewrite every fact row.
"""

from __future__ import annotations

import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from cairn_api.pipeline.embeddings import DIMENSIONS


class EdgeKind(enum.StrEnum):
    """Why two facts are connected. Typed, not a single "related" edge, so a
    chain can be checked rather than just trusted."""

    SHARED_EVIDENCE = "shared_evidence"
    SHARED_PERSON = "shared_person"
    SAME_SUBJECT = "same_subject"

    #: Traversed only for history questions — otherwise never reaches synthesis.
    SUPERSEDES = "supersedes"


class FactEdge(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A directed, typed relationship between two facts."""

    __tablename__ = "fact_edges"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facts.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facts.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[EdgeKind] = mapped_column(
        Enum(EdgeKind, name="edge_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: Traversal cost, not a confidence score — must not reach the interface
    #: (md/05 §A.2.1).
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint("source_fact_id <> target_fact_id", name="no_self_edge"),
        UniqueConstraint(
            "source_fact_id", "target_fact_id", "kind", name="uq_fact_edges_source_target_kind"
        ),
        Index("ix_fact_edges_tenant_id", "tenant_id"),
        # Composite on (source, kind): expansion filters by kind.
        Index("ix_fact_edges_source_kind", "source_fact_id", "kind"),
        Index("ix_fact_edges_target", "target_fact_id"),
    )


class FactEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The vector for one fact's statement."""

    __tablename__ = "fact_embeddings"

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

    embedding: Mapped[list[float]] = mapped_column(Vector(DIMENSIONS), nullable=False)

    #: Vectors from different models aren't comparable; mixing degrades search
    #: silently.
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("fact_id", "model", name="uq_fact_embeddings_fact_model"),
        Index("ix_fact_embeddings_tenant_id", "tenant_id"),
    )
