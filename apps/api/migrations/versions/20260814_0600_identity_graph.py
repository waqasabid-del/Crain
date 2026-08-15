"""The identity graph: people and their identity claims.

Unresolved, one person fragments into three partial contributors — a work email,
a personal address, a GitHub handle — each with an incomplete record. The product
then reports something false about who did the work, obviously false to the team
and invisible to the dashboard.

Both tables are tenant-scoped and under row-level security. Unlike the GitHub
tables, these are written from *within* tenant context — attribution happens on a
worker that already knows which workspace it is processing — so the application
role gets full DML here, filtered by the policy.

Revision ID: f3c81b5e2a47
Revises: e2f74a91c630
"""


# DDL. PostgreSQL accepts no bound parameters in policy definitions, and no
# value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3c81b5e2a47"
down_revision: str | None = "e2f74a91c630"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"

# `create_type=False` on each: a plain sa.Enum re-issues CREATE TYPE inside
# create_table and collides with the explicit creation below.
PERSON_KIND = postgresql.ENUM("human", "bot", "agent", name="person_kind", create_type=False)
IDENTITY_KIND = postgresql.ENUM("email", "github_login", name="identity_kind", create_type=False)
IDENTITY_STATUS = postgresql.ENUM(
    "proposed", "confirmed", "rejected", name="identity_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (PERSON_KIND, IDENTITY_KIND, IDENTITY_STATUS):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "people",
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
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("kind", PERSON_KIND, nullable=False, server_default="human"),
        # Nullable and expected to stay null for a long time: someone appears in
        # commit history when the integration connects, and may accept their
        # invitation weeks later or never. Attribution must not require an
        # account — it is what makes the invitation worth accepting.
        sa.Column(
            "user_id",
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
    )
    op.create_index("ix_people_tenant_id", "people", ["tenant_id"])
    op.create_index("ix_people_user_id", "people", ["user_id"])

    op.create_table(
        "identities",
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
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", IDENTITY_KIND, nullable=False),
        sa.Column("value", sa.String(320), nullable=False),
        sa.Column("status", IDENTITY_STATUS, nullable=False, server_default="proposed"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by_user_id",
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
        # One identifier belongs to one person per workspace. Without it, two
        # concurrent pushes carrying the same address create two people and the
        # record splits in a way nobody would think to look for.
        sa.UniqueConstraint("tenant_id", "kind", "value", name="uq_identities_tenant_kind_value"),
    )
    op.create_index("ix_identities_person_id", "identities", ["person_id"])
    op.create_index("ix_identities_tenant_id", "identities", ["tenant_id"])

    for table in ("people", "identities"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        """)

    # Full DML, unlike the GitHub tables.
    #
    # Attribution runs on a worker that already knows which workspace it is
    # processing, so these are written from *within* tenant context. The
    # WITH CHECK clause above means a scoped session cannot write a row for
    # another tenant even if it tried — which is the guarantee that makes
    # granting INSERT here safe where it was not for `webhook_deliveries`.
    for table in ("people", "identities"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cairn_app")


def downgrade() -> None:
    for table in ("identities", "people"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")

    op.drop_index("ix_identities_tenant_id", table_name="identities")
    op.drop_index("ix_identities_person_id", table_name="identities")
    op.drop_table("identities")

    op.drop_index("ix_people_user_id", table_name="people")
    op.drop_index("ix_people_tenant_id", table_name="people")
    op.drop_table("people")

    bind = op.get_bind()
    for enum_type in (IDENTITY_STATUS, IDENTITY_KIND, PERSON_KIND):
        enum_type.drop(bind, checkfirst=True)
