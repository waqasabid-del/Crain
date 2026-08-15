"""Deleting raw activity once its retention period is up.

Deleted rather than filtered: the period is published in the Trust & Privacy
Center. Only raw webhook payloads are swept; facts and briefs are the team's own
record. Runs on the worker timer, which spans tenants as a job session cannot.
"""

from __future__ import annotations

from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.github_models import WebhookDelivery
from cairn_api.db.models import Tenant

logger = structlog.get_logger(__name__)

#: Rows per sweep, bounded so a first sweep over years of payloads drains across
#: passes rather than holding locks through one statement.
BATCH_SIZE = 5_000


async def sweep(session: AsyncSession, *, limit: int = BATCH_SIZE) -> int:
    """Delete raw deliveries past their tenant's retention window; returns rows removed."""
    cutoff = func.now() - func.make_interval(0, 0, 0, Tenant.retention_days)

    # Selected then deleted by id: `DELETE ... USING ... LIMIT` is not valid
    # PostgreSQL.
    expired = (
        select(WebhookDelivery.id)
        .join(Tenant, Tenant.id == WebhookDelivery.tenant_id)
        .where(WebhookDelivery.created_at < cutoff)
        .order_by(WebhookDelivery.created_at)
        .limit(limit)
        # skip_locked so two workers sweeping at once do not contend.
        .with_for_update(skip_locked=True)
    )

    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(WebhookDelivery).where(WebhookDelivery.id.in_(expired.scalar_subquery()))
        ),
    )
    removed = int(result.rowcount or 0)
    await session.commit()

    if removed:
        await logger.ainfo("retention.swept", removed=removed, capped=removed >= limit)
    return removed
