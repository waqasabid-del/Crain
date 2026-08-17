"""Cross-source identity: the two ways in, and every way that must stay shut.

Step 34's exit criterion is *one person, many accounts, and no guessing*. These
tests are written as attempts to get a link CAIRN should refuse — an unverified
address, a matching name, somebody else's account, an administrator writing a
colleague's record — because the failure that matters is a link being made, not
a link being unavailable.

The most important test in the file is
`test_no_route_can_write_another_members_identity`. It asserts the *absence* of
a route, which is the only way to test a design decision that lives in what was
not written: a permission check can be loosened in a later commit and still look
correct, an endpoint that does not exist cannot be.
"""

from __future__ import annotations

import inspect
import re
import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.api.routers import identities as identities_router
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.external_identity_models import (
    ExternalIdentity,
    IdentityLinkState,
    IdentityVerification,
)
from cairn_api.db.identity_models import Identity, IdentityKind, IdentityStatus, Person
from cairn_api.db.models import Membership, TenantRole, User
from cairn_api.db.tenancy import tenant_session
from cairn_api.identity import external
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery"  # noqa: S105
TEST_ORIGIN = "http://localhost:3000"


class Actor:
    """A signed-in person, their workspace, and their `Person` row if any."""

    def __init__(self, client: AsyncClient, user_id: uuid.UUID, workspace_id: str) -> None:
        self.client = client
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.person_id: uuid.UUID | None = None
        self.email = ""

    @property
    def tenant_id(self) -> uuid.UUID:
        return uuid.UUID(self.workspace_id)


async def signed_up(app: FastAPI) -> Actor:
    client = AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": TEST_ORIGIN},
    )
    suffix = uuid.uuid4().hex[:10]
    email = f"person-{suffix}@example.com"
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "workspaceName": "Acme",
            "workspaceSlug": f"identity-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    actor = Actor(client, uuid.UUID(body["user"]["id"]), body["workspaces"][0]["workspace"]["id"])
    actor.email = email
    return actor


async def joins(app: FastAPI, platform: AsyncSession, host: Actor, role: TenantRole) -> Actor:
    """A colleague in the host's workspace, at the given role."""
    colleague = await signed_up(app)
    platform.add(Membership(tenant_id=host.tenant_id, user_id=colleague.user_id, role=role))
    await platform.commit()
    joined = Actor(colleague.client, colleague.user_id, host.workspace_id)
    joined.email = colleague.email
    return joined


async def given_a_person(actor: Actor, *, display_name: str = "Ali") -> uuid.UUID:
    """Attach a `Person` to this user, as attribution would have.

    Written from inside tenant context because that is where the pipeline writes
    it — the policy's WITH CHECK is part of what is under test elsewhere, and a
    fixture that bypassed it would be building a scenario production cannot
    reach.
    """
    async with tenant_session(actor.tenant_id) as session:
        person = Person(tenant_id=actor.tenant_id, user_id=actor.user_id, display_name=display_name)
        session.add(person)
        await session.commit()
        actor.person_id = person.id
        return person.id


async def verify_email(platform: AsyncSession, actor: Actor) -> None:
    """Mark the CAIRN address verified, as the confirmation link would."""
    user = await platform.get(User, actor.user_id)
    assert user is not None
    user.email_verified_at = datetime.now(UTC)
    await platform.commit()


async def confirm(actor: Actor, *, provider: str, account_id: str) -> tuple[int, dict[str, object]]:
    response = await actor.client.post(
        f"/v1/workspaces/{actor.workspace_id}/me/identities",
        json={"provider": provider, "providerAccountId": account_id},
    )
    body: dict[str, object] = response.json() if response.content else {}
    return response.status_code, body


# --------------------------------------------------------------------------
# The two ways in
# --------------------------------------------------------------------------


