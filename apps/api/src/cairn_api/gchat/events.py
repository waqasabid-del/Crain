"""What a Google Chat payload *is*, and what it means once the push has verified.

Split from `pubsub.py` for the reason `slack/events.py` is split from
`slack/inbound.py`: verification and interpretation fail for different reasons
and at different times. A token that does not verify is a security event; a
payload shape CAIRN declines to ingest is an ordinary product decision. Keeping
them apart is also what lets every rule below be a pure function with no HTTP, no
database and no clock.

The rules that are specific to Chat, and that cost time to learn:

**The event type is not in the payload.** Created, updated and deleted arrive as
*structurally identical* bodies; what distinguishes them is the CloudEvent
`ce-type` attribute Pub/Sub carries beside the data. So `read_event` takes the
type as an argument rather than reading one out of the body, and a body claiming
a type is ignored. The documented *deleted* example still shows `text` and
`sender` — that is boilerplate, and requiring either on a delete would drop every
retirement.

**Identity is the message resource name.** `spaces/{space}/messages/{message}` is
globally unique and identical for the create, every edit and the delete of one
message, so it is what makes an edit an update rather than a second statement and
a delete a retirement rather than a new fact. Nothing shorter works: a bare
message id is unique only within its space.

**The space is derived from the message name, not read beside it.** A payload
carries the space twice — `message.name` contains it and `message.space.name`
repeats it — and a body that disagrees with itself is refused rather than
resolved. Trusting the standalone copy would let one field name the space a
tenant lookup uses while another named the message actually stored.

**Bots are dropped before the author or the text is read.** `sender.type` is
`BOT` for app posts, which is how CAIRN never ingests its own output. It is
applied to creates and edits only: a delete's sender is the boilerplate above, and
declining to retire a statement because unreliable boilerplate called it a bot
would leave a retracted claim standing as current.
"""

from __future__ import annotations

import enum
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import structlog
from pydantic import AnyUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.events.schema import (
    Activity,
    ActivityCategory,
    ActivityEvent,
    ActivityPayload,
    Actor,
    Certainty,
    Content,
    Provenance,
)
from cairn_api.gchat.pubsub import PROVIDER
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.runner import JobRegistry, registry

logger = structlog.get_logger(__name__)

#: The job the endpoint publishes. One per accepted message, on the existing
#: queue, with the existing retry and dead-letter behaviour.
GCHAT_EVENT_JOB: Final = "gchat.event"

#: The `type` discriminator on a stored payload.
#:
#: Chat's own bodies carry no type at all — see the module docstring — so the
#: receipt path stores the CloudEvent type alongside the decoded resource. The
#: marker is what lets `pipeline/jobs.py` tell a Chat delivery from a GitHub one
#: in the shared `webhook_deliveries` table, where every provider's payload lands
#: in the same column.
STORED_PAYLOAD_TYPE: Final = "google_chat_event"

#: Chat's `sender.type` for a person. Anything else — `BOT`, or a value Google
#: adds later — is not somebody saying something.
HUMAN_SENDER_TYPE: Final = "HUMAN"

#: `Activity.summary` is a `String(2000)` downstream, and a longer one fails
#: validation for every long message rather than for none.
MAX_SUMMARY_CHARS: Final = 2000

#: The space id (`spaces/…`) is this many segments of a message resource name.
_SPACE_SEGMENTS: Final = 2

#: `spaces/{space}/messages/{message}` — four segments, and exactly four.
_NAME_SEGMENTS: Final = 4


class GoogleChatDeliveryNotFoundError(LookupError):
    """The delivery named by a job does not exist in this tenant."""


