"""Cross-source identity: one provider account, one person, on checkable evidence.

Adds `external_identities`, the table that decides whose activity a GitHub, Slack
or Google Chat event belongs to. The design notes live in
`db/external_identity_models.py`; what follows is what this migration decides,
because a schema decision is only reviewable where it is made.

**Two enums, both closed and both deliberately small.** `identity_verification`
has exactly two members — a provider-verified email that matched a CAIRN-verified
email, and a person's own authenticated confirmation. There is no `suggested`,
`inferred` or `probable` member, and adding one would be a migration somebody has
to write and defend. That is the intended cost: the product's promise is that
CAIRN never guesses who somebody is, and a promise enforced by a CHECK constraint
outlives the person who made it.

**`provider` is a checked string, not a Postgres enum**, because that is what
`source_connections` already is. Two spellings of one concept surface as rows
that will not join, which is a worse error than the one a CHECK constraint gives.
The vocabulary is restated below rather than imported, following
`20260817_0200_slack_channels.py`: a migration must describe the schema as it was
at this revision, and an import silently rewrites history when the model changes.

**This migration also makes `people.user_id` unique.** It was not, and nothing
noticed because only GitHub ever created people. `me.py::_person_for` resolves the
caller with `select(Person).where(Person.user_id == ...)` and no `LIMIT` — so a
second `Person` row for the same human makes My Week, the correction gate and the
opt-out surface bind to an arbitrary one of them. Attributing Slack and Chat
accounts is exactly what would have produced that second row, so the constraint
lands in the same change that creates the risk. Partial, because `user_id` is
null for everyone who has never signed in, and those are the majority.

**The unique index is partial, and that is the whole integrity story.** Unique on
`(tenant_id, provider, provider_account_id)` *where* `state = 'active'`:

- Two people cannot hold the same provider account at once. The second confirm
  fails in the database, not in a handler — which matters because the case that
  breaks a handler is two confirms racing, and that race is decided by the index.
- An account can still change hands, but only after the first link is revoked,
  which leaves a row, a timestamp and a reason behind. There is no path from one
  owner to another that erases the first.
- Revoked and disputed rows stay outside the index, so history accumulates
  instead of being overwritten. Nothing here is ever `DELETE`d by the
  application, which is why no DELETE grant is issued below.

**Grants: SELECT, INSERT, UPDATE — and no DELETE.** Confirming inserts; revoking
and disputing update `state`. Deleting would destroy the evidence that a link
ever existed, which is exactly what a person examining their own record needs to
see, and exactly what an attacker who has just claimed somebody's account would
want gone. `test_tenant_isolation.py` asserts this set explicitly, so widening it
fails a test rather than passing review.

Revision: b3f7c21a9e64, on c5a92f7e4d18 (Google Chat).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

#: Restated, not imported — the same decision `20260817_0200_slack_channels.py`
#: records: a migration must describe the schema as it was at this revision, and
#: an import makes an old migration change meaning when the model changes.
TENANT_SETTING = "app.current_tenant_id"

#: The provider vocabulary as it stands at this revision, restated for the same
#: reason. `source_connections` carries the identical CHECK; the two are meant to
#: agree, and if a provider is ever added, both are meant to be edited.
PROVIDERS = "('github', 'slack', 'google_chat')"

revision: str = "b3f7c21a9e64"
down_revision: str | None = "c5a92f7e4d18"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    identity_verification = postgresql.ENUM(
        "verified_email_match",
        "self_confirmed",
        name="identity_verification",
        create_type=False,
    )
    identity_link_state = postgresql.ENUM(
        "active",
        "revoked",
        "disputed",
        name="identity_link_state",
        create_type=False,
    )
    identity_verification.create(op.get_bind(), checkfirst=True)
    identity_link_state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "external_identities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "person_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("people.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        # The provider's stable id, never a handle or a display name: both are
        # renameable, and a link keyed on a renameable string is silently
        # granted or revoked by a rename somebody else performs.
        sa.Column("provider_account_id", sa.String(length=255), nullable=False),
        # Kept only where it was the evidence. Null on every self-confirmed row —
        # storing an address that proved nothing would collect a personal
        # identifier for no purpose and would read as evidence to the next person
        # who opens this table.
        sa.Column("provider_email", sa.String(length=320), nullable=True),
        sa.Column("verification", identity_verification, nullable=False),
        sa.Column("state", identity_link_state, nullable=False, server_default="active"),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        # SET NULL rather than RESTRICT: a person leaving must not be blocked by
        # a link they created, and the row's history stays readable without them.
        sa.Column(
            "linked_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=200), nullable=True),
        sa.Column(
            "revoked_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # A verified-email link must carry the address that was the evidence, and
        # a self-confirmed link must not. Asserted in the schema because this is
        # the difference between "the provider proved it" and "the person said
        # so", and a row that blurs the two cannot be explained to its subject.
        sa.CheckConstraint(
            "(verification = 'verified_email_match' AND provider_email IS NOT NULL)"
            " OR (verification = 'self_confirmed' AND provider_email IS NULL)",
            name="ck_external_identities_evidence_matches_method",
        ),
        # A row that is not active must say when it stopped. Without this, a
        # revoked link and a live one are distinguishable only by a column
        # somebody remembered to set.
        sa.CheckConstraint(
            "(state = 'active' AND revoked_at IS NULL)"
            " OR (state <> 'active' AND revoked_at IS NOT NULL)",
            name="ck_external_identities_revocation_is_dated",
        ),
        sa.CheckConstraint(f"provider IN {PROVIDERS}", name="ck_external_identities_provider"),
    )

    op.create_index(
        "uq_external_identities_live_account",
        "external_identities",
        ["tenant_id", "provider", "provider_account_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index("ix_external_identities_person_id", "external_identities", ["person_id"])
    op.create_index("ix_external_identities_tenant_id", "external_identities", ["tenant_id"])

    op.execute("ALTER TABLE external_identities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE external_identities FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON external_identities
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # No DELETE: revoking updates `state` and keeps the evidence. The privilege
    # that could erase the record of a link is the one an injection reaches for
    # first, and it is the record a person needs most when a link was wrong.
    op.execute("GRANT SELECT, INSERT, UPDATE ON external_identities TO cairn_app")

    # One person row per account, per workspace. See the docstring: `_person_for`
    # has no LIMIT, so a duplicate makes record ownership nondeterministic rather
    # than wrong in a way anybody would notice.
    op.create_index(
        "uq_people_tenant_user",
        "people",
        ["tenant_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_people_tenant_user", table_name="people")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON external_identities")
    op.drop_index("uq_external_identities_live_account", table_name="external_identities")
    op.drop_index("ix_external_identities_person_id", table_name="external_identities")
    op.drop_index("ix_external_identities_tenant_id", table_name="external_identities")
    op.drop_table("external_identities")
    # `connector_provider` is not dropped: `source_connections` still uses it.
    op.execute("DROP TYPE IF EXISTS identity_link_state")
    op.execute("DROP TYPE IF EXISTS identity_verification")
