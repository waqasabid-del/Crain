"""Tenant context — the mechanism CAIRN's isolation depends on (md/06 §4.3). A
query that loses it silently returns another customer's data instead of
raising. Two layers: application fails loudly; RLS fails safely (md/06 §4.2).
``SET LOCAL``, not ``SET``, which would leak the prior tenant to the next
pooled request.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.session import get_session_factory

#: PostgreSQL setting the RLS policies read.
TENANT_SETTING = "app.current_tenant_id"


class MissingTenantContextError(RuntimeError):
    """No tenant for an operation that requires one. Not a ``ValueError``
    subclass — must never be swallowed by a generic bad-input handler."""


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind a session's transaction to one tenant via ``set_config()``."""
    await session.execute(
        text("SELECT set_config(:setting, :value, true)"),
        {"setting": TENANT_SETTING, "value": str(tenant_id)},
    )


async def get_tenant_context(session: AsyncSession) -> uuid.UUID | None:
    """Return the tenant currently bound to this transaction, if any."""
    raw = await session.scalar(
        text("SELECT current_setting(:setting, true)"),
        {"setting": TENANT_SETTING},
    )
    if not raw:
        return None
    return uuid.UUID(raw)


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID | None) -> AsyncIterator[AsyncSession]:
    """Open a session scoped to exactly one tenant.

    Raises:
        MissingTenantContextError: If ``tenant_id`` is ``None``.
    """
    if tenant_id is None:
        msg = (
            "tenant_session() requires a tenant ID. If this operation genuinely "
            "spans tenants, use session_scope() explicitly and document why."
        )
        raise MissingTenantContextError(msg)

    factory = get_session_factory()
    async with factory() as session:
        # Re-apply on every new transaction: `SET LOCAL` dies with its
        # transaction, so a mid-block commit would otherwise go unscoped.
        @event.listens_for(session.sync_session, "after_begin")
        def _reapply_tenant_context(
            sess: object,
            transaction: object,
            connection: Connection,
        ) -> None:
            connection.execute(
                text("SELECT set_config(:setting, :value, true)"),
                {"setting": TENANT_SETTING, "value": str(tenant_id)},
            )

        try:
            await set_tenant_context(session, tenant_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
