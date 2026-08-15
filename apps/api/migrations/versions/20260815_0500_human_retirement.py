"""A person can retire a fact without replacing it.

``ck_facts_supersession_is_complete`` required ``valid_until`` and
``superseded_by_id`` to be set together. That rule was right for the case it was
written for: a machine closing a fact's validity with no successor is a fact
that silently vanishes from every brief with nothing to explain the absence.

**Human correction is the case it was not written for.** md/09 §9 makes
correction an *input* rather than a UI affordance, and the most common correction
is "this did not happen" — which has no replacement by definition. Under the old
constraint the only ways to express it were to invent a successor sentence
nobody wrote, or to leave the denied fact valid and watch it reappear in
tomorrow's brief. Both are worse than relaxing the rule.

The rule is therefore narrowed rather than dropped: a closed validity window
still needs a successor **unless** the row is marked ``origin = 'correction'``,
which is only ever set by a person and always alongside
``corrected_by_user_id``. The original property survives — nothing disappears
silently, because every retirement without a successor names the human who asked
for it.

Revision ID: f8c25d13a704
Revises: e7b41c92f5d8
"""

from __future__ import annotations

from alembic import op

revision: str = "f8c25d13a704"
down_revision: str | None = "e7b41c92f5d8"
branch_labels: None = None
depends_on: None = None

OLD = "(valid_until IS NULL) = (superseded_by_id IS NULL)"
NEW = (
    "(valid_until IS NULL AND superseded_by_id IS NULL) "
    "OR superseded_by_id IS NOT NULL "
    "OR (origin = 'correction' AND corrected_by_user_id IS NOT NULL)"
)


def upgrade() -> None:
    # Named without the `ck_facts_` prefix: the metadata naming convention adds
    # it, and passing the full name produces `ck_facts_ck_facts_…`.
    op.drop_constraint("supersession_is_complete", "facts", type_="check")
    op.create_check_constraint("supersession_is_complete", "facts", NEW)


def downgrade() -> None:
    # Any row the new rule allowed and the old one forbids has to go back to
    # being expressible, so this fails loudly rather than silently dropping the
    # retirements. There is no correct automatic answer: inventing a successor
    # would fabricate a sentence, and clearing `valid_until` would republish a
    # fact a person denied.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM facts
                WHERE valid_until IS NOT NULL AND superseded_by_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Facts retired by a person without a successor exist. '
                    'Downgrading would either republish a denied fact or '
                    'require inventing a replacement. Resolve them first.';
            END IF;
        END $$;
    """)
    # Named without the `ck_facts_` prefix: the metadata naming convention adds
    # it, and passing the full name produces `ck_facts_ck_facts_…`.
    op.drop_constraint("supersession_is_complete", "facts", type_="check")
    op.create_check_constraint("supersession_is_complete", "facts", OLD)
