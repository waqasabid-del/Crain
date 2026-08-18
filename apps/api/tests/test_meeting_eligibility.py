"""The consent gate, exhausted.

Pure and synchronous, so every branch is reachable without a database — which is
the point of taking rows rather than reading them. A gate that needs a fixture
per case is a gate whose rare branches go untested, and the rare branches here
are the ones that decide whether somebody who declined gets recorded anyway.

The organising question for each test is: *what would have to be true for CAIRN
to collect a meeting it should not?* Each one closes a way.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest
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
from cairn_api.meetings import eligibility
from cairn_api.meetings.eligibility import ReasonCode

TENANT = uuid.uuid4()
START = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
END = START + timedelta(hours=1)
BEFORE = START - timedelta(days=1)


def a_meeting(
    *,
    state: CaptureState = CaptureState.PENDING,
    policy: str = CONSENT_POLICY_VERSION,
    tenant: uuid.UUID = TENANT,
) -> MeetingCaptureRequest:
    return MeetingCaptureRequest(
        id=uuid.uuid4(),
        tenant_id=tenant,
        provider=MeetingProvider.GOOGLE_MEET,
        external_meeting_ref="meet/abc-defg-hij",
        scheduled_start=START,
        scheduled_end=END,
        purpose="Write up the launch decisions.",
        policy_version=policy,
        state=state,
        state_changed_at=BEFORE,
    )


def a_participant(
    *,
    person: uuid.UUID | None = None,
    status: ParticipantStatus = ParticipantStatus.EXPECTED,
    added: datetime = BEFORE,
) -> MeetingParticipant:
    return MeetingParticipant(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        meeting_id=uuid.uuid4(),
        person_id=person if person is not None else uuid.uuid4(),
        status=status,
        source=ParticipantSource.CALENDAR,
        added_at=added,
        removed_at=None if status is ParticipantStatus.EXPECTED else BEFORE,
    )


def a_decision(
    participant: MeetingParticipant,
    decision: ConsentDecision = ConsentDecision.ACCEPTED,
    *,
    policy: str = CONSENT_POLICY_VERSION,
    at: datetime | None = BEFORE,
    superseded: datetime | None = None,
) -> MeetingConsent:
    return MeetingConsent(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        meeting_id=participant.meeting_id,
        participant_id=participant.id,
        decision=decision,
        decided_at=None if decision is ConsentDecision.PENDING else at,
        policy_version=policy,
        superseded_at=superseded,
    )


def check(
    meeting: MeetingCaptureRequest | None,
    participants: Sequence[MeetingParticipant],
    consents: Sequence[MeetingConsent],
    *,
    tenant_id: uuid.UUID = TENANT,
    provider: MeetingProvider | None = None,
    now: datetime | None = None,
) -> eligibility.Eligibility:
    """The gate, with this file's defaults filled in."""
    return eligibility.check(
        meeting,
        participants,
        consents,
        tenant_id=tenant_id,
        provider=provider,
        now=now,
    )


