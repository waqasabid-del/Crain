"""Slack install state and public-channel selection.

Two tables, and deliberately no third. The Slack *connection* is a row in
``source_connections`` — the table created one migration ago for exactly this —
so nothing here duplicates "which workspace is connected to which account".

``slack_oauth_states`` gets **no grant at all** to the application role, which is
the unusual decision in this file and the one worth reading. Every statement
against it happens on the platform connection: the install starts inside a
workspace, but the callback arrives on a URL registered once with Slack and
therefore carrying no workspace — there is no tenant context to scope to when the
row has to be read. A scoped session that could read it would learn nothing
useful (the nonce is stored hashed), but one that could *write* it could mint an
install state for its own workspace, and one that could update it could un-consume
a state and replay a callback. Row-level security is still enabled and forced, so
the absence of a grant is defence in depth rather than the only defence.

``slack_channel_selections`` gets SELECT, INSERT and DELETE — the same set as
``source_opt_outs``, for the same reason. The presence of a row *is* the
permission, so there is no mutable state to UPDATE; deselecting a channel deletes
the row, and a tombstone of a withdrawn permission is the wrong kind of memory.
Both writes happen from inside tenant context (an admin acting on their own
workspace), and the policy's WITH CHECK means a scoped session cannot write a
selection for another tenant even if it tried.

Revision ID: e7b41c8d0392
Revises: d3f81b6c052a
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b41c8d0392"
down_revision: str | None = "d3f81b6c052a"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"

#: Mirrors ``db/slack_models.CHANNEL_ID_PATTERN``. Restated rather than imported
#: because a migration must describe the schema as it was at this revision — an
#: import would make an old migration change meaning when the model changes.
CHANNEL_ID_PATTERN = "^C[A-Z0-9]{2,31}$"


def upgrade() -> None:
    op.create_table(
        "slack_oauth_states",
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
        # RESTRICT, like `source_connections.authorised_by_user_id`: an in-flight
        # install is a consent record, and losing who started it because they
        # left the company is exactly backwards.
        sa.Column(
            "initiated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # SHA-256 hex of the nonce. Never the nonce — a stored plaintext would
        # let anyone who can read this table finish an install somebody else
        # started, which is the single thing the nonce exists to prevent.
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Stamped when the callback claims it, before the code is exchanged, so
        # a failed exchange cannot leave a replayable state behind.
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Global, not per-tenant. Two rows sharing a nonce would make "which
        # install is this callback for" ambiguous, and the resolution — pick one
        # — would bind a Slack workspace to whichever tenant sorted first.
        sa.UniqueConstraint("state_hash", name="uq_slack_oauth_states_state_hash"),
    )
    op.create_index("ix_slack_oauth_states_tenant_id", "slack_oauth_states", ["tenant_id"])
    # Supports the expiry sweep: without it, clearing lapsed states scans a table
    # that grows by one row per abandoned install.
    op.create_index("ix_slack_oauth_states_expires_at", "slack_oauth_states", ["expires_at"])

    op.execute("ALTER TABLE slack_oauth_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE slack_oauth_states FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON slack_oauth_states
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # No GRANT. See the module docstring — this is the deliberate absence, not an
    # oversight, and `test_tenant_isolation.py` asserts the table is unreachable
    # from the application role so that a later "just add SELECT" fails a test
    # rather than passing review.

    op.create_table(
        "slack_channel_selections",
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
        # CASCADE: a selection outliving its connection is a permission attached
        # to nothing, and the next connection to the same Slack workspace would
        # silently inherit it.
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The Slack channel id, never the display name. Names change — a rename
        # would silently revoke or grant a permission — and a channel name is
        # customer data of the kind `ConnectorErrorCategory` exists to keep out
        # of logs and staff screens. There is no name column to leak.
        sa.Column("channel_id", sa.String(length=32), nullable=False),
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
        # Rejects a display name at the database rather than only in the request
        # model. `#general` is what arrives when an interface passes the label
        # through, and storing it would create a permission that matches no
        # inbound event — a channel that looks selected and delivers nothing.
        sa.CheckConstraint(
            f"channel_id ~ '{CHANNEL_ID_PATTERN}'",
            name="ck_slack_channel_selections_channel_id_is_an_id",
        ),
        # Per connection, not per tenant: channel ids are unique within a Slack
        # workspace, not globally, so a tenant that reconnects to a different
        # Slack team must not inherit the previous team's selection.
        sa.UniqueConstraint(
            "connection_id", "channel_id", name="uq_slack_channel_selections_connection_channel"
        ),
    )
    op.create_index(
        "ix_slack_channel_selections_tenant_id", "slack_channel_selections", ["tenant_id"]
    )
    # The lookup every inbound Slack event performs: may this tenant process this
    # channel. The one index here that is on the hot path.
    op.create_index(
        "ix_slack_channel_selections_tenant_channel",
        "slack_channel_selections",
        ["tenant_id", "channel_id"],
    )

    op.execute("ALTER TABLE slack_channel_selections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE slack_channel_selections FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON slack_channel_selections
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # SELECT, INSERT, DELETE — the `source_opt_outs` set, for the same reason.
    # The presence of the row is the permission, so there is nothing to UPDATE:
    # selecting inserts, deselecting deletes. Granting UPDATE would add a
    # privilege nothing uses, and an unused privilege is the one an injection
    # gets to use first. Both writes run from inside tenant context, where the
    # WITH CHECK above stops a scoped session writing another tenant's row.
    op.execute("GRANT SELECT, INSERT, DELETE ON slack_channel_selections TO cairn_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON slack_channel_selections")
    op.drop_table("slack_channel_selections")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON slack_oauth_states")
    op.drop_table("slack_oauth_states")
