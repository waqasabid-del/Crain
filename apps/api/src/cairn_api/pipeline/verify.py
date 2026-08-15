"""Span verification: does the cited evidence support the claim?

Unsupported claims are suppressed, not caveated (md/09 §5.2). Deliberately not
a model — asking a model to grade its own output asks the suspect to grade
itself — so this is set arithmetic over synthesis's input facts. Catches an
invented subject/number/outcome, not a same-vocabulary reversal ("Postgres was
not chosen" vs. a fact saying it was) — that gap is covered upstream, since
Stage 3 refuses to merge across a polarity difference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Kept small: removing "not"/"without" would make a reversal look supported.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "they",
        "this",
        "to",
        "was",
        "were",
        "will",
        "with",
        "we",
        "our",
        "us",
        "also",
        "then",
        "than",
    ]
)

_WORD = re.compile(r"[a-z0-9][a-z0-9'#/_.-]*")

#: 0.6 is a stated compromise: full coverage would suppress good paraphrasing;
#: much less lets an invented clause ride a shared subject. Tuned toward
#: suppression — a suppressed true claim is recoverable, an admitted false one isn't.
MIN_SUPPORT = 0.6


@dataclass(frozen=True, slots=True)
class Support:
    supported: bool

    #: Internal only — never displayed, never a confidence score (md/05 §A.2.1).
    coverage: float

    unsupported_terms: tuple[str, ...] = ()


def content_words(text: str) -> set[str]:
    return {
        word.rstrip(".-_/'#")
        for word in _WORD.findall(text.lower())
        if word not in _STOPWORDS and len(word) > 1
    }


def check(claim: str, evidence: list[str]) -> Support:
    """Empty evidence is unsupported, never vacuously true."""
    claim_words = content_words(claim)
    if not claim_words:
        return Support(supported=False, coverage=0.0)

    if not evidence:
        return Support(
            supported=False,
            coverage=0.0,
            unsupported_terms=tuple(sorted(claim_words)),
        )

    supported_words: set[str] = set()
    for item in evidence:
        supported_words |= content_words(item)

    missing = claim_words - supported_words
    coverage = 1.0 - (len(missing) / len(claim_words))

    return Support(
        supported=coverage >= MIN_SUPPORT,
        coverage=coverage,
        unsupported_terms=tuple(sorted(missing)),
    )
