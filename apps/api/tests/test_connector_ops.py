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
    "str | None",
    "ConnectorProvider",
    "Mapping[str, int]",
    "tuple[ConnectorHealth, ...]",
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

MODELS = (connectors.ConnectorHealth, connectors.ConnectorFleet)


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

    def test_the_one_free_text_field_may_only_hold_a_constant(self) -> None:
        """`deliveries_unobservable_reason` is the single `str` on the model.

        It exists because "no number" needs a reason, and it is the obvious
        place for somebody to put a provider's error body during an incident —
        which for Slack and Chat quotes channel names and message fragments.
        Constraining its values to a module constant is what stops that being a
        judgement call at 3am.
        """
        reason_fields = [
            item.name
            for model in MODELS
            for item in dataclasses.fields(model)
            if str(item.type) == "str | None"
        ]
        assert reason_fields == ["deliveries_unobservable_reason"]
        assert connectors.NO_DELIVERY_RECORD in connectors.DELIVERY_UNOBSERVABLE_REASONS

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
