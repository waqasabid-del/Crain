"""Spans and metrics, with a no-op default.

OpenTelemetry's API is a no-op until an SDK is installed into it, which is
exactly the local behaviour wanted: instrumentation runs everywhere, costs
nothing until configured, and needs no branch at the call site.

`stage()` is the only span helper the pipeline uses. It stamps the outcome and a
safe error category on the way out, so a failed stage is queryable without
anybody remembering to record it.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import structlog
from opentelemetry import metrics, trace
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import Status, StatusCode

from cairn_api.telemetry.attributes import UnsafeAttributeError, safe

logger = structlog.get_logger(__name__)

tracer = trace.get_tracer("cairn.pipeline")
meter = metrics.get_meter("cairn.pipeline")

#: How long a stage took. A histogram rather than a gauge: the question is "how
#: slow is the slow end", and an average hides it.
stage_duration = meter.create_histogram(
    "cairn.stage.duration", unit="ms", description="Wall time per pipeline stage"
)

stage_failures = meter.create_counter(
    "cairn.stage.failures", description="Pipeline stages that ended in an error"
)

model_calls = meter.create_counter("cairn.model.calls", description="Model invocations")

model_tokens = meter.create_counter("cairn.model.tokens", description="Tokens billed")

model_cost = meter.create_counter(
    "cairn.model.cost", unit="microdollars", description="Model spend"
)

queue_depth = meter.create_counter(
    "cairn.queue.events", description="Queue publishes, receipts, retries and dead letters"
)

#: Dead letters, on their own counter.
#:
#: Separate from `cairn.queue.events` on purpose. A dead letter is the one queue
#: outcome an operator pages on, and an alert written against the general
#: counter has to filter on an attribute — which means it breaks silently the
#: first time an outcome is renamed, and cannot be given a different retention
#: or a different route from the ordinary publish/ack traffic it is buried in.
#: This is the series `docs/OPERATIONS.md` alerts on: warn on any increase, page
#: above five in an hour.
dead_letters = meter.create_counter(
    "cairn.queue.dead_letters",
    description="Jobs that failed permanently and were set aside for investigation",
)

evaluation_results = meter.create_counter(
    "cairn.evaluation.results", description="Evaluation outcomes by result and failure mode"
)


def error_category(error: BaseException) -> str:
    """A class name, never a message.

    An exception's message routinely contains the thing that broke — a row, an
    address, a fragment of a payload. The type is the part that is safe and the
    part an operator groups by.
    """
    return type(error).__name__


#: Categories for a dead letter whose reason is not an exception type.
_UNCATEGORISED = "other"
_NO_REASON = "unknown"

#: Reasons a queue writes itself rather than deriving from an exception.
_LITERAL_CATEGORIES: frozenset[str] = frozenset({"undecodable"})

#: What an exception class name looks like. Length-bounded so a category can
#: never be a sentence, even a short one.
_CLASS_NAME = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def dead_letter_category(reason: str | None) -> str:
    """Reduce a dead-letter reason to a bounded, exportable category.

    A reason is a free string — `worker.py` builds it as ``f"{type(exc).__name__}:
    {exc}"``, and an exception message routinely quotes the row that broke. The
    full text belongs in the durable row and the structured log, both of which
    live under the product's retention and deletion promises; a metric label
    does not, and a label is also where unbounded cardinality goes to kill a
    time-series database.

    So only the leading segment is considered, and only if it looks like an
    exception class: an identifier ending in `Error` or `Exception`. Everything
    else becomes `other`. That is deliberately conservative — an oddly named
    exception is filed as `other` rather than risking a label like `Priya` from
    a reason somebody assembled by hand — and it is *stable*: two failures of
    the same type categorise identically however different their messages.
    """
    if not reason or not reason.strip():
        return _NO_REASON

    head = reason.split(":", 1)[0].strip()
    if head in _LITERAL_CATEGORIES:
        return head
    if _CLASS_NAME.match(head) and head.endswith(("Error", "Exception")):
        return head
    return _UNCATEGORISED


def _attributes(values: dict[str, Any] | None) -> dict[str, Any]:
    """Validated attributes, or none at all.

    A span with an unsafe attribute is dropped to an empty one rather than
    raising into the caller: telemetry must not be able to fail the work it
    describes. The refusal is logged, loudly, because it is a bug.
    """
    try:
        return safe(values)
    except UnsafeAttributeError as error:
        logger.error("telemetry.unsafe_attribute", detail=str(error))
        return {}


@contextmanager
def stage(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Trace one pipeline stage."""
    values = _attributes({"stage": name, **attributes})
    started = time.perf_counter()

    # `record_exception` and `set_status_on_exception` are off deliberately.
    # Both write the exception's message and stack trace onto the span, and an
    # exception message routinely contains the row that broke — a statement, an
    # address, a fragment of payload. The category is recorded instead.
    with tracer.start_as_current_span(
        f"cairn.{name}",
        attributes=values,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as error:
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("outcome", "error")
            span.set_attribute("error_category", error_category(error))
            stage_failures.add(1, {**values, "error_category": error_category(error)})
            raise
        else:
            span.set_attribute("outcome", "ok")
        finally:
            stage_duration.record((time.perf_counter() - started) * 1000, values)


@asynccontextmanager
async def astage(name: str, **attributes: Any) -> AsyncIterator[trace.Span]:
    """`stage`, for async callers."""
    with stage(name, **attributes) as span:
        yield span


def record_model_call(
    *,
    model: str,
    provider: str,
    live: bool,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_micros: int = 0,
    outcome: str = "ok",
) -> None:
    """One model invocation, as numbers.

    The prompt and the response are deliberately absent — see `attributes.py`.
    """
    values = _attributes({"model": model, "provider": provider, "live": live, "outcome": outcome})
    model_calls.add(1, values)
    if tokens_in or tokens_out:
        model_tokens.add(tokens_in + tokens_out, values)
    if cost_micros:
        model_cost.add(cost_micros, values)


def record_queue_event(*, job_type: str, outcome: str, priority: str | None = None) -> None:
    """A publish, a receipt, a retry or a dead letter."""
    queue_depth.add(
        1, _attributes({"job_type": job_type, "outcome": outcome, "priority": priority})
    )


def record_dead_letter(*, job_type: str, reason: str | None, priority: str | None = None) -> None:
    """One job that will not be retried again.

    Takes the raw reason and reduces it here rather than accepting a category
    from the caller: `error_category` is an allow-listed *name*, so a caller
    handed the choice could put the whole reason string behind it and the
    allow-list would pass it. Reduction at the only place that writes the
    counter is what makes "the raw reason never reaches telemetry" a property of
    the code rather than a rule people remember.
    """
    dead_letters.add(
        1,
        _attributes(
            {
                "job_type": job_type,
                "error_category": dead_letter_category(reason),
                "priority": priority,
            }
        ),
    )


def record_evaluation(*, result: str, failure_mode: str | None = None) -> None:
    """One graded case."""
    evaluation_results.add(
        1, _attributes({"evaluation_result": result, "failure_mode": failure_mode})
    )


def current_trace_context() -> dict[str, str]:
    """The W3C headers that link a later span to this one.

    Carried in the job envelope so a worker's spans join the request that
    queued the work, rather than starting a second unrelated trace.
    """
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


@contextmanager
def linked_to(carrier: dict[str, str] | None) -> Iterator[None]:
    """Continue the trace a carrier describes."""
    if not carrier:
        yield
        return

    from opentelemetry.context import attach, detach

    token = attach(extract(carrier))
    try:
        yield
    finally:
        detach(token)
