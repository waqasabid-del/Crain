"""Whether a source is delivering, answered without reading anything it delivered.

Step 32 adds Slack and Google Chat. This module is the half that has to exist
first: the moment a second and third provider arrive, "is ingestion working"
stops being a single number and becomes a per-provider question, and the
tempting way to answer it is to look at what came in. That is the one thing an
operator may never do — a channel name, a message, a repository or a person is
customer content, and reaching it needs the consent-gated, time-boxed support
session in md/15 §5.2, not a dashboard.

So everything here is a **count, an age, or a category from a closed set**, and
the constraint is structural rather than remembered:

- Every field on `ConnectorHealth` is an integer, a boolean, an optional age in
  minutes, or a mapping keyed by an enum somebody else already closed. There is
  no free-text field a provider payload could be put in, and
  `test_connector_ops.py` asserts that over the model's fields rather than over
  the source, so the field that breaks the promise fails a test rather than a
  review.
- Nothing is grouped by anything smaller than a workspace. There is no
  per-person and no per-channel count, and there never will be: md/05 §B.2
  forbids the individual-productivity shape, and a per-channel count is that
  metric with a different label on it.

**Counting is not measuring people.** `workspaces_connected` counts
authorisations. `deliveries_last_hour` counts webhooks. Neither says who sent
anything, and neither can be sliced until it does.

## Where the numbers come from

`db/connector_models.py` — `source_connections`, the provider-neutral connection
record, which a migration trigger already projects every `github_installations`
write into. That is what makes this read model provider-neutral on day one
rather than a GitHub screen with two empty rows bolted on: Slack and Google Chat
appear here the moment they write a connection, with no change to this file.

Its four vocabularies are reused rather than restated. `ConnectionState`,
`ConnectionHealth` and `ConnectorErrorCategory` are defined once, next to the
column that stores them; a parallel enum here would be a second answer to "is
this connection working", which is the exact duplication `source_connections`
was created to remove.

**Two honest gaps, stated here rather than discovered on a screen.** The
migration that projects `github_installations` into `source_connections` sets no
`last_successful_sync_at` and leaves `health` at `unknown` — that table never
recorded either — so every GitHub connection reports as never-synced and shows
up in the sync-age number. For GitHub the delivery counts below are the real
signal; the sync age becomes meaningful for a provider only once its connector
writes those columns. And no connector writes `health` yet at all, so
`workspaces_by_health` is a column with one value in it until Step 32.

**Slack cost this read model nothing.** Step 32 added no field, no query and no
enum here: Slack writes `source_connections` like any other provider, so its row
was already being produced, already counted by state, health and error category,
and already reported as configured-but-unverified. What Slack did add is a set of
*constants* — `ProviderLimits` — because its published limits are operationally
load-bearing in a way GitHub's are not, and one of them is unlike anything else
in this file: cross Slack's inbound ceiling and the events are **discarded, not
queued and not redelivered**. CAIRN requests no history scope, so nothing can go
back for them. That is a permanent hole in a customer's record rather than a
delay, which is why `drops_events_when_throttled` exists as its own question.

Delivery counts are the one thing that is still per-provider. Only GitHub has a
durable inbound record (`webhook_deliveries`), so only GitHub reports delivery
numbers; the others report `None` with a reason rather than zero, for the same
reason `slo.py` refuses to fabricate a measurement. A zero on a connector screen
reads as "connected and quiet" and is indistinguishable from "connected and
broken".

## Mounting it

There is no endpoint here — `api/routers/internal.py` owns the `/operations/*`
routes and this is the fifth. `connector_health` is shaped to be mounted there
in one small step behind `requires_staff(*OPERATIONS_ROLES)`, the same
`engineering`/`security` gate as every other operations surface.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from opentelemetry import metrics
from sqlalchemy import DateTime, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from cairn_api.config import Settings
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.telemetry.attributes import safe

#: The states in which a connection is authorised and expected to deliver.
#:
#: `DISCONNECTED` and `REVOKED` are deliberately absent: a customer who turned a
#: source off is not an outage, and counting them as one produces the page that
#: sends somebody to re-issue credentials for an integration that was removed on
#: purpose.
LIVE_STATES: frozenset[ConnectionState] = frozenset(
    {ConnectionState.CONNECTED, ConnectionState.PENDING, ConnectionState.ERROR}
)

#: The window every "last hour" number here is counted over. One hour matches
#: `/operations/pipeline` deliberately — two numbers describing the same traffic
#: over different windows is how an operator learns to trust neither.
COUNT_WINDOW = timedelta(hours=1)

#: Why a provider has no delivery counts.
#:
#: A module constant rather than an f-string, and the tests assert that the only
#: string-typed field on the read model never holds anything else. It is the
#: obvious place for somebody to put a provider's error body during an incident,
#: and provider error bodies quote the request that failed — which for Slack and
#: Chat means channel names and message fragments.
NO_DELIVERY_RECORD = (
    "This provider has no durable inbound record yet, so deliveries cannot be "
    "counted. Connection state and last-successful-sync age below are real; a "
    "zero here would not be."
)

#: Every reason that field may hold. One today; the set exists so that adding a
#: second is a deliberate edit to a constant rather than a new string literal at
#: a call site.
DELIVERY_UNOBSERVABLE_REASONS: frozenset[str] = frozenset({NO_DELIVERY_RECORD})


@dataclass(frozen=True, slots=True)
class ProviderLimits:
    """A provider's own published limits, as constants.

    Not measurements. Nothing here is read from a connection, a delivery or a
    workspace — these are numbers from the provider's documentation, recorded in
    code so that an alert threshold and a runbook cannot drift apart, and so
    that "how long do we have to answer" has one answer rather than one per
    reader.

    They live here rather than in the connector because the operational
    question — *are we near a limit, and what happens when we cross it* — is
    asked on this side of the boundary, by somebody who is not allowed to look
    at what the connector received.
    """

    #: How long the provider waits for a 2xx before it treats the delivery as
    #: failed. Slack's is three seconds, which is short enough that any
    #: synchronous work in the request path is a design error rather than a
    #: tuning problem.
    ack_deadline_seconds: float

    #: How many times a failed delivery is retried, in total.
    retry_attempts: int

    #: The gaps before each retry, in minutes, from the first attempt. Slack's
    #: `(0, 1, 5)` means immediately, then after a minute, then after five.
    retry_backoff_minutes: tuple[int, ...]

    #: Inbound events the provider will deliver, per workspace, per app, per
    #: hour. `None` where the provider publishes no such ceiling.
    events_per_hour: int | None = None

    #: Whether exceeding `events_per_hour` **discards** events rather than
    #: queueing them. Slack's does: the events are not buffered, and because
    #: CAIRN requests no history scope there is no way to go back for them.
    events_dropped_when_exceeded: bool = False

    #: Whether the provider redelivers what it dropped. Recorded separately from
    #: the line above because "throttled" and "throttled and gone forever" are
    #: different incidents, and only the second one is a permanent hole in a
    #: customer's record that has to be disclosed rather than fixed.
    events_redelivered_after_drop: bool = False

    @property
    def alert_events_per_hour(self) -> int | None:
        """Where to warn: 80% of the ceiling, or `None` if there is no ceiling.

        Well before the limit, deliberately. At the limit the events are already
        gone — an alert that fires on the ceiling is a notification that data was
        lost, not a chance to prevent it.
        """
        return int(self.events_per_hour * 0.8) if self.events_per_hour is not None else None


#: Slack's Events API, from the current official documentation.
#:
#: The 30,000 is the number that matters and the reason this dataclass exists:
#: Slack delivers at most 30,000 events per workspace per app per hour, and
#: **beyond it events are dropped, not queued and not redelivered**. CAIRN asks
#: for no history scope, so nothing can go back and fetch them. That is a
#: permanent gap in a customer's record, and it is the one connector failure
#: mode that cannot be repaired after the fact.
SLACK_LIMITS = ProviderLimits(
    ack_deadline_seconds=3.0,
    retry_attempts=3,
    retry_backoff_minutes=(0, 1, 5),
    events_per_hour=30_000,
    events_dropped_when_exceeded=True,
    events_redelivered_after_drop=False,
)


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """What is known about a provider before anything is measured."""

    provider: ConnectorProvider

    #: `Settings` attributes that must all be set for credentials to count as
    #: configured. Read with `getattr`, because Slack's and Google Chat's fields
    #: do not exist on `Settings` yet and this module does not own `config.py`.
    settings_fields: tuple[str, ...]

    #: The environment variables behind those fields, so a blocked release gate
    #: can name them.
    env_vars: tuple[str, ...]

    #: Whether a durable per-delivery record exists for this provider. GitHub
    #: has `webhook_deliveries`; nothing else does yet.
    has_delivery_record: bool = False

    #: The provider's published limits, where it publishes any.
    limits: ProviderLimits | None = None

    #: The manual check that would close this provider's release gate — the one
    #: thing configuration cannot do. Held here rather than in
    #: `release_gates.py` so that each provider's live-validation step sits next
    #: to the rest of what is known about it, and the gate composes rather than
    #: grows a branch per provider.
    manual_verification: str = ""

    def credentials_configured(self, settings: Settings) -> bool:
        """Whether every credential this provider needs is present.

        Present, not valid, and not installed. A secret in an environment
        variable proves somebody set a variable — the distinction the whole of
        `release_gates.py` is built on.
        """
        return all(bool(getattr(settings, name, None)) for name in self.settings_fields)


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        provider=ConnectorProvider.GITHUB,
        settings_fields=("github_app_id", "github_webhook_secret", "github_private_key"),
        env_vars=(
            "CAIRN_GITHUB_APP_ID",
            "CAIRN_GITHUB_WEBHOOK_SECRET",
            "CAIRN_GITHUB_PRIVATE_KEY",
        ),
        has_delivery_record=True,
        manual_verification=(
            "GitHub: push one commit to an installed repository and confirm the "
            "delivery verifies its signature."
        ),
    ),
    ProviderSpec(
        provider=ConnectorProvider.SLACK,
        settings_fields=("slack_client_id", "slack_client_secret", "slack_signing_secret"),
        env_vars=(
            "CAIRN_SLACK_CLIENT_ID",
            "CAIRN_SLACK_CLIENT_SECRET",
            "CAIRN_SLACK_SIGNING_SECRET",
        ),
        limits=SLACK_LIMITS,
        manual_verification=(
            "Slack: /invite the bot to one channel first — CAIRN never requests "
            "channels:join, so a bot that has not been invited receives nothing "
            "however correct the scopes and the Request URL are. Then post one "
            "message in that channel."
        ),
    ),
    ProviderSpec(
        provider=ConnectorProvider.GOOGLE_CHAT,
        settings_fields=("google_chat_project_id", "google_chat_service_account"),
        env_vars=("CAIRN_GOOGLE_CHAT_PROJECT_ID", "CAIRN_GOOGLE_CHAT_SERVICE_ACCOUNT"),
        manual_verification=("Google Chat: add the app to one space and post one message in it."),
    ),
)


def spec(provider: ConnectorProvider) -> ProviderSpec:
    """Look one up, or fail loudly, in the style of `slo.objective`."""
    for candidate in PROVIDERS:
        if candidate.provider is provider:
            return candidate
    msg = f"no connector spec for provider {provider!r}"
    raise KeyError(msg)


# --------------------------------------------------------------------------
# The read model
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    """One provider, as far as it can be seen without reading what it carried.

    Every field is a count, an age, a flag, or a mapping keyed by a closed enum.
    There is nowhere here to put a channel, a message, a repository, an account
    label or a person — `source_connections.external_account_label` sits one
    column away from these queries and is deliberately never selected.
    """

    provider: ConnectorProvider

    #: Credentials are present in the environment. Says nothing about whether
    #: the provider accepts them, or whether anyone has installed anything.
    credentials_configured: bool

    #: Workspaces with a connection that is authorised right now.
    workspaces_connected: int = 0

    #: Workspaces this provider has ever successfully delivered to. The only
    #: evidence that inbound delivery has been observed rather than configured,
    #: and the number `inbound_verified` and the release gate turn on.
    workspaces_ever_synced: int = 0

    #: Every connection, keyed by `ConnectionState.value`. Includes the states
    #: that are not faults — `disconnected` and `revoked` are a customer's
    #: decision, and burying them in a single "not working" number is how an
    #: operator ends up re-issuing credentials somebody deliberately withdrew.
    workspaces_by_state: Mapping[str, int] = field(default_factory=dict)

    #: Live connections keyed by `ConnectionHealth.value`. State is about
    #: permission; health is about whether data is arriving. A connection can be
    #: perfectly authorised and rate-limited into uselessness.
    workspaces_by_health: Mapping[str, int] = field(default_factory=dict)

    #: Live connections keyed by `ConnectorErrorCategory.value`, from
    #: `last_error_category`. Never a provider message: those quote the request
    #: that failed, which is customer data.
    errors_by_category: Mapping[str, int] = field(default_factory=dict)

    #: How long the worst live connection has gone without a successful sync, in
    #: minutes, measured from its last success or — if it has never had one —
    #: from when it was authorised. `None` means no live connection is behind.
    oldest_unsuccessful_sync_minutes: float | None = None

    #: `None`, not zero, when this provider has no durable inbound record.
    deliveries_last_hour: int | None = None
    failures_last_hour: int | None = None
    deliveries_total: int | None = None

    #: Why the three fields above are `None`. Always a member of
    #: `DELIVERY_UNOBSERVABLE_REASONS`.
    deliveries_unobservable_reason: str | None = None

    @property
    def key(self) -> str:
        """Stable identifier for a row on a screen or in an alert rule."""
        return self.provider.value

    @property
    def workspaces_in_error(self) -> int:
        """Live connections in the `error` state.

        Read off the state breakdown rather than stored, so it cannot drift from
        its own detail.
        """
        return self.workspaces_by_state.get(ConnectionState.ERROR.value, 0)

    @property
    def workspaces_failing(self) -> int:
        """Live connections that are authorised and not collecting.

        Distinct from `workspaces_in_error`: a connection can be perfectly
        authorised and delivering nothing, and that is the failure a customer
        notices first.
        """
        return self.workspaces_by_health.get(ConnectionHealth.FAILING.value, 0)

    @property
    def inbound_verified(self) -> bool:
        """Whether anything has ever actually arrived from this provider.

        The distinction the release gate turns on. Credentials being configured
        is not evidence; a recorded successful sync, or a recorded delivery, is.
        """
        return self.workspaces_ever_synced > 0 or bool(self.deliveries_total)

    @property
    def delivering(self) -> bool:
        """Whether anything arrived in the counting window.

        `False` for a provider with no delivery record, because "not seen" must
        never render as "seen and fine".
        """
        return bool(self.deliveries_last_hour)

    @property
    def limits(self) -> ProviderLimits | None:
        """The provider's published limits, if it publishes any.

        Derived from `PROVIDERS` rather than stored as a field, which is what
        keeps the read model's field list unchanged: a constant from a
        documentation page is not a measurement and has no business being
        carried alongside one.
        """
        return spec(self.provider).limits

    @property
    def throttled_workspaces(self) -> int:
        """Live connections the provider is currently throttling.

        Read off `errors_by_category`, so it cannot drift from its own detail.
        For Slack this is the closest thing to a rate-limit signal that exists
        today, and it is a lagging one — see `event_budget_observable`.
        """
        return self.errors_by_category.get(ConnectorErrorCategory.RATE_LIMITED.value, 0)

    @property
    def drops_events_when_throttled(self) -> bool:
        """Whether being throttled by this provider loses data permanently.

        True for Slack. Crossing its ceiling discards events, and they are
        neither queued nor redelivered — so a throttled Slack workspace is not a
        delay to wait out, it is a hole in that customer's record. Distinguished
        from ordinary throttling because the response differs: one is patience,
        the other is a disclosure.
        """
        found = self.limits
        return bool(
            found and found.events_dropped_when_exceeded and not found.events_redelivered_after_drop
        )

    @property
    def event_budget_per_hour(self) -> int | None:
        """The provider's inbound ceiling per workspace per hour, if it has one.

        A published constant, not a reading. **How close a workspace actually is
        to it cannot be answered from this model, and is not approximated here.**
        The ceiling is per workspace; every count above is platform-wide, and
        Slack has no durable inbound record at all. A gauge built from a
        platform-wide total would read 3% while one workspace sat at 100% and
        lost a morning of decisions, which is worse than an empty panel because
        somebody would trust it.

        Closing that needs a per-workspace inbound event count. The telemetry to
        carry one already exists — `record_connector_delivery` takes an optional
        `tenant_id`, which is on the allow-list — and the Slack connector has to
        pass it. Until then this is a number to compare against by hand.
        """
        found = self.limits
        return found.events_per_hour if found else None

    @property
    def event_budget_alert_at(self) -> int | None:
        """Where to warn: 80% of the ceiling. `None` when there is no ceiling.

        Well before it. At the ceiling the events are already discarded, so an
        alert that fires there reports a loss rather than preventing one.
        """
        found = self.limits
        return found.alert_events_per_hour if found else None


@dataclass(frozen=True, slots=True)
class ConnectorFleet:
    """Every provider at one moment, and the numbers worth alerting on."""

    measured_at: datetime
    providers: tuple[ConnectorHealth, ...]

    @property
    def workspaces_in_error(self) -> int:
        return sum(item.workspaces_in_error for item in self.providers)

    @property
    def workspaces_failing(self) -> int:
        return sum(item.workspaces_failing for item in self.providers)

    @property
    def providers_configured_but_unverified(self) -> int:
        """The number that has to be zero before a release.

        Configured and never proven is precisely the state `release_gates.py`
        refuses to call "passed", and this is its runtime reading — so the gate
        and the screen cannot disagree.
        """
        return sum(
            1
            for item in self.providers
            if item.credentials_configured and not item.inbound_verified
        )

    @property
    def oldest_unsuccessful_sync_minutes(self) -> float | None:
        """The worst age across every provider, or `None` if nothing is behind."""
        ages = [
            item.oldest_unsuccessful_sync_minutes
            for item in self.providers
            if item.oldest_unsuccessful_sync_minutes is not None
        ]
        return max(ages) if ages else None


# --------------------------------------------------------------------------
# The queries
# --------------------------------------------------------------------------


def _live(statement: Select[Any], provider: ConnectorProvider) -> Select[Any]:
    """Narrow a query to one provider's authorised connections."""
    return statement.where(
        SourceConnection.provider == provider,
        SourceConnection.state.in_(tuple(LIVE_STATES)),
    )


