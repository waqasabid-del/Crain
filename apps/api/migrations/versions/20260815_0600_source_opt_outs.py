"""Per-source opt-out.

md/11 §4.1 requires the opt-out to be offered in the worker notification itself
rather than buried in settings, and §7 makes the opt-out rate the trust
barometer for the whole product. Neither means anything unless the opt-out is
enforced, which starts here.

Tenant-scoped and under row-level security like every other table holding
customer data. Unlike the fact graph, the application role **does** get
``DELETE``: opting back in is a person changing their mind about their own
record, and the row that expresses "I opted out" is the one thing they must be
able to remove. Retaining a tombstone of a withdrawn opt-out would be keeping a
record of a privacy choice after the person reversed it.

Revision ID: a3f0d81b6c42
Revises: f8c25d13a704
"""

# DDL. PostgreSQL accepts no bound parameters in policy definitions, and no
# value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f0d81b6c42"
down_revision: str | None = "f8c25d13a704"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"


def upgrade() -> None:
    op.create_table(
        "source_opt_outs",
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
        # The person, not the user: somebody appears in commit history before
        # they ever sign in, and a contributor who never creates an account must
        # still be able to opt out.
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # Opting out twice is opting out once. Two rows would make the metric
        # that measures trust (md/11 §7) read high for a double-tapped toggle.
        sa.UniqueConstraint("person_id", "source", name="uq_source_opt_outs_person_source"),
    )
    op.create_index("ix_source_opt_outs_tenant_id", "source_opt_outs", ["tenant_id"])
    op.create_index("ix_source_opt_outs_person_id", "source_opt_outs", ["person_id"])

    op.execute("ALTER TABLE source_opt_outs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE source_opt_outs FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON source_opt_outs
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)
    # DELETE is granted here, unlike on facts and briefs. Opting back in is a
    # person reversing a decision about their own record, and keeping a
    # tombstone of a withdrawn privacy choice would be the wrong kind of memory.
    #
    # UPDATE is not, because the row has no mutable state: the *presence* of the
    # row is the choice. Opting out inserts, opting back in deletes, and a
    # privilege nothing needs is one that only widens what a mistake can reach.
    op.execute("GRANT SELECT, INSERT, DELETE ON source_opt_outs TO cairn_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON source_opt_outs")
    op.drop_index("ix_source_opt_outs_person_id", table_name="source_opt_outs")
    op.drop_index("ix_source_opt_outs_tenant_id", table_name="source_opt_outs")
    op.drop_table("source_opt_outs")
