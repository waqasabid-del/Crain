"""The one vocabulary for "which source did this come from".

**This module exists because there were two vocabularies and they did not
agree.** Evidence ids were minted with `github` / `slack` / `google_chat`
prefixes and those values were written to `fact_sources.source`. Consent spoke a
different language — `github` / `chat` / `meeting` / `document` — and opt-out is
enforced by intersecting those two sets at attribution time:

    blocked = opted_out.get(person_id, set())
    if blocked & sources_by_fact.get(fact_id, set()):
        continue

`{"chat"} & {"slack"}` is empty. So a person who opted out of chat was recorded
anyway, in silence, and every screen showed the opt-out honoured. The failure was
invisible from both ends: the toggle saved, the row existed, and the only place
the disagreement surfaced was a set intersection nobody could see.

That is the whole reason this is a module rather than a constant. A vocabulary
defined once, imported everywhere, and validated at both ends cannot drift; two
tuples in two files agreeing by convention will drift the moment a source is
added, and the symptom will again be silent over-collection rather than an error.

**`chat` is gone, deliberately.** It was one word for two products a customer
connects, authorises and disconnects separately — so a single opt-out could not
express "stop reading my Slack but keep Google Chat", and the coarser reading
always won. The five values below are exactly the things a person can be asked
about.

**Unknown fails closed.** `source_of_evidence_id` used to return `"github"` for
any unrecognised prefix, which silently relabelled unknown evidence as the one
source most likely to already be connected — and consent decisions were then made
against that wrong label. An unrecognised source now raises, because attribution
is the wrong place to guess and a crash in a worker is recoverable in a way that
quietly attributing somebody's work is not.
"""

from __future__ import annotations

import enum
from typing import Final, final


@final
class Source(enum.StrEnum):
    """Where a piece of evidence came from.

    A `StrEnum` so the stored column, the evidence-id prefix, the consent row and
    the API payload are all the same string — there is no mapping layer to get
    wrong, which was the original defect.
    """

    GITHUB = "github"

    #: Slack and Google Chat are separate members rather than one `chat`. A
    #: person can connect one and not the other, and can reasonably want to be
    #: read in one and not the other.
    SLACK = "slack"
    GOOGLE_CHAT = "google_chat"

    #: Declared, not yet produced by any connector. Present because consent has
    #: always offered them and removing the offer would narrow what a person may
    #: refuse — the wrong direction to resolve an inconsistency.
    MEETING = "meeting"
    DOCUMENT = "document"


#: Every source a person may opt out of. The consent surface and the attribution
#: gate read this same tuple, so a source that can produce evidence and a source
#: somebody can refuse cannot fall out of step.
SOURCES: Final[tuple[str, ...]] = tuple(item.value for item in Source)

#: What a `chat` opt-out means now that `chat` is not a source.
#:
#: Read by the migration and by nothing else. A person who refused "chat" refused
#: both products it named, so the row expands to both — the reading that collects
#: less. Resolving it the other way, or dropping the row, would silently widen
#: what CAIRN may read about somebody who had already said no.
LEGACY_CHAT_SOURCES: Final[tuple[Source, ...]] = (Source.SLACK, Source.GOOGLE_CHAT)


class UnknownSourceError(ValueError):
    """A source value nothing in the product recognises.

    Raised rather than defaulted. The caller is deciding whether somebody's
    activity may be recorded, and a default there is a decision about a person
    made by whichever branch happened to be first.
    """


def parse(value: str) -> Source:
    """Turn a stored or incoming string into a `Source`, or refuse.

    Every boundary that reads a source string goes through here, so an unknown
    value fails at the edge with the value named, rather than three layers later
    as an opt-out that mysteriously did nothing.
    """
    try:
        return Source(value)
    except ValueError as error:
        msg = f"Unknown source: {value!r}"
        raise UnknownSourceError(msg) from error


def source_of_evidence_id(evidence_id: str) -> Source:
    """The source an evidence id names, from the prefix it was minted with.

    Read from the id rather than threaded down from the caller, so it cannot
    drift from the thing it describes.

    **Raises on an unrecognised prefix.** The previous behaviour — fall back to
    `github` — meant unknown evidence was labelled as a source the workspace
    probably had connected, and the consent gate then compared a person's real
    refusal against a fabricated label. Failing closed makes that a loud error in
    a retryable worker instead of a silent, permanent over-collection.
    """
    prefix, _, _ = evidence_id.partition(":")
    return parse(prefix)
