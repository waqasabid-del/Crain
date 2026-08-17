"""Structured logging.

JSON in deployed environments, human-readable locally. Cloud Logging parses JSON
lines into queryable fields; a formatted string is a blob you can only grep, and
"which tenant did this happen to" stops being answerable at exactly the moment
someone needs to know (md/17 §5, standard 5: *errors carry context*).

**Context is bound once and travels.** `structlog`'s contextvars integration
means a request handler binds `request_id` and `tenant_id` at the edge, and every
log line emitted anywhere beneath it carries them without being passed the
values. The alternative — threading a logger through call signatures — is what
makes people give up and log without context.

The two ids that travel this way are `request_id` (bound in `api/middleware.py`,
one HTTP request) and `correlation_id` (`telemetry/correlation.py`, one unit of
work — from the webhook that started it to the brief it produced, across
processes and across the queue in between). The second is what makes
`grep <correlation_id>` reconstruct a whole path rather than one hop of it.

**What must never be logged here** is as important as what is. No email
addresses, no session tokens, no request bodies. A log store has a different
retention policy, a different access model and a different deletion path from
the database, so anything written here escapes the GDPR erasure guarantees the
product makes (md/05 §B). Identifiers are UUIDs precisely so a log line can be
specific without being personal.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from cairn_api.config import Settings


def configure_logging(settings: Settings) -> None:
    """Set up structlog and route the standard library through it.

    Idempotent, so tests and a reloading dev server can call it repeatedly.

    Routing `logging` through structlog matters because the noisiest emitters in
    a FastAPI service — uvicorn, SQLAlchemy, alembic — use the standard library.
    Left alone they write plain text alongside JSON, and a log pipeline that has
    to parse two formats reliably parses neither.
    """
    render_json = settings.environment != "local"

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        # Exceptions become a `exception` field rather than a multi-line tail.
        # A traceback split across lines is a traceback the log aggregator
        # ingests as N unrelated entries.
        structlog.processors.format_exc_info,
    ]

    if render_json:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared,
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # uvicorn installs its own handlers and marks its loggers non-propagating,
    # so without this its access log bypasses everything above.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    # SQLAlchemy's engine logger emits full SQL with bound parameters at INFO
    # when echo is on. That is customer data in the log store, which is why
    # `database_echo` is refused outside local development — this is the second
    # line of that defence.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database_echo else logging.WARNING
    )
