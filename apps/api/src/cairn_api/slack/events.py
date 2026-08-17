"""What a Slack payload *is*, and what it means once it has verified.

Split from `inbound.py` because verification and interpretation fail for
different reasons and at different times: a bad signature is a security event,
and a payload shape we decline to ingest is an ordinary product decision. Keeping
them apart is also what lets every rule below be tested as a pure function, with
no HTTP, no database and no clock.

The rules that cost other people production incidents, stated once here:

**Identity is `(team_id, channel, ts)`.** A Slack `ts` is unique *within a
channel*, not globally, so keying on `ts` alone merges two workspaces' messages
the first time two channels produce the same timestamp.

**An edit's `ts` is not the message's `ts`.** `message_changed` carries the
original message under `event.message`, and the outer `event.ts` is the
timestamp *of the edit*. Reading the outer one produces a brand-new identity,
so the edit is stored as a second message and the stale original is left
standing as current — the classic version of this bug, and the one this module
exists to make unrepresentable. `message_deleted` has the same shape with
`event.deleted_ts`.

**Bots are filtered before the author is read.** A `bot_message` payload has no
`user` field at all, so any code that reads the author first raises `KeyError`
on the one class of message it was meant to drop. This is also how CAIRN never
ingests its own output: our messages carry a `bot_id`, so the loop is closed by
the same check.

**`app_rate_limited` is not an `event_callback`.** It has no nested `event` and
no `event_id`, so anything reaching for `payload["event"]["type"]` raises on the
delivery that means Slack is *dropping* this workspace's events.
"""

from __future__ import annotations

import enum
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

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
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.runner import JobRegistry, registry
from cairn_api.slack.inbound import TEARDOWN_EVENTS

logger = structlog.get_logger(__name__)

#: The job the endpoint publishes. One per accepted message, on the existing
#: queue, with the existing retry and dead-letter behaviour.
SLACK_EVENT_JOB = "slack.event"

#: The only `channel_type` CAIRN ingests. `im`, `mpim` and `group` are direct
#: messages, group DMs and private channels; a payload claiming one of those —
#: or claiming nothing — is dropped, so a mis-scoped token cannot quietly widen
#: what is collected.
PUBLIC_CHANNEL_TYPE = "channel"

#: Slack's own cap is 40k characters. Kept because `Activity.summary` is a
#: `String(2000)` downstream and a longer one fails validation for every long
#: message rather than for none.
MAX_SUMMARY_CHARS = 2000


class SlackDeliveryNotFoundError(LookupError):
    """The delivery named by a job does not exist in this tenant."""


class MessageAction(enum.StrEnum):
    """What happened to a message. Three, and no more: Slack's other subtypes
    are joins, leaves, topic changes and file shares, none of which is somebody
    saying something."""

    CREATED = "created"
    EDITED = "edited"
    DELETED = "deleted"


class DropReason(enum.StrEnum):
    """Why a verified delivery produced no work.

    A closed set, for the same reason `ConnectorErrorCategory` is one: these
    values are logged and counted, so they must be categories rather than
    sentences assembled out of a payload.
    """

    NOT_A_MESSAGE = "not_a_message"
    NOT_PUBLIC_CHANNEL = "not_public_channel"
    AUTOMATED_AUTHOR = "automated_author"
    UNSUPPORTED_SUBTYPE = "unsupported_subtype"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class SlackEnvelope:
    """The outer Slack envelope, read defensively.

    Every field is optional at this level because every one of them is absent on
    some real delivery: `url_verification` has no team, `app_rate_limited` has no
    event and no event id, and a malformed body has none of it.
    """

    type: str
    team_id: str | None
    event_id: str | None
    event_type: str
    event: Mapping[str, Any]
    challenge: str | None

    @property
    def is_teardown(self) -> bool:
        """`app_uninstalled` or `tokens_revoked` — both arrive as ordinary
        `event_callback` envelopes, and Slack guarantees no order between
        them."""
        return self.event_type in TEARDOWN_EVENTS


