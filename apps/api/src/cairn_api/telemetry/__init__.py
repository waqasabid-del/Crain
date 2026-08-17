"""Telemetry: spans, metrics, and the allow-list of what they may carry."""

from cairn_api.telemetry.correlation import (
    correlated,
    correlation_id_for_new_work,
    current_correlation_id,
    new_correlation_id,
)
from cairn_api.telemetry.spans import (
    astage,
    current_trace_context,
    dead_letter_category,
    error_category,
    linked_to,
    record_dead_letter,
    record_evaluation,
    record_model_call,
    record_queue_event,
    stage,
)

__all__ = [
    "astage",
    "correlated",
    "correlation_id_for_new_work",
    "current_correlation_id",
    "current_trace_context",
    "dead_letter_category",
    "error_category",
    "linked_to",
    "new_correlation_id",
    "record_dead_letter",
    "record_evaluation",
    "record_model_call",
    "record_queue_event",
    "stage",
]
