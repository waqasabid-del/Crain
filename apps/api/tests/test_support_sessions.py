"""Support access: consent-gated, time-boxed, customer-visible.

Step 28's exit criterion is **a support session requires approval, expires, and
appears in the customer's own audit log**, and each clause is tested as a
refusal rather than as a happy path — the failure that matters is access
happening, not access being unavailable.

The property underneath all of them, from md/15 §5.2: *support access is
requested by CAIRN staff and approved by a tenant Owner or Admin — not granted
by staff to themselves.* Every test here is a way of trying to get round that.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource
from cairn_api.db.models import Membership, TenantRole
from cairn_api.db.staff_models import InternalAuditEntry, StaffMember, StaffRole
from cairn_api.db.support_models import (
    SupportScope,
    SupportSession,
    SupportSessionStatus,
)
from cairn_api.db.tenancy import tenant_session
from cairn_api.internal import support
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery"  # noqa: S105
TEST_ORIGIN = "http://localhost:3000"


class Person:
    def __init__(self, client: AsyncClient, user_id: uuid.UUID, workspace_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.workspace_id = workspace_id

    @property
    def tenant_id(self) -> uuid.UUID:
        return uuid.UUID(self.workspace_id)


async def signed_up(app: FastAPI) -> Person:
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
            "workspaceSlug": f"support-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Person(client, uuid.UUID(body["user"]["id"]), body["workspaces"][0]["workspace"]["id"])


async def joins(app: FastAPI, platform: AsyncSession, host: Person, role: TenantRole) -> Person:
    colleague = await signed_up(app)
    platform.add(Membership(tenant_id=host.tenant_id, user_id=colleague.user_id, role=role))
    await platform.commit()
    return Person(colleague.client, colleague.user_id, host.workspace_id)


async def as_staff(
    platform: AsyncSession, person: Person, role: StaffRole = StaffRole.SUPPORT
) -> Person:
    platform.add(StaffMember(user_id=person.user_id, role=role))
    await platform.commit()
    return person


async def request_session(
    staff: Person,
    customer: Person,
    *,
    scope: str = "configuration_diagnostics",
    minutes: int = 60,
    reason: str = "investigating an integration failure",
) -> dict[str, object]:
    response = await staff.client.post(
        f"/v1/internal/tenants/{customer.workspace_id}/support-sessions",
        params={"reason": reason},
        json={"reason": reason, "scope": scope, "minutes": minutes},
    )
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def approve(
    customer: Person, session_id: str, *, approve_it: bool = True
) -> dict[str, object]:
    response = await customer.client.post(
        f"/v1/workspaces/{customer.workspace_id}/support-sessions/{session_id}/decision",
        json={"approve": approve_it},
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def add_activity(tenant_id: uuid.UUID, statement: str) -> None:
    async with tenant_session(tenant_id) as session:
        session.add(
            FactRow(
                tenant_id=tenant_id,
                kind="delivery",
                statement=statement,
                certainty="verified",
                occurred_at=datetime.now(UTC),
                valid_from=datetime.now(UTC),
                sources=[
                    FactSource(
                        tenant_id=tenant_id,
                        source="github",
                        evidence_id=f"ev-{uuid.uuid4().hex[:8]}",
                    )
                ],
            )
        )
        await session.commit()


# --------------------------------------------------------------------------
# Nothing is granted without a customer saying so
# --------------------------------------------------------------------------


class TestAccessRequiresApproval:
    async def test_a_staff_role_alone_reads_no_activity(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The premise of the whole model.

        Holding a staff role is not access. Without an approved content session
        there is no path from the back-office to a workspace's work.
        """
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")

        response = await staff.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert response.status_code == 403, response.text
        assert "Priya" not in response.text

    async def test_a_pending_request_grants_nothing(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")
        await request_session(staff, customer, scope="activity_content", minutes=30)

        response = await staff.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert response.status_code == 403

    async def test_a_rejected_request_grants_nothing(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")
        session = await request_session(staff, customer, scope="activity_content", minutes=30)

        await approve(customer, str(session["id"]), approve_it=False)

        response = await staff.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert response.status_code == 403

    async def test_staff_cannot_approve_their_own_request(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """There is no route that would let them.

        Approval lives on the customer router, behind workspace membership and a
        permission a staff account does not hold in somebody else's workspace.
        """
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)

        response = await staff.client.post(
            f"/v1/workspaces/{customer.workspace_id}/support-sessions/{session['id']}/decision",
            json={"approve": True},
        )
        assert response.status_code == 404, "a staff account is not a member of that workspace"

    async def test_the_domain_refuses_self_approval_even_if_a_route_ever_allowed_it(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Belt and braces, deliberately.

        The API makes this unreachable today. The rule is the feature, so it is
        also enforced where the decision is actually taken.
        """
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        raw = await request_session(staff, customer)

        row = await platform.scalar(
            select(SupportSession).where(SupportSession.id == uuid.UUID(str(raw["id"])))
        )
        assert row is not None

        with pytest.raises(support.SupportError, match="cannot approve"):
            await support.decide(
                platform, support_session=row, approver_user_id=staff.user_id, approve=True
            )


class TestOnlyTheRightPeopleDecide:
    async def test_an_owner_can_approve(self, app: FastAPI, platform: AsyncSession) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)

        body = await approve(customer, str(session["id"]))
        assert body["status"] == "approved"
        assert body["active"] is True
        assert body["expiresAt"] is not None

    async def test_an_admin_can_approve(self, app: FastAPI, platform: AsyncSession) -> None:
        staff = await as_staff(platform, await signed_up(app))
        owner = await signed_up(app)
        admin = await joins(app, platform, owner, TenantRole.ADMIN)
        session = await request_session(staff, owner)

        response = await admin.client.post(
            f"/v1/workspaces/{owner.workspace_id}/support-sessions/{session['id']}/decision",
            json={"approve": True},
        )
        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("role", [TenantRole.MEMBER, TenantRole.VIEWER])
    async def test_a_member_or_viewer_cannot_decide(
        self, app: FastAPI, platform: AsyncSession, role: TenantRole
    ) -> None:
        """Deciding who may look at the team's workspace is a workspace-level
        decision, not an individual one."""
        staff = await as_staff(platform, await signed_up(app))
        owner = await signed_up(app)
        colleague = await joins(app, platform, owner, role)
        session = await request_session(staff, owner)

        response = await colleague.client.post(
            f"/v1/workspaces/{owner.workspace_id}/support-sessions/{session['id']}/decision",
            json={"approve": True},
        )
        assert response.status_code == 403, response.text

    async def test_another_workspace_cannot_approve_it(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Fails closed as a 404: the request is not merely forbidden to an
        outsider, it is invisible."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        stranger = await signed_up(app)
        session = await request_session(staff, customer)

        response = await stranger.client.post(
            f"/v1/workspaces/{stranger.workspace_id}/support-sessions/{session['id']}/decision",
            json={"approve": True},
        )
        assert response.status_code == 404, response.text

    async def test_a_decision_cannot_be_taken_twice(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))

        response = await customer.client.post(
            f"/v1/workspaces/{customer.workspace_id}/support-sessions/{session['id']}/decision",
            json={"approve": False},
        )
        assert response.status_code == 422, response.text


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------


class TestScopeDoesNotWiden:
    async def test_configuration_approval_does_not_unlock_content(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """md/15 §5.2: viewing work content requires a separate escalation and a
        separate approval. This is the case somebody will try first."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")

        session = await request_session(staff, customer, scope="configuration_diagnostics")
        await approve(customer, str(session["id"]))

        response = await staff.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert response.status_code == 403, response.text
        assert "Priya" not in response.text

    async def test_content_requires_its_own_approved_session(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")

        session = await request_session(staff, customer, scope="activity_content", minutes=30)
        await approve(customer, str(session["id"]))

        response = await staff.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert response.status_code == 200, response.text
        assert any("payments migration" in item["statement"] for item in response.json())

    async def test_approval_grants_exactly_what_was_asked_for(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Approving cannot widen a request. A customer approves the words they
        read, not a category the server chose."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer, scope="configuration_diagnostics")

        body = await approve(customer, str(session["id"]))
        assert body["approvedScope"] == "configuration_diagnostics"

    async def test_a_content_session_is_capped_more_tightly(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Four hours of reading somebody's work is standing access with extra
        steps."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)

        response = await staff.client.post(
            f"/v1/internal/tenants/{customer.workspace_id}/support-sessions",
            params={"reason": "asking for too long"},
            json={
                "reason": "investigating something at length",
                "scope": "activity_content",
                "minutes": 240,
            },
        )
        assert response.status_code == 422, response.text

    async def test_a_scope_nobody_defined_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)

        response = await staff.client.post(
            f"/v1/internal/tenants/{customer.workspace_id}/support-sessions",
            params={"reason": "trying a made-up scope"},
            json={"reason": "trying a made-up scope", "scope": "everything", "minutes": 30},
        )
        assert response.status_code == 422, response.text


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------


class TestSessionsExpire:
    async def test_an_expired_session_grants_nothing(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """No standing access (md/15 §5.2).

        The expiry is moved into the past directly, which is the only honest way
        to test a clock without waiting an hour.
        """
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")

        session = await request_session(staff, customer, scope="activity_content", minutes=30)
        await approve(customer, str(session["id"]))

        assert (
            await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}/support/activity")
        ).status_code == 200, "positive control: access worked before it expired"

        row = await platform.scalar(
            select(SupportSession).where(SupportSession.id == uuid.UUID(str(session["id"])))
        )
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await platform.commit()

        response = await staff.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert response.status_code == 403

    async def test_expiry_comes_from_the_server_not_the_request(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """There is no field to send. The duration is minutes, bounded, and the
        instant is computed at approval."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer, minutes=30)

        before = datetime.now(UTC)
        body = await approve(customer, str(session["id"]))
        expires = datetime.fromisoformat(str(body["expiresAt"]))

        assert timedelta(minutes=29) < expires - before < timedelta(minutes=31)

    async def test_a_revoked_session_stops_immediately(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")

        session = await request_session(staff, customer, scope="activity_content", minutes=60)
        await approve(customer, str(session["id"]))
        assert (
            await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}/support/activity")
        ).status_code == 200, "positive control"

        revoked = await customer.client.post(
            f"/v1/workspaces/{customer.workspace_id}/support-sessions/{session['id']}/revoke"
        )
        assert revoked.status_code == 200, revoked.text

        response = await staff.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert response.status_code == 403

    async def test_revoking_is_idempotent(self, app: FastAPI, platform: AsyncSession) -> None:
        """Somebody ending access under pressure should not have to read a
        status first."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))

        for _ in range(2):
            response = await customer.client.post(
                f"/v1/workspaces/{customer.workspace_id}/support-sessions/{session['id']}/revoke"
            )
            assert response.status_code == 200, response.text


# --------------------------------------------------------------------------
# The customer can see all of it
# --------------------------------------------------------------------------


class TestTheCustomerSeesIt:
    async def test_the_history_names_who_what_why_and_when(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """md/15 §5.2's own example: "CAIRN support accessed configuration on
        12 Aug, approved by you, for 40 minutes, reason: integration failure"."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(
            staff, customer, reason="investigating an integration failure", minutes=40
        )
        await approve(customer, str(session["id"]))

        [entry] = (
            await customer.client.get(f"/v1/workspaces/{customer.workspace_id}/support-sessions")
        ).json()

        assert entry["reason"] == "investigating an integration failure"
        assert entry["requestedMinutes"] == 40
        assert entry["requestedScope"] == "configuration_diagnostics"
        assert entry["status"] == "approved"
        assert entry["decidedBy"] is not None
        assert entry["expiresAt"] is not None
        assert entry["breakGlass"] is False

    async def test_every_member_can_read_the_history(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Who looked at your workspace is not administrative information. A
        record only managers can read is one the people it concerns have to take
        on trust."""
        staff = await as_staff(platform, await signed_up(app))
        owner = await signed_up(app)
        viewer = await joins(app, platform, owner, TenantRole.VIEWER)
        await request_session(staff, owner)

        response = await viewer.client.get(f"/v1/workspaces/{owner.workspace_id}/support-sessions")
        assert response.status_code == 200, response.text
        assert len(response.json()) == 1

    async def test_actual_reads_appear_in_the_history(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """An approval is permission; this is use. "Did they actually look" is
        the question, and only these rows answer it."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")

        session = await request_session(staff, customer, scope="activity_content", minutes=30)
        await approve(customer, str(session["id"]))
        await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}/support/activity")

        [entry] = (
            await customer.client.get(f"/v1/workspaces/{customer.workspace_id}/support-sessions")
        ).json()

        assert len(entry["events"]) == 1
        assert entry["events"][0]["scope"] == "activity_content"
        assert "statements" in entry["events"][0]["description"]

    async def test_a_workspace_sees_only_its_own_sessions(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        first = await signed_up(app)
        second = await signed_up(app)
        await request_session(staff, first, reason="looking at the first workspace")

        assert (
            len(
                (
                    await first.client.get(f"/v1/workspaces/{first.workspace_id}/support-sessions")
                ).json()
            )
            == 1
        ), "positive control"

        theirs = (
            await second.client.get(f"/v1/workspaces/{second.workspace_id}/support-sessions")
        ).json()
        assert theirs == []

    async def test_a_stranger_cannot_read_the_history(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        stranger = await signed_up(app)
        await request_session(staff, customer)

        response = await stranger.client.get(
            f"/v1/workspaces/{customer.workspace_id}/support-sessions"
        )
        assert response.status_code == 404, response.text


# --------------------------------------------------------------------------
# The Step 27 guarantees still hold
# --------------------------------------------------------------------------


class TestTheInternalAuditStillCoversThis:
    @pytest.fixture(autouse=True)
    async def _empty_log(self, platform: AsyncSession) -> None:
        """Start from an empty chain.

        The audit log is global by design, and `test_internal.py` deliberately
        corrupts it to prove tampering is detected. Without this, "Step 28's
        writes leave the chain intact" would be asserting that no other test
        broke it first — a different claim, and one that depends on file order.
        """
        from sqlalchemy import text

        await platform.execute(text("DELETE FROM internal_audit_log"))
        await platform.commit()

    async def test_requesting_a_session_is_recorded_with_a_reason(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await request_session(staff, customer, reason="investigating an integration failure")

        entry = await platform.scalar(
            select(InternalAuditEntry).order_by(InternalAuditEntry.sequence.desc()).limit(1)
        )
        assert entry is not None
        assert entry.action == "support.requested"
        assert entry.tenant_id == customer.tenant_id
        assert entry.actor_user_id == staff.user_id
        assert entry.reason == "investigating an integration failure"

    async def test_the_audit_chain_is_still_intact_afterwards(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        from cairn_api.internal import audit

        security = await as_staff(platform, await signed_up(app), StaffRole.SECURITY)
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))

        platform.expire_all()
        assert (await audit.verify(platform)).intact

        body = (await security.client.get("/v1/internal/audit/verify")).json()
        assert body["intact"] is True

    async def test_the_application_role_still_cannot_rewrite_the_audit_log(
        self, session: AsyncSession, platform: AsyncSession, app: FastAPI
    ) -> None:
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await request_session(staff, customer)

        for statement in (
            "UPDATE internal_audit_log SET reason = 'edited'",
            "DELETE FROM internal_audit_log",
        ):
            with pytest.raises(DBAPIError):
                await session.execute(text(statement))
            await session.rollback()


class TestIsolationOfTheNewTables:
    async def test_a_scoped_session_sees_only_its_own_support_rows(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Row-level security, not a remembered `WHERE` clause."""
        staff = await as_staff(platform, await signed_up(app))
        first = await signed_up(app)
        second = await signed_up(app)
        await request_session(staff, first)

        async with tenant_session(first.tenant_id) as scoped:
            assert len(list(await scoped.scalars(select(SupportSession)))) == 1

        async with tenant_session(second.tenant_id) as scoped:
            assert list(await scoped.scalars(select(SupportSession))) == []

    async def test_the_application_role_cannot_create_a_session(
        self, session: AsyncSession, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Staff request platform-side. An application role that could insert
        one could approve its own access from inside a workspace."""
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        customer = await signed_up(app)

        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO support_sessions "
                    "(tenant_id, requested_by_user_id, reason, requested_scope, status, "
                    " requested_minutes) VALUES (:t, :u, 'forged', "
                    "'activity_content', 'approved', 60)"
                ),
                {"t": str(customer.tenant_id), "u": str(customer.user_id)},
            )
        await session.rollback()

    async def test_the_application_role_cannot_delete_a_session(
        self, session: AsyncSession, app: FastAPI, platform: AsyncSession
    ) -> None:
        """A support session that can be deleted cannot be evidenced."""
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await request_session(staff, customer)

        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM support_sessions"))
        await session.rollback()


class TestConfigurationIsGatedToo:
    """Settings and ingestion health are customer data.

    Step 28's first draft gated content only, which left "what is this
    workspace configured to do, and is it healthy" readable by any staff role
    without anybody's consent.
    """

    async def test_a_role_alone_reads_no_configuration(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)

        response = await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")
        assert response.status_code == 403, response.text

    async def test_an_approved_configuration_session_opens_it(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))

        response = await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")
        assert response.status_code == 200, response.text

    async def test_reading_configuration_appears_in_the_customer_history(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The customer sees the read, not only the approval."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))
        await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")

        [entry] = (
            await customer.client.get(f"/v1/workspaces/{customer.workspace_id}/support-sessions")
        ).json()
        assert len(entry["events"]) == 1
        assert entry["events"][0]["scope"] == "configuration_diagnostics"
        assert "settings" in entry["events"][0]["description"]

    async def test_an_expired_configuration_session_closes_it_again(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))
        assert (
            await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")
        ).status_code == 200, "positive control"

        row = await platform.scalar(
            select(SupportSession).where(SupportSession.id == uuid.UUID(str(session["id"])))
        )
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await platform.commit()

        response = await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")
        assert response.status_code == 403


class TestEveryAccessReachesTheTamperEvidentLog:
    """The customer-visible table is updatable by the application role; the
    Step 27 chain is not. Both records are written, so neither is the only one."""

    @pytest.fixture(autouse=True)
    async def _empty_log(self, platform: AsyncSession) -> None:
        from sqlalchemy import text

        await platform.execute(text("DELETE FROM internal_audit_log"))
        await platform.commit()

    async def test_a_content_read_is_in_the_internal_chain(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        await add_activity(customer.tenant_id, "Priya shipped the payments migration.")
        session = await request_session(staff, customer, scope="activity_content", minutes=30)
        await approve(customer, str(session["id"]))

        await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}/support/activity")

        entries = list(
            await platform.scalars(
                select(InternalAuditEntry).where(InternalAuditEntry.action == "support.accessed")
            )
        )
        assert len(entries) == 1
        assert entries[0].tenant_id == customer.tenant_id
        assert entries[0].actor_user_id == staff.user_id
        assert entries[0].detail["scope"] == "activity_content"

    async def test_a_configuration_read_is_in_the_internal_chain(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))

        await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")

        entries = list(
            await platform.scalars(
                select(InternalAuditEntry).where(InternalAuditEntry.action == "support.accessed")
            )
        )
        assert len(entries) == 1
        assert entries[0].detail["scope"] == "configuration_diagnostics"

    async def test_the_chain_survives_a_burst_of_reads(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Access now appends to the chain, so the Step 27 advisory lock has to
        hold for support traffic as well as for staff management."""
        from cairn_api.internal import audit

        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))

        await asyncio.gather(
            *(staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}") for _ in range(5))
        )

        platform.expire_all()
        assert (await audit.verify(platform)).intact


class TestTwoOwnersCannotRace:
    """Two people deciding the same request at the same moment.

    Without a lock both read `pending`, both pass the check, and the second
    overwrites the first's expiry — a session lasting longer than either person
    agreed to.
    """

    async def test_only_one_decision_is_recorded(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        owner = await signed_up(app)
        admin = await joins(app, platform, owner, TenantRole.ADMIN)
        session = await request_session(staff, owner)
        session_id = str(session["id"])

        async def decide(person: Person, approve_it: bool) -> int:
            response = await person.client.post(
                f"/v1/workspaces/{owner.workspace_id}/support-sessions/{session_id}/decision",
                json={"approve": approve_it},
            )
            return response.status_code

        first, second = await asyncio.gather(decide(owner, True), decide(admin, False))

        assert sorted([first, second]) == [200, 422], (
            f"both decisions were accepted: {first}, {second}"
        )

    async def test_the_stored_decision_is_self_consistent(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Whichever decision won, the row must match it.

        An approval that lost the race must not leave an expiry behind, and a
        rejection that lost must not leave the session unapproved-but-expiring.
        """
        staff = await as_staff(platform, await signed_up(app))
        owner = await signed_up(app)
        admin = await joins(app, platform, owner, TenantRole.ADMIN)
        session = await request_session(staff, owner)
        session_id = uuid.UUID(str(session["id"]))

        async def decide(person: Person, approve_it: bool) -> None:
            await person.client.post(
                f"/v1/workspaces/{owner.workspace_id}/support-sessions/{session_id}/decision",
                json={"approve": approve_it},
            )

        await asyncio.gather(decide(owner, True), decide(admin, False))

        platform.expire_all()
        row = await platform.scalar(select(SupportSession).where(SupportSession.id == session_id))
        assert row is not None
        if row.status is SupportSessionStatus.APPROVED:
            assert row.approved_scope is not None
            assert row.expires_at is not None
        else:
            assert row.status is SupportSessionStatus.REJECTED
            assert row.approved_scope is None
            assert row.expires_at is None


class TestTheDatabaseEnforcesEventIntegrity:
    """Invariants the application could bypass, moved into the database."""

    async def test_an_event_cannot_name_another_workspaces_session(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The composite foreign key makes misattribution unrepresentable."""
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        staff = await as_staff(platform, await signed_up(app))
        first = await signed_up(app)
        second = await signed_up(app)
        session = await request_session(staff, first)
        await approve(first, str(session["id"]))

        with pytest.raises(DBAPIError):
            await platform.execute(
                text(
                    "INSERT INTO support_access_events (tenant_id, session_id, scope, description)"
                    " VALUES (:tenant, :session, 'configuration_diagnostics', 'forged')"
                ),
                {"tenant": str(second.tenant_id), "session": str(session["id"])},
            )
        await platform.rollback()

    async def test_an_event_cannot_exceed_the_approved_scope(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """A configuration approval can never carry a content event, whatever a
        future route forgets to check."""
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)
        await approve(customer, str(session["id"]))

        with pytest.raises(DBAPIError):
            await platform.execute(
                text(
                    "INSERT INTO support_access_events (tenant_id, session_id, scope, description)"
                    " VALUES (:tenant, :session, 'activity_content', 'reading the work')"
                ),
                {"tenant": str(customer.tenant_id), "session": str(session["id"])},
            )
        await platform.rollback()

    async def test_an_event_cannot_precede_an_approval(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Recording use against permission that was never given is the specific
        lie this table exists to prevent."""
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)
        session = await request_session(staff, customer)

        with pytest.raises(DBAPIError):
            await platform.execute(
                text(
                    "INSERT INTO support_access_events (tenant_id, session_id, scope, description)"
                    " VALUES (:tenant, :session, 'configuration_diagnostics', 'jumped the gun')"
                ),
                {"tenant": str(customer.tenant_id), "session": str(session["id"])},
            )
        await platform.rollback()


class TestTheLifecycle:
    def test_status_has_no_expired_value(self) -> None:
        """Expiry is a fact about the clock.

        A stored `expired` status is wrong between the moment a session lapses
        and whenever a job gets round to updating it — and during that window
        `status == 'approved'` reads as live access.
        """
        assert {status.value for status in SupportSessionStatus} == {
            "pending",
            "approved",
            "rejected",
            "revoked",
        }

    def test_scope_is_a_closed_set(self) -> None:
        assert {scope.value for scope in SupportScope} == {
            "configuration_diagnostics",
            "activity_content",
        }

    def test_break_glass_is_recorded_and_never_set(self) -> None:
        """The field exists so the customer record can say "this was not
        break-glass" truthfully. No path sets it — see md/16 Step 28 for why it
        is deferred rather than faked.
        """
        import inspect

        from cairn_api.api.routers import internal
        from cairn_api.internal import support as support_module

        sources = inspect.getsource(internal) + inspect.getsource(support_module)
        assert "break_glass=True" not in sources
