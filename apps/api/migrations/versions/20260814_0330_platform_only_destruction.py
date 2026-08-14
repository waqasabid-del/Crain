"""Make identity and workspace destruction platform-only.

Revision ID: a9d24e60c3f1
Revises: f1c93a70b5d2
Created: 2026-08-14 03:30:00

The previous migration applied the principle "creating an identity, a workspace
or a membership is a platform operation" to ``INSERT`` and stopped there.
**Destroying one is exactly the same kind of operation**, and leaving ``DELETE``
granted left two paths open. Both were reproduced.

---

**Workspace deletion required no authorization at all.**

Reproduced: a scoped session ran ``DELETE FROM tenants`` and the row was
removed. The ``tenants`` policy is ``USING (id = current setting)``, so a session
may delete precisely the workspace it is scoped to — and nothing at the database
layer consults a role. ``WORKSPACE_DELETE`` is reserved to the Owner in the
permission model (md/15 §2.2), but the permission model is only consulted in
application code, and any injection or missed check goes straight past it.

A Viewer could destroy the workspace, with every membership, invitation and
future record cascading with it.

**Deleting a shared user destroyed their memberships in other workspaces.**

The ``users`` policy makes a person visible when they share a workspace with the
current tenant, and foreign keys cascade. So a session scoped to Acme could
delete a contractor who also belongs to Globex, taking that person's Globex
membership, sessions, password credential and OAuth identities with them.

Globex loses a member because of an action taken entirely inside Acme.

---

Both are now platform-only. Account erasure is a GDPR Article 17 operation that
belongs behind an audited, authenticated path (md/05 §B.5), and workspace
deletion is an Owner action that must go through a permission check — neither
should be reachable by a stray statement on the application connection.

The application role keeps ``DELETE`` on ``memberships`` and ``invitations``:
removing someone from a workspace and revoking an invitation are genuine
in-tenant actions, and the isolation policy already scopes them correctly.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a9d24e60c3f1"
down_revision: str | None = "f1c93a70b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Workspace deletion is an Owner action gated by WORKSPACE_DELETE, and
    # irreversible. It must not be reachable without that check.
    op.execute("REVOKE DELETE ON tenants FROM cairn_app")

    # Account erasure is a GDPR Article 17 operation, and cascades across every
    # workspace the person belongs to.
    op.execute("REVOKE DELETE ON users FROM cairn_app")

    # UPDATE on users stays for now — display-name changes are legitimate
    # self-service. It is narrowed to the authenticated subject once the API
    # layer exists; recorded in md/18 rather than left implicit.


def downgrade() -> None:
    op.execute("GRANT DELETE ON tenants, users TO cairn_app")
