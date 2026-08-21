"""Alembic environment.

Runs migrations synchronously and deliberately. Migrations are infrequent,
happen outside the request path, and benefit from being simple to reason about
far more than from being fast.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from cairn_api.config import get_settings
from cairn_api.db.auth_models import (  # noqa: F401  (register metadata)
    Invitation,
    OAuthIdentity,
    PasswordCredential,
    Session,
)
from cairn_api.db.base import Base
from cairn_api.db.models import Membership, Tenant, User  # noqa: F401  (register metadata)
from cairn_api.db.project_models import (  # noqa: F401  (register metadata)
    Project,
    ProjectMember,
    ProjectSource,
)
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The database URL comes from application settings so it is defined in exactly
# one place and never committed to the repository.
config.set_main_option("sqlalchemy.url", get_settings().sync_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Used to review the exact statements before applying them to production —
    a schema change is one of the few operations that cannot be rolled back by
    redeploying.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Without these, Alembic silently misses column type and default
            # changes, and the schema drifts from the models unnoticed.
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
