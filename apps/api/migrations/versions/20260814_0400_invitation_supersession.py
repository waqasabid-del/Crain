"""Let a workspace re-invite an address whose invitation went unaccepted.

The partial unique index on ``(tenant_id, email) WHERE accepted_at IS NULL``
enforced one outstanding invitation per address, which is right. But an
invitation that expired unaccepted still matched that predicate, so it held the
slot permanently: every subsequent attempt to invite that person failed on the
constraint, and the workspace had no way to recover except manual SQL.

``superseded_at`` separates "this invitation is finished" from "this invitation
was accepted". Issuing a new invitation stamps the old one, freeing the slot and
invalidating the previous token in the same step — which is also the correct
behaviour for "resend invitation", where two simultaneously redeemable links
would be a defect in their own right.

Rows are stamped rather than deleted: how many times an address was invited
without ever accepting is a question an audit trail should be able to answer.

Revision ID: b6e30f14a7c9
Revises: a9d24e60c3f1
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b6e30f14a7c9"
down_revision: str | None = "a9d24e60c3f1"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "invitations",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Rebuild the index against the new predicate. Dropped first because a
    # partial unique index cannot be altered in place, and recreated in the same
    # transaction so no window exists in which duplicates could be inserted.
    op.drop_index("uq_invitations_pending", table_name="invitations")
    op.create_index(
        "uq_invitations_pending",
        "invitations",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND superseded_at IS NULL"),
    )


def downgrade() -> None:
    # Superseded invitations become indistinguishable from outstanding ones on
    # the way down, so any address holding more than one would violate the
    # narrower index. Retire the extras first, keeping the newest — the only one
    # whose token the application still honours.
    op.execute(
        sa.text("""
        UPDATE invitations SET accepted_at = superseded_at
        WHERE superseded_at IS NOT NULL
          AND accepted_at IS NULL
          AND id NOT IN (
              SELECT DISTINCT ON (tenant_id, email) id
              FROM invitations
              WHERE accepted_at IS NULL
              ORDER BY tenant_id, email, created_at DESC
          )
        """)
    )

    op.drop_index("uq_invitations_pending", table_name="invitations")
    op.create_index(
        "uq_invitations_pending",
        "invitations",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL"),
    )
    op.drop_column("invitations", "superseded_at")
