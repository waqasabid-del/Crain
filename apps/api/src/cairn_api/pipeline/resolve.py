"""Stage 3 — resolve. Deterministic, and that is the whole point.

Trust boundary (md/09 §6.2): no model call, since a model asked which of two contradictory facts is current answers unreliably and unrepeatably (md/09 §2). Three jobs: deduplication, supersession (facts marked, never deleted — md/12 §6, md/09 §3.2), and person-mention resolution (unambiguous matches only). Thresholds below are tuned toward the recoverable failure: a missed merge is a visible duplicate; a wrong merge destroys a fact invisibly.
"""

from __future__ import annotations

import enum
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cairn_api.domain import Certainty, strongest_certainty
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef

# --- Text normalisation ---

_WORD = re.compile(r"[a-z0-9][a-z0-9'#/_.-]*")

#: Words carrying no subject information; kept small so it doesn't remove distinguishing words.
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
    ]
)

#: Subject-state words, removed only from the subject key so "blocked on X" and "unblocked X" share a subject.
_STATE_WORDS = frozenset(
    [
        "blocked",
        "unblocked",
        "blocking",
        "resolved",
        "resolving",
        "unresolved",
        "shipped",
        "shipping",
        "ships",
        "merged",
        "merging",
        "delivered",
        "delivering",
        "delayed",
        "deferred",
        "paused",
        "resumed",
        "started",
        "starting",
        "finished",
        "completed",
        "complete",
        "done",
        "reverted",
        "reverting",
        "decided",
        "deciding",
        "chose",
        "chosen",
        "choosing",
        "picked",
        "selected",
        "agreed",
        "rejected",
        "dropped",
        "abandoned",
        "waiting",
        "pending",
        "progress",
        "ongoing",
        "continues",
        "fixed",
        "fixing",
    ]
)

#: Negations/qualifiers never discarded as stopwords, so "will not use X" can't collapse onto "will use X".
_POLARITY = frozenset({"no", "not", "never", "cannot", "without", "instead", "unless"})


def tokens(text: str) -> frozenset[str]:
    """Content tokens: internal punctuation kept, trailing punctuation
    stripped (`auth.py` stays one token; `store.` matches `store`)."""
    found = (word.rstrip(".-_/'#") for word in _WORD.findall(text.lower()))
    return frozenset(
        word for word in found if word in _POLARITY or (word not in _STOPWORDS and len(word) > 1)
    )


def subject_key(text: str) -> frozenset[str]:
    """What a statement is *about*, with its state removed — lets a later
    fact supersede an earlier one about the same subject."""
    return frozenset(word for word in tokens(text) if word not in _STATE_WORDS)


def similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard overlap. 1.0 identical, 0.0 disjoint."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# --- The rules ---

#: Overlap for same-kind statements to be one fact; 0.7 not 0.5, or similar-wording deliveries would merge.
MERGE_THRESHOLD = 0.7

#: Absolute (not proportional) shared-token floor, so short statements don't merge on coincidence.
MIN_SHARED_TOKENS = 3

#: Subject containment (not Jaccard); lower than `MERGE_THRESHOLD` since a wrong supersession is reversible.
SUBJECT_CONTAINMENT = 0.6

#: Minimum shared subject tokens, so one common word can't equate two subjects.
MIN_SHARED_SUBJECT_TOKENS = 2

#: Window for two mentions to be one fact rather than a later revisit.
MERGE_WINDOW = timedelta(days=14)

#: "Incoming K supersedes an open fact of kind in SUPERSEDES[K], same subject." Nothing supersedes `DELIVERY`.
SUPERSEDES: dict[FactKind, frozenset[FactKind]] = {
    FactKind.DECISION: frozenset({FactKind.DECISION, FactKind.OPEN_QUESTION}),
    FactKind.DELIVERY: frozenset({FactKind.IN_PROGRESS, FactKind.BLOCKER}),
    FactKind.BLOCKER: frozenset({FactKind.BLOCKER}),
    FactKind.IN_PROGRESS: frozenset({FactKind.IN_PROGRESS}),
    FactKind.OPEN_QUESTION: frozenset({FactKind.OPEN_QUESTION}),
}


