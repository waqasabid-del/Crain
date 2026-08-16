"""Staff identity, and a tamper-evident record of everything staff do.

md/15 §5.2 requires the log to be capable of *exonerating*: when a customer asks
whether staff read their data, an answer that staff could have edited is worth
nothing. Two mechanisms, because neither is sufficient alone:

**Hash chaining.** Each entry stores the hash of its predecessor, so altering or
deleting any row breaks every hash after it. Detection is a walk, not a diff
against a backup.

**Grants.** ``cairn_app`` receives INSERT and SELECT on the log and nothing else.
There is no UPDATE or DELETE to abuse, so an application-level compromise cannot
rewrite history — only append to it, visibly.

Neither table is tenant-scoped and neither carries row-level security: staff are
not members of a tenant, and the log's whole purpose is to span them. Both are
therefore excluded from the RLS policies deliberately rather than by omission,
and `test_internal.py` asserts the exclusion is intentional.

**What is deferred:** md/15 §5.2 also asks for storage *separate from the
application database*, so that a compromise of this database cannot suppress the
record. That is an infrastructure change — a write-only sink in another project
— and belongs with Step 29's observability work. The chain makes tampering
detectable here; separate storage would make it impossible. Recorded so the gap
is a decision rather than an oversight.

Revision ID: f7a1c3e95b28
Revises: e4b78c2af913
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7a1c3e95b28"
down_revision: str | None = "e4b78c2af913"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "staff_members",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Constrained in the database as well as in Python. This column decides
        # what a member of staff may reach, and an application-only check is one
        # bad migration or one direct UPDATE away from granting anything.
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "role IN ('support', 'billing', 'engineering', 'security')",
            name="ck_staff_members_role",
        ),
        # Revoked rather than deleted: "was this person staff in March" is the
        # question an audit asks, and a deleted row cannot answer it.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "internal_audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Monotonic, and the order the chain is verified in. A timestamp is not
        # enough: two entries can share one, and clocks move backwards.
        # An identity column rather than a serial: the implicit sequence needs no
        # separate grant, so the append-only privilege set stays two words long.
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False, unique=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        # Nullable: some actions concern the platform rather than one customer.
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Why, in the operator's words. Required by the API, because an action
        # with no stated reason is one nobody can review.
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "detail", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False, unique=True),
    )
    op.create_index("ix_internal_audit_log_tenant_id", "internal_audit_log", ["tenant_id"])
    op.create_index("ix_internal_audit_log_actor", "internal_audit_log", ["actor_user_id"])
    op.create_index("ix_internal_audit_log_sequence", "internal_audit_log", ["sequence"])

    op.execute("GRANT SELECT, INSERT, UPDATE ON staff_members TO cairn_app")

    # Append and read. No UPDATE and no DELETE: the log is the one table in this
    # schema that must survive a compromise of the application role.
    op.execute("GRANT SELECT, INSERT ON internal_audit_log TO cairn_app")


def downgrade() -> None:
    op.drop_table("internal_audit_log")
    op.drop_table("staff_members")