@dataclass(frozen=True, slots=True)
class SlackMessage:
    """One public-channel message, at one point in its life."""

    team_id: str
    channel_id: str

    #: The **original** message's ts, for all three actions. This is the field
    #: the whole module is arranged around: it is what makes an edit an update
    #: instead of a duplicate, and a delete a retirement instead of a new fact.
    message_ts: str

    action: MessageAction

    #: Slack's user id (`U…`), never a handle or a display name. Absent on a
    #: delete, which names no author.
    author_id: str | None

    text: str | None

    @property
    def provider_message_id(self) -> str:
        """The stable identity: team, channel, and the original timestamp.

        All three, because a `ts` is unique per channel only. Identical across
        the create, every edit and the delete of one message, which is exactly
        what makes those three collapse onto one record downstream.
        """
        return f"{self.team_id}:{self.channel_id}:{self.message_ts}"


@dataclass(frozen=True, slots=True)
class DroppedMessage:
    """A delivery that verified and was deliberately not ingested."""

    reason: DropReason


def read_envelope(body: bytes) -> SlackEnvelope | None:
    """Decode a verified body, or `None` if it is not a Slack envelope.

    `None` rather than an exception: this runs after verification, so a payload
    that does not parse is a Slack change or a bug, not an attack, and the
    endpoint answers it the same undifferentiated way either case deserves.
    """
    try:
        decoded: object = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(decoded, dict):
        return None

    envelope_type = _text(decoded.get("type"))
    if envelope_type is None:
        return None

    # `.get`, not `["event"]`. `app_rate_limited` has no nested event, and an
    # endpoint that raises on it is one that 500s precisely when Slack is
    # telling us we are losing this workspace's data.
    raw_event = decoded.get("event")
    event: Mapping[str, Any] = raw_event if isinstance(raw_event, dict) else {}

    return SlackEnvelope(
        type=envelope_type,
        # Top level, and only top level. Slack puts `team_id` beside `type`, not
        # inside `event`; reading the inner one yields `None` on every delivery
        # and would make every event unattributable.
        team_id=_text(decoded.get("team_id")),
        event_id=_text(decoded.get("event_id")),
        event_type=_text(event.get("type")) or "",
        event=event,
        challenge=_text(decoded.get("challenge")),
    )


def read_message(envelope: SlackEnvelope) -> SlackMessage | DroppedMessage:
    """Interpret a message event, or say why it produced nothing.

    The order of the checks is the contract:

    1. it must be a message at all;
    2. it must be in a **public channel** — before any content is touched;
    3. it must not be from a bot or from us — before the author is read;
    4. only then is the subtype dispatched and the identity chosen.
    """
    if envelope.event_type != "message":
        return DroppedMessage(DropReason.NOT_A_MESSAGE)

    event = envelope.event

    # Ahead of everything else. A payload claiming `im`, `mpim` or `group` — or
    # omitting the field — is not something a customer permitted us to read, and
    # deciding that before the body is examined means an unpermitted message is
    # never even held in a local.
    if _text(event.get("channel_type")) != PUBLIC_CHANNEL_TYPE:
        return DroppedMessage(DropReason.NOT_PUBLIC_CHANNEL)

    subtype = _text(event.get("subtype"))
    edited = event.get("message")
    inner: Mapping[str, Any] = edited if isinstance(edited, dict) else {}

    # Before the author is read, in both the outer event and the edited-message
    # body. `bot_id` is the reliable signal — `subtype` is `bot_message` only
    # for some app posts — and an edit of a bot's message carries it inside.
    if subtype == "bot_message" or "bot_id" in event or "bot_id" in inner:
        return DroppedMessage(DropReason.AUTOMATED_AUTHOR)

    team_id = envelope.team_id
    channel_id = _text(event.get("channel"))
    if team_id is None or channel_id is None:
        return DroppedMessage(DropReason.MALFORMED)

    if subtype is None:
        return _built(
            team_id,
            channel_id,
            MessageAction.CREATED,
            ts=_text(event.get("ts")),
            author=_text(event.get("user")),
            text=_text(event.get("text")),
        )

    if subtype == "message_changed":
        # `inner["ts"]`, never `event["ts"]`. The outer one is the timestamp of
        # the *edit*; using it invents a second message and leaves the original
        # standing as current. Note this event also fires for Slack's automatic
        # language detection, so an edit whose text is byte-identical to the
        # original is normal and must still resolve to the same identity.
        return _built(
            team_id,
            channel_id,
            MessageAction.EDITED,
            ts=_text(inner.get("ts")),
            author=_text(inner.get("user")),
            text=_text(inner.get("text")),
        )

    if subtype == "message_deleted":
        return _built(
            team_id,
            channel_id,
            MessageAction.DELETED,
            ts=_text(event.get("deleted_ts")),
            author=None,
            text=None,
        )

    # Joins, leaves, topic changes, file shares, thread broadcasts. Not refused
    # — simply not a statement anybody made in prose, and ingesting them would
    # fill a workspace's record with "Priya joined #general".
    return DroppedMessage(DropReason.UNSUPPORTED_SUBTYPE)