class Outcome(enum.StrEnum):
    """What resolution decided about one incoming fact."""

    NEW = "new"
    MERGED = "merged"

    #: Later statement about a recorded subject; earlier fact marked superseded, never deleted (md/12 §6).
    SUPERSEDES = "supersedes"

    #: Two facts disagree with no way to order them — both kept, neither marked.
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class Decision:
    """What to do with one incoming fact, and why."""

    fact: Fact
    outcome: Outcome

    #: Set only for the matching `outcome` (MERGED/SUPERSEDES/CONFLICT).
    merged_into: uuid.UUID | None = None
    supersedes: uuid.UUID | None = None
    conflicts_with: uuid.UUID | None = None

    #: Plain-language justification — the audit trail behind a disputed brief.
    reason: str = ""


@dataclass
class ResolutionPlan:
    """Every decision for one batch, plus the facts as they should be stored."""

    decisions: list[Decision] = field(default_factory=list)

    @property
    def to_store(self) -> list[Fact]:
        """New and superseding facts. Merged ones exist already."""
        return [
            d.fact
            for d in self.decisions
            if d.outcome in {Outcome.NEW, Outcome.SUPERSEDES, Outcome.CONFLICT}
        ]

    @property
    def to_supersede(self) -> list[tuple[uuid.UUID, Fact]]:
        """`(existing fact id, the fact replacing it)`."""
        return [
            (d.supersedes, d.fact)
            for d in self.decisions
            if d.outcome is Outcome.SUPERSEDES and d.supersedes is not None
        ]

    @property
    def merges(self) -> list[tuple[uuid.UUID, Fact]]:
        """`(existing fact id, the merged result to write back)`."""
        return [
            (d.merged_into, d.fact)
            for d in self.decisions
            if d.outcome is Outcome.MERGED and d.merged_into is not None
        ]


def resolve(incoming: Sequence[Fact], existing: Sequence[Fact] = ()) -> ResolutionPlan:
    """Reconcile a batch of extracted facts against what is already known.
    `existing` must be currently-valid facts only; the batch also resolves
    against itself."""
    # Stable sort by occurrence, undated first; not by fact id (random, non-reproducible ties).
    ordered = sorted(
        incoming,
        key=lambda f: f.occurred_at.timestamp() if f.occurred_at else float("-inf"),
    )

    plan = ResolutionPlan()
    pool: list[Fact] = list(existing)  # accepted batch facts join the pool too

    for candidate in ordered:
        decision = _classify(candidate, pool)
        plan.decisions.append(decision)

        if decision.outcome is Outcome.MERGED:
            pool = [decision.fact if f.id == decision.merged_into else f for f in pool]
        elif decision.outcome is Outcome.SUPERSEDES:
            pool = [f for f in pool if f.id != decision.supersedes]
            pool.append(decision.fact)
        else:
            pool.append(decision.fact)

    return plan


def _classify(candidate: Fact, pool: Sequence[Fact]) -> Decision:
    """Decide one fact against the pool. Duplicates checked before
    supersession — a restatement scores high on both, and treating it as
    supersession would mark a fact superseded by itself."""
    candidate_tokens = tokens(candidate.statement)
    candidate_subject = subject_key(candidate.statement)

    duplicate = _find_duplicate(candidate, candidate_tokens, pool)
    if duplicate is not None:
        return Decision(
            fact=_merge(duplicate, candidate),
            outcome=Outcome.MERGED,
            merged_into=duplicate.id,
            reason=(
                f"same {candidate.kind.value} already recorded from "
                f"{', '.join(sorted({s.source for s in duplicate.sources}))}"
            ),
        )

    superseded = _find_superseded(candidate, candidate_subject, pool)
    if superseded is not None:
        earlier, ordered_in_time = superseded
        if not ordered_in_time:
            return Decision(
                fact=candidate,
                outcome=Outcome.CONFLICT,
                conflicts_with=earlier.id,
                reason=(
                    "contradicts an existing fact about the same subject with no "
                    "way to order the two in time"
                ),
            )
        return Decision(
            fact=candidate,
            outcome=Outcome.SUPERSEDES,
            supersedes=earlier.id,
            reason=(
                f"later {candidate.kind.value} about the same subject as an "
                f"earlier {earlier.kind.value}"
            ),
        )

    return Decision(fact=candidate, outcome=Outcome.NEW, reason="no matching fact on record")


