"""Reading and writing meeting-capture consent, without ever deciding it.

**This module writes state; `eligibility.check` decides it.** Every place here
that could be tempted to work out "has everybody agreed?" calls the gate and
stores what it said. There is no second calculation, no shortcut for the easy
case, and no branch that sets `ELIGIBLE` from a count — the one function that
knows the rule is the one function that answers it, so a future provider and
this service cannot come to different conclusions about the same meeting.

**Nothing here can consent on somebody's behalf.** `record_decision` takes
`caller_user_id` — the id the session resolved to — and writes it into
`decided_by_user_id`. It takes no subject, no participant id and no person id,
so there is no argument an administrator's request could carry that would make
the decision somebody else's. md/03 §3.1: in all-party states an employer cannot
mandate recording over an employee's objection, which makes a consent an employer
could write worth precisely nothing.

**Decisions are appended, never edited.** Changing your mind supersedes the old
row and inserts a new one. The only column ever updated on `meeting_consents` is
`superseded_at`; `decision`, `decided_at` and `decided_by_user_id` are written
once and never touched again, and there is no DELETE grant to lose them with.

**`state_changed_at` is stamped only for changes that are not consequences of
the answers.** The gate reads it as evidence that the meeting moved under
somebody's feet — a decision taken well before the start, with the meeting
changed after it, is treated as a reschedule and stops counting. So stamping it
when a request merely *becomes* eligible would make the gate report, on the very
next read, a reschedule that never happened, and an agreed meeting would flip
back to refused for no reason a customer could see. Cancellation, refusal and
expiry stamp it; becoming eligible or falling back to pending does not.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.identity_models import Person
from cairn_api.db.meeting_models import (
    CONSENT_POLICY_VERSION,
    CaptureState,
    ConsentDecision,
    MeetingCaptureRequest,
    MeetingConsent,
    MeetingParticipant,
    MeetingProvider,
    ParticipantSource,
    ParticipantStatus,
)
from cairn_api.meetings.eligibility import Eligibility, ReasonCode, check

#: A request in one of these states is finished. Nothing reopens it — a refusal
#: is not a prompt to ask again, and re-asking is a new request somebody has to
#: justify in their own words.
TERMINAL: Final[frozenset[CaptureState]] = frozenset(
    {
        CaptureState.CANCELLED,
        CaptureState.REFUSED,
        CaptureState.EXPIRED,
        CaptureState.COMPLETED,
    }
)

#: The states in which somebody's answer still means something.
OPEN: Final[frozenset[CaptureState]] = frozenset({CaptureState.PENDING, CaptureState.ELIGIBLE})

#: What a participant may say. Deliberately not `ConsentDecision` itself:
#: `PENDING` is the absence of an answer and `EXPIRED` is something the gate
#: concludes, and neither is a thing a caller may assert about themselves.
ANSWERABLE: Final[frozenset[ConsentDecision]] = frozenset(
    {ConsentDecision.ACCEPTED, ConsentDecision.DECLINED, ConsentDecision.WITHDRAWN}
)

#: Guards a single request against an unbounded invitation list.
MAX_PARTICIPANTS: Final = 200


class MeetingError(Exception):
    """A rule was broken. Carries the wording and the problem type a reader gets.

    One class rather than a hierarchy: the router maps `status_code` and
    `problem_type` straight through, so a new rule is a new constant here rather
    than a new `except` clause in a handler that might forget it.
    """

    def __init__(self, message: str, *, problem_type: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.problem_type = problem_type
        self.status_code = status_code


@final
@dataclass(frozen=True, slots=True)
class MeetingView:
    """One request as the workspace sees it: standing and counts, never people.

    `accepted` is a count and there is deliberately no list. Which colleague has
    answered is not a fact this product hands to the person who asked them —
    that is what makes declining safe, and a request nobody can safely decline is
    not one anybody consented to.
    """

    meeting: MeetingCaptureRequest
    expected: Sequence[MeetingParticipant]
    accepted: int
    eligibility: Eligibility


@final
@dataclass(frozen=True, slots=True)
class MyMeetingView:
    """One request as the participant sees it: their own answer, and nobody else's."""

    meeting: MeetingCaptureRequest
    participant: MeetingParticipant
    decision: MeetingConsent | None
    participant_count: int
    eligibility: Eligibility


