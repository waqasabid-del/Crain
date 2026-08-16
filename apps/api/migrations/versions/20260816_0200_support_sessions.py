"""Consent-gated, time-boxed, customer-visible support access.

md/15 §5.2. Support access is *requested* by staff and *approved* by a workspace
Owner or Admin; staff cannot grant it to themselves, and nothing here creates a
standing grant.

Both tables are tenant-scoped and under row-level security, because the customer
must be able to read their own support history and must never read anybody
else's. The grants follow the GitHub tables' pattern for the same reason: staff
write platform-side, before and outside any tenant context, so the application
role gets no INSERT.

``support_sessions`` grants the application role UPDATE — approving, rejecting
and revoking are customer decisions made from inside their own workspace. It
gets no DELETE: a support session that can be deleted is a support session that
cannot be evidenced.

``support_access_events`` is append-only to the application role in the same
sense as the internal audit log: SELECT only, since every write happens
platform-side when staff actually read something.

Revision ID: b2d9c41f8a37
Revises: f7a1c3e95b28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2d9c41f8a37"
down_revision: str | None = "f7a1c3e95b28"
branch_labels: None = None
depends_on: None = None

TENANT_SETTING = "app.current_tenant_id"

SCOPES = "('configuration_diagnostics', 'activity_content')"
STATUSES = "('pending', 'approved', 'rejected', 'revoked')"


def upgrade() -> None:
    op.create_table(
        "support_sessions",
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
            "requested_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Free text, required, and shown to the customer. "Reason: integration
        # failure" is what makes an approval a decision rather than a reflex.
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("requested_scope", sa.String(length=32), nullable=False),
        # Null until approved. Recorded separately from the request so that
        # "they asked for content and were given configuration" stays visible.
        sa.Column("approved_scope", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("requested_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        # Set at approval from the server clock. Never supplied by a caller.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        # Reserved. No break-glass path exists — see the module docstring in
        # `internal/support.py` for why it is not claimed rather than faked.
        sa.Column("break_glass", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(f"requested_scope IN {SCOPES}", name="ck_support_sessions_requested"),
        sa.CheckConstraint(
            f"approved_scope IS NULL OR approved_scope IN {SCOPES}",
            name="ck_support_sessions_approved",
        ),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_support_sessions_status"),
        # An approved session must carry both a scope and an expiry. Half an
        # approval is a session with no end.
        sa.CheckConstraint(
            "status <> 'approved' OR (approved_scope IS NOT NULL AND expires_at IS NOT NULL)",
            name="ck_support_sessions_approval_is_complete",
        ),
        sa.CheckConstraint(
            "requested_minutes > 0 AND requested_minutes <= 240",
            name="ck_support_sessions_duration",
        ),
    )
    op.create_index("ix_support_sessions_tenant_id", "support_sessions", ["tenant_id"])
    op.create_index(
        "ix_support_sessions_requested_by", "support_sessions", ["requested_by_user_id"]
    )

    op.create_table(
        "support_access_events",
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
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("support_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("scope", sa.String(length=32), nullable=False),
        # What was opened, in the customer's terms rather than a route path.
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.CheckConstraint(f"scope IN {SCOPES}", name="ck_support_access_events_scope"),
    )
    op.create_index("ix_support_access_events_tenant_id", "support_access_events", ["tenant_id"])
    op.create_index("ix_support_access_events_session", "support_access_events", ["session_id"])

    for table in ("support_sessions", "support_access_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        """)

    # Staff request platform-side, before any tenant context exists, so the
    # application role gets no INSERT. UPDATE is granted because approving,
    # rejecting and revoking are the customer's own decisions, taken from inside
    # their workspace. No DELETE: a session that can be deleted cannot be
    # evidenced.
    op.execute("GRANT SELECT, UPDATE ON support_sessions TO cairn_app")

    # Read-only. Every access event is written platform-side at the moment staff
    # actually read something.
    op.execute("GRANT SELECT ON support_access_events TO cairn_app")


def downgrade() -> None:
    for table in ("support_access_events", "support_sessions"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("support_access_events")
    op.drop_table("support_sessions")
