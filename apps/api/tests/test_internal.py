"""The internal back-office, and the record of what staff do.

Step 27's exit criterion is **every internal write is logged, tamper-evident**,
and both halves are asserted structurally rather than by example:

- *Every* write is logged: a test enumerates the router and fails if any
  non-GET route lacks the `audited` dependency. Testing three endpoints would
  prove nothing about the fourth somebody adds next month.
- Tamper-evident: the chain is broken deliberately, three different ways, and
  verification must name where.

The third property has no line in the criterion and matters as much: **staff
cannot reach customer content through this router.** CAIRN sells the promise
that nobody is watching people's work, and a back-office that can read a
workspace's facts is that promise broken from the inside.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cairn_api.api.routers import internal
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource
from cairn_api.db.github_models import GitHubInstallation, WebhookDelivery
from cairn_api.db.staff_models import InternalAuditEntry, StaffMember, StaffRole
from cairn_api.db.tenancy import tenant_session
from cairn_api.internal import audit
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery"  # noqa: S105
TEST_ORIGIN = "http://localhost:3000"


class _FixedProvider:
    """A model that always reports the same usage.

    Enough to drive the ledger past a ceiling so the operations screen has a
    refusal to show. Deliberately not `ScriptedProvider`, which reports zero
    tokens and would never reach a token ceiling.
    """

    async def complete(self, request: object) -> Any:
        from cairn_api.pipeline.provider import ModelResponse

        return ModelResponse(text="{}", input_tokens=50, output_tokens=0, model="fixed")


class Actor:
    def __init__(self, client: AsyncClient, user_id: uuid.UUID, workspace_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.workspace_id = workspace_id


async def signed_up(app: FastAPI) -> Actor:
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
            "workspaceSlug": f"internal-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Actor(client, uuid.UUID(body["user"]["id"]), body["workspaces"][0]["workspace"]["id"])


async def as_staff(
    platform: AsyncSession, actor: Actor, role: StaffRole = StaffRole.SECURITY
) -> Actor:
    platform.add(StaffMember(user_id=actor.user_id, role=role))
    await platform.commit()
    return actor


async def with_configuration_session(staff: Actor, customer: Actor) -> None:
    """Give this staff member an approved configuration session on this workspace.

    Reading a workspace's settings and health is reading customer data, so
    Step 28 puts it behind the same consent gate as content. These tests are
    about what the screens show and who may see them, so they establish the
    approval first rather than asserting the gate — `test_support_sessions.py`
    asserts the gate.
    """
    requested = await staff.client.post(
        f"/v1/internal/tenants/{customer.workspace_id}/support-sessions",
        params={"reason": "diagnosing a reported problem"},
        json={
            "reason": "diagnosing a reported problem",
            "scope": "configuration_diagnostics",
            "minutes": 60,
        },
    )
    assert requested.status_code == 201, requested.text

    decided = await customer.client.post(
        f"/v1/workspaces/{customer.workspace_id}/support-sessions/"
        f"{requested.json()['id']}/decision",
        json={"approve": True},
    )
    assert decided.status_code == 200, decided.text


# --------------------------------------------------------------------------
# Who may reach the back-office
# --------------------------------------------------------------------------


class TestAccess:
    async def test_a_customer_cannot_tell_the_back_office_exists(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """404, not 403.

        A signed-in customer learning that `/internal` exists and refuses them
        has learnt something they have no business knowing.
        """
        customer = await signed_up(app)

        response = await customer.client.get("/v1/internal/tenants")
        assert response.status_code == 404, response.text

    async def test_an_anonymous_caller_is_refused(self, app: FastAPI, client: AsyncClient) -> None:
        assert (await client.get("/v1/internal/tenants")).status_code == 401

    async def test_a_staff_member_can_list_workspaces(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))

        response = await staff.client.get("/v1/internal/tenants")
        assert response.status_code == 200, response.text
        assert any(item["slug"].startswith("internal-") for item in response.json())

    async def test_revoked_access_stops_working(self, app: FastAPI, platform: AsyncSession) -> None:
        """Revoked, not deleted — the row survives so "were they staff in March"
        stays answerable — but the session stops resolving immediately."""
        staff = await as_staff(platform, await signed_up(app))
        assert (await staff.client.get("/v1/internal/tenants")).status_code == 200

        member = await platform.scalar(
            select(StaffMember).where(StaffMember.user_id == staff.user_id)
        )
        assert member is not None
        member.revoked_at = datetime.now(UTC)
        await platform.commit()

        assert (await staff.client.get("/v1/internal/tenants")).status_code == 404

    async def test_only_the_security_role_can_grant_access(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        support = await as_staff(platform, await signed_up(app), StaffRole.SUPPORT)
        subject = await signed_up(app)

        response = await support.client.post(
            f"/v1/internal/staff/{subject.user_id}",
            params={"role": "support", "reason": "helping out"},
        )
        assert response.status_code == 403, response.text


# --------------------------------------------------------------------------
# The promise the back-office must not break
# --------------------------------------------------------------------------


class TestLeastPrivilege:
    """md/15 §6: least privilege applies internally too.

    A billing operator has no reason to reach a workspace's ingestion health,
    and a support engineer has none to read every customer's audit history.
    Asserted as a matrix, because the failure is silent: an endpoint that
    forgets its role check works perfectly for the person who wrote it.
    """

    #: Route and the roles that may reach it. Written out rather than derived
    #: from the router, so the test disagrees with the code when one of them is
    #: wrong instead of agreeing with whatever the code happens to say.
    #: Route, the roles that may reach it, and whether it also needs an approved
    #: support session. The per-tenant routes read customer configuration, so
    #: Step 28 gates them by consent as well as by role.
    MATRIX = (
        ("/v1/internal/tenants", {"support", "billing", "engineering", "security"}, False),
        (
            "/v1/internal/tenants/{tenant_id}",
            {"support", "engineering", "billing"},
            True,
        ),
        (
            "/v1/internal/tenants/{tenant_id}/subscription",
            {"support", "engineering", "billing"},
            True,
        ),
        ("/v1/internal/audit", {"security"}, False),
        ("/v1/internal/audit/verify", {"security"}, False),
    )

    @pytest.mark.parametrize(("path", "allowed", "needs_session"), MATRIX)
    @pytest.mark.parametrize("role", ["support", "billing", "engineering", "security"])
    async def test_each_route_admits_only_its_roles(
        self,
        app: FastAPI,
        platform: AsyncSession,
        path: str,
        allowed: set[str],
        needs_session: bool,
        role: str,
    ) -> None:
        staff = await as_staff(platform, await signed_up(app), StaffRole(role))
        customer = await signed_up(app)

        if needs_session and role in allowed:
            await with_configuration_session(staff, customer)

        response = await staff.client.get(path.replace("{tenant_id}", customer.workspace_id))

        if role in allowed:
            assert response.status_code == 200, f"{role} should reach {path}: {response.text}"
        else:
            assert response.status_code == 403, (
                f"{role} reached {path} and should not have: {response.status_code}"
            )

    async def test_configuration_needs_consent_as_well_as_a_role(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Step 28 turned this from a role check into a role check plus consent.

        Holding the right role is no longer enough to open a workspace's
        settings: that workspace has to have approved it, and the approval
        expires. md/15 §6's rule still holds underneath — billing reaches
        configuration and never activity content, which the content gate
        enforces separately.
        """
        billing = await as_staff(platform, await signed_up(app), StaffRole.BILLING)
        customer = await signed_up(app)

        refused = await billing.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/subscription"
        )
        assert refused.status_code == 403, "a role alone should not open a workspace"

        await with_configuration_session(billing, customer)

        allowed = await billing.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/subscription"
        )
        assert allowed.status_code == 200, allowed.text

        # Configuration consent never reaches content.
        content = await billing.client.get(
            f"/v1/internal/tenants/{customer.workspace_id}/support/activity"
        )
        assert content.status_code == 403

    async def test_support_cannot_read_the_audit_log(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Every reason for every action across every customer is a security
        record, not an operational convenience."""
        support = await as_staff(platform, await signed_up(app), StaffRole.SUPPORT)

        assert (await support.client.get("/v1/internal/tenants")).status_code == 200
        assert (await support.client.get("/v1/internal/audit")).status_code == 403

    def test_every_route_declares_its_roles(self) -> None:
        """No route may fall back to "any active staff member".

        The matrix above covers the routes that exist; this fails when somebody
        adds one that checks membership and forgets the role.
        """

        def declares_a_role(dependant: object) -> bool:
            """Walk the whole dependency tree, not only the first level.

            A route may reach its role check through another dependency — the
            content route does, via `active_content_session` — and a check that
            only looked one level deep would report a satisfied requirement as
            missing.
            """
            for dependency in getattr(dependant, "dependencies", []):
                if "requires_staff" in getattr(dependency.call, "__qualname__", ""):
                    return True
                if declares_a_role(dependency):
                    return True
            return False

        undeclared = [
            route.path
            for route in internal.router.routes
            if isinstance(route, APIRoute) and not declares_a_role(route.dependant)
        ]

        assert not undeclared, f"routes with no staff-role requirement: {undeclared}"


class TestOperationsData:
    """Step 29's read models. Metadata only, and only for the roles that run
    the system."""

    OPERATIONS = (
        "/v1/internal/operations/pipeline",
        "/v1/internal/operations/queue",
        "/v1/internal/operations/spend",
        "/v1/internal/operations/evaluation",
        "/v1/internal/operations/slo",
    )

    def test_every_operations_route_is_in_this_list(self) -> None:
        """Otherwise a new one is gated by nothing anybody checked.

        The role and content assertions below are parametrised over `OPERATIONS`,
        so a route missing from it is a route with no test — and it would be
        added by somebody in a hurry to see a number during an incident.
        """
        declared = {path.removeprefix("/v1") for path in self.OPERATIONS}
        actual = {
            route.path
            for route in internal.router.routes
            if isinstance(route, APIRoute) and route.path.startswith("/internal/operations/")
        }
        assert actual == declared

    @pytest.mark.parametrize("path", OPERATIONS)
    @pytest.mark.parametrize("role", ["support", "billing", "engineering", "security"])
    async def test_only_engineering_and_security_may_read_it(
        self, app: FastAPI, platform: AsyncSession, path: str, role: str
    ) -> None:
        """md/15 §6 gives pipeline health, cost and evaluation to Engineering.
        Security is included because an incident is when this data is most
        needed and least convenient to request."""
        staff = await as_staff(platform, await signed_up(app), StaffRole(role))

        response = await staff.client.get(path)

        if role in {"engineering", "security"}:
            assert response.status_code == 200, response.text
        else:
            assert response.status_code == 403, f"{role} read {path}"

    async def test_a_customer_cannot_reach_operations_data(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        customer = await signed_up(app)

        for path in self.OPERATIONS:
            assert (await customer.client.get(path)).status_code == 404

    async def test_pipeline_health_names_no_workspace(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Counts and ages, platform-wide.

        A per-workspace view of what a customer is producing is a support
        session's business, not a dashboard's — and "which team shipped most"
        is the shape of the metric md/05 §B.2 forbids.
        """
        staff = await as_staff(platform, await signed_up(app), StaffRole.ENGINEERING)
        customer = await signed_up(app)

        body = (await staff.client.get("/v1/internal/operations/pipeline")).json()

        assert set(body) == {
            "deliveriesLastHour",
            "deliveriesUnprocessed",
            "oldestUnprocessedMinutes",
            "factsLastHour",
            "workspacesIngesting",
        }
        assert customer.workspace_id not in str(body)

    async def test_spend_reports_the_ledger_and_says_whose_view_it_is(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """In-process, so one replica's view — stated rather than implied,
        because a spend figure that looks global and is not is how a cost
        incident gets missed."""
        staff = await as_staff(platform, await signed_up(app), StaffRole.ENGINEERING)

        body = (await staff.client.get("/v1/internal/operations/spend")).json()

        assert body["live"] is False
        assert set(body) == {
            "live",
            "backend",
            "totalCalls",
            "totalTokens",
            "byStage",
            "ceilingTokens",
            "ceilingCalls",
            "warnings",
            "refusals",
            "workspacesRefused",
            "note",
        }
        assert "replica" in (body["note"] or "")

    async def test_the_spend_screen_shows_the_ceiling_signals(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Capping without signalling is a cost incident nobody hears about.

        The refusal has to reach the screen an operator is already looking at,
        by stage, and with the configured ceiling beside it so "how close" has
        something to be close to.
        """
        from cairn_api.pipeline.provider import ModelRequest
        from cairn_api.pipeline.spend import SPEND_SIGNALS, BudgetedProvider, SpendCeilingError
        from cairn_api.pipeline.spend import TokenLedger as Ledger

        staff = await as_staff(platform, await signed_up(app), StaffRole.ENGINEERING)

        SPEND_SIGNALS.reset()
        try:
            provider = BudgetedProvider(
                inner=_FixedProvider(),
                ledger=Ledger(tenant=str(uuid.uuid4()), max_tokens=10, max_calls=None),
                stage="synthesize",
            )
            await provider.complete(ModelRequest(instruction="go", untrusted_data="secret"))
            with pytest.raises(SpendCeilingError):
                await provider.complete(ModelRequest(instruction="go", untrusted_data="secret"))

            body = (await staff.client.get("/v1/internal/operations/spend")).json()
        finally:
            SPEND_SIGNALS.reset()

        assert body["refusals"] == 1
        assert body["workspacesRefused"] == 1
        line = next(item for item in body["byStage"] if item["stage"] == "synthesize")
        assert line["refusals"] == 1
        assert line["closestApproach"] is not None
        # No workspace and no request text, on a screen a staff role can open
        # without any customer's approval.
        assert "secret" not in str(body)

    async def test_the_slo_screen_reports_a_target_and_a_source_for_every_objective(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """ "Slow" is only a number somebody agreed to if the number is on a
        screen next to where it came from."""
        from cairn_api.ops import slo

        staff = await as_staff(platform, await signed_up(app), StaffRole.ENGINEERING)

        body = (await staff.client.get("/v1/internal/operations/slo")).json()

        assert {item["key"] for item in body["objectives"]} == {
            objective.key for objective in slo.OBJECTIVES
        }
        for item in body["objectives"]:
            assert item["target"] > 0
            assert item["measuredFrom"]
            assert item["windowMinutes"] > 0

    async def test_an_unmeasurable_objective_reports_unmeasurable_rather_than_met(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The failure mode this endpoint exists to avoid.

        Availability has no measurement today, and a status screen that showed
        it as met would be a fabricated number somebody makes a decision with.
        `met` is null and the reason is on the row.
        """
        staff = await as_staff(platform, await signed_up(app), StaffRole.ENGINEERING)

        body = (await staff.client.get("/v1/internal/operations/slo")).json()
        availability = next(item for item in body["objectives"] if item["key"] == "availability")

        assert availability["measurable"] is False
        assert availability["measured"] is None
        assert availability["met"] is None
        assert availability["note"]
        assert body["unmeasurable"] >= 1

    async def test_the_slo_screen_names_no_workspace(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Platform-wide counts. A per-workspace latency view is a support
        session's business, and "which team is slowest" is the shape md/05 §B.2
        forbids outright."""
        staff = await as_staff(platform, await signed_up(app), StaffRole.ENGINEERING)
        customer = await signed_up(app)

        response = await staff.client.get("/v1/internal/operations/slo")

        assert customer.workspace_id not in response.text

    async def test_the_queue_view_says_when_jobs_are_lost_on_restart(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The in-memory broker loses jobs silently. An operator reading this
        screen has to know that before they read the depth."""
        staff = await as_staff(platform, await signed_up(app), StaffRole.ENGINEERING)

        body = (await staff.client.get("/v1/internal/operations/queue")).json()
        assert body["inMemoryBroker"] is True


class TestStaffCannotReachCustomerContent:
    """md/15 §5.2. Reading a customer's work requires an approved, time-boxed
    support session — which is Step 28 and which no staff role can grant
    itself."""

    async def test_no_response_model_on_this_router_can_carry_content(self) -> None:
        """Structural, because behaviour cannot see the endpoint nobody wrote yet.

        A field named `statement`, `narrative`, `claims` or `facts` appearing on
        any back-office response is the moment the promise breaks, and it would
        arrive as a convenience — "just show the last few facts so support can
        see what is wrong".
        """
        forbidden = {"statement", "statements", "narrative", "claims", "facts", "quote", "mention"}

        # The one route that may return content, and only behind an approved,
        # unexpired, content-scoped support session that the customer granted
        # (Step 28). Named explicitly: a pattern-based exemption would let the
        # next content route opt out by being called something similar.
        content_under_support = "/internal/tenants/{tenant_id}/support/activity"

        for route in internal.router.routes:
            if not isinstance(route, APIRoute):
                continue
            if route.path == content_under_support:
                continue
            model = route.response_model
            if model is None:
                continue
            fields = getattr(model, "model_fields", None)
            # `list[Model]` — reach through to the item type.
            if fields is None:
                args = getattr(model, "__args__", ())
                fields = getattr(args[0], "model_fields", {}) if args else {}

            leaked = forbidden & set(fields)
            assert not leaked, f"{route.path} exposes customer content: {leaked}"

    async def test_the_detail_view_reports_health_without_content(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app), StaffRole.SUPPORT)
        customer = await signed_up(app)
        tenant_id = uuid.UUID(customer.workspace_id)

        async with tenant_session(tenant_id) as session:
            session.add(
                FactRow(
                    tenant_id=tenant_id,
                    kind="delivery",
                    statement="Priya shipped the payments migration.",
                    certainty="verified",
                    occurred_at=datetime.now(UTC),
                    valid_from=datetime.now(UTC),
                    sources=[FactSource(tenant_id=tenant_id, source="github", evidence_id="ev-1")],
                )
            )
            await session.commit()

        await with_configuration_session(staff, customer)
        response = await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")
        assert response.status_code == 200, response.text

        body = response.json()
        assert body["memberCount"] == 1
        assert "Priya" not in response.text
        assert "payments migration" not in response.text


# --------------------------------------------------------------------------
# Health and billing
# --------------------------------------------------------------------------


class TestTenantHealth:
    async def test_ingestion_staleness_is_computed_server_side(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """One threshold, applied once. Two operators reading different
        definitions of "stale" reach different conclusions from the same
        screen."""
        staff = await as_staff(platform, await signed_up(app), StaffRole.SUPPORT)
        customer = await signed_up(app)
        tenant_id = uuid.UUID(customer.workspace_id)

        delivery = WebhookDelivery(
            tenant_id=tenant_id,
            delivery_id=str(uuid.uuid4()),
            event_type="push",
            payload={},
        )
        platform.add(delivery)
        await platform.flush()
        delivery.created_at = datetime.now(UTC) - timedelta(days=2)
        await platform.commit()

        await with_configuration_session(staff, customer)

        body = (await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")).json()
        assert body["ingestionStale"] is True
        assert body["unprocessedDeliveries"] == 1

    async def test_integration_state_distinguishes_connected_from_removed(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app), StaffRole.SUPPORT)
        customer = await signed_up(app)
        tenant_id = uuid.UUID(customer.workspace_id)

        platform.add_all(
            [
                GitHubInstallation(
                    tenant_id=tenant_id,
                    installation_id=610_000 + uuid.uuid4().int % 9_000,
                    account_login="acme",
                    account_type="Organization",
                ),
                GitHubInstallation(
                    tenant_id=tenant_id,
                    installation_id=620_000 + uuid.uuid4().int % 9_000,
                    account_login="acme-old",
                    account_type="Organization",
                    uninstalled_at=datetime.now(UTC),
                ),
            ]
        )
        await platform.commit()

        await with_configuration_session(staff, customer)

        body = (await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}")).json()
        assert body["githubConnected"] == 1
        assert body["githubDisconnected"] == 1

    async def test_the_subscription_inspector_says_billing_is_not_implemented(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Rather than inventing a plan to fill the screen. An operator who
        reads a fabricated subscription state will act on it."""
        staff = await as_staff(platform, await signed_up(app), StaffRole.SUPPORT)
        customer = await signed_up(app)

        await with_configuration_session(staff, customer)

        body = (
            await staff.client.get(f"/v1/internal/tenants/{customer.workspace_id}/subscription")
        ).json()
        assert body["providerConnected"] is False
        assert body["seatsInUse"] == 1
        assert "not implemented" in body["note"]


# --------------------------------------------------------------------------
# Every write is logged
# --------------------------------------------------------------------------


class TestStaffManagementGuards:
    async def test_nobody_revokes_their_own_access(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The realistic version is somebody tidying up and locking themselves
        out of the tool they would use to undo it."""
        staff = await as_staff(platform, await signed_up(app))

        response = await staff.client.delete(
            f"/v1/internal/staff/{staff.user_id}", params={"reason": "tidying up"}
        )
        assert response.status_code == 422, response.text
        assert "self-revocation" in response.json()["type"]

    async def test_the_last_security_account_cannot_be_revoked(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Only the security role grants access, so removing the last one leaves
        an installation nobody can administer from inside."""
        keeper = await as_staff(platform, await signed_up(app))
        leaver = await as_staff(platform, await signed_up(app))

        assert (
            await keeper.client.delete(
                f"/v1/internal/staff/{leaver.user_id}", params={"reason": "left the company"}
            )
        ).status_code == 204

        # `keeper` is now the only one, and cannot be removed by the person who
        # would have to do it — themselves.
        response = await keeper.client.delete(
            f"/v1/internal/staff/{keeper.user_id}", params={"reason": "trying anyway"}
        )
        assert response.status_code == 422

    async def test_the_last_security_account_survives_a_third_party_attempt(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The guard that was silently disabled.

        `member.role is StaffRole.SECURITY` compared an enum member against the
        `str` a plain String column returns, so it was always false and this
        path never fired. The column now round-trips as the enum; this asserts
        the rule rather than the comparison.
        """
        keeper = await as_staff(platform, await signed_up(app))
        second = await as_staff(platform, await signed_up(app))

        # `second` may revoke `keeper` while two exist.
        assert (
            await second.client.delete(
                f"/v1/internal/staff/{keeper.user_id}", params={"reason": "left the company"}
            )
        ).status_code == 204

        # `second` is now the only one, and cannot be removed by anybody.
        third = await as_staff(platform, await signed_up(app), StaffRole.SUPPORT)
        assert (
            await third.client.delete(
                f"/v1/internal/staff/{second.user_id}", params={"reason": "trying"}
            )
        ).status_code == 403, "support has no staff-management route"

        response = await second.client.delete(
            f"/v1/internal/staff/{second.user_id}", params={"reason": "trying myself"}
        )
        assert response.status_code == 422

    async def test_granting_access_to_an_unknown_account_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """A typo in a UUID should be a 404, not a foreign-key error surfaced as
        a 500."""
        staff = await as_staff(platform, await signed_up(app))

        response = await staff.client.post(
            f"/v1/internal/staff/{uuid.uuid4()}",
            params={"role": "support", "reason": "onboarding"},
        )
        assert response.status_code == 404, response.text


class TestEveryWriteIsLogged:
    def test_no_mutating_route_can_be_added_without_an_audit_record(self) -> None:
        """The exit criterion, enforced structurally.

        Asserting that three endpoints write an entry proves nothing about the
        fourth. This walks the router and fails on any non-GET route whose
        dependencies do not include one built by `audited`.
        """
        unaudited = []

        for route in internal.router.routes:
            if not isinstance(route, APIRoute):
                continue
            methods = (route.methods or set()) - {"HEAD", "OPTIONS"}
            if methods <= {"GET"}:
                continue

            dependencies = route.dependant.dependencies
            names = {getattr(dependency.call, "__qualname__", "") for dependency in dependencies}
            if not any("audited" in name for name in names):
                unaudited.append(f"{sorted(methods)} {route.path}")

        assert not unaudited, f"mutating routes with no audit record: {unaudited}"

    async def test_granting_staff_access_is_recorded_with_its_reason(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        subject = await signed_up(app)

        response = await staff.client.post(
            f"/v1/internal/staff/{subject.user_id}",
            params={"role": "support", "reason": "onboarding a new support hire"},
        )
        assert response.status_code == 204, response.text

        entries = list(
            await platform.scalars(
                select(InternalAuditEntry).order_by(InternalAuditEntry.sequence.desc())
            )
        )
        assert entries[0].action == "staff.granted"
        assert entries[0].reason == "onboarding a new support hire"
        assert entries[0].actor_user_id == staff.user_id

    async def test_an_action_without_a_reason_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """An action nobody had to justify is one nobody can review."""
        staff = await as_staff(platform, await signed_up(app))
        subject = await signed_up(app)

        response = await staff.client.post(
            f"/v1/internal/staff/{subject.user_id}", params={"role": "support"}
        )
        assert response.status_code == 422, response.text

    async def test_an_action_that_fails_is_still_recorded(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The entry records an attempt, not an outcome.

        It is committed before the handler runs, so a handler that then fails
        cannot take the record with it — the case where the record matters most.
        """
        staff = await as_staff(platform, await signed_up(app))

        response = await staff.client.post(
            f"/v1/internal/staff/{uuid.uuid4()}",
            params={"role": "support", "reason": "granting to a typo"},
        )
        assert response.status_code == 404

        entry = await platform.scalar(
            select(InternalAuditEntry).order_by(InternalAuditEntry.sequence.desc()).limit(1)
        )
        assert entry is not None
        assert entry.reason == "granting to a typo"
        assert entry.action == "staff.granted"

    async def test_reads_are_not_logged(self, app: FastAPI, platform: AsyncSession) -> None:
        """A log that records every list view buries the entries that matter.

        Reading a customer's *work* is the thing md/15 §5 constrains, and that
        needs a support session — audited, approved and time-boxed.
        """
        staff = await as_staff(platform, await signed_up(app))
        before = await platform.scalar(select(InternalAuditEntry.sequence).limit(1))

        await staff.client.get("/v1/internal/tenants")
        await staff.client.get("/v1/internal/audit")

        after = await platform.scalar(select(InternalAuditEntry.sequence).limit(1))
        assert before == after


# --------------------------------------------------------------------------
# Tamper evidence
# --------------------------------------------------------------------------


class TestConcurrentAppends:
    """The chain has to survive two people acting at once.

    Appending reads the last hash and then inserts. Without serialisation, two
    simultaneous actions read the same predecessor, both commit, and the chain
    is broken by ordinary use — no attacker required, and the damage is
    permanent because the log cannot be rewritten to repair it.
    """

    @pytest.fixture(autouse=True)
    async def _empty_log(self, platform: AsyncSession) -> None:
        await platform.execute(text("DELETE FROM internal_audit_log"))
        await platform.commit()

    async def test_concurrent_appends_do_not_break_the_chain(self, platform: AsyncSession) -> None:
        from cairn_api.db.session import platform_session

        actor = await signed_up_user(platform)
        await platform.commit()

        async def append(index: int) -> None:
            # A session each, as two requests would have. Sharing one would
            # serialise them by accident and prove nothing.
            async with platform_session() as session:
                await audit.record(
                    session,
                    actor_user_id=actor,
                    action="test.concurrent",
                    reason=f"writer {index}",
                )
                await session.commit()

        await asyncio.gather(*(append(index) for index in range(6)))

        platform.expire_all()
        result = await audit.verify(platform)
        assert result.intact, f"concurrent appends broke the chain at {result.broken_at}"
        assert result.entries == 6

    async def test_no_two_entries_share_a_predecessor(self, platform: AsyncSession) -> None:
        """The specific corruption, asserted directly.

        Verification catches a fork after the fact; a chain that has forked has
        already lost the property it exists for.
        """
        from cairn_api.db.session import platform_session

        actor = await signed_up_user(platform)
        await platform.commit()

        async def append(index: int) -> None:
            async with platform_session() as session:
                await audit.record(
                    session, actor_user_id=actor, action="test.fork", reason=f"writer {index}"
                )
                await session.commit()

        await asyncio.gather(*(append(index) for index in range(5)))

        platform.expire_all()
        predecessors = list(
            await platform.scalars(
                select(InternalAuditEntry.previous_hash).order_by(InternalAuditEntry.sequence)
            )
        )
        assert len(set(predecessors)) == len(predecessors), "two entries share a predecessor"


class TestTheChainDetectsTampering:
    """md/15 §5.2: the log must be capable of exonerating, which an editable log
    cannot do."""

    @pytest.fixture(autouse=True)
    async def _empty_log(self, platform: AsyncSession) -> None:
        """Start each test from an empty chain.

        The log is global by design — it spans tenants — so one test's
        deliberate corruption is the next test's inherited break, and every
        assertion about *where* the chain failed would point at the previous
        test. Truncated through the owner connection, which is the only one that
        can: the application role has no DELETE, which is the property under
        test two cases down.
        """
        await platform.execute(text("DELETE FROM internal_audit_log"))
        await platform.commit()

    async def test_an_intact_chain_verifies(self, app: FastAPI, platform: AsyncSession) -> None:
        staff = await as_staff(platform, await signed_up(app))
        subject = await signed_up(app)

        for index in range(3):
            await staff.client.post(
                f"/v1/internal/staff/{subject.user_id}",
                params={"role": "support", "reason": f"change {index}"},
            )

        body = (await staff.client.get("/v1/internal/audit/verify")).json()
        assert body["intact"] is True
        assert body["entries"] >= 3

    async def test_editing_an_entry_is_detected(self, app: FastAPI, platform: AsyncSession) -> None:
        """The realistic attack: quietly rewrite the reason on an action that
        later looks bad."""
        staff = await as_staff(platform, await signed_up(app))
        subject = await signed_up(app)
        await staff.client.post(
            f"/v1/internal/staff/{subject.user_id}",
            params={"role": "support", "reason": "the original reason"},
        )

        # Through the owner connection, because the application role has no
        # UPDATE on this table — which is itself the first line of defence.
        await platform.execute(
            text("UPDATE internal_audit_log SET reason = 'a better-looking reason'")
        )
        await platform.commit()

        body = (await staff.client.get("/v1/internal/audit/verify")).json()
        assert body["intact"] is False
        assert body["brokenAt"] is not None
        assert "changed" in body["reason"]

    async def test_moving_a_timestamp_is_detected(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """`occurred_at` is inside the hash.

        Without it, an attacker with database access can move when an action
        appears to have happened — "support opened this account during the
        incident" versus an hour afterwards — and verification would still pass.
        """
        staff = await as_staff(platform, await signed_up(app))
        subject = await signed_up(app)
        await staff.client.post(
            f"/v1/internal/staff/{subject.user_id}",
            params={"role": "support", "reason": "a recorded action"},
        )

        await platform.execute(
            text("UPDATE internal_audit_log SET occurred_at = occurred_at - interval '1 hour'")
        )
        await platform.commit()

        body = (await staff.client.get("/v1/internal/audit/verify")).json()
        assert body["intact"] is False
        assert "changed" in body["reason"]

    async def test_deleting_an_entry_is_detected(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        staff = await as_staff(platform, await signed_up(app))
        subject = await signed_up(app)
        for index in range(3):
            await staff.client.post(
                f"/v1/internal/staff/{subject.user_id}",
                params={"role": "support", "reason": f"change {index}"},
            )

        middle = await platform.scalar(
            select(InternalAuditEntry).order_by(InternalAuditEntry.sequence).offset(1).limit(1)
        )
        assert middle is not None
        await platform.execute(
            text("DELETE FROM internal_audit_log WHERE id = :id"), {"id": middle.id}
        )
        await platform.commit()

        body = (await staff.client.get("/v1/internal/audit/verify")).json()
        assert body["intact"] is False
        assert "missing" in body["reason"]

    async def test_the_application_role_cannot_rewrite_the_log(
        self, session: AsyncSession, platform: AsyncSession, app: FastAPI
    ) -> None:
        """The grants, asserted directly.

        The hash chain makes tampering *detectable*. This makes it impossible
        through the application, which is the path an attacker actually has.
        """
        from sqlalchemy.exc import DBAPIError

        staff = await as_staff(platform, await signed_up(app))
        subject = await signed_up(app)
        await staff.client.post(
            f"/v1/internal/staff/{subject.user_id}",
            params={"role": "support", "reason": "a recorded action"},
        )

        for statement in (
            "UPDATE internal_audit_log SET reason = 'edited'",
            "DELETE FROM internal_audit_log",
        ):
            with pytest.raises(DBAPIError):
                await session.execute(text(statement))
            await session.rollback()

    async def test_verification_names_where_the_chain_broke(self, platform: AsyncSession) -> None:
        """A boolean tells an investigator nothing. The sequence number is where
        they start reading."""
        actor = await signed_up_user(platform)
        first = await audit.record(platform, actor_user_id=actor, action="test.one", reason="first")
        await audit.record(platform, actor_user_id=actor, action="test.two", reason="second")
        await platform.commit()

        await platform.execute(
            text("UPDATE internal_audit_log SET action = 'test.edited' WHERE id = :id"),
            {"id": first.id},
        )
        await platform.commit()

        # Expired first: this session still holds the pre-edit rows in its
        # identity map, and verification would rehash what it remembers rather
        # than what is stored. Production reads on a fresh session per request,
        # which is why the HTTP-driven cases above did not need this.
        platform.expire_all()

        result = await audit.verify(platform)
        assert result.intact is False
        assert result.broken_at == first.sequence


async def signed_up_user(platform: AsyncSession) -> uuid.UUID:
    """A bare user row, for tests that need an actor and no HTTP."""
    from cairn_api.db.models import User

    user = User(email=f"actor-{uuid.uuid4().hex[:10]}@example.com")
    platform.add(user)
    await platform.flush()
    return user.id


class TestTheRoutesAreRegistered:
    def test_the_back_office_is_reachable(self) -> None:
        from cairn_api.api.app import create_app
        from cairn_api.config import Settings

        instance = create_app(Settings(environment="test", cors_allowed_origins=(TEST_ORIGIN,)))
        paths = set(instance.openapi()["paths"])

        for surface in ("/internal/tenants", "/internal/audit", "/internal/audit/verify"):
            assert any(path.endswith(surface) for path in paths), (
                f"no {surface} route: {sorted(paths)}"
            )

    async def test_the_audit_tables_are_not_tenant_scoped(self, platform: AsyncSession) -> None:
        """Deliberate, not an omission.

        Staff are not members of a tenant, and a log readable only from inside
        one workspace could not answer "which customers did this person open".
        """
        rows = await platform.execute(
            text(
                "SELECT relrowsecurity FROM pg_class WHERE relname IN "
                "('internal_audit_log', 'staff_members')"
            )
        )
        assert all(not enabled for (enabled,) in rows)


class TestTenantIsolationStillHolds:
    async def test_staff_endpoints_do_not_leak_across_workspaces(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The back-office spans tenants by design, so the isolation that
        matters is the customer API's — a staff session must not become a way
        into a workspace's content endpoints."""
        staff = await as_staff(platform, await signed_up(app))
        customer = await signed_up(app)

        response = await staff.client.get(f"/v1/workspaces/{customer.workspace_id}/facts")
        assert response.status_code == 404, response.text
