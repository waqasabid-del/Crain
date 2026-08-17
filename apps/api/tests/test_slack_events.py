"""What a Slack payload means once it has verified.

Every test here is a pure function over a payload — no HTTP, no database, no
clock — because these are the rules that are wrong in most Slack integrations
and each of them has a payload shape that makes the error visible on its own.

The three that carry the most weight:

* an **edit** must resolve to the *original* message's identity, or the edit is
  stored as a second message and the stale original is left standing as current;
* a **delete** must retire the statement rather than adding a tombstone beside
  it;
* a **bot** message must be dropped before the author is read, because a
  ``bot_message`` payload has no ``user`` field at all — and because that same
  check is what stops CAIRN ingesting its own output.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from cairn_api.events.schema import event_key
from cairn_api.slack.events import (
    DroppedMessage,
    DropReason,
    MessageAction,
    SlackMessage,
    current_statements,
    normalise,
    read_envelope,
    read_message,
)

TEAM = "T0ACME01"
CHANNEL = "C0123ABCDEF"
OTHER_CHANNEL = "C0999ZZZZZZ"
USER = "U07PRIYA"
TS = "1755400000.000100"
EDIT_TS = "1755409999.000900"


def envelope_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def message_payload(
    *,
    event: dict[str, Any] | None = None,
    team_id: str | None = TEAM,
    event_id: str = "Ev0000000001",
) -> dict[str, Any]:
    """An `event_callback` envelope wrapping a message event."""
    body: dict[str, Any] = {
        "type": "event_callback",
        "event_id": event_id,
        "event": event
        if event is not None
        else {
            "type": "message",
            "channel": CHANNEL,
            "channel_type": "channel",
            "user": USER,
            "text": "We are shipping the payments migration on Friday.",
            "ts": TS,
        },
    }
    if team_id is not None:
        body["team_id"] = team_id
    return body


def read(payload: dict[str, Any]) -> SlackMessage | DroppedMessage:
    parsed = read_envelope(envelope_bytes(payload))
    assert parsed is not None
    return read_message(parsed)


class TestTheEnvelope:
    def test_the_team_and_event_id_are_read_from_the_top_level(self) -> None:
        """Both are siblings of `type`, not fields of the nested event.

        Reading `event.event_id` yields `None` on every delivery, which makes
        every idempotency key a derived digest — and reading `event.team_id`
        makes every event unattributable.
        """
        parsed = read_envelope(envelope_bytes(message_payload(event_id="Ev123ABC456")))

        assert parsed is not None
        assert parsed.team_id == TEAM
        assert parsed.event_id == "Ev123ABC456"
        assert parsed.event_type == "message"

    def test_app_rate_limited_does_not_raise_on_its_missing_event(self) -> None:
        """It is not an `event_callback`: there is no nested `event` at all.

        Code reaching for `payload["event"]["type"]` raises here — on the one
        delivery that means Slack is *dropping* this workspace's events, which
        is the worst possible moment for the endpoint to fail.
        """
        parsed = read_envelope(
            envelope_bytes(
                {"type": "app_rate_limited", "team_id": TEAM, "minute_rate_limited": 1755400000}
            )
        )

        assert parsed is not None
        assert parsed.type == "app_rate_limited"
        assert parsed.event_id is None
        assert parsed.event_type == ""
        # And interpreting it as a message is a drop, not an exception.
        assert read_message(parsed) == DroppedMessage(DropReason.NOT_A_MESSAGE)

    @pytest.mark.parametrize(
        "body",
        [b"", b"not json at all", b"[1, 2, 3]", b'"a string"', b'{"no":"type"}'],
    )
    def test_a_body_that_is_not_a_slack_envelope_is_refused(self, body: bytes) -> None:
        assert read_envelope(body) is None

    def test_a_teardown_event_is_recognised_by_either_name(self) -> None:
        """Both are subscribed, and Slack guarantees no order between them."""
        for name in ("app_uninstalled", "tokens_revoked"):
            parsed = read_envelope(
                envelope_bytes({"type": "event_callback", "team_id": TEAM, "event": {"type": name}})
            )
            assert parsed is not None
            assert parsed.is_teardown


class TestOnlyPublicChannels:
    @pytest.mark.parametrize("channel_type", ["im", "mpim", "group", "private_channel"])
    def test_direct_and_private_conversations_are_never_ingested(self, channel_type: str) -> None:
        """A payload claiming one of these is dropped whatever else it says.

        Slack's own scopes should never deliver these, which is exactly why the
        check is here: a mis-scoped or re-scoped token must not be able to widen
        what CAIRN collects without anybody deciding to.
        """
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "channel": "D0PRIVATE1",
                    "channel_type": channel_type,
                    "user": USER,
                    "text": "a private thing",
                    "ts": TS,
                }
            )
        )

        assert decision == DroppedMessage(DropReason.NOT_PUBLIC_CHANNEL)

    def test_a_missing_channel_type_is_dropped_rather_than_assumed_public(self) -> None:
        decision = read(
            message_payload(
                event={"type": "message", "channel": CHANNEL, "user": USER, "ts": TS, "text": "hi"}
            )
        )

        assert decision == DroppedMessage(DropReason.NOT_PUBLIC_CHANNEL)


class TestAutomatedAuthors:
    def test_a_bot_message_is_dropped_before_the_author_is_read(self) -> None:
        """A `bot_message` payload has **no** `user` field.

        Any implementation that reads the author first raises `KeyError` on
        precisely the messages it meant to drop, so the ordering is the test.
        """
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "subtype": "bot_message",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "bot_id": "B0CAIRN01",
                    "text": "Weekly brief: 4 facts recorded.",
                    "ts": TS,
                }
            )
        )

        assert decision == DroppedMessage(DropReason.AUTOMATED_AUTHOR)

    def test_a_bot_id_without_the_subtype_is_still_dropped(self) -> None:
        """`bot_id` is the reliable signal; the subtype is not always set.

        This is also how CAIRN never ingests its own output: our posts carry a
        `bot_id`, so the loop is closed here rather than by a name comparison
        somebody has to keep up to date.
        """
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "bot_id": "B0CAIRN01",
                    "user": "U0CAIRNBOT",
                    "text": "Weekly brief: 4 facts recorded.",
                    "ts": TS,
                }
            )
        )

        assert decision == DroppedMessage(DropReason.AUTOMATED_AUTHOR)

    def test_an_edit_of_a_bot_message_is_dropped_too(self) -> None:
        # The `bot_id` moves inside `event.message` on an edit, so a check that
        # only looks at the outer event lets a bot's edited output through.
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "ts": EDIT_TS,
                    "message": {"bot_id": "B0CAIRN01", "text": "edited brief", "ts": TS},
                }
            )
        )

        assert decision == DroppedMessage(DropReason.AUTOMATED_AUTHOR)


class TestMessageIdentity:
    def test_a_new_message_is_identified_by_team_channel_and_ts(self) -> None:
        """`ts` is unique per *channel*, not globally.

        Keying on it alone merges two workspaces' messages the first time two
        channels produce the same timestamp — which, since a `ts` is a clock
        reading, is not rare.
        """
        decision = read(message_payload())

        assert isinstance(decision, SlackMessage)
        assert decision.action is MessageAction.CREATED
        assert decision.provider_message_id == f"{TEAM}:{CHANNEL}:{TS}"

    def test_the_same_ts_in_two_channels_is_two_messages(self) -> None:
        here = read(message_payload())
        there = read(
            message_payload(
                event={
                    "type": "message",
                    "channel": OTHER_CHANNEL,
                    "channel_type": "channel",
                    "user": USER,
                    "text": "a different message",
                    "ts": TS,
                }
            )
        )

        assert isinstance(here, SlackMessage)
        assert isinstance(there, SlackMessage)
        assert here.provider_message_id != there.provider_message_id

    def test_an_edit_takes_the_originals_ts_not_the_edits(self) -> None:
        """The classic bug, asserted directly.

        `event.ts` on a `message_changed` is the timestamp *of the edit*. Using
        it produces a second, unrelated identity — so the edit is stored as a
        new message and the stale original is left presented as current.
        """
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "ts": EDIT_TS,
                    "message": {
                        "type": "message",
                        "user": USER,
                        "text": "We are shipping the payments migration on Monday.",
                        "ts": TS,
                    },
                }
            )
        )

        assert isinstance(decision, SlackMessage)
        assert decision.action is MessageAction.EDITED
        assert decision.message_ts == TS
        assert decision.message_ts != EDIT_TS
        assert decision.provider_message_id == f"{TEAM}:{CHANNEL}:{TS}"

    def test_a_delete_takes_deleted_ts_not_the_outer_ts(self) -> None:
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "subtype": "message_deleted",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "ts": EDIT_TS,
                    "deleted_ts": TS,
                }
            )
        )

        assert isinstance(decision, SlackMessage)
        assert decision.action is MessageAction.DELETED
        assert decision.message_ts == TS
        assert decision.provider_message_id == f"{TEAM}:{CHANNEL}:{TS}"

    def test_an_edit_with_identical_text_still_resolves_to_the_original(self) -> None:
        """`message_changed` also fires for Slack's automatic language
        detection, so an edit that changes nothing visible is normal traffic —
        and must not create a second record."""
        text = "We are shipping the payments migration on Friday."
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "ts": EDIT_TS,
                    "message": {"user": USER, "text": text, "ts": TS},
                }
            )
        )

        assert isinstance(decision, SlackMessage)
        assert decision.provider_message_id == f"{TEAM}:{CHANNEL}:{TS}"

    @pytest.mark.parametrize(
        "subtype", ["channel_join", "channel_leave", "channel_topic", "channel_purpose"]
    )
    def test_membership_noise_is_not_a_statement(self, subtype: str) -> None:
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "subtype": subtype,
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "user": USER,
                    "text": "<@U07PRIYA> has joined the channel",
                    "ts": TS,
                }
            )
        )

        assert decision == DroppedMessage(DropReason.UNSUPPORTED_SUBTYPE)

    def test_a_message_without_a_timestamp_is_dropped(self) -> None:
        decision = read(
            message_payload(
                event={
                    "type": "message",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "user": USER,
                    "text": "no ts",
                }
            )
        )

        assert decision == DroppedMessage(DropReason.MALFORMED)


class TestNormalisation:
    """Onto the shared `ActivityEvent`, with a stable id and real provenance."""

    def test_the_created_event_carries_identity_provenance_and_tenant(self) -> None:
        tenant_id = uuid.uuid4()
        decision = read(message_payload())
        assert isinstance(decision, SlackMessage)

        activity = normalise(decision, tenant_id=tenant_id)

        assert activity.id == f"{TEAM}:{CHANNEL}:{TS}"
        assert activity.source == f"/slack/{TEAM}"
        assert activity.type == "ai.cairn.slack.message.created.v1"
        assert activity.subject == CHANNEL
        assert activity.tenantid == tenant_id
        # Provenance is a product feature: a reader can open the message.
        assert str(activity.data.provenance.source_url) == (
            f"https://slack.com/archives/{CHANNEL}/p1755400000000100"
        )
        # The author is Slack's opaque user id, never a handle.
        assert activity.data.actor.raw_identity == USER

    def test_the_time_is_when_the_message_was_sent(self) -> None:
        # Not when we received it: every user-facing view orders by this, and
        # conflating the two produces a brief claiming today's work that
        # happened last month.
        decision = read(message_payload())
        assert isinstance(decision, SlackMessage)

        activity = normalise(decision, tenant_id=uuid.uuid4())

        assert activity.time.timestamp() == pytest.approx(float(TS))

    def test_an_edit_normalises_onto_the_same_key_as_the_original(self) -> None:
        original = read(message_payload())
        edit = read(
            message_payload(
                event={
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": CHANNEL,
                    "channel_type": "channel",
                    "ts": EDIT_TS,
                    "message": {"user": USER, "text": "Monday, not Friday.", "ts": TS},
                }
            )
        )
        assert isinstance(original, SlackMessage)
        assert isinstance(edit, SlackMessage)

        tenant_id = uuid.uuid4()
        first = normalise(original, tenant_id=tenant_id)
        second = normalise(edit, tenant_id=tenant_id)

        # `(source, id)` is the deduplication key. Identical means "update".
        assert event_key(first) == event_key(second)
        assert second.type == "ai.cairn.slack.message.edited.v1"


class TestEditsAndDeletesResolve:
    """The property the identity work exists for, stated as an outcome."""

    def _fold(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        tenant_id = uuid.uuid4()
        activities = []
        for payload in payloads:
            decision = read(payload)
            assert isinstance(decision, SlackMessage)
            activities.append(normalise(decision, tenant_id=tenant_id))
        return dict(current_statements(activities))

    def test_an_edit_updates_rather_than_duplicating(self) -> None:
        current = self._fold(
            [
                message_payload(),
                message_payload(
                    event={
                        "type": "message",
                        "subtype": "message_changed",
                        "channel": CHANNEL,
                        "channel_type": "channel",
                        "ts": EDIT_TS,
                        "message": {
                            "user": USER,
                            "text": "We are shipping the payments migration on Monday.",
                            "ts": TS,
                        },
                    }
                ),
            ]
        )

        assert len(current) == 1
        [statement] = current.values()
        # The current text is the edited one — the stale Friday claim is gone,
        # rather than sitting beside it as a second, equally current fact.
        assert "Monday" in statement.data.activity.summary
        assert "Friday" not in statement.data.activity.summary

    def test_a_delete_retires_the_statement(self) -> None:
        current = self._fold(
            [
                message_payload(),
                message_payload(
                    event={
                        "type": "message",
                        "subtype": "message_deleted",
                        "channel": CHANNEL,
                        "channel_type": "channel",
                        "ts": EDIT_TS,
                        "deleted_ts": TS,
                    }
                ),
            ]
        )

        # Retired, not tombstoned beside the original: a retracted sentence
        # presented as current is worse than one that was never recorded.
        assert current == {}

    def test_a_delete_of_one_message_leaves_the_others_alone(self) -> None:
        # The positive control. Without it the test above would pass against an
        # implementation that discarded everything on any delete.
        current = self._fold(
            [
                message_payload(),
                message_payload(
                    event={
                        "type": "message",
                        "channel": OTHER_CHANNEL,
                        "channel_type": "channel",
                        "user": USER,
                        "text": "still true",
                        "ts": TS,
                    }
                ),
                message_payload(
                    event={
                        "type": "message",
                        "subtype": "message_deleted",
                        "channel": CHANNEL,
                        "channel_type": "channel",
                        "ts": EDIT_TS,
                        "deleted_ts": TS,
                    }
                ),
            ]
        )

        assert list(current) == [f"{TEAM}:{OTHER_CHANNEL}:{TS}"]
