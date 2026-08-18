"""Admit `understood` to the transcript artifact's state check.

Revision ID: 8f2a6d91c340
Revises: 7c4d2f81ab60
Create Date: 2026-08-19

Step 36 stored transcripts and deliberately never read them; the reading path
now exists (`gmeet/understanding.py`), and `understood` is the state that says a
transcript's bytes were sent to the model exactly once, under a consent permit
re-checked at the moment of reading.

The CHECK is widened by drop-and-recreate rather than edited: PostgreSQL has no
ALTER for a check constraint's expression, and the recreate names every value so
the constraint stays the single authoritative list. The downgrade refuses if any
row already holds the new state — reverting a schema must not silently invalidate
rows, and an `understood` transcript demoted to `stored` would be re-read and
re-billed on the next maintenance pass, which is the exact double-read the state
exists to prevent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "8f2a6d91c340"
down_revision = "7c4d2f81ab60"
branch_labels = None
depends_on = None

_TABLE = "google_meet_transcript_artifacts"
_NAME = "state"

_OLD = ("announced", "retrieving", "stored", "refused", "failed", "dead_lettered", "retired")
_NEW = (*_OLD, "understood")


def _recreate(values: tuple[str, ...]) -> None:
    # Raw SQL both ways: alembic's naming convention re-wraps the constraint
    # name on drop, producing a name that does not exist.
    quoted = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT ck_{_TABLE}_{_NAME}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT ck_{_TABLE}_{_NAME} CHECK (state IN ({quoted}))"
    )


def upgrade() -> None:
    _recreate(_NEW)


def downgrade() -> None:
    # Refuse rather than orphan: a row in the new state has been billed for a
    # model read, and demoting it schedules a second one.
    connection = op.get_bind()
    holding = connection.execute(
        # S608: _TABLE is a module constant, not input.
        sa.text(f"SELECT count(*) FROM {_TABLE} WHERE state = 'understood'")  # noqa: S608
    ).scalar_one()
    if holding:
        msg = (
            f"{holding} transcript artifact(s) are in state 'understood'. "
            "Re-classify or delete them deliberately before downgrading; a "
            "silent demotion to 'stored' would re-read and re-bill each one."
        )
        raise RuntimeError(msg)
    _recreate(_OLD)
