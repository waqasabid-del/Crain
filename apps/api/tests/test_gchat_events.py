"""What a Chat payload means once it has verified — decided as pure functions.

Every rule below is a function of a payload and a CloudEvent type: no HTTP, no
database, no clock. That is the point of the split from `pubsub.py`, and it is
what lets the awkward cases be stated directly rather than smuggled through a
request.

The three that cost other people production incidents:

* **created, updated and deleted are the same body.** Only `ce-type` tells them
  apart, so every test here passes the type in explicitly and several of them
  pass a *create* body with a *delete* type to prove nothing reads a type out of
  the payload.
* **the documented delete example still carries `text` and `sender`.** Requiring
  either would drop every retirement; trusting either would resurrect the claim
  the deletion retracted. Both are asserted.
* **identity survives the edit.** The create, the edit and the delete of one
  message normalise onto one `ActivityEvent.id`, which is what makes an edit an
  update instead of a second statement.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.gchat.events import (
    GCHAT_EVENT_JOB,
    ChatEvent,
    ChatMessage,
    DroppedMessage,
    DropReason,
    GoogleChatDeliveryNotFoundError,
    MessageAction,
    current_statements,
    handle_gchat_event,
    normalise,
    read_event,
    read_message,
    read_stored,
    register,
    stored_payload,
)
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.runner import JobRegistry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SPACE = "spaces/AAAASELECTED"
MESSAGE = f"{SPACE}/messages/MESSAGE1"
SENDER = "users/107700770077007700770"
TENANT = uuid.uuid4()

CREATED = "google.workspace.chat.message.v1.created"
UPDATED = "google.workspace.chat.message.v1.updated"
DELETED = "google.workspace.chat.message.v1.deleted"

TEXT = "Priya is deferring the payments migration until the audit clears."


def payload(
    *,
    name: str = MESSAGE,
    text: str | None = TEXT,
    sender: str | None = SENDER,
    sender_type: str | None = "HUMAN",
    space: str | None = SPACE,
    create_time: str | None = "2026-08-17T09:30:00Z",
) -> bytes:
    """Chat's `includeResource: true` body, as documented."""
    message: dict[str, Any] = {"name": name}
    if create_time is not None:
        message["createTime"] = create_time
    if space is not None:
        message["space"] = {"name": space}
    if sender is not None:
        message["sender"] = {"name": sender, **({"type": sender_type} if sender_type else {})}
    if text is not None:
        message["text"] = text
    return json.dumps({"message": message}).encode("utf-8")


def parsed(event_type: str = CREATED, **kwargs: Any) -> ChatMessage:
    """Decode and interpret, asserting it was not dropped."""
    event = read_event(payload(**kwargs), event_type=event_type)
    assert event is not None
    message = read_message(event)
    assert isinstance(message, ChatMessage), message
    return message


def dropped(event_type: str = CREATED, **kwargs: Any) -> DropReason:
    event = read_event(payload(**kwargs), event_type=event_type)
    assert event is not None
    message = read_message(event)
    assert isinstance(message, DroppedMessage), message
    return message.reason


# --------------------------------------------------------------------------
# Only `ce-type` says what happened
# --------------------------------------------------------------------------


