"""Close two confirmed cross-tenant compromise paths.

Revision ID: d7a91f4c2e58
Revises: 53bd3c7afb3d
Created: 2026-08-14 02:00:00

Both were found by an adversarial review of the previous migrations and then
**reproduced against a live database** before this fix was written. Neither was
theoretical.

---

**Gap 1 — a scoped session could plant an invitation into any workspace.**

The previous migration created two permissive policies on ``invitations``:
``tenant_isolation`` (FOR ALL, WITH CHECK tenant_id = current setting) and
``tenant_insert`` (FOR INSERT, WITH CHECK true). PostgreSQL ORs permissive
policies together, so the effective INSERT check was ``(tenant_id = ctx) OR
true`` — that is, ``true``. The isolation policy was dead for inserts.

Reproduced: a session scoped to Tenant A successfully inserted an invitation
row for Tenant B with ``role = 'owner'``. The attacker chooses the token, so
being unable to read the row back does not matter. They then redeem it through
the ordinary public acceptance flow — which runs platform-side — and become
Owner of a workspace they were never part of.

The policy's stated justification was also simply wrong: accepting an invitation
does not INSERT into ``invitations``, it UPDATEs ``accepted_at``.

**Gap 2 — the authentication tables had no row-level security at all**, and the
application role held full DML on them.

``sessions``, ``password_credentials`` and ``oauth_identities`` were created
without RLS and then granted to ``cairn_app``, the role every tenant-scoped
request and every job handler uses. Reproduced: the application role inserted a
session row for an arbitrary user, with no tenant context set, and read the
sessions table freely.

That turns any injection or scoping bug anywhere in the application into account
takeover — mint a session for any user, or overwrite any password hash. It also
contradicted the guarantee in ``db/tenancy.py`` that RLS is the net catching
"the query that somehow slipped past".

These tables genuinely cannot be tenant-scoped: a session must be resolvable
before the tenant is known. The correct answer is therefore not a policy but
**no access at all** from the application role — authentication is a platform
operation, and every function in ``auth/service.py`` already runs on the
platform connection. Deny-all RLS is added alongside the revoke so that a future
``GRANT``, or the ``ALTER DEFAULT PRIVILEGES`` rule from the role migration,
cannot silently reopen the hole.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d7a91f4c2e58"
down_revision: str | None = "53bd3c7afb3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Authentication material. Platform-only by design.
AUTH_TABLES = ("sessions", "password_credentials", "oauth_identities")

TENANT_SETTING = "app.current_tenant_id"


def upgrade() -> None:
    # ---------------------------------------------------- Gap 1: invitations
    # tenant_isolation's WITH CHECK already permits inserts within the current
    # tenant, which is the only legitimate case. This policy only ever widened
    # that to "any tenant".
    op.execute("DROP POLICY IF EXISTS tenant_insert ON invitations")

    # ------------------------------------------------- Gap 2: auth tables
    for table in AUTH_TABLES:
        # Revoke first. The grant is the actual exposure; RLS is defence in
        # depth behind it.
        op.execute(f"REVOKE ALL ON {table} FROM cairn_app")

        # Deny-all: RLS enabled and forced, with no policy. PostgreSQL denies
        # every row when RLS is on and nothing permits it, so this holds even if
        # someone re-grants the table later.
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Stop the default-privileges rule from re-granting these on any future
    # table creation in this schema. Explicit grants remain possible; automatic
    # ones do not.
    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM cairn_app
    """)

    # Re-grant only the tables the application legitimately uses, explicitly.
    # Listing them by name means a new table is invisible to the application
    # until someone deliberately adds it — and has to think about RLS while
    # doing so.
    op.execute("""
        GRANT SELECT, INSERT, UPDATE, DELETE
        ON tenants, users, memberships, invitations
        TO cairn_app
    """)


def downgrade() -> None:
    op.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cairn_app
    """)

    for table in AUTH_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cairn_app")

    op.execute("CREATE POLICY tenant_insert ON invitations FOR INSERT WITH CHECK (true)")
