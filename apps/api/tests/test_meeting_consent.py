"""Meeting capture consent: asked of everybody, answered only by themselves.

Step 35's exit criterion is **no meeting becomes collectable without every
expected participant having personally agreed**, and every test here is a way of
trying to get round it rather than a walk through the happy path. The failure
that matters is collection happening, not collection being unavailable.

The property underneath all of them, from md/03 §3.1: in all-party states an
employer *cannot* mandate recording over an employee's objection. So a consent an
employer could write is worth nothing, and the tests below are largely about
proving there is no route, field or flag through which one could be written.

**Nothing in this suite records a meeting**, because nothing in the product does.
These tables decide only whether CAIRN may later ask a platform for an artifact
that platform produced under its own flow, and no provider integration exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cairn_api.api.app import create_app
from cairn_api.config import Settings
from cairn_api.db.identity_models import Person
from cairn_api.db.meeting_models import (
    CONSENT_POLICY_VERSION,
    CaptureState,
    ConsentDecision,
    MeetingCaptureRequest,
    MeetingConsent,
    MeetingParticipant,
    ParticipantSource,
    ParticipantStatus,
)
from cairn_api.db.models import Membership, TenantRole
from cairn_api.db.staff_models import StaffMember, StaffRole
from cairn_api.db.tenancy import tenant_session
from cairn_api.meetings import service
from cairn_api.meetings.eligibility import ReasonCode
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery"  # noqa: S105
TEST_ORIGIN = "http://localhost:3000"


class Account:
    """A signed-in account, its workspace, and the `Person` it is recorded as."""

    def __init__(self, client: AsyncClient, user_id: uuid.UUID, workspace_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.person_id: uuid.UUID | None = None

    @property
    def tenant_id(self) -> uuid.UUID:
        return uuid.UUID(self.workspace_id)


async def signed_up(app: FastAPI) -> Account:
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": TEST_ORIGIN},
    )
    suffix = uuid.uuid4().hex[:10]
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"person-{suffix}@example.com",
            "password": PASSWORD,
            "workspaceName": "Acme",
            "workspaceSlug": f"meet-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Account(client, uuid.UUID(body["user"]["id"]), body["workspaces"][0]["workspace"]["id"])


async def joins(
    app: FastAPI,
    platform: AsyncSession,
    host: Account,
    role: TenantRole = TenantRole.MEMBER,
) -> Account:
    colleague = await signed_up(app)
    platform.add(Membership(tenant_id=host.tenant_id, user_id=colleague.user_id, role=role))
    await platform.commit()
    return Account(colleague.client, colleague.user_id, host.workspace_id)


async def recorded_as_person(platform: AsyncSession, member: Account) -> Account:
    """Give the account a `Person` row, which is what a participant refers to.

    A user and a person are different things: somebody can appear in a source's
    history for months before they ever sign in, and somebody can sign in before
    CAIRN has attributed anything to them.
    """
    row = Person(tenant_id=member.tenant_id, user_id=member.user_id, display_name=None)
    platform.add(row)
    await platform.commit()
    member.person_id = row.id
    return member


async def unreachable_person(platform: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    """Somebody CAIRN knows of but cannot ask: a person with no account."""
    row = Person(tenant_id=tenant_id, user_id=None, display_name=None)
    platform.add(row)
    await platform.commit()
    return row.id


def window(hours: int = 2) -> tuple[str, str]:
    start = datetime.now(UTC) + timedelta(hours=hours)
    return start.isoformat(), (start + timedelta(hours=1)).isoformat()


async def ask(
    requester: Account,
    participants: list[Account | uuid.UUID],
    *,
    expect: int = 201,
    **overrides: Any,
) -> dict[str, Any]:
    start, end = window()
    body: dict[str, Any] = {
        "provider": "google_meet",
        "externalMeetingRef": f"meet-{uuid.uuid4().hex[:12]}",
        "scheduledStart": start,
        "scheduledEnd": end,
        "purpose": "Weekly delivery sync, so the brief can cite what was decided.",
        "participantPersonIds": [
            str(item.person_id if isinstance(item, Account) else item) for item in participants
        ],
    }
    body.update(overrides)

    response = await requester.client.post(
        f"/v1/workspaces/{requester.workspace_id}/meetings/capture-requests",
        json=body,
    )
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def decide(
    member: Account, meeting_id: str, decision: str, *, expect: int = 200
) -> dict[str, Any]:
    response = await member.client.post(
        f"/v1/workspaces/{member.workspace_id}/me/meeting-requests/{meeting_id}/decision",
        json={"decision": decision},
    )
    assert response.status_code == expect, response.text
    payload: dict[str, Any] = response.json()
    return payload


async def workspace_view(member: Account, meeting_id: str) -> dict[str, Any]:
    response = await member.client.get(
        f"/v1/workspaces/{member.workspace_id}/meetings/capture-requests"
    )
    assert response.status_code == 200, response.text
    found = next(row for row in response.json()["requests"] if row["id"] == meeting_id)
    return dict(found)


async def self_view(member: Account) -> list[dict[str, Any]]:
    response = await member.client.get(f"/v1/workspaces/{member.workspace_id}/me/meeting-requests")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["requests"]
    return rows


async def stored(platform: AsyncSession, meeting_id: str) -> MeetingCaptureRequest:
    row = await platform.get(MeetingCaptureRequest, uuid.UUID(meeting_id))
    assert row is not None
    await platform.refresh(row)
    return row


async def consents_for(platform: AsyncSession, meeting_id: str) -> list[MeetingConsent]:
    return list(
        await platform.scalars(
            select(MeetingConsent)
            .where(MeetingConsent.meeting_id == uuid.UUID(meeting_id))
            .order_by(MeetingConsent.created_at)
        )
    )


# --------------------------------------------------------------------------
# Rule 1 — nobody consents on somebody else's behalf
# --------------------------------------------------------------------------


class TestNoBlanketConsent:
    async def test_an_owner_cannot_answer_for_a_colleague(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The route that would do it does not exist, and the one that looks
        like it might is self-only.

        The Owner here asks about a meeting they are not in, then tries to answer
        for it. There is no body field naming a subject, no admin decision route,
        and the `/me/` route resolves the participant from the Owner's own
        session — so the only thing left to try returns 404.
        """
        owner = await signed_up(app)
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [colleague])

        response = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/me/meeting-requests/{meeting['id']}/decision",
            json={"decision": "accepted"},
        )

        assert response.status_code == 404
        assert response.json()["type"].endswith("/not-your-meeting-decision")
        # And nothing was written: no consent row exists at all.
        assert await consents_for(platform, meeting["id"]) == []
        assert (await stored(platform, meeting["id"])).state is CaptureState.PENDING

    async def test_the_request_body_has_no_field_that_could_carry_a_consent(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """`extra="forbid"`, so an invented field is refused rather than ignored.

        Silently dropping `"consented": true` is the dangerous outcome: the
        caller believes they granted something, the server believes nothing
        happened, and the difference surfaces as a support conversation about why
        a meeting was or was not collected.
        """
        owner = await recorded_as_person(platform, await signed_up(app))

        await ask(owner, [owner], expect=422, consented=True)
        await ask(owner, [owner], expect=422, approvedBy=str(owner.user_id))

    async def test_a_decision_is_attributed_to_the_session_that_made_it(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """`decided_by_user_id` is the answerer, by construction.

        There is no argument anywhere in the write path that could make it
        somebody else — the router passes the id the session cookie resolved to,
        and the service has no subject parameter.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [owner, colleague])
        await decide(colleague, meeting["id"], "accepted")

        rows = await consents_for(platform, meeting["id"])
        assert [row.decided_by_user_id for row in rows] == [colleague.user_id]
        assert rows[0].policy_version == CONSENT_POLICY_VERSION
        assert rows[0].decided_at is not None


# --------------------------------------------------------------------------
# Rule 2 — everybody, affirmatively, before anything is collectable
# --------------------------------------------------------------------------


class TestEveryParticipantMustAgree:
    async def test_one_silence_is_enough_to_hold_the_whole_meeting(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Silence never ages into agreement.

        The first acceptance changes nothing about what may be collected. Only
        when the last expected participant has personally agreed does the state
        move, and it is the gate that decides that, not a count in a handler.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [owner, colleague])
        assert meeting["state"] == "pending"
        assert meeting["eligible"] is False
        assert meeting["reason"] == ReasonCode.AWAITING_CONSENT.value

        after_one = await decide(owner, meeting["id"], "accepted")
        assert after_one["state"] == "pending"
        assert (await workspace_view(owner, meeting["id"]))["eligible"] is False

        after_both = await decide(colleague, meeting["id"], "accepted")
        assert after_both["state"] == "eligible"

        view = await workspace_view(owner, meeting["id"])
        assert view["eligible"] is True
        assert view["reason"] == ReasonCode.ALLOWED.value
        assert (await stored(platform, meeting["id"])).state is CaptureState.ELIGIBLE

    async def test_eligibility_survives_being_read_again(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Reading the screen does not un-agree the meeting.

        The gate treats a decision taken well before the start, with the meeting
        changed after it, as a reschedule. So recording "everybody agreed" as a
        change to the meeting would make the very next read report a reschedule
        that never happened — and an agreed meeting would flip to refused for a
        reason no customer could see. This is the regression test for that.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])
        await decide(owner, meeting["id"], "accepted")

        for _ in range(3):
            view = await workspace_view(owner, meeting["id"])
            assert view["state"] == "eligible"
            assert view["eligible"] is True
            assert view["reason"] == ReasonCode.ALLOWED.value

    async def test_a_caller_cannot_assert_eligibility(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """There is no state on the wire, in either direction of the write path."""
        owner = await recorded_as_person(platform, await signed_up(app))

        await ask(owner, [owner], expect=422, state="eligible")
        await ask(owner, [owner], expect=422, eligible=True)


# --------------------------------------------------------------------------
# Rule 3 — a new participant invalidates it; a refusal ends it
# --------------------------------------------------------------------------


class TestChangesInvalidate:
    async def test_adding_somebody_takes_the_agreement_away(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Somebody added after the others answered has agreed to nothing.

        Exercised through the service function that production uses to add
        participants, because that is the point: adding one is not an `INSERT`
        anybody can do without the standing being recomputed in the same call.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])
        await decide(owner, meeting["id"], "accepted")
        assert (await workspace_view(owner, meeting["id"]))["state"] == "eligible"

        latecomer = await recorded_as_person(platform, await joins(app, platform, owner))
        assert latecomer.person_id is not None

        async with tenant_session(owner.tenant_id) as db:
            row = await service.lock_request(
                db, tenant_id=owner.tenant_id, meeting_id=uuid.UUID(meeting["id"])
            )
            assert row is not None
            view = await service.add_participants(db, meeting=row, person_ids=[latecomer.person_id])

        assert view.meeting.state is CaptureState.PENDING
        assert view.eligibility.allowed is False

        after = await workspace_view(owner, meeting["id"])
        assert after["state"] == "pending"
        assert after["eligible"] is False
        assert after["participantCount"] == 2

    async def test_a_decline_refuses_the_request_immediately(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """One refusal ends it, and ends it terminally."""
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [owner, colleague])
        await decide(owner, meeting["id"], "accepted")
        result = await decide(colleague, meeting["id"], "declined")

        assert result["state"] == "refused"
        assert (await stored(platform, meeting["id"])).state is CaptureState.REFUSED

        # Afterwards the gate answers `not_collectable`, not `refused`: once the
        # request is closed it is closed for every reason at once, and the gate
        # deliberately stops distinguishing them. The stored state is what says a
        # refusal happened, and it is the field a screen renders.
        view = await workspace_view(owner, meeting["id"])
        assert view["eligible"] is False
        assert view["reason"] == ReasonCode.NOT_COLLECTABLE.value
        assert "nothing will be collected" in view["message"]

    async def test_a_withdrawal_after_everybody_agreed_refuses_it_too(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Agreement is revocable right up until something is collected.

        A product that promises withdrawal and then keeps collecting has made a
        promise it cannot demonstrate it kept.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [owner, colleague])
        await decide(owner, meeting["id"], "accepted")
        assert (await decide(colleague, meeting["id"], "accepted"))["state"] == "eligible"

        result = await decide(colleague, meeting["id"], "withdrawn")

        assert result["state"] == "refused"
        assert result["myDecision"] == "withdrawn"
        assert (await stored(platform, meeting["id"])).state is CaptureState.REFUSED


# --------------------------------------------------------------------------
# Rule 4 — decisions are appended, never edited
# --------------------------------------------------------------------------


class TestAppendOnly:
    async def test_changing_your_mind_supersedes_rather_than_overwrites(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Two rows afterwards, and the first still says what it said.

        The history is the product's only evidence that withdrawal was possible
        and honoured. An `UPDATE`-in-place model cannot produce it, and there is
        no DELETE grant with which to lose it.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])

        await decide(owner, meeting["id"], "accepted")
        await decide(owner, meeting["id"], "withdrawn")

        rows = await consents_for(platform, meeting["id"])
        assert [row.decision for row in rows] == [
            ConsentDecision.ACCEPTED,
            ConsentDecision.WITHDRAWN,
        ]
        assert rows[0].superseded_at is not None
        assert rows[0].decided_at is not None
        assert rows[1].superseded_at is None

    async def test_answering_the_same_way_twice_is_a_double_click(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Idempotent, so a re-render does not look like a fresh decision."""
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])

        first = await decide(owner, meeting["id"], "accepted")
        second = await decide(owner, meeting["id"], "accepted")

        assert first["myDecidedAt"] == second["myDecidedAt"]
        assert len(await consents_for(platform, meeting["id"])) == 1