class TestTheEventTypeIsTheCloudEventType:
    @pytest.mark.parametrize(
        ("ce_type", "action"),
        [
            (CREATED, MessageAction.CREATED),
            (UPDATED, MessageAction.UPDATED),
            (DELETED, MessageAction.DELETED),
        ],
    )
    def test_the_three_supported_types_map_to_the_three_actions(
        self, ce_type: str, action: MessageAction
    ) -> None:
        # The bodies are byte-identical across all three: only the type differs.
        assert parsed(ce_type).action is action

    @pytest.mark.parametrize(
        "ce_type",
        [
            "google.workspace.chat.reaction.v1.created",
            "google.workspace.chat.membership.v1.created",
            "google.workspace.chat.space.v1.updated",
            "google.workspace.chat.message.v2.created",
            "message.created",
            "",
            None,
        ],
    )
    def test_everything_else_is_not_ingested(self, ce_type: str | None) -> None:
        """An exhaustive list, not a prefix match.

        Reactions, memberships and space updates share the
        `google.workspace.chat.` namespace, so a prefix test would quietly start
        ingesting whatever Google adds to it next.
        """
        assert read_event(payload(), event_type=ce_type) is None

    def test_a_type_claimed_in_the_body_is_ignored(self) -> None:
        """The body has no say.

        A payload naming itself `deleted` while the CloudEvent attribute says
        `created` is a create — otherwise a crafted body could retire a
        statement nobody deleted.
        """
        body = json.loads(payload())
        body["type"] = DELETED
        body["message"]["type"] = DELETED
        event = read_event(json.dumps(body).encode("utf-8"), event_type=CREATED)

        assert event is not None
        assert event.action is MessageAction.CREATED

    @pytest.mark.parametrize("body", [b"not json", b"[]", b'{"message":"a string"}', b"", b"{}"])
    def test_a_body_that_is_not_a_chat_resource_is_not_ingested(self, body: bytes) -> None:
        # `None` rather than an exception: this runs after the token verified,
        # so a body that does not parse is a Google change or a bug, and
        # Pub/Sub redelivering it would decode it the same way.
        assert read_event(body, event_type=CREATED) is None


# --------------------------------------------------------------------------
# Interpretation
# --------------------------------------------------------------------------


class TestReadingAMessage:
    def test_a_created_message_is_read_whole(self) -> None:
        message = parsed()

        assert message.space_name == SPACE
        assert message.message_name == MESSAGE
        assert message.sender_id == SENDER
        assert message.text == TEXT
        assert message.create_time == "2026-08-17T09:30:00Z"

    def test_the_space_is_derived_from_the_message_name(self) -> None:
        """Not read from `message.space.name`.

        The two are separate copies of one fact, and the derived one cannot
        disagree with the resource that is actually stored.
        """
        assert parsed(space=None).space_name == SPACE

    def test_a_payload_that_disagrees_with_itself_about_its_space_is_dropped(self) -> None:
        # Refused rather than reconciled: whichever copy lost would be the one
        # some later reader used — including the tenant lookup.
        assert dropped(space="spaces/AAAAOTHER99") is DropReason.MALFORMED

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "MESSAGE1",
            "spaces//messages/M",
            "spaces/A/messages/",
            "rooms/A/messages/M",
            "spaces/A/threads/T",
            "spaces/A/messages/M/threads/T",
            "spaces/A",
            "spaces",
        ],
    )
    def test_a_message_with_no_usable_identity_is_dropped(self, name: str) -> None:
        # A bare message id is unique only within its space, so anything short
        # of the resource name would collide across spaces.
        assert dropped(name=name, space=None) is DropReason.MALFORMED

    @pytest.mark.parametrize("sender_type", ["BOT", "TYPE_UNSPECIFIED", "", None])
    def test_an_app_post_is_dropped_before_the_author_is_read(
        self, sender_type: str | None
    ) -> None:
        """Including CAIRN's own output, which is how the loop stays closed."""
        assert dropped(sender_type=sender_type) is DropReason.AUTOMATED_AUTHOR

    def test_a_message_with_no_sender_block_at_all_is_dropped(self) -> None:
        # Code that reads the author first raises here rather than dropping.
        assert dropped(sender=None) is DropReason.AUTOMATED_AUTHOR

    def test_an_edit_of_an_app_post_is_dropped_too(self) -> None:
        assert dropped(UPDATED, sender_type="BOT") is DropReason.AUTOMATED_AUTHOR

    def test_a_message_with_no_text_is_still_a_message(self) -> None:
        # A card, an attachment, or a post whose text is genuinely empty. It has
        # an author and an identity, so it is a statement with nothing said.
        assert parsed(text=None).text is None


