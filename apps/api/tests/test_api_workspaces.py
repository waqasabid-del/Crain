"""HTTP tests for workspaces, membership and authorisation.

The most important tests in the API layer. Everything else here is plumbing; a
defect in one of these is a customer reading another customer's data, or a
Member granting themselves Owner.

Each isolation test asserts against a **second real workspace with real data in
it**. Asserting that a response is empty proves nothing on its own — an endpoint
that is simply broken returns empty too. Every case below first proves the data
is visible to the person who owns it.
"""

from __future__ import annotations

import uuid

import pytest
from cairn_api.api.ratelimit import InMemoryRateLimiter
from cairn_api.config import SESSION_COOKIE_NAME
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ruff: noqa: S105
PASSWORD = "correct-horse-battery"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class Actor:
    """A signed-in person with their own cookie jar.

    A separate client per person rather than swapping cookies on one. Sharing a
    jar makes a test that forgets to swap pass as the wrong user — which, for a
    file whose entire subject is who can see what, is the one failure mode that
    must not be possible.
    """

    def __init__(self, client: AsyncClient, email: str, workspace_id: str) -> None:
        self.client = client
        self.email = email
        self.workspace_id = workspace_id


async def new_actor(app: FastAPI, *, role_label: str = "owner") -> Actor:
    """Create a fresh account, workspace and client."""
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost:3000"},
    )
    email = f"{_unique(role_label)}@example.com"
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "workspaceName": role_label.title(),
            "workspaceSlug": _unique("ws"),
        },
    )
    assert response.status_code == 201, response.text
    workspace_id = response.json()["workspaces"][0]["workspace"]["id"]
    return Actor(client, email, workspace_id)


async def join_as(app: FastAPI, owner: Actor, role: str) -> Actor:
    """Invite someone at `role` and have them redeem it.

    Goes through the real invitation flow rather than inserting a membership
    row, so the tests below exercise the path a real member arrives by.
    """
    email = f"{_unique(role)}@example.com"
    issued = await owner.client.post(
        f"/v1/workspaces/{owner.workspace_id}/invitations",
        json={"email": email, "role": role},
    )
    assert issued.status_code == 201, issued.text

    token = await _invitation_token(app, issued.json()["id"])
    joiner = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost:3000"},
    )
    accepted = await joiner.post(
        "/v1/invitations/accept",
        json={"token": token, "email": email, "password": PASSWORD},
    )
    assert accepted.status_code == 201, accepted.text

    # Redeeming deliberately does not sign anyone in — holding an invitation
    # link is not proof of knowing the password.
    assert SESSION_COOKIE_NAME not in joiner.cookies
    logged_in = await joiner.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert logged_in.status_code == 200

    return Actor(joiner, email, owner.workspace_id)


async def _invitation_token(app: FastAPI, invitation_id: str) -> str:
    """Recover an invitation token.

    Reaches into the database because the API deliberately never returns it —
    it goes to the invited address and nowhere else. A test needing a back door
    here is the correct shape: if this were easy, the endpoint would be leaking.

    Tokens are stored as hashes, so the plaintext is unrecoverable. The row is
    re-stamped with a known token instead.
    """
    from cairn_api.auth.tokens import generate_token, hash_token
    from cairn_api.db.auth_models import Invitation
    from cairn_api.db.session import platform_session

    _ = app
    token = generate_token()
    async with platform_session() as db:
        invitation = await db.get(Invitation, uuid.UUID(invitation_id))
        assert invitation is not None
        invitation.token_hash = hash_token(token)
    return token


