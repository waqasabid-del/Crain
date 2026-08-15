"""What a fact was about, and how the feed finds it.

Two additions, both in service of Step 24's exit criterion — *filter by person,
project, source and date; search returns grounded results*.

**``fact_sources.project`` — the project belongs to the evidence, not to the
statement.** A fact reconciled from a pull request in ``acme/payments`` and a
meeting that mentioned it belongs to both, and the row that knows which is the
citation rather than the fact. Putting a single ``project`` column on ``facts``
would have forced a choice between them, and the choice would have been made by
whichever source happened to be extracted first.

Nullable, and expected to be null often: chat and meeting evidence frequently has
no project at all. A filter therefore means "evidence that names this project",
never "everything that could plausibly relate to it" — the honest reading, and
the one a reader can check by opening the citation.

**A full-text index on ``facts.statement``.** Search runs lexically first, and a
sequential scan per keystroke is the version that works in development and falls
over on the first workspace with real history. English is the configuration
because it is what the statements are written in; a workspace writing in another
language gets a degraded but working stemmer, which is the same trade every
product makes before it has a language column to consult.

Revision ID: c5d47a1e83b9
Revises: a3f0d81b6c42
"""

# DDL. No value here originates from user input.

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c5d47a1e83b9"
down_revision: str | None = "a3f0d81b6c42"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("fact_sources", sa.Column("project", sa.String(length=200), nullable=True))

    # The query the feed runs: this workspace's evidence for one project. The
    # partial clause keeps the index off the many rows with no project, which
    # are never a filter's answer.
    op.create_index(
        "ix_fact_sources_tenant_project",
        "fact_sources",
        ["tenant_id", "project"],
        postgresql_where=sa.text("project IS NOT NULL"),
    )

    op.execute(
        "CREATE INDEX ix_facts_statement_fts ON facts USING GIN (to_tsvector('english', statement))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_facts_statement_fts")
    op.drop_index("ix_fact_sources_tenant_project", table_name="fact_sources")
    op.drop_column("fact_sources", "project")