class TestDeletes:
    def test_a_delete_is_read_even_though_its_payload_is_boilerplate(self) -> None:
        """Google's documented delete example still shows `text` and `sender`.

        Requiring either would drop every retirement; both are ignored instead.
        """
        message = parsed(DELETED)

        assert message.action is MessageAction.DELETED
        assert message.message_name == MESSAGE
        assert message.text is None
        assert message.sender_id is None

    def test_a_delete_with_no_text_or_sender_is_read_the_same_way(self) -> None:
        message = parsed(DELETED, text=None, sender=None)

        assert message.action is MessageAction.DELETED
        assert message.message_name == MESSAGE

    def test_a_delete_is_never_dropped_for_naming_a_bot(self) -> None:
        """The sender block on a delete is boilerplate about a message that no
        longer exists. Declining to retire a statement on the strength of it
        would leave a retracted claim standing as current."""
        message = parsed(DELETED, sender_type="BOT")

        assert message.action is MessageAction.DELETED


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


class TestNormalisation:
    def test_the_three_actions_share_one_identity(self) -> None:
        """The whole reason this module is arranged around the resource name.

        `event_key` is `(source, id)`, so identical ids collapse the create, the
        edit and the delete onto one record rather than accumulating three.
        """
        events = [
            normalise(parsed(ce_type), tenant_id=TENANT) for ce_type in (CREATED, UPDATED, DELETED)
        ]

        assert {event.id for event in events} == {MESSAGE}
        assert {event.source for event in events} == {f"/google_chat/{SPACE}"}
        assert [event.type for event in events] == [
            "ai.cairn.google_chat.message.created.v1",
            "ai.cairn.google_chat.message.updated.v1",
            "ai.cairn.google_chat.message.deleted.v1",
        ]

    def test_the_activity_carries_provenance_a_reader_can_open(self) -> None:
        # Provenance is the product's central promise: a claim nobody can check
        # is worse than no claim.
        event = normalise(parsed(), tenant_id=TENANT)

        assert event.data.provenance.source_url is not None
        assert str(event.data.provenance.source_url).startswith(
            "https://chat.google.com/room/AAAASELECTED/MESSAGE1"
        )
        assert event.data.actor.raw_identity == SENDER
        assert event.data.actor.is_bot is False
        assert event.data.content.text == TEXT

    def test_the_time_is_when_the_message_was_written(self) -> None:
        # Not when CAIRN received it. Conflating the two produces a brief
        # claiming today's work that actually happened in March.
        event = normalise(parsed(), tenant_id=TENANT)

        assert event.time.isoformat() == "2026-08-17T09:30:00+00:00"
        assert event.time.tzinfo is not None

    def test_a_delete_is_dated_by_the_statement_it_retires(self) -> None:
        # Dating it "now" would reorder a space's history every time somebody
        # tidied up an old thread.
        event = normalise(parsed(DELETED), tenant_id=TENANT)

        assert event.time.isoformat() == "2026-08-17T09:30:00+00:00"

    def test_a_message_with_no_text_still_normalises(self) -> None:
        # `Activity.summary` requires at least one character, and a delete or a
        # card legitimately has none. A validation error there would fail the
        # delivery rather than record it.
        assert normalise(parsed(text=None), tenant_id=TENANT).data.activity.summary
        assert normalise(parsed(DELETED), tenant_id=TENANT).data.activity.summary

    def test_a_malformed_timestamp_does_not_lose_the_message(self) -> None:
        event = normalise(parsed(create_time="the day before yesterday"), tenant_id=TENANT)

        assert event.time.tzinfo is not None

    def test_every_message_carries_something_a_reader_can_open(self) -> None:
        """`Provenance` refuses an `observed` claim with nothing to open.

        So "the link is optional" is not an available design: a resource name a
        permalink cannot be built from has to be rejected at interpretation, not
        carried to normalisation and failed there.
        """
        for ce_type in (CREATED, UPDATED, DELETED):
            event = normalise(parsed(ce_type), tenant_id=TENANT)
            assert event.data.provenance.source_url is not None

    def test_the_summary_is_bounded(self) -> None:
        # `Activity.summary` is a `String(2000)` downstream, and a longer one
        # fails validation for every long message rather than for none.
        event = normalise(parsed(text="x" * 9000), tenant_id=TENANT)

        assert len(event.data.activity.summary) <= 2000


