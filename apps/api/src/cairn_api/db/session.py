"""Engines and session management.

Two connections: Application (``get_engine``) is NOSUPERUSER/NOBYPASSRLS, so
RLS genuinely applies. Platform (``get_platform_engine``) bypasses RLS,
reserved for signup, workspace creation, and admin tooling. Keeping them apart
makes elevated privilege an explicit, greppable act.
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
    """Engine with conservative pooling — per-instance pool times autoscaled
    instance count is how a connection limit gets exhausted (md/06 §3.1)."""
    return create_async_engine(
        url,
        echo=echo,
        pool_size=5,
        max_overflow=5,
        # Recycle before typical proxy idle timeouts.
        pool_recycle=1800,
        pool_pre_ping=True,
    )


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return _build_engine(str(settings.database_url), echo=settings.database_echo)


@lru_cache
def get_platform_engine() -> AsyncEngine:
    """Smaller pool than the application engine — platform ops are rare."""
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
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@lru_cache
def get_platform_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_platform_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def platform_session() -> AsyncIterator[AsyncSession]:
    """Open a privileged session that bypasses tenant isolation.

    Only for operations with no tenant context: signup, workspace/account
    creation, admin tooling (file 15 §5). Otherwise use
    ``tenancy.tenant_session``. New call sites need PR justification.
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
    await get_engine().dispose()
    await get_platform_engine().dispose()