def _built(
    team_id: str,
    channel_id: str,
    action: MessageAction,
    *,
    ts: str | None,
    author: str | None,
    text: str | None,
) -> SlackMessage | DroppedMessage:
    """Assemble a message, or drop it for want of an identity."""
    if ts is None:
        return DroppedMessage(DropReason.MALFORMED)
    return SlackMessage(
        team_id=team_id,
        channel_id=channel_id,
        message_ts=ts,
        action=action,
        author_id=author,
        text=text,
    )


def normalise(
    message: SlackMessage, *, tenant_id: uuid.UUID, traceparent: str | None = None
) -> ActivityEvent:
    """A Slack message as the shared `ActivityEvent`.

    The envelope's `id` is the **stable provider id**, identical for the create,
    the edits and the delete of one message, so `event_key` — `(source, id)` —
    dedupes them onto one record rather than accumulating three. What changes
    between them is the `type` suffix, which is what tells a consumer whether
    this is the current statement or its retirement.

    `time` is the original message's timestamp for every action, including the
    delete. That is deliberate: a retirement is dated by the statement it
    retires, and dating it "now" would reorder a workspace's history every time
    somebody tidied up an old thread.
    """
    action = message.action
    return ActivityEvent(
        id=message.provider_message_id,
        source=f"/slack/{message.team_id}",
        type=f"ai.cairn.slack.message.{action.value}.v1",
        subject=message.channel_id,
        time=_occurred_at(message.message_ts),
        data=ActivityPayload(
            actor=Actor(
                # Slack's opaque user id, never a handle or display name.
                # Identity resolution maps it to a person; a handle here would
                # put a name into every consumer that only needed a key.
                raw_identity=message.author_id or f"slack:{message.team_id}:unknown",
                is_bot=False,
            ),
            activity=Activity(
                category=ActivityCategory.CONVERSATION,
                action=action.value,
                summary=_summary(message),
                project_ref=None,
            ),
            provenance=Provenance(
                # Something a human can open, in Slack, at that message.
                source_url=_permalink(message),
                certainty=Certainty.OBSERVED,
            ),
            content=Content(
                text=message.text,
                metadata={
                    "team_id": message.team_id,
                    "channel_id": message.channel_id,
                    "message_ts": message.message_ts,
                    "action": action.value,
                },
            ),
        ),
        tenantid=tenant_id,
        traceparent=traceparent,
    )


