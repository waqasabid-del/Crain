"""Tenant administration, and the two places it must refuse.

Step 25's exit criterion is *an Owner can manage the workspace without contacting
support*. That is a support-cost target with a security consequence: every task
an administrator cannot do is a task a member of CAIRN's staff does for them, in
their data, on their word.

So most of this file is ordinary — roles change, members leave, integrations stop
reading. Three groups are not ordinary and are the reason the file is long:

- **The refusals.** A workspace that loses its last Owner cannot be given one
  from inside, and the recovery path is the support ticket this step exists to
  remove. Enforced in the API rather than in the interface, because a
  confirmation dialog is a suggestion and a 422 is not.
- **The asymmetry on the notification screen.** Who has been notified is named,
  because it is an obligation owed to each person. Who has opted out is a count,
  because a list of names beside "opted out" is a list of employees who declined
  to be recorded, handed to whoever writes their review.
- **Retention that deletes.** A retention period the system does not apply is the
  most damaging sentence this product could publish, because the Trust & Privacy
  Center publishes it to the audience deciding whether the rest is true.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.config import SESSION_COOKIE_NAME
from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.github_models import GitHubInstallation, WebhookDelivery
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Membership, TenantRole
from cairn_api.db.tenancy import tenant_session
from cairn_api.pipeline import retention
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery"  # noqa: S105
TEST_ORIGIN = "http://localhost:3000"


class Actor:
    """Somebody signed in, with their own cookie jar.

    A client per person rather than swapping cookies on one: in a file about who
    may do what, a test that forgets to swap must fail rather than quietly pass
    as the wrong person.
    """

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


async def owner_of_new_workspace(app: FastAPI) -> Actor:
    client = _client(app)
    suffix = uuid.uuid4().hex[:10]
    response = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"owner-{suffix}@example.com",
            "password": PASSWORD,
            "workspaceName": "Acme",
            "workspaceSlug": f"admin-{suffix}",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Actor(client, body["user"]["id"], body["workspaces"][0]["workspace"]["id"])


async def joins(app: FastAPI, platform: AsyncSession, owner: Actor, role: str) -> Actor:
    """Add a colleague at `role` and sign them in.

    Written directly rather than through the invitation flow. The invitation
    path has its own tests, and threading a token out of the database here would
    make every test in this file depend on a feature none of them is about.
    """
    client = _client(app)
    suffix = uuid.uuid4().hex[:10]
    signup = await client.post(
        "/v1/auth/signup",
        json={
            "email": f"member-{suffix}@example.com",
            "password": PASSWORD,
            "workspaceName": "Theirs",
            "workspaceSlug": f"theirs-{suffix}",
        },
    )
    assert signup.status_code == 201, signup.text
    user_id = signup.json()["user"]["id"]

    platform.add(
        Membership(
            tenant_id=uuid.UUID(owner.workspace_id),
            user_id=uuid.UUID(user_id),
            role=TenantRole(role),
        )
    )
    await platform.commit()
    return Actor(client, user_id, owner.workspace_id)


# --------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------


class TestRoles:
    async def test_an_owner_can_change_a_member_s_role(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        response = await owner.client.patch(
            f"/v1/workspaces/{owner.workspace_id}/members/{member.user_id}",
            json={"role": "admin"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["role"] == "admin"

    async def test_a_member_cannot_promote_themselves(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The permission check, on the endpoint that would be worth attacking."""
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        response = await member.client.patch(
            f"/v1/workspaces/{owner.workspace_id}/members/{member.user_id}",
            json={"role": "owner"},
        )
        assert response.status_code == 403, response.text

    async def test_nobody_changes_their_own_role(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Including somebody who has the permission.

        The realistic version is an Owner demoting themselves while tidying up
        and losing billing access on a Friday. There is a transfer flow for
        handing a workspace over; this is not it.
        """
        owner = await owner_of_new_workspace(app)
        await joins(app, platform, owner, "owner")

        response = await owner.client.patch(
            f"/v1/workspaces/{owner.workspace_id}/members/{owner.user_id}",
            json={"role": "member"},
        )
        assert response.status_code == 422, response.text
        assert "self-role-change" in response.json()["type"]

    async def test_the_last_owner_cannot_be_demoted(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """A workspace with no Owner cannot be given one from inside it.

        Which makes the recovery path a support ticket — the exact thing this
        step exists to remove.
        """
        owner = await owner_of_new_workspace(app)
        admin = await joins(app, platform, owner, "admin")

        response = await admin.client.patch(
            f"/v1/workspaces/{owner.workspace_id}/members/{owner.user_id}",
            json={"role": "member"},
        )
        assert response.status_code == 422, response.text
        assert "last-owner" in response.json()["type"]

    async def test_a_second_owner_makes_the_first_demotable(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The positive control. Without it, the test above would pass against an
        endpoint that refused every demotion."""
        owner = await owner_of_new_workspace(app)
        second = await joins(app, platform, owner, "owner")

        response = await second.client.patch(
            f"/v1/workspaces/{owner.workspace_id}/members/{owner.user_id}",
            json={"role": "member"},
        )
        assert response.status_code == 200, response.text

    async def test_a_stranger_sees_a_workspace_that_does_not_exist(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")
        stranger = await owner_of_new_workspace(app)

        response = await stranger.client.patch(
            f"/v1/workspaces/{owner.workspace_id}/members/{member.user_id}",
            json={"role": "admin"},
        )
        # 404 rather than 403: membership of another workspace is not something
        # a non-member is entitled to have confirmed.
        assert response.status_code == 404, response.text


class TestRemoval:
    async def test_removing_a_member_ends_their_access(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        assert (
            await member.client.get(f"/v1/workspaces/{owner.workspace_id}")
        ).status_code == 200, "positive control"

        response = await owner.client.delete(
            f"/v1/workspaces/{owner.workspace_id}/members/{member.user_id}"
        )
        assert response.status_code == 204, response.text

        # The session still exists — they have their own workspace — but it no
        # longer resolves here.
        assert (await member.client.get(f"/v1/workspaces/{owner.workspace_id}")).status_code == 404

    async def test_their_record_is_not_deleted_with_them(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The decision worth arguing with, asserted rather than assumed.

        A leaver's work is the team's history: the decision they made in March is
        why the system is shaped as it is, and removing it on their last day
        rewrites the record for everyone still there.
        """
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        person = Person(
            tenant_id=uuid.UUID(owner.workspace_id),
            display_name="Priya Nair",
            user_id=uuid.UUID(member.user_id),
        )
        platform.add(person)
        await platform.commit()

        await owner.client.delete(f"/v1/workspaces/{owner.workspace_id}/members/{member.user_id}")

        async with tenant_session(uuid.UUID(owner.workspace_id)) as session:
            remaining = list(await session.scalars(select(Person)))
        assert [row.display_name for row in remaining] == ["Priya Nair"]

    async def test_the_last_owner_cannot_remove_themselves(self, app: FastAPI) -> None:
        owner = await owner_of_new_workspace(app)

        response = await owner.client.delete(
            f"/v1/workspaces/{owner.workspace_id}/members/{owner.user_id}"
        )
        assert response.status_code == 422, response.text
        assert "last-owner" in response.json()["type"]

    async def test_a_viewer_cannot_remove_anybody(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await owner_of_new_workspace(app)
        viewer = await joins(app, platform, owner, "viewer")
        member = await joins(app, platform, owner, "member")

        response = await viewer.client.delete(
            f"/v1/workspaces/{owner.workspace_id}/members/{member.user_id}"
        )
        assert response.status_code == 403, response.text


# --------------------------------------------------------------------------
# Integrations
# --------------------------------------------------------------------------


class TestIntegrations:
    async def test_every_member_can_see_what_is_connected(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Not administrators only.

        What is connected decides what CAIRN can see about the person reading.
        Hiding it behind a role would mean a Viewer had to ask permission to find
        out what was being read about them.
        """
        owner = await owner_of_new_workspace(app)
        viewer = await joins(app, platform, owner, "viewer")
        platform.add(
            GitHubInstallation(
                tenant_id=uuid.UUID(owner.workspace_id),
                installation_id=770_000 + uuid.uuid4().int % 90_000,
                account_login="acme-inc",
                account_type="Organization",
            )
        )
        await platform.commit()

        response = await viewer.client.get(f"/v1/workspaces/{owner.workspace_id}/integrations")
        assert response.status_code == 200, response.text
        [integration] = response.json()
        assert integration["source"] == "github"
        assert integration["account"] == "acme-inc"
        assert integration["disconnectedAt"] is None

    async def test_the_connection_record_reaches_the_interface(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Step 31's connector fields are real data or they are absent.

        The interface renders a fact or omits the row; it never fills a gap with
        something plausible. So this asserts both halves: what the connector
        genuinely knows arrives, and what it does not know arrives as null rather
        than as a value derived from something else.
        """
        from sqlalchemy import text as sql

        owner = await owner_of_new_workspace(app)
        installation_id = 910_000 + uuid.uuid4().int % 80_000

        await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/integrations/github",
            json={
                "installationId": installation_id,
                "accountLogin": "acme-inc",
                "accountType": "Organization",
            },
        )

        # The scopes a provider granted are connector state, not installation
        # state, so they are set where the connector records them.
        await platform.execute(
            sql(
                "UPDATE source_connections SET scopes = :scopes "
                "WHERE installation_id = :installation_id"
            ),
            {
                "scopes": '["contents:read", "pull_requests:read"]',
                "installation_id": str(installation_id),
            },
        )
        await platform.commit()

        [integration] = (
            await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/integrations")
        ).json()

        assert integration["scopes"] == ["contents:read", "pull_requests:read"]
        # Nothing has synced and nobody recorded an authoriser for a projected
        # connection, so both are null rather than guessed from connectedAt.
        assert integration["lastSuccessfulSyncAt"] is None
        assert integration["authorisedBy"] is None
        assert integration["revokedAt"] is None

    async def test_connecting_does_not_start_reading_history_by_itself(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Connecting a source is permission to watch from now on.

        Reading months of past activity is a second, larger decision — it pulls
        in work by people who never saw the connection happen — so it needs the
        caller to name the repositories. A connect that quietly began importing
        everything would make the consent notice arrive after the collection.

        Asserted on the count the API returns, because "no backfill ran" is not
        something a reader could otherwise verify.
        """
        owner = await owner_of_new_workspace(app)
        installation_id = 860_000 + uuid.uuid4().int % 90_000

        response = await owner.client.post(
            f"/v1/workspaces/{owner.workspace_id}/integrations/github",
            json={
                "installationId": installation_id,
                "accountLogin": "acme-inc",
                "accountType": "Organization",
                # No `repositories`: the caller connected, and asked for nothing
                # historical.
            },
        )

        assert response.status_code in (200, 201), response.text
        assert response.json()["backfillRuns"] == 0, "connecting silently began reading history"

    async def test_disconnecting_stops_capture_and_keeps_the_record(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Marked, not deleted.

        Deleting the row would erase the record that the integration ever
        existed, turning months of activity into facts with no explanation of
        where they came from.
        """
        owner = await owner_of_new_workspace(app)
        installation_id = 780_000 + uuid.uuid4().int % 90_000
        platform.add(
            GitHubInstallation(
                tenant_id=uuid.UUID(owner.workspace_id),
                installation_id=installation_id,
                account_login="acme-inc",
                account_type="Organization",
            )
        )
        await platform.commit()

        response = await owner.client.delete(
            f"/v1/workspaces/{owner.workspace_id}/integrations/github/{installation_id}"
        )
        assert response.status_code == 204, response.text

        listed = await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/integrations")
        [integration] = listed.json()
        assert integration["disconnectedAt"] is not None, "the connection is still shown as live"

    async def test_a_member_cannot_disconnect(self, app: FastAPI, platform: AsyncSession) -> None:
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")
        installation_id = 790_000 + uuid.uuid4().int % 90_000
        platform.add(
            GitHubInstallation(
                tenant_id=uuid.UUID(owner.workspace_id),
                installation_id=installation_id,
                account_login="acme-inc",
                account_type="Organization",
            )
        )
        await platform.commit()

        response = await member.client.delete(
            f"/v1/workspaces/{owner.workspace_id}/integrations/github/{installation_id}"
        )
        assert response.status_code == 403, response.text

    async def test_one_workspace_cannot_disconnect_another_s_integration(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await owner_of_new_workspace(app)
        stranger = await owner_of_new_workspace(app)
        installation_id = 800_000 + uuid.uuid4().int % 90_000
        platform.add(
            GitHubInstallation(
                tenant_id=uuid.UUID(owner.workspace_id),
                installation_id=installation_id,
                account_login="acme-inc",
                account_type="Organization",
            )
        )
        await platform.commit()

        response = await stranger.client.delete(
            f"/v1/workspaces/{stranger.workspace_id}/integrations/github/{installation_id}"
        )
        assert response.status_code == 404, response.text


# --------------------------------------------------------------------------
# Privacy and retention
# --------------------------------------------------------------------------


class TestPrivacySettings:
    async def test_an_owner_can_change_the_retention_period(self, app: FastAPI) -> None:
        owner = await owner_of_new_workspace(app)

        response = await owner.client.put(
            f"/v1/workspaces/{owner.workspace_id}/privacy", json={"retentionDays": 90}
        )
        assert response.status_code == 200, response.text
        assert response.json()["retentionDays"] == 90

    async def test_the_default_is_twelve_months(self, app: FastAPI) -> None:
        owner = await owner_of_new_workspace(app)

        response = await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/privacy")
        assert response.json()["retentionDays"] == 365

    @pytest.mark.parametrize("days", [0, 3, 3650])
    async def test_a_period_outside_the_range_is_refused(self, app: FastAPI, days: int) -> None:
        owner = await owner_of_new_workspace(app)

        response = await owner.client.put(
            f"/v1/workspaces/{owner.workspace_id}/privacy", json={"retentionDays": days}
        )
        assert response.status_code == 422, response.text

    async def test_a_member_can_read_the_settings_but_not_change_them(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Readable by everyone: these are facts about what happens to the
        reader's own activity, and a person should not need a role to learn
        them."""
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        assert (
            await member.client.get(f"/v1/workspaces/{owner.workspace_id}/privacy")
        ).status_code == 200

        response = await member.client.put(
            f"/v1/workspaces/{owner.workspace_id}/privacy", json={"retentionDays": 30}
        )
        assert response.status_code == 403, response.text

    async def test_region_is_reported_and_not_settable(self, app: FastAPI) -> None:
        """Moving a workspace between regions is a data migration under
        compliance pressure, not a dropdown — and a control that silently did
        nothing would be worse than its absence."""
        owner = await owner_of_new_workspace(app)

        assert (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/privacy")).json()[
            "region"
        ] == "us-central1"

        response = await owner.client.put(
            f"/v1/workspaces/{owner.workspace_id}/privacy",
            json={"retentionDays": 90, "region": "europe-west1"},
        )
        # Rejected rather than ignored: silently dropping an unrecognised field
        # means an administrator's change vanishes without an error.
        assert response.status_code == 422, response.text


class TestRetentionIsEnforced:
    """The setting deletes. Without this the Trust & Privacy Center is a claim
    nothing backs."""

    async def test_raw_activity_past_the_window_is_deleted(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await owner_of_new_workspace(app)
        tenant_id = uuid.UUID(owner.workspace_id)

        old = WebhookDelivery(
            tenant_id=tenant_id,
            delivery_id=str(uuid.uuid4()),
            event_type="push",
            payload={"commits": [{"message": "old"}]},
        )
        recent = WebhookDelivery(
            tenant_id=tenant_id,
            delivery_id=str(uuid.uuid4()),
            event_type="push",
            payload={"commits": [{"message": "recent"}]},
        )
        platform.add_all([old, recent])
        await platform.flush()
        old.created_at = datetime.now(UTC) - timedelta(days=400)
        await platform.commit()

        removed = await retention.sweep(platform)

        assert removed >= 1
        remaining = list(
            await platform.scalars(
                select(WebhookDelivery).where(WebhookDelivery.tenant_id == tenant_id)
            )
        )
        assert [row.payload["commits"][0]["message"] for row in remaining] == ["recent"]

    async def test_a_shorter_window_takes_effect_on_the_next_sweep(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Shortening retention deletes what has just fallen outside it. The
        honest consequence, and the interface states it before the change."""
        owner = await owner_of_new_workspace(app)
        tenant_id = uuid.UUID(owner.workspace_id)

        delivery = WebhookDelivery(
            tenant_id=tenant_id,
            delivery_id=str(uuid.uuid4()),
            event_type="push",
            payload={},
        )
        platform.add(delivery)
        await platform.flush()
        delivery.created_at = datetime.now(UTC) - timedelta(days=60)
        await platform.commit()

        # Inside the default window: nothing happens.
        await retention.sweep(platform)
        assert await platform.get(WebhookDelivery, delivery.id) is not None, "positive control"

        await owner.client.put(
            f"/v1/workspaces/{owner.workspace_id}/privacy", json={"retentionDays": 30}
        )
        await retention.sweep(platform)

        platform.expire_all()
        assert await platform.get(WebhookDelivery, delivery.id) is None

    async def test_each_workspace_gets_its_own_window(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """One statement, every tenant, each with its own cutoff. A loop over
        tenants would be one round trip each to ask the same question with a
        different number — and the bug it hides is one workspace's setting being
        applied to another's data."""
        keeps = await owner_of_new_workspace(app)
        deletes = await owner_of_new_workspace(app)
        await deletes.client.put(
            f"/v1/workspaces/{deletes.workspace_id}/privacy", json={"retentionDays": 7}
        )

        rows = []
        for actor in (keeps, deletes):
            row = WebhookDelivery(
                tenant_id=uuid.UUID(actor.workspace_id),
                delivery_id=str(uuid.uuid4()),
                event_type="push",
                payload={},
            )
            rows.append(row)
        platform.add_all(rows)
        await platform.flush()
        for row in rows:
            row.created_at = datetime.now(UTC) - timedelta(days=30)
        await platform.commit()

        # Read before expiring: afterwards `row.id` is a lazy load, and a lazy
        # load on an expired instance outside the session's greenlet is an
        # error about greenlets rather than about retention.
        kept_id, swept_id = rows[0].id, rows[1].id

        await retention.sweep(platform)
        platform.expire_all()

        assert await platform.get(WebhookDelivery, kept_id) is not None
        assert await platform.get(WebhookDelivery, swept_id) is None

    async def test_facts_are_not_swept(self, app: FastAPI, platform: AsyncSession) -> None:
        """Retention covers the raw payloads, not what CAIRN understood.

        Deleting facts on a timer would mean a workspace losing the decision it
        made two years ago, which is the thing they kept CAIRN for. Somebody who
        wants their own record removed has a different route, and none of them is
        a timer.
        """
        assert retention.sweep.__module__ == "cairn_api.pipeline.retention"
        source = (retention.sweep.__doc__ or "") + (retention.__doc__ or "")
        assert "facts" in source.lower()

        # The property itself, not the documentation of it.
        from cairn_api.db.fact_models import Fact as FactRow

        owner = await owner_of_new_workspace(app)
        tenant_id = uuid.UUID(owner.workspace_id)
        async with tenant_session(tenant_id) as session:
            row = FactRow(
                tenant_id=tenant_id,
                kind="decision",
                statement="The team chose Postgres.",
                certainty="verified",
                occurred_at=datetime.now(UTC) - timedelta(days=800),
                valid_from=datetime.now(UTC) - timedelta(days=800),
            )
            session.add(row)
            await session.commit()
            fact_id = row.id

        await retention.sweep(platform)

        async with tenant_session(tenant_id) as session:
            assert await session.get(FactRow, fact_id) is not None


# --------------------------------------------------------------------------
# Worker notification
# --------------------------------------------------------------------------


class TestNotificationStatus:
    async def test_it_names_who_has_not_been_notified(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Named, because notification is an obligation owed to each person
        before capture begins, and an Owner who cannot see who is outstanding
        cannot discharge it."""
        owner = await owner_of_new_workspace(app)
        await joins(app, platform, owner, "member")

        response = await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/notifications")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["memberCount"] == 2
        assert all(person["notifiedAt"] is None for person in body["people"])

    async def test_serving_the_notification_records_it(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """ "Notified" means the notification's own content was delivered to
        them — deliberately narrower than "they read it", which no software
        knows."""
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        assert (
            await member.client.get(f"/v1/workspaces/{owner.workspace_id}/me/sources")
        ).status_code == 200

        body = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/notifications")).json()
        stamped = {person["userId"]: person["notifiedAt"] for person in body["people"]}
        assert stamped[member.user_id] is not None
        assert stamped[owner.user_id] is None, "only the person who was shown it is stamped"

    async def test_the_first_time_is_the_recorded_time(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The question an auditor asks is *when were they told*. Refreshing the
        screen a year later must not answer it with today."""
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        await member.client.get(f"/v1/workspaces/{owner.workspace_id}/me/sources")
        first = (
            await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/notifications")
        ).json()["people"]

        await member.client.get(f"/v1/workspaces/{owner.workspace_id}/me/sources")
        second = (
            await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/notifications")
        ).json()["people"]

        assert [person["notifiedAt"] for person in first] == [
            person["notifiedAt"] for person in second
        ]

    async def test_opt_outs_are_a_number_and_never_a_list(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """**The most considered decision in this step.**

        An opt-out is a person's own decision about their own record. A list of
        names beside "opted out" is a list of employees who declined to be
        recorded, handed to whoever writes their review — and a person weighing
        that possibility before opting out produces a low rate that means
        nothing, which is the number md/11 §7 makes the product's trust
        barometer.
        """
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        person = Person(
            tenant_id=uuid.UUID(owner.workspace_id),
            display_name="Priya Nair",
            user_id=uuid.UUID(member.user_id),
        )
        platform.add(person)
        await platform.flush()
        platform.add(
            SourceOptOut(
                tenant_id=uuid.UUID(owner.workspace_id), person_id=person.id, source="github"
            )
        )
        await platform.commit()

        body = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/notifications")).json()

        assert body["optedOutCount"] == 1
        # Structural, because behaviour cannot see this one: the endpoint that
        # would leak the names is the one somebody adds a field to.
        assert "Priya Nair" not in str(body)
        for person_entry in body["people"]:
            assert set(person_entry) == {"userId", "email", "displayName", "notifiedAt"}

    async def test_a_member_cannot_read_the_notification_status(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """It names people, and whether a colleague has been notified is
        compliance administration rather than something everyone needs."""
        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")

        response = await member.client.get(f"/v1/workspaces/{owner.workspace_id}/notifications")
        assert response.status_code == 403, response.text


# --------------------------------------------------------------------------
# Trust & Privacy Center
# --------------------------------------------------------------------------


class TestTrustCenter:
    async def test_every_member_can_open_it(self, app: FastAPI, platform: AsyncSession) -> None:
        """md/05 §B.6: customer-facing, not admin-only. A page about trust that
        some of the team cannot open has answered the question it was written to
        address."""
        owner = await owner_of_new_workspace(app)
        viewer = await joins(app, platform, owner, "viewer")

        response = await viewer.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")
        assert response.status_code == 200, response.text

    async def test_its_numbers_come_from_this_workspace(self, app: FastAPI) -> None:
        """A trust page stating a retention period the system does not apply is
        the most damaging sentence this product could publish."""
        owner = await owner_of_new_workspace(app)
        await owner.client.put(
            f"/v1/workspaces/{owner.workspace_id}/privacy", json={"retentionDays": 90}
        )

        body = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")).json()
        assert body["retentionDays"] == 90
        assert body["region"] == "us-central1"

    async def test_it_says_which_sources_are_actually_connected(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        owner = await owner_of_new_workspace(app)

        before = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")).json()
        assert {source["source"]: source["connected"] for source in before["sources"]}[
            "github"
        ] is (False)

        platform.add(
            GitHubInstallation(
                tenant_id=uuid.UUID(owner.workspace_id),
                installation_id=810_000 + uuid.uuid4().int % 90_000,
                account_login="acme-inc",
                account_type="Organization",
            )
        )
        await platform.commit()

        after = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")).json()
        assert {source["source"]: source["connected"] for source in after["sources"]}["github"] is (
            True
        )

    async def test_every_source_is_listed_whether_connected_or_not(self, app: FastAPI) -> None:
        """ "What could CAIRN read here if somebody switched it on" is the
        question a person joining a workspace is actually asking."""
        from cairn_api.pipeline import consent

        owner = await owner_of_new_workspace(app)
        body = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")).json()

        assert [source["source"] for source in body["sources"]] == list(consent.SOURCES)

    async def test_the_refusals_are_the_same_ones_the_notification_makes(
        self, app: FastAPI
    ) -> None:
        """Two hand-maintained lists of promises is one list plus a way for the
        product to start promising different things in different places."""
        from cairn_api.api.routers.me import REFUSALS

        owner = await owner_of_new_workspace(app)
        body = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")).json()

        assert body["refusals"] == list(REFUSALS)

    async def test_it_names_its_subprocessors(self, app: FastAPI) -> None:
        """md/02 §5. "Trusted partners" is the phrasing of a company that would
        rather its customers did not check."""
        owner = await owner_of_new_workspace(app)
        body = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")).json()

        titles = " ".join(item["title"] for item in body["subprocessors"])
        assert "Google" in titles
        assert body["subprocessors"], "a subprocessor list is the first thing a review asks for"

    async def test_it_counts_who_is_still_waiting_to_be_notified(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """Shown to everybody, because "has everyone here been told?" is a
        question the whole team has a stake in — as a count, because "who has
        not been told" is administration."""
        owner = await owner_of_new_workspace(app)
        await joins(app, platform, owner, "member")

        body = (await owner.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")).json()
        assert body["awaitingNotification"] == 2
        assert "email" not in str(body).lower() or "@" not in str(body)

    async def test_a_stranger_cannot_read_it(self, app: FastAPI) -> None:
        owner = await owner_of_new_workspace(app)
        stranger = await owner_of_new_workspace(app)

        response = await stranger.client.get(f"/v1/workspaces/{owner.workspace_id}/trust")
        assert response.status_code == 404, response.text


class TestNotificationIsEnforcedNotDeclared:
    """`Membership.notified_at` said "ingestion checks this column; NULL means no
    capture, with no exception path" — and nothing checked it, which made the
    comment the most confident false statement in the schema.

    The failure that was possible is not a bug report: a workspace attributing
    somebody's work to them before anybody had told them the product existed.
    """

    async def test_nothing_is_attributed_to_a_member_who_has_not_been_notified(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        from cairn_api.db.fact_models import Fact as FactRow
        from cairn_api.db.identity_models import Identity, IdentityKind
        from cairn_api.domain import Certainty
        from cairn_api.pipeline import store
        from cairn_api.pipeline.facts import Fact, FactKind, SourceRef

        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")
        tenant_id = uuid.UUID(owner.workspace_id)

        person = Person(
            tenant_id=tenant_id, display_name="Priya Nair", user_id=uuid.UUID(member.user_id)
        )
        platform.add(person)
        await platform.flush()
        platform.add(
            Identity(
                tenant_id=tenant_id,
                person_id=person.id,
                kind=IdentityKind.GITHUB_LOGIN,
                value=f"priya-{uuid.uuid4().hex[:8]}",
            )
        )
        await platform.commit()

        incoming = Fact(
            kind=FactKind.DELIVERY,
            statement="Priya shipped rate limiting.",
            sources=[SourceRef(source="github", evidence_id=f"ev-{uuid.uuid4().hex[:8]}")],
            certainty=Certainty.VERIFIED,
            people=["Priya Nair"],
            occurred_at=datetime.now(UTC),
        )

        async def attribute() -> uuid.UUID:
            async with tenant_session(tenant_id) as session:
                await store.apply(session, tenant_id=tenant_id, incoming=[incoming])
                await store.attach_people_bulk(session, tenant_id=tenant_id, fact_ids=[incoming.id])
                await session.commit()
                return incoming.id

        fact_id = await attribute()

        async with tenant_session(tenant_id) as session:
            fact = await session.get(FactRow, fact_id)
            assert fact is not None
            [link] = fact.people
            # The mention survives with nobody behind it — the same shape an
            # unresolved mention has, and the same shape an opt-out leaves.
            assert link.mention == "Priya Nair"
            assert link.person_id is None, "attributed to somebody nobody had told"

    async def test_once_they_have_been_notified_attribution_resumes(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """The positive control, and the reason this is a gate rather than a
        wall: the moment the obligation is discharged, the product works."""
        from cairn_api.db.fact_models import Fact as FactRow
        from cairn_api.db.identity_models import Identity, IdentityKind
        from cairn_api.domain import Certainty
        from cairn_api.pipeline import store
        from cairn_api.pipeline.facts import Fact, FactKind, SourceRef

        owner = await owner_of_new_workspace(app)
        member = await joins(app, platform, owner, "member")
        tenant_id = uuid.UUID(owner.workspace_id)

        person = Person(
            tenant_id=tenant_id, display_name="Ali Hassan", user_id=uuid.UUID(member.user_id)
        )
        platform.add(person)
        await platform.flush()
        platform.add(
            Identity(
                tenant_id=tenant_id,
                person_id=person.id,
                kind=IdentityKind.GITHUB_LOGIN,
                value=f"ali-{uuid.uuid4().hex[:8]}",
            )
        )
        await platform.commit()

        # Serving the notification is what discharges it.
        assert (
            await member.client.get(f"/v1/workspaces/{owner.workspace_id}/me/sources")
        ).status_code == 200

        incoming = Fact(
            kind=FactKind.DELIVERY,
            statement="Ali fixed the staging certificate.",
            sources=[SourceRef(source="github", evidence_id=f"ev-{uuid.uuid4().hex[:8]}")],
            certainty=Certainty.VERIFIED,
            people=["Ali Hassan"],
            occurred_at=datetime.now(UTC),
        )
        async with tenant_session(tenant_id) as session:
            await store.apply(session, tenant_id=tenant_id, incoming=[incoming])
            await store.attach_people_bulk(session, tenant_id=tenant_id, fact_ids=[incoming.id])
            await session.commit()

        async with tenant_session(tenant_id) as session:
            fact = await session.get(FactRow, incoming.id)
            assert fact is not None
            [link] = fact.people
            assert link.person_id == person.id

    async def test_somebody_with_no_account_here_is_still_credited(
        self, app: FastAPI, platform: AsyncSession
    ) -> None:
        """An outside contributor to a public repository has no account to
        notify and no relationship in which to try.

        Blocking their attribution would not discharge an obligation to them; it
        would only erase the credit they are owed for work they did in public.
        """
        from cairn_api.db.fact_models import Fact as FactRow
        from cairn_api.db.identity_models import Identity, IdentityKind
        from cairn_api.domain import Certainty
        from cairn_api.pipeline import store
        from cairn_api.pipeline.facts import Fact, FactKind, SourceRef

        owner = await owner_of_new_workspace(app)
        tenant_id = uuid.UUID(owner.workspace_id)

        outsider = Person(tenant_id=tenant_id, display_name="Sam Okafor")
        platform.add(outsider)
        await platform.flush()
        platform.add(
            Identity(
                tenant_id=tenant_id,
                person_id=outsider.id,
                kind=IdentityKind.GITHUB_LOGIN,
                value=f"sam-{uuid.uuid4().hex[:8]}",
            )
        )
        await platform.commit()

        incoming = Fact(
            kind=FactKind.DELIVERY,
            statement="Sam Okafor contributed a fix upstream.",
            sources=[SourceRef(source="github", evidence_id=f"ev-{uuid.uuid4().hex[:8]}")],
            certainty=Certainty.VERIFIED,
            people=["Sam Okafor"],
            occurred_at=datetime.now(UTC),
        )
        async with tenant_session(tenant_id) as session:
            await store.apply(session, tenant_id=tenant_id, incoming=[incoming])
            await store.attach_people_bulk(session, tenant_id=tenant_id, fact_ids=[incoming.id])
            await session.commit()

        async with tenant_session(tenant_id) as session:
            fact = await session.get(FactRow, incoming.id)
            assert fact is not None
            [link] = fact.people
            assert link.person_id == outsider.id


class TestTheRoutesExist:
    def test_they_are_registered_on_the_app(self) -> None:
        """A router written and never included is a screen nobody can reach."""
        from cairn_api.api.app import create_app
        from cairn_api.config import Settings

        app = create_app(Settings(environment="test", cors_allowed_origins=(TEST_ORIGIN,)))
        paths = set(app.openapi()["paths"])

        for surface in ("/privacy", "/notifications", "/trust", "/members/{user_id}"):
            assert any(path.endswith(surface) for path in paths), (
                f"no {surface} route on the app: {sorted(paths)}"
            )


class TestSessionsStillWork:
    async def test_the_cookie_is_what_carries_the_session(self, app: FastAPI) -> None:
        """A guard on the helpers above rather than on the product.

        Every test in this file depends on `owner_of_new_workspace` producing a
        signed-in client. If signup stopped setting the cookie, they would all
        fail with a confusing 401 rather than a clear one.
        """
        owner = await owner_of_new_workspace(app)
        assert SESSION_COOKIE_NAME in owner.client.cookies