async def _grouped(
    db: AsyncSession,
    provider: ConnectorProvider,
    column: InstrumentedAttribute[Any],
    *,
    live_only: bool,
) -> dict[str, int]:
    """Distinct workspaces per category, as a plain mapping of value to count.

    Grouped by a column whose type is a closed enum in every caller, so the keys
    of the result are a closed set too — a mapping keyed by whatever a provider
    returned would be the same leak wearing a count's clothes.
    """
    statement = select(column, func.count(func.distinct(SourceConnection.tenant_id))).where(
        SourceConnection.provider == provider
    )
    if live_only:
        statement = statement.where(SourceConnection.state.in_(tuple(LIVE_STATES)))

    rows = await db.execute(statement.group_by(column))
    return {
        (key.value if hasattr(key, "value") else str(key)): int(count)
        for key, count in rows.all()
        if key is not None
    }


async def _delivery_counts(db: AsyncSession, since: datetime) -> tuple[int, int, int]:
    """GitHub's inbound record: recent, recently failed, and ever.

    Nothing here selects `payload`. It is one column away from every one of
    these queries and reading it would answer "what did they say" rather than
    "did it arrive", which is a support session's business.
    """
    from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery

    recent = await db.scalar(
        select(func.count()).select_from(WebhookDelivery).where(WebhookDelivery.created_at >= since)
    )
    failed = await db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.created_at >= since, WebhookDelivery.status == DeliveryStatus.FAILED)
    )
    total = await db.scalar(select(func.count()).select_from(WebhookDelivery))
    return int(recent or 0), int(failed or 0), int(total or 0)


