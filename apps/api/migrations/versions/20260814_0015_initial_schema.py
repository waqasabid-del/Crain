"""Initial schema: tenants, users and memberships.

Revision ID: 7f3ecb2d0b7a
Revises:
Created: 2026-08-14 00:15:20.254721
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7f3ecb2d0b7a"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector is required by the temporal graph's entry-point search
    # (md/09-understanding-layer.md §3.3). Enabled in the first migration
    # because CREATE EXTENSION needs privileges that the application role will
    # not hold in production — doing it later means a privileged out-of-band
    # step during a deploy.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column(
            "region",
            sa.Enum("us-central1", "europe-west1", name="region"),
            server_default="us-central1",
            nullable=False,
        ),
        sa.Column("retention_days", sa.Integer(), server_default=sa.text("365"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_index(
        "ix_tenants_slug_lower", "tenants", [sa.literal_column("lower(slug)")], unique=True
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "ix_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "memberships",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "admin", "member", "viewer", name="tenant_role"),
            server_default="member",
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_memberships_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"], unique=False)
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_index("ix_memberships_tenant_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_tenants_slug_lower", table_name="tenants")
    op.drop_table("tenants")

    # Dropping a table does NOT drop the enum type it referenced. Without this,
    # `downgrade` followed by `upgrade` fails with "type already exists" — the
    # exact sequence a rollback performs, so the failure would only appear at
    # the worst possible moment. Verified by test_migrations.py.
    sa.Enum(name="tenant_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="region").drop(op.get_bind(), checkfirst=True)

    op.execute("DROP EXTENSION IF EXISTS vector")
