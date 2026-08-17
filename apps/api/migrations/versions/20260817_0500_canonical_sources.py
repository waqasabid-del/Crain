"""One source vocabulary, and the `chat` opt-outs migrated rather than reinterpreted.

`source_opt_outs.source` held `github` / `chat` / `meeting` / `document`, while
`fact_sources.source` held `github` / `slack` / `google_chat`. Opt-out is enforced
by intersecting those two sets at attribution time, and `{"chat"} & {"slack"}` is
empty — so **every Slack and Google Chat opt-out silently did nothing** while the
toggle, the stored row and every screen reported it as honoured.

Code alone cannot fix that. The rows already in the table say `chat`, and a
deployment that ships the new vocabulary without touching them would leave those
people opted out of a source name that no longer exists — the same silent
over-collection, now with the bug moved into the data.

**A `chat` refusal expands to both products, and that direction is deliberate.**
The person was offered one control named "Chat" covering Slack and Google Chat,
and they refused it. Expanding to both honours what they were told they were
doing. The alternatives are worse in a way that matters: picking one product
would resume reading the other without asking, and deleting the row would resume
reading both. When a migration has to interpret a consent decision, it must
resolve toward collecting less.

`ON CONFLICT DO NOTHING` because a person may already hold an explicit `slack` or
`google_chat` row; the unique constraint is `(person_id, source)`.

**The downgrade collapses them back to a single `chat` row.** It is lossy — a
person who later refused only Slack comes back as having refused both — and lossy
in the safe direction, for the same reason.

Revision: 7d21e5b8c093, on b3f7c21a9e64.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "7d21e5b8c093"
down_revision: str | None = "b3f7c21a9e64"
branch_labels: str | None = None
depends_on: str | None = None

#: Restated, not imported. A migration describes the schema and the vocabulary as
#: they were at this revision; importing `cairn_api.sources` would make this file
#: change meaning the next time somebody edits that module.
LEGACY = "chat"
REPLACEMENTS = ("slack", "google_chat")


def upgrade() -> None:
    for replacement in REPLACEMENTS:
        op.execute(
            sa.text("""
                INSERT INTO source_opt_outs (tenant_id, person_id, source)
                SELECT tenant_id, person_id, :replacement
                FROM source_opt_outs
                WHERE source = :legacy
                ON CONFLICT ON CONSTRAINT uq_source_opt_outs_person_source DO NOTHING
            """).bindparams(replacement=replacement, legacy=LEGACY)
        )

    # Only after both replacements exist. Deleting first would leave a window in
    # which the person is opted out of nothing at all, and this runs in one
    # transaction with a worker that may be attributing concurrently.
    op.execute(
        sa.text("DELETE FROM source_opt_outs WHERE source = :legacy").bindparams(legacy=LEGACY)
    )


def downgrade() -> None:
    op.execute(
        sa.text("""
            INSERT INTO source_opt_outs (tenant_id, person_id, source)
            SELECT DISTINCT tenant_id, person_id, :legacy
            FROM source_opt_outs
            WHERE source = ANY(:replacements)
            ON CONFLICT ON CONSTRAINT uq_source_opt_outs_person_source DO NOTHING
        """).bindparams(legacy=LEGACY, replacements=list(REPLACEMENTS))
    )
    op.execute(
        sa.text("DELETE FROM source_opt_outs WHERE source = ANY(:replacements)").bindparams(
            replacements=list(REPLACEMENTS)
        )
    )
