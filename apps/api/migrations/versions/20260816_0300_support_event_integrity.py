"""Make a support access event unable to lie about its session.

Application code decides which event belongs to which session, and application
code is what an attacker or a careless refactor gets to influence. Three
invariants move into the database, where they hold whatever the caller does:

**Same tenant.** A composite foreign key on ``(session_id, tenant_id)`` means an
event cannot claim a session belonging to another workspace — the row simply
cannot be written. This needs a unique key on ``support_sessions(id, tenant_id)``,
which is redundant against the primary key and exists only as the target.

**Approved scope only.** A trigger refuses an event whose scope is not the scope
the customer approved. A `configuration_diagnostics` approval can therefore never
carry an `activity_content` event, even if a future route forgot to check.

**Approved at all.** The same trigger refuses an event against a session that is
pending, rejected or revoked. Recording use against permission that was never
given is the specific lie this table exists to prevent.

Revision ID: c8f3e07d61b4
Revises: b2d9c41f8a37
"""

from __future__ import annotations

from alembic import op

revision: str = "c8f3e07d61b4"
down_revision: str | None = "b2d9c41f8a37"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_support_sessions_id_tenant", "support_sessions", ["id", "tenant_id"]
    )

    # Replaces the single-column foreign key: the pair is what makes a
    # cross-tenant attribution unrepresentable.
    op.drop_constraint(
        "fk_support_access_events_session_id_support_sessions",
        "support_access_events",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_support_access_events_session_tenant",
        "support_access_events",
        "support_sessions",
        ["session_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION support_access_event_matches_session()
        RETURNS TRIGGER AS $$
        DECLARE
            session_status TEXT;
            session_scope TEXT;
        BEGIN
            SELECT status, approved_scope INTO session_status, session_scope
            FROM support_sessions WHERE id = NEW.session_id;

            IF session_status IS DISTINCT FROM 'approved' THEN
                RAISE EXCEPTION
                    'support access event % is against a session that is not approved (%)',
                    NEW.id, session_status;
            END IF;

            IF NEW.scope IS DISTINCT FROM session_scope THEN
                RAISE EXCEPTION
                    'support access event scope % does not match the approved scope %',
                    NEW.scope, session_scope;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER support_access_event_integrity
        BEFORE INSERT OR UPDATE ON support_access_events
        FOR EACH ROW EXECUTE FUNCTION support_access_event_matches_session();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS support_access_event_integrity ON support_access_events")
    op.execute("DROP FUNCTION IF EXISTS support_access_event_matches_session()")
    op.drop_constraint(
        "fk_support_access_events_session_tenant", "support_access_events", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_support_access_events_session_id_support_sessions",
        "support_access_events",
        "support_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_support_sessions_id_tenant", "support_sessions", type_="unique")