def current_statements(events: Iterable[ActivityEvent]) -> dict[str, ActivityEvent]:
    """Fold a stream of Slack activity into what is true *now*.

    Small and pure, and the executable statement of requirement 6: an edit
    replaces the statement under the same key rather than adding a second one,
    and a delete removes it rather than leaving a retracted sentence presented as
    current. A consumer that stores instead of folding gets the same result from
    the same key, which is the point of the key being stable.
    """
    current: dict[str, ActivityEvent] = {}
    for event in events:
        if event.type.endswith(".deleted.v1"):
            current.pop(event.id, None)
            continue
        current[event.id] = event
    return current


async def handle_slack_event(session: AsyncSession, envelope: JobEnvelope) -> None:
    """Process one accepted Slack delivery, on the worker.

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
        raise SlackDeliveryNotFoundError(msg)

    delivery = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
    )
    if delivery is None:
        msg = f"Delivery {delivery_id} not found for tenant {envelope.tenant_id}"
        raise SlackDeliveryNotFoundError(msg)

    if delivery.status is DeliveryStatus.PROCESSED:
        # At-least-once delivery guarantees this happens. Treating it as an
        # error would fill the dead-letter queue with successful work.
        await logger.adebug("slack.delivery_already_processed", delivery_id=delivery_id)
        return

    slack_envelope = read_envelope(json.dumps(delivery.payload).encode("utf-8"))
    decision = (
        read_message(slack_envelope)
        if slack_envelope is not None
        else DroppedMessage(DropReason.MALFORMED)
    )

    if isinstance(decision, DroppedMessage):
        # Reachable only if a stored payload no longer parses the way it did at
        # receipt — a Slack schema change, or a bug. Recorded, not raised: a
        # retry would decode it the same way three more times.
        delivery.status = DeliveryStatus.PROCESSED
        delivery.processed_at = datetime.now(UTC)
        await logger.awarning(
            "slack.delivery_not_normalisable",
            delivery_id=delivery_id,
            reason=decision.reason.value,
        )
        return

    activity = normalise(decision, tenant_id=envelope.tenant_id, traceparent=envelope.traceparent)

    delivery.status = DeliveryStatus.PROCESSED
    delivery.processed_at = datetime.now(UTC)
    delivery.error = None

    # Ids and categories only. No text, no channel name (Slack does not send
    # one), no user handle. `correlation_id` is already bound by the worker.
    await logger.ainfo(
        "slack.delivery_processed",
        delivery_id=delivery_id,
        action=decision.action.value,
        activity_type=activity.type,
    )


def register(target: JobRegistry | None = None) -> None:
    """Register the handler, explicit rather than by import side effect."""
    (target or registry).register(SLACK_EVENT_JOB)(handle_slack_event)


def _summary(message: SlackMessage) -> str:
    """One line, always non-empty.

    `Activity.summary` requires at least one character, and a Slack message
    legitimately has none: a delete carries no text, and `message_changed` fires
    for Slack's own language detection on messages that are pure attachments. A
    validation error on those would fail the delivery rather than record it.
    """
    if message.action is MessageAction.DELETED:
        return "A message was deleted."
    text = (message.text or "").strip()
    if not text:
        return "A message with no text."
    return text[:MAX_SUMMARY_CHARS]


def _permalink(message: SlackMessage) -> AnyUrl:
    """Slack's archive URL for this exact message.

    Built rather than fetched: `chat.getPermalink` is an API call per event,
    inside a three-second acknowledgement budget, for a URL whose format is
    documented and stable.
    """
    return AnyUrl(
        f"https://slack.com/archives/{message.channel_id}/p{message.message_ts.replace('.', '')}"
    )


def _occurred_at(ts: str) -> datetime:
    """A Slack `ts` as an instant.

    Slack's `ts` is Unix seconds with a microsecond suffix. A malformed one
    falls back to now rather than raising — the message did arrive, and refusing
    to record it because its timestamp is odd loses more than it protects.
    """
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return datetime.now(UTC)


def _text(value: object) -> str | None:
    """A non-empty string, or nothing."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