async def _provider_health(
    db: AsyncSession, provider_spec: ProviderSpec, settings: Settings, now: datetime
) -> ConnectorHealth:
    """One provider's row."""
    provider = provider_spec.provider

    connected = await db.scalar(
        select(func.count(func.distinct(SourceConnection.tenant_id))).where(
            SourceConnection.provider == provider,
            SourceConnection.state == ConnectionState.CONNECTED,
            SourceConnection.disconnected_at.is_(None),
            SourceConnection.revoked_at.is_(None),
        )
    )
    ever_synced = await db.scalar(
        select(func.count(func.distinct(SourceConnection.tenant_id))).where(
            SourceConnection.provider == provider,
            SourceConnection.last_successful_sync_at.is_not(None),
        )
    )

    # The worst live connection that is not healthy, aged from its last success
    # or — when it has never had one — from when it was authorised. A connection
    # that has never synced is the one most likely to be silently broken, and
    # excluding it because it has no success timestamp would hide exactly that.
    behind_since = await db.scalar(
        _live(
            select(
                func.min(
                    func.coalesce(
                        SourceConnection.last_successful_sync_at,
                        SourceConnection.connected_at,
                        SourceConnection.created_at,
                        type_=DateTime(timezone=True),
                    )
                )
            ),
            provider,
        ).where(
            or_(
                SourceConnection.health != ConnectionHealth.HEALTHY,
                SourceConnection.last_successful_sync_at.is_(None),
            )
        )
    )

    deliveries = failures = total = None
    reason = None
    if provider_spec.has_delivery_record:
        deliveries, failures, total = await _delivery_counts(db, now - COUNT_WINDOW)
    else:
        reason = NO_DELIVERY_RECORD

    return ConnectorHealth(
        provider=provider,
        credentials_configured=provider_spec.credentials_configured(settings),
        workspaces_connected=int(connected or 0),
        workspaces_ever_synced=int(ever_synced or 0),
        workspaces_by_state=await _grouped(db, provider, SourceConnection.state, live_only=False),
        workspaces_by_health=await _grouped(db, provider, SourceConnection.health, live_only=True),
        errors_by_category=await _grouped(
            db, provider, SourceConnection.last_error_category, live_only=True
        ),
        oldest_unsuccessful_sync_minutes=(
            (now - behind_since).total_seconds() / 60 if behind_since is not None else None
        ),
        deliveries_last_hour=deliveries,
        failures_last_hour=failures,
        deliveries_total=total,
        deliveries_unobservable_reason=reason,
    )


