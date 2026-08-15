"""Stage 4 — synthesis: facts become prose, the only premium-model stage
(md/09 §5-7). Four gates, each dropping rather than editing: referenced facts
exist, span verification (§5.2), guardrails, hedging (only downward)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

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
- If the facts do not support a brief, say so instead of padding.

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


def _narrative(narrative: Any, brief: Brief) -> str:
    if not isinstance(narrative, str) or not narrative.strip():
        return " ".join(claim.text for claim in brief.claims)

    text = narrative.strip()
    if guardrails.inspect(text):
        brief.suppressed.append(Suppression(text=text, reason="narrative tripped a guardrail"))
        return " ".join(claim.text for claim in brief.claims)

    return text