class TestEveryoneMustAgree:
    """The operating rule from md/03 §3.4, and the reason it is unanimous."""

    def test_all_accepted_is_the_only_way_through(self) -> None:
        one, two = a_participant(), a_participant()

        result = check(a_meeting(), [one, two], [a_decision(one), a_decision(two)], now=START)

        assert result.allowed
        assert result.reason is ReasonCode.ALLOWED

    def test_one_silence_blocks_everything(self) -> None:
        """Silence never ages into agreement. There is no timeout after which an
        unanswered request becomes a yes."""
        one, two = a_participant(), a_participant()

        result = check(a_meeting(), [one, two], [a_decision(one)], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.AWAITING_CONSENT

    def test_one_decline_blocks_everything(self) -> None:
        one, two = a_participant(), a_participant()

        result = check(
            a_meeting(),
            [one, two],
            [a_decision(one), a_decision(two, ConsentDecision.DECLINED)],
            now=START,
        )

        assert not result.allowed
        assert result.reason is ReasonCode.REFUSED

    def test_a_withdrawal_blocks_everything(self) -> None:
        """The product promises withdrawal works, and this is where that promise
        is either kept or is words on a screen."""
        one = a_participant()

        result = check(a_meeting(), [one], [a_decision(one, ConsentDecision.WITHDRAWN)], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.REFUSED

    def test_no_participants_is_not_unanimous(self) -> None:
        """**The branch that would otherwise be the whole bug.**

        "Everyone agreed" over an empty list is vacuously true, and a gate that
        answered `all(...)` on no rows would permit collection for a meeting
        nobody had been asked about.
        """
        result = check(a_meeting(), [], [], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.NO_PARTICIPANTS

    def test_a_removed_participant_is_not_asked(self) -> None:
        """Somebody taken off the invitation is not blocking, and their absence
        is not consent either — they are simply no longer part of the question."""
        staying = a_participant()
        gone = a_participant(status=ParticipantStatus.REMOVED)

        result = check(a_meeting(), [staying, gone], [a_decision(staying)], now=START)

        assert result.allowed


class TestChangesInvalidateAgreement:
    def test_a_participant_added_later_blocks_it(self) -> None:
        """The meeting somebody agreed to is not the meeting with one more person
        in it. Their agreement does not exist yet, and cannot be assumed."""
        early = a_participant()
        late = a_participant(added=BEFORE + timedelta(hours=2))

        result = check(a_meeting(), [early, late], [a_decision(early)], now=START)

        assert not result.allowed
        assert result.reason in {ReasonCode.PARTICIPANT_ADDED, ReasonCode.AWAITING_CONSENT}

    def test_a_policy_change_invalidates_every_answer(self) -> None:
        """Somebody who agreed to one explanation has not agreed to a different
        one. Carrying the answer forward silently is the move this module exists
        to prevent."""
        one = a_participant()

        result = check(a_meeting(), [one], [a_decision(one, policy="2020-01-01.0")], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.POLICY_CHANGED

    def test_a_meeting_on_an_old_policy_is_refused(self) -> None:
        one = a_participant()

        result = check(a_meeting(policy="2020-01-01.0"), [one], [a_decision(one)], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.POLICY_CHANGED

    def test_an_expired_decision_is_not_a_refusal(self) -> None:
        """A reschedule means somebody has not answered *this* question. Treating
        that as a decline would misreport what they said."""
        one = a_participant()

        result = check(a_meeting(), [one], [a_decision(one, ConsentDecision.EXPIRED)], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.RESCHEDULED


class TestItFailsClosed:
    @pytest.mark.parametrize(
        "state",
        [
            CaptureState.CANCELLED,
            CaptureState.REFUSED,
            CaptureState.EXPIRED,
            CaptureState.COMPLETED,
        ],
    )
    def test_a_closed_request_collects_nothing(self, state: CaptureState) -> None:
        one = a_participant()

        result = check(a_meeting(state=state), [one], [a_decision(one)], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.NOT_COLLECTABLE

    def test_a_missing_meeting_is_refused_rather_than_crashing(self) -> None:
        assert not check(None, [], []).allowed

    def test_another_workspace_is_refused(self) -> None:
        """Checked here as well as by the caller's scoping. A gate that trusts
        its caller opens the moment one caller gets it wrong."""
        one = a_participant()

        result = check(a_meeting(), [one], [a_decision(one)], tenant_id=uuid.uuid4(), now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.SCOPE_MISMATCH

    def test_the_wrong_provider_is_refused(self) -> None:
        one = a_participant()

        result = check(
            a_meeting(), [one], [a_decision(one)], provider=MeetingProvider.ZOOM, now=START
        )

        assert not result.allowed
        assert result.reason is ReasonCode.SCOPE_MISMATCH

    def test_an_unidentified_participant_blocks_it(self) -> None:
        """Somebody CAIRN cannot identify is somebody it cannot ask. Blocking is
        the honest consequence of refusing to guess who people are — the
        alternative is deciding an identity by inference, which Step 34 forbids.
        """
        known = a_participant()
        unknown = a_participant(person=None)
        unknown.person_id = None

        result = check(a_meeting(), [known, unknown], [a_decision(known)], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.UNRESOLVED_PARTICIPANT

    def test_an_acceptance_with_no_timestamp_is_refused(self) -> None:
        """A row that cannot say when somebody agreed is not evidence that they
        did."""
        one = a_participant()

        result = check(a_meeting(), [one], [a_decision(one, at=None)], now=START)

        assert not result.allowed

    def test_long_after_the_meeting_it_stops(self) -> None:
        one = a_participant()

        result = check(a_meeting(), [one], [a_decision(one)], now=END + timedelta(days=3))

        assert not result.allowed
        assert result.reason is ReasonCode.WINDOW_PASSED


class TestSupersededDecisionsAreHistory:
    def test_a_superseded_acceptance_does_not_count(self) -> None:
        """Reading history as if it were current is exactly how a withdrawal gets
        ignored. The gate is documented to take live rows; this proves it does
        not quietly accept a stale one.
        """
        one = a_participant()
        stale = a_decision(one, superseded=BEFORE)

        result = check(a_meeting(), [one], [stale], now=START)

        assert not result.allowed
        assert result.reason is ReasonCode.AWAITING_CONSENT


class TestTheWordingNamesNobody:
    """The privacy property of the public message.

    Naming who declined would make refusing socially expensive — which, in an
    employment context, is a way of making consent not freely given, the exact
    defect md/03 §3.3 says invalidates it.
    """

    def test_no_public_message_can_carry_an_identifier(self) -> None:
        for reason in ReasonCode:
            message = eligibility.Eligibility(
                allowed=reason is ReasonCode.ALLOWED, reason=reason
            ).public_message

            assert message
            assert "@" not in message
            assert (
                "somebody" in message.lower()
                or "everyone" in message.lower()
                or ("nobody" in message.lower() or "this" in message.lower())
            )

    def test_the_refusal_message_does_not_say_who(self) -> None:
        one, two = a_participant(), a_participant()

        result = check(
            a_meeting(),
            [one, two],
            [a_decision(one), a_decision(two, ConsentDecision.DECLINED)],
            now=START,
        )

        assert str(two.person_id) not in result.public_message
        assert "somebody" in result.public_message.lower()
