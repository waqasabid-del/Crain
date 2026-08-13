"""Async engine and session management."""

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


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide engine.

    Pool sizing is deliberately conservative. Cloud Run scales instances
    aggressively under webhook bursts, and every instance holds its own pool —
    so a generous per-instance pool multiplied by an autoscaling instance count
    is precisely how a database connection limit gets exhausted (md/06 §3.1).
    Connections are pooled per instance and capped; PgBouncer sits in front in
    production.
    """
    settings = get_settings()
    return create_async_engine(
        str(settings.database_url),
        echo=settings.database_echo,
        pool_size=5,
        max_overflow=5,
        # Recycle before typical proxy idle timeouts, so a pooled connection is
        # never handed out already closed at the other end.
        pool_recycle=1800,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Provide a transactional session, committing on success.

    Note this is the *unscoped* entry point and does not set tenant context.
    Step 4 introduces the tenant-scoped variant, which is what application code
    will use. Anything reaching customer data through this function directly
    will be prohibited by review once that exists.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Close all pooled connections. Called on shutdown and after tests."""
    engine = get_engine()
    await engine.dispose()
