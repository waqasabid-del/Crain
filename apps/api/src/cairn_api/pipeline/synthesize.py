"""Stage 4 — synthesis: facts become prose, the only premium-model stage
(md/09 §5-7). Four gates, each dropping rather than editing: referenced facts
exist, span verification (§5.2), guardrails, hedging (only downward)."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from cairn_api import telemetry
from cairn_api.domain import Certainty, weakest_certainty
from cairn_api.pipeline import guardrails, hedging, prompts, verify
from cairn_api.pipeline.facts import Fact
from cairn_api.pipeline.provider import ModelProvider

logger = structlog.get_logger(__name__)

MAX_FACTS = 40  # item ceiling, on top of retrieval's token budget (md/09 §4.2)

INSTRUCTION = """\
Write a short brief for a founder about their team's week, using only the facts
listed in the data block.

Rules:
- Every claim must reference the fact ids it comes from. Reference only ids in
  the block. If you cannot reference it, do not write it.
- Say what happened. Never evaluate a person, rank people, compare them, or
  suggest how work should be allocated.
- Facts marked "observed" must be written with light hedging. Facts marked
  "suggested" must be written with explicit hedging — "it sounded like", "it
  appears that". Facts marked "verified" are stated plainly.
- Blockers and open questions matter more to the reader than volume of activity.
- **The facts are listed oldest to newest, and the newest are the news.** When
  there are more facts than a short brief can carry, cover the most recent work
  first and let the oldest go - a brief that repeats last week and omits
  yesterday is stale on arrival, which is the one failure a daily brief cannot
  survive.
- **"There is not enough here to write a brief" is a correct and expected
  answer, not a failure.** A week with nothing in it should produce no claims at
  all - reply with an empty claims list and say so in the narrative. But this is
  about *empty weeks*, not modest ones: if even one fact records something that
  happened, write the claim for it.
- **Inventing a claim is the worst thing you can do here** — worse than saying
  nothing, and worse than an incomplete brief. A reader who is told nothing
  happened can go and look; a reader given a plausible sentence about something
  that did not happen cannot.
- When the data block does not name who did something, **write the claim without
  a person in it** - "the billing migration may slip" is a real claim even when
  nobody knows who said it. Drop the *who*, never the *what*.
- The line is between something *happening* and somebody *musing*. A reported
  event, outcome or slip is a claim even unattributed. A floated thought from
  nobody in particular - "we should probably...", "maybe we ought to" - is not
  an event and gets no claim: writing it up would put a stray remark on the
  record as if the team had decided it.
- **Use the facts' own words for names of things.** Write "PR #312" if the fact
  says "PR #312" - not "a pull request". Every claim is checked word-by-word
  against its cited facts, and a synonym or expansion reads as an invention and
  is dropped.

Reply with JSON only:
{"narrative": "...", "claims": [{"text": "...", "fact_ids": ["..."],
                                "certainty": "verified|observed|suggested"}]}
