"""Google Meet transcript retrieval: a second grant, provenance, and a store nothing may read.

Three new tables, one new column, and the reason each of them is separate from
something that already exists.

**`google_meet_transcript_grants` is not a second row in `source_connections`.**
``drive.meet.readonly`` is a RESTRICTED OAuth scope and its own consent action.
Recording it as an extra entry in ``source_connections.scopes`` would make
"connected Google Meet" and "may read our transcripts" the same fact in the
database, which is exactly the conflation the product promises not to make. A
workspace can hold a Meet connection with no row here — that is the normal state
— and revoking transcript access sets ``revoked_at`` without touching the
connection, the subscriptions, or anything already collected.

**`google_meet_transcript_artifacts` holds an encrypted reference, and Step 36A's
`google_meet_artifact_signals` still holds none.** The announcement table keeps
its shape: a digest, and nothing that could be used to fetch anything. Retrieval
needs a name — a download requires one, a retry requires it again — so the name
lives here, encrypted with the connector key, beside the digest that every
recognition query uses instead. The signal table's promise is unchanged; this
table is where the new capability is, in the open, with its own grants.

**`google_meet_transcript_raw` is a separate table so that deletion is possible.**
Retention ends and these rows go; the provenance beside them stays, so a workspace
can be told that a transcript existed, was collected, and has since been deleted.
A content column on the artifact row would force the same deletion to erase the
record of the collection. It also has **no GRANT at all** — the strongest posture
in this schema, and the right one for a verbatim record of what people said in a
meeting: every write is platform-side, and no product surface reads it.

Revision ID: 7c4d2f81ab60
Revises: 5b1a7c3e9d40
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7c4d2f81ab60"
down_revision: str | None = "5b1a7c3e9d40"
branch_labels: None = None
depends_on: None = None

#: Restated, not imported — the decision `20260817_0200_slack_channels.py`
#: records: a migration must describe the schema as it was at this revision, and
#: an import silently rewrites history when the model changes.
TENANT_SETTING = "app.current_tenant_id"

#: Which grant an in-flight install is for. Two values, and the default is the
#: narrow one: a state whose kind was somehow lost must not be redeemable as
#: transcript access.
GRANT_KINDS = "('connection', 'transcript')"

#: The transcript lifecycle, as a SQL literal. Mirrors
#: `GoogleMeetTranscriptState`.
TRANSCRIPT_STATES = (
    "('announced', 'retrieving', 'stored', 'refused', 'failed', 'dead_lettered', 'retired')"
)

#: The refusal vocabulary, as a SQL literal. Mirrors `GoogleMeetRefusalReason`.
#: Written out rather than generated so that widening it is a visible edit here
#: as well as in Python.
REFUSAL_REASONS = (
    "('consent_not_current', 'opted_out', 'identity_revoked', 'scope_not_granted', "
    "'connection_inactive', 'reference_mismatch', 'not_a_transcript', 'too_large', "
    "'checksum_mismatch', 'artifact_gone', 'artifact_changed')"
)

#: The bounded error vocabulary, matching `ConnectorErrorCategory`.
ERROR_CATEGORIES = (
    "('authentication_expired', 'permission_revoked', 'rate_limited', "
    "'provider_unavailable', 'configuration_invalid', 'unknown')"
)


def _tenant_policy(table: str) -> None:
    """Row-level security, enabled and forced, with the standard policy.

    FORCE as well as ENABLE, because a policy that the table owner bypasses is a
    policy that is inert in exactly the session that does the most damage.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)


