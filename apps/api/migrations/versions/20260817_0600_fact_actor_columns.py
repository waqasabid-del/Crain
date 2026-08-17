"""Provider account ids out of `fact_people.mention` and into structured columns.

The actor a provider names was briefly encoded into `fact_people.mention` as
`provider-actor:{provider}:{account_id}`. That column is **not internal**, and
the audit that established it is the reason this migration exists:

- `FactPersonResponse.mention` is a required field of the public OpenAPI
  document (`apps/api/src/cairn_api/api/schemas.py`), so every consumer of the
  facts API receives it.
- `apps/web/src/routes/FeedPage.tsx` maps it straight onto `credits`, the line
  that names who a fact concerns. A sentinel would have been rendered to every
  member of the workspace as the literal text
  `provider-actor:slack:U0ALICE99`.
- `brief/adapter.ts` uses the mention as both the id and the display name of a
  person facet, so it would also have become a filter label.

A Slack member id is a private provider identifier. Publishing one to every
colleague in the workspace, as a person's name, is a disclosure — and it would
have been introduced by a change whose entire purpose was to attribute work more
carefully.

**So the two things are separated by shape rather than by discipline.**
`mention` keeps its one meaning: human-readable text somebody may recognise and
correct. `provider` and `provider_account_id` carry the machine identity, are
never serialised, and cannot be rendered by a component that receives the row,
because the row a component receives no longer contains them.

`mention` becomes nullable and a CHECK requires **exactly one** of the two
shapes. A row is either a name a model wrote or an account a provider named, and
never both — a row that was both would be a name with an account's authority.

The unique constraint splits to match: `(fact_id, mention)` where a mention
exists, `(fact_id, provider, provider_account_id)` where an account does. Both
stay unique, so re-processing one delivery cannot accumulate duplicate rows.

Existing sentinel rows are converted in place rather than deleted, and the
downgrade rebuilds them, so the change is reversible in both directions.

Revision: 9c4a1f602e7b, on 7d21e5b8c093.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "9c4a1f602e7b"
down_revision: str | None = "7d21e5b8c093"
branch_labels: str | None = None
depends_on: str | None = None

#: Restated, not imported: a migration describes the vocabulary as it was here.
PROVIDER_VALUES = ("github", "slack", "google_chat")

#: The same set as a SQL literal, for the CHECK constraint, which cannot take a
#: bind parameter. Built from the tuple above so the two cannot disagree.
PROVIDERS = "(" + ", ".join(f"'{value}'" for value in PROVIDER_VALUES) + ")"

#: The sentinel this migration exists to retire.
PREFIX = "provider-actor:"


def upgrade() -> None:
    op.add_column("fact_people", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column(
        "fact_people", sa.Column("provider_account_id", sa.String(length=255), nullable=True)
    )
    op.alter_column("fact_people", "mention", existing_type=sa.String(length=255), nullable=True)

    # Convert before constraining: the CHECK below would reject these rows.
    #
    # Fully parameterised — no value is interpolated into the statement text.
    # The inputs here are module constants rather than anything a caller
    # supplies, but a migration that builds SQL by concatenation is a pattern the
    # next author copies into one that does take input.
    #
    # `right(...)` rather than a regex: the sentinel is
    # `provider:{provider}:{account_id}` and an account id may itself contain a
    # colon, so the account is everything after the *first* colon of the
    # remainder rather than a fixed field.
    op.execute(
        sa.text("""
            WITH stripped AS (
                SELECT id, right(mention, length(mention) - length(:prefix)) AS rest
                FROM fact_people
                WHERE mention LIKE :pattern
            )
            UPDATE fact_people AS f
            SET provider = split_part(s.rest, ':', 1),
                provider_account_id = right(s.rest, length(s.rest) - position(':' in s.rest)),
                mention = NULL
            FROM stripped AS s
            WHERE f.id = s.id
        """).bindparams(prefix=PREFIX, pattern=f"{PREFIX}%")
    )

    # Anything that did not parse into both halves is not a sentinel this
    # migration understands. Failing loudly beats leaving a half-converted row
    # that the CHECK would then reject at the next write.
    op.execute(
        sa.text("""
            DELETE FROM fact_people
            WHERE mention IS NULL
              AND (
                  provider IS NULL
                  OR provider_account_id IS NULL
                  OR provider <> ALL(:providers)
              )
        """).bindparams(providers=list(PROVIDER_VALUES))
    )

    op.drop_constraint("uq_fact_people_fact_mention", "fact_people", type_="unique")
    op.create_index(
        "uq_fact_people_fact_mention",
        "fact_people",
        ["fact_id", "mention"],
        unique=True,
        postgresql_where=sa.text("mention IS NOT NULL"),
    )
    op.create_index(
        "uq_fact_people_fact_actor",
        "fact_people",
        ["fact_id", "provider", "provider_account_id"],
        unique=True,
        postgresql_where=sa.text("provider_account_id IS NOT NULL"),
    )

    op.create_check_constraint(
        "ck_fact_people_one_shape",
        "fact_people",
        "(mention IS NOT NULL AND provider IS NULL AND provider_account_id IS NULL)"
        " OR (mention IS NULL AND provider IS NOT NULL AND provider_account_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_fact_people_provider",
        "fact_people",
        f"provider IS NULL OR provider IN {PROVIDERS}",
    )

    # Reconciliation looks facts up by the account that produced them, tenant
    # first because every such query is scoped.
    op.create_index(
        "ix_fact_people_actor_lookup",
        "fact_people",
        ["tenant_id", "provider", "provider_account_id"],
        postgresql_where=sa.text("provider_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_fact_people_actor_lookup", table_name="fact_people")
    op.drop_constraint("ck_fact_people_provider", "fact_people", type_="check")
    op.drop_constraint("ck_fact_people_one_shape", "fact_people", type_="check")

    # Rebuild the sentinel so the column is populated before it is made NOT NULL.
    op.execute(
        sa.text("""
            UPDATE fact_people
            SET mention = :prefix || provider || ':' || provider_account_id,
                provider = NULL,
                provider_account_id = NULL
            WHERE provider_account_id IS NOT NULL
        """).bindparams(prefix=PREFIX)
    )

    op.drop_index("uq_fact_people_fact_actor", table_name="fact_people")
    op.drop_index("uq_fact_people_fact_mention", table_name="fact_people")
    op.create_unique_constraint(
        "uq_fact_people_fact_mention", "fact_people", ["fact_id", "mention"]
    )

    op.alter_column("fact_people", "mention", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("fact_people", "provider_account_id")
    op.drop_column("fact_people", "provider")
