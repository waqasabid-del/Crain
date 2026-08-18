"""What happened to a consent request, recorded without recording anybody.

**The durable audit is `meeting_consents` itself.** It is append-only, carries
who decided what and when, and cannot be edited or deleted — so "did this person
agree, and did they later withdraw?" is answerable from the data rather than from
a log somebody has to trust. This module is the *operational* half: the events an
operator watches to see the consent flow working, which is a different question
and must not carry the same detail.

**Deliberately not `internal/audit.py`.** That is the staff back-office log —
tamper-evident, written when CAIRN's own people act on a workspace. A customer
answering a question about their own meeting is not a staff action, and filing it
there would put customer decisions in the log staff read, inverting who the
record is about.

**What may never appear here**, and the reason each would be a disclosure:

- the meeting title — none is stored, and it is frequently the most sensitive
  string in a workspace;
- the purpose text — written by a requester about a specific conversation;
- a participant id, person id, user id or provider attendee id — the identity of
  who agreed or refused;
- a meeting id — stable, correlatable across events, and enough on its own to
  reconstruct one meeting's consent history from the log store;
- anything a future transcript would contain.

What is left is a category and a count, which is what an operator actually needs:
is the flow moving, are requests being refused, is anything stuck. The log store
sits outside the erasure path the product promises, so anything identifying that
reaches it cannot be taken back.
"""

from __future__ import annotations

import enum

import structlog

from cairn_api.meetings.eligibility import ReasonCode

logger = structlog.get_logger(__name__)


class ConsentEvent(enum.StrEnum):
    """The transitions worth watching. Closed, because a free-form event name is
    how an identifier eventually gets appended to one."""

    REQUEST_CREATED = "meeting.request_created"
    REQUEST_CANCELLED = "meeting.request_cancelled"

    #: A participant answered for themselves. Which way is a separate field, and
    #: there is no field for who.
    DECISION_RECORDED = "meeting.decision_recorded"

    #: Somebody was added to or removed from the expected list, which changes
    #: whose agreement is required.
    PARTICIPANTS_CHANGED = "meeting.participants_changed"

    #: The computed verdict moved — most importantly into or out of eligible.
    ELIGIBILITY_CHANGED = "meeting.eligibility_changed"

    #: The wording changed underneath existing answers, so they stopped counting.
    POLICY_INVALIDATED = "meeting.policy_invalidated"


async def record(
    event: ConsentEvent,
    *,
    reason: ReasonCode | None = None,
    decision: str | None = None,
    participants: int | None = None,
    accepted: int | None = None,
) -> None:
    """Emit one safe operational event.

    Every parameter is a category or a count, and the signature is the guarantee:
    there is no field for a meeting, a person or a purpose, so a caller in a
    hurry has nowhere to put one. `decision` is a bounded word (`accepted`,
    `declined`, `withdrawn`) and never says whose.

    Counts are the workspace's shape, not an individual's: "three expected, two
    accepted" describes progress. It is also why `accepted` is omitted rather
    than sent once a request is refused — see the API layer, where the same
    subtraction would name the refuser.
    """
    fields: dict[str, object] = {}
    if reason is not None:
        fields["reason"] = reason.value
    if decision is not None:
        fields["decision"] = decision
    if participants is not None:
        fields["participants"] = participants
    if accepted is not None:
        fields["accepted"] = accepted

    await logger.ainfo(event.value, **fields)
