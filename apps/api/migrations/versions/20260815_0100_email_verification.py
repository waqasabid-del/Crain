"""Email verification, closing the pre-registration hijack.

The gap this closes is specific and was the oldest open finding in the audit
register (O1).

Anyone could register `victim@company.com` — no proof of control required — and
wait. When a colleague later invited that address to a workspace, the squatter's
account accepted the invitation and the real person was locked out of mail sent
to their own address. The email check on acceptance verified that the *address
matched*, which is not the same as verifying that the *person* did.

**An invitation is itself proof of address control**, because the token was
delivered by email. So redeeming one verifies the address rather than requiring
it verified. What is blocked is narrower and precisely aimed: an unverified
account that already holds a *password* cannot claim an invitation, because that
is the squatter. A brand-new account created during redemption is fine — the
token proves the address.

Revision ID: b4d19e73f5a8
Revises: a71f39d0c8b4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4d19e73f5a8"
down_revision: str | None = "a71f39d0c8b4"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "email_verifications",
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
        ),
        # The address this token proves control of, captured at issue time.
        #
        # Stored rather than read from the user row, because someone can change
        # their address while a token is outstanding — and a token issued for
        # the old address must not verify the new one.
        sa.Column("email", sa.String(320), nullable=False),
        # SHA-256, for the same reason as sessions and invitations: a leaked
        # database must not yield usable verification links.
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_email_verifications_user_id", "email_verifications", ["user_id"])

    # Deliberately NOT tenant-scoped and not under row-level security, for the
    # same reason as `sessions`: verification identifies a *person* and happens
    # before any workspace is known. It is written and read platform-side.
    #
    # The application role is granted nothing at all here. A scoped session that
    # could insert a verification row could verify an address it does not
    # control, which is the entire attack this table exists to prevent.
    op.execute("REVOKE ALL ON email_verifications FROM cairn_app")

    # Existing accounts are grandfathered as verified.
    #
    # There are none in production — nothing has shipped — but leaving them
    # unverified would be a silent lockout on the first deploy that did have
    # users, and a migration that can lock people out is one nobody runs.
    op.execute(sa.text("UPDATE users SET email_verified_at = now()"))


def downgrade() -> None:
    op.drop_index("ix_email_verifications_user_id", table_name="email_verifications")
    op.drop_table("email_verifications")
    op.drop_column("users", "email_verified_at")
