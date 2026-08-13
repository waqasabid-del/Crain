"""Application settings.

Loaded from the environment, validated at startup. Failing loudly on a missing
or malformed setting is deliberate: a service that boots with a half-configured
database URL fails later, in a harder place to diagnose.

No secret ever has a production-usable default. The local database password is
the sole exception, and it only reaches a container that never holds real data
(md/17-engineering-standards.md §9.1).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CAIRN_",
        extra="ignore",
    )

    environment: Environment = "local"

    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://cairn_app:cairn_local_dev@localhost:5432/cairn"),
        description=(
            "Application connection. Uses a NOSUPERUSER, NOBYPASSRLS role so that "
            "row-level security actually applies — RLS is silently inert for "
            "superusers regardless of FORCE."
        ),
    )

    platform_database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://cairn:cairn_local_dev@localhost:5432/cairn"),
        description=(
            "Privileged connection for operations that legitimately precede any "
            "tenant context: signup, workspace creation, migrations. Deliberately "
            "separate so that reaching for it is a visible, greppable decision "
            "rather than something that happens by default."
        ),
    )

    #: Echo SQL to the log. Useful locally, unacceptable in production, where it
    #: would write customer data into log storage.
    database_echo: bool = False

    @field_validator("database_url", "platform_database_url")
    @classmethod
    def require_async_driver(cls, value: PostgresDsn) -> PostgresDsn:
        """Reject a synchronous driver.

        The application is async throughout. A ``postgresql://`` URL would work
        in isolated tests and then block the event loop under real concurrency —
        a performance failure that only appears under load, which is the worst
        time to discover it.
        """
        if value.scheme != "postgresql+asyncpg":
            msg = f"database_url must use the postgresql+asyncpg driver, got {value.scheme!r}"
            raise ValueError(msg)
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL, for Alembic only.

        Derived from the *platform* URL: migrations need DDL privileges the
        application role deliberately does not hold. psycopg 3 is used rather
        than the legacy psycopg2, which is in maintenance mode.
        """
        return str(self.platform_database_url).replace("+asyncpg", "+psycopg")


@lru_cache
def get_settings() -> Settings:
    """Return cached settings.

    Cached so that configuration is parsed once per process rather than on every
    request or dependency resolution.
    """
    return Settings()