class MessageAction(enum.StrEnum):
    """What happened to a message. Three, and no more — Chat publishes exactly
    three message event types and CAIRN subscribes to no others."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"


#: The only CloudEvent types CAIRN ingests, and the action each one means.
#:
#: An exhaustive mapping rather than a prefix match: reactions, memberships and
#: space updates share the `google.workspace.chat.` namespace, and a prefix test
#: would quietly start ingesting whatever Google adds to it next.
SUPPORTED_EVENT_TYPES: Final[Mapping[str, MessageAction]] = {
    "google.workspace.chat.message.v1.created": MessageAction.CREATED,
    "google.workspace.chat.message.v1.updated": MessageAction.UPDATED,
    "google.workspace.chat.message.v1.deleted": MessageAction.DELETED,
}


class DropReason(enum.StrEnum):
    """Why a verified push produced no work.

    A closed set, for the same reason `ConnectorErrorCategory` is one: these
    values are logged and counted, so they must be categories rather than
    sentences assembled out of a payload.
    """

    NOT_A_MESSAGE_EVENT = "not_a_message_event"
    AUTOMATED_AUTHOR = "automated_author"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """One decoded Chat event: what happened, and to which resource."""

    #: The CloudEvent type, verbatim. Kept rather than reduced to the action so a
    #: stored payload can be re-read years later against whatever this module
    #: supports then.
    event_type: str

    action: MessageAction

    #: The `message` resource from the decoded payload, un-interpreted.
    message: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One space message, at one point in its life."""

    #: `spaces/{space}`, derived from the message resource name.
    space_name: str

    #: `spaces/{space}/messages/{message}` — the stable identity, identical
    #: across the create, every edit and the delete of one message.
    message_name: str

    action: MessageAction

    #: Google's opaque user resource name (`users/{user}`), never a display name
    #: or an email. Absent on a delete, whose sender field is boilerplate.
    sender_id: str | None

    text: str | None

    #: Chat's RFC 3339 `createTime`, as sent. Absent on some deletes.
    create_time: str | None

    @property
    def provider_message_id(self) -> str:
        """The resource name, which is already globally unique."""
        return self.message_name


@dataclass(frozen=True, slots=True)
class DroppedMessage:
    """A push that verified and was deliberately not ingested."""

    reason: DropReason


def read_event(data: bytes, *, event_type: str | None) -> ChatEvent | None:
    """Decode a verified Pub/Sub payload, or `None` if CAIRN does not ingest it.

    `None` rather than an exception: this runs after the token has verified, so a
    payload that does not parse is a Google change or a bug rather than an
    attack, and the endpoint acknowledges all of them the same way. Pub/Sub
    redelivering a body that will not parse the second time either is not a
    recovery.

    `event_type` is the `ce-type` attribute and is the **only** discriminator —
    see the module docstring.
    """
    action = SUPPORTED_EVENT_TYPES.get(event_type or "")
    if action is None:
        # Reactions, memberships, space changes, and anything Google adds later.
        return None

    try:
        decoded: object = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(decoded, dict):
        return None

    message = decoded.get("message")
    if not isinstance(message, dict):
        return None

    # `event_type` is not None here: it matched a key above.
    return ChatEvent(event_type=event_type or "", action=action, message=message)


def read_message(event: ChatEvent) -> ChatMessage | DroppedMessage:
    """Interpret a decoded event, or say why it produced nothing.

    The order of the checks is the contract:

    1. it must name a message resource, so it has an identity at all;
    2. the two copies of the space must agree — before either is used;
    3. an app's own post is dropped **before** the author or the text is read;
    4. only then is the content assembled.
    """
    message = event.message

    message_name = _text(message.get("name"))
    if message_name is None:
        return DroppedMessage(DropReason.MALFORMED)

    space_name = _space_of(message_name)
    if space_name is None:
        return DroppedMessage(DropReason.MALFORMED)

    space = message.get("space")
    stated = _text(space.get("name")) if isinstance(space, dict) else None
    if stated is not None and stated != space_name:
        # A body that disagrees with itself about which space it belongs to.
        # Refused rather than reconciled: whichever copy lost would be the one
        # some later reader used.
        return DroppedMessage(DropReason.MALFORMED)

    sender = message.get("sender")
    sender_map: Mapping[str, Any] = sender if isinstance(sender, dict) else {}

    if event.action is not MessageAction.DELETED and (
        _text(sender_map.get("type")) != HUMAN_SENDER_TYPE
    ):
        # Before the author and the text are touched. A missing or non-`HUMAN`
        # sender is an app post — including CAIRN's own, which is how the loop
        # stays closed. Deletes are exempt: their sender block is boilerplate,
        # and refusing to retire a statement on the strength of it would leave a
        # retracted claim standing as current.
        return DroppedMessage(DropReason.AUTOMATED_AUTHOR)

    if event.action is MessageAction.DELETED:
        # No author and no text, whatever the payload echoes back. A retirement
        # names the statement it retires and nothing else.
        return ChatMessage(
            space_name=space_name,
            message_name=message_name,
            action=event.action,
            sender_id=None,
            text=None,
            create_time=_text(message.get("createTime")),
        )

    return ChatMessage(
        space_name=space_name,
        message_name=message_name,
        action=event.action,
        sender_id=_text(sender_map.get("name")),
        text=_text(message.get("text")),
        create_time=_text(message.get("createTime")),
    )


