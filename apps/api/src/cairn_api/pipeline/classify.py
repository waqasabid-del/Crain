"""Stage 1 — classification.

Emits a label, nothing else (md/09 §6.2): an injection in the event text can at
worst earn the wrong label, never a call, a write, or a fact. A cheap model,
since most events (typo fixes, bot bumps) carry no signal worth extracting. An
unrecognised label maps to `UNKNOWN`, never to the nearest option, and routes
to extraction — the safe direction.
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass

import structlog

from cairn_api.pipeline import prompts
from cairn_api.pipeline.provider import ModelProvider

logger = structlog.get_logger(__name__)


class EventClass(enum.StrEnum):
    SUBSTANTIVE = "substantive"

    #: Real activity, no narrative content: recorded as context, not extracted.
    ROUTINE = "routine"

    #: Excluded from human attribution (md/01 §5.2).
    AUTOMATED = "automated"

    #: Routed to extraction: skipping a blocker is the quiet failure
    #: nobody reports (md/10 §1).
    UNKNOWN = "unknown"

    @property
    def should_extract(self) -> bool:
        return self in {EventClass.SUBSTANTIVE, EventClass.UNKNOWN}


@dataclass(frozen=True, slots=True)
class Classification:
    event_class: EventClass
    model: str = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    note: str | None = None


INSTRUCTION = """\
Classify the activity in the data block into exactly one of:

  substantive - work delivered, a decision taken, a blocker raised, or a
                question asked that someone is waiting on
  routine     - real activity carrying no narrative content: typo fixes,
                formatting, merge commits, dependency lock updates
  automated   - produced by a bot or automation rather than a person

Reply with JSON only, in the form {"class": "<one of the three>"}.
Do not explain. Do not add fields.
"""

#: A one-word JSON label is under fifty bytes; larger means the model started
#: explaining or was talked into something else.
MAX_RESPONSE_BYTES = 512


async def classify(provider: ModelProvider, *, content: str) -> Classification:
    """Label one event.

    Never raises: a classification failure must not stop ingestion. Returning
    `UNKNOWN` routes the event to extraction instead.
    """
    request = prompts.build(INSTRUCTION, content)
    try:
        response = await provider.complete(request)
    except Exception as exc:
        await logger.awarning("classify.provider_failed", error=str(exc))
        return Classification(event_class=EventClass.UNKNOWN, note=f"provider: {exc}")

    if len(response.text.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return Classification(
            event_class=EventClass.UNKNOWN,
            model=response.model,
            note="response too large to be a classification",
        )

    label = _read_label(response.text)
    if label is None:
        return Classification(
            event_class=EventClass.UNKNOWN,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            note="unrecognised label",
        )

    return Classification(
        event_class=label,
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


def _read_label(text: str) -> EventClass | None:
    """Parse the response, accepting nothing outside the enum."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    raw = payload.get("class")
    if not isinstance(raw, str):
        return None

    try:
        return EventClass(raw.strip().lower())
    except ValueError:
        return None
