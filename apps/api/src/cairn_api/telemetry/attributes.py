"""What a span or metric is allowed to carry.

Telemetry leaves the product. It goes to an exporter, a vendor, a dashboard and
a retention policy none of which are covered by the promises in md/05 — so the
rule here is an allow-list, not a deny-list. A deny-list of "prompt, statement,
quote" fails the first time somebody adds an attribute nobody thought to ban.

Every attribute is a *shape*: an identifier, a category, a number, a duration.
None of them is content. A tenant id is safe because it names a customer without
describing them; a statement is not, whatever it says.
"""

from __future__ import annotations

from typing import Any

#: Attributes any span or metric may carry.
#:
#: Adding to this list is a deliberate act. The question to ask is not "is this
#: useful" but "would this still be safe in an exporter we do not control, kept
#: for a year, read by somebody who has never seen md/05".
ALLOWED: frozenset[str] = frozenset(
    {
        # Who and what, by identifier only.
        "tenant_id",
        "job_id",
        "job_type",
        "delivery_id",
        "session_id",
        # One unit of work, from the webhook that started it to the brief it
        # produced. Allowed because it is opaque by construction — 32 hex
        # characters minted from `uuid4`, derived from nothing, describing
        # nobody — and `telemetry/correlation.py` enforces that shape on any id
        # that arrives from storage rather than being generated here. It names a
        # path without saying anything about what travelled it.
        "correlation_id",
        # Where in the pipeline.
        "stage",
        "source",
        "feature",
        "priority",
        "region",
        # The model boundary.
        "model",
        "provider",
        "model_version",
        "tokens_in",
        "tokens_out",
        "cost_micros",
        "live",
        # How it went.
        "outcome",
        "error_category",
        "attempt",
        "duration_ms",
        "count",
        "queue_depth",
        "dead_lettered",
        # Evaluation.
        "evaluation_result",
        "failure_mode",
        "score_bucket",
    }
)


class UnsafeAttributeError(ValueError):
    """An attribute outside the allow-list reached telemetry."""


def safe(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Validate attributes, or refuse them.

    Raises rather than dropping. A silently dropped attribute is a span that
    looks complete and is missing the field somebody is debugging with; a raised
    error is caught in one place (`spans.py`) and turns into a log line naming
    the offender.
    """
    if not attributes:
        return {}

    unknown = set(attributes) - ALLOWED
    if unknown:
        msg = f"attributes outside the telemetry allow-list: {sorted(unknown)}"
        raise UnsafeAttributeError(msg)

    return {key: value for key, value in attributes.items() if value is not None}