# --------------------------------------------------------------------------
# Rule 5 — nobody learns who declined, or who is still silent
# --------------------------------------------------------------------------


class TestNobodyLearnsWhoRefused:
    async def test_the_self_view_carries_only_the_callers_own_answer(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """A participant sees the standing, never the person behind it."""
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))
        assert colleague.person_id is not None

        meeting = await ask(owner, [owner, colleague])
        await decide(colleague, meeting["id"], "declined")

        rows = await self_view(owner)
        assert len(rows) == 1
        mine = rows[0]
        assert mine["myDecision"] is None
        assert mine["state"] == "refused"
        # The wording says "somebody", and the payload contains no identifier of
        # the person who refused.
        serialised = str(rows)
        assert str(colleague.person_id) not in serialised
        assert str(colleague.user_id) not in serialised
        assert "declined" not in serialised

    async def test_the_workspace_view_is_counts_and_states(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Counts, and not even a count once it would be arithmetic.

        Three people, two agreed, one refused: reporting "2 accepted" beside
        "refused" names the third by subtraction, so the count is withheld once a
        request is refused.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        second = await recorded_as_person(platform, await joins(app, platform, owner))
        third = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [owner, second, third])
        await decide(owner, meeting["id"], "accepted")

        open_view = await workspace_view(owner, meeting["id"])
        assert open_view["participantCount"] == 3
        assert open_view["acceptedCount"] == 1

        await decide(second, meeting["id"], "accepted")
        await decide(third, meeting["id"], "declined")

        refused_view = await workspace_view(owner, meeting["id"])
        assert refused_view["state"] == "refused"
        assert refused_view["acceptedCount"] is None
        serialised = str(refused_view)
        for member in (second, third):
            assert str(member.person_id) not in serialised
            assert str(member.user_id) not in serialised

    async def test_the_list_carries_the_totals_and_the_promise(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await recorded_as_person(platform, await signed_up(app))
        await ask(owner, [owner])
        await ask(owner, [owner])

        response = await owner.client.get(
            f"/v1/workspaces/{owner.workspace_id}/meetings/capture-requests"
        )
        body = response.json()

        assert body["totals"]["pending"] == 2
        assert body["totals"]["eligible"] == 0
        assert "who declined" in body["notice"]

    async def test_a_member_sees_only_their_own_invitations(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The self list takes no subject, so there is nothing to point at somebody."""
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))
        bystander = await recorded_as_person(platform, await joins(app, platform, owner))

        await ask(owner, [owner, colleague])

        assert len(await self_view(colleague)) == 1
        assert await self_view(bystander) == []


# --------------------------------------------------------------------------
# Rule 6 — CAIRN staff have no path to any of this
# --------------------------------------------------------------------------


class TestStaffHaveNoAccess:
    def test_no_internal_route_reaches_meeting_data(self) -> None:
        """Checked against the schema rather than by reading `internal.py`.

        A back-office route added later would have to appear here, and this fails
        the moment one does. The consent-gated support session remains the only
        path staff have into a workspace at all — and it does not reach these
        tables either, because nothing in `internal/` queries them.
        """
        schema = create_app(Settings(environment="local")).openapi()
        internal = [path for path in schema["paths"] if path.startswith("/v1/internal")]

        assert [path for path in internal if "meeting" in path] == []

    async def test_a_staff_role_alone_reads_no_meeting_request(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Holding a staff role is not membership, and membership is the only door."""
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])

        staff = await signed_up(app)
        platform.add(StaffMember(user_id=staff.user_id, role=StaffRole.SUPPORT))
        await platform.commit()

        listing = await staff.client.get(
            f"/v1/workspaces/{owner.workspace_id}/meetings/capture-requests"
        )
        assert listing.status_code == 404
        assert listing.json()["type"].endswith("/workspace-not-found")

        decision = await staff.client.post(
            f"/v1/workspaces/{owner.workspace_id}/me/meeting-requests/{meeting['id']}/decision",
            json={"decision": "accepted"},
        )
        assert decision.status_code == 404


