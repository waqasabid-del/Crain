"""Space selection: the only thing that permits CAIRN to read anything from Chat.

Connecting Google Chat grants nothing. These tests exist to keep that true,
because "connected therefore reading" is the natural assumption and every
shortcut in this area produces it.

What each group protects:

- **Only named spaces are offered.** Direct messages, group direct messages,
  one-to-one app conversations and unnamed spaces are excluded — twice, because
  Google's own filter is asked for as well and a picker that offered a direct
  message would not be noticed until somebody selected one.
- **Selection is by resource name.** A display name is refused at the helper,
  at the request model and at the database. Names change; a permission keyed on
  one is silently granted or revoked by a rename.
- **An unselected space is not permitted**, including in a workspace that has
  selected other spaces — the case a "connected implies allowed" bug passes.
- **A disconnected or revoked connection permits nothing**, even with its
  selection intact. The selection is deliberately kept so reconnecting restores
  it, which is exactly why the connection has to be checked too.
- **Saving drives the subscriptions.** Selecting creates a lease; deselecting
  deletes the selection row *before* Google is called, and blocks the space even
  when the remote delete fails.
- **No display name is stored or logged.**

No test here reaches Google: the doubles from `test_gchat_subscriptions` satisfy
the protocols structurally, and the space directory below does the same.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from cairn_api.connectors.credentials import SecretValue
from cairn_api.db.connector_models import ConnectionState
from cairn_api.db.gchat_models import (
    GoogleChatSpaceSelection,
    GoogleChatSubscription,
    GoogleChatSubscriptionState,
)
from cairn_api.gchat import spaces
from cairn_api.gchat.spaces import AvailableSpace, GoogleChatSelectionError
from cairn_api.gchat.subscriptions import SubscriptionError, SubscriptionFailure
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_gchat_subscriptions import (  # noqa: F401 — fixtures, re-exported by importing them
    DESIGN,
    ENGINEERING,
    FakeEvents,
    Workspace,
    _forget_tokens,
    a_client,
    gchat_tables,
    select_space,
    workspace,
)

pytestmark = [pytest.mark.integration]

#: A display name of the kind that must never reach a column or a log line. It
#: is the whole reason this connector stores resource names.
SENSITIVE = "Acme / Northwind diligence"

NAMED = AvailableSpace(
    name=ENGINEERING, display_name="Engineering", space_type="SPACE", single_user_bot_dm=False
)
ALSO_NAMED = AvailableSpace(
    name=DESIGN, display_name=SENSITIVE, space_type="SPACE", single_user_bot_dm=False
)

#: A one-to-one conversation between two people. Private correspondence, and
#: nothing anyone selected a product to read.
DIRECT_MESSAGE = AvailableSpace(
    name="spaces/AAAADM000001",
    display_name="",
    space_type="DIRECT_MESSAGE",
    single_user_bot_dm=False,
)

#: A group chat, which Google also reports outside ``SPACE``.
GROUP_CHAT = AvailableSpace(
    name="spaces/AAAAGROUP001", display_name="", space_type="GROUP_CHAT", single_user_bot_dm=False
)

#: The trap: Google reports ``spaceType: SPACE`` *and* ``singleUserBotDm``, so a
#: filter that trusted the type alone would offer somebody's private
#: conversation with an app.
APP_DM = AvailableSpace(
    name="spaces/AAAABOTDM001", display_name="CAIRN", space_type="SPACE", single_user_bot_dm=True
)

#: A named space with no name. In practice an ad-hoc conversation, and
#: undescribable to the person being asked to choose.
UNNAMED = AvailableSpace(
    name="spaces/AAAAUNNAMED1", display_name="", space_type="SPACE", single_user_bot_dm=False
)

EVERYTHING = (NAMED, DIRECT_MESSAGE, GROUP_CHAT, APP_DM, UNNAMED, ALSO_NAMED)


class FakeDirectory:
    """A `SpaceDirectory` that never opens a socket.

    Structural typing, so this class inherits nothing from the package it stands
    in for — the same split every other double in this suite uses.
    """

    def __init__(self, *, listing: tuple[AvailableSpace, ...] = EVERYTHING) -> None:
        self.listing = listing
        self.calls = 0

    async def list_spaces(self, *, access_token: SecretValue) -> tuple[AvailableSpace, ...]:
        self.calls += 1
        return self.listing


async def permitted(db: AsyncSession, scenario: Workspace, space_name: str) -> bool:
    """Ask the ingestion contract directly, past every response model."""
    return await spaces.is_space_permitted(db, tenant_id=scenario.tenant_id, space_name=space_name)


class TestOnlyNamedSpacesAreOffered:
    """What a customer is allowed to be shown, and therefore to select."""

    async def test_direct_messages_group_chats_and_app_dms_are_excluded(self) -> None:
        directory = FakeDirectory()

        offered = await spaces.eligible_spaces(directory, access_token=SecretValue("t"))

        assert [space.name for space in offered] == [NAMED.name, ALSO_NAMED.name]

    async def test_a_space_typed_as_a_named_space_but_flagged_as_an_app_dm_is_excluded(
        self,
    ) -> None:
        """The trap: the type alone is not enough.

        Google reports ``spaceType: SPACE`` for a one-to-one conversation with an
        app. A picker filtering on the type would offer it, and selecting it
        would put a person's private exchange with a bot into a company's record.
        """
        assert APP_DM.space_type == spaces.NAMED_SPACE_TYPE
        assert APP_DM.eligible is False

    async def test_an_unnamed_space_is_excluded(self) -> None:
        assert UNNAMED.eligible is False

    async def test_the_named_space_filter_is_still_asked_of_google(self) -> None:
        """Both filters, not one.

        The local check is the guarantee; the server-side filter is what stops a
        page of direct messages crossing the wire in the first place. Removing
        either should fail a test rather than be noticed by a customer.
        """
        assert spaces.NAMED_SPACE_FILTER == 'spaceType = "SPACE"'

    async def test_a_malformed_listing_yields_nothing_rather_than_raising(self) -> None:
        """A hostile or broken payload must not become a 500 in a picker."""
        assert spaces._spaces_from({"spaces": "not-a-list"}) == []
        assert spaces._spaces_from({"spaces": [{"noName": True}, 7]}) == []


class TestSelectionIsByResourceName:
    """Names change. Permissions keyed on them are granted and revoked by a rename."""

    async def test_a_display_name_is_refused(self) -> None:
        with pytest.raises(GoogleChatSelectionError):
            spaces.normalise_space_names([SENSITIVE])

    async def test_the_refusal_does_not_echo_the_display_name(self) -> None:
        """The message a customer sees must not repeat what they sent.

        A reflected space name lands in a response body and from there in
        whatever logs the response — which is the disclosure this whole design
        avoids by storing resource names.
        """
        with pytest.raises(GoogleChatSelectionError) as raised:
            spaces.normalise_space_names([SENSITIVE])
        assert SENSITIVE not in str(raised.value)

    async def test_a_bare_id_with_the_prefix_stripped_is_refused(self) -> None:
        """It would create a permission that matches no inbound event."""
        with pytest.raises(GoogleChatSelectionError):
            spaces.normalise_space_names(["AAAAENGINEER"])

    async def test_duplicates_collapse_and_order_is_preserved(self) -> None:
        assert spaces.normalise_space_names([DESIGN, ENGINEERING, DESIGN]) == (DESIGN, ENGINEERING)

    async def test_more_names_than_one_request_may_carry_are_refused(self) -> None:
        too_many = [f"spaces/A{index:012d}" for index in range(spaces.MAX_SELECTED_SPACES + 1)]
        with pytest.raises(GoogleChatSelectionError):
            spaces.normalise_space_names(too_many)


class TestNothingIsPermittedUntilSomethingIsSelected:
    """The rule the whole feature exists to enforce."""

    async def test_a_freshly_connected_workspace_permits_nothing(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        assert await permitted(platform, workspace, ENGINEERING) is False

    async def test_selecting_permits_exactly_that_space(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        """The positive control for every refusal in this file.

        Without it, "not permitted" would also be the answer from a check that is
        simply broken — indistinguishable from working correctly.
        """
        await select_space(platform, workspace, ENGINEERING)

        assert await permitted(platform, workspace, ENGINEERING) is True
        assert await permitted(platform, workspace, DESIGN) is False

    async def test_a_disconnected_connection_permits_nothing(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        """The selection survives a disconnect deliberately. It must not grant."""
        await select_space(platform, workspace, ENGINEERING)
        workspace.connection.state = ConnectionState.DISCONNECTED
        await platform.flush()

        assert await permitted(platform, workspace, ENGINEERING) is False

    async def test_a_revoked_connection_permits_nothing(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        """What `oauth.mark_refresh_failure` leaves behind when a grant is withdrawn."""
        await select_space(platform, workspace, ENGINEERING)
        workspace.connection.state = ConnectionState.REVOKED
        await platform.flush()

        assert await permitted(platform, workspace, ENGINEERING) is False

    async def test_a_display_name_never_matches_a_selection(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        await select_space(platform, workspace, ENGINEERING)

        assert await permitted(platform, workspace, SENSITIVE) is False

    async def test_another_workspace_id_does_not_reach_this_selection(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        await select_space(platform, workspace, ENGINEERING)

        assert (
            await spaces.is_space_permitted(
                platform, tenant_id=uuid.uuid4(), space_name=ENGINEERING
            )
            is False
        )


class TestSavingDrivesTheSubscriptions:
    """The vertical slice: a checkbox that does not create a lease delivers silence."""

    async def test_selecting_creates_a_lease_for_that_space(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        events = FakeEvents()

        saved = await spaces.save_selection(
            platform,
            a_client(events),
            connection=workspace.connection,
            user_id=workspace.user_id,
            space_names=[ENGINEERING],
        )

        assert saved == (ENGINEERING,)
        assert [space for space, _ in events.creates] == [ENGINEERING]
        row = await platform.scalar(
            select(GoogleChatSubscription).where(GoogleChatSubscription.space_name == ENGINEERING)
        )
        assert row is not None
        assert row.state is GoogleChatSubscriptionState.ACTIVE

    async def test_re_asserting_a_selection_does_not_create_a_second_lease(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        """A picker submits the whole set on every save.

        A create per assertion would accumulate leases nobody renews — each one
        delivering forever and invisible.
        """
        events = FakeEvents()
        client = a_client(events)
        for _ in range(3):
            await spaces.save_selection(
                platform,
                client,
                connection=workspace.connection,
                user_id=workspace.user_id,
                space_names=[ENGINEERING],
            )

        assert len(events.creates) == 1

    async def test_unselecting_tears_the_lease_down(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        events = FakeEvents()
        client = a_client(events)
        await spaces.save_selection(
            platform,
            client,
            connection=workspace.connection,
            user_id=workspace.user_id,
            space_names=[ENGINEERING, DESIGN],
        )

        await spaces.save_selection(
            platform,
            client,
            connection=workspace.connection,
            user_id=workspace.user_id,
            space_names=[DESIGN],
        )

        assert len(events.deletes) == 1
        assert await permitted(platform, workspace, ENGINEERING) is False
        assert await permitted(platform, workspace, DESIGN) is True

    async def test_unselecting_blocks_even_when_the_remote_delete_fails(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        """The failure this product cannot have.

        A withdrawn permission that keeps taking data because a third party was
        unreachable is not a smaller version of the promise — it is the opposite
        of it. The selection row is deleted and flushed before Google is called,
        so the block does not depend on the network at all.
        """
        events = FakeEvents()
        client = a_client(events)
        await spaces.save_selection(
            platform,
            client,
            connection=workspace.connection,
            user_id=workspace.user_id,
            space_names=[ENGINEERING],
        )
        events.delete_error = SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE)

        await spaces.save_selection(
            platform,
            client,
            connection=workspace.connection,
            user_id=workspace.user_id,
            space_names=[],
        )

        assert await permitted(platform, workspace, ENGINEERING) is False
        remaining = await platform.scalars(
            select(GoogleChatSpaceSelection.space_name).where(
                GoogleChatSpaceSelection.connection_id == workspace.connection.id
            )
        )
        assert remaining.all() == []

    async def test_one_failing_space_does_not_discard_the_others(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        """A throttled space must not roll back four working ones.

        The failed space keeps its row and its category, which is what the picker
        renders — a space that failed to subscribe with a reason on it is worth
        more than a space with no row at all.
        """
        events = FakeEvents(create_error=SubscriptionError(SubscriptionFailure.RATE_LIMITED))

        saved = await spaces.save_selection(
            platform,
            a_client(events),
            connection=workspace.connection,
            user_id=workspace.user_id,
            space_names=[ENGINEERING],
        )

        assert saved == (ENGINEERING,)
        assert await permitted(platform, workspace, ENGINEERING) is True
        row = await platform.scalar(
            select(GoogleChatSubscription).where(GoogleChatSubscription.space_name == ENGINEERING)
        )
        assert row is not None
        assert row.state is GoogleChatSubscriptionState.ERROR
        assert row.suspension_category is not None

    async def test_a_deployment_with_no_topic_still_records_the_decision(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
    ) -> None:
        """No client is not a reason to refuse somebody's choice.

        Nothing will arrive — there is nowhere for Google to publish — but the
        selection is the customer's decision, not the deployment's, and
        deselecting must keep working on such a deployment too.
        """
        saved = await spaces.save_selection(
            platform,
            None,
            connection=workspace.connection,
            user_id=workspace.user_id,
            space_names=[ENGINEERING],
        )

        assert saved == (ENGINEERING,)
        assert await permitted(platform, workspace, ENGINEERING) is True


class TestNoDisplayNameIsKept:
    """A space name is the most sensitive string this connector touches."""

    async def test_saving_logs_counts_and_never_a_name(
        self,
        platform: AsyncSession,
        workspace: Workspace,  # noqa: F811
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            await spaces.save_selection(
                platform,
                a_client(),
                connection=workspace.connection,
                user_id=workspace.user_id,
                space_names=[ENGINEERING],
            )

        written = "\n".join(
            record.getMessage() for record in caplog.records if record.name.startswith("cairn_api")
        )
        assert SENSITIVE not in written
        assert ENGINEERING not in written

    async def test_the_selection_row_has_nowhere_to_put_a_display_name(self) -> None:
        """Asserted against the model rather than trusted.

        A column added "just for the picker" is a column a log line, an error
        body and a staff screen eventually read.
        """
        assert "display_name" not in GoogleChatSpaceSelection.__table__.columns