def stored_payload(event: ChatEvent) -> dict[str, Any]:
    """What the receipt path writes to `webhook_deliveries.payload`.

    The CloudEvent type is stored *with* the resource, because it is the only
    thing that distinguishes a delete from a create and it arrives in a Pub/Sub
    attribute the body never carries. A stored payload without it would be
    un-re-readable — which is precisely what the worker and the pipeline do with
    it later.
    """
    return {
        "type": STORED_PAYLOAD_TYPE,
        "event_type": event.event_type,
        "message": dict(event.message),
    }


def read_stored(payload: Mapping[str, Any]) -> ChatEvent | None:
    """The inverse of `stored_payload`, for the worker and anything re-reading a
    delivery."""
    if _text(payload.get("type")) != STORED_PAYLOAD_TYPE:
        return None
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    return read_event(
        json.dumps({"message": message}).encode("utf-8"),
        event_type=_text(payload.get("event_type")),
    )


def normalise(
    message: ChatMessage, *, tenant_id: uuid.UUID, traceparent: str | None = None
) -> ActivityEvent:
    """A Chat message as the shared `ActivityEvent`.

    The envelope's `id` is the message resource name, identical for the create,
    the edits and the delete of one message, so `event_key` — `(source, id)` —
    collapses them onto one record rather than accumulating three. What changes
    between them is the `type` suffix, which is what tells a consumer whether
    this is the current statement or its retirement.

    `time` is the message's own `createTime` for every action, including the
    delete. A retirement is dated by the statement it retires; dating it "now"
    would reorder a space's history every time somebody tidied up an old thread.
    """
    action = message.action
    return ActivityEvent(
        id=message.provider_message_id,
        source=f"/google_chat/{message.space_name}",
        type=f"ai.cairn.google_chat.message.{action.value}.v1",
        subject=message.space_name,
        time=_occurred_at(message.create_time),
        data=ActivityPayload(
            actor=Actor(
                # Google's opaque user resource name, never a display name or an
                # address. Identity resolution maps it to a person; a name here
                # would put one into every consumer that only needed a key.
                raw_identity=message.sender_id or f"google_chat:{message.space_name}:unknown",
                is_bot=False,
            ),
            activity=Activity(
                category=ActivityCategory.CONVERSATION,
                action=action.value,
                summary=_summary(message),
                project_ref=None,
            ),
            provenance=Provenance(
                source_url=_permalink(message),
                certainty=Certainty.OBSERVED,
            ),
            content=Content(
                text=message.text,
                metadata={
                    "space_name": message.space_name,
                    "message_name": message.message_name,
                    "action": action.value,
                },
            ),
        ),
        tenantid=tenant_id,
        traceparent=traceparent,
    )


def current_statements(events: Iterable[ActivityEvent]) -> dict[str, ActivityEvent]:
    """Fold a stream of Chat activity into what is true *now*.

    Small and pure: an edit replaces the statement under the same key rather than
    adding a second one, and a delete removes it rather than leaving a retracted
    sentence presented as current. A consumer that stores instead of folding gets
    the same result from the same key, which is the point of the key being
    stable.
    """
    current: dict[str, ActivityEvent] = {}
    for event in events:
        if event.type.endswith(".deleted.v1"):
            current.pop(event.id, None)
            continue
        current[event.id] = event
    return current