class TestTenantIsolation:
    """Two real workspaces. One must never see the other."""

    async def test_a_stranger_cannot_read_another_workspace(self, app: FastAPI) -> None:
        alice = await new_actor(app, role_label="alice")
        mallory = await new_actor(app, role_label="mallory")

        # Positive control first: without it, this test would pass against an
        # endpoint that is simply broken for everyone.
        assert (await alice.client.get(f"/v1/workspaces/{alice.workspace_id}")).status_code == 200

        response = await mallory.client.get(f"/v1/workspaces/{alice.workspace_id}")

        # 404, not 403. A 403 confirms the workspace exists, which lets anyone
        # enumerate customers by guessing IDs.
        assert response.status_code == 404
        assert response.json()["type"].endswith("/workspace-not-found")

    async def test_a_stranger_cannot_list_another_workspaces_members(self, app: FastAPI) -> None:
        alice = await new_actor(app, role_label="alice")
        await join_as(app, alice, "member")
        mallory = await new_actor(app, role_label="mallory")

        visible = await alice.client.get(f"/v1/workspaces/{alice.workspace_id}/members")
        assert len(visible.json()) == 2  # the data genuinely exists

        response = await mallory.client.get(f"/v1/workspaces/{alice.workspace_id}/members")

        assert response.status_code == 404

    async def test_a_stranger_cannot_invite_into_another_workspace(self, app: FastAPI) -> None:
        alice = await new_actor(app, role_label="alice")
        mallory = await new_actor(app, role_label="mallory")

        response = await mallory.client.post(
            f"/v1/workspaces/{alice.workspace_id}/invitations",
            json={"email": f"{_unique('mole')}@example.com", "role": "owner"},
        )

        assert response.status_code == 404

    async def test_a_stranger_cannot_withdraw_another_workspaces_invitation(
        self, app: FastAPI
    ) -> None:
        alice = await new_actor(app, role_label="alice")
        issued = await alice.client.post(
            f"/v1/workspaces/{alice.workspace_id}/invitations",
            json={"email": f"{_unique('pending')}@example.com"},
        )
        invitation_id = issued.json()["id"]
        mallory = await new_actor(app, role_label="mallory")

        response = await mallory.client.delete(
            f"/v1/workspaces/{mallory.workspace_id}/invitations/{invitation_id}"
        )

        # Scoped by tenant *and* invisible to row-level security, so it is not
        # merely forbidden — the row cannot be read at all.
        assert response.status_code == 404

        still_there = await alice.client.get(f"/v1/workspaces/{alice.workspace_id}/invitations")
        assert len(still_there.json()) == 1


class TestAuthorisation:
    """Closes audit finding O4 at the transport layer.

    The permission model was fully tested and called from one place. These
    assert it is now enforced on the routes themselves.
    """

    async def test_a_member_cannot_invite(self, app: FastAPI) -> None:
        owner = await new_actor(app)
        member = await join_as(app, owner, "member")

        response = await member.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations",
            json={"email": f"{_unique('new')}@example.com"},
        )

        # 403, not 404: this caller *is* a member and the workspace plainly
        # exists to them, so hiding it would be a lie that costs a support
        # ticket.
        assert response.status_code == 403
        assert response.json()["type"].endswith("/permission-denied")

    async def test_a_viewer_cannot_invite(self, app: FastAPI) -> None:
        owner = await new_actor(app)
        viewer = await join_as(app, owner, "viewer")

        response = await viewer.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations",
            json={"email": f"{_unique('new')}@example.com"},
        )

        assert response.status_code == 403

    async def test_an_admin_cannot_mint_an_owner(self, app: FastAPI) -> None:
        # An Admin legitimately holds MEMBERS_INVITE, so a permission check
        # alone is not enough. Without the rank rule, an Admin could invite an
        # address they control as Owner and redeem it — acquiring the billing,
        # deletion and transfer rights the Owner/Admin split exists to withhold.
        owner = await new_actor(app)
        admin = await join_as(app, owner, "admin")

        response = await admin.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations",
            json={"email": f"{_unique('puppet')}@example.com", "role": "owner"},
        )

        assert response.status_code == 409
        assert "cannot invite someone as owner" in response.text.lower()

    async def test_an_admin_may_invite_a_member(self, app: FastAPI) -> None:
        # The positive control for the two tests above. Without it they would
        # pass against a route that rejects every invitation.
        owner = await new_actor(app)
        admin = await join_as(app, owner, "admin")

        response = await admin.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations",
            json={"email": f"{_unique('new')}@example.com", "role": "member"},
        )

        assert response.status_code == 201

    async def test_a_member_cannot_list_invitations(self, app: FastAPI) -> None:
        owner = await new_actor(app)
        member = await join_as(app, owner, "member")

        response = await member.client.get(f"/v1/workspaces/{owner.workspace_id}/invitations")

        assert response.status_code == 403

    @pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer"])
    async def test_every_role_sees_the_same_member_list(self, app: FastAPI, role: str) -> None:
        """The symmetry invariant, asserted over HTTP.

        Roles govern configuration; they do not govern how much is visible about
        a person. An Owner sees exactly what a Viewer sees. This is the test that
        fails when someone adds a field only Admins receive — which is the first
        step towards the visibility hierarchy this product exists not to have.
        """
        owner = await new_actor(app)
        actor = owner if role == "owner" else await join_as(app, owner, role)

        response = await actor.client.get(f"/v1/workspaces/{owner.workspace_id}/members")

        assert response.status_code == 200
        fields = set(response.json()[0])
        # `capacity` and `capacityStatedAt` joined 2026-08-19: the person's own
        # statement about availability, symmetric by design - every role sees
        # the same two fields carrying the same self-reported words. Anything
        # else appearing here is still the defect this guard exists for.
        assert fields == {
            "userId",
            "email",
            "displayName",
            "role",
            "joinedAt",
            "capacity",
            "capacityStatedAt",
        }


