"""The job runner: the only place a handler gets a database session, already tenant-scoped."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.tenancy import tenant_session
from cairn_api.jobs.envelope import JobEnvelope

logger = logging.getLogger(__name__)

#: Never an engine, session factory, or connection — only a scoped session.
type JobHandler = Callable[[AsyncSession, JobEnvelope], Awaitable[None]]


class UnknownJobTypeError(LookupError):
    """Raised, not logged-and-skipped — a dropped job looks like a completed one."""


class JobRegistry:
    """Not dynamic import by name — lets a queue writer execute arbitrary code (file 07 §4)."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str) -> Callable[[JobHandler], JobHandler]:
        """Raises ValueError if already registered rather than letting import order decide."""

        def decorator(handler: JobHandler) -> JobHandler:
            if job_type in self._handlers:
                msg = f"Job type {job_type!r} is already registered"
                raise ValueError(msg)
            self._handlers[job_type] = handler
            return handler

        return decorator

    def resolve(self, job_type: str) -> JobHandler:
        handler = self._handlers.get(job_type)
        if handler is None:
            msg = f"No handler registered for job type {job_type!r}"
            raise UnknownJobTypeError(msg)
        return handler

    def registered_types(self) -> frozenset[str]:
        return frozenset(self._handlers)

    def clear(self) -> None:
        self._handlers.clear()


registry = JobRegistry()


async def run_job(envelope: JobEnvelope, *, job_registry: JobRegistry | None = None) -> None:
    """The only sanctioned way to run a handler; errors propagate after rollback (md/06 §6B.2)."""
    active = job_registry if job_registry is not None else registry
    handler = active.resolve(envelope.job_type)

    logger.info(
        "job.start",
        extra={
            "job_id": str(envelope.job_id),
            "job_type": envelope.job_type,
            "tenant_id": str(envelope.tenant_id),
            "attempt": envelope.attempt,
        },
    )

    async with tenant_session(envelope.tenant_id) as session:
        await handler(session, envelope)

    logger.info(
        "job.complete",
        extra={
            "job_id": str(envelope.job_id),
            "job_type": envelope.job_type,
            "tenant_id": str(envelope.tenant_id),
        },
    )
