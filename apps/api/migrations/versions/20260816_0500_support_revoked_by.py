"""Record who ended a support session, not just when.

`revoked_at` was stored and `revoked_by` was not, so the customer-visible record
could say a session ended early without saying who ended it. The interface then
rendered the *approver's* name beside "Ended early", because that was the only
name on the row — attributing the ending to whoever had allowed it.

That is the specific misattribution the support model exists to prevent: the
record is the customer's evidence of what CAIRN did and what their own
colleagues decided, and a name in the wrong place is worse than no name.

Nullable, because every session that already exists was revoked before this
column did. A backfilled guess would be exactly the invention this is fixing.

Revision ID: b1e6c4a92f37
Revises: a4c72e19d8f5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1e6c4a92f37"
down_revision: str | None = "a4c72e19d8f5"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "support_sessions",
        sa.Column(
            "revoked_by_user_id",
            postgresql.UUID(as_uuid=True),
            # RESTRICT for the same reason as the requester and the decider: a
            # person who ended somebody's access is part of the record, and an
            # account deletion must not quietly erase that.
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("support_sessions", "revoked_by_user_id")
