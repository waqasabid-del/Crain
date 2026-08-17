"""Connector operations: enough to run a source, not enough to read one.

Step 32 adds Slack and Google Chat. Everything asserted here is about what an
operator can see *before* that lands and — more importantly — what they must
still not be able to see afterwards.

Four properties, each with a test that fails if the property is removed:

**The read model cannot carry content or a person.** Asserted over
`dataclasses.fields`, not by reading the source. A test that grepped the file
would pass the day somebody adds `last_message` through a helper, and the field
that breaks the promise always arrives as a convenience — "just show the last
event so support can see what is wrong". `source_connections` stores an
`external_account_label` and a `sync_cursor` one column away from every query
this module makes, so the field that would leak already exists upstream.

**A configured connector is never "passed".** A signing secret in an environment
variable proves somebody set a variable. The gate has no input that is a
delivery, so `PASSED` is unreachable from it, and that is pinned rather than
left as an accident of the current branches.

**No metric measures a person.** md/05 §B.2 forbids the individual-productivity
shape, and a per-channel or per-account count is that metric with a different
label on it. Structural, in the same style as `test_slo.py`.

**Staff-role gating matches the other operations surfaces.** The router is
another engineer's file, so this asserts the pattern the read model has to be
mounted behind, and becomes a direct check on the route the moment it exists.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cairn_api.api.routers import internal
from cairn_api.config import Settings
from cairn_api.db.connector_models import ConnectionState
from cairn_api.db.github_models import GitHubInstallation
from cairn_api.db.models import Tenant
from cairn_api.db.staff_models import StaffRole
from cairn_api.ops import connectors
from cairn_api.ops.release_gates import GateStatus, evaluate_release_gates
from cairn_api.telemetry.attributes import ALLOWED
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

# --------------------------------------------------------------------------
# The shape of the read model
# --------------------------------------------------------------------------

#: Words that would mean the model has started carrying what a source delivered
#: rather than whether it delivered. Deliberately broader than the fields that
#: exist: the list is here to reject the *next* one.
#:
#: Matched against the field name's underscore-separated words, singular or
#: plural, rather than as substrings. Substring matching reads `space` inside
#: `workspaces_connected` and rejects a count of workspaces — a test that cries
#: wolf on the safest field on the model is one somebody deletes.
FORBIDDEN_FIELD_WORDS = (
    "message",
    "text",
    "body",
    "content",
    "payload",
    "channel",
    "space",
    "conversation",
    "thread",
    "repository",
    "repo",
    "author",
    "actor",
    "account",
    "label",
    "login",
    "email",
    "handle",
    "user",
    "member",
    "person",
    "people",
    "employee",
    "sample",
    "cursor",
    "token",
    "secret",
    "credential",
    "url",
)

#: The only types a connector operations field may have: a count, an age, a
#: flag, a closed-set category, a timestamp, or a mapping of category to count.
#: Anything else is somewhere a string could be put. Widening this set is the
#: review that should be hard.
ALLOWED_FIELD_TYPES = {
    "int",
    "int | None",
    "bool",
    "float | None",
    "datetime",
    "datetime | None",
    "str | None",
    "ConnectorProvider",
    "Mapping[str, int]",
    "tuple[ConnectorHealth, ...]",
    # Step 33's subscription aggregate. Both are enums already closed next to
    # the columns that store them, reused rather than restated — see
    # `test_the_subscription_categories_are_the_ones_the_column_already_closed`.
    "GoogleChatSubscriptionState",
    "ConnectorErrorCategory | None",
}

#: Field names allowed to contain a forbidden word, listed exactly.
#:
#: Named one by one rather than matched by a pattern, for the reason
#: `test_internal.py` names its one content route explicitly: a pattern-based
#: exemption lets the next field opt out by being called something similar.
#: `credentials_configured` is a boolean about the environment — whether a
#: variable is set — and holds no credential, which is why the word "credential"
#: stays on the list above.
EXEMPT_FIELDS = frozenset({"credentials_configured"})

MODELS = (
    connectors.ConnectorHealth,
    connectors.ConnectorFleet,
    # Step 33's subscription aggregate, and the value type its reducer consumes.
    # The input type is in here on purpose: it is the place a space identifier
    # would arrive, because the caller building it holds one.
    connectors.SubscriptionHealth,
    connectors.SubscriptionRecord,
)

#: Every `str | None` field across the models, and the constants each may hold.
#:
#: A `str` on an operations model is where a provider's error body ends up during
#: an incident, and provider errors quote the request that failed — a channel, a
#: space, a message fragment. Each one is pinned to a closed set of module
#: constants so that the value is a deliberate edit rather than a judgement call
#: at 3am, and the mapping is exhaustive so a third one cannot arrive unnoticed.
REASON_FIELDS = {
    "deliveries_unobservable_reason": connectors.DELIVERY_UNOBSERVABLE_REASONS,
    "subscriptions_unobservable_reason": connectors.SUBSCRIPTION_UNOBSERVABLE_REASONS,
}


class TestTheReadModelCannotCarryContent:
    """The load-bearing file. Everything else here is downstream of it."""

    @pytest.mark.parametrize("model", MODELS, ids=lambda item: item.__name__)
    def test_no_field_could_hold_a_message_a_channel_or_a_person(self, model: type) -> None:
        """Asserted over the model's fields, never over the source text.

        Reading the file would pass the day the field arrives through a helper,
        a base class or a `**kwargs`. `dataclasses.fields` sees what the model
        actually is.
        """
        for item in dataclasses.fields(model):
            if item.name in EXEMPT_FIELDS:
                continue
            words = {part.removesuffix("s") for part in item.name.lower().split("_")}
            leaked = words & {word.removesuffix("s") for word in FORBIDDEN_FIELD_WORDS}
            assert not leaked, (
                f"{model.__name__}.{item.name} could carry customer content or a person "
                f"({sorted(leaked)}). Reading a workspace's activity needs the "
                f"consent-gated support session in md/15 §5.2, not an operations screen."
            )

    @pytest.mark.parametrize("model", MODELS, ids=lambda item: item.__name__)
    def test_every_field_is_a_count_an_age_or_a_closed_category(self, model: type) -> None:
        """A type check, because a name check alone is beatable.

        `status: str` passes any word list and holds anything at all.
        """
        for item in dataclasses.fields(model):
            annotation = str(item.type)
            assert annotation in ALLOWED_FIELD_TYPES, (
                f"{model.__name__}.{item.name} is {annotation!r}, which is not a count, "
                f"an age, a flag or a closed-set category"
            )

    def test_every_free_text_field_may_only_hold_a_constant(self) -> None:
        """The only `str` fields on these models are the two "why not" reasons.

        They exist because "no number" needs a reason, and each is the obvious
        place for somebody to put a provider's error body during an incident —
        which for Slack and Chat quotes channel names, space names and message
        fragments. Constraining their values to module constants is what stops
        that being a judgement call at 3am, and the exhaustive mapping is what
        stops a third free-text field arriving without one.
        """
        reason_fields = {
            item.name
            for model in MODELS
            for item in dataclasses.fields(model)
            if str(item.type) == "str | None"
        }
        assert reason_fields == set(REASON_FIELDS)

        assert connectors.NO_DELIVERY_RECORD in connectors.DELIVERY_UNOBSERVABLE_REASONS
        assert connectors.NO_SUBSCRIPTION_RECORD in connectors.SUBSCRIPTION_UNOBSERVABLE_REASONS

    def test_the_categories_are_the_ones_the_column_already_closed(self) -> None:
        """Reused from `db/connector_models.py`, not restated.

        A parallel enum here would be a second answer to "is this connection
        working", which is the duplication `source_connections` was created to
        remove — and the two would diverge at the first provider that reported
        something neither list had.
        """
        from cairn_api.db import connector_models

        assert connectors.ConnectorErrorCategory is connector_models.ConnectorErrorCategory
        assert connectors.ConnectionState is connector_models.ConnectionState
        assert connectors.ConnectionHealth is connector_models.ConnectionHealth
        assert connectors.ConnectorProvider is connector_models.ConnectorProvider

    def test_the_three_indistinguishable_causes_are_separate_categories(self) -> None:
        """The runbook's central distinction, pinned in code.

        "The customer disconnected it", "our credentials expired" and "the
        provider is down" all look identical from a screen showing zero events,
        and they have completely different responses: contact the customer,
        re-issue a key, or wait. Collapsing any two is how an operator re-issues
        credentials for an integration somebody deliberately removed.
        """
        categories = connectors.ConnectorErrorCategory
        states = connectors.ConnectionState

        ours = {categories.AUTHENTICATION_EXPIRED, categories.PERMISSION_REVOKED}
        theirs = {categories.PROVIDER_UNAVAILABLE, categories.RATE_LIMITED}
        customer = {states.DISCONNECTED, states.REVOKED}

        assert not ours & theirs
        assert len(ours) == len(theirs) == len(customer) == 2

    def test_a_customer_turning_a_source_off_is_not_counted_as_an_error(self) -> None:
        """`workspaces_in_error` reads the `error` state and nothing else.

        A workspace that disconnected is not an outage. Counting it as one
        produces the page that sends somebody to re-issue credentials for an
        integration that was removed on purpose — the single worst response
        available, because it is an attempt to restore access that was withdrawn.
        """
        health = connectors.ConnectorHealth(
            provider=connectors.ConnectorProvider.SLACK,
            credentials_configured=True,
            workspaces_by_state={
                ConnectionState.CONNECTED.value: 4,
                ConnectionState.DISCONNECTED.value: 3,
                ConnectionState.REVOKED.value: 2,
                ConnectionState.ERROR.value: 1,
            },
        )

        assert health.workspaces_in_error == 1

    def test_disconnected_and_revoked_are_outside_the_live_states(self) -> None:
        """Which is what keeps them out of the health and error breakdowns."""
        assert ConnectionState.DISCONNECTED not in connectors.LIVE_STATES
        assert ConnectionState.REVOKED not in connectors.LIVE_STATES
        assert ConnectionState.CONNECTED in connectors.LIVE_STATES


def _public_properties(model: type) -> list[str]:
    """Every derived reading a caller can get off a model.

    Properties are not `dataclasses.fields`, so the two structural tests above
    do not see them — and a property is the easiest place to reintroduce exactly
    what those tests forbid, because it needs no migration, no column and no
    schema change. `limits`, `throttled_workspaces` and the Slack event-budget
    readings all arrived as properties in Step 32.
    """
    return [
        name
        for name in dir(model)
        if not name.startswith("_") and isinstance(getattr(model, name, None), property)
    ]


class TestSlackNeededNoChangeToTheReadModel:
    """Step 31 claimed this read model was provider-neutral. Step 32 checks.

    The claim was that Slack would appear through `source_connections` with no
    new field, no new query and no new enum — that this was a connector screen
    rather than a GitHub screen with two empty rows bolted on. A claim like that
    is worth nothing unless something fails when it stops being true, so the
    field list is pinned exactly.
    """

    def test_slack_added_no_field_to_the_read_model(self) -> None:
        """The exact field list from Step 31, unchanged by Slack's arrival.

        If a future provider needs a field here, this fails and the question
        gets asked out loud: is this a count, an age or a category — or is it
        the first piece of a provider's payload arriving on an operations
        screen?
        """
        assert [item.name for item in dataclasses.fields(connectors.ConnectorHealth)] == [
            "provider",
            "credentials_configured",
            "workspaces_connected",
            "workspaces_ever_synced",
            "workspaces_by_state",
            "workspaces_by_health",
            "errors_by_category",
            "oldest_unsuccessful_sync_minutes",
            "deliveries_last_hour",
            "failures_last_hour",
            "deliveries_total",
            "deliveries_unobservable_reason",
        ]

    def test_slack_is_a_row_like_any_other(self) -> None:
        """No branch, no special case: one entry in `PROVIDERS`."""
        assert connectors.spec(connectors.ConnectorProvider.SLACK).provider is (
            connectors.ConnectorProvider.SLACK
        )
        assert connectors.ConnectorProvider.SLACK in {
            item.provider for item in connectors.PROVIDERS
        }

    @pytest.mark.parametrize("model", MODELS, ids=lambda item: item.__name__)
    def test_no_derived_reading_carries_content_or_a_person_either(self, model: type) -> None:
        """The same word list as the fields, applied to the properties.

        Adding a property is the cheap way around a test that only reads
        `dataclasses.fields`, and "just expose the last channel we heard from so
        support can see what is wrong" is a one-line property.
        """
        for name in _public_properties(model):
            if name in EXEMPT_FIELDS:
                continue
            words = {part.removesuffix("s") for part in name.lower().split("_")}
            leaked = words & {word.removesuffix("s") for word in FORBIDDEN_FIELD_WORDS}
            assert not leaked, (
                f"{model.__name__}.{name} could carry customer content or a person "
                f"({sorted(leaked)})"
            )

    def test_the_slack_limits_are_the_published_ones(self) -> None:
        """Constants from Slack's documentation, recorded once.

        Written down in code so that the runbook, the alert threshold and the
        acknowledgement budget cannot drift apart — three copies of "3 seconds"
        in three documents is two of them going stale.
        """
        limits = connectors.SLACK_LIMITS

        assert limits.ack_deadline_seconds == 3.0
        assert limits.retry_attempts == 3
        assert limits.retry_backoff_minutes == (0, 1, 5)
        assert limits.events_per_hour == 30_000
        assert limits.alert_events_per_hour == 24_000

    def test_slack_throttling_is_recorded_as_permanent_data_loss(self) -> None:
        """The fact that makes Slack unlike every other failure here.

        Beyond 30,000 events per workspace per hour Slack **discards** events.
        They are not queued and not redelivered, and because CAIRN requests no
        history scope nothing can go back for them. So a throttled Slack
        workspace is not a delay to wait out — it is a hole in that customer's
        record, and the two need different responses.
        """
        slack = connectors.ConnectorHealth(
            provider=connectors.ConnectorProvider.SLACK, credentials_configured=True
        )
        github = connectors.ConnectorHealth(
            provider=connectors.ConnectorProvider.GITHUB, credentials_configured=True
        )

        assert connectors.SLACK_LIMITS.events_dropped_when_exceeded is True
        assert connectors.SLACK_LIMITS.events_redelivered_after_drop is False
        assert slack.drops_events_when_throttled is True
        assert github.drops_events_when_throttled is False

    def test_the_event_budget_is_a_ceiling_and_not_a_reading(self) -> None:
        """A published number to compare against by hand, never an estimate.

        Slack's ceiling is per workspace per hour; every count on this model is
        platform-wide, and Slack has no durable inbound record at all. A gauge
        derived from a platform-wide total would read 3% while one workspace sat
        at 100% and lost a morning of decisions — worse than an empty panel,
        because somebody would trust it. So there is no fraction property, and
        this test is the reason there is not.
        """
        slack = connectors.ConnectorHealth(
            provider=connectors.ConnectorProvider.SLACK, credentials_configured=True
        )

        assert slack.event_budget_per_hour == 30_000
        assert slack.event_budget_alert_at == 24_000
        assert not [name for name in _public_properties(type(slack)) if "fraction" in name]

    def test_a_throttled_workspace_is_counted_from_the_error_category(self) -> None:
        """`app_rate_limited` reduces to `rate_limited`, like every other
        failure. Slack's payload carries `team_id` and `minute_rate_limited`;
        neither reaches this model."""
        slack = connectors.ConnectorHealth(
            provider=connectors.ConnectorProvider.SLACK,
            credentials_configured=True,
            errors_by_category={connectors.ConnectorErrorCategory.RATE_LIMITED.value: 2},
        )

        assert slack.throttled_workspaces == 2


class TestGoogleChatNeededNoChangeToTheReadModel:
    """Step 33 asks the same question of Google Chat that Step 32 asked of Slack.

    The answer is the same: `ConnectorHealth` did not change. Chat writes
    `source_connections` like every other provider, so its row is produced,
    counted and reported as configured-but-unverified with no new field, query or
    enum. The field list is pinned again rather than assumed, because "it was
    provider-neutral last time" is not evidence.

    What Chat *does* add is a second aggregate, and the reason it is separate is
    structural rather than stylistic: a Chat subscription is a lease **per
    space** with a four-hour life, and `source_connections` has one row per
    connection. Folding N leases into one connection row would mean either a
    per-space breakdown — forbidden — or an average that hides the one lease that
    died.
    """

    def test_google_chat_added_no_field_to_the_read_model(self) -> None:
        """The exact field list from Step 31, unchanged by two chat providers."""
        assert [item.name for item in dataclasses.fields(connectors.ConnectorHealth)] == [
            "provider",
            "credentials_configured",
            "workspaces_connected",
            "workspaces_ever_synced",
            "workspaces_by_state",
            "workspaces_by_health",
            "errors_by_category",
            "oldest_unsuccessful_sync_minutes",
            "deliveries_last_hour",
            "failures_last_hour",
            "deliveries_total",
            "deliveries_unobservable_reason",
        ]

    def test_google_chat_is_a_row_like_any_other(self) -> None:
        """No branch, no special case: one entry in `PROVIDERS`."""
        assert connectors.spec(connectors.ConnectorProvider.GOOGLE_CHAT).provider is (
            connectors.ConnectorProvider.GOOGLE_CHAT
        )
        assert connectors.ConnectorProvider.GOOGLE_CHAT in {
            item.provider for item in connectors.PROVIDERS
        }

    def test_a_subscription_record_has_nowhere_to_put_a_space(self) -> None:
        """The input type to the aggregate, pinned exactly.

        This is the one place a space identifier would plausibly arrive: the
        caller building these records holds the space name, the space id and the
        subscription name, and passing one through "so support can see which
        space is broken" is a one-word edit. Pinning the field list means that
        edit fails a test instead of shipping.
        """
        assert [item.name for item in dataclasses.fields(connectors.SubscriptionRecord)] == [
            "state",
            "suspension_category",
            "expires_at",
        ]

    def test_the_subscription_categories_are_the_ones_the_column_already_closed(self) -> None:
        """Reused from `db/gchat_models.py`, not restated.

        A parallel lifecycle enum here would be a second answer to "is this
        subscription working", and the two would diverge at the first state
        Google added — with the renewal loop reading one and the operator's
        screen reading the other.
        """
        from cairn_api.db import gchat_models

        assert connectors.GoogleChatSubscriptionState is gchat_models.GoogleChatSubscriptionState

    def test_the_aggregate_reports_counts_and_one_age(self) -> None:
        """Live, suspended, expired and the nearest expiry — nothing else."""
        now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
        states = connectors.GoogleChatSubscriptionState
        records = [
            connectors.SubscriptionRecord(state=states.ACTIVE, expires_at=now + timedelta(hours=3)),
            connectors.SubscriptionRecord(
                state=states.ACTIVE, expires_at=now + timedelta(minutes=45)
            ),
            connectors.SubscriptionRecord(
                state=states.SUSPENDED,
                suspension_category=connectors.ConnectorErrorCategory.CONFIGURATION_INVALID,
            ),
            connectors.SubscriptionRecord(state=states.EXPIRED),
        ]

        health = connectors.subscription_health(records, expected=6, now=now)

        assert health.subscriptions_live == 2
        assert health.subscriptions_suspended == 1
        assert health.subscriptions_expired == 1
        assert health.nearest_expiry_minutes == 45
        assert health.subscriptions_by_error_category == {"configuration_invalid": 1}
        assert health.observable is True

    def test_a_lease_that_no_longer_exists_is_counted_as_missing(self) -> None:
        """The number this aggregate exists for.

        An expired Chat subscription is **deleted**, not renewed, so the live
        count falls below the number of selected spaces while the connection
        still reads `connected` and every credential check passes. Nothing else
        on any screen in this product moves when that happens.
        """
        health = connectors.subscription_health(
            [connectors.SubscriptionRecord(state=connectors.GoogleChatSubscriptionState.ACTIVE)],
            expected=4,
        )

        assert health.subscriptions_missing == 3
        assert health.expiry_is_permanent_loss is True

    def test_nothing_stored_reports_a_reason_rather_than_zero(self) -> None:
        """The `slo.py` rule, applied to a store whose migration has not landed.

        "0 suspended, 0 expired" reads as a healthy renewal loop, and there is no
        renewal loop to read. Empty breakdowns with a reason are the honest
        state — and `subscriptions_missing` is `None` rather than the number of
        selected spaces, which would page somebody about leases nobody has looked
        for yet.
        """
        health = connectors.subscription_health(None, expected=9)

        assert health.subscriptions_by_state == {}
        assert health.subscriptions_by_error_category == {}
        assert health.subscriptions_missing is None
        assert health.observable is False
        assert (
            health.subscriptions_unobservable_reason in connectors.SUBSCRIPTION_UNOBSERVABLE_REASONS
        )

    def test_only_a_live_lease_counts_towards_the_nearest_expiry(self) -> None:
        """A suspended lease is already not delivering and an expired one is
        already gone. Counting either would make the nearest-expiry number
        *improve* at the moment a subscription died."""
        now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
        states = connectors.GoogleChatSubscriptionState
        health = connectors.subscription_health(
            [
                connectors.SubscriptionRecord(
                    state=states.SUSPENDED,
                    suspension_category=connectors.ConnectorErrorCategory.UNKNOWN,
                    expires_at=now + timedelta(minutes=5),
                ),
                connectors.SubscriptionRecord(
                    state=states.ACTIVE, expires_at=now + timedelta(hours=2)
                ),
            ],
            now=now,
        )

        assert health.nearest_expiry_minutes == 120
        assert health.renewal_due_within_minutes == 0

    def test_the_lease_is_four_hours_and_renewal_is_forever(self) -> None:
        """Four hours with `includeResource: true` and no domain-wide delegation.

        Twelve renewals per selected space per day, in every customer, for as
        long as the connector exists. That is the connector's steady-state load
        and the reason renewals must be staggered rather than swept by one cron.
        """
        limits = connectors.GOOGLE_CHAT_SUBSCRIPTION

        assert limits.ttl_hours == 4.0
        assert limits.renew_after_hours == 2.0
        assert limits.renewals_per_subscription_per_day == 12
        assert limits.request_rate_limits_published is False

    def test_the_seven_day_lease_is_recorded_with_what_it_costs(self) -> None:
        """`includeResource: false` buys a seven-day lease and a harder wall.

        Every message then costs a `spaces.messages.get` against 3,000 reads per
        **project** per 60 seconds — shared by every tenant on that Cloud
        project, so one busy customer throttles all of them. CAIRN took the
        four-hour lease and renews; the trade is recorded so the next person to
        notice the renewal loop does not "simplify" it.
        """
        limits = connectors.GOOGLE_CHAT_SUBSCRIPTION

        assert limits.ttl_hours_without_resource == 168.0
        assert limits.reads_per_project_per_minute == 3_000
        assert limits.ttl_hours < limits.ttl_hours_without_resource

    def test_the_expiration_reminder_cannot_arrive_in_time(self) -> None:
        """Google documents a reminder 12 hours before expiry. The lease is 4
        hours long, so the reminder would have to precede the subscription.

        Google's own guidance is to track `expireTime` and renew, and this test
        exists so that a renewal loop built on the reminder fails here rather
        than in a customer's account.
        """
        limits = connectors.GOOGLE_CHAT_SUBSCRIPTION

        assert limits.documented_expiration_reminder_lead_hours == 12.0
        assert limits.expiration_reminder_is_reachable is False

    def test_an_expired_lease_is_a_gap_rather_than_a_delay(self) -> None:
        """It is deleted permanently and cannot be renewed — only recreated.

        A renewal loop that only knows how to renew will retry forever against a
        subscription that no longer exists, and the events published for that
        space in the meantime were never delivered anywhere.
        """
        assert connectors.GOOGLE_CHAT_SUBSCRIPTION.expired_subscription_is_recoverable is False
        assert connectors.subscription_health(None).expiry_is_permanent_loss is True

    def test_how_long_a_suspended_lease_stays_reactivatable_is_unknown(self) -> None:
        """`subscriptions.reactivate` exists; the window is undocumented.

        `None` records the absence of an answer rather than a guess, which is the
        same rule the delivery counts follow. The operational consequence is to
        reactivate promptly rather than queue it.
        """
        assert connectors.GOOGLE_CHAT_SUBSCRIPTION.reactivation_window_hours is None

    def test_the_publisher_principal_is_not_confirmed(self) -> None:
        """Google names `chat-api-push@system.gserviceaccount.com` for Chat
        *interaction* events and does not say whether Workspace-Events-for-Chat
        publishes as the same principal.

        Granting the wrong one surfaces as an `ENDPOINT_PERMISSION_DENIED`
        suspension rather than as a configuration error, which is why it is
        recorded as unconfirmed rather than written into a setup guide as fact.
        """
        assert connectors.GOOGLE_CHAT_SUBSCRIPTION.publisher_principal_confirmed is False

    def test_the_seven_day_refresh_token_trap_is_recorded(self) -> None:
        """While the consent screen is in "Testing" with external user type,
        refresh tokens expire after 7 days and every customer connection breaks
        weekly. The 101st token per account per client id silently invalidates
        the oldest, with no error anywhere."""
        limits = connectors.GOOGLE_CHAT_SUBSCRIPTION

        assert limits.refresh_token_days_while_testing == 7
        assert limits.refresh_tokens_per_account_per_client == 100

    def test_a_personal_account_cannot_authorise_the_connector(self) -> None:
        """The authorising user must belong to a Workspace organisation. Every
        configuration check passes for a personal Gmail account, which makes this
        an onboarding qualification rather than a support ticket."""
        assert connectors.GOOGLE_CHAT_SUBSCRIPTION.personal_accounts_can_authorise is False

    def test_the_push_ack_deadline_is_also_the_request_timeout(self) -> None:
        """Default 10 seconds, raisable to 600, and not extendable per message —
        push has no `modifyAckDeadline`. Delivery is at-least-once; exactly-once
        is pull-only, so every handler must be idempotent."""
        limits = connectors.GOOGLE_CHAT_LIMITS

        assert limits.ack_deadline_seconds == 10.0
        assert limits.ack_deadline_max_seconds == 600.0
        assert limits.ack_deadline_extendable_per_delivery is False
        assert limits.delivers_at_least_once is True
        assert limits.retry_backoff_seconds_range == (0.1, 60.0)

    def test_pubsub_retries_have_no_fixed_count(self) -> None:
        """Slack retries three times; Pub/Sub redelivers until retention expires.

        `None` rather than an invented integer, for the reason the delivery counts
        report `None` rather than zero: a number here would be read as a number.
        """
        assert connectors.GOOGLE_CHAT_LIMITS.retry_attempts is None
        assert connectors.SLACK_LIMITS.retry_attempts == 3

    def test_the_restricted_scope_is_recorded_as_the_launch_blocker(self) -> None:
        """`chat.messages.readonly` is RESTRICTED: verification plus an
        independent third-party CASA assessment, re-taken at least every 12
        months. There is no lower-tier read-only Chat message scope.

        `chat.spaces.readonly` is SENSITIVE — verification, no third party — and
        the two are kept apart because conflating them makes the assessment look
        optional.
        """
        scopes = {item.name: item for item in connectors.GOOGLE_CHAT_SCOPES}

        assert scopes["chat.messages.readonly"].tier is connectors.ScopeTier.RESTRICTED
        assert scopes["chat.messages.readonly"].requires_security_assessment is True
        assert scopes["chat.spaces.readonly"].tier is connectors.ScopeTier.SENSITIVE
        assert scopes["chat.spaces.readonly"].requires_security_assessment is False
        assert connectors.RESTRICTED_SCOPE_REVERIFICATION_MONTHS == 12

    def test_every_suspension_reason_reduces_to_a_category(self) -> None:
        """Total over Google's published set, so a reason cannot arrive unmapped.

        The mapping is also why this connector needs no new telemetry attribute:
        `suspension_reason` is not on the allow-list and does not have to be.
        """
        assert set(connectors.SUSPENSION_REASON_CATEGORY) == set(connectors.SuspensionReason)
        for reason, category in connectors.SUSPENSION_REASON_CATEGORY.items():
            assert isinstance(category, connectors.ConnectorErrorCategory), reason

    def test_the_suspension_reasons_keep_ours_and_theirs_apart(self) -> None:
        """Three families with nothing in common but the word "suspended".

        The customer withdrew a grant, our credential failed, or our endpoint is
        wrong. A single "suspended" count sends somebody to re-authorise a
        customer who deliberately removed us — the one response that must never
        follow.
        """
        mapping = connectors.SUSPENSION_REASON_CATEGORY
        reasons = connectors.SuspensionReason
        categories = connectors.ConnectorErrorCategory

        assert mapping[reasons.USER_SCOPE_REVOKED] is categories.PERMISSION_REVOKED
        assert mapping[reasons.APP_SCOPE_REVOKED] is categories.PERMISSION_REVOKED
        assert mapping[reasons.USER_AUTHORIZATION_FAILURE] is categories.AUTHENTICATION_EXPIRED
        assert mapping[reasons.RESOURCE_DELETED] is categories.CONFIGURATION_INVALID
        assert mapping[reasons.ENDPOINT_PERMISSION_DENIED] is categories.CONFIGURATION_INVALID
        assert mapping[reasons.ENDPOINT_NOT_FOUND] is categories.CONFIGURATION_INVALID
        assert mapping[reasons.ENDPOINT_RESOURCE_EXHAUSTED] is categories.RATE_LIMITED
        assert mapping[reasons.OTHER] is categories.UNKNOWN

    def test_google_chat_is_not_the_provider_that_drops_events_when_throttled(self) -> None:
        """Slack's ceiling discards events; Chat's loss mode is a lapsed lease.

        Recorded as different questions because the responses differ — one is a
        rate limit to alert on, the other is a renewal loop to fix — and because
        reusing Slack's flag would put Chat's real failure mode under a label
        that does not describe it.
        """
        chat = connectors.ConnectorHealth(
            provider=connectors.ConnectorProvider.GOOGLE_CHAT, credentials_configured=True
        )

        assert chat.drops_events_when_throttled is False
        assert chat.event_budget_per_hour is None
        assert connectors.subscription_health(None).expiry_is_permanent_loss is True


class TestNoMetricMeasuresAPerson:
    """A product boundary, not a preference (md/05 §B.2).

    Structural, in the same style as `test_slo.py`, because the failure arrives
    as a well-intentioned addition: "messages per person" is the first thing
    anybody who has run a support team asks a chat connector for, and it is
    exactly what CAIRN promises never to produce.
    """

    def test_nothing_in_the_module_counts_smaller_than_a_workspace(self) -> None:
        """Workspaces and events. Never channels, never accounts, never people.

        A per-channel count is a per-team productivity metric with a different
        label; a per-account count is the forbidden one outright.
        """
        forbidden = (
            "per_person",
            "per_user",
            "per_member",
            "per_channel",
            "per_space",
            "per_account",
            "by_person",
            "by_user",
            "by_channel",
            "by_author",
            "productivity",
            "activity_score",
            "responsiveness",
            "leaderboard",
            "top_",
        )
        for name in dir(connectors):
            if name.startswith("__"):
                continue
            lowered = name.lower()
            for word in forbidden:
                assert word not in lowered, f"connectors.{name} measures people: {word!r}"

    def test_the_counted_units_are_workspaces_and_deliveries_only(self) -> None:
        """The positive half. Every count says what it counts, and there are two
        nouns."""
        counts = [
            item.name
            for item in dataclasses.fields(connectors.ConnectorHealth)
            if str(item.type) in {"int", "int | None"}
        ]
        assert counts == [
            "workspaces_connected",
            "workspaces_ever_synced",
            "deliveries_last_hour",
            "failures_last_hour",
            "deliveries_total",
        ]

    def test_the_metrics_carry_only_allow_listed_attributes(self) -> None:
        """The counters leave the product, to an exporter with its own retention
        and its own readers.

        Captured from the instrument rather than read from the call site, so a
        second attribute added anywhere fails here.
        """
        captured: list[dict[str, Any]] = []

        class _Recording:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append(attributes or {})

        original_deliveries = connectors.connector_deliveries
        original_errors = connectors.connector_errors
        connectors.connector_deliveries = _Recording()  # type: ignore[assignment]
        connectors.connector_errors = _Recording()  # type: ignore[assignment]
        try:
            connectors.record_connector_delivery(
                source=connectors.ConnectorProvider.SLACK, outcome="processed"
            )
            connectors.record_connector_error(
                source=connectors.ConnectorProvider.SLACK,
                category=connectors.ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
            )
        finally:
            connectors.connector_deliveries = original_deliveries
            connectors.connector_errors = original_errors

        assert captured == [
            {"source": "slack", "outcome": "processed"},
            {"source": "slack", "error_category": "authentication_expired"},
        ]
        for attributes in captured:
            assert set(attributes) <= ALLOWED

    def test_a_workspace_is_the_smallest_thing_a_metric_may_be_grouped_by(self) -> None:
        """`tenant_id` is the floor, and it is the floor for a reason.

        Slack's inbound ceiling is per workspace per hour, so a platform-wide
        total cannot warn anybody they are about to lose data — one busy
        workspace hits 30,000 while the fleet total looks calm. A workspace is a
        customer, not a person. Nothing finer is offered here, and nothing finer
        could be: the allow-list has no channel, conversation or account entry.
        """
        captured: list[dict[str, Any]] = []

        class _Recording:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append(attributes or {})

        tenant = uuid.uuid4()
        original = connectors.connector_deliveries
        connectors.connector_deliveries = _Recording()  # type: ignore[assignment]
        try:
            connectors.record_connector_delivery(
                source=connectors.ConnectorProvider.SLACK, outcome="accepted", tenant_id=tenant
            )
        finally:
            connectors.connector_deliveries = original

        assert captured == [{"source": "slack", "outcome": "accepted", "tenant_id": str(tenant)}]
        assert set(captured[0]) <= ALLOWED

    def test_a_dropped_event_window_is_counted_without_the_workspace_slack_names(self) -> None:
        """`app_rate_limited` carries `team_id` and `minute_rate_limited`.

        Neither reaches telemetry. `team_id` is Slack's identifier for a
        customer, not CAIRN's, and exporting a provider's own workspace id names
        a customer in a system with its own retention and its own readers. The
        window is also recorded as an ordinary `rate_limited` error, so the
        existing alert still fires — counted separately so that "we were
        throttled" and "we permanently lost events" are not one number.
        """
        captured: list[tuple[str, dict[str, Any]]] = []

        class _Recording:
            def __init__(self, label: str) -> None:
                self.label = label

            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append((self.label, attributes or {}))

        original_windows = connectors.connector_rate_limit_windows
        original_errors = connectors.connector_errors
        connectors.connector_rate_limit_windows = _Recording("windows")  # type: ignore[assignment]
        connectors.connector_errors = _Recording("errors")  # type: ignore[assignment]
        try:
            connectors.record_connector_rate_limited(source=connectors.ConnectorProvider.SLACK)
        finally:
            connectors.connector_rate_limit_windows = original_windows
            connectors.connector_errors = original_errors

        assert captured == [
            ("windows", {"source": "slack"}),
            ("errors", {"source": "slack", "error_category": "rate_limited"}),
        ]
        for _, attributes in captured:
            assert set(attributes) <= ALLOWED
            assert "team_id" not in attributes
            assert "minute_rate_limited" not in attributes

    def test_a_renewal_is_counted_without_naming_the_lease(self) -> None:
        """Twelve renewals per selected space per day is the highest-frequency
        machine work in this connector, and the only early warning that the
        renewal loop is failing — a failed renewal is recoverable, a lapsed lease
        is not.

        A subscription names a space, so nothing identifying the lease is
        exported: `source` and `outcome`, as with every other connector counter.
        """
        captured: list[dict[str, Any]] = []

        class _Recording:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append(attributes or {})

        original = connectors.connector_subscription_renewals
        connectors.connector_subscription_renewals = _Recording()  # type: ignore[assignment]
        try:
            connectors.record_subscription_renewal(
                source=connectors.ConnectorProvider.GOOGLE_CHAT, outcome="processed"
            )
        finally:
            connectors.connector_subscription_renewals = original

        assert captured == [{"source": "google_chat", "outcome": "processed"}]
        assert set(captured[0]) <= ALLOWED

    def test_a_suspension_reaches_telemetry_as_a_category_not_a_reason(self) -> None:
        """`suspension_reason` is not on the telemetry allow-list, and does not
        need to be.

        Google's reason is a closed set and would be safe to export, but adding
        an attribute is an edit to a file this module does not own — so every
        reason is reduced to a `ConnectorErrorCategory` the exporter already
        accepts, and the full reason stays inside the product on the subscription
        aggregate. The alert fires either way.
        """
        captured: list[dict[str, Any]] = []

        class _Recording:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append(attributes or {})

        original = connectors.connector_errors
        connectors.connector_errors = _Recording()  # type: ignore[assignment]
        try:
            connectors.record_subscription_suspended(
                source=connectors.ConnectorProvider.GOOGLE_CHAT,
                reason=connectors.SuspensionReason.USER_SCOPE_REVOKED,
            )
        finally:
            connectors.connector_errors = original

        assert captured == [{"source": "google_chat", "error_category": "permission_revoked"}]
        assert "suspension_reason" not in ALLOWED
        for attributes in captured:
            assert set(attributes) <= ALLOWED

    def test_a_source_can_only_be_a_known_provider(self) -> None:
        """`source` is the one identifier the metrics carry. Typed as the enum,
        so it cannot become a workspace, an account or a channel."""
        assert set(connectors.ConnectorProvider) == {
            connectors.ConnectorProvider.GITHUB,
            connectors.ConnectorProvider.SLACK,
            connectors.ConnectorProvider.GOOGLE_CHAT,
        }


# --------------------------------------------------------------------------
# The release gate
# --------------------------------------------------------------------------


DEPLOYED: dict[str, object] = {
    "environment": "production",
    "database_url": "postgresql+asyncpg://cairn_app:s@10.0.0.4:5432/cairn",
    "platform_database_url": "postgresql+asyncpg://cairn:s@10.0.0.4:5432/cairn",
    "cors_allowed_origins": ("https://app.example.com",),
    "github_webhook_secret": "a-real-secret",
    "email_backend": "smtp",
    "smtp_host": "relay.example.com",
    "connector_encryption_key": "hZ6vX0nQq3rTt7pS5yWm2cJ8bK4dL1fA9gN0eR6uZ3s=",
}


#: Slack credentials, present and unproven — the state this gate exists for.
#:
#: Real `Settings` fields now that Step 32's OAuth half has landed them, so this
#: is a plain dictionary rather than the subclass shim it used to be.
#: `slack_redirect_uri` is https because a deployed `Settings` refuses anything
#: else: the install code arrives on that URL and is exchangeable for a
#: workspace's bot token by whoever sees it first.
SLACK_CONFIGURED: dict[str, object] = {
    "slack_client_id": "A0000000000",
    "slack_client_secret": "not-a-real-secret",
    "slack_signing_secret": "not-a-real-secret",
    "slack_redirect_uri": "https://app.example.com/v1/integrations/slack/callback",
}


def configured_slack(**overrides: object) -> Settings:
    """A deployed environment with Slack credentials set and nothing proven."""
    return Settings.model_validate({**DEPLOYED, **SLACK_CONFIGURED, **overrides})


class GoogleChatSettings(Settings):
    """`Settings` with the two fields Google Chat's OAuth half will add.

    A subclass rather than a dictionary because `Settings` is configured with
    `extra="ignore"`: passing `google_chat_project_id` to `model_validate` today
    is silently dropped, and a test built on that would assert against a provider
    that is not configured while appearing to assert the opposite.

    `ops/connectors.py` reads these with `getattr(..., None)` for the same
    reason — `config.py` is another engineer's file and the fields land there in
    the OAuth half of Step 33.
    """

    google_chat_project_id: str = ""
    google_chat_service_account: str = ""


def configured_google_chat(**overrides: object) -> Settings:
    """A deployed environment with Chat credentials set and nothing proven."""
    return GoogleChatSettings.model_validate(
        {
            **DEPLOYED,
            "google_chat_project_id": "cairn-chat-prod",
            "google_chat_service_account": "cairn-chat@cairn-chat-prod.iam.gserviceaccount.com",
            **overrides,
        }
    )


def connector_gate(settings: Settings) -> Any:
    return next(item for item in evaluate_release_gates(settings) if item.name == "connectors")


class TestTheConnectorGateNeverClaimsMoreThanEvidence:
    def test_configured_credentials_are_manual_never_passed(self) -> None:
        """The assertion this gate exists for.

        A Slack signing secret in an environment variable proves somebody set a
        variable. It does not prove the app is installed on a workspace, that
        the scopes asked for were granted, or that one event has ever arrived.
        Reporting that as `passed` is how a release gets signed off on the
        strength of a `.env` file.
        """
        gate = connector_gate(configured_slack())

        # `is not PASSED` is deliberately absent: mypy narrows `status` to
        # UNVERIFIED on the line above and rejects the comparison as one that
        # can never be true. `blocks_release` asserts the same property without
        # asking the type checker to doubt what it just proved.
        assert gate.status is GateStatus.UNVERIFIED
        assert gate.blocks_release

    def test_passed_is_unreachable_whatever_the_configuration(self) -> None:
        """Not an accident of the current branches.

        Every input the gate has is configuration; none of them is a delivery.
        If a future change makes `PASSED` reachable, the gate has started
        treating configuration as proof and this fails.
        """
        for settings in (
            Settings(),
            Settings.model_validate(DEPLOYED),
            configured_slack(),
            configured_slack(github_app_id="12345"),
        ):
            gate = connector_gate(settings)
            assert gate.status is not GateStatus.PASSED, gate.detail

    def test_an_unconfigured_environment_blocks_and_names_the_variables(self) -> None:
        gate = connector_gate(Settings())

        assert gate.status is GateStatus.BLOCKED
        assert "CAIRN_SLACK_CLIENT_ID" in gate.next_step
        assert "CAIRN_GOOGLE_CHAT_PROJECT_ID" in gate.next_step

    def test_the_next_step_names_the_check_rather_than_performing_it(self) -> None:
        """Nothing in `release_gates.py` calls a network. The remedy is a
        sentence an operator can follow, which is what makes `MANUAL` different
        from `BLOCK` rather than a softer word for it."""
        gate = connector_gate(configured_slack())

        assert "operations/connectors" in gate.next_step
        assert "inboundVerified" in gate.next_step

    def test_the_slack_manual_step_starts_with_the_bot_invitation(self) -> None:
        """The first thing that is wrong, named first.

        "The scopes look right but no events arrive" is almost always a bot that
        was never invited to the channel. CAIRN does not request
        `channels:join`, so an uninvited bot receives nothing at all — and every
        configuration check passes in that state, which is precisely why a
        configuration-only gate must not call it `passed`.
        """
        gate = connector_gate(configured_slack())

        assert gate.status is GateStatus.UNVERIFIED
        assert "invite" in gate.next_step
        assert "channels:join" in gate.next_step
        assert gate.next_step.index("invite") < gate.next_step.index("operations/connectors")

    def test_it_does_not_ask_for_a_delivery_count_slack_cannot_produce(self) -> None:
        """Slack has no durable inbound record, so `deliveriesLastHour` is
        `null` for it forever. A next step that told an operator to wait for it
        to rise above zero would be a check that can never succeed."""
        gate = connector_gate(configured_slack())

        assert "deliveriesLastHour" not in gate.next_step
        assert "inboundVerified" in gate.next_step

    def test_github_alone_does_not_satisfy_it(self) -> None:
        """The gate is about chat sources. A configured GitHub App says nothing
        about whether a decision made in Slack can reach a brief."""
        gate = connector_gate(
            Settings.model_validate(
                {**DEPLOYED, "github_app_id": "12345", "github_private_key": "not-a-real-key"}
            )
        )

        assert gate.status is GateStatus.BLOCKED

    def test_missing_credentials_are_named_one_by_one(self) -> None:
        """So "blocked" is a runbook rather than an observation."""
        missing = connectors.missing_credentials(
            connectors.ConnectorProvider.SLACK, Settings.model_validate(DEPLOYED)
        )

        assert missing == (
            "CAIRN_SLACK_CLIENT_ID",
            "CAIRN_SLACK_CLIENT_SECRET",
            "CAIRN_SLACK_SIGNING_SECRET",
        )
        assert (
            connectors.missing_credentials(connectors.ConnectorProvider.SLACK, configured_slack())
            == ()
        )


class TestTheGoogleChatGateNamesTheAssessment:
    """Configuration is never proof, and for Chat it is not even close.

    Two environment variables can be perfectly correct while the restricted-scope
    security assessment has not been *started* — an independent third-party
    review that runs weeks to months and gates the launch rather than the merge.
    A gate that reported "configured" without saying so would let a team finish
    the code, read a green-ish line, and discover the real blocker at launch.
    """

    def test_configured_credentials_are_manual_never_passed(self) -> None:
        gate = connector_gate(configured_google_chat())

        assert gate.status is GateStatus.UNVERIFIED
        assert gate.blocks_release
        assert "google_chat" in gate.detail

    def test_passed_stays_unreachable_with_chat_configured(self) -> None:
        """Every input the gate has is still configuration. None is a delivery."""
        for settings in (
            configured_google_chat(),
            configured_google_chat(**SLACK_CONFIGURED),
            configured_google_chat(github_app_id="12345"),
        ):
            assert connector_gate(settings).status is not GateStatus.PASSED

    def test_the_next_step_names_the_security_assessment(self) -> None:
        """The single largest blocker in the connector programme, stated in the
        gate rather than buried in a runbook.

        `chat.messages.readonly` is RESTRICTED: OAuth verification **plus** an
        independent third-party CASA assessment ending in a Letter of Assessment,
        re-taken at least every 12 months. There is no read-only Chat message
        scope that avoids the tier.
        """
        step = connector_gate(configured_google_chat()).next_step

        assert "security assessment" in step
        assert "RESTRICTED" in step
        assert "chat.messages.readonly" in step
        assert "12 months" in step

    def test_the_assessment_precedes_the_manual_check(self) -> None:
        """Order matters. An operator who reads "add the app to a space and post
        a message" first will do exactly that, watch it work, and conclude the
        connector is ready to launch — while the thing that actually gates the
        launch has not been started."""
        step = connector_gate(configured_google_chat()).next_step

        assert step.index("security assessment") < step.index("add the app to one space")

    def test_it_says_finished_code_does_not_clear_it(self) -> None:
        """A deployment that has not begun the assessment cannot ship this
        connector however complete the repository is, and the gate says so in
        those terms rather than implying it."""
        step = connector_gate(configured_google_chat()).next_step

        assert "cannot ship" in step
        assert "weeks to months" in step

    def test_the_seven_day_refresh_token_trap_is_in_the_gate(self) -> None:
        """Until the app is published and verified the consent screen stays in
        "Testing", where refresh tokens last 7 days. A connector that breaks
        every customer's connection weekly is not shippable, and the two facts
        are stated together because they have one cause."""
        step = connector_gate(configured_google_chat()).next_step

        assert "7 days" in step
        assert "Testing" in step

    def test_the_manual_check_starts_with_the_account_type(self) -> None:
        """A personal Gmail account cannot authorise this connector at all, and
        every configuration check passes in that state — the Chat equivalent of
        Slack's uninvited bot."""
        step = connector_gate(configured_google_chat()).next_step

        assert "Workspace organisation" in step
        assert step.index("Workspace organisation") < step.index("post one message")

    def test_an_unconfigured_environment_still_warns_about_the_assessment(self) -> None:
        """Started before the code, not after it. A blocked gate that names only
        the environment variables teaches a team to configure first and discover
        the months-long dependency last."""
        gate = connector_gate(Settings())

        assert gate.status is GateStatus.BLOCKED
        assert "security assessment" in gate.next_step
        assert "CAIRN_GOOGLE_CHAT_PROJECT_ID" in gate.next_step

    def test_slack_alone_does_not_drag_the_chat_blocker_in(self) -> None:
        """The blocker is composed from the configured providers, not branched
        on. A Slack-only deployment has no assessment to start and must not be
        told it does."""
        step = connector_gate(configured_slack()).next_step

        assert "security assessment" not in step
        assert "invite" in step

    def test_missing_chat_credentials_are_named_one_by_one(self) -> None:
        missing = connectors.missing_credentials(
            connectors.ConnectorProvider.GOOGLE_CHAT, Settings.model_validate(DEPLOYED)
        )

        assert missing == (
            "CAIRN_GOOGLE_CHAT_PROJECT_ID",
            "CAIRN_GOOGLE_CHAT_SERVICE_ACCOUNT",
        )
        assert (
            connectors.missing_credentials(
                connectors.ConnectorProvider.GOOGLE_CHAT, configured_google_chat()
            )
            == ()
        )


