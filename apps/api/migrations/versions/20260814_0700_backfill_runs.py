"""Backfill runs: resumable, leased historical imports.

A ninety-day import is thousands of paginated requests against an API with hard
rate ceilings, run by workers that can be recycled at any moment. Progress
therefore lives here rather than in a worker's memory: a worker killed at page
400 resumes at page 400, instead of re-spending four hundred pages of an
installation's rate budget to reach the same place.

Revision ID: a71f39d0c8b4
Revises: f3c81b5e2a47
"""


# into DDL. PostgreSQL accepts no bound parameters in policy definitions, and no
# value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a71f39d0c8b4"
down_revision: str | None = "f3c81b5e2a47"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"

BACKFILL_STATE = postgresql.ENUM(
    "pending",
    "running",
    "throttled",
    "completed",
    "failed",
    name="backfill_state",
    create_type=False,
)


def upgrade() -> None:
    BACKFILL_STATE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "backfill_runs",
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
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        # One run per repository, not per installation: a run covering twenty
        # repositories has one cursor and cannot record that eighteen finished
        # and two did not.
        sa.Column("repository", sa.String(255), nullable=False),
        sa.Column("state", BACKFILL_STATE, nullable=False, server_default="pending"),
        sa.Column("cursor", sa.String(512), nullable=True),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("commits_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        # A lease, not a lock. A lock held by a process that no longer exists is
        # a run that never resumes.
        sa.Column("leased_by", sa.String(128), nullable=True),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resume_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1024), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_backfill_runs_tenant_id", "backfill_runs", ["tenant_id"])
    op.create_index("ix_backfill_runs_state", "backfill_runs", ["state", "leased_until"])

    # One live run per repository per installation.
    #
    # Partial, so a completed run does not block a later re-import — a customer
    # who disconnects and reconnects should get their history again. Without
    # this, two concurrent onboarding triggers create two runs that walk the
    # same repository, doubling the rate budget spent to import it once.
    op.create_index(
        "uq_backfill_runs_active",
        "backfill_runs",
        ["installation_id", "repository"],
        unique=True,
        postgresql_where=sa.text("state IN ('pending', 'running', 'throttled')"),
    )

    op.execute("ALTER TABLE backfill_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE backfill_runs FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON backfill_runs
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # Full DML: a backfill worker runs inside tenant context, and the policy's
    # WITH CHECK means a scoped session cannot write a row for another tenant.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON backfill_runs TO cairn_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON backfill_runs")
    op.drop_index("uq_backfill_runs_active", table_name="backfill_runs")
    op.drop_index("ix_backfill_runs_state", table_name="backfill_runs")
    op.drop_index("ix_backfill_runs_tenant_id", table_name="backfill_runs")
    op.drop_table("backfill_runs")
    BACKFILL_STATE.drop(op.get_bind(), checkfirst=True)