"""


@dataclass(frozen=True, slots=True)
class BriefClaim:
    """One sentence in a brief, with its certainty and citations."""

    text: str
    certainty: Certainty
    fact_ids: tuple[uuid.UUID, ...]

    citations: tuple[str, ...]
    credits: tuple[str, ...] = ()
    hedged_by_system: bool = False


@dataclass(frozen=True, slots=True)
class Suppression:
    text: str
    reason: str


@dataclass
class Brief:
    narrative: str = ""
    claims: list[BriefClaim] = field(default_factory=list)
    suppressed: list[Suppression] = field(default_factory=list)
    abstained: bool = False


async def synthesize(
    provider: ModelProvider,
    *,
    facts: list[Fact],
    period: str = "this week",
    max_facts: int | None = None,
) -> Brief:
    """`max_facts` overrides `MAX_FACTS` per-call, keeping this module pure."""
    with telemetry.stage("synthesis"):
        if not facts:
            return Brief(
                abstained=True,
                narrative="There is not enough activity this period to summarise.",
            )

        usable = facts[: max_facts if max_facts is not None else MAX_FACTS]
        by_id = {fact.id: fact for fact in usable}

        request = prompts.build(
            INSTRUCTION.replace("their team's week", f"their team's {period}"),
            _render(usable),
        )

        try:
            response = await provider.complete(request)
        except Exception as exc:
            await logger.aerror("synthesize.provider_failed", error=str(exc))
            return Brief(
                abstained=True,
                narrative="This brief could not be generated. No summary is available.",
            )

        return _assemble(response.text, by_id)


def _render(facts: list[Fact]) -> str:
    lines = []
    for fact in facts:
        people = f" [{', '.join(fact.people)}]" if fact.people else ""
        lines.append(
            f"({fact.id}) [{fact.kind.value}] [{fact.certainty.value}]{people} {fact.statement}"
        )
    return "\n".join(lines)


def _assemble(text: str, by_id: dict[uuid.UUID, Fact]) -> Brief:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return Brief(
            abstained=True,
            narrative="This brief could not be generated. No summary is available.",
        )

    if not isinstance(payload, dict):
        return Brief(abstained=True)

    brief = Brief()
    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list):
        raw_claims = []

    for raw in raw_claims:
        claim, reason = _build_claim(raw, by_id)
        if claim is None:
            brief.suppressed.append(Suppression(text=_summarise(raw), reason=reason))
            continue
        brief.claims.append(claim)

    narrative = payload.get("narrative")
    brief.narrative = _narrative(narrative, brief)
    brief.abstained = not brief.claims

    if brief.suppressed:
        _log_suppressions(brief)
    return brief


def _log_suppressions(brief: Brief) -> None:
    logger.warning(
        "synthesize.claims_suppressed",
        count=len(brief.suppressed),
        reasons=[item.reason for item in brief.suppressed][:5],
    )


def _summarise(raw: Any) -> str:
    if isinstance(raw, dict) and isinstance(raw.get("text"), str):
        return str(raw["text"])[:200]
    return "<malformed claim>"


def _build_claim(raw: Any, by_id: dict[uuid.UUID, Fact]) -> tuple[BriefClaim | None, str]:
    if not isinstance(raw, dict):
        return None, "not an object"

    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        return None, "no text"
    text = text.strip()

    raw_ids = raw.get("fact_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, "cited no facts"

    facts: list[Fact] = []
    for value in raw_ids:
        try:
            fact_id = uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return None, f"malformed fact id {value!r}"
        fact = by_id.get(fact_id)
        if fact is None:
            return None, f"referenced a fact that was not supplied ({value})"
        facts.append(fact)

    support = verify.check(text, [fact.statement for fact in facts])
    if not support.supported:
        missing = ", ".join(support.unsupported_terms[:5])
        return None, f"not supported by its cited facts (unsupported: {missing})"

    violations = guardrails.inspect(text)
    if violations:
        return None, "; ".join(v.detail for v in violations)

    certainty = weakest_certainty(*(fact.certainty for fact in facts))
    hedged = hedging.apply(text, certainty)

    return (
        BriefClaim(
            text=hedged,
            certainty=certainty,
            fact_ids=tuple(fact.id for fact in facts),
            citations=tuple(
                dict.fromkeys(ref.evidence_id for fact in facts for ref in fact.sources)
            ),
            credits=tuple(dict.fromkeys(person for fact in facts for person in fact.people)),
            hedged_by_system=hedged != text,
        ),
        "",
    )


#: A fact id, as it appears when a model puts one in prose. Optionally wrapped
#: in the brackets it usually arrives in, with the space before them, so that
#: removing it leaves a sentence rather than a gap and a stray full stop.
_LEAKED_ID = re.compile(
    r"\s*[(\[]?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[)\]]?",
    re.IGNORECASE,
)


def _strip_identifiers(text: str) -> str:
    """Remove fact ids from prose a person reads.

    Claims carry citations structurally, so an id in the narrative is never
    load-bearing - it is the model referencing the data block it was shown. A
    founder should not meet a database key in the middle of a sentence, and the
    fix is removal rather than a prompt rule, because this is a thing that must
    not happen rather than a thing that should be rare.
    """
    cleaned = _LEAKED_ID.sub("", text)
    # Collapse the double spaces a mid-sentence removal leaves behind.
    return re.sub(r"[ 	]{2,}", " ", cleaned).strip()


def _narrative(narrative: Any, brief: Brief) -> str:
    if not isinstance(narrative, str) or not narrative.strip():
        return " ".join(claim.text for claim in brief.claims)

    text = _strip_identifiers(narrative.strip())
    if not text:
        return " ".join(claim.text for claim in brief.claims)
    if guardrails.inspect(text):
        brief.suppressed.append(Suppression(text=text, reason="narrative tripped a guardrail"))
        return " ".join(claim.text for claim in brief.claims)

    return text