# --------------------------------------------------------------------------
# Staff-role gating
# --------------------------------------------------------------------------


class TestItIsMountedBehindTheSameRolesAsEveryOtherOperationsSurface:
    """`api/routers/internal.py` is another engineer's file.

    So this asserts the pattern the read model has to be mounted behind, and
    becomes a direct check on the route the moment it is added — which is the
    point at which forgetting the role would matter.
    """

    def test_the_operations_roles_are_engineering_and_security(self) -> None:
        """md/15 §6 gives pipeline health to Engineering; Security is included
        because an incident is when this data is most needed. Support and
        Billing Ops are excluded, and a connector screen is exactly the surface
        somebody would argue Support needs — least privilege applies internally
        too."""
        assert internal.OPERATIONS_ROLES == (StaffRole.ENGINEERING, StaffRole.SECURITY)

    def test_every_operations_route_declares_that_gate(self) -> None:
        """Walked from the router, so the connector route is covered the day it
        is mounted without anybody remembering to extend this test."""
        operations = [
            route
            for route in internal.router.routes
            if isinstance(route, APIRoute) and route.path.startswith("/internal/operations/")
        ]
        assert operations, "no operations routes found — the assertion below would be vacuous"

        for route in operations:
            declared = [
                dependency
                for dependency in route.dependant.dependencies
                if "requires_staff" in getattr(dependency.call, "__qualname__", "")
            ]
            assert declared, f"{route.path} has no staff-role requirement"

    def test_a_connector_route_may_only_be_mounted_as_an_operations_route(self) -> None:
        """Mounting it anywhere else on this router would give it a different
        role set. Vacuous until Step 32 mounts it, and stops being vacuous at
        exactly the moment it matters."""
        for route in internal.router.routes:
            if isinstance(route, APIRoute) and "connector" in route.path:
                assert route.path.startswith("/internal/operations/"), route.path