def upgrade() -> None:
    # -- Which grant an install is for --------------------------------------
    #
    # Google registers one redirect URI per OAuth client, so both consent actions
    # come back through the same callback. Without this column the callback would
    # have to infer what the person agreed to from the `scope` parameter Google
    # sends back — deciding what was consented to by reading what was granted,
    # which is exactly backwards.
    op.add_column(
        "google_meet_oauth_states",
        sa.Column(
            "requested_grant",
            sa.String(length=16),
            nullable=False,
            server_default="connection",
        ),
    )
    op.create_check_constraint(
        "requested_grant",
        "google_meet_oauth_states",
        f"requested_grant IN {GRANT_KINDS}",
    )

    # -- The second, separate consent ---------------------------------------
    op.create_table(
        "google_meet_transcript_grants",
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
        # CASCADE: a grant outliving the connection it was authorised on is
        # consent attached to no credential, and the next connection would
        # inherit it.
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT rather than SET NULL: a grant with nobody's name on it is a
        # grant nobody can be asked about.
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("granted_scopes", postgresql.JSONB(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        # Marked, never deleted: "transcript access was held between these dates"
        # is what somebody asks after finding a stored transcript.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        # The grant's own refresh token, encrypted. Not the connection's:
        # transcript access is authorised on a separate OAuth client, so it is a
        # different credential with a different scope set — which is what makes
        # revoking transcript access revoke something rather than set a flag
        # beside a token that still works.
        sa.Column("secret_ciphertext", sa.String(length=2048), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # One row per connection outright. Two would be two answers to one
        # question, and the code would read whichever the query ordered first.
        sa.UniqueConstraint("connection_id", name="uq_google_meet_transcript_grants_connection"),
    )
    op.create_index(
        "ix_google_meet_transcript_grants_tenant_id",
        "google_meet_transcript_grants",
        ["tenant_id"],
    )
    _tenant_policy("google_meet_transcript_grants")

    # SELECT only. The grant is written by the OAuth callback, which runs
    # platform-side because the redirect URI names no workspace — so an INSERT
    # grant would be an unused privilege, and the one it would enable is a scoped
    # session granting itself restricted-scope artifact access. UPDATE would let
    # it clear `revoked_at` and undo a withdrawal, which is precisely the
    # privilege an injection reaches for first.
    op.execute("GRANT SELECT ON google_meet_transcript_grants TO cairn_app")

    # -- Provenance and lifecycle -------------------------------------------
    op.create_table(
        "google_meet_transcript_artifacts",
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
            "signal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("google_meet_artifact_signals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("google_meet_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Provenance that has to be inferred from which table a row is in stops
        # being provenance the moment a second provider arrives.
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("conference_digest", sa.String(length=64), nullable=False),
        # The resource name, encrypted with the connector key. The only reversible
        # provider identifier in this connector's schema, and it exists because a
        # download requires a name and a retry requires it again.
        sa.Column("artifact_reference_ciphertext", sa.Text(), nullable=False),
        # The source timestamp reference: when the platform produced it. Nullable,
        # because Google does not always say and a fabricated time is worse than
        # an absent one.
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        # Copied rather than joined: a policy version pins what somebody agreed
        # to, and a join would report today's.
        sa.Column("consent_policy_version", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="announced"),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refusal_reason", sa.String(length=32), nullable=True),
        sa.Column("error_category", sa.String(length=32), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("content_bytes", sa.Integer(), nullable=True),
        sa.Column("content_checksum", sa.String(length=64), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # One artifact per announcement, so a redelivery cannot produce a second
        # download.
        sa.UniqueConstraint("signal_id", name="uq_google_meet_transcript_artifacts_signal"),
        # And one per artifact per workspace. Tenant-scoped rather than global for
        # the reason the signal table's constraint is: a global one would let one
        # workspace's row silently suppress another's.
        sa.UniqueConstraint(
            "tenant_id", "artifact_digest", name="uq_google_meet_transcript_artifacts_digest"
        ),
        # The constraint that makes "transcripts only" a property of the data
        # rather than of the code. There is no value this column may hold that
        # names a recording, audio, video or smart notes.
        sa.CheckConstraint("kind = 'transcript'", name="kind_is_transcript"),
        sa.CheckConstraint("provider = 'google_meet'", name="provider_is_meet"),
        sa.CheckConstraint(f"state IN {TRANSCRIPT_STATES}", name="state"),
        sa.CheckConstraint(
            f"refusal_reason IS NULL OR refusal_reason IN {REFUSAL_REASONS}",
            name="refusal_reason",
        ),
        sa.CheckConstraint(
            f"error_category IS NULL OR error_category IN {ERROR_CATEGORIES}",
            name="error_category",
        ),
        # 64 hex characters and nothing else, so a future caller that "just stored
        # the name" fails at the database rather than writing a conference record
        # id into a column called `digest`.
        sa.CheckConstraint(
            "artifact_digest ~ '^[0-9a-f]{64}$'",
            name="artifact_digest_shape",
        ),
        sa.CheckConstraint(
            "conference_digest ~ '^[0-9a-f]{64}$'",
            name="conference_digest_shape",
        ),
        sa.CheckConstraint(
            "content_checksum IS NULL OR content_checksum ~ '^[0-9a-f]{64}$'",
            name="content_checksum_shape",
        ),
        sa.CheckConstraint(
            "content_bytes IS NULL OR content_bytes >= 0",
            name="content_bytes_non_negative",
        ),
    )
    op.create_index(
        "ix_google_meet_transcript_artifacts_tenant_id",
        "google_meet_transcript_artifacts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_google_meet_transcript_artifacts_meeting",
        "google_meet_transcript_artifacts",
        ["meeting_id"],
    )
    # The retrieval pass: "what is waiting, and what is retryable now".
    op.create_index(
        "ix_google_meet_transcript_artifacts_state_next_attempt",
        "google_meet_transcript_artifacts",
        ["state", "next_attempt_at"],
    )
    # The retention sweep.
    op.create_index(
        "ix_google_meet_transcript_artifacts_retention",
        "google_meet_transcript_artifacts",
        ["retention_expires_at", "raw_purged_at"],
    )
    _tenant_policy("google_meet_transcript_artifacts")

    # SELECT only, matching every other Meet table. The retrieval worker resolves
    # a subscription to a workspace before any tenant context exists, so every
    # write is platform-side. INSERT would let a scoped session fabricate the
    # record that a meeting produced a transcript; UPDATE would let it clear
    # `withdrawn_at` or `refusal_reason` and walk back a refusal.
    op.execute("GRANT SELECT ON google_meet_transcript_artifacts TO cairn_app")

    # -- The transcript itself ----------------------------------------------
    op.create_table(
        "google_meet_transcript_raw",
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
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("google_meet_transcript_artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Fernet ciphertext, under the same key every stored credential uses, so a
        # deployed environment with no key refuses to start rather than writing
        # transcripts in the clear.
        sa.Column("content_ciphertext", sa.Text(), nullable=False),
        sa.Column("content_checksum", sa.String(length=64), nullable=False),
        sa.Column("content_bytes", sa.Integer(), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("artifact_id", name="uq_google_meet_transcript_raw_artifact"),
        sa.CheckConstraint(
            "content_checksum ~ '^[0-9a-f]{64}$'",
            name="checksum_shape",
        ),
    )
    op.create_index(
        "ix_google_meet_transcript_raw_tenant_id", "google_meet_transcript_raw", ["tenant_id"]
    )
    _tenant_policy("google_meet_transcript_raw")

    # **No GRANT at all**, deliberately, and asserted by `test_tenant_isolation.py`
    # rather than left as an absence a reader has to notice. Row-level security is
    # still enabled and forced — the grant is the outer door, the policy the inner
    # one — but nothing in the application role's world may open either. Every
    # write is platform-side, and there is no product surface that reads a
    # transcript: at this step customers see availability and status, never
    # content.


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_meet_transcript_raw")
    op.drop_table("google_meet_transcript_raw")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_meet_transcript_artifacts")
    op.drop_table("google_meet_transcript_artifacts")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_meet_transcript_grants")
    op.drop_table("google_meet_transcript_grants")

    # The physical name carries the naming convention's doubling — see
    # `20260818_0200_google_meet.py`, which records why a constraint declared as
    # `ck_x_y` is created as `ck_x_ck_x_y`.
    op.execute(
        "ALTER TABLE google_meet_oauth_states DROP CONSTRAINT IF EXISTS "
        "ck_google_meet_oauth_states_ck_google_meet_oauth_states_requested_grant"
    )
    op.drop_column("google_meet_oauth_states", "requested_grant")
