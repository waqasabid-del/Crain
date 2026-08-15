"""Briefs kept for the archive.

A brief for a *finished* period is stored; the current period is still generated
live and never written. The reasoning is in ``db/brief_models.py`` and comes down
to one sentence: a correction should change tomorrow's brief and must not edit
the record of what the team already read.

Both tables are tenant-scoped and under row-level security, and — like the fact
graph — the application role gets no ``DELETE``. A brief is a record of what was
said, and the operation that makes an inconvenient one disappear is the one worth
not having.

Revision ID: e7b41c92f5d8
Revises: d6f3ab29e814
"""

# DDL. PostgreSQL accepts no bound parameters in policy definitions, and no
# value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b41c92f5d8"
down_revision: str | None = "d6f3ab29e814"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"
TABLES = ("briefs", "brief_claims")


def upgrade() -> None:
    op.create_table(
        "briefs",
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
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False, server_default=""),
        sa.Column("abstained", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("suppressed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("model", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # One brief per period per workspace. Without it, two readers opening the
        # same day both generate one and the archive shows that period twice with
        # different words — the most confusing possible symptom of a race.
        sa.UniqueConstraint("tenant_id", "period_start", "period_end", name="uq_briefs_period"),
        sa.CheckConstraint("period_end > period_start", name="period_is_forwards"),
    )
    op.create_index("ix_briefs_tenant_period", "briefs", ["tenant_id", "period_end"])

    op.create_table(
        "brief_claims",
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
            "brief_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("briefs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("certainty", sa.String(16), nullable=False),
        # No foreign key on the fact ids, deliberately: a fact superseded after
        # this brief was written must not take the brief's citation with it. The
        # record of what was said survives the correction that followed it.
        sa.Column(
            "fact_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("credits", postgresql.ARRAY(sa.String(255)), nullable=False, server_default="{}"),
        sa.Column("hedged_by_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("brief_id", "ordinal", name="uq_brief_claims_ordinal"),
    )
    op.create_index("ix_brief_claims_tenant_id", "brief_claims", ["tenant_id"])
    op.create_index("ix_brief_claims_brief_id", "brief_claims", ["brief_id"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        """)
        # No DELETE, matching the fact graph. A brief is a record of what was
        # said to a team; the operation that makes an inconvenient one disappear
        # is the one worth not having.
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO cairn_app")


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index("ix_brief_claims_brief_id", table_name="brief_claims")
    op.drop_index("ix_brief_claims_tenant_id", table_name="brief_claims")
    op.drop_table("brief_claims")

    op.drop_index("ix_briefs_tenant_period", table_name="briefs")
    op.drop_table("briefs")