class TestInvitationFlow:
    async def test_an_invited_person_joins_the_existing_workspace(self, app: FastAPI) -> None:
        """The failure that looks like success.

        A signup path that creates a workspace per account splits one team into
        isolated single-person workspaces, each showing an empty brief. Everyone
        can sign in, so it appears to work.
        """
        owner = await new_actor(app)
        member = await join_as(app, owner, "member")

        session = await member.client.get("/v1/auth/session")
        workspaces = session.json()["workspaces"]

        assert len(workspaces) == 1
        assert workspaces[0]["workspace"]["id"] == owner.workspace_id
        assert workspaces[0]["role"] == "member"

    async def test_an_invitation_cannot_be_redeemed_by_a_different_address(
        self, app: FastAPI
    ) -> None:
        # An invitation is addressed to a person, not a bearer token. Without
        # this, a forwarded link lets anyone join.
        owner = await new_actor(app)
        issued = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations",
            json={"email": f"{_unique('intended')}@example.com"},
        )
        token = await _invitation_token(app, issued.json()["id"])

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:3000"},
        ) as interloper:
            response = await interloper.post(
                "/v1/invitations/accept",
                json={
                    "token": token,
                    "email": f"{_unique('interloper')}@example.com",
                    "password": PASSWORD,
                },
            )

        assert response.status_code == 409
        assert "different email address" in response.text

    async def test_a_withdrawn_invitation_can_no_longer_be_redeemed(self, app: FastAPI) -> None:
        owner = await new_actor(app)
        email = f"{_unique('withdrawn')}@example.com"
        issued = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations",
            json={"email": email},
        )
        token = await _invitation_token(app, issued.json()["id"])

        withdrawn = await owner.client.delete(
            f"/v1/workspaces/{owner.workspace_id}/invitations/{issued.json()['id']}"
        )
        assert withdrawn.status_code == 204

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:3000"},
        ) as invitee:
            response = await invitee.post(
                "/v1/invitations/accept",
                json={"token": token, "email": email, "password": PASSWORD},
            )

        assert response.status_code == 409

    async def test_an_address_can_be_reinvited_after_withdrawal(self, app: FastAPI) -> None:
        # The deadlock that used to be permanent: an unaccepted invitation held
        # the one pending slot for that address forever, and every re-invitation
        # died on the unique index.
        owner = await new_actor(app)
        email = f"{_unique('again')}@example.com"
        first = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations", json={"email": email}
        )
        await owner.client.delete(
            f"/v1/workspaces/{owner.workspace_id}/invitations/{first.json()['id']}"
        )

        second = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/invitations", json={"email": email}
        )

        assert second.status_code == 201


class TestRateLimiting:
    """Closes the second half of audit finding O2."""

    async def test_repeated_failures_are_eventually_refused(
        self, app: FastAPI, limiter: InMemoryRateLimiter
    ) -> None:
        owner = await new_actor(app)
        limiter.reset()

        statuses = [
            (
                await owner.client.post(
                    "/v1/auth/login",
                    json={"email": owner.email, "password": "wrong-password-here"},
                )
            ).status_code
            for _ in range(12)
        ]

        # Ten attempts per address per fifteen minutes, so the eleventh is
        # refused. Everything before it must be a plain 401 — a limit that fires
        # on the third attempt would lock out a person who mistyped.
        assert statuses[:10] == [401] * 10
        assert statuses[10] == 429

    async def test_the_refusal_says_how_long_to_wait(
        self, app: FastAPI, limiter: InMemoryRateLimiter
    ) -> None:
        owner = await new_actor(app)
        limiter.reset()

        response = None
        for _ in range(12):
            response = await owner.client.post(
                "/v1/auth/login",
                json={"email": owner.email, "password": "wrong-password-here"},
            )
            if response.status_code == 429:
                break

        assert response is not None
        assert response.status_code == 429
        # Without Retry-After a well-behaved client has to guess, and guessing
        # means retrying immediately.
        assert int(response.headers["retry-after"]) > 0
        # Deliberately vague about *which* limit fired: naming it would tell an
        # attacker how to spread traffic to avoid it.
        assert "address" not in response.text.lower()
