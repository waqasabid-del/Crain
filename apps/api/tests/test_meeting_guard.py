"""No permit, no collection — and no way to forge a permit.

The eligibility rule is exhausted in `test_meeting_eligibility.py`. What this
file tests is the *boundary*: that a future Meet or Zoom integration cannot reach
a transcript by forgetting to ask, by asking wrongly, or by constructing the
object that says it did.

There is no provider integration yet, and that is exactly why these tests exist
now. A gate written alongside the first connector is a gate whose absence nobody
notices until the connector ships; written first, the connector cannot be built
without walking through it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
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
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.meetings import guard
from cairn_api.meetings.eligibility import ReasonCode
from cairn_api.meetings.guard import CollectionPermit, CollectionRefusedError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

START = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
END = START + timedelta(hours=1)


async def a_meeting(
    platform: AsyncSession, *, accepted: int, expected: int
) -> tuple[uuid.UUID, uuid.UUID]:
    """A request with `expected` participants, `accepted` of whom agreed."""
    tenant = Tenant(name="Acme", slug=f"meet-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.flush()
    people = [Person(tenant_id=tenant.id, display_name=f"P{i}") for i in range(expected)]
    platform.add_all(people)
    await platform.commit()

    async with tenant_session(tenant.id) as session:
        meeting = MeetingCaptureRequest(
            tenant_id=tenant.id,
            provider=MeetingProvider.GOOGLE_MEET,
            external_meeting_ref=f"meet/{uuid.uuid4().hex[:12]}",
            scheduled_start=START,
            scheduled_end=END,
            purpose="Write up the launch decisions.",
            policy_version=CONSENT_POLICY_VERSION,
            state=CaptureState.PENDING,
            state_changed_at=START - timedelta(days=1),
        )
        session.add(meeting)
        await session.flush()

        for index, person in enumerate(people):
            participant = MeetingParticipant(
                tenant_id=tenant.id,
                meeting_id=meeting.id,
                person_id=person.id,
                status=ParticipantStatus.EXPECTED,
                source=ParticipantSource.MANUAL,
                added_at=START - timedelta(days=1),
            )
            session.add(participant)
            await session.flush()
            if index < accepted:
                session.add(
                    MeetingConsent(
                        tenant_id=tenant.id,
                        meeting_id=meeting.id,
                        participant_id=participant.id,
                        decision=ConsentDecision.ACCEPTED,
                        decided_at=START - timedelta(hours=2),
                        policy_version=CONSENT_POLICY_VERSION,
                    )
                )
        await session.commit()
        return tenant.id, meeting.id


class TestTheGuardRefusesUnlessEverybodyAgreed:
    async def test_it_issues_a_permit_when_everyone_accepted(self, platform: AsyncSession) -> None:
        tenant_id, meeting_id = await a_meeting(platform, accepted=2, expected=2)

        async with tenant_session(tenant_id) as session:
            permit = await guard.permit_collection(
                session, tenant_id=tenant_id, meeting_id=meeting_id, now=START
            )

        assert isinstance(permit, CollectionPermit)
        assert permit.meeting_id == meeting_id

    async def test_one_silence_refuses(self, platform: AsyncSession) -> None:
        tenant_id, meeting_id = await a_meeting(platform, accepted=1, expected=2)

        async with tenant_session(tenant_id) as session:
            with pytest.raises(CollectionRefusedError) as caught:
                await guard.permit_collection(
                    session, tenant_id=tenant_id, meeting_id=meeting_id, now=START
                )

        assert caught.value.reason is ReasonCode.AWAITING_CONSENT

    async def test_a_meeting_that_does_not_exist_refuses(self, platform: AsyncSession) -> None:
        """Missing data fails closed. A `None` meeting must not read as "nothing
        to object to"."""
        tenant_id, _ = await a_meeting(platform, accepted=1, expected=1)

        async with tenant_session(tenant_id) as session:
            with pytest.raises(CollectionRefusedError):
                await guard.permit_collection(
                    session, tenant_id=tenant_id, meeting_id=uuid.uuid4(), now=START
                )

    async def test_the_wrong_provider_refuses(self, platform: AsyncSession) -> None:
        tenant_id, meeting_id = await a_meeting(platform, accepted=1, expected=1)

        async with tenant_session(tenant_id) as session:
            with pytest.raises(CollectionRefusedError) as caught:
                await guard.permit_collection(
                    session,
                    tenant_id=tenant_id,
                    meeting_id=meeting_id,
                    provider=MeetingProvider.ZOOM,
                    now=START,
                )

        assert caught.value.reason is ReasonCode.SCOPE_MISMATCH

    async def test_another_workspace_cannot_obtain_a_permit(self, platform: AsyncSession) -> None:
        _, meeting_id = await a_meeting(platform, accepted=1, expected=1)
        other = Tenant(name="Globex", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(other.id) as session:
            with pytest.raises(CollectionRefusedError):
                await guard.permit_collection(
                    session, tenant_id=other.id, meeting_id=meeting_id, now=START
                )

    async def test_a_withdrawal_revokes_the_permit(self, platform: AsyncSession) -> None:
        """The property the whole step exists for: agreement can be taken back,
        and the boundary honours it on the very next call."""
        tenant_id, meeting_id = await a_meeting(platform, accepted=1, expected=1)

        async with tenant_session(tenant_id) as session:
            await guard.permit_collection(
                session, tenant_id=tenant_id, meeting_id=meeting_id, now=START
            )

        async with tenant_session(tenant_id) as session:
            live = await session.scalar(
                select(MeetingConsent).where(
                    MeetingConsent.meeting_id == meeting_id,
                    MeetingConsent.superseded_at.is_(None),
                )
            )
            assert live is not None
            # Superseded, not edited: the acceptance stays on the record and a
            # new row carries the change of mind. That is what makes the history
            # evidence rather than a current-value column.
            live.superseded_at = START
            session.add(
                MeetingConsent(
                    tenant_id=tenant_id,
                    meeting_id=meeting_id,
                    participant_id=live.participant_id,
                    decision=ConsentDecision.WITHDRAWN,
                    decided_at=START,
                    policy_version=CONSENT_POLICY_VERSION,
                )
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            with pytest.raises(CollectionRefusedError) as caught:
                await guard.permit_collection(
                    session, tenant_id=tenant_id, meeting_id=meeting_id, now=START
                )

        assert caught.value.reason is ReasonCode.REFUSED


class TestAPermitCannotBeForged:
    """The permit is the type a future integration will demand.

    If it could be constructed by hand, the signature would be decoration: a
    caller under deadline pressure would build one rather than ask, and the
    consent check would quietly stop happening.
    """

    def test_constructing_one_directly_is_refused(self) -> None:
        with pytest.raises(TypeError):
            CollectionPermit(
                meeting_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                provider=MeetingProvider.GOOGLE_MEET,
                external_meeting_ref="meet/forged",
                checked_at=START,
                proof=object(),
            )

    def test_there_is_no_bypass_argument(self) -> None:
        """Nothing takes `force`, `skip`, or a precomputed verdict. A safeguard
        with an override is a safeguard that gets overridden."""
        import inspect

        parameters = set(inspect.signature(guard.permit_collection).parameters)

        assert parameters == {"db", "tenant_id", "meeting_id", "provider", "now"}
        for forbidden in ("force", "skip", "override", "bypass", "verdict", "allow"):
            assert not any(forbidden in name for name in parameters)


class TestTheRefusalTellsAnOperatorNothingPrivate:
    async def test_no_identifier_reaches_the_log(self, platform: AsyncSession) -> None:
        """A meeting id is stable and correlatable; enough of them in a log store
        reconstructs one meeting's consent history outside the erasure path."""
        import inspect

        from cairn_api.meetings import audit

        signature = set(inspect.signature(audit.record).parameters)

        assert signature == {"event", "reason", "decision", "participants", "accepted"}
        for forbidden in ("meeting", "person", "user", "participant_id", "purpose", "title"):
            assert not any(forbidden in name for name in signature), (
                f"{forbidden!r} can be logged — the log store is outside the erasure path"
            )

    async def test_the_public_message_names_nobody(self, platform: AsyncSession) -> None:
        tenant_id, meeting_id = await a_meeting(platform, accepted=1, expected=2)

        async with tenant_session(tenant_id) as session:
            with pytest.raises(CollectionRefusedError) as caught:
                await guard.permit_collection(
                    session, tenant_id=tenant_id, meeting_id=meeting_id, now=START
                )

        message = caught.value.public_message
        assert str(meeting_id) not in message
        assert "@" not in message
        assert "waiting" in message.lower()