# -- Reading ----------------------------------------------------------------


async def list_requests(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int,
    now: datetime | None = None,
) -> list[MeetingView]:
    """Every capture request in the workspace, newest meeting first.

    Read-only, including the eligibility it reports. A `GET` that persisted what
    the gate concluded would make reading a screen a write, and two people
    opening it at once a race — so the stored `state` is what the last decision
    made it, and the gate's verdict is computed fresh for display beside it.
    """
    moment = now or datetime.now(UTC)

    meetings = list(
        await db.scalars(
            select(MeetingCaptureRequest)
            .where(MeetingCaptureRequest.tenant_id == tenant_id)
            .order_by(MeetingCaptureRequest.scheduled_start.desc())
            .limit(limit)
        )
    )
    if not meetings:
        return []

    participants, consents = await _load_many(db, [row.id for row in meetings])

    return [
        _view(meeting, participants.get(meeting.id, []), consents.get(meeting.id, []), moment)
        for meeting in meetings
    ]


async def my_requests(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    limit: int,
    now: datetime | None = None,
) -> list[MyMeetingView]:
    """The requests the caller was asked about. Self only, by construction.

    The person is resolved from the caller's own session and there is no
    parameter naming anybody else, so this cannot be pointed at a colleague by a
    caller of any role. Removed participants are omitted: somebody taken off the
    invitation has nothing left to answer.
    """
    moment = now or datetime.now(UTC)

    person = await person_for_user(db, caller_user_id)
    if person is None:
        return []

    rows = list(
        await db.scalars(
            select(MeetingParticipant)
            .where(
                MeetingParticipant.person_id == person.id,
                MeetingParticipant.status == ParticipantStatus.EXPECTED,
            )
            .limit(limit)
        )
    )
    if not rows:
        return []

    meetings = {
        row.id: row
        for row in await db.scalars(
            select(MeetingCaptureRequest).where(
                MeetingCaptureRequest.id.in_([row.meeting_id for row in rows]),
                MeetingCaptureRequest.tenant_id == tenant_id,
            )
        )
    }
    participants, consents = await _load_many(db, list(meetings))

    views = [
        _my_view(meetings[row.meeting_id], row, participants, consents, moment)
        for row in rows
        if row.meeting_id in meetings
    ]
    views.sort(key=lambda view: view.meeting.scheduled_start, reverse=True)
    return views


async def person_for_user(db: AsyncSession, user_id: uuid.UUID) -> Person | None:
    """The workspace `Person` for a signed-in account, or `None`.

    `None` is a real answer rather than a fault: a user and a person are
    different things, and somebody who has never been recorded as a participant
    or a contributor has no person row to be asked through.
    """
    person: Person | None = await db.scalar(select(Person).where(Person.user_id == user_id))
    return person


# -- Writing ----------------------------------------------------------------