async def connector_health(db: AsyncSession, settings: Settings | None = None) -> ConnectorFleet:
    """Every provider's state, in counts and categories.

    Platform-wide and never per workspace, matching `/operations/pipeline`.
    Which customer is connected to what is a support session's question, and
    putting it on a dashboard answers it for every workspace at once with
    nobody's consent.

    A provider CAIRN cannot count reports `None` with a reason rather than zero.
    Zeros on this screen read as "connected and quiet", which is the most
    reassuring possible rendering of "this cannot be seen from here".
    """
    from cairn_api.config import get_settings

    resolved = settings or get_settings()
    now = datetime.now(UTC)

    rows = [await _provider_health(db, item, resolved, now) for item in PROVIDERS]
    return ConnectorFleet(measured_at=now, providers=tuple(rows))


def configured_providers(settings: Settings) -> tuple[ConnectorProvider, ...]:
    """Providers whose credentials are all present.

    Shared with the release gate so that "configured" means one thing in both
    places, and a provider cannot be configured for the gate and unconfigured
    for the screen.
    """
    return tuple(item.provider for item in PROVIDERS if item.credentials_configured(settings))


def missing_credentials(provider: ConnectorProvider, settings: Settings) -> tuple[str, ...]:
    """The environment variables this provider is still missing, by name.

    Named, because "blocked" without the variable to set is an observation
    rather than a runbook.
    """
    found = spec(provider)
    return tuple(
        variable
        for name, variable in zip(found.settings_fields, found.env_vars, strict=True)
        if not getattr(settings, name, None)
    )


