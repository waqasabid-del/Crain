"""What a person does, so CAIRN can open on something useful to them.

md/08 §A: five roles use the same data through different lenses, and md/11 §6
gives each of them a different first screen. A developer opens on their own
contribution record; a designer on theirs with discussion and reviews weighted
equally with commits; a product manager on a live initiative across sources;
marketing and operations on the plain-English brief.

**This is not a permission and must never become one.** `memberships.role` —
Owner, Admin, Member, Viewer — decides what somebody may *configure*. This column
decides only what CAIRN *opens on* and how their own record is framed. Every
person sees exactly the same facts either way, which is the symmetry commitment
(md/05 §B.2, md/15 §2.2) and is asserted by a test rather than left to habit.

**Nullable, and it stays nullable.** "I would rather not say" is a legitimate
answer to a question about what somebody does, and the default view has to work
for the person who never answers it. A `NOT NULL` with a default would turn a
skipped question into a claim about them that they did not make.

**Set by the person themselves, never by an administrator.** There is no endpoint
that writes this column for anybody else. An admin-assigned work role would be a
management classification stored on a colleague's record, in a product whose
entire position is that it does not do that.

Revision ID: e4b78c2af913
Revises: c5d47a1e83b9
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e4b78c2af913"
down_revision: str | None = "c5d47a1e83b9"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("memberships", sa.Column("work_role", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("memberships", "work_role")
