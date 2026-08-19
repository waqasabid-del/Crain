"""Durable model-spend counters, per tenant, per period, per stage.

Revision ID: 4c7d1e83b9a2
Revises: 6b3e8a92f1d4
Create Date: 2026-08-19

The Stage E debt `pipeline/spend.py` flagged about itself: the ledger was
in-process, so every restart reset every tenant's counters and two replicas
would each have granted a full ceiling. These rows are the cluster-wide truth;
the in-process ledger remains the per-job view.

No DELETE grant. A spend row is billing evidence, and the retention question
(when may an old period's row go) is a decision for the retention sweep, not a
privilege the application role holds ambiently.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4c7d1e83b9a2"
down_revision = "6b3e8a92f1d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spend_counters",
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        # The first instant of the UTC calendar month. Computed in exactly one
        # place (`spend_store.current_period_start`) — see the timezone note
        # there.
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("calls", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "period_start", "stage"),
        sa.CheckConstraint("calls >= 0 AND tokens >= 0", name="spend_non_negative"),
    )

    # Tenant-scoped under RLS like every other tenant table. FORCE, so even the
    # table owner cannot read across tenants through the application role.
    op.execute("ALTER TABLE spend_counters ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE spend_counters FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON spend_counters
        USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE ON spend_counters TO cairn_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON spend_counters")
    op.drop_table("spend_counters")