# --------------------------------------------------------------------------
# Source-specific metrics
# --------------------------------------------------------------------------
#
# Every attribute below is on the `telemetry/attributes.py` allow-list:
# `source`, `outcome`, `error_category`, `tenant_id`. Nothing else is accepted.
#
# The reduction to a category happens *here* rather than at the call site. A
# connector author handed a `str` could pass a provider's error body as an
# `error_category` and the allow-list — which checks keys — would wave it
# through; taking the enum makes "no provider error text reaches telemetry" a
# property of the signature instead of a rule somebody remembers.
#
# There is no per-channel, per-space, per-conversation or per-account attribute,
# and no allow-list entry that could carry one. That is the boundary, not an
# omission.

meter = metrics.get_meter("cairn.connectors")

connector_deliveries = meter.create_counter(
    "cairn.connector.deliveries",
    description="Inbound events accepted from a connected source, by provider and outcome",
)

connector_errors = meter.create_counter(
    "cairn.connector.errors",
    description="Connector failures by provider and category",
)

connector_rate_limit_windows = meter.create_counter(
    "cairn.connector.rate_limit_windows",
    description=("Windows in which a provider throttled a source and discarded inbound events"),
)


def record_connector_delivery(
    *, source: ConnectorProvider, outcome: str, tenant_id: uuid.UUID | None = None
) -> None:
    """One inbound event from a source.

    `outcome` uses the pipeline's existing vocabulary — `accepted`, `processed`,
    `failed`, `unclaimed` — so a connector alert reads the same way as a queue
    alert. It carries nothing about what arrived.

    `tenant_id` is optional and is the *floor* of what may be grouped by, not an
    exception to it. Slack's inbound ceiling is per workspace per hour, so a
    platform-wide total cannot tell anybody they are about to lose data — one
    busy workspace hits the limit while the fleet total looks calm. A workspace
    is a customer, not a person, and `tenant_id` is on the allow-list for
    exactly that reason. Nothing finer is available here or ever will be: there
    is no channel, no conversation and no account attribute, and none of them
    could be added without an edit to the closed allow-list.
    """
    connector_deliveries.add(
        1,
        safe(
            {
                "source": source.value,
                "outcome": outcome,
                "tenant_id": str(tenant_id) if tenant_id is not None else None,
            }
        ),
    )