class TestVerifiedEmailMatch:
    async def test_two_verified_addresses_that_agree_link_the_person(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The automatic route, and every clause of it is load-bearing."""
        actor = await signed_up(app)
        await verify_email(platform, actor)
        person_id = await given_a_person(actor)

        async with tenant_session(actor.tenant_id) as session:
            row = await external.link_by_verified_email(
                session,
                tenant_id=actor.tenant_id,
                provider=ConnectorProvider.GITHUB,
                provider_account_id="MDQ6VXNlcjE=",
                provider_verified_email=actor.email.upper(),
            )
            assert row is not None
            assert row.person_id == person_id
            assert row.verification is IdentityVerification.VERIFIED_EMAIL_MATCH
            assert row.state is IdentityLinkState.ACTIVE
            # The address is kept only because it *was* the evidence.
            assert row.provider_email == actor.email.lower()
            await session.commit()

    async def test_an_unverified_cairn_address_does_not_link(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Matching two claims is not matching two people.

        The provider verified its side; CAIRN has not verified its own. Without
        the `email_verified_at` clause, anybody who could sign up with a
        colleague's address would inherit that colleague's provider account.
        """
        actor = await signed_up(app)
        await given_a_person(actor)
        assert (await platform.get(User, actor.user_id)) is not None

        async with tenant_session(actor.tenant_id) as session:
            row = await external.link_by_verified_email(
                session,
                tenant_id=actor.tenant_id,
                provider=ConnectorProvider.GITHUB,
                provider_account_id="MDQ6VXNlcjI=",
                provider_verified_email=actor.email,
            )

        assert row is None, "an unverified CAIRN address must not be enough"

    async def test_an_unverified_provider_email_has_nowhere_to_be_passed(self) -> None:
        """The refusal is in the signature, not in a check somebody can skip.

        A caller holding an address the provider did *not* mark verified has no
        parameter to put it in: the only one is named `provider_verified_email`,
        and there is no general `link()` taking a verification method as an
        argument for a future caller to pass the wrong one.
        """
        parameters = set(inspect.signature(external.link_by_verified_email).parameters)
        assert "provider_verified_email" in parameters
        assert "email" not in parameters
        assert "provider_email" not in parameters

        assert not hasattr(external, "link"), (
            "a single entry point taking a verification method is a single place "
            "to pass the wrong one"
        )

    async def test_no_code_path_links_by_name_or_similarity(self) -> None:
        """A display name never links anybody, asserted as an absence.

        There is nothing to disable and no threshold to tune, because a
        threshold implies a high enough score would be good enough — and for
        "is this the same human" it is not. So the assertion is that the module
        contains no similarity machinery at all, and that the verification enum
        has exactly the two members that name real evidence.
        """
        assert set(IdentityVerification) == {
            IdentityVerification.VERIFIED_EMAIL_MATCH,
            IdentityVerification.SELF_CONFIRMED,
        }, "a new verification member is a schema migration and a conversation"

        public = {name for name in vars(external) if not name.startswith("_")}
        forbidden = re.compile(
            r"display_name|similar|fuzzy|distance|score|threshold|guess|infer|suggest",
            re.IGNORECASE,
        )
        assert not [name for name in public if forbidden.search(name)]

        # And nothing in the source either, so a private helper cannot smuggle
        # one in under a name the check above would not see.
        source = inspect.getsource(external)
        assert "difflib" not in source
        assert "Levenshtein" not in source
        assert "display_name" not in source


class TestSelfConfirmation:
    async def test_a_person_can_confirm_their_own_account(self, app: FastAPI) -> None:
        actor = await signed_up(app)
        await given_a_person(actor)

        code, body = await confirm(actor, provider="slack", account_id="U012ABCDEF")

        assert code == 201, body
        assert body["provider"] == "slack"
        assert body["providerAccountId"] == "U012ABCDEF"
        assert body["verification"] == "self_confirmed"
        assert body["state"] == "active"

    async def test_confirming_twice_is_a_double_click_not_a_second_claim(
        self, app: FastAPI
    ) -> None:
        actor = await signed_up(app)
        await given_a_person(actor)

        first_code, first = await confirm(actor, provider="github", account_id="MDQ6VXNlcjM=")
        second_code, second = await confirm(actor, provider="github", account_id="MDQ6VXNlcjM=")

        assert first_code == 201
        assert second_code == 201
        assert first["id"] == second["id"]

    async def test_the_explanation_is_words_and_never_a_number(self, app: FastAPI) -> None:
        """md/05 §A.2.1: certainty is categorical, never numeric.

        A percentage next to a person's name implies a threshold, and a
        threshold implies that a high enough score would have been good enough.
        """
        actor = await signed_up(app)
        await given_a_person(actor)

        _, body = await confirm(actor, provider="slack", account_id="U0EXPLAIN1")

        explanation = str(body["explanation"])
        assert "signed in" in explanation
        assert "%" not in explanation
        assert not re.search(r"\b0\.\d+\b", explanation), "no score, ever"
        assert "confidence" not in explanation.lower()

    async def test_a_second_person_claiming_the_same_account_is_refused(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """409, and the refusal names nobody.

        Which colleague holds an account is not the asker's to know: an error
        that named them would be an oracle for mapping accounts to people, one
        refused request at a time.
        """
        owner = await signed_up(app)
        await given_a_person(owner, display_name="Ali")
        colleague = await joins(app, platform, owner, TenantRole.MEMBER)
        await given_a_person(colleague, display_name="Sara")

        first_code, _ = await confirm(owner, provider="github", account_id="MDQ6VXNlcjk=")
        assert first_code == 201

        code, body = await confirm(colleague, provider="github", account_id="MDQ6VXNlcjk=")

        assert code == 409, body
        assert str(body["type"]).endswith("identity-already-linked")
        blob = str(body)
        assert "Ali" not in blob
        assert owner.email not in blob
        assert str(owner.user_id) not in blob

    async def test_a_person_with_no_record_yet_is_told_so_rather_than_silently_dropped(
        self, app: FastAPI
    ) -> None:
        """ "Done" would be a lie — nothing would have been written."""
        actor = await signed_up(app)

        code, body = await confirm(actor, provider="slack", account_id="U0NOPERSON")

        assert code == 403, body
        assert str(body["type"]).endswith("not-your-record")


# --------------------------------------------------------------------------
# Self only, by construction
# --------------------------------------------------------------------------


class TestNobodyWritesSomebodyElsesRecord:
    def test_no_route_can_write_another_members_identity(self, app: FastAPI) -> None:
        """The absence is the feature, so the absence is what is asserted.

        Every write in this router is a `/me/` route resolving its person from
        the session. A route taking a person, user or member id — however well
        gated — would be an administrator writing evidence, in CAIRN's own
        words, that a colleague's work belongs to whoever they chose.
        """
        # Read from the published document rather than by walking `app.routes`.
        # This application mounts routers inside routers, so the leaf paths are
        # not all direct children of `app.routes` — and the document is the
        # stronger subject anyway: it is what a client can actually call.
        published = app.openapi()["paths"]
        paths = {path for path in published if "identit" in path}

        assert paths, "the identities router is not mounted"

        subject_like = re.compile(r"\{(person|user|member|subject|people)_?\w*\}")
        for path in paths:
            assert not subject_like.search(path), f"{path} takes a subject"

        writes = {
            (method.upper(), path)
            for path in paths
            for method in published[path]
            if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        }
        for method, path in writes:
            assert "/me/identities" in path, f"{method} {path} writes a link outside /me/"

    def test_the_confirm_body_has_no_subject_field(self) -> None:
        """Following `me.py::set_work_role`: the person comes from the session."""
        from cairn_api.api.schemas import ConfirmIdentityRequest

        assert set(ConfirmIdentityRequest.model_fields) == {"provider", "provider_account_id"}

    async def test_an_owner_cannot_revoke_a_colleagues_link(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """404 rather than 403: a link that is not yours does not exist to you."""
        owner = await signed_up(app)
        await given_a_person(owner, display_name="Ali")
        colleague = await joins(app, platform, owner, TenantRole.MEMBER)
        await given_a_person(colleague, display_name="Sara")

        _, link = await confirm(colleague, provider="slack", account_id="U0COLLEAGUE")

        response = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/me/identities/{link['id']}/revoke",
            json={"disputed": False},
        )

        assert response.status_code == 404, response.text

        # And the colleague's link is untouched.
        listing = await colleague.client.get(
            f"/v1/workspaces/{colleague.workspace_id}/me/identities"
        )
        assert listing.json()["identities"][0]["state"] == "active"


class TestProposalsAreNeverAMenu:
    async def test_proposals_are_only_the_callers_own(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The claim-a-colleague attack, attempted through the list endpoint.

        A member's `proposals` must contain their own unconfirmed identifiers
        and nothing else. If it ever listed the workspace's unresolved accounts,
        the second person to open the screen would take whatever the first had
        not claimed — recorded, with CAIRN's own evidence field, as
        `SELF_CONFIRMED`.
        """
        owner = await signed_up(app)
        owner_person = await given_a_person(owner, display_name="Ali")
        colleague = await joins(app, platform, owner, TenantRole.MEMBER)
        colleague_person = await given_a_person(colleague, display_name="Sara")

        async with tenant_session(owner.tenant_id) as session:
            session.add_all(
                [
                    Identity(
                        tenant_id=owner.tenant_id,
                        person_id=owner_person,
                        kind=IdentityKind.EMAIL,
                        value="ali@work.test",
                        status=IdentityStatus.PROPOSED,
                    ),
                    Identity(
                        tenant_id=owner.tenant_id,
                        person_id=colleague_person,
                        kind=IdentityKind.GITHUB_LOGIN,
                        value="sara-at-work",
                        status=IdentityStatus.PROPOSED,
                    ),
                ]
            )
            await session.commit()

        response = await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/me/identities")

        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["value"] for item in body["proposals"]] == ["ali@work.test"]
        assert "sara-at-work" not in response.text
        assert body["notice"]

    async def test_an_unclaimed_account_is_not_offered_to_anybody(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """A `Person` with no user — a contractor who never signed in.

        Their proposed identifiers belong to their record, not to a picker.
        """
        owner = await signed_up(app)
        await given_a_person(owner, display_name="Ali")

        async with tenant_session(owner.tenant_id) as session:
            stranger = Person(tenant_id=owner.tenant_id, display_name="Unclaimed Contractor")
            session.add(stranger)
            await session.flush()
            session.add(
                Identity(
                    tenant_id=owner.tenant_id,
                    person_id=stranger.id,
                    kind=IdentityKind.GITHUB_LOGIN,
                    value="unclaimed-contractor",
                    status=IdentityStatus.PROPOSED,
                )
            )
            await session.commit()

        response = await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/me/identities")

        assert response.status_code == 200
        assert response.json()["proposals"] == []
        assert "unclaimed-contractor" not in response.text
        assert "Unclaimed Contractor" not in response.text


# --------------------------------------------------------------------------
# Revocation keeps the evidence
# --------------------------------------------------------------------------


class TestRevocation:
    async def test_revoking_keeps_the_row_and_how_it_was_made(self, app: FastAPI) -> None:
        actor = await signed_up(app)
        await given_a_person(actor)
        _, link = await confirm(actor, provider="github", account_id="MDQ6VXNlcjc=")

        response = await actor.client.post(
            f"/v1/workspaces/{actor.workspace_id}/me/identities/{link['id']}/revoke",
            json={"disputed": False},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == "revoked"
        assert body["revokedAt"] is not None
        assert body["revokedReason"]
        # The evidence survives the revocation: what CAIRN believed and why is
        # part of the record somebody checks when attribution went wrong.
        assert body["verification"] == "self_confirmed"
        assert body["providerAccountId"] == "MDQ6VXNlcjc="

        async with tenant_session(actor.tenant_id) as session:
            row = await session.scalar(
                select(ExternalIdentity).where(ExternalIdentity.id == uuid.UUID(str(link["id"])))
            )
            assert row is not None, "revocation must not delete the row"
            assert row.verification is IdentityVerification.SELF_CONFIRMED

    async def test_disputing_says_it_was_never_theirs(self, app: FastAPI) -> None:
        actor = await signed_up(app)
        await given_a_person(actor)
        _, link = await confirm(actor, provider="slack", account_id="U0DISPUTED")

        response = await actor.client.post(
            f"/v1/workspaces/{actor.workspace_id}/me/identities/{link['id']}/revoke",
            json={"disputed": True},
        )

        assert response.json()["state"] == "disputed"

    async def test_revoking_twice_is_idempotent(self, app: FastAPI) -> None:
        """A double-click is not an error, and must not move the timestamp."""
        actor = await signed_up(app)
        await given_a_person(actor)
        _, link = await confirm(actor, provider="slack", account_id="U0TWICE001")

        url = f"/v1/workspaces/{actor.workspace_id}/me/identities/{link['id']}/revoke"
        first = await actor.client.post(url, json={"disputed": False})
        second = await actor.client.post(url, json={"disputed": False})

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["revokedAt"] == first.json()["revokedAt"]
        assert second.json()["state"] == "revoked"

    async def test_a_revoked_account_no_longer_resolves(self, app: FastAPI) -> None:
        """Revocation is not cosmetic: only `ACTIVE` links attribute."""
        actor = await signed_up(app)
        await given_a_person(actor)
        _, link = await confirm(actor, provider="github", account_id="MDQ6VXNlcjg=")

        await actor.client.post(
            f"/v1/workspaces/{actor.workspace_id}/me/identities/{link['id']}/revoke",
            json={"disputed": False},
        )

        async with tenant_session(actor.tenant_id) as session:
            resolved = await external.resolve_person(
                session,
                provider=ConnectorProvider.GITHUB,
                provider_account_id="MDQ6VXNlcjg=",
            )

        assert resolved is None, "unresolved is a first-class answer"


# --------------------------------------------------------------------------
# One workspace cannot see or take another's links
# --------------------------------------------------------------------------


class TestTenantIsolation:
    async def test_another_workspaces_link_is_invisible_and_unclaimable(self, app: FastAPI) -> None:
        """Two workspaces, one provider account id.

        The exclusive index is scoped per tenant, so the same account id in a
        different workspace is a different thing entirely — and the second
        workspace must be able to claim it without seeing that the first has.
        """
        first = await signed_up(app)
        await given_a_person(first, display_name="Ali")
        second = await signed_up(app)
        await given_a_person(second, display_name="Jordan")

        first_code, first_link = await confirm(first, provider="github", account_id="MDQ6U0hBUkVE")
        assert first_code == 201

        listing = await second.client.get(f"/v1/workspaces/{second.workspace_id}/me/identities")
        assert listing.status_code == 200
        assert listing.json()["identities"] == []
        assert str(first_link["id"]) not in listing.text

        # Not blocked by the other workspace's claim, because it is not the
        # same account as far as this workspace is concerned.
        second_code, _ = await confirm(second, provider="github", account_id="MDQ6U0hBUkVE")
        assert second_code == 201

        # And neither can revoke the other's row.
        response = await second.client.post(
            f"/v1/workspaces/{second.workspace_id}/me/identities/{first_link['id']}/revoke",
            json={"disputed": False},
        )
        assert response.status_code == 404

    async def test_resolution_never_crosses_the_boundary(self, app: FastAPI) -> None:
        first = await signed_up(app)
        await given_a_person(first, display_name="Ali")
        second = await signed_up(app)

        await confirm(first, provider="slack", account_id="U0CROSSTEN")

        async with tenant_session(second.tenant_id) as session:
            resolved = await external.resolve_person(
                session, provider=ConnectorProvider.SLACK, provider_account_id="U0CROSSTEN"
            )

        assert resolved is None


# --------------------------------------------------------------------------
# Attribution health: counts, and only for the people who configure things
# --------------------------------------------------------------------------


class TestAttributionHealth:
    async def test_an_owner_sees_counts(self, app: FastAPI) -> None:
        actor = await signed_up(app)
        await given_a_person(actor)
        await confirm(actor, provider="github", account_id="MDQ6SEVBTFRI")

        response = await actor.client.get(f"/v1/workspaces/{actor.workspace_id}/attribution-health")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["resolvedByProvider"] == {"github": 1}
        assert body["unresolvedByProvider"] == {}
        assert body["disputed"] == 0
        assert body["revoked"] == 0
        assert body["notice"]

    async def test_an_admin_sees_counts(self, app: FastAPI, platform: AsyncSession) -> None:
        owner = await signed_up(app)
        admin = await joins(app, platform, owner, TenantRole.ADMIN)

        response = await admin.client.get(f"/v1/workspaces/{admin.workspace_id}/attribution-health")

        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("role", [TenantRole.MEMBER, TenantRole.VIEWER])
    async def test_a_member_or_viewer_is_refused(
        self, app: FastAPI, platform: AsyncSession, role: TenantRole
    ) -> None:
        owner = await signed_up(app)
        colleague = await joins(app, platform, owner, role)

        response = await colleague.client.get(
            f"/v1/workspaces/{colleague.workspace_id}/attribution-health"
        )

        assert response.status_code == 403, response.text

    async def test_the_response_carries_no_person_at_all(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """md/05 §B.3.3 and md/15 §2.3, asserted against the payload.

        A per-person breakdown would reclassify the product, and an Admin may
        not see more about a member than the member sees. So the body must
        contain no user id, no person id, no email address and no provider
        account id — not filtered out by a client, absent from the response.
        """
        owner = await signed_up(app)
        person_id = await given_a_person(owner, display_name="Ali Rahman")
        colleague = await joins(app, platform, owner, TenantRole.MEMBER)
        colleague_person = await given_a_person(colleague, display_name="Sara Bennett")

        await confirm(owner, provider="github", account_id="MDQ6QVVESVRPUg==")
        _, disputed = await confirm(colleague, provider="slack", account_id="U0AUDITOR1")
        await colleague.client.post(
            f"/v1/workspaces/{colleague.workspace_id}/me/identities/{disputed['id']}/revoke",
            json={"disputed": True},
        )

        response = await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/attribution-health")
        raw = response.text

        assert response.status_code == 200, raw
        for secret in (
            str(owner.user_id),
            str(colleague.user_id),
            str(person_id),
            str(colleague_person),
            owner.email,
            colleague.email,
            "Ali Rahman",
            "Sara Bennett",
            "MDQ6QVVESVRPUg==",
            "U0AUDITOR1",
        ):
            assert secret not in raw, f"attribution health leaked {secret!r}"

        # And no UUID of any kind, which catches an identifier added later under
        # a field name this test could not have predicted.
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw)
        assert "@" not in raw.replace("\\u0040", "")

        body = response.json()
        assert body["disputed"] == 1
        assert body["unresolvedByProvider"] == {"slack": 1}

    def test_the_response_model_has_nowhere_to_put_a_person(self) -> None:
        """Belt and braces: the shape, not just one sample of it.

        `AttributionHealth` counts links grouped by provider and state. There is
        no field here that could carry a name, and none that counts anybody's
        activity — an "unresolved by person" breakdown is a leaderboard with the
        ranking left as an exercise for the reader.
        """
        from cairn_api.api.schemas import AttributionHealthResponse

        assert set(AttributionHealthResponse.model_fields) == {
            "resolved_by_provider",
            "unresolved_by_provider",
            "disputed",
            "revoked",
            "notice",
        }

    def test_the_service_offers_no_per_person_variant(self) -> None:
        assert set(inspect.signature(external.attribution_health).parameters) == {"session"}
        assert not any("by_person" in name or "per_person" in name for name in vars(external))


def test_the_router_docstring_states_why_there_is_no_menu() -> None:
    """The reasoning is in the code, where the next author will read it."""
    doc = identities_router.my_identities.__doc__ or ""
    assert "menu of unclaimed accounts" in doc
    assert "claim-a-colleague" in doc
