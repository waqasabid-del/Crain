"""Create the non-superuser application role that row-level security requires.

Revision ID: c8b2f5a41e77
Revises: a1c4e7d92b03
Created: 2026-08-14 01:30:00

**Row-level security does not apply to superusers. At all. Ever.**

Not with ``ENABLE``, not with ``FORCE``, not with any policy. PostgreSQL exempts
superusers and roles holding ``BYPASSRLS`` before policies are even considered.

This was discovered the way it should be — by writing an isolation test that
tried to read another tenant's rows and watching it succeed. Without that test,
the policies from the previous migration would have looked correct in every
inspection (``pg_policies`` populated, ``relforcerowsecurity`` true) while
providing no isolation whatsoever, because the application connected as the
superuser that owns the database.

That is a uniquely dangerous class of bug: every visible signal says the control
is working. It would very plausibly have survived to production.

So the application connects as ``cairn_app``:

  - **NOSUPERUSER, NOBYPASSRLS** — the entire point.
  - **NOCREATEDB, NOCREATEROLE** — least privilege (md/06 §7).
  - **DML only, no DDL** — schema changes belong to migrations, which run as the
    owner. An application that cannot alter its own schema cannot corrupt it.

The migration role stays the owner. Two roles, two jobs.
"""

# ruff: noqa: S608 — these statements interpolate module-level constants into
# DDL. PostgreSQL does not accept bound parameters in DDL or policy
# definitions, and no value here originates from user input.

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c8b2f5a41e77"
down_revision: str | None = "a1c4e7d92b03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "cairn_app"

# Local development only. Production supplies this through Secret Manager
# (md/06 §7); no environment that holds customer data ever uses this value.
LOCAL_DEV_PASSWORD = "cairn_local_dev"  # noqa: S105


def upgrade() -> None:
    # CREATE ROLE has no IF NOT EXISTS, and roles are cluster-level — they
    # survive a database drop. A guarded block keeps the migration re-runnable.
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE}
                    LOGIN
                    PASSWORD '{LOCAL_DEV_PASSWORD}'
                    NOSUPERUSER
                    NOBYPASSRLS
                    NOCREATEDB
                    NOCREATEROLE
                    NOINHERIT;
            END IF;
        END
        $$;
    """)

    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")

    # Data manipulation only. No CREATE, no ALTER, no DROP.
    op.execute(f"""
        GRANT SELECT, INSERT, UPDATE, DELETE
        ON ALL TABLES IN SCHEMA public
        TO {APP_ROLE}
    """)
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")

    # Future tables created by later migrations are covered automatically.
    # Without this, every new table would be invisible to the application until
    # someone remembered to add a GRANT — and the failure would look like a
    # permissions bug rather than a missing default.
    op.execute(f"""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}
    """)
    op.execute(f"""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}
    """)


def downgrade() -> None:
    op.execute(f"""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE}
    """)
    op.execute(f"""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE}
    """)
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")

    # The role itself is left in place. Dropping it would break any other
    # database in the cluster that granted it privileges, and a login role with
    # no grants can reach nothing.