def record_connector_error(*, source: ConnectorProvider, category: ConnectorErrorCategory) -> None:
    """One connector failure, reduced to a category before it can leave."""
    connector_errors.add(1, safe({"source": source.value, "error_category": category.value}))


def record_connector_rate_limited(*, source: ConnectorProvider) -> None:
    """One window in which a provider throttled us and discarded events.

    A separate counter from `connector_errors` because it means something the
    other categories do not: for Slack, the events refused during this window
    were **dropped rather than queued, and are never redelivered**. CAIRN
    requests no history scope, so nothing can go back for them and the gap in
    that customer's record is permanent. It is recorded as an error as well, so
    the existing error alert still fires, and counted separately so that "we
    were slow" and "we lost data" are not one number.

    Deliberately carries only `source`. Slack's `app_rate_limited` payload holds
    `team_id` and `minute_rate_limited`; neither is passed. `team_id` is Slack's
    identifier, not CAIRN's tenant id, and putting a provider's own workspace
    identifier into an exporter would name a customer in a system with its own
    retention and its own readers. The caller that knows the mapping should use
    `record_connector_delivery(tenant_id=...)`, which carries CAIRN's id.
    """
    connector_rate_limit_windows.add(1, safe({"source": source.value}))
    record_connector_error(source=source, category=ConnectorErrorCategory.RATE_LIMITED)


__all__ = [
    "COUNT_WINDOW",
    "DELIVERY_UNOBSERVABLE_REASONS",
    "LIVE_STATES",
    "NO_DELIVERY_RECORD",
    "PROVIDERS",
    "SLACK_LIMITS",
    "ConnectionHealth",
    "ConnectionState",
    "ConnectorErrorCategory",
    "ConnectorFleet",
    "ConnectorHealth",
    "ConnectorProvider",
    "ProviderLimits",
    "ProviderSpec",
    "configured_providers",
    "connector_health",
    "missing_credentials",
    "record_connector_delivery",
    "record_connector_error",
    "record_connector_rate_limited",
    "spec",
]
