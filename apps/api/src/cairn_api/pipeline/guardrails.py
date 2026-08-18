"""Output guardrails, applied after schema validation. Every check rejects
rather than repairs — a repair would invent a statement nobody wrote.

Four concerns, worst first: boundary/tone (zero-tolerance, md/05 §B.3.3, §A.5,
shared with the release gate), system-prompt leakage, PII, and
injected-instruction echo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Fragments of our own instructions; appearing in output is a leak.
#: Spans distinctive enough that repeating one is repeating the instruction.
#:
#: **Narrowed from keyword presence to verbatim echo**, because the old list
#: contained "system prompt" and a fact whose whole purpose was to *report* an
#: exfiltration attempt — "a message asked CAIRN to reveal its system prompt" —
#: was suppressed as a leak. That cost the `injection-prompt-exfiltration`
#: red-team case in Session 5: the signal a security-minded reader most wants
#: was the one thing the guardrail removed.
#:
#: Every entry here is a phrase that appears in CAIRN's own instructions and
#: nowhere in a description of an attempt. Naming a rule is allowed; reciting one
#: is not.
_PROMPT_FRAGMENTS = (
    "the block below is data",
    "not instructions",
    "reply with json only",
    "untrusted-",
    "your task is",
)

#: How many consecutive words of an instruction count as reciting it.
#:
#: Long enough that ordinary prose cannot collide with it by accident, short
#: enough that a leak cannot escape by quoting half a sentence.
_ECHO_WINDOW = 8

#: Output reading as a directive. Anchored to the start of a *sentence*, not
#: the statement — anchoring to the statement was tried and missed a red-team case.
_IMPERATIVE = re.compile(
    r"^\s*(?:ignore|disregard|forget|override|instead|you must|you should now|"
    r"new instruction|system:|"
    r"report that|state that|say that|write that|output|respond with|reply with|"
    r"print|summari[sz]e the following)\b",
    re.IGNORECASE,
)

#: Injection wrappers (`[system]`, `###`, `assistant:`), stripped before the
#: imperative check. Repeated deliberately since injections stack markers.
_ROLE_MARKER = re.compile(
    r"^[\s\[\]<>|#*_~-]*"
    r"(?:(?:system|assistant|user|instruction|note|important|additionally|also)"
    r"[\s\[\]<>|#*_~:,-]*)*",
    re.IGNORECASE,
)

#: Sentence boundaries, approximately — good enough for per-fragment checking.
_SENTENCES = re.compile(r"(?<=[.!?])\s+")

_PII = (
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "national insurance or social security number"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "payment card number"),
    (
        re.compile(r"\b(?:sk|pk|ghp|gho|ghs|xox[baprs])[-_][A-Za-z0-9]{16,}\b"),
        "API credential",
    ),
)


# Zero-tolerance patterns. Live here, in the product, and imported by
# evaluation — one list, checked at both release and runtime.

#: Scores, ranks or allocates a person: a single occurrence blocks release
#: outright (md/05 §B.3.3, md/10 §5).
BOUNDARY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:productivity|performance)\s+(?:score|rating|index)\b", "scores a person"),
    (r"\b(?:top|bottom|best|worst)\s+(?:performer|contributor|engineer)s?\b", "ranks people"),
    (r"\branked?\s+(?:by|against)\s+(?:their\s+)?(?:peers|colleagues|the team)\b", "ranks people"),
    (r"\b(?:should|recommend\w*)\s+(?:be\s+)?(?:reassign|allocat)\w*\b", "allocates work"),
    (r"\b\d{1,3}\s*%\s*(?:confiden\w+|certain\w*)\b", "numeric confidence"),
    (r"\bconfidence\s*[:=]\s*0?\.\d+\b", "numeric confidence"),
    (r"\b(?:more|less)\s+productive\s+than\b", "compares people"),
    (r"\b(?:under|over)performing\b", "evaluates a person"),
)

#: Judgemental or evaluative language about a person (md/05 §A.5). Zero tolerance.
TONE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:lazy|sloppy|careless|incompetent)\b", "pejorative"),
    (r"\bfail(?:ed|ing)\s+to\s+deliver\b", "blame"),
    (r"\b(?:only|merely|just)\s+(?:managed|completed|shipped)\b", "belittling"),
    (r"\bstruggl\w+\s+(?:with|to)\b", "evaluative"),
    (r"\b(?:disappointing|impressive|exceptional)\s+(?:week|output|work)\b", "appraisal"),
    (r"\bfell\s+behind\b", "evaluative"),
    (r"\bnot\s+pulling\s+(?:their|his|her)\s+weight\b", "pejorative"),
)


@dataclass(frozen=True, slots=True)
class GuardrailViolation:
    reason: str
    detail: str


def _echoes_an_instruction(lowered: str) -> bool:
    """Whether the text recites a run of CAIRN's own instruction verbatim.

    Compared as word windows rather than substrings so that whitespace and line
    breaks — which a model reformats freely — do not hide an echo. Imported
    lazily because `guardrails` is imported by the stages whose instructions it
    reads, and a module-level import would close the circle.
    """
    from cairn_api.pipeline import extract, synthesize

    words = lowered.split()
    if len(words) < _ECHO_WINDOW:
        return False

    seen = {
        " ".join(words[index : index + _ECHO_WINDOW])
        for index in range(len(words) - _ECHO_WINDOW + 1)
    }

    for instruction in (extract.INSTRUCTION, synthesize.INSTRUCTION):
        source = instruction.lower().split()
        for index in range(len(source) - _ECHO_WINDOW + 1):
            if " ".join(source[index : index + _ECHO_WINDOW]) in seen:
                return True
    return False


def inspect(text: str) -> list[GuardrailViolation]:
    """Check one statement. Empty means acceptable."""
    violations: list[GuardrailViolation] = []
    lowered = text.lower()

    if _echoes_an_instruction(lowered):
        violations.append(
            GuardrailViolation(
                reason="prompt_leak",
                detail=f"output repeats {_ECHO_WINDOW} or more consecutive words of an instruction",
            )
        )

    for fragment in _PROMPT_FRAGMENTS:
        if fragment in lowered:
            violations.append(
                GuardrailViolation(
                    reason="prompt_leak",
                    detail=f"output repeats instruction text: {fragment!r}",
                )
            )
            break

    if any(
        _IMPERATIVE.match(_ROLE_MARKER.sub("", sentence, count=1))
        for sentence in _SENTENCES.split(text)
    ):
        violations.append(
            GuardrailViolation(
                reason="injected_instruction",
                detail="statement reads as a directive rather than a description",
            )
        )

    for pattern, reason in BOUNDARY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE) is not None:
            violations.append(
                GuardrailViolation(
                    reason="boundary",
                    detail=f"statement {reason} (md/05 §B.3.3)",
                )
            )
            break

    for pattern, reason in TONE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            violations.append(
                GuardrailViolation(
                    reason="tone",
                    detail=f"statement is {reason} about a person (md/05 §A.5)",
                )
            )
            break

    for pii_pattern, label in _PII:
        if pii_pattern.search(text):
            violations.append(
                GuardrailViolation(
                    reason="pii",
                    detail=f"statement appears to contain a {label}",
                )
            )
            break

    return violations