# --------------------------------------------------------------------------
# The numbers
# --------------------------------------------------------------------------


@pytest.fixture
async def workspace(platform: AsyncSession) -> AsyncIterator[uuid.UUID]:
    tenant = Tenant(
        name="Connector Workspace",
        slug=f"conn-{uuid.uuid4().hex[:10]}",
        region="us-central1",
    )
    platform.add(tenant)
    await platform.commit()

    yield tenant.id

    await platform.delete(tenant)
    await platform.commit()


async def _installation(
    platform: AsyncSession, tenant_id: uuid.UUID, **overrides: Any
) -> GitHubInstallation:
    """One installation, which the migration's trigger projects into
    `source_connections`. Written this way on purpose: the read model has to be
    correct about rows produced by real production traffic, not about rows a
    test inserted into the table it reads."""
    installation = GitHubInstallation(
        tenant_id=tenant_id,
        installation_id=uuid.uuid4().int % 10**9,
        account_login="an-org",
        account_type="Organization",
        **overrides,
    )
    platform.add(installation)
    await platform.commit()
    return installation


class TestWhatCanBeObserved:
    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_a_provider_with_no_inbound_record_says_so_rather_than_reporting_zero(
        self, platform: AsyncSession
    ) -> None:
        """The `slo.py` rule applied to connectors.

        A zero reads as "connected and quiet" and is indistinguishable from
        "connected and broken". A provider CAIRN cannot count has to say so on
        its own row, with a reason somebody can act on.
        """
        fleet = await connectors.connector_health(platform, Settings(environment="test"))

        silent = [item for item in fleet.providers if item.deliveries_last_hour is None]
        assert {item.provider for item in silent} == {
            connectors.ConnectorProvider.SLACK,
            connectors.ConnectorProvider.GOOGLE_CHAT,
        }
        for item in silent:
            assert item.deliveries_unobservable_reason in connectors.DELIVERY_UNOBSERVABLE_REASONS
            assert item.delivering is False

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_every_provider_gets_a_row(self, platform: AsyncSession) -> None:
        """A provider silently dropped is a row that is not on the screen, and
        nobody notices a row that is not there."""
        fleet = await connectors.connector_health(platform, Settings(environment="test"))

        assert [item.provider for item in fleet.providers] == [
            item.provider for item in connectors.PROVIDERS
        ]

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_a_connected_workspace_is_counted_from_the_connection_record(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """Counted through the provider-neutral table, so Slack and Google Chat
        arrive here with no change to the read model."""
        await _installation(platform, workspace)

        fleet = await connectors.connector_health(platform, Settings(environment="test"))
        github = next(
            item for item in fleet.providers if item.provider is connectors.ConnectorProvider.GITHUB
        )

        assert github.workspaces_connected >= 1
        assert github.workspaces_by_state.get(ConnectionState.CONNECTED.value, 0) >= 1

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_a_suspended_installation_is_the_customer_not_a_fault(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """Suspension happens at GitHub, by the customer.

        It projects to `disconnected`, which is outside the live states, so it
        appears in the state breakdown and in no error count. Counting it as an
        error would page somebody to fix an integration that was deliberately
        turned off — and the fix they would reach for, re-issuing credentials,
        is the one action that must not follow from it.
        """
        await _installation(platform, workspace, suspended_at=datetime.now(UTC))

        fleet = await connectors.connector_health(platform, Settings(environment="test"))
        github = next(
            item for item in fleet.providers if item.provider is connectors.ConnectorProvider.GITHUB
        )

        assert github.workspaces_by_state.get(ConnectionState.DISCONNECTED.value, 0) >= 1
        assert ConnectionState.DISCONNECTED.value not in github.errors_by_category

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_the_response_names_no_workspace_and_no_account(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """Platform-wide, like `/operations/pipeline`.

        `external_account_label` holds "an-org" one column away from every query
        this read model makes, and never appears in the result.
        """
        await _installation(platform, workspace)

        fleet = await connectors.connector_health(platform, Settings(environment="test"))

        assert str(workspace) not in str(fleet)
        assert "an-org" not in str(fleet)

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_configured_but_unverified_is_visible_at_runtime_too(
        self, platform: AsyncSession
    ) -> None:
        """The runtime counterpart of the release gate.

        Both answer the same question and must agree: credentials without a
        delivery is not a working connector.
        """
        fleet = await connectors.connector_health(
            platform, Settings.model_validate({**SLACK_CONFIGURED, "environment": "test"})
        )

        slack = next(
            item for item in fleet.providers if item.provider is connectors.ConnectorProvider.SLACK
        )
        assert slack.credentials_configured is True
        assert slack.inbound_verified is False
        assert fleet.providers_configured_but_unverified >= 1

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_a_never_synced_connection_counts_as_behind(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """A connection that has never delivered is the one most likely to be
        silently broken.

        Excluding it because it has no success timestamp would hide exactly the
        case the number exists for, and the answer is an age in minutes — not a
        delivery id, not an error string, and not the event that caused it.
        """
        await _installation(platform, workspace)

        fleet = await connectors.connector_health(platform, Settings(environment="test"))
        github = next(
            item for item in fleet.providers if item.provider is connectors.ConnectorProvider.GITHUB
        )

        assert github.oldest_unsuccessful_sync_minutes is not None
        assert github.oldest_unsuccessful_sync_minutes >= 0
        assert isinstance(github.oldest_unsuccessful_sync_minutes, float)

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_the_fleet_reports_the_worst_age_across_providers(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """One number for a dashboard, derived rather than stored so it cannot
        drift from the per-provider rows it summarises."""
        await _installation(platform, workspace)

        fleet = await connectors.connector_health(platform, Settings(environment="test"))
        ages = [
            item.oldest_unsuccessful_sync_minutes
            for item in fleet.providers
            if item.oldest_unsuccessful_sync_minutes is not None
        ]

        assert fleet.oldest_unsuccessful_sync_minutes == max(ages)

    @pytest.mark.anyio
    @pytest.mark.integration
    async def test_the_measurement_is_stamped_with_when_it_was_taken(
        self, platform: AsyncSession
    ) -> None:
        """A connector screen with no timestamp is one somebody reads during an
        incident without knowing whether it is ten seconds or ten minutes old."""
        fleet = await connectors.connector_health(platform, Settings(environment="test"))

        assert datetime.now(UTC) - fleet.measured_at < timedelta(minutes=1)
