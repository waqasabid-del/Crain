"""Google Meet: the install, one lease per consented meeting, and a signal that says nothing.

Three new tables and **three altered CHECK constraints**, and the second half is
the part that would have been missed.

``google_meet`` is a checked VARCHAR in three places that were written
independently — ``source_connections``, ``external_identities`` and
``fact_people`` — each restating the provider vocabulary as a SQL literal because
a migration must describe the schema as it was at its own revision. Adding
``GOOGLE_MEET`` to the Python enum without touching all three produces a value
the ORM accepts and PostgreSQL rejects at INSERT, with the failure landing in
whichever of the three happens to be written to first.

**`google_meet_oauth_states` has no grant at all**, exactly as
`google_chat_oauth_states` has none. The redirect URI is registered with Google
once and therefore cannot name a workspace, so the callback arrives with no
tenant context to scope a policy to and every statement against it is
platform-side. The row also holds the PKCE ``code_verifier``, which cannot be
hashed — it is a value CAIRN presents to Google rather than one it recognises —
so a scoped session that could read this table could finish an install an admin
started. `test_tenant_isolation.py` asserts the absence rather than leaving it as
something a reader has to notice.

**`google_meet_subscriptions` carries no meeting reference and no joining code.**
For Google Meet, Step 35's ``external_meeting_ref`` *is* the meeting's joining
code, which is a credential — anyone holding it can enter the meeting — and Step
35 already removed it from every response for that reason. It is needed exactly
once, when a subscription is created, and it is read from the consent permit at
that moment. A column here would put a live meeting credential in a database, a
backup, a staff diagnostics screen and a log line to save one join.

**`google_meet_artifact_signals` has nowhere to put an artifact.** It records
that Google announced a transcript file exists: which meeting, which lease, a
digest of the resource name, and when. There is no URI, no file id, no conference
record id, no participant, no duration and no content column. Step 36A subscribes
to the announcement and stops there; a schema that *could* hold the pointer would
make "we did not fetch it" a claim about the code rather than about the data.

Revision ID: 5b1a7c3e9d40
Revises: 4e8b1d90c7a2
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from cairn_api.db.gmeet_models import SUBSCRIPTION_NAME_PATTERN
from sqlalchemy.dialects import postgresql

revision: str = "5b1a7c3e9d40"
down_revision: str | None = "4e8b1d90c7a2"
branch_labels: None = None
depends_on: None = None

#: Restated, not imported — the decision `20260817_0200_slack_channels.py`
#: records: a migration must describe the schema as it was at this revision, and
#: an import silently rewrites history when the model changes.
TENANT_SETTING = "app.current_tenant_id"

#: The provider vocabulary **before** this migration, and after it. Both are
#: written out, because the ``DROP CONSTRAINT`` / ``ADD CONSTRAINT`` pair below
#: has to restore the old one exactly on the way down and a computed difference
#: would be a guess.
PROVIDERS_BEFORE = "('github', 'slack', 'google_chat')"
PROVIDERS_AFTER = "('github', 'slack', 'google_chat', 'google_meet')"

#: The three tables whose ``provider`` column is a checked VARCHAR, with the
#: constraint name and the predicate shape each one uses.
#:
#: A table rather than three hand-written pairs of statements, so a fourth site
#: added later is one row here instead of a fourth place to forget.
_PROVIDER_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("source_connections", "ck_source_connections_provider", "provider IN {values}"),
    ("external_identities", "ck_external_identities_provider", "provider IN {values}"),
    # Nullable here: `fact_people` carries either a `mention` or a provider
    # account, never both, so the provider column is null on half the rows and a
    # bare `IN` would reject them.
    ("fact_people", "ck_fact_people_provider", "provider IS NULL OR provider IN {values}"),
)

#: The subscription lifecycle, as a SQL literal. Mirrors
#: `GoogleMeetSubscriptionState`, and deliberately restated rather than derived
#: from the Chat table's constraint: two connectors with two lifecycles must be
#: able to diverge without one silently widening the other.
SUBSCRIPTION_STATES = "('pending', 'active', 'suspended', 'expired', 'deleted', 'error')"

#: The bounded error vocabulary, matching `ConnectorErrorCategory`.
ERROR_CATEGORIES = (
    "('authentication_expired', 'permission_revoked', 'rate_limited', "
    "'provider_unavailable', 'configuration_invalid', 'unknown')"
)

#: What an artifact signal may be. One value, and the constraint is the point: a
#: second one could only arrive by somebody widening the event tuple in
#: `gmeet/subscriptions.py`, and this makes that a database error rather than a
#: recording.
ARTIFACT_KINDS = "('transcript')"


def _physical(table: str, name: str) -> str:
    """The name PostgreSQL actually holds, which is not the name anyone wrote.

    ``Base.metadata``'s naming convention is ``ck_%(table_name)s_%(constraint_name)s``,
    and SQLAlchemy applies a convention containing ``constraint_name`` to
    **named** check constraints as well as anonymous ones. So a constraint
    declared as ``ck_source_connections_provider`` is created as
    ``ck_source_connections_ck_source_connections_provider``.

    That is invisible until something tries to ``DROP`` one by the name it was
    written under — which is exactly what this migration does — and the failure
    is "constraint does not exist" on a constraint that is plainly there.
    Computed here rather than hardcoded three times so the doubling is stated
    once, with its reason.
    """
    return f"ck_{table}_{name}"


def _retarget_provider_checks(values: str) -> None:
    """Point every provider CHECK at one vocabulary.

    ``DROP`` then ``ADD``, because PostgreSQL has no "widen this CHECK" — and
    because the ``ADD`` validates the existing rows, which is the step that would
    catch a table already holding a value the new list omits.

    The drop is raw SQL against the physical name; the add goes through
    ``create_check_constraint`` so the naming convention regenerates that same
    physical name rather than leaving the two halves to agree by hand.
    """
    for table, name, predicate in _PROVIDER_CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {_physical(table, name)}")
        op.create_check_constraint(name, table, predicate.format(values=values))


def upgrade() -> None:
    # -- The provider vocabulary -------------------------------------------
    _retarget_provider_checks(PROVIDERS_AFTER)

    # -- The in-flight install ---------------------------------------------
    op.create_table(
        "google_meet_oauth_states",
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
            "initiated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # The nonce is stored hashed. A plaintext column would let anyone who can
        # read this table finish an install an administrator started.
        sa.Column("state_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_google_meet_oauth_states_tenant_id", "google_meet_oauth_states", ["tenant_id"]
    )
    # Supports the expiry sweep. Without it, deleting lapsed states is a
    # sequential scan over a table that grows by one row per abandoned install —
    # the shape a scanner can inflate for free.
    op.create_index(
        "ix_google_meet_oauth_states_expires_at", "google_meet_oauth_states", ["expires_at"]
    )

    op.execute("ALTER TABLE google_meet_oauth_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_meet_oauth_states FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON google_meet_oauth_states
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # No GRANT, for the reason in the module docstring. `test_tenant_isolation.py`
    # asserts the table is unreachable from the application role, so a later
    # "just add SELECT" fails a test rather than passing review.

    # -- One lease per consented meeting ------------------------------------
    op.create_table(
        "google_meet_subscriptions",
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
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The **only** meeting identifier on this table, and it is internal. See
        # the module docstring on why there is no `external_meeting_ref` here.
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subscription_name", sa.String(length=160), nullable=True),
        sa.Column("expire_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        # A category from the closed set, never Google's message. Google's errors
        # quote the resource that failed, which here means a meeting space and the
        # authorising person's address.
        sa.Column("error_category", sa.String(length=32), nullable=True),
        # Separate from `updated_at`, which moves on every successful renewal, so
        # "how long has this been broken" stays answerable.
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # One lease per meeting. Two would mean two renewal schedules for one
        # consent decision and, when they disagree, a meeting still subscribed to
        # after the row somebody looked at said it was not.
        sa.UniqueConstraint("meeting_id", name="uq_google_meet_subscriptions_meeting"),
        # Globally unique, not per tenant. An inbound push carries a subscription
        # name and nothing else CAIRN may trust, so this is what makes "which
        # workspace is this for" have exactly one answer.
        sa.UniqueConstraint(
            "subscription_name", name="uq_google_meet_subscriptions_subscription_name"
        ),
        sa.CheckConstraint(
            f"subscription_name IS NULL OR subscription_name ~ '{SUBSCRIPTION_NAME_PATTERN}'",
            name="ck_google_meet_subscriptions_subscription_name_is_a_resource_name",
        ),
        sa.CheckConstraint(
            f"state IN {SUBSCRIPTION_STATES}", name="ck_google_meet_subscriptions_state"
        ),
        sa.CheckConstraint(
            f"error_category IS NULL OR error_category IN {ERROR_CATEGORIES}",
            name="ck_google_meet_subscriptions_error_category",
        ),
    )
    op.create_index(
        "ix_google_meet_subscriptions_tenant_id", "google_meet_subscriptions", ["tenant_id"]
    )
    op.create_index(
        "ix_google_meet_subscriptions_connection_id",
        "google_meet_subscriptions",
        ["connection_id"],
    )
    # The renewal sweep: "which leases lapse soon". State first, because the sweep
    # only ever looks at live ones.
    op.create_index(
        "ix_google_meet_subscriptions_state_expire_time",
        "google_meet_subscriptions",
        ["state", "expire_time"],
    )

    op.execute("ALTER TABLE google_meet_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_meet_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON google_meet_subscriptions
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # SELECT only, matching `google_chat_subscriptions` and for a sharper version
    # of the same reason. A subscription row is not a permission — it is CAIRN's
    # record of a lease it holds at Google — and every write is platform-side:
    # the consent-gated create path and the maintenance sweep, both of which
    # already know the tenant.
    #
    # UPDATE is the dangerous one here. `remove_subscription` marks a row
    # `deleted` *before* it calls Google, which is what makes a withdrawal take
    # effect immediately whether or not Google can be reached; a scoped session
    # that could UPDATE this table could flip that row back to `active` and undo
    # a withdrawal of consent. That is precisely the privilege an injection gets
    # to use first.
    op.execute("GRANT SELECT ON google_meet_subscriptions TO cairn_app")

    # -- The announcement, and nothing else ---------------------------------
    op.create_table(
        "google_meet_artifact_signals",
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
        sa.Column("kind", sa.String(length=16), nullable=False),
        # SHA-256, hex, of the artifact resource name Google named — never the
        # name. A Meet transcript resource name embeds the conference record id,
        # which is a durable handle to one specific meeting; hashing costs
        # nothing and makes this column useless to anybody who obtains it,
        # including us.
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Tenant-scoped rather than global. The digest is derived from a provider
        # identifier, and a global constraint would let one workspace's row
        # silently suppress another's — a cross-tenant side channel for the sake
        # of a narrower index.
        sa.UniqueConstraint(
            "tenant_id", "artifact_digest", name="uq_google_meet_artifact_signals_digest"
        ),
        sa.CheckConstraint(
            f"kind IN {ARTIFACT_KINDS}", name="ck_google_meet_artifact_signals_kind"
        ),
        # 64 hex characters, and nothing else. The constraint exists so that a
        # future caller which "just stored the name" fails at the database rather
        # than writing a conference record id into a column called `digest`.
        sa.CheckConstraint(
            "artifact_digest ~ '^[0-9a-f]{64}$'",
            name="ck_google_meet_artifact_signals_digest_is_a_digest",
        ),
    )
    op.create_index(
        "ix_google_meet_artifact_signals_tenant_id", "google_meet_artifact_signals", ["tenant_id"]
    )
    op.create_index(
        "ix_google_meet_artifact_signals_meeting", "google_meet_artifact_signals", ["meeting_id"]
    )
    op.create_index(
        "ix_google_meet_artifact_signals_subscription",
        "google_meet_artifact_signals",
        ["subscription_id"],
    )

    op.execute("ALTER TABLE google_meet_artifact_signals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_meet_artifact_signals FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON google_meet_artifact_signals
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # SELECT only, and narrower than every other write path in this schema.
    #
    # The single writer is the Pub/Sub receiver, which is unauthenticated at the
    # transport level and runs platform-side: it resolves the tenant from a
    # verified subscription name before any tenant context could exist, so a
    # scoped INSERT grant would be an unused privilege. And it would be the worst
    # kind: a scoped session that could INSERT here could fabricate the record
    # that a meeting produced a transcript, which is a claim about a meeting
    # nobody in it agreed to. UPDATE and DELETE would let it edit or erase one.
    op.execute("GRANT SELECT ON google_meet_artifact_signals TO cairn_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_meet_artifact_signals")
    op.drop_table("google_meet_artifact_signals")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_meet_subscriptions")
    op.drop_table("google_meet_subscriptions")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_meet_oauth_states")
    op.drop_table("google_meet_oauth_states")

    # Narrowed last, and only once nothing references the value. A downgrade that
    # narrowed the CHECK first would fail against any `source_connections` row
    # holding `google_meet` — which is the correct failure, but it would leave the
    # three tables above behind in a half-dropped state. Dropping them first means
    # the only rows that could still carry the value are connections, and those
    # are a customer's authorisation rather than this migration's to delete: the
    # ADD CONSTRAINT below will refuse, loudly, and an operator disconnects Meet
    # before downgrading.
    _retarget_provider_checks(PROVIDERS_BEFORE)