async def create_request(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    requested_by_user_id: uuid.UUID,
    provider: MeetingProvider,
    external_meeting_ref: str,
    scheduled_start: datetime,
    scheduled_end: datetime,
    purpose: str,
    person_ids: Sequence[uuid.UUID],
    now: datetime | None = None,
) -> MeetingView:
    """Ask a set of people whether CAIRN may collect one meeting's artifact.

    Creates nothing but a question. The request lands `PENDING` with no consent
    rows at all — silence is the starting state and it never ages into agreement,
    so a request created and then ignored collects nothing forever.

    **Fails closed on every participant it cannot ask.** A person id that is not
    this workspace's, or one belonging to somebody with no CAIRN account, is
    refused at creation rather than accepted into a request that could never
    become eligible. The alternative is a request that sits pending for a reason
    nobody can see, which reads as a bug and gets "fixed" by relaxing the gate.
    """
    moment = now or datetime.now(UTC)

    _require_aware(scheduled_start, "scheduledStart")
    _require_aware(scheduled_end, "scheduledEnd")
    if scheduled_end <= scheduled_start:
        raise MeetingError(
            "A meeting has to end after it starts.",
            problem_type="meeting-window-invalid",
        )

    wanted = _unique(person_ids)
    if not wanted:
        # An empty invitation list is not unanimous consent; it is a request
        # nobody has been asked about. The gate refuses it too — this is the
        # earlier, clearer refusal.
        raise MeetingError(
            "A capture request has to name the people who would be in the meeting.",
            problem_type="meeting-participants-required",
        )
    if len(wanted) > MAX_PARTICIPANTS:
        raise MeetingError(
            f"A capture request may name at most {MAX_PARTICIPANTS} people.",
            problem_type="meeting-participants-required",
        )

    await _check_people(db, wanted)

    existing = await db.scalar(
        select(MeetingCaptureRequest).where(
            MeetingCaptureRequest.tenant_id == tenant_id,
            MeetingCaptureRequest.provider == provider,
            MeetingCaptureRequest.external_meeting_ref == external_meeting_ref,
            MeetingCaptureRequest.state.not_in(TERMINAL - {CaptureState.COMPLETED}),
        )
    )
    if existing is not None:
        raise MeetingError(
            "This workspace already has an open capture request for that meeting.",
            problem_type="meeting-request-exists",
            status_code=409,
        )

    meeting = MeetingCaptureRequest(
        tenant_id=tenant_id,
        provider=provider,
        external_meeting_ref=external_meeting_ref,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        requested_by_user_id=requested_by_user_id,
        purpose=purpose,
        policy_version=CONSENT_POLICY_VERSION,
        state=CaptureState.PENDING,
        state_changed_at=moment,
    )
    db.add(meeting)

    try:
        await db.flush()
    except IntegrityError as error:
        # The partial unique index decides a race the check above cannot: two
        # requests for one meeting would be two different sets of answers to the
        # same question.
        raise MeetingError(
            "This workspace already has an open capture request for that meeting.",
            problem_type="meeting-request-exists",
            status_code=409,
        ) from error

    return await add_participants(db, meeting=meeting, person_ids=wanted, now=moment)


async def add_participants(
    db: AsyncSession,
    *,
    meeting: MeetingCaptureRequest,
    person_ids: Sequence[uuid.UUID],
    source: ParticipantSource = ParticipantSource.MANUAL,
    now: datetime | None = None,
) -> MeetingView:
    """Expect more people in a meeting, and lose eligibility by doing so.

    **This is why the function exists rather than a bare `INSERT`.** Somebody
    added after the others answered has not agreed to anything, and a request
    that stayed `ELIGIBLE` through their arrival would be collected under
    everybody's consent except theirs. Re-running the gate here is what turns
    that from a rule somebody has to remember into one they cannot skip: the only
    supported way to add a participant recomputes the standing in the same call.
    """
    moment = now or datetime.now(UTC)

    if meeting.state in TERMINAL:
        raise MeetingError(
            "This request is closed, so nobody else can be added to it.",
            problem_type="meeting-not-open",
        )

    await _check_people(db, person_ids)

    known = {
        row.person_id
        for row in await db.scalars(
            select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id)
        )
    }
    for person_id in _unique(person_ids):
        if person_id in known:
            # Adding somebody twice is a double-click, not a second attendee.
            continue
        db.add(
            MeetingParticipant(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                person_id=person_id,
                status=ParticipantStatus.EXPECTED,
                source=source,
                added_at=moment,
            )
        )

    await db.flush()
    return await refresh_state(db, meeting=meeting, now=moment)


