"""Tenant context — the mechanism CAIRN's isolation depends on.

This is the sharpest technical risk in the architecture (md/06 §4.3), because
its failure mode is silent. A query that loses tenant context does not raise; it
quietly returns another customer's data, or writes into their workspace. For a
product whose entire proposition is trust, that is the worst available failure.

**Two layers, deliberately.**

1. *Application layer — fails loudly.* Every scoped session must be given a
   tenant ID. Asking for one without it raises immediately, at the call site,
   with a clear message.

2. *Database layer — fails safely.* PostgreSQL row-level security filters on
   ``app.current_tenant_id``. If that setting is absent, policies match nothing
   and queries return no rows.

Neither layer alone is sufficient. The application check catches the mistake
early and explains it; RLS catches the query that somehow slipped past — a raw
SQL statement, a forgotten filter, a library that opens its own session. RLS is
the safety net, not the primary control (md/06 §4.2).

**Why ``SET LOCAL`` and not ``SET``.**

``SET LOCAL`` scopes the setting to the current transaction. ``SET`` scopes it
to the *session*, which under connection pooling means the next request to
borrow that connection inherits the previous tenant's context. That is a
cross-tenant data leak produced by a single missing keyword, and it would only
appear under concurrency — never in a local test with one user.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.session import get_session_factory

#: PostgreSQL setting the RLS policies read. Defined once so a typo cannot
#: silently disable isolation — a misspelled name in a policy would simply never
#: match, which reads as "no data" rather than "broken".
TENANT_SETTING = "app.current_tenant_id"


class MissingTenantContextError(RuntimeError):
    """Raised when an operation that requires a tenant does not have one.

    Deliberately not a subclass of ``ValueError``. This must never be swallowed
    by a generic ``except ValueError`` that was written to handle bad input —
    it signals a programming error with data-isolation consequences, and should
    reach a human.
    """


async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Bind a session's current transaction to one tenant.

    Uses ``SET LOCAL`` so the binding dies with the transaction and cannot
    outlive it on a pooled connection.

    The value is passed as a bound parameter rather than interpolated into the
    statement. ``SET LOCAL`` does not accept parameters directly, so this uses
    ``set_config()``, which does — closing an SQL injection path that string
    formatting would leave open.
    """
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

    This is the only sanctioned way for application code to reach customer data.
    ``platform_session()`` in ``session.py`` opens a privileged session and is
    reserved for operations that legitimately precede tenant context — signup,
    workspace creation, and support tooling.

    Args:
        tenant_id: The workspace to scope to. ``None`` raises rather than
            silently opening an unscoped session, because the most likely way
            for a tenant ID to be ``None`` is that something upstream failed to
            resolve it.

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
        try:
            # Must precede any query. Because the setting is transaction-scoped,
            # it applies to everything in this block and nothing outside it.
            await set_tenant_context(session, tenant_id)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
