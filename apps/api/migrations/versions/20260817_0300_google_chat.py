"""Google Chat: the install, the chosen spaces, and one subscription each.

Three tables, and the interesting one is the middle.

**`google_chat_oauth_states` has no grant at all.** The redirect URI is
registered with Google once and therefore cannot name a workspace, so the
callback arrives with no tenant context to scope a policy to — every statement
against it is platform-side. The absence is asserted rather than assumed.

**`google_chat_space_selections` is unique on `space_name` globally**, not per
connection. Slack can key on a team id; the two Chat scopes CAIRN requests carry
no account identity at all — no customer id, no domain, no address — so there is
nothing equivalent to bind a connection to. A Chat space resource name *is*
globally unique, so the property that actually matters is enforced exactly here:
one space feeds at most one CAIRN workspace, and an inbound event resolves to
one tenant or to none.

**`google_chat_subscriptions` exists because Google's subscriptions expire in
four hours.** With message text delivered inline and no domain-wide delegation
that is the ceiling, so every selected space is renewed several times a day,
forever. The row is what the renewal sweep reads and what makes "why did this
space go quiet" answerable after Google has deleted the subscription itself —
an expired subscription is destroyed at Google and cannot be renewed, only
recreated, so the local record is the only remaining evidence.

Revision ID: c5a92f7e4d18
Revises: e7b41c8d0392
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from cairn_api.db.gchat_models import SPACE_NAME_PATTERN, SUBSCRIPTION_NAME_PATTERN
from cairn_api.db.tenancy import TENANT_SETTING
from sqlalchemy.dialects import postgresql

revision: str = "c5a92f7e4d18"
down_revision: str | None = "e7b41c8d0392"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # -- The in-flight install ---------------------------------------------
    op.create_table(
        "google_chat_oauth_states",
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
        "ix_google_chat_oauth_states_tenant_id", "google_chat_oauth_states", ["tenant_id"]
    )
    op.create_index(
        "ix_google_chat_oauth_states_expires_at", "google_chat_oauth_states", ["expires_at"]
    )

    op.execute("ALTER TABLE google_chat_oauth_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_chat_oauth_states FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON google_chat_oauth_states
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # No GRANT, for the reason in the module docstring. `test_tenant_isolation.py`
    # asserts the table is unreachable from the application role, so a later
    # "just add SELECT" fails a test rather than passing review.

    # -- The chosen spaces --------------------------------------------------
    op.create_table(
        "google_chat_space_selections",
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
        sa.Column("space_name", sa.String(length=160), nullable=False),
        sa.Column(
            "selected_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("space_name", name="uq_google_chat_space_selections_space_name"),
        # Rejects a display name at the database rather than only in the request
        # model. A bare id with the prefix stripped is refused too: it would never
        # match the resource name a Chat event carries, so it would be a
        # permission that looks granted and delivers nothing.
        sa.CheckConstraint(
            f"space_name ~ '{SPACE_NAME_PATTERN}'",
            name="ck_google_chat_space_selections_space_name_is_a_resource_name",
        ),
    )
    op.create_index(
        "ix_google_chat_space_selections_tenant_id", "google_chat_space_selections", ["tenant_id"]
    )
    op.create_index(
        "ix_google_chat_space_selections_connection_id",
        "google_chat_space_selections",
        ["connection_id"],
    )
    # The ingestion lookup — "may this tenant process this space" — runs on every
    # inbound event, so it is the one index that has to exist.
    op.create_index(
        "ix_google_chat_space_selections_tenant_space",
        "google_chat_space_selections",
        ["tenant_id", "space_name"],
    )

    op.execute("ALTER TABLE google_chat_space_selections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_chat_space_selections FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON google_chat_space_selections
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # SELECT, INSERT, DELETE — the `slack_channel_selections` set, for the same
    # reason: the presence of the row is the permission, so selecting inserts and
    # deselecting deletes and there is nothing to UPDATE. An unused privilege is
    # the one an injection gets to use first.
    op.execute("GRANT SELECT, INSERT, DELETE ON google_chat_space_selections TO cairn_app")

    # -- One subscription per chosen space ----------------------------------
    op.create_table(
        "google_chat_subscriptions",
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
        sa.Column("space_name", sa.String(length=160), nullable=False),
        sa.Column("subscription_name", sa.String(length=160), nullable=True),
        sa.Column("expire_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        # A category from the closed set, never Google's message. Google's
        # suspension reasons quote the resource that failed, which here means
        # space display names and the authorising person's address — and this
        # column is read by staff diagnostics and rendered in the customer's own
        # integrations screen.
        sa.Column("suspension_category", sa.String(length=32), nullable=True),
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
        # Two rows would mean two renewal schedules for one space and, when they
        # disagree, a space that stops delivering while a row still says active.
        sa.UniqueConstraint(
            "connection_id",
            "space_name",
            name="uq_google_chat_subscriptions_connection_space",
        ),
        sa.CheckConstraint(
            f"space_name ~ '{SPACE_NAME_PATTERN}'",
            name="ck_google_chat_subscriptions_space_name_is_a_resource_name",
        ),
        sa.CheckConstraint(
            f"subscription_name IS NULL OR subscription_name ~ '{SUBSCRIPTION_NAME_PATTERN}'",
            name="ck_google_chat_subscriptions_subscription_name_is_a_resource_name",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'active', 'suspended', 'expired', 'deleted', 'error')",
            name="ck_google_chat_subscriptions_state",
        ),
    )
    op.create_index(
        "ix_google_chat_subscriptions_tenant_id", "google_chat_subscriptions", ["tenant_id"]
    )
    op.create_index(
        "ix_google_chat_subscriptions_connection_id", "google_chat_subscriptions", ["connection_id"]
    )
    # The renewal sweep: "which subscriptions lapse soon". State first, because
    # the sweep only ever looks at live ones.
    op.create_index(
        "ix_google_chat_subscriptions_state_expire_time",
        "google_chat_subscriptions",
        ["state", "expire_time"],
    )
    op.create_index(
        "ix_google_chat_subscriptions_subscription_name",
        "google_chat_subscriptions",
        ["subscription_name"],
    )

    op.execute("ALTER TABLE google_chat_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_chat_subscriptions FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON google_chat_subscriptions
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # SELECT only. Every write is the renewal sweep or the create/delete path,
    # both platform-side: the sweep runs in the worker with no tenant context,
    # because it crosses every tenant by definition. A scoped session that could
    # UPDATE this table could mark its own subscription active and make a space
    # that Google is not delivering look healthy.
    op.execute("GRANT SELECT ON google_chat_subscriptions TO cairn_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_chat_subscriptions")
    op.drop_table("google_chat_subscriptions")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_chat_space_selections")
    op.drop_table("google_chat_space_selections")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON google_chat_oauth_states")
    op.drop_table("google_chat_oauth_states")