async def cancel(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    meeting_id: uuid.UUID,
    now: datetime | None = None,
) -> MeetingView:
    """Call the request off before anything is collected.

    Only an open request can be cancelled. A refused one is already closed and
    cancelling it would overwrite the fact that somebody said no with a tidier
    word — the record has to keep saying refused, because that is the thing the
    product may later have to demonstrate it honoured.
    """
    moment = now or datetime.now(UTC)

    meeting = await lock_request(db, tenant_id=tenant_id, meeting_id=meeting_id)
    if meeting is None:
        raise _not_found()
    if meeting.state not in OPEN:
        raise MeetingError(
            "This request is already closed, so there is nothing to cancel.",
            problem_type="meeting-not-cancellable",
        )

    meeting.state = CaptureState.CANCELLED
    meeting.state_changed_at = moment
    await db.flush()

    participants, consents = await _load_one(db, meeting.id)
    return _view(meeting, participants, consents, moment)


async def record_decision(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    meeting_id: uuid.UUID,
    caller_user_id: uuid.UUID,
    decision: ConsentDecision,
    now: datetime | None = None,
) -> MyMeetingView:
    """Record one person's own answer, and recompute what it makes possible.

    **`caller_user_id` is the authenticated session's id and nothing else.**
    There is no subject parameter here, and no route above that could supply one,
    so `decided_by_user_id` is the answerer by construction rather than by a
    check somebody could forget. An administrator calling this records their own
    answer to their own invitation or gets a 404.

    **404, never 403, when the decision is not theirs.** Whether a meeting exists
    is not something a non-participant gets to confirm, and a 403 would confirm
    it — turning this endpoint into a way to discover that a colleague is in a
    meeting somebody asked to capture.
    """
    moment = now or datetime.now(UTC)

    if decision not in ANSWERABLE:
        # Unreachable through the API, whose model admits three values. Stated
        # anyway: `PENDING` is the absence of an answer and `EXPIRED` is the
        # gate's conclusion, and a caller asserting either about themselves is a
        # caller writing a record that means something it does not.
        raise MeetingError(
            "That is not an answer somebody can give.",
            problem_type="meeting-decision-invalid",
        )

    # Locked first, so two answers arriving together are serialised: the state
    # they produce must not depend on which handler read the row first.
    meeting = await lock_request(db, tenant_id=tenant_id, meeting_id=meeting_id)

    person = await person_for_user(db, caller_user_id)
    participant = None
    if meeting is not None and person is not None:
        participant = await db.scalar(
            select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == meeting.id,
                MeetingParticipant.person_id == person.id,
                MeetingParticipant.status == ParticipantStatus.EXPECTED,
            )
        )
    if meeting is None or participant is None:
        # One refusal for "no such meeting", "not your meeting" and "you were
        # removed from it". Distinguishing them is the oracle.
        raise _not_yours()

    if meeting.state not in OPEN:
        raise MeetingError(
            "This request is closed, so answers are no longer being recorded.",
            problem_type="meeting-not-open",
        )

    live = await db.scalar(
        select(MeetingConsent).where(
            MeetingConsent.meeting_id == meeting.id,
            MeetingConsent.participant_id == participant.id,
            MeetingConsent.superseded_at.is_(None),
        )
    )

    if decision is ConsentDecision.WITHDRAWN and (
        live is None or live.decision is not ConsentDecision.ACCEPTED
    ):
        # Withdrawal is taking an agreement back, and there is none to take.
        # Refusing rather than quietly filing it as a decline keeps the two
        # distinguishable, which is the whole reason `WITHDRAWN` exists.
        raise MeetingError(
            "You have not agreed to this, so there is nothing to withdraw.",
            problem_type="meeting-decision-invalid",
        )

    if live is not None and live.decision is decision:
        # Answering the same way twice is a double-click. Appending would move
        # `decided_at` and make a re-render look like a fresh decision.
        return await _my_result(db, meeting, participant, live, moment)

    if live is not None:
        # The one column ever updated on this table. The decision itself, when
        # it was made and who made it are written once and never rewritten.
        live.superseded_at = moment
        await db.flush()

    fresh = MeetingConsent(
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        participant_id=participant.id,
        decision=decision,
        decided_at=moment,
        decided_by_user_id=caller_user_id,
        policy_version=CONSENT_POLICY_VERSION,
    )
    db.add(fresh)
    await db.flush()

    await refresh_state(db, meeting=meeting, now=moment)
    return await _my_result(db, meeting, participant, fresh, moment)


