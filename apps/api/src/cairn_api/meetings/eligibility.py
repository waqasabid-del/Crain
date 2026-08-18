"""The one place that decides whether CAIRN may collect a meeting artifact.

**Every future provider calls this, and nothing recomputes it.** Before a Meet or
Zoom integration may read artifact metadata, fetch a transcript the platform
produced, enqueue a job, create an event or a fact, or spend a model call, it
asks `check()` and proceeds only on `allowed`. A second implementation in a
router, a worker or a screen is the failure this module is shaped to prevent: two
consent calculations disagree eventually, and the disagreement is discovered when
somebody who declined turns up in a brief.

**It fails closed on everything.** Missing data, an unknown state, a tenant
mismatch, a provider mismatch, an unresolved participant, a policy change, a
reschedule, a participant added after the answers came in — each returns a
refusal with a reason. There is no default-allow branch and no argument that
relaxes one; the function cannot be asked to skip a check, because there is no
parameter with which to ask.

**Two vocabularies, deliberately.** `ReasonCode` is precise and internal, for
operators and tests. `public_message` is what a person reads, and it never says
which colleague declined or stayed silent — "waiting on somebody" is what a
participant is entitled to know, and "Dana refused" is a disclosure that turns a
consent screen into a place where refusing has a social cost. That single
distinction is most of the privacy design here.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, final

from cairn_api.db.meeting_models import (
    CONSENT_POLICY_VERSION,
    RESCHEDULE_TOLERANCE_MINUTES,
    CaptureState,
    ConsentDecision,
    MeetingCaptureRequest,
    MeetingConsent,
    MeetingParticipant,
    ParticipantStatus,
)


class ReasonCode(enum.StrEnum):
    """Why collection is or is not permitted. Internal, precise, never shown raw."""

    ALLOWED = "allowed"

    #: At least one expected participant has not answered.
    AWAITING_CONSENT = "awaiting_consent"

    #: Somebody said no, or took their agreement back.
    REFUSED = "refused"

    #: A participant CAIRN cannot identify, so cannot ask. Blocking on purpose:
    #: the alternative is deciding somebody's identity by inference, which the
    #: product refuses (Step 34).
    UNRESOLVED_PARTICIPANT = "unresolved_participant"

    #: Somebody joined the invitation after the others answered. Their agreement
    #: does not exist yet, and the meeting is a different meeting to them.
    PARTICIPANT_ADDED = "participant_added"

    #: The wording changed. Answers to the old question are not answers to this.
    POLICY_CHANGED = "policy_changed"

    #: The meeting moved beyond the tolerance. Consent for one afternoon is not
    #: consent for whenever it eventually happens.
    RESCHEDULED = "rescheduled"

    #: Called off, refused, expired, or already collected.
    NOT_COLLECTABLE = "not_collectable"

    #: The meeting's window has passed without agreement in place.
    WINDOW_PASSED = "window_passed"

    #: Asked about the wrong workspace or the wrong platform.
    SCOPE_MISMATCH = "scope_mismatch"

    #: Nobody is expected. An empty participant list is not unanimous consent;
    #: it is a request nobody has been asked about.
    NO_PARTICIPANTS = "no_participants"


#: What a reader sees. One sentence per code, and **none of them names a person**.
#:
#: `AWAITING_CONSENT` and `REFUSED` are worded so that a participant learns the
#: state without learning who caused it. Naming the refuser would make declining
#: socially expensive, which in an employment context is a way of making consent
#: not freely given — the exact defect md/03 §3.3 says invalidates it.
_PUBLIC: Final[dict[ReasonCode, str]] = {
    ReasonCode.ALLOWED: "Everyone invited has agreed, so CAIRN may collect this meeting's transcript from the platform when it exists.",
    ReasonCode.AWAITING_CONSENT: "CAIRN is still waiting for everyone invited to answer. Nothing will be collected until they have.",
    ReasonCode.REFUSED: "Somebody invited did not agree, so CAIRN will not collect anything from this meeting.",
    ReasonCode.UNRESOLVED_PARTICIPANT: "Somebody invited is not connected to a CAIRN account, so they cannot be asked and nothing will be collected.",
    ReasonCode.PARTICIPANT_ADDED: "Somebody was added to this meeting after the others answered, so CAIRN is waiting for their answer too.",
    ReasonCode.POLICY_CHANGED: "The explanation of what CAIRN may receive has changed since these answers were given, so everyone will be asked again.",
    ReasonCode.RESCHEDULED: "This meeting moved, so the earlier answers no longer apply and everyone will be asked again.",
    ReasonCode.NOT_COLLECTABLE: "This request is closed, so nothing will be collected.",
    ReasonCode.WINDOW_PASSED: "This meeting finished without everyone agreeing, so nothing will be collected.",
    ReasonCode.SCOPE_MISMATCH: "This request does not belong to this workspace.",
    ReasonCode.NO_PARTICIPANTS: "Nobody has been asked about this meeting yet, so nothing will be collected.",
}


@final
@dataclass(frozen=True, slots=True)
class Eligibility:
    """The answer, in both vocabularies."""

    allowed: bool
    reason: ReasonCode

    @property
    def public_message(self) -> str:
        """Safe wording. Names nobody, quotes nothing, blames no one."""
        return _PUBLIC[self.reason]


def _refuse(reason: ReasonCode) -> Eligibility:
    return Eligibility(allowed=False, reason=reason)


def check(
    meeting: MeetingCaptureRequest | None,
    participants: Sequence[MeetingParticipant],
    consents: Sequence[MeetingConsent],
    *,
    tenant_id: uuid.UUID,
    provider: object | None = None,
    now: datetime | None = None,
) -> Eligibility:
    """May CAIRN collect this meeting's artifact? Default is no.

    Takes the rows rather than reading them, so the rule is a pure function a
    test can exhaust and a caller cannot accidentally scope wrongly. The caller
    loads within its own tenant session; `tenant_id` is checked here as well
    because a gate that trusts its caller's scoping is a gate that opens when one
    caller gets it wrong.

    `consents` must be the **live** rows — those with no `superseded_at`. A
    superseded decision is history, and reading history as if it were current is
    how a withdrawal gets ignored.
    """
    moment = now or datetime.now(UTC)

    if meeting is None:
        return _refuse(ReasonCode.NOT_COLLECTABLE)
    if meeting.tenant_id != tenant_id:
        return _refuse(ReasonCode.SCOPE_MISMATCH)
    if provider is not None and meeting.provider != provider:
        return _refuse(ReasonCode.SCOPE_MISMATCH)

    if meeting.state in {
        CaptureState.CANCELLED,
        CaptureState.REFUSED,
        CaptureState.EXPIRED,
        CaptureState.COMPLETED,
    }:
        return _refuse(ReasonCode.NOT_COLLECTABLE)

    if meeting.policy_version != CONSENT_POLICY_VERSION:
        return _refuse(ReasonCode.POLICY_CHANGED)

    expected = [item for item in participants if item.status is ParticipantStatus.EXPECTED]
    if not expected:
        # An empty list is not unanimity. This is the branch that would otherwise
        # make "nobody was asked" indistinguishable from "everybody agreed".
        return _refuse(ReasonCode.NO_PARTICIPANTS)

    if any(item.person_id is None for item in expected):
        return _refuse(ReasonCode.UNRESOLVED_PARTICIPANT)

    live = {item.participant_id: item for item in consents if item.superseded_at is None}

    # A refusal anywhere ends it, and is checked before anything else so that a
    # declined meeting never reports "waiting" — which would read as though the
    # answer might still change.
    if any(
        live.get(item.id) is not None
        and live[item.id].decision in {ConsentDecision.DECLINED, ConsentDecision.WITHDRAWN}
        for item in expected
    ):
        return _refuse(ReasonCode.REFUSED)

    tolerance = timedelta(minutes=RESCHEDULE_TOLERANCE_MINUTES)
    for item in expected:
        decision = live.get(item.id)
        if decision is None or decision.decision is ConsentDecision.PENDING:
            # Added after the others answered, or simply not answered yet. The
            # distinction is only for wording; both refuse.
            if decision is None and any(
                other.decided_at is not None and item.added_at > other.decided_at
                for other in live.values()
            ):
                return _refuse(ReasonCode.PARTICIPANT_ADDED)
            return _refuse(ReasonCode.AWAITING_CONSENT)

        if decision.decision is ConsentDecision.EXPIRED:
            return _refuse(ReasonCode.RESCHEDULED)
        if decision.decision is not ConsentDecision.ACCEPTED:
            return _refuse(ReasonCode.REFUSED)
        if decision.policy_version != CONSENT_POLICY_VERSION:
            return _refuse(ReasonCode.POLICY_CHANGED)
        if decision.decided_at is None:
            # An acceptance with no time is a row somebody built wrong. Refusing
            # is the only safe reading of a record that cannot say when it was
            # given.
            return _refuse(ReasonCode.AWAITING_CONSENT)
        if meeting.scheduled_start - decision.decided_at > tolerance and (
            decision.decided_at < meeting.scheduled_start - tolerance
            and meeting.state_changed_at > decision.decided_at
        ):
            return _refuse(ReasonCode.RESCHEDULED)

    if moment > meeting.scheduled_end + timedelta(days=1):
        # Long past. Consent does not decay the instant a meeting ends — the
        # platform writes its transcript afterwards — but it does not last
        # indefinitely either.
        return _refuse(ReasonCode.WINDOW_PASSED)

    return Eligibility(allowed=True, reason=ReasonCode.ALLOWED)
