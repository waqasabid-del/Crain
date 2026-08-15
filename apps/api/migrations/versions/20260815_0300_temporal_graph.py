"""The temporal graph: edges between facts, and vectors to enter it by.

Two tables. ``fact_edges`` carries typed, derived relationships; ``fact_embeddings``
carries one vector per fact per model.

**The embedding is a separate table, not a column on ``facts``.** A re-embed
after a model change would otherwise rewrite every fact row and every index on
it, and the vector — by far the widest column in the schema — would be read by
every query that only wanted a statement.

**The HNSW index is created with an explicit operator class.** ``vector_cosine_ops``
must match the distance operator the query uses (``<=>``); a mismatch does not
error, it silently falls back to a sequential scan, and the only symptom is
latency nobody attributes to the index.

Both tables are tenant-scoped, under row-level security, and — like the fact
graph — granted no ``DELETE``. An embedding is derived data and a re-embed
replaces it by ``UPDATE``; an edge that no longer holds is one whose facts have
been superseded, which is a validity question rather than a deletion.

Revision ID: d6f3ab29e814
Revises: c5e28a41d7b3
"""

# DDL. PostgreSQL accepts no bound parameters in policy definitions, and no
# value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6f3ab29e814"
down_revision: str | None = "c5e28a41d7b3"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"
TABLES = ("fact_edges", "fact_embeddings")

#: Must match `embeddings.DIMENSIONS`. Duplicated rather than imported because a
#: migration describes the schema as it was on the day it ran — importing the
#: constant would make an old migration silently change shape when the model
#: does, and a re-embed is a data migration, not an edit to this file.
DIMENSIONS = 768

EDGE_KIND = postgresql.ENUM(
    "shared_evidence",
    "shared_person",
    "same_subject",
    "supersedes",
    name="edge_kind",
    create_type=False,
)


def upgrade() -> None:
    EDGE_KIND.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "fact_edges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_fact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_fact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", EDGE_KIND, nullable=False),
        # A traversal cost, never a confidence score. It orders an expansion
        # that has to stop somewhere and must not reach the interface.
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("detail", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # A fact related to itself is a traversal that never terminates and a
        # sentence that says nothing.
        sa.CheckConstraint("source_fact_id <> target_fact_id", name="no_self_edge"),
        sa.UniqueConstraint(
            "source_fact_id", "target_fact_id", "kind", name="uq_fact_edges_source_target_kind"
        ),
    )
    op.create_index("ix_fact_edges_tenant_id", "fact_edges", ["tenant_id"])
    op.create_index("ix_fact_edges_source_kind", "fact_edges", ["source_fact_id", "kind"])
    op.create_index("ix_fact_edges_target", "fact_edges", ["target_fact_id"])

    op.create_table(
        "fact_embeddings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Vectors from different models are not comparable, and mixing them
        # degrades search with nothing in the logs to explain it.
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("fact_id", "model", name="uq_fact_embeddings_fact_model"),
    )
    # Added in raw SQL rather than through a SQLAlchemy type, so this migration
    # depends on the `vector` extension and not on a Python package version. A
    # migration should still run years from now against whatever the extension
    # is; it should not stop running because a library changed its type class.
    op.execute(f"ALTER TABLE fact_embeddings ADD COLUMN embedding vector({DIMENSIONS}) NOT NULL")
    op.create_index("ix_fact_embeddings_tenant_id", "fact_embeddings", ["tenant_id"])

    # `vector_cosine_ops` matches the `<=>` operator the search uses. A mismatch
    # does not error — it quietly plans a sequential scan.
    op.execute("""
        CREATE INDEX ix_fact_embeddings_vector
        ON fact_embeddings
        USING hnsw (embedding vector_cosine_ops)
    """)

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        """)
        # No DELETE, matching the fact graph. Derived data is replaced by
        # UPDATE; an edge whose facts were superseded is a validity question,
        # and the answer is not to destroy the row that explains the chain.
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO cairn_app")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.execute("DROP INDEX IF EXISTS ix_fact_embeddings_vector")
    op.drop_index("ix_fact_embeddings_tenant_id", table_name="fact_embeddings")
    op.drop_table("fact_embeddings")

    op.drop_index("ix_fact_edges_target", table_name="fact_edges")
    op.drop_index("ix_fact_edges_source_kind", table_name="fact_edges")
    op.drop_index("ix_fact_edges_tenant_id", table_name="fact_edges")
    op.drop_table("fact_edges")

    EDGE_KIND.drop(op.get_bind(), checkfirst=True)
