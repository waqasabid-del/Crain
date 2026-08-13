"""Row-level security on tenant-scoped tables.

Revision ID: a1c4e7d92b03
Revises: 7f3ecb2d0b7a
Created: 2026-08-14 01:00:00

The database-level half of tenant isolation. See ``db/tenancy.py`` for the
application-level half and why both exist.

Three details here are easy to get wrong and expensive to get wrong:

1. **FORCE, not just ENABLE.** ``ENABLE ROW LEVEL SECURITY`` does not apply to
   the table's owner, and the application connects as the owner in most
   deployments — including this one. Without ``FORCE``, every policy below
   would be silently inert while appearing correct in ``\\d+`` output. This is
   the single most common way RLS is misconfigured.

2. **``current_setting(..., true)`` returns NULL when unset**, so an unscoped
   query matches no rows rather than raising. That is deliberate: the database
   fails *safely* while the application layer fails *loudly*. A policy that
   raised would make legitimate platform operations awkward and would tempt
   someone to disable RLS entirely.

3. **``users`` is filtered by relationship, not by a tenant column.** A user is
   global — one person, one identity across every workspace (see
   ``db/models.py``). Visibility is therefore "do we share a tenant", expressed
   as an EXISTS over memberships. Without this, any authenticated context could
   enumerate every email address on the platform.
"""

# ruff: noqa: S608 — these statements interpolate module-level constants into
# DDL. PostgreSQL does not accept bound parameters in DDL or policy
# definitions, and no value here originates from user input.

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a1c4e7d92b03"
down_revision: str | None = "7f3ecb2d0b7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SETTING = "app.current_tenant_id"


def upgrade() -> None:
    # ---------------------------------------------------------------- tenants
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")

    op.execute(f"""
        CREATE POLICY tenant_isolation ON tenants
        USING (id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # Creating a workspace happens before any tenant context can exist, so
    # INSERT is permitted unconditionally. The row is only readable afterwards
    # by a session scoped to it, per the policy above.
    op.execute("""
        CREATE POLICY tenant_insert ON tenants
        FOR INSERT WITH CHECK (true)
    """)

    # ----------------------------------------------------------- memberships
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships FORCE ROW LEVEL SECURITY")

    # USING governs reads and the rows an UPDATE/DELETE may touch;
    # WITH CHECK governs the rows a write may produce. Both are required:
    # without WITH CHECK, a scoped session could insert a row belonging to a
    # different tenant, or move one across the boundary with an UPDATE.
    op.execute(f"""
        CREATE POLICY tenant_isolation ON memberships
        USING (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
        WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid)
    """)

    # ----------------------------------------------------------------- users
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")

    # A user is visible when they share a workspace with the current context.
    op.execute(f"""
        CREATE POLICY tenant_isolation ON users
        USING (
            EXISTS (
                SELECT 1 FROM memberships m
                WHERE m.user_id = users.id
                  AND m.tenant_id = NULLIF(current_setting('{TENANT_SETTING}', true), '')::uuid
            )
        )
    """)

    # Signup creates a user before any membership exists, so INSERT is
    # unconditional for the same reason as tenants above.
    op.execute("""
        CREATE POLICY tenant_insert ON users
        FOR INSERT WITH CHECK (true)
    """)


def downgrade() -> None:
    for table in ("users", "memberships", "tenants"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_insert ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
