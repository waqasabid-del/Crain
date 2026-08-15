"""Language discipline: the certainty tier has to be audible in the sentence
(md/09 §5.5; tiers in md/05 §A.2.2). Only ever weakens a claim, never
strengthens or drops one — unlike `guardrails.py`'s reject-don't-repair,
adding "it looks like" can't make output less true.
"""

from __future__ import annotations

import re

from cairn_api.domain import Certainty

#: Phrases that count as hedging.
_HEDGE_PATTERNS = (
    r"\bit (?:looks|looked|seems|seemed|sounds|sounded) like\b",
    r"\bappears? to\b",
    r"\bappeared to\b",
    r"\bmay (?:be|have)\b",
    r"\bmight (?:be|have)\b",
    r"\bseems? to\b",
    r"\bsuggests? that\b",
    r"\bbased on (?:a|one) (?:meeting|mention|comment|transcript)\b",
    r"\breportedly\b",
    r"\bappears\b",
    r"\bpossibly\b",
    r"\bappear to\b",
)

_HEDGED = re.compile("|".join(_HEDGE_PATTERNS), re.IGNORECASE)

#: Fallback prefix for a model that didn't hedge on its own.
_PREFIX = {
    Certainty.OBSERVED: "It appears that ",
    Certainty.SUGGESTED: "It sounded like ",
}

#: `VERIFIED` deliberately absent: hedging a merged pull request defeats hedging.
MUST_HEDGE = (Certainty.OBSERVED, Certainty.SUGGESTED)


def is_hedged(text: str) -> bool:
    return _HEDGED.search(text) is not None


def needs_hedging(text: str, certainty: Certainty) -> bool:
    return certainty in MUST_HEDGE and not is_hedged(text)


def apply(text: str, certainty: Certainty) -> str:
    """Idempotent: an already-hedged sentence is returned unchanged."""
    if not needs_hedging(text, certainty):
        return text

    prefix = _PREFIX[certainty]
    head, separator, tail = text.partition(" ")

    # Lowered only if capitalised for being first; a name (e.g. "Ali") keeps its case.
    if head.lower().strip(".,;:") in _SENTENCE_STARTERS:
        head = head[:1].lower() + head[1:]

    return f"{prefix}{head}{separator}{tail}"


_SENTENCE_STARTERS = frozenset(
    [
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "work",
        "it",
        "there",
        "they",
        "he",
        "she",
        "we",
        "our",
        "their",
        "his",
        "her",
    ]
)