async def handle_gchat_event(session: AsyncSession, envelope: JobEnvelope) -> None:
    """Process one accepted Chat delivery, on the worker.

    The payload is re-read from the database rather than carried on the message,
    for the reason `github/handlers.py` gives: the queue is not a durable store,
    redelivery is normal, and customer content on a broker has none of the
    storage promises the database has. The session is already tenant-scoped, so
    row-level security is what makes another workspace's delivery invisible
    rather than a `WHERE` clause somebody could omit.
    """
    delivery_id = envelope.payload.get("delivery_id")
    if not isinstance(delivery_id, str):
        msg = f"Job {envelope.job_id} has no delivery_id"
        raise GoogleChatDeliveryNotFoundError(msg)

    delivery = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
    )
    if delivery is None:
        msg = f"Delivery {delivery_id} not found for tenant {envelope.tenant_id}"
        raise GoogleChatDeliveryNotFoundError(msg)

    if delivery.status is DeliveryStatus.PROCESSED:
        # At-least-once delivery guarantees this happens. Treating it as an
        # error would fill the dead-letter queue with successful work.
        await logger.adebug("gchat.delivery_already_processed", delivery_id=delivery_id)
        return

    event = read_stored(delivery.payload)
    decision: ChatMessage | DroppedMessage = (
        read_message(event) if event is not None else DroppedMessage(DropReason.MALFORMED)
    )

    if isinstance(decision, DroppedMessage):
        # Reachable only if a stored payload no longer parses the way it did at
        # receipt — a Google schema change, or a bug. Recorded, not raised: a
        # retry would decode it the same way three more times.
        delivery.status = DeliveryStatus.PROCESSED
        delivery.processed_at = datetime.now(UTC)
        await logger.awarning(
            "gchat.delivery_not_normalisable",
            delivery_id=delivery_id,
            reason=decision.reason.value,
        )
        return

    activity = normalise(decision, tenant_id=envelope.tenant_id, traceparent=envelope.traceparent)

    delivery.status = DeliveryStatus.PROCESSED
    delivery.processed_at = datetime.now(UTC)
    delivery.error = None

    # Ids and categories only. No text, no space name, no sender.
    # `correlation_id` is already bound by the worker.
    await logger.ainfo(
        "gchat.delivery_processed",
        delivery_id=delivery_id,
        action=decision.action.value,
        activity_type=activity.type,
    )


def register(target: JobRegistry | None = None) -> None:
    """Register the handler, explicit rather than by import side effect."""
    (target or registry).register(GCHAT_EVENT_JOB)(handle_gchat_event)


def _space_of(message_name: str) -> str | None:
    """`spaces/{space}` from `spaces/{space}/messages/{message}`.

    Derived rather than read from `message.space.name`, so the space a tenant is
    looked up by and the message that is stored can never name different rooms.

    The **exact** four-segment shape is required, not a prefix of it. That is
    what makes every `ChatMessage` carry a resource name a permalink can be built
    from — and `Provenance` refuses an `observed` claim with nothing to open, so
    a name this function let through loosely would fail validation later, at
    normalisation, for a reason nobody would connect back to here.
    """
    parts = message_name.split("/")
    if len(parts) != _NAME_SEGMENTS or parts[0] != "spaces" or parts[2] != "messages":
        return None
    if not parts[1] or not parts[3]:
        return None
    return "/".join(parts[:_SPACE_SEGMENTS])


def _summary(message: ChatMessage) -> str:
    """One line, always non-empty.

    `Activity.summary` requires at least one character, and a Chat message
    legitimately has none: a delete carries no text, and a message can be a card
    or an attachment with an empty `text`. A validation error on those would fail
    the delivery rather than record it.
    """
    if message.action is MessageAction.DELETED:
        return "A message was deleted."
    text = (message.text or "").strip()
    if not text:
        return "A message with no text."
    return text[:MAX_SUMMARY_CHARS]


def _permalink(message: ChatMessage) -> AnyUrl:
    """Chat's own URL for this exact message.

    Built rather than fetched: asking `spaces.messages.get` for a link would be
    an API call per event inside an acknowledgement budget that cannot be
    extended, for a URL whose shape is `chat.google.com/room/{space}/{message}`
    and stable.

    Total, not optional, and that is a property of `_space_of` rather than of
    this function: every `ChatMessage` carries a four-segment resource name, so
    there is no case where a citation would have to be published with nothing a
    reader can open.
    """
    space_id = message.space_name.removeprefix("spaces/")
    message_id = message.message_name.rsplit("/", 1)[-1]
    return AnyUrl(f"https://chat.google.com/room/{space_id}/{message_id}")


def _occurred_at(create_time: str | None) -> datetime:
    """Chat's RFC 3339 `createTime` as an instant.

    A missing or malformed one falls back to now rather than raising — the
    message did arrive, and refusing to record it because its timestamp is odd
    loses more than it protects.
    """
    if not create_time:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _text(value: object) -> str | None:
    """A non-empty string, or nothing."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "GCHAT_EVENT_JOB",
    "PROVIDER",
    "STORED_PAYLOAD_TYPE",
    "SUPPORTED_EVENT_TYPES",
    "ChatEvent",
    "ChatMessage",
    "DropReason",
    "DroppedMessage",
    "GoogleChatDeliveryNotFoundError",
    "MessageAction",
    "current_statements",
    "handle_gchat_event",
    "normalise",
    "read_event",
    "read_message",
    "read_stored",
    "register",
    "stored_payload",
]
