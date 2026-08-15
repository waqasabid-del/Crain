"""The fact graph: facts, their sources, and the people they concern.

Three tables, tenant-scoped and under row-level security. Written from a worker
that already knows which workspace it is processing, so the application role
gets full DML here — the same reasoning as the identity graph, and safe for the
same reason: the ``WITH CHECK`` clause means a scoped session cannot write a row
for another tenant even if it tried.

**The column that carries the design is ``valid_until``.** Facts are superseded,
never deleted (md/12 §6). A fact whose validity has ended keeps its row, its
sources and its history, and gains a pointer to whatever replaced it. Only rows
with ``valid_until IS NULL`` reach synthesis, which is why the composite index is
partial on exactly that predicate: superseded rows accumulate forever and are
read only when someone asks what changed.

``superseded_by_id`` is self-referential with ``ON DELETE SET NULL``, not
CASCADE. Deleting a superseding fact must never take the history it replaced
with it — in practice facts are not deleted at all, and this is the guard for
the case where one is.

Revision ID: c5e28a41d7b3
Revises: b4d19e73f5a8
"""

# DDL. PostgreSQL accepts no bound parameters in policy definitions, and no
# value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5e28a41d7b3"
down_revision: str | None = "b4d19e73f5a8"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"
TABLES = ("facts", "fact_sources", "fact_people")

FACT_ORIGIN = postgresql.ENUM("extracted", "correction", name="fact_origin", create_type=False)


def upgrade() -> None:
    FACT_ORIGIN.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "facts",
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
        # A string rather than an enum type: the taxonomy will grow as the
        # product learns what a brief needs, and a new fact kind should be a
        # code change rather than an ALTER TYPE lock on a hot table.
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("certainty", sa.String(16), nullable=False),
        sa.Column("origin", FACT_ORIGIN, nullable=False, server_default="extracted"),
        # When the activity happened, distinct from when the row was written.
        # The distinction decides supersession: a backfill of six months of
        # history is ingested today but must not supersede this morning's state.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "superseded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("facts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("supersession_reason", sa.String(500), nullable=True),
        sa.Column(
            "corrected_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # A superseded fact must say what replaced it. Half a supersession —
        # validity closed with no successor — is a fact that silently vanishes
        # from every brief with nothing to explain the absence.
        sa.CheckConstraint(
            "(valid_until IS NULL) = (superseded_by_id IS NULL)",
            name="supersession_is_complete",
        ),
        # Nothing may supersede itself. Without this, one bad update makes a
        # fact permanently invalid and permanently unexplainable.
        sa.CheckConstraint(
            "superseded_by_id IS NULL OR superseded_by_id <> id",
            name="no_self_supersession",
        ),
    )
    op.create_index("ix_facts_tenant_id", "facts", ["tenant_id"])
    op.create_index("ix_facts_superseded_by_id", "facts", ["superseded_by_id"])
    op.create_index(
        "ix_facts_tenant_valid",
        "facts",
        ["tenant_id", "occurred_at"],
        postgresql_where=sa.text("valid_until IS NULL"),
    )

    op.create_table(
        "fact_sources",
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
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("evidence_id", sa.String(255), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # One source cites a fact once. Without it, reprocessing the same event
        # after a redeploy doubles a fact's apparent corroboration — and
        # corroboration promotes certainty, so the duplicate would not merely
        # be untidy, it would make the system sound more sure than it is.
        sa.UniqueConstraint(
            "fact_id", "source", "evidence_id", name="uq_fact_sources_fact_source_evidence"
        ),
    )
    op.create_index("ix_fact_sources_tenant_id", "fact_sources", ["tenant_id"])
    op.create_index("ix_fact_sources_fact_id", "fact_sources", ["fact_id"])

    op.create_table(
        "fact_people",
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
        # Null when the mention could not be resolved to exactly one person.
        # The row is kept anyway: an unresolved mention is a question the
        # product can ask the workspace, a dropped one is a name nobody can
        # recover.
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("mention", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("fact_id", "mention", name="uq_fact_people_fact_mention"),
    )
    op.create_index("ix_fact_people_tenant_id", "fact_people", ["tenant_id"])
    op.create_index("ix_fact_people_person_id", "fact_people", ["person_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        """)
        # No DELETE, deliberately.
        #
        # Facts are superseded, never deleted (md/12 §6) — the invariant the
        # whole table is built around. Leaving the privilege granted "just in
        # case" would mean the one operation that destroys history is available
        # to every code path that already has a scoped session, and the first
        # time it is used will be a bug fix under time pressure. A tenant being
        # removed still cascades: referential actions run with the table
        # owner's rights, not the caller's.
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO cairn_app")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index("ix_fact_people_person_id", table_name="fact_people")
    op.drop_index("ix_fact_people_tenant_id", table_name="fact_people")
    op.drop_table("fact_people")

    op.drop_index("ix_fact_sources_fact_id", table_name="fact_sources")
    op.drop_index("ix_fact_sources_tenant_id", table_name="fact_sources")
    op.drop_table("fact_sources")

    op.drop_index("ix_facts_tenant_valid", table_name="facts")
    op.drop_index("ix_facts_superseded_by_id", table_name="facts")
    op.drop_index("ix_facts_tenant_id", table_name="facts")
    op.drop_table("facts")

    FACT_ORIGIN.drop(op.get_bind(), checkfirst=True)
