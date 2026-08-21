"""Work roles: different first screens, identical data.

Step 26's exit criterion is *each of the five roles has a view that makes sense
without explanation* (md/08 §A, md/11 §6). The interesting half is on the client,
because a role changes emphasis rather than content. What has to be true on this
side is narrower and much more important:

- **A work role is not a permission.** `memberships.role` decides what somebody
  may configure. `work_role` decides what CAIRN opens on. The day the second
  starts filtering facts is the day the product acquires the visibility hierarchy
  md/05 §B.2 exists to refuse, so the symmetry is asserted directly rather than
  assumed from the absence of a filter.
- **Only the person themselves can set it.** There is no path through this API
  that writes anybody else's, and this file pins that absence — an
  administrator-assigned work role would be a management classification stored on
  a colleague's record.
- **Declining to answer is an answer.** Null must round-trip, and every endpoint
  has to work for somebody who never said.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource
from cairn_api.db.models import Membership, TenantRole, WorkRole
from cairn_api.db.tenancy import tenant_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery"  # noqa: S105
TEST_ORIGIN = "http://localhost:3000"


class Actor:
    def __init__(self, client: AsyncClient, user_id: str, workspace_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.workspace_id = workspace_id


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": TEST_ORIGIN},
    )


async def founder_of_new_workspace(app: FastAPI) -> Actor:
    client = _client(app)
    suffix = uuid.uuid4().hex[:10]
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"founder-{suffix}@example.com",
            "password": PASSWORD,
            "workspaceName": "Acme",
            "workspaceSlug": f"roles-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Actor(client, body["user"]["id"], body["workspaces"][0]["workspace"]["id"])


async def joins(app: FastAPI, platform: AsyncSession, host: Actor, role: str = "member") -> Actor:
    client = _client(app)
    suffix = uuid.uuid4().hex[:10]
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"colleague-{suffix}@example.com",
            "password": PASSWORD,
            "workspaceName": "Theirs",
            "workspaceSlug": f"theirs-{suffix}",
        },
    )
    assert signup.status_code == 201, signup.text
    user_id = signup.json()["user"]["id"]
    platform.add(
        Membership(
            tenant_id=uuid.UUID(host.workspace_id),
            user_id=uuid.UUID(user_id),
            role=TenantRole(role),
            # Notified, so attribution is not blocked by the Step 25 gate. This
            # file is about roles; the notification rule has its own tests.
            notified_at=datetime.now(UTC),
        )
    )
    await platform.commit()
    return Actor(client, user_id, host.workspace_id)


async def add_fact(tenant_id: uuid.UUID, statement: str) -> None:
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
                people=[FactPerson(tenant_id=tenant_id, mention="Priya Nair")],
            )
        )
        await session.commit()


class TestSayingWhatYouDo:
    async def test_a_role_is_recorded_and_returned(self, app: FastAPI) -> None:
        founder = await founder_of_new_workspace(app)

        response = await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "developer"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["workRole"] == "developer"

        assert (await founder.client.get(f"/v1/workspaces/{founder.workspace_id}/me/role")).json()[
            "workRole"
        ] == "developer"

    async def test_saying_nothing_is_the_starting_state(self, app: FastAPI) -> None:
        """Every screen works for somebody who never answered.

        A default would turn a skipped question into a claim about them that they
        did not make.
        """
        founder = await founder_of_new_workspace(app)

        response = await founder.client.get(f"/v1/workspaces/{founder.workspace_id}/me/role")
        assert response.status_code == 200, response.text
        assert response.json()["workRole"] is None

    async def test_the_answer_can_be_withdrawn(self, app: FastAPI) -> None:
        """Otherwise the only way out of a wrong guess is a different wrong
        guess."""
        founder = await founder_of_new_workspace(app)

        await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "designer"}
        )
        response = await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": None}
        )

        assert response.status_code == 200, response.text
        assert response.json()["workRole"] is None

    @pytest.mark.parametrize("role", ["founder", "developer", "designer", "product", "operations"])
    async def test_every_role_in_the_spec_is_accepted(self, app: FastAPI, role: str) -> None:
        """md/08 Part A names five. A sixth in the interface with no home in the
        API is a picker that fails on selection."""
        founder = await founder_of_new_workspace(app)

        response = await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": role}
        )
        assert response.status_code == 200, response.text

    async def test_something_that_is_not_a_role_is_refused(self, app: FastAPI) -> None:
        founder = await founder_of_new_workspace(app)

        response = await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "chief-vibes"}
        )
        assert response.status_code == 422, response.text

    async def test_a_viewer_may_answer_a_question_about_themselves(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """No permission is declared, deliberately. Requiring one would mean a
        person's own description of their work was something the workspace
        granted them."""
        founder = await founder_of_new_workspace(app)
        viewer = await joins(app, platform, founder, "viewer")

        response = await viewer.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "designer"}
        )
        assert response.status_code == 200, response.text

    async def test_it_reaches_the_session(self, app: FastAPI) -> None:
        """Read from the session by every screen, because a first screen that
        arrives one request late is one the reader watches change under them."""
        founder = await founder_of_new_workspace(app)
        await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "product"}
        )

        session = (await founder.client.get("/v1/auth/session")).json()
        [membership] = session["workspaces"]
        assert membership["workRole"] == "product"
        # The permission role is a separate field and unchanged. The two must
        # never be conflated: one decides what you may configure, the other what
        # CAIRN opens on.
        assert membership["role"] == "owner"


class TestARoleIsNotAPermission:
    """The property this whole feature has to preserve.

    md/05 §B.2 and md/15 §2.2: what a person can see is decided by the symmetry
    rule, never by their role. `work_role` is the field most likely to be wired
    to a filter later — it is called a role, it is on the membership, and every
    other product's equivalent does exactly that.
    """

    async def test_two_roles_see_identical_facts(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        founder = await founder_of_new_workspace(app)
        developer = await joins(app, platform, founder)
        designer = await joins(app, platform, founder)

        await developer.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "developer"}
        )
        await designer.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "designer"}
        )

        await add_fact(uuid.UUID(founder.workspace_id), "Priya shipped rate limiting.")
        await add_fact(uuid.UUID(founder.workspace_id), "The team chose Postgres.")

        theirs = await developer.client.get(f"/v1/workspaces/{founder.workspace_id}/facts")
        hers = await designer.client.get(f"/v1/workspaces/{founder.workspace_id}/facts")

        assert theirs.status_code == 200, theirs.text
        assert [item["statement"] for item in theirs.json()["items"]], "positive control"
        assert theirs.json() == hers.json()

    async def test_stating_a_role_changes_nothing_about_what_is_returned(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The same person, before and after answering.

        Any difference here would mean the answer had become a filter, which is
        the failure mode this field is one rename away from.
        """
        founder = await founder_of_new_workspace(app)
        await add_fact(uuid.UUID(founder.workspace_id), "Priya shipped rate limiting.")

        before = (await founder.client.get(f"/v1/workspaces/{founder.workspace_id}/facts")).json()
        await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "operations"}
        )
        after = (await founder.client.get(f"/v1/workspaces/{founder.workspace_id}/facts")).json()

        assert before == after

    async def test_the_work_role_is_absent_from_the_members_list(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """**Nobody else's business.**

        A colleague's self-description rendered on an administrator's screen is a
        directory of who does what, which is a small step from a directory of who
        should be doing what. It is on the session — where only its owner reads
        it — and nowhere else.
        """
        founder = await founder_of_new_workspace(app)
        member = await joins(app, platform, founder)
        await member.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "designer"}
        )

        listed = await founder.client.get(f"/v1/workspaces/{founder.workspace_id}/members")
        assert listed.status_code == 200, listed.text
        assert "designer" not in listed.text
        for entry in listed.json():
            # Capacity is the one self-description that IS on the list - by
            # design, not by leak: it is shown identically to every role, set
            # only by its owner, and the work role stays off precisely because
            # it never got that contract. `personId` is an identifier rather
            # than a self-description, which is why it may sit alongside it.
            assert set(entry) == {
                "userId",
                "email",
                "displayName",
                "role",
                "joinedAt",
                "capacity",
                "capacityStatedAt",
                "personId",
            }

    async def test_nobody_can_set_somebody_else_s_role(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """There is no endpoint for it, and this is what pins that.

        The route takes no user id: it writes the membership the caller's own
        session resolved to. An Owner wanting to label a colleague has nowhere to
        do it, which is the intended answer rather than a missing feature.
        """
        founder = await founder_of_new_workspace(app)
        member = await joins(app, platform, founder)

        await founder.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "founder"}
        )

        # The founder's answer applied to the founder, and to nobody else.
        theirs = await member.client.get(f"/v1/workspaces/{founder.workspace_id}/me/role")
        assert theirs.json()["workRole"] is None

        # And there is no route that takes a subject.
        from cairn_api.api.app import create_app
        from cairn_api.config import Settings

        instance = create_app(Settings(environment="test", cors_allowed_origins=(TEST_ORIGIN,)))
        for path in instance.openapi()["paths"]:
            if path.endswith("/role"):
                assert "{user_id}" not in path, f"a role route takes a subject: {path}"

    async def test_a_role_is_per_workspace(self, app: FastAPI, platform: AsyncSession) -> None:
        """Somebody can be a founder in their own workspace and a designer in a
        client's. Storing it on the user would force one answer to cover both."""
        founder = await founder_of_new_workspace(app)
        contractor = await joins(app, platform, founder)

        await contractor.client.put(
            f"/v1/workspaces/{founder.workspace_id}/me/role", json={"workRole": "designer"}
        )

        session = (await contractor.client.get("/v1/auth/session")).json()
        by_workspace = {
            entry["workspace"]["id"]: entry["workRole"] for entry in session["workspaces"]
        }
        assert by_workspace[founder.workspace_id] == "designer"
        # Their own workspace, where they signed up, is untouched.
        assert len(by_workspace) == 2
        assert None in by_workspace.values()


class TestTheEnumMatchesTheSpec:
    def test_five_roles_no_more(self) -> None:
        """md/08 §A.6: all five need the same data through different lenses. A
        sixth is a product decision, not an enum edit — it needs a first screen,
        or it is a label that changes nothing."""
        assert {role.value for role in WorkRole} == {
            "founder",
            "developer",
            "designer",
            "product",
            "operations",
        }
