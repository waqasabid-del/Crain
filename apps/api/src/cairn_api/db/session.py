"""Engines and session management.

Two connections exist, deliberately:

- **Application** (``get_engine``) — connects as a NOSUPERUSER, NOBYPASSRLS role,
  so row-level security genuinely applies. Everything that touches customer data
  goes through here, via ``tenancy.tenant_session``.

- **Platform** (``get_platform_engine``) — connects as the owner and therefore
  bypasses RLS. Reserved for the handful of operations that legitimately precede
  any tenant context: signup, workspace creation, and administrative tooling.

Keeping them apart means using elevated privileges is an explicit, greppable act
rather than the default. ``grep platform_session`` should return a short list,
and every entry should be justifiable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cairn_api.config import get_settings


def _build_engine(url: str, *, echo: bool) -> AsyncEngine:
    """Create an engine with conservative pooling.

    Pool sizing matters more than it looks. Cloud Run scales instances
    aggressively under webhook bursts and every instance holds its own pool, so
    a generous per-instance pool multiplied by an autoscaling instance count is
    exactly how a database connection limit gets exhausted (md/06 §3.1).
    PgBouncer sits in front in production.
    """
    return create_async_engine(
        url,
        echo=echo,
        pool_size=5,
        max_overflow=5,
        # Recycle before typical proxy idle timeouts, so a pooled connection is
        # never handed out already closed at the far end.
        pool_recycle=1800,
        pool_pre_ping=True,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    """The application engine. Subject to row-level security."""
    settings = get_settings()
    return _build_engine(str(settings.database_url), echo=settings.database_echo)


@lru_cache
def get_platform_engine() -> AsyncEngine:
    """The privileged engine. Bypasses row-level security.

    A smaller pool than the application engine: platform operations are rare,
    and a large pool of privileged connections is both wasteful and a broader
    blast radius than necessary.
    """
    settings = get_settings()
    engine = create_async_engine(
        str(settings.platform_database_url),
        echo=settings.database_echo,
        pool_size=2,
        max_overflow=2,
        pool_recycle=1800,
        pool_pre_ping=True,
    )
    return engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Session factory for the application engine."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@lru_cache
def get_platform_session_factory() -> async_sessionmaker[AsyncSession]:
    """Session factory for the privileged engine."""
    return async_sessionmaker(
        bind=get_platform_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def platform_session() -> AsyncIterator[AsyncSession]:
    """Open a privileged session that bypasses tenant isolation.

    **Use this only for operations that cannot have a tenant context**, because
    the tenant does not exist yet or the operation spans tenants by design:

    - creating a workspace during signup
    - creating a user account before any membership exists
    - platform administration and support tooling (file 15 §5)

    Anything reading or writing customer data within a known workspace must use
    ``tenancy.tenant_session`` instead. Reviewers should treat a new call to this
    function as requiring justification in the pull request.
    """
    factory = get_platform_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engines() -> None:
    """Close all pooled connections. Called on shutdown and after tests."""
    await get_engine().dispose()
    await get_platform_engine().dispose()
