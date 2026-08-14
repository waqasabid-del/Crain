"""Make identity and membership creation platform-only.

Revision ID: f1c93a70b5d2
Revises: e4f82b6d1a93
Created: 2026-08-14 03:00:00

A second audit pass found that the previous fix was **incomplete**. Closing the
``invitations`` hole left the same pattern in place on ``tenants`` and ``users``,
and left a third path open through ``memberships``. All three were reproduced.

---

**Membership grafting — a cross-tenant data leak.**

The ``users`` policy makes a person visible when they share a workspace with the
current tenant. A scoped session could freely insert into ``memberships`` for
any ``user_id`` — including one it could not see, because foreign-key checks run
as the constraint owner and are exempt from row-level security.

Reproduced: a session scoped to Tenant A inserted a membership for a user
belonging only to Tenant B, then read that user's email address. The victim also
silently became a member of the attacker's workspace, which would have
associated their future contribution records with it.

**Rogue tenants and users — enumeration oracles.**

``tenants`` and ``users`` each carried a ``tenant_insert`` policy with
``WITH CHECK (true)``, for the same stated reason as invitations: signup happens
before any tenant context exists. Reproduced: a scoped session created both.

Beyond the junk rows, this hands back exactly the account-enumeration oracle
that ``InvalidCredentialsError`` and the constant-time hash in ``authenticate``
were carefully built to deny. Attempt ``INSERT INTO users(email)`` — a unique
violation proves the account exists, success proves it does not.

---

**The correction.** Creating an identity, a workspace, or a membership is a
*platform* operation in every case:

- workspace creation and user creation happen during signup, before any tenant
  context can exist;
- membership creation happens at signup and at invitation acceptance — both of
  which already run on the platform connection.

There is therefore no legitimate reason for the application role to INSERT into
any of them. Revoking that is both simpler and stronger than trying to write a
policy clever enough to distinguish the legitimate case, and it removes the need
for the ``WITH CHECK (true)`` escape hatches entirely.

The application role keeps SELECT, UPDATE and DELETE on ``memberships`` — role
changes and removals are genuinely in-tenant operations, and the isolation
policy already scopes them correctly.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f1c93a70b5d2"
down_revision: str | None = "e4f82b6d1a93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The escape hatches are no longer needed: nothing the application role can
    # do reaches these tables' INSERT path at all now.
    op.execute("DROP POLICY IF EXISTS tenant_insert ON tenants")
    op.execute("DROP POLICY IF EXISTS tenant_insert ON users")

    # Identity and workspace creation are platform operations.
    op.execute("REVOKE INSERT ON tenants FROM cairn_app")
    op.execute("REVOKE INSERT ON users FROM cairn_app")

    # So is membership creation — this is the grafting fix. UPDATE and DELETE
    # stay, because changing a role or removing someone is a genuine in-tenant
    # action and the isolation policy already scopes it.
    op.execute("REVOKE INSERT ON memberships FROM cairn_app")

    # The migration state table was picked up by the default-privileges rule
    # before it was revoked. The application has no business touching it — a
    # stray DELETE would make Alembic believe migrations had never run, and the
    # next deploy would try to apply them all again against a populated schema.
    op.execute("REVOKE ALL ON alembic_version FROM cairn_app")


def downgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON alembic_version TO cairn_app")
    op.execute("GRANT INSERT ON tenants, users, memberships TO cairn_app")
    op.execute("CREATE POLICY tenant_insert ON tenants FOR INSERT WITH CHECK (true)")
    op.execute("CREATE POLICY tenant_insert ON users FOR INSERT WITH CHECK (true)")