async def refresh_state(
    db: AsyncSession,
    *,
    meeting: MeetingCaptureRequest,
    now: datetime | None = None,
) -> MeetingView:
    """Ask the gate where this request stands, and store the answer.

    **The only writer of `CaptureState.ELIGIBLE` in the product.** It is set from
    `Eligibility.allowed` and from nothing else — not from a count of
    acceptances, not from a caller's assertion, not from a flag. Everything a
    provider will later ask goes through the same function that decided this, so
    the stored state and the gate cannot disagree.

    Terminal states are left alone. A refusal is not revisited by a later read,
    and a cancelled request does not come back because somebody changed their
    answer afterwards.
    """
    moment = now or datetime.now(UTC)
    participants, consents = await _load_one(db, meeting.id)
    verdict = check(meeting, participants, consents, tenant_id=meeting.tenant_id, now=moment)

    if meeting.state in TERMINAL:
        return _view(meeting, participants, consents, moment)

    if verdict.allowed:
        # No stamp: becoming eligible is a consequence of the answers, not a
        # change to the meeting, and recording it as one would make the gate read
        # its own bookkeeping as a reschedule on the very next call.
        meeting.state = CaptureState.ELIGIBLE
    elif verdict.reason is ReasonCode.REFUSED:
        meeting.state = CaptureState.REFUSED
        meeting.state_changed_at = moment
    elif verdict.reason is ReasonCode.WINDOW_PASSED:
        meeting.state = CaptureState.EXPIRED
        meeting.state_changed_at = moment
    else:
        meeting.state = CaptureState.PENDING

    await db.flush()
    return _view(meeting, participants, consents, moment)


