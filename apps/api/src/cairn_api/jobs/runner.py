"""The job runner — the single place tenant context is established.

**The design rule this file exists to enforce: a handler never opens its own
session.** It receives one, already scoped, from the runner. There is no code
path by which a handler can reach the database unscoped, because it is never
given the means to.

That is a structural guarantee rather than a convention. A convention ("remember
to call ``set_tenant_context``") is followed until someone is in a hurry; a
handler signature that only ever receives a scoped session cannot be got wrong
without deliberately importing the session factory, which review and the
architecture tests would both catch.

Failure is closed at three points:

1. **Parsing** — an envelope without a tenant fails validation (``envelope.py``).
2. **Dispatch** — an unknown job type raises rather than being ignored, because
   a silently dropped job is indistinguishable from one that succeeded.
3. **Execution** — if tenant context cannot be established, the job errors
   instead of running.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.tenancy import tenant_session
from cairn_api.jobs.envelope import JobEnvelope

logger = logging.getLogger(__name__)

#: A handler receives a tenant-scoped session and the envelope. It never
#: receives an engine, a session factory, or a connection.
type JobHandler = Callable[[AsyncSession, JobEnvelope], Awaitable[None]]


class UnknownJobTypeError(LookupError):
    """Raised when no handler is registered for a job type.

    Raising rather than logging-and-continuing is deliberate. A dropped job
    leaves no trace and looks identical to one that completed, which is how work
    silently disappears from a queue for weeks before anyone notices.
    """


class JobRegistry:
    """Maps job types to handlers.

    A registry rather than dynamic import by name: importing a module path from
    a queue message would let anything that can write to the queue execute
    arbitrary code (file 07 §4 covers the same class of risk for MCP).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str) -> Callable[[JobHandler], JobHandler]:
        """Register a handler for a job type.

        Raises:
            ValueError: If the job type is already registered. Silently
                replacing a handler would mean two modules disagreeing about
                what a job does, with the winner decided by import order.
        """

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
        """Reset the registry. Test support only."""
        self._handlers.clear()


#: Process-wide registry.
registry = JobRegistry()


async def run_job(envelope: JobEnvelope, *, job_registry: JobRegistry | None = None) -> None:
    """Execute one job inside its tenant's context.

    The only sanctioned way to run a handler. Everything a handler needs arrives
    through this function, which is what makes the isolation guarantee
    structural rather than advisory.

    Args:
        envelope: The validated job message.
        job_registry: Override for testing. Defaults to the process registry.

    Raises:
        UnknownJobTypeError: If no handler is registered for the job type.
        Exception: Whatever the handler raises, after rollback. Retry and
            dead-lettering are the queue's responsibility (md/06 §6B.2), not
            this function's — swallowing an error here would convert a failed
            job into a silently successful one.
    """
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

    # tenant_session raises if the tenant is missing and sets the database
    # context before the handler sees the session. A handler therefore cannot
    # execute a statement outside its tenant's scope.
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
