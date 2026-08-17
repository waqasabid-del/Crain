"""Channel selection: the only thing that permits CAIRN to read anything.

Connecting Slack grants nothing. These tests exist to keep that true, because
"connected therefore reading" is the natural assumption and every shortcut in
this area produces it.

What each group protects:

- **Selection is by ID.** A display name is refused at the request model, at the
  helper and at the database. Names change; a permission keyed on one is silently
  granted or revoked by a rename.
- **An unselected channel is not permitted.** Including in a workspace that has
  selected other channels, which is the case a "connected implies allowed" bug
  passes.
- **A disconnected workspace permits nothing**, even with its selection intact —
  the selection is deliberately kept so reconnecting restores it, which is
  exactly why the connection has to be checked too.
- **Isolation.** One workspace's selection never reaches another's, asserted
  against a second real workspace with real rows in it.
- **Member and Viewer cannot change what is read**, and cannot see the picker.
- **No channel name is stored, logged or echoed** outside the picker itself.

No test here reaches slack.com; the double from `test_slack_oauth` serves every
route.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from cairn_api.db.slack_models import SlackChannelSelection
from cairn_api.db.tenancy import tenant_session
from cairn_api.slack import channels as channel_selection
from cairn_api.slack.channels import SlackSelectionError
from cairn_api.slack.oauth import SlackChannel
from fastapi import FastAPI
from sqlalchemy import func, select
from test_api_workspaces import Actor, join_as, new_actor
from test_slack_oauth import (
    FakeSlack,
    a_grant,
    cairn_log,
    connection_for,
    finish_install,
    slack_app,  # noqa: F401 — a fixture, re-exported by importing it
    start_install,
    use,
)

pytestmark = [pytest.mark.integration]

GENERAL = SlackChannel(id="C0GENERAL1", name="general", bot_is_member=True)
ENGINEERING = SlackChannel(id="C0ENGINEER", name="engineering", bot_is_member=True)

#: A channel the app has *not* been invited to. The picker has to say so:
#: selecting it produces a permission that delivers nothing, forever, silently.
UNINVITED = SlackChannel(id="C0NOTINVIT", name="private-ish", bot_is_member=False)

ALL_CHANNELS = (GENERAL, ENGINEERING, UNINVITED)


async def connected(app: FastAPI, *, label: str, team_id: str) -> tuple[Actor, FakeSlack]:
    """An Owner with Slack connected and a channel list ready to serve."""
    channel_selection.clear_channel_cache()
    owner = await new_actor(app, role_label=label)
    api = use(app, FakeSlack(grant=a_grant(team_id=team_id), channels=ALL_CHANNELS))
    await finish_install(owner, state=await start_install(owner))
    # The install's own exchange, not a listing. Reset so the caching assertions
    # below count only what they cause.
    api.exchanges = 0
    return owner, api


def base(actor: Actor) -> str:
    return f"/v1/workspaces/{actor.workspace_id}/integrations/slack"


async def permitted(workspace_id: str, channel_id: str) -> bool:
    """Ask the ingestion contract directly, through a tenant-scoped session.

    Through the scoped session rather than the platform one, because that is how
    a worker will call it — so row-level security is exercised on the same path
    production uses rather than only on the one a test found convenient.
    """
    async with tenant_session(uuid.UUID(workspace_id)) as db:
        return await channel_selection.is_channel_permitted(
            db, tenant_id=uuid.UUID(workspace_id), channel_id=channel_id
        )


class TestNothingIsPermittedUntilSomethingIsSelected:
    """The rule the whole feature exists to enforce."""

    async def test_a_freshly_connected_workspace_permits_nothing(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        owner, _ = await connected(slack_app, label="fresh", team_id="T0FRESH001")

        for channel in ALL_CHANNELS:
            assert await permitted(owner.workspace_id, channel.id) is False

    async def test_selecting_permits_exactly_that_channel(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """The positive control for every refusal in this file.

        Without it, "not permitted" would also be the answer from a check that is
        simply broken — which is indistinguishable from working correctly.
        """
        owner, _ = await connected(slack_app, label="one-only", team_id="T0ONEONLY1")

        response = await owner.client.put(
            f"{base(owner)}/channels", json={"channelIds": [GENERAL.id]}
        )
        assert response.status_code == 200, response.text

        assert await permitted(owner.workspace_id, GENERAL.id) is True
        assert await permitted(owner.workspace_id, ENGINEERING.id) is False

    async def test_deselecting_withdraws_the_permission(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """A replace, not a merge.

        If the endpoint merged, unchecking a box would do nothing — and the box
        being unchecked is somebody withdrawing permission to read a
        conversation, which is the one operation here that must not silently
        fail.
        """
        owner, _ = await connected(slack_app, label="deselect", team_id="T0DESEL001")
        await owner.client.put(
            f"{base(owner)}/channels", json={"channelIds": [GENERAL.id, ENGINEERING.id]}
        )
        assert await permitted(owner.workspace_id, ENGINEERING.id) is True

        await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [GENERAL.id]})

        assert await permitted(owner.workspace_id, ENGINEERING.id) is False
        assert await permitted(owner.workspace_id, GENERAL.id) is True

    async def test_an_empty_selection_is_valid_and_permits_nothing(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """ "Read nothing" has to be expressible, and it has to be one request."""
        owner, _ = await connected(slack_app, label="empty", team_id="T0EMPTY001")
        await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [GENERAL.id]})

        response = await owner.client.put(f"{base(owner)}/channels", json={"channelIds": []})

        assert response.status_code == 200
        assert response.json()["channelIds"] == []
        assert await permitted(owner.workspace_id, GENERAL.id) is False

    async def test_a_disconnected_workspace_permits_nothing_despite_its_selection(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """The reason `is_channel_permitted` checks the connection as well.

        The selection is deliberately retained on disconnect, so reconnecting
        restores it rather than making somebody rebuild it. That retention is
        exactly what would keep permitting reads if the check looked only at the
        selection rows.
        """
        owner, _ = await connected(slack_app, label="disc-perm", team_id="T0DISCPRM1")
        await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [GENERAL.id]})
        assert await permitted(owner.workspace_id, GENERAL.id) is True

        await owner.client.post(f"{base(owner)}/disconnect")

        assert await permitted(owner.workspace_id, GENERAL.id) is False
        # And the row survived, which is what makes the assertion above load-bearing.
        connection = await connection_for(owner.workspace_id)
        assert connection is not None
        async with tenant_session(uuid.UUID(owner.workspace_id)) as db:
            kept = await channel_selection.selected_channel_ids(db, connection_id=connection.id)
        assert kept == frozenset({GENERAL.id})


class TestSelectionIsByIdNotByName:
    @pytest.mark.parametrize(
        "value",
        [
            # What an interface sends when it passes the label through.
            "#general",
            "general",
            # A private-channel id. Not a public channel, and this connector does
            # not read private ones at all.
            "G0PRIVATE1",
            # A user id, which is what a DM "channel" looks like.
            "D0DIRECT01",
            "",
            "C",
        ],
    )
    async def test_anything_that_is_not_a_public_channel_id_is_refused(
        self,
        slack_app: FastAPI,  # noqa: F811
        value: str,
    ) -> None:
        # A fresh team id per case. Deriving one from the parameter looked
        # tidier and collided — and a collision here fails as
        # "already connected to another workspace", which reads like a defect in
        # the code under test rather than in the fixture.
        suffix = uuid.uuid4().hex[:8].upper()
        owner, _ = await connected(slack_app, label=f"byid-{suffix}", team_id=f"T0{suffix}")

        response = await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [value]})

        assert response.status_code == 422, response.text
        assert await permitted(owner.workspace_id, value) is False

    async def test_the_refusal_does_not_echo_what_was_sent(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """A channel name in an error body is a disclosure on its own.

        `#acme-layoffs-legal` reflected into a response reaches every log, error
        tracker and browser console that response passes through.
        """
        owner, _ = await connected(slack_app, label="no-echo-ch", team_id="T0NOECHO01")

        response = await owner.client.put(
            f"{base(owner)}/channels", json={"channelIds": ["#acme-layoffs-legal"]}
        )

        assert response.status_code == 422
        assert "acme-layoffs-legal" not in response.text

    def test_the_helper_refuses_a_name_without_a_database(self) -> None:
        """Asserted at the helper too, so a second caller cannot bypass the
        route's validation by calling the service layer directly."""
        with pytest.raises(SlackSelectionError):
            channel_selection.normalise_channel_ids(["#general"])

    def test_a_duplicate_selection_is_collapsed_in_order(self) -> None:
        """The response echoes the selection back, so the order has to be the
        one that was sent rather than a set's arbitrary one."""
        assert channel_selection.normalise_channel_ids(
            [ENGINEERING.id, GENERAL.id, ENGINEERING.id]
        ) == (ENGINEERING.id, GENERAL.id)

    async def test_the_database_refuses_a_name_even_past_the_application(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """The CHECK constraint, exercised directly.

        Validation in Python protects the endpoint. This protects the table from
        a script, a fixture, or a future writer that never sees the endpoint.
        """
        from sqlalchemy.exc import DBAPIError

        owner, _ = await connected(slack_app, label="ck-name", team_id="T0CKNAME01")
        connection = await connection_for(owner.workspace_id)
        assert connection is not None

        async with tenant_session(uuid.UUID(owner.workspace_id)) as db:
            db.add(
                SlackChannelSelection(
                    tenant_id=uuid.UUID(owner.workspace_id),
                    connection_id=connection.id,
                    channel_id="#general",
                    selected_by_user_id=connection.authorised_by_user_id,
                )
            )
            with pytest.raises(DBAPIError):
                await db.flush()
            await db.rollback()


class TestWhoMayChooseWhatIsRead:
    async def test_a_member_cannot_see_the_picker(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """This is the one endpoint in the API that returns Slack channel names.

        Gated on the permission to *change* what is read rather than on plain
        membership: a Member gains nothing from a list they cannot act on, and a
        channel list is a map of how a company is organised.
        """
        owner, _ = await connected(slack_app, label="picker-owner", team_id="T0PICKER01")
        member = await join_as(slack_app, owner, "member")

        assert (await owner.client.get(f"{base(owner)}/channels")).status_code == 200

        assert (await member.client.get(f"{base(member)}/channels")).status_code == 403

    async def test_a_viewer_cannot_change_the_selection(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        owner, _ = await connected(slack_app, label="sel-viewer", team_id="T0SELVIEW1")
        viewer = await join_as(slack_app, owner, "viewer")

        response = await viewer.client.put(
            f"{base(viewer)}/channels", json={"channelIds": [GENERAL.id]}
        )

        assert response.status_code == 403
        assert await permitted(owner.workspace_id, GENERAL.id) is False

    async def test_an_admin_may(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """The positive half. Without it the two refusals above would also pass
        against an endpoint nobody can call."""
        owner, _ = await connected(slack_app, label="sel-admin", team_id="T0SELADMN1")
        admin = await join_as(slack_app, owner, "admin")

        response = await admin.client.put(
            f"{base(admin)}/channels", json={"channelIds": [GENERAL.id]}
        )

        assert response.status_code == 200
        assert await permitted(owner.workspace_id, GENERAL.id) is True


class TestIsolation:
    async def test_one_workspaces_selection_never_reaches_another(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """Two real workspaces, both with selections, both with rows.

        Asserting an empty result would prove nothing — a broken query returns
        empty too — so each side's own selection is confirmed first.
        """
        alice, _ = await connected(slack_app, label="iso-alice", team_id="T0ISOALICE")
        await alice.client.put(f"{base(alice)}/channels", json={"channelIds": [GENERAL.id]})

        mallory, _ = await connected(slack_app, label="iso-mallory", team_id="T0ISOMALLY")
        await mallory.client.put(f"{base(mallory)}/channels", json={"channelIds": [ENGINEERING.id]})

        assert await permitted(alice.workspace_id, GENERAL.id) is True
        assert await permitted(mallory.workspace_id, ENGINEERING.id) is True

        # The same channel id in the other workspace. Ids are unique per Slack
        # workspace, not globally, so a collision is not hypothetical — and a
        # check that forgot its tenant filter would answer True here.
        assert await permitted(mallory.workspace_id, GENERAL.id) is False
        assert await permitted(alice.workspace_id, ENGINEERING.id) is False

    async def test_a_stranger_cannot_read_or_write_another_workspaces_channels(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """404, not 403 — a 403 would confirm the workspace exists."""
        alice, _ = await connected(slack_app, label="str-alice", team_id="T0STRALICE")
        mallory = await new_actor(slack_app, role_label="str-mallory")

        assert (await mallory.client.get(f"{base(alice)}/channels")).status_code == 404
        assert (
            await mallory.client.put(f"{base(alice)}/channels", json={"channelIds": [GENERAL.id]})
        ).status_code == 404

    async def test_a_scoped_session_sees_only_its_own_selection_rows(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """Row-level security underneath the application's own filters.

        The safety net, not the primary control — but the one that still holds
        when a future query forgets its `tenant_id` predicate.
        """
        alice, _ = await connected(slack_app, label="rls-alice", team_id="T0RLSALICE")
        await alice.client.put(f"{base(alice)}/channels", json={"channelIds": [GENERAL.id]})
        mallory, _ = await connected(slack_app, label="rls-mallory", team_id="T0RLSMALLY")
        await mallory.client.put(f"{base(mallory)}/channels", json={"channelIds": [GENERAL.id]})

        async with tenant_session(uuid.UUID(alice.workspace_id)) as db:
            # No tenant predicate at all. Everything filtering this is the policy.
            visible = await db.scalar(select(func.count()).select_from(SlackChannelSelection))

        assert visible == 1


class TestThePickerAndItsCopy:
    async def test_it_reports_whether_the_bot_has_been_invited(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """`channels:history` is not enough on its own.

        The bot receives events only from channels it has been added to, and
        CAIRN does not request `channels:join` — so a channel with
        `botIsMember: false` will deliver nothing until a human runs `/invite`.
        A picker that hides this ships an integration that silently does nothing.
        """
        owner, _ = await connected(slack_app, label="invited", team_id="T0INVITE01")

        body = (await owner.client.get(f"{base(owner)}/channels")).json()

        by_id = {item["id"]: item for item in body["channels"]}
        assert by_id[GENERAL.id]["botIsMember"] is True
        assert by_id[UNINVITED.id]["botIsMember"] is False

    async def test_the_invite_requirement_is_stated_on_every_surface(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """Served from the API rather than written into an interface, so a second
        client cannot ship without it."""
        owner, _ = await connected(slack_app, label="notice", team_id="T0NOTICE01")

        listing = (await owner.client.get(f"{base(owner)}/channels")).json()
        saved = (
            await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [GENERAL.id]})
        ).json()

        for notice in (listing["notice"], saved["notice"]):
            assert "/invite" in notice
        assert listing["notice"] == channel_selection.BOT_INVITE_NOTICE

    async def test_the_picker_marks_what_is_already_selected(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        owner, _ = await connected(slack_app, label="marks", team_id="T0MARKED01")
        await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [ENGINEERING.id]})

        body = (await owner.client.get(f"{base(owner)}/channels")).json()

        selected = {item["id"] for item in body["channels"] if item["selected"]}
        assert selected == {ENGINEERING.id}

    async def test_the_list_is_cached_so_a_reload_does_not_spend_the_rate_limit(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """`conversations.list` is rate-limited, and the picker is exactly the
        screen somebody reloads while deciding."""
        owner, api = await connected(slack_app, label="cached", team_id="T0CACHED01")

        await owner.client.get(f"{base(owner)}/channels")
        await owner.client.get(f"{base(owner)}/channels")

        assert api.listings == 1

    async def test_the_picker_is_unavailable_when_slack_cannot_be_reached(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        """502 with a bounded category, rather than an empty list.

        An empty picker reads as "this workspace has no channels", which is a
        wrong answer presented as a right one.
        """
        from cairn_api.db.connector_models import ConnectorErrorCategory
        from cairn_api.slack.oauth import SlackInstallError, SlackInstallFailure

        owner, api = await connected(slack_app, label="unreach", team_id="T0UNREACH1")
        channel_selection.clear_channel_cache()
        api.error = SlackInstallError(
            SlackInstallFailure.PROVIDER_UNAVAILABLE, "Slack could not be reached."
        )

        response = await owner.client.get(f"{base(owner)}/channels")

        assert response.status_code == 502
        assert response.json()["category"] == ConnectorErrorCategory.PROVIDER_UNAVAILABLE.value


class TestNoChannelNameIsKept:
    def test_the_table_has_no_column_that_could_hold_a_name(self) -> None:
        """Asserted over the mapped columns rather than by reading the file.

        A name column arrives as a convenience — "so the settings screen renders
        without calling Slack" — and it is the field that puts
        `#acme-layoffs-legal` into every database backup and staff query.
        """
        columns = {column.name for column in SlackChannelSelection.__table__.columns}

        assert columns == {
            "id",
            "tenant_id",
            "connection_id",
            "channel_id",
            "selected_by_user_id",
            "created_at",
            "updated_at",
        }

    async def test_saving_a_selection_logs_counts_and_never_ids_or_names(
        self,
        slack_app: FastAPI,  # noqa: F811
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A channel id identifies a conversation inside a customer's workspace.

        Logs are read by people who were never granted a support session
        (md/15 §5.2), so neither the id nor the name belongs in one — only how
        many. Captured from the standard-library handler rather than with
        `structlog.testing.capture_logs`, which sees nothing once
        `cache_logger_on_first_use` has bound a logger in an earlier test.
        """
        owner, _ = await connected(slack_app, label="log-sel", team_id="T0LOGSEL01")

        with caplog.at_level(logging.DEBUG):
            await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [GENERAL.id]})

        # The positive half first, so the two refusals below cannot pass against
        # a flow that logged nothing at all.
        written = cairn_log(caplog)
        assert "slack.channel_selection_saved" in written
        assert GENERAL.id not in written
        assert GENERAL.name not in written

    async def test_the_selection_response_answers_in_ids_alone(
        self,
        slack_app: FastAPI,  # noqa: F811
    ) -> None:
        owner, _ = await connected(slack_app, label="ids-only", team_id="T0IDSONLY1")

        body = (
            await owner.client.put(f"{base(owner)}/channels", json={"channelIds": [GENERAL.id]})
        ).json()

        assert body["channelIds"] == [GENERAL.id]
        assert GENERAL.name not in str(body)