def _find_duplicate(
    candidate: Fact, candidate_tokens: frozenset[str], pool: Iterable[Fact]
) -> Fact | None:
    """The best same-kind match above the merge bar, or nothing. *Best*, not
    first, so the outcome doesn't depend on storage order."""
    best: Fact | None = None
    best_score = 0.0

    for other in pool:
        if other.kind is not candidate.kind:
            continue  # cross-kind merge would fold a blocker into a delivery and lose it
        if not _within_window(candidate, other):
            continue

        other_tokens = tokens(other.statement)
        if _polarity(candidate_tokens) != _polarity(other_tokens):
            continue  # "will use X" vs "will not use X" must never merge

        shared = candidate_tokens & other_tokens
        if len(shared) < MIN_SHARED_TOKENS:
            continue

        score = similarity(candidate_tokens, other_tokens)
        if score >= MERGE_THRESHOLD and score > best_score:
            best, best_score = other, score

    return best


def _find_superseded(
    candidate: Fact, candidate_subject: frozenset[str], pool: Iterable[Fact]
) -> tuple[Fact, bool] | None:
    """The open fact this one replaces, and whether the two can be ordered.
    `ordered=False` means subjects match but timestamps don't order them —
    a contradiction to surface, not resolve."""
    best: Fact | None = None
    best_overlap = 0.0
    best_ordered = False

    for other in pool:
        if other.kind not in SUPERSEDES.get(candidate.kind, frozenset()):
            continue

        if not _same_people(candidate, other):
            continue  # different people named = different situations, not a state change

        other_subject = subject_key(other.statement)
        overlap = _containment(candidate_subject, other_subject)
        if (
            overlap < SUBJECT_CONTAINMENT
            or len(candidate_subject & other_subject) < MIN_SHARED_SUBJECT_TOKENS
        ):
            continue

        ordered = (
            candidate.occurred_at is not None
            and other.occurred_at is not None
            and candidate.occurred_at > other.occurred_at
        )
        if overlap > best_overlap:
            best, best_overlap, best_ordered = other, overlap, ordered

    if best is None:
        return None
    return best, best_ordered


def _polarity(token_set: frozenset[str]) -> frozenset[str]:
    """The negations present in a statement. Two facts merge only if these match."""
    return token_set & _POLARITY


def _containment(left: frozenset[str], right: frozenset[str]) -> float:
    """How much of the smaller set the larger one contains — used for
    subjects instead of Jaccard, since a restatement is often a different length."""
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def _same_people(left: Fact, right: Fact) -> bool:
    """Whether two facts can name the same person's situation: if both name
    people, at least one must match; if either names nobody, passes (documented gap)."""
    if not left.people or not right.people:
        return True
    return bool({p.lower() for p in left.people} & {p.lower() for p in right.people})


def _within_window(left: Fact, right: Fact) -> bool:
    """Whether two facts are close enough in time to be the same one. An
    undated fact is compared to everything, else it would accumulate as
    silent duplicates."""
    if left.occurred_at is None or right.occurred_at is None:
        return True
    return abs(left.occurred_at - right.occurred_at) <= MERGE_WINDOW


def _merge(existing: Fact, incoming: Fact) -> Fact:
    """Fold a duplicate into the fact already on record. The existing
    identity and statement survive; the newer wording is not more accurate
    for being second."""
    sources = list(existing.sources)
    seen = {(s.source, s.evidence_id) for s in sources}
    for ref in incoming.sources:
        if (ref.source, ref.evidence_id) not in seen:
            sources.append(ref)
            seen.add((ref.source, ref.evidence_id))

    people = list(existing.people)
    people.extend(p for p in incoming.people if p not in people)

    return existing.model_copy(
        update={
            "sources": sources,
            "people": people,
            "certainty": _corroborated(existing, incoming, sources),
            "occurred_at": _earliest(existing.occurred_at, incoming.occurred_at),
        }
    )


def _corroborated(existing: Fact, incoming: Fact, sources: list[SourceRef]) -> Certainty:
    """Certainty after a merge: stronger tier, plus one promotion —
    `suggested` corroborated by a 2nd source becomes `observed`. Never `verified` (requires direct evidence)."""
    strongest = strongest_certainty(existing.certainty, incoming.certainty)
    if strongest is Certainty.SUGGESTED and len({s.source for s in sources}) > 1:
        return Certainty.OBSERVED
    return strongest


def _earliest(left: datetime | None, right: datetime | None) -> datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)