class TestRetirement:
    def test_an_edit_replaces_and_a_delete_removes(self) -> None:
        """Requirement 6, as an executable statement.

        An edit replaces the statement under the same key rather than adding a
        second one, and a delete removes it rather than leaving a retracted
        sentence presented as current.
        """
        created = normalise(parsed(CREATED), tenant_id=TENANT)
        edited = normalise(parsed(UPDATED, text="Actually it ships Monday."), tenant_id=TENANT)
        deleted = normalise(parsed(DELETED), tenant_id=TENANT)

        assert current_statements([created]) == {MESSAGE: created}
        assert current_statements([created, edited]) == {MESSAGE: edited}
        assert current_statements([created, edited, deleted]) == {}

    def test_a_delete_of_one_message_leaves_the_others_standing(self) -> None:
        # The positive control: a fold that emptied everything would pass the
        # test above.
        other = f"{SPACE}/messages/MESSAGE2"
        kept = normalise(parsed(CREATED, name=other), tenant_id=TENANT)
        deleted = normalise(parsed(DELETED), tenant_id=TENANT)

        assert current_statements([kept, deleted]) == {other: kept}


# --------------------------------------------------------------------------
# The stored payload, and the worker
# --------------------------------------------------------------------------


class TestTheStoredPayload:
    def test_it_round_trips_through_storage(self) -> None:
        """The CloudEvent type is stored *with* the resource.

        Without it a stored delete is indistinguishable from a stored create,
        and the worker and the pipeline both re-read this row.
        """
        event = read_event(payload(), event_type=DELETED)
        assert event is not None

        stored = stored_payload(event)
        # It has to survive a JSON column round trip, not just a dict copy.
        recovered = read_stored(json.loads(json.dumps(stored)))

        assert isinstance(recovered, ChatEvent)
        assert recovered.action is MessageAction.DELETED
        assert recovered.event_type == DELETED
        message = read_message(recovered)
        assert isinstance(message, ChatMessage)
        assert message.message_name == MESSAGE

    @pytest.mark.parametrize(
        "stored",
        [
            {},
            {"type": "event_callback", "event": {}},
            {"type": "google_chat_event", "event_type": CREATED},
            {"type": "google_chat_event", "event_type": "reaction", "message": {"name": MESSAGE}},
        ],
        ids=["empty", "a-slack-payload", "no-message", "an-unsupported-type"],
    )
    def test_anything_else_is_not_a_chat_delivery(self, stored: dict[str, Any]) -> None:
        assert read_stored(stored) is None


class TestRegistration:
    def test_the_handler_registers_under_the_job_the_endpoint_publishes(self) -> None:
        """Explicit, never by import side effect.

        `pipeline/jobs.py`'s own history is the argument: an import-time
        registry looked populated in tests and was empty in the worker.
        """
        target = JobRegistry()
        register(target)

        assert target.resolve(GCHAT_EVENT_JOB) is handle_gchat_event


# --------------------------------------------------------------------------
# The worker side
# --------------------------------------------------------------------------


