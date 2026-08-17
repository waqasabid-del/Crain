"""The correlation id: one opaque name for one unit of work.

`traceparent` (see `spans.py`) links *spans*. It exists only while a tracer is
installed, which is a no-op locally and in any deployment without a collector,
and it is never written anywhere durable. So the question an operator actually
asks — "this webhook arrived at 14:02 and the brief is wrong; show me
everything that happened in between" — has no answer from trace context alone.

The correlation id answers it. It is generated at the true entry point (a
webhook receipt, or the origin of scheduled work), carried on the envelope
through the queue into the worker, bound into the logging context so every line
beneath it carries the id without being passed the value, and stamped on spans
alongside — never instead of — `traceparent`. `grep <correlation_id>` over the
log store reconstructs the path with no tracer involved at all.

**It is an identifier, never content.** The format is deliberately narrow:
lowercase hex, fixed length, no separators, nothing derived from a payload. That
is what makes it safe to add to the telemetry allow-list, and `coerce` is what
keeps it true for an id that arrived from somewhere less trusted than this
process — a queue row, a message attribute — where a "correlation id" field
could otherwise carry a customer's sentence into an exporter.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import structlog

#: Bound for the duration of one unit of work: a request, or a job on a worker.
#: A ContextVar rather than a parameter because the value has to reach envelopes
#: constructed several layers down (`JobEnvelope.correlation_id`'s default) in
#: code that has no reason to know about correlation at all.
_correlation_id: ContextVar[str | None] = ContextVar("cairn_correlation_id", default=None)

#: 32 lowercase hex characters. Anything else is not one of ours.
_SHAPE = re.compile(r"\A[0-9a-f]{32}\Z")


def new_correlation_id() -> str:
    """A fresh id. Opaque by construction — no tenant, no time, no content."""
    return uuid.uuid4().hex


def current_correlation_id() -> str | None:
    """The id of the unit of work in progress, if there is one."""
    return _correlation_id.get()


def correlation_id_for_new_work() -> str:
    """Inherit the ambient id, or start one.

    Inheriting is what ties a webhook to the understanding job a later handler
    publishes; starting one is what keeps scheduled and backfill work — which
    has no originating request — from being the case that has no id at all.
    """
    return _correlation_id.get() or new_correlation_id()


def coerce(raw: object) -> str | None:
    """A correlation id read from outside this process, or nothing.

    Queue rows and message attributes are storage, not truth: this value ends up
    in logs and on spans, so it is checked against the shape rather than
    trusted. A malformed one is discarded and the caller mints a fresh id — a
    unit of work with a new id is a small loss of continuity, where a unit of
    work carrying an arbitrary string into an exporter is a leak.
    """
    if not isinstance(raw, str) or not _SHAPE.match(raw):
        return None
    return raw


@contextmanager
def correlated(correlation_id: str | None = None) -> Iterator[str]:
    """Run a unit of work under an id, in the context and in the log.

    Both bindings are reset on the way out rather than cleared: a worker handles
    many jobs in one process, and a job that left its id behind would label the
    next one's logs with the previous one's path.
    """
    value = coerce(correlation_id) or new_correlation_id()
    token = _correlation_id.set(value)
    log_tokens = structlog.contextvars.bind_contextvars(correlation_id=value)
    try:
        yield value
    finally:
        structlog.contextvars.reset_contextvars(**log_tokens)
        _correlation_id.reset(token)


def begin(correlation_id: str | None = None) -> str:
    """Start a unit of work at a request boundary and return its id.

    The un-scoped form of `correlated`, for a request handler that cannot wrap
    its own body. Safe there because each request runs in its own task with its
    own copy of the context, and `api/middleware.py` clears the logging context
    at the start of every request.
    """
    value = coerce(correlation_id) or new_correlation_id()
    _correlation_id.set(value)
    structlog.contextvars.bind_contextvars(correlation_id=value)
    return value
