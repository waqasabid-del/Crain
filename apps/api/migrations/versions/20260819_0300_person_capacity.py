"""Self-declared capacity on the person record.

Revision ID: 6b3e8a92f1d4
Revises: 8f2a6d91c340
Create Date: 2026-08-19

Two columns and no history table, and the absence is the design: a capacity
timeline is a monitoring log wearing a scarf. Current state plus when the
person themselves stated it — nothing else exists to query, so nothing can be
trended, compared, or reviewed later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "6b3e8a92f1d4"
down_revision = "8f2a6d91c340"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "people",
        sa.Column(
            "capacity",
            sa.String(length=16),
            nullable=False,
            server_default="not_stated",
        ),
    )
    op.add_column(
        "people",
        sa.Column("capacity_stated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "ALTER TABLE people ADD CONSTRAINT ck_people_capacity "
        "CHECK (capacity IN ('open_to_work', 'at_capacity', 'not_stated'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE people DROP CONSTRAINT ck_people_capacity")
    op.drop_column("people", "capacity_stated_at")
    op.drop_column("people", "capacity")