async def lock_request(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    meeting_id: uuid.UUID,
) -> MeetingCaptureRequest | None:
    """One request, locked for update.

    The tenant predicate is stated even though row-level security already scopes
    the query: a 404 that depends on RLS alone becomes a 200 the day somebody
    runs this on a platform connection.
    """
    row: MeetingCaptureRequest | None = await db.scalar(
        select(MeetingCaptureRequest)
        .where(
            MeetingCaptureRequest.id == meeting_id,
            MeetingCaptureRequest.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    return row


# -- Internals --------------------------------------------------------------


async def _check_people(db: AsyncSession, person_ids: Sequence[uuid.UUID]) -> None:
    """Refuse anybody CAIRN could not actually ask.

    Two separate refusals, because they are two different mistakes: an id that
    belongs to no person in this workspace is a caller error, and a person with
    no CAIRN account is somebody the product has no way to put a question to.
    Neither is allowed to become a silent participant whose absent answer nobody
    notices.
    """
    if not person_ids:
        return

    found = {
        row.id: row
        for row in await db.scalars(select(Person).where(Person.id.in_(list(person_ids))))
    }

    missing = [person_id for person_id in person_ids if person_id not in found]
    if missing:
        raise MeetingError(
            "One of the people named is not in this workspace.",
            problem_type="meeting-participant-unknown",
        )

    unreachable = [person_id for person_id in person_ids if found[person_id].user_id is None]
    if unreachable:
        raise MeetingError(
            "One of the people named has no CAIRN account, so they cannot be "
            "asked. CAIRN will not collect a meeting somebody had no way to "
            "refuse.",
            problem_type="meeting-participant-unreachable",
        )


async def _load_one(
    db: AsyncSession, meeting_id: uuid.UUID
) -> tuple[list[MeetingParticipant], list[MeetingConsent]]:
    """Every participant, and the **live** decisions only.

    Superseded rows are history. Reading history as if it were current is how a
    withdrawal gets ignored, so they are filtered out here rather than left for
    each caller to remember.
    """
    participants = list(
        await db.scalars(
            select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
        )
    )
    consents = list(
        await db.scalars(
            select(MeetingConsent).where(
                MeetingConsent.meeting_id == meeting_id,
                MeetingConsent.superseded_at.is_(None),
            )
        )
    )
    return participants, consents


async def _load_many(
    db: AsyncSession, meeting_ids: Sequence[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[MeetingParticipant]], dict[uuid.UUID, list[MeetingConsent]]]:
    """The same, for a page of requests, in two queries rather than 2N."""
    participants: dict[uuid.UUID, list[MeetingParticipant]] = {}
    consents: dict[uuid.UUID, list[MeetingConsent]] = {}
    if not meeting_ids:
        return participants, consents

    ids = list(meeting_ids)
    for participant in await db.scalars(
        select(MeetingParticipant).where(MeetingParticipant.meeting_id.in_(ids))
    ):
        participants.setdefault(participant.meeting_id, []).append(participant)
    for consent in await db.scalars(
        select(MeetingConsent).where(
            MeetingConsent.meeting_id.in_(ids),
            MeetingConsent.superseded_at.is_(None),
        )
    ):
        consents.setdefault(consent.meeting_id, []).append(consent)

    return participants, consents


def _view(
    meeting: MeetingCaptureRequest,
    participants: Sequence[MeetingParticipant],
    consents: Sequence[MeetingConsent],
    moment: datetime,
) -> MeetingView:
    expected = [row for row in participants if row.status is ParticipantStatus.EXPECTED]
    ids = {row.id for row in expected}
    accepted = sum(
        1
        for row in consents
        if row.participant_id in ids and row.decision is ConsentDecision.ACCEPTED
    )
    return MeetingView(
        meeting=meeting,
        expected=expected,
        accepted=accepted,
        eligibility=check(meeting, participants, consents, tenant_id=meeting.tenant_id, now=moment),
    )


def _my_view(
    meeting: MeetingCaptureRequest,
    participant: MeetingParticipant,
    participants: dict[uuid.UUID, list[MeetingParticipant]],
    consents: dict[uuid.UUID, list[MeetingConsent]],
    moment: datetime,
) -> MyMeetingView:
    rows = participants.get(meeting.id, [])
    live = consents.get(meeting.id, [])
    mine = next((row for row in live if row.participant_id == participant.id), None)
    return MyMeetingView(
        meeting=meeting,
        participant=participant,
        decision=mine,
        participant_count=sum(1 for row in rows if row.status is ParticipantStatus.EXPECTED),
        eligibility=check(meeting, rows, live, tenant_id=meeting.tenant_id, now=moment),
    )


async def _my_result(
    db: AsyncSession,
    meeting: MeetingCaptureRequest,
    participant: MeetingParticipant,
    decision: MeetingConsent,
    moment: datetime,
) -> MyMeetingView:
    participants, consents = await _load_one(db, meeting.id)
    return MyMeetingView(
        meeting=meeting,
        participant=participant,
        decision=decision,
        participant_count=sum(
            1 for row in participants if row.status is ParticipantStatus.EXPECTED
        ),
        eligibility=check(meeting, participants, consents, tenant_id=meeting.tenant_id, now=moment),
    )


def _unique(person_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """Order-preserving de-duplication, so a repeated id is not two attendees."""
    seen: set[uuid.UUID] = set()
    ordered: list[uuid.UUID] = []
    for person_id in person_ids:
        if person_id not in seen:
            seen.add(person_id)
            ordered.append(person_id)
    return ordered


def _require_aware(moment: datetime, field: str) -> None:
    """Refuse a naive timestamp.

    A meeting time without an offset is a meeting time in somebody's unstated
    local zone, and consent given for one afternoon has to be checkable against
    the same afternoon the platform means.
    """
    if moment.tzinfo is None:
        raise MeetingError(
            f"`{field}` needs a time zone offset.",
            problem_type="meeting-window-invalid",
        )


def _not_found() -> MeetingError:
    return MeetingError(
        "This workspace has no capture request with that identifier.",
        problem_type="meeting-request-not-found",
        status_code=404,
    )


def _not_yours() -> MeetingError:
    """404 rather than 403, deliberately — see `record_decision`."""
    return MeetingError(
        "You have no meeting request with that identifier to answer.",
        problem_type="not-your-meeting-decision",
        status_code=404,
    )