# --------------------------------------------------------------------------
# Rule 7 — RFC 9457, and 404 where 403 would be a disclosure
# --------------------------------------------------------------------------


class TestErrorContract:
    async def test_an_unknown_request_is_a_problem_document(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await recorded_as_person(platform, await signed_up(app))

        response = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/meetings/capture-requests/{uuid.uuid4()}/cancel"
        )

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["type"].endswith("/meeting-request-not-found")

    async def test_somebody_elses_decision_is_404_and_not_403(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Its existence is not theirs to confirm.

        A 403 would tell a member that a meeting they are not in exists and has a
        capture request — which is a way of discovering who is meeting whom, one
        refused request at a time.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))
        outsider = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [owner, colleague])

        response = await outsider.client.post(
            f"/v1/workspaces/{outsider.workspace_id}/me/meeting-requests/{meeting['id']}/decision",
            json={"decision": "accepted"},
        )

        assert response.status_code == 404
        assert response.json()["type"].endswith("/not-your-meeting-decision")

    async def test_a_missing_meeting_and_a_meeting_that_is_not_yours_look_alike(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """One refusal for both, or the difference between them is the oracle."""
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))
        meeting = await ask(owner, [owner])

        real = await colleague.client.post(
            f"/v1/workspaces/{colleague.workspace_id}/me/meeting-requests/{meeting['id']}/decision",
            json={"decision": "accepted"},
        )
        imaginary = await colleague.client.post(
            f"/v1/workspaces/{colleague.workspace_id}/me/meeting-requests/{uuid.uuid4()}/decision",
            json={"decision": "accepted"},
        )

        assert real.status_code == imaginary.status_code == 404
        assert real.json()["type"] == imaginary.json()["type"]
        assert real.json()["detail"] == imaginary.json()["detail"]

    async def test_a_closed_request_cannot_be_cancelled_again(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])

        first = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/meetings/capture-requests/{meeting['id']}/cancel"
        )
        assert first.status_code == 200
        assert first.json()["state"] == "cancelled"

        second = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/meetings/capture-requests/{meeting['id']}/cancel"
        )
        assert second.status_code == 422
        assert second.json()["type"].endswith("/meeting-not-cancellable")

    async def test_asking_needs_the_permission_to_configure_the_workspace(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """403 here, deliberately: the caller is a member and simply lacks the role.

        A 404 would be a lie that costs a support ticket — unlike the decision
        route, where the resource genuinely is not the caller's to know about.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        member = await recorded_as_person(
            platform, await joins(app, platform, owner, TenantRole.MEMBER)
        )

        await ask(member, [member], expect=403)

        listing = await member.client.get(
            f"/v1/workspaces/{member.workspace_id}/meetings/capture-requests"
        )
        assert listing.status_code == 403


# --------------------------------------------------------------------------
# Rule 8 — fail closed on anything unrecognised
# --------------------------------------------------------------------------


class TestFailsClosed:
    async def test_an_unknown_provider_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await recorded_as_person(platform, await signed_up(app))
        await ask(owner, [owner], expect=422, provider="teams")

    async def test_an_unknown_answer_is_refused(self, app: FastAPI, platform: AsyncSession) -> None:
        """`pending` and `expired` are not answers anybody may give.

        One is the absence of an answer and the other is a conclusion the gate
        reaches; a caller asserting either about themselves would be writing a
        record that means something it does not.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])

        await decide(owner, meeting["id"], "pending", expect=422)
        await decide(owner, meeting["id"], "expired", expect=422)
        await decide(owner, meeting["id"], "maybe", expect=422)

    async def test_a_person_outside_the_workspace_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await recorded_as_person(platform, await signed_up(app))

        response = await ask(owner, [uuid.uuid4()], expect=422)
        assert response["type"].endswith("/meeting-participant-unknown")

    async def test_somebody_with_no_account_cannot_be_made_a_participant(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Refused at creation rather than left pending forever.

        Somebody CAIRN cannot ask is somebody who had no way to refuse, and a
        request that can never be answered is one whose stuck state reads as a
        bug — which is how a gate gets relaxed.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        ghost = await unreachable_person(platform, owner.tenant_id)

        response = await ask(owner, [owner, ghost], expect=422)
        assert response["type"].endswith("/meeting-participant-unreachable")

    async def test_a_meeting_with_no_participants_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """An empty invitation list is not unanimous consent."""
        owner = await recorded_as_person(platform, await signed_up(app))
        await ask(owner, [], expect=422)

    async def test_a_backwards_window_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await recorded_as_person(platform, await signed_up(app))
        start, end = window()

        response = await ask(owner, [owner], expect=422, scheduledStart=end, scheduledEnd=start)
        assert response["type"].endswith("/meeting-window-invalid")

    async def test_a_closed_request_records_no_further_answers(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])

        await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/meetings/capture-requests/{meeting['id']}/cancel"
        )
        result = await decide(owner, meeting["id"], "accepted", expect=422)

        assert result["type"].endswith("/meeting-not-open")
        assert await consents_for(platform, meeting["id"]) == []

    async def test_withdrawing_something_never_agreed_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Withdrawal is taking an agreement back, and there is none to take.

        Filing it quietly as a decline would blur the two, and the difference
        between them is what the record exists to show.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])

        result = await decide(owner, meeting["id"], "withdrawn", expect=422)
        assert result["type"].endswith("/meeting-decision-invalid")

    async def test_one_meeting_gets_one_open_request(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Two requests for one meeting are two sets of answers to one question."""
        owner = await recorded_as_person(platform, await signed_up(app))
        # Held by the test rather than read back from the response: the joining
        # code is deliberately not published, so a caller cannot recover it and
        # neither can this test.
        reference = f"meet-{uuid.uuid4().hex[:12]}"
        await ask(owner, [owner], externalMeetingRef=reference)

        response = await ask(owner, [owner], expect=409, externalMeetingRef=reference)
        assert response["type"].endswith("/meeting-request-exists")

    async def test_the_joining_code_is_never_published(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """**For Meet, the provider reference is the joining code.**

        Anybody holding it can attempt to join the conversation, which makes it
        a credential rather than a label — and this API would otherwise have
        handed it to every participant and every administrator. A request is
        identified to a client by its own `id`, which grants nothing; the
        reference stays in the database, where the future connector needs it and
        nobody else does.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        reference = f"meet-{uuid.uuid4().hex[:12]}"
        await ask(owner, [owner], externalMeetingRef=reference)

        workspace = (
            await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/meetings/capture-requests")
        ).text
        mine = (
            await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/me/meeting-requests")
        ).text

        assert reference not in workspace
        assert reference not in mine
        assert "externalMeetingRef" not in workspace
        assert "externalMeetingRef" not in mine


# --------------------------------------------------------------------------
# The gate is the only calculation
# --------------------------------------------------------------------------


class TestTheGateDecides:
    async def test_eligible_is_written_only_from_the_gates_verdict(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """A participant row with no person behind it blocks the whole meeting.

        Constructed directly, because no route can produce it: an unresolved
        participant is somebody CAIRN cannot ask, and the honest consequence of
        refusing to guess who they are is that nothing is collected. The service
        must take the gate's answer even when a naive count of acceptances would
        say yes.
        """
        owner = await recorded_as_person(platform, await signed_up(app))
        meeting = await ask(owner, [owner])
        await decide(owner, meeting["id"], "accepted")
        assert (await stored(platform, meeting["id"])).state is CaptureState.ELIGIBLE

        platform.add(
            MeetingParticipant(
                tenant_id=owner.tenant_id,
                meeting_id=uuid.UUID(meeting["id"]),
                person_id=None,
                provider_account_id="attendee-unknown",
                status=ParticipantStatus.EXPECTED,
                source=ParticipantSource.CALENDAR,
                added_at=datetime.now(UTC),
            )
        )
        await platform.commit()

        async with tenant_session(owner.tenant_id) as db:
            row = await service.lock_request(
                db, tenant_id=owner.tenant_id, meeting_id=uuid.UUID(meeting["id"])
            )
            assert row is not None
            view = await service.refresh_state(db, meeting=row)

        assert view.eligibility.allowed is False
        assert view.eligibility.reason is ReasonCode.UNRESOLVED_PARTICIPANT
        assert view.meeting.state is CaptureState.PENDING

    async def test_a_refusal_is_terminal(self, app: FastAPI, platform: AsyncSession) -> None:
        """Re-asking is a new request somebody has to justify, not a retry."""
        owner = await recorded_as_person(platform, await signed_up(app))
        colleague = await recorded_as_person(platform, await joins(app, platform, owner))

        meeting = await ask(owner, [owner, colleague])
        await decide(colleague, meeting["id"], "declined")

        await decide(owner, meeting["id"], "accepted", expect=422)
        assert (await stored(platform, meeting["id"])).state is CaptureState.REFUSED
