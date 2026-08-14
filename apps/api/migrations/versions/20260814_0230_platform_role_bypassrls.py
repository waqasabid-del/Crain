"""Give the platform role BYPASSRLS explicitly, instead of assuming superuser.

Revision ID: e4f82b6d1a93
Revises: d7a91f4c2e58
Created: 2026-08-14 02:30:00

``db/session.py`` states that the platform engine "connects as the owner and
therefore bypasses row-level security". **That is false wherever ``FORCE ROW
LEVEL SECURITY`` is set** — which is everywhere in this schema. ``FORCE`` exists
precisely to subject a table's owner to its own policies. Only a **superuser** or
a role holding **BYPASSRLS** skips them.

It works locally by accident: ``docker-compose.yml`` runs PostgreSQL as ``cairn``,
the bootstrap superuser, and the platform URL defaults to that role. Managed
PostgreSQL — Cloud SQL, RDS — never grants superuser, and the database owner
there has ``rolbypassrls = false``.

So on the first production deploy, every platform-session read would have
returned zero rows:

- ``authenticate`` would find no user and raise ``InvalidCredentialsError`` for
  everyone. Nobody could log in.
- ``accept_invitation`` would report "Invitation not found" for every valid link.
- ``sign_up``'s duplicate-email check would silently pass — indexes are not
  RLS-filtered — so the failure would surface as a raw ``IntegrityError``
  instead of the domain error.

Silent, total, and environment-dependent, so no test could have caught it: the
test fixtures point the platform connection at the same local superuser.

This migration makes the property explicit rather than incidental. The platform
role gets ``BYPASSRLS`` and nothing else — notably **not** superuser, so it still
cannot bypass permission grants, create roles, or alter the schema outside a
migration.

A startup check in the application asserts both roles have the attributes they
are supposed to have, so a misconfigured ``CAIRN_DATABASE_URL`` cannot silently
disable isolation the way a misconfigured platform URL would have silently
disabled login.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "e4f82b6d1a93"
down_revision: str | None = "d7a91f4c2e58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _platform_role() -> str:
    """The role the application's privileged connection logs in as.

    Defaults to the local development superuser. In any other environment the
    role is named explicitly, because granting BYPASSRLS to the wrong role is
    not something to guess at.
    """
    explicit = os.environ.get("CAIRN_PLATFORM_ROLE")
    if explicit:
        return explicit

    environment = os.environ.get("CAIRN_ENVIRONMENT", "local")
    if environment != "local":
        msg = (
            "CAIRN_PLATFORM_ROLE must be set when CAIRN_ENVIRONMENT is "
            f"'{environment}'. Refusing to guess which role should receive "
            "BYPASSRLS."
        )
        raise RuntimeError(msg)

    return "cairn"


def upgrade() -> None:
    role = _platform_role()

    # The role name crosses into the DO block through a setting rather than
    # string interpolation, for the same reason as the password in the previous
    # role migration.
    op.execute(text("SELECT set_config('cairn.platform_role', :role, true)").bindparams(role=role))

    # A superuser already bypasses RLS, so granting the attribute would be
    # redundant — skip rather than error, so a local database stays valid.
    op.execute(
        text("""
            DO $$
            DECLARE
                target text := current_setting('cairn.platform_role');
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_roles
                    WHERE rolname = target AND NOT rolsuper AND NOT rolbypassrls
                ) THEN
                    EXECUTE format('ALTER ROLE %I BYPASSRLS', target);
                END IF;
            END
            $$;
        """)
    )


def downgrade() -> None:
    role = _platform_role()
    op.execute(text("SELECT set_config('cairn.platform_role', :role, true)").bindparams(role=role))
    op.execute(
        text("""
            DO $$
            DECLARE
                target text := current_setting('cairn.platform_role');
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM pg_roles WHERE rolname = target AND NOT rolsuper
                ) THEN
                    EXECUTE format('ALTER ROLE %I NOBYPASSRLS', target);
                END IF;
            END
            $$;
        """)
    )