@pytest.mark.integration
class TestTheWorkerSide:
    """The handler, against real rows under real row-level security.

    Everything above is pure; this is the part that has to hold when the
    delivery comes back from the queue a second time, or with somebody else's
    tenant on it.
    """

    async def _tenant(self, platform: AsyncSession) -> Tenant:
        suffix = uuid.uuid4().hex[:10]
        tenant = Tenant(name=f"Acme {suffix}", slug=f"gchat-worker-{suffix}")
        platform.add(tenant)
        await platform.commit()
        return tenant

    async def _delivery(
        self, platform: AsyncSession, tenant: Tenant, *, event_type: str = CREATED
    ) -> str:
        """Record a delivery the way the push route does — platform-side.

        The application role has SELECT and UPDATE on `webhook_deliveries` and
        deliberately **no INSERT**: a tenant-scoped session that could create a
        delivery could forge activity for its own workspace.
        """
        event = read_event(payload(), event_type=event_type)
        assert event is not None
        delivery_id = f"sha256:{uuid.uuid4().hex}"
        platform.add(
            WebhookDelivery(
                tenant_id=tenant.id,
                delivery_id=delivery_id,
                event_type=event_type[:64],
                payload=stored_payload(event),
            )
        )
        await platform.commit()
        return delivery_id

    async def test_processing_marks_the_delivery_done_and_is_repeatable(
        self, platform: AsyncSession
    ) -> None:
        # At-least-once delivery guarantees a second run happens eventually;
        # treating it as an error would fill the dead-letter queue with
        # successful work.
        tenant = await self._tenant(platform)
        delivery_id = await self._delivery(platform, tenant)
        job = JobEnvelope(
            job_type=GCHAT_EVENT_JOB, tenant_id=tenant.id, payload={"delivery_id": delivery_id}
        )

        for _ in range(2):
            async with tenant_session(tenant.id) as session:
                await handle_gchat_event(session, job)
                await session.commit()

        row = await platform.scalar(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        assert row is not None
        await platform.refresh(row)
        assert row.status is DeliveryStatus.PROCESSED
        assert row.processed_at is not None

    async def test_a_handler_cannot_reach_another_workspaces_delivery(
        self, platform: AsyncSession
    ) -> None:
        """Row-level security, asserted where new data enters the system.

        A job naming a real delivery id but the wrong tenant must find nothing —
        not the row.
        """
        tenant = await self._tenant(platform)
        other = await self._tenant(platform)
        delivery_id = await self._delivery(platform, tenant)

        job = JobEnvelope(
            job_type=GCHAT_EVENT_JOB, tenant_id=other.id, payload={"delivery_id": delivery_id}
        )
        async with tenant_session(other.id) as session:
            with pytest.raises(GoogleChatDeliveryNotFoundError):
                await handle_gchat_event(session, job)

    async def test_a_stored_payload_that_no_longer_normalises_is_recorded_not_retried(
        self, platform: AsyncSession
    ) -> None:
        """Reachable only after a Google schema change, or a bug.

        Recorded rather than raised: a retry would decode it the same way three
        more times and then dead-letter.
        """
        tenant = await self._tenant(platform)
        delivery_id = f"sha256:{uuid.uuid4().hex}"
        platform.add(
            WebhookDelivery(
                tenant_id=tenant.id,
                delivery_id=delivery_id,
                event_type=CREATED,
                payload={"type": "google_chat_event", "event_type": CREATED, "message": {}},
            )
        )
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            await handle_gchat_event(
                session,
                JobEnvelope(
                    job_type=GCHAT_EVENT_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        row = await platform.scalar(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        assert row is not None
        await platform.refresh(row)
        assert row.status is DeliveryStatus.PROCESSED

    async def test_a_job_with_no_delivery_id_is_refused(self, platform: AsyncSession) -> None:
        tenant = await self._tenant(platform)

        async with tenant_session(tenant.id) as session:
            with pytest.raises(GoogleChatDeliveryNotFoundError):
                await handle_gchat_event(
                    session,
                    JobEnvelope(job_type=GCHAT_EVENT_JOB, tenant_id=tenant.id, payload={}),
                )
