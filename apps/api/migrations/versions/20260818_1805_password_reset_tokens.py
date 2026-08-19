"""password reset tokens

Mirrors `email_verifications` exactly: a token identifying a person rather
than a workspace member, so it is platform-side and not tenant-scoped, and
the application role is granted nothing on it at all — a scoped session able
to insert here could reset a password it does not own, which is the same
class of attack the email-verification table exists to close.

Revision ID: 1631eea85edf
Revises: b1e6c4a92f37
Created: 2026-08-18 18:05:29.631974
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1631eea85edf"
down_revision: str | None = "4c7d1e83b9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_resets",
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
        # SHA-256, for the same reason as sessions, invitations and email
        # verifications: a leaked database must not yield usable reset links.
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
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])

    # Deliberately NOT tenant-scoped and not under row-level security, for the
    # same reason as `email_verifications`: this identifies a person and must
    # be resolvable before any workspace is known, and is written and read
    # platform-side only.
    #
    # The application role is granted nothing at all here. A scoped session
    # that could insert a reset row could reset a password it does not
    # control, which is the entire attack this table exists to prevent.
    op.execute("REVOKE ALL ON password_resets FROM cairn_app")


def downgrade() -> None:
    op.drop_index("ix_password_resets_user_id", table_name="password_resets")
    op.drop_table("password_resets")
