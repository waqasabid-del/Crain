"""GitHub installations and webhook deliveries.

Two tables, both tenant-scoped and both under row-level security.

The installation table is read *before* tenant context exists — an inbound
webhook is unauthenticated, and the installation ID in its payload is the only
evidence of who it belongs to. That read happens on the platform connection, the
same way session lookup does. Every other read of either table is scoped.

**The unique constraint on `delivery_id` is the idempotency guarantee.** GitHub
documents that delivery is not exactly-once; without it a redelivered webhook
produces a second row and the same activity is counted twice, which for a
product whose output is "what happened this week" is a correctness failure a
customer notices before we do.

Revision ID: e2f74a91c630
Revises: d8b52c04e719
"""


# DDL. PostgreSQL accepts no bound parameters in policy definitions, and no
# value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2f74a91c630"
down_revision: str | None = "d8b52c04e719"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"

#: `create_type=False` is load-bearing. A plain `sa.Enum` on a column re-issues
#: CREATE TYPE inside create_table, colliding with the explicit creation below —
#: the migration fails on a fresh database, which is the only kind CI has.
DELIVERY_STATUS = postgresql.ENUM(
    "accepted",
    "processed",
    "failed",
    "unclaimed",
    name="delivery_status",
    create_type=False,
)


def upgrade() -> None:
    DELIVERY_STATUS.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "github_installations",
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
        # BigInteger: GitHub's IDs are 64-bit and already past the 32-bit range.
        # An Integer column would work for years, then reject new installations
        # with an overflow nobody is expecting.
        sa.Column("installation_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("account_login", sa.String(255), nullable=False),
        sa.Column("account_type", sa.String(32), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_github_installations_tenant_id", "github_installations", ["tenant_id"])

    op.create_table(
        "webhook_deliveries",
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
        sa.Column("delivery_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=True),
        sa.Column("installation_id", sa.BigInteger(), nullable=True),
        sa.Column("status", DELIVERY_STATUS, nullable=False, server_default="accepted"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(1024), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("delivery_id", name="uq_webhook_deliveries_delivery_id"),
    )
    op.create_index("ix_webhook_deliveries_tenant_id", "webhook_deliveries", ["tenant_id"])
    op.create_index("ix_webhook_deliveries_created_at", "webhook_deliveries", ["created_at"])

    # ---------------------------------------------------------------- RLS
    for table in ("github_installations", "webhook_deliveries"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE, because ENABLE alone does not apply to the table owner — the
        # single most common way RLS is misconfigured, and one this project has
        # already been caught by once.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        """)

    # Writes are platform-side only.
    #
    # Both tables are written by the webhook handler, which runs *before* tenant
    # context exists — it is resolving the tenant. Granting INSERT to the
    # application role would mean a scoped session could forge a delivery for
    # its own tenant, and, worse, register an installation and start receiving
    # another organisation's activity.
    #
    # The application role gets SELECT only, filtered by the policy above.
    op.execute("GRANT SELECT ON github_installations TO cairn_app")
    op.execute("GRANT SELECT ON webhook_deliveries TO cairn_app")

    # UPDATE on deliveries only: a worker marks its own delivery processed, and
    # that runs inside tenant context. It cannot create one or read another
    # tenant's.
    op.execute("GRANT UPDATE ON webhook_deliveries TO cairn_app")


def downgrade() -> None:
    for table in ("webhook_deliveries", "github_installations"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index("ix_webhook_deliveries_created_at", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_tenant_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")

    op.drop_index("ix_github_installations_tenant_id", table_name="github_installations")
    op.drop_table("github_installations")

    DELIVERY_STATUS.drop(op.get_bind(), checkfirst=True)
