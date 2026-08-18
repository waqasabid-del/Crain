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

**Google Chat cost this read model nothing either.** Step 33 adds no field, no
query and no enum to `ConnectorHealth`: Chat writes `source_connections` like any
other provider, so its row is already produced, already counted by state, health
and error category, and already reported as configured-but-unverified.
`test_google_chat_added_no_field_to_the_read_model` pins that next to Slack's.

What Google Chat *does* add is a second, separate aggregate — `SubscriptionHealth`
— and it is separate because it is not a property of a connection. Chat delivers
through the Workspace Events API, which leases one **subscription per selected
space** with a **four-hour** time-to-live; `source_connections` has one row per
connection and no place to put N leases, so folding this into `ConnectorHealth`
would mean either a per-space row (forbidden) or a number that averages away the
one subscription that died. It is counts only: how many leases are live,
suspended, expired and *missing*, and how long until the nearest one expires. No
space identifier reaches it, and the reducer's input type has nowhere to put one.

The missing count is the one that matters. **An expired Chat subscription is
permanently deleted and cannot be renewed** — it has to be recreated — so the
number of live leases can silently fall below the number of selected spaces while
every connection still reads `connected`. That is a gap in delivery, not a delay.

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

import enum
import uuid
from collections.abc import Mapping, Sequence
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
from cairn_api.db.gchat_models import GoogleChatSubscriptionState
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

#: Why Google Chat's subscription aggregate has counts of `None` rather than 0.
#:
#: The same rule as `NO_DELIVERY_RECORD` and the same reason: nothing stores a
#: Chat subscription lease yet, and a screen reading "0 suspended, 0 expired"
#: while nothing is being watched is the most reassuring possible rendering of
#: "this cannot be seen from here".
NO_SUBSCRIPTION_RECORD = (
    "No subscription lease is stored yet, so live, suspended and expired counts "
    "cannot be produced. Zeros here would read as a healthy renewal loop and "
    "there is not one to read."
)

#: Every reason that field may hold, for the same reason the delivery set exists.
SUBSCRIPTION_UNOBSERVABLE_REASONS: frozenset[str] = frozenset({NO_SUBSCRIPTION_RECORD})


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
    #: tuning problem. Google Chat arrives over a Pub/Sub push subscription,
    #: whose **acknowledgement deadline doubles as the request timeout** — the
    #: default is ten seconds.
    ack_deadline_seconds: float

    #: How many times a failed delivery is retried, in total. `None` where the
    #: provider retries until a retention deadline rather than a fixed number of
    #: times: Pub/Sub redelivers a nacked message until the topic's message
    #: retention expires, so "how many attempts" has no answer for Google Chat
    #: and a fabricated integer would be read as one.
    retry_attempts: int | None

    #: The gaps before each retry, in minutes, from the first attempt. Slack's
    #: `(0, 1, 5)` means immediately, then after a minute, then after five.
    #: Empty where the provider publishes a range instead — see
    #: `retry_backoff_seconds_range`.
    retry_backoff_minutes: tuple[int, ...]

    #: The provider's published backoff *range* in seconds, where it publishes a
    #: range rather than a schedule. Pub/Sub's is 100ms to 60s, which cannot be
    #: expressed in whole minutes and must not be rounded to zero.
    retry_backoff_seconds_range: tuple[float, float] | None = None

    #: The largest acknowledgement deadline the provider allows, where it is
    #: configurable. Pub/Sub's push deadline can be raised to 600 seconds — and
    #: raising it raises the request timeout with it, which is a decision about
    #: how long a push endpoint may block, not a free win.
    ack_deadline_max_seconds: float | None = None

    #: Whether a single delivery's deadline can be extended while it is being
    #: handled. It cannot be, for either provider: Pub/Sub **push** has no
    #: per-message `modifyAckDeadline`, so the endpoint answers inside the
    #: subscription's deadline or the message is redelivered.
    ack_deadline_extendable_per_delivery: bool = False

    #: Whether the provider may deliver the same event more than once. Pub/Sub
    #: is at-least-once; its exactly-once guarantee is **pull-only** and CAIRN
    #: receives by push, so every Chat handler must be idempotent.
    delivers_at_least_once: bool = False

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


#: Google Chat's inbound path, which is Pub/Sub push rather than a webhook.
#:
#: The ack deadline is the number to design against: it **doubles as the request
#: timeout** and cannot be extended for one message, so a handler that has not
#: answered by then has its message redelivered whether or not it eventually
#: succeeds. Ten seconds is roomier than Slack's three, and the discipline is the
#: same — acknowledge, then work.
#:
#: There is no `events_per_hour` here because Google publishes no inbound event
#: ceiling for Chat, and inventing one would be worse than the blank: the real
#: ceiling in this connector is the **3,000 reads per project per 60 seconds** on
#: `spaces.messages.get`, which is only paid when subscriptions are created with
#: `includeResource: false`. See `GOOGLE_CHAT_SUBSCRIPTION`.
GOOGLE_CHAT_LIMITS = ProviderLimits(
    ack_deadline_seconds=10.0,
    retry_attempts=None,
    retry_backoff_minutes=(),
    retry_backoff_seconds_range=(0.1, 60.0),
    ack_deadline_max_seconds=600.0,
    ack_deadline_extendable_per_delivery=False,
    delivers_at_least_once=True,
)


#: Google Meet's inbound path, which is the same Pub/Sub push transport as Chat's
#: and therefore the same numbers.
#:
#: Restated rather than aliased. They are equal today because both ride Cloud
#: Pub/Sub, not because they are the same fact — Google can change one product's
#: push configuration without changing the other's, and an alias would quietly
#: make a Meet incident report Chat's ack deadline.
#:
#: There is no `events_per_hour`: Google publishes no inbound ceiling, and unlike
#: Chat there is no per-project read quota behind it either, because this
#: connector never reads a resource.
GOOGLE_MEET_LIMITS = ProviderLimits(
    ack_deadline_seconds=10.0,
    retry_attempts=None,
    retry_backoff_minutes=(),
    retry_backoff_seconds_range=(0.1, 60.0),
    ack_deadline_max_seconds=600.0,
    ack_deadline_extendable_per_delivery=False,
    delivers_at_least_once=True,
)


class ScopeTier(enum.StrEnum):
    """How hard Google makes a scope to ship, which is a release constraint.

    Not a security classification and not ours: these are Google's own OAuth
    verification tiers, recorded because the difference between them is measured
    in months of calendar time and no amount of correct code shortens it.
    """

    #: No verification beyond the consent screen.
    BASIC = "basic"

    #: OAuth verification by Google. Weeks, no third party involved.
    SENSITIVE = "sensitive"

    #: OAuth verification **plus** an independent third-party security
    #: assessment (CASA), ending in a Letter of Assessment, and re-assessment at
    #: least every twelve months. Weeks to months, repeated annually, forever.
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class OAuthScope:
    """One scope and what shipping it costs."""

    name: str
    tier: ScopeTier

    @property
    def requires_security_assessment(self) -> bool:
        """Whether a third party has to assess CAIRN before this scope goes live.

        True only for `RESTRICTED`. It is the property the release gate turns on,
        because it is the one constraint on this connector that is not satisfiable
        by writing or reviewing code.
        """
        return self.tier is ScopeTier.RESTRICTED


#: How often a restricted scope has to be re-assessed, in months. Google requires
#: re-verification at least annually, so the assessment is a standing operational
#: obligation with an expiry date, not a launch task that is finished once.
RESTRICTED_SCOPE_REVERIFICATION_MONTHS = 12

#: The scopes the Google Chat connector needs, and their verification tier.
#:
#: `chat.messages.readonly` is **RESTRICTED**. There is no read-only Chat message
#: scope in a lower tier — reading messages at all puts CAIRN in the tier that
#: requires an independent security assessment. This is the single largest
#: blocker in the connector programme and it is a calendar problem, not an
#: engineering one.
GOOGLE_CHAT_SCOPES: tuple[OAuthScope, ...] = (
    OAuthScope(name="chat.messages.readonly", tier=ScopeTier.RESTRICTED),
    OAuthScope(name="chat.spaces.readonly", tier=ScopeTier.SENSITIVE),
)


#: Google Meet's scopes, which are one scope.
#:
#: **SENSITIVE, not RESTRICTED**, and the difference is months of calendar time.
#: `meetings.space.readonly` needs Google OAuth app verification and no
#: independent CASA assessment, so Meet can go live on a timeline Chat cannot.
#:
#: That holds only while the list is one entry long. Retrieving a transcript
#: means a Drive scope, Drive scopes are RESTRICTED, and adding one moves this
#: connector into Chat's release regime. The tier is recorded here so that
#: becomes a visible edit to a constant with a test on it rather than a
#: discovery during a launch review.
GOOGLE_MEET_SCOPES: tuple[OAuthScope, ...] = (
    OAuthScope(name="meetings.space.readonly", tier=ScopeTier.SENSITIVE),
)


#: The scope Step 36B's **transcript retrieval** needs, and the prediction above
#: coming true.
#:
#: `drive.meet.readonly` is **RESTRICTED**: Google OAuth verification *plus* an
#: independent third-party CASA security assessment ending in a Letter of
#: Assessment, re-taken at least every 12 months, forever. It is the narrowest
#: scope that can read a Meet transcript — `drive.readonly` would work and would
#: also grant every other file in the account — and there is no lower-tier
#: alternative, exactly as there is none for Chat's messages.
#:
#: **Kept as its own constant rather than appended to `GOOGLE_MEET_SCOPES`.** The
#: two are separate consent actions on separate OAuth clients, and a deployment
#: may ship the connection half — announcements only, SENSITIVE, weeks — while the
#: assessment for this one is still running. Merging the lists would report the
#: whole connector as blocked and would quietly make the *reverse* mistake
#: available later: adding a restricted scope to a list somebody reads as "the
#: Meet scopes" and shipping on the strength of the tier that was there before.
GOOGLE_MEET_TRANSCRIPT_SCOPES: tuple[OAuthScope, ...] = (
    OAuthScope(name="drive.meet.readonly", tier=ScopeTier.RESTRICTED),
)


@dataclass(frozen=True, slots=True)
class SubscriptionLimits:
    """Google Workspace Events subscription leases, as published constants.

    A Chat subscription is a **lease per space**, not a webhook registration, and
    every number here is about how short that lease is and what happens when one
    lapses. They are constants from Google's documentation for the same reason
    `ProviderLimits` is: so a renewal interval, an alert threshold and a runbook
    cannot drift apart.
    """

    #: The lease, in hours, as CAIRN creates them. Four, because CAIRN requests
    #: `includeResource: true` and does **not** use domain-wide delegation. The
    #: 24-hour ceiling requires domain-wide delegation, which is out of scope: it
    #: is an admin granting one application the right to impersonate every user
    #: in the organisation, which is a larger grant than this product needs.
    ttl_hours: float = 4.0

    #: The lease if CAIRN asked for `includeResource: false`: seven days. Not the
    #: free win it looks like — see `reads_per_project_per_minute`.
    ttl_hours_without_resource: float = 168.0

    #: The read ceiling paid for that longer lease. Without the resource on the
    #: event, every single message costs one `spaces.messages.get`, and those are
    #: capped at 3,000 reads per project per 60 seconds **across all customers on
    #: this Cloud project**. A per-project ceiling shared by every tenant is a
    #: harder wall than a renewal loop, and crossing it throttles everybody at
    #: once, so CAIRN takes the four-hour lease and renews.
    reads_per_project_per_minute: int = 3_000

    #: Renew at half the lease. Two hours of slack means a renewal can fail
    #: outright, be retried on the next pass, and still land before the lease
    #: lapses — and a lapse is not recoverable by retrying.
    renewal_at_fraction_of_ttl: float = 0.5

    #: How far ahead Google's documented expiration-reminder event fires. Recorded
    #: because it is **structurally unreachable at this lease length** — see
    #: `expiration_reminder_is_reachable` — and somebody will otherwise build the
    #: renewal loop on it.
    documented_expiration_reminder_lead_hours: float = 12.0

    #: Whether an expired subscription can be renewed. It cannot: it is deleted,
    #: permanently, and delivery for that space stops until a new subscription is
    #: **created**. Renewal and recreation are different code paths and only one
    #: of them exists in a renewal loop.
    expired_subscription_is_recoverable: bool = False

    #: How long a suspended subscription stays reactivatable via
    #: `subscriptions.reactivate`. Google does not document it. `None` records
    #: the absence of an answer rather than a guess, and the operational
    #: consequence is the same either way: reactivate promptly, do not queue it.
    reactivation_window_hours: float | None = None

    #: Whether Workspace Events publishes request-rate limits. It does not, which
    #: is why renewals must be staggered rather than run as one cron sweep: with
    #: N spaces renewing several times a day, a thundering herd is the shape most
    #: likely to find the undocumented limit.
    request_rate_limits_published: bool = False

    #: Whether the Pub/Sub publisher principal for Workspace Events on Chat is
    #: confirmed. It is **not**. Google's documentation names
    #: `chat-api-push@system.gserviceaccount.com` for Chat *interaction* events
    #: and does not state whether Workspace-Events-for-Chat publishes as the same
    #: principal. Granting the wrong one surfaces as an
    #: `ENDPOINT_PERMISSION_DENIED` suspension rather than as a configuration
    #: error, so it must be verified empirically in a real project.
    publisher_principal_confirmed: bool = False

    #: How long a refresh token survives while the OAuth consent screen is in
    #: "Testing" with external user type: seven days. Every customer connection
    #: then breaks weekly until the app is published and verified — which for
    #: this connector means the restricted-scope assessment is finished.
    refresh_token_days_while_testing: int = 7

    #: Refresh tokens per account per client id. The 101st silently invalidates
    #: the oldest, with no error anywhere, so a reconnect loop quietly logs out
    #: the connection that was working.
    refresh_tokens_per_account_per_client: int = 100

    #: Whether the authorising user may hold a personal Google account. They may
    #: not — the account has to belong to a Workspace organisation, which makes
    #: this a qualification question during onboarding rather than a support
    #: ticket after it.
    personal_accounts_can_authorise: bool = False

    @property
    def renew_after_hours(self) -> float:
        """When to renew a lease: half of it. Two hours, today."""
        return self.ttl_hours * self.renewal_at_fraction_of_ttl

    @property
    def renewals_per_subscription_per_day(self) -> int:
        """How often each lease is renewed, per day, forever.

        Twelve. Multiplied by every selected space in every customer, this is the
        connector's steady-state background load and the reason renewals are
        staggered rather than swept.
        """
        return int(24 / self.renew_after_hours)

    @property
    def expiration_reminder_is_reachable(self) -> bool:
        """Whether Google's expiration reminder can arrive before expiry.

        It cannot: the reminder is documented to fire twelve hours ahead and the
        lease is four hours long, so the reminder would have to precede the
        subscription. Google's own guidance is to track `expireTime` and renew,
        and this property exists so that "we'll renew when it tells us to" fails
        a test rather than a customer.
        """
        return self.documented_expiration_reminder_lead_hours < self.ttl_hours


#: The lease Google Chat actually gets, as CAIRN creates them.
GOOGLE_CHAT_SUBSCRIPTION = SubscriptionLimits()


class SuspensionReason(enum.StrEnum):
    """Why Google suspended a subscription, from its published set.

    Closed, and distinguished rather than collapsed, because the responses have
    nothing in common: three of these are the customer's decision, two are a
    credential of ours, two are our endpoint being wrong, and one is Google
    telling us it will not say. A single "suspended" count sends somebody to
    re-authorise a customer who deliberately removed us.
    """

    #: The authorising user withdrew a scope.
    USER_SCOPE_REVOKED = "USER_SCOPE_REVOKED"

    #: The user's credential no longer authenticates — expired, or the account
    #: was disabled.
    USER_AUTHORIZATION_FAILURE = "USER_AUTHORIZATION_FAILURE"

    #: The space itself is gone. Nothing to reconnect to.
    RESOURCE_DELETED = "RESOURCE_DELETED"

    #: Google could not publish to our topic. Almost always the publisher
    #: principal missing `roles/pubsub.publisher` — and the principal is the one
    #: fact in this connector that is not confirmed.
    ENDPOINT_PERMISSION_DENIED = "ENDPOINT_PERMISSION_DENIED"

    #: The topic does not exist, or not in the project Google was told.
    ENDPOINT_NOT_FOUND = "ENDPOINT_NOT_FOUND"

    #: Our topic or push endpoint is over quota. Ours, and it is back-pressure.
    ENDPOINT_RESOURCE_EXHAUSTED = "ENDPOINT_RESOURCE_EXHAUSTED"

    #: An administrator removed the application's grant organisation-wide.
    APP_SCOPE_REVOKED = "APP_SCOPE_REVOKED"

    #: The application's own credential failed.
    APP_AUTHORIZATION_FAILURE = "APP_AUTHORIZATION_FAILURE"

    #: Deliberately last and deliberately vague, like `ConnectorErrorCategory`.
    OTHER = "OTHER"


#: Google's suspension reason reduced to CAIRN's error category.
#:
#: Total over `SuspensionReason`, and a test asserts that it stays total, so a
#: reason Google adds cannot arrive as an unmapped string. The mapping is also
#: what keeps this connector off the telemetry allow-list: there is no
#: `suspension_reason` attribute and none is needed, because every reason reduces
#: to a category the exporter already accepts.
SUSPENSION_REASON_CATEGORY: Mapping[SuspensionReason, ConnectorErrorCategory] = {
    SuspensionReason.USER_SCOPE_REVOKED: ConnectorErrorCategory.PERMISSION_REVOKED,
    SuspensionReason.USER_AUTHORIZATION_FAILURE: ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
    SuspensionReason.RESOURCE_DELETED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SuspensionReason.ENDPOINT_PERMISSION_DENIED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SuspensionReason.ENDPOINT_NOT_FOUND: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SuspensionReason.ENDPOINT_RESOURCE_EXHAUSTED: ConnectorErrorCategory.RATE_LIMITED,
    SuspensionReason.APP_SCOPE_REVOKED: ConnectorErrorCategory.PERMISSION_REVOKED,
    SuspensionReason.APP_AUTHORIZATION_FAILURE: ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
    SuspensionReason.OTHER: ConnectorErrorCategory.UNKNOWN,
}


class ConnectorCategory(enum.StrEnum):
    """What kind of thing a provider is, for the surfaces that group them.

    Added with Google Meet, and the reason is a bug it would otherwise have
    caused. `release_gates._connectors_gate` used to define "chat connector" by
    subtraction — ``item is not ConnectorProvider.GITHUB`` — which was correct
    while the only three providers were GitHub, Slack and Chat. A fourth provider
    that is not a chat product silently joined that gate, so a deployment with
    Meet configured and no chat source would have read "a chat connector is
    configured" and a gate about chat coverage would have been satisfied by a
    meeting connector.

    Stated rather than inferred, because the next provider after this one will
    not be a chat product either.
    """

    #: GitHub. Code review, commits, issues.
    SOURCE_CONTROL = "source_control"

    #: Slack, Google Chat. A conversation a person can be read in.
    CHAT = "chat"

    #: Google Meet, and Zoom when it lands. Consent-gated per meeting rather than
    #: per workspace, which is why it is not a chat source with a different
    #: transport.
    MEETING = "meeting"


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

    #: What kind of source this is. Read by the release gate, which reports on
    #: chat coverage; see `ConnectorCategory` for the bug that made it explicit.
    category: ConnectorCategory = ConnectorCategory.CHAT

    #: Whether a durable per-delivery record exists for this provider. GitHub
    #: has `webhook_deliveries`; nothing else does yet.
    has_delivery_record: bool = False

    #: The provider's published limits, where it publishes any.
    limits: ProviderLimits | None = None

    #: The OAuth scopes this provider needs, with the verification tier each one
    #: costs. Empty where the provider's scopes carry no verification tier.
    scopes: tuple[OAuthScope, ...] = ()

    #: A constraint outside CAIRN's control that must be *started* before this
    #: provider can go live, stated in the gate ahead of the manual check.
    #:
    #: Distinct from `manual_verification`, which is a thing an operator can do
    #: this afternoon. A release blocker is a thing somebody else does over weeks
    #: or months — Google's restricted-scope security assessment is the example —
    #: and a deployment that has not begun it cannot ship however finished the
    #: code is. Empty for providers that have none.
    release_blocker: str = ""

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
        category=ConnectorCategory.SOURCE_CONTROL,
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
        category=ConnectorCategory.CHAT,
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
        category=ConnectorCategory.CHAT,
        settings_fields=("google_chat_project_id", "google_chat_service_account"),
        env_vars=("CAIRN_GOOGLE_CHAT_PROJECT_ID", "CAIRN_GOOGLE_CHAT_SERVICE_ACCOUNT"),
        limits=GOOGLE_CHAT_LIMITS,
        scopes=GOOGLE_CHAT_SCOPES,
        release_blocker=(
            "Google Chat cannot go live until the restricted-scope security "
            "assessment is finished: chat.messages.readonly is a RESTRICTED scope, "
            "so Google requires OAuth verification plus an independent third-party "
            "CASA security assessment ending in a Letter of Assessment, and "
            "re-assessment at least every 12 months. Assessments take weeks to "
            "months and no amount of finished code shortens one. A deployment that "
            "has not started it cannot ship this connector. Until the app is "
            "published and verified, the consent screen stays in Testing and every "
            "customer's refresh token expires after 7 days, so every connection "
            "breaks weekly."
        ),
        manual_verification=(
            "Google Chat: confirm the authorising account belongs to a Google "
            "Workspace organisation — a personal Gmail account cannot authorise "
            "this connector at all, and every configuration check passes in that "
            "state. Then add the app to one space, create the subscription, and "
            "post one message in that space."
        ),
    ),
    ProviderSpec(
        provider=ConnectorProvider.GOOGLE_MEET,
        # **Not CHAT.** The release gate reports on chat coverage, and before
        # this field existed it defined "chat" as "not GitHub" — so adding Meet
        # would have satisfied a gate about conversations with a connector that
        # reads none. See `ConnectorCategory`.
        category=ConnectorCategory.MEETING,
        settings_fields=("google_meet_project_id", "google_meet_service_account"),
        env_vars=("CAIRN_GOOGLE_MEET_PROJECT_ID", "CAIRN_GOOGLE_MEET_SERVICE_ACCOUNT"),
        limits=GOOGLE_MEET_LIMITS,
        scopes=GOOGLE_MEET_SCOPES,
        # **The connection half has no blocker; transcript retrieval does.**
        #
        # Meet's connection scope is SENSITIVE rather than RESTRICTED, so
        # announcing that a transcript exists needs OAuth verification and no CASA
        # assessment — weeks rather than months, and that half can ship. Step 36B
        # added `drive.meet.readonly`, which is RESTRICTED, so *retrieving* the
        # transcript carries Chat's blocker in full. The sentence below says which
        # half is blocked, because a blocker on the whole connector would be read
        # as "Meet cannot ship" and one on neither would be read as "all of Meet
        # can".
        release_blocker=(
            "Google Meet TRANSCRIPT RETRIEVAL cannot go live until the "
            "restricted-scope security assessment is finished: drive.meet.readonly "
            "is a RESTRICTED scope, so Google requires OAuth verification plus an "
            "independent third-party CASA security assessment ending in a Letter of "
            "Assessment, and re-assessment at least every 12 months. Assessments "
            "take weeks to months and no amount of finished code shortens one. Do "
            "not describe transcript retrieval as live before the Letter of "
            "Assessment exists. The Meet connection itself is not blocked by this "
            "— meetings.space.readonly is SENSITIVE — so a deployment may ship "
            "transcript *announcements* while this assessment is outstanding, with "
            "retrieval left unconfigured."
        ),
        manual_verification=(
            "Google Meet: connecting proves nothing on its own, because "
            "connecting grants no collection — so the check is the whole consent "
            "path. Create a capture request for one real meeting, have every "
            "invited person accept, confirm a subscription reaches 'active', "
            "hold the meeting with the host turning transcription on, and "
            "confirm one transcript announcement is recorded. Then have somebody "
            "withdraw on a second meeting and confirm the subscription is torn "
            "down on the next maintenance pass. Also confirm the Meet OAuth "
            "client is a different client from the Google Chat one: sharing it "
            "breaks both connectors at refresh time, days later."
        ),
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
# Subscription leases, in aggregate
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SubscriptionRecord:
    """One lease, reduced to the three things operations may know about it.

    **There is deliberately no identifier on this type.** Not a space name, not a
    subscription name, not the tenant, not the authorising user —
    `google_chat_subscriptions` stores all of them one column away from the
    reducer below. A caller who wanted to put a space on a screen would have to
    add a field to this dataclass, which is a visible edit to a file with a test
    that rejects it rather than a passing thought at 3am.

    The vocabulary is reused, not restated: `GoogleChatSubscriptionState` and
    `ConnectorErrorCategory` are defined next to the columns that store them, and
    a parallel enum here would be a second answer to "is this subscription
    working" that diverges at the first state Google adds.

    A value type rather than a query, for one reason stated plainly: the ORM
    models landed in `db/gchat_models.py` and **the migration that creates the
    tables has not**, and `migrations/` is not this module's to write. Wiring is
    one comprehension over the rows — `state`, `suspension_category`,
    `expire_time` — and until the tables exist, `subscription_health(None)` is
    the honest reading.
    """

    state: GoogleChatSubscriptionState

    #: Why it is suspended, errored or expired — already a category, because
    #: Google's own suspension reason quotes the resource that failed.
    #: `SUSPENSION_REASON_CATEGORY` is the reduction that produces it.
    suspension_category: ConnectorErrorCategory | None = None

    #: Google's `expireTime`. The renewal loop's only reliable input — the
    #: documented expiration reminder cannot fire inside a four-hour lease.
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SubscriptionHealth:
    """Every lease for one provider at one moment, as counts and one age.

    Answers the three questions an operator has about a renewal loop — how many
    leases are alive, how many are broken, and how long until the next one
    lapses — and answers none of the questions a support session exists for.
    Every field is an integer, an optional age, a closed-enum mapping or the
    provider; there is nowhere here to put a space.
    """

    provider: ConnectorProvider

    #: Every lease keyed by `GoogleChatSubscriptionState.value`. Grouped rather
    #: than reduced to "working / not working" for the reason
    #: `workspaces_by_state` is grouped: `suspended` is reactivatable and
    #: `expired` is gone, and a renewal loop that treats them alike spends its
    #: time renewing subscriptions that no longer exist.
    subscriptions_by_state: Mapping[str, int] = field(default_factory=dict)

    #: Leases that are not delivering, keyed by `ConnectorErrorCategory.value`.
    #: Never Google's suspension text: that names the space it failed on.
    subscriptions_by_error_category: Mapping[str, int] = field(default_factory=dict)

    #: How many leases *should* exist — one per selected space. `None` when the
    #: caller cannot say, which is not the same as zero.
    subscriptions_expected: int | None = None

    #: Minutes until the nearest live lease expires. Signed, because a negative
    #: value means one has already lapsed and clamping it to zero would hide the
    #: only case renewing cannot fix. `None` when no live lease has an expiry to
    #: count down.
    nearest_expiry_minutes: float | None = None

    #: Why the counts above are empty. Always a member of
    #: `SUBSCRIPTION_UNOBSERVABLE_REASONS`.
    subscriptions_unobservable_reason: str | None = None

    @property
    def observable(self) -> bool:
        """Whether these counts mean anything yet."""
        return self.subscriptions_unobservable_reason is None

    @property
    def subscriptions_live(self) -> int:
        """Leases Google is delivering on. Read off the state breakdown, so it
        cannot drift from its own detail."""
        return self.subscriptions_by_state.get(GoogleChatSubscriptionState.ACTIVE.value, 0)

    @property
    def subscriptions_suspended(self) -> int:
        """Recoverable, via `subscriptions.reactivate` — promptly, because how
        long a subscription stays reactivatable is undocumented."""
        return self.subscriptions_by_state.get(GoogleChatSubscriptionState.SUSPENDED.value, 0)

    @property
    def subscriptions_expired(self) -> int:
        """**Not** recoverable. Deleted at Google; that space delivers nothing
        until a subscription is created afresh."""
        return self.subscriptions_by_state.get(GoogleChatSubscriptionState.EXPIRED.value, 0)

    @property
    def subscriptions_missing(self) -> int | None:
        """Leases that should exist and do not.

        The number this aggregate exists for. An expired Chat subscription is
        deleted rather than renewed, so the live count silently falls below the
        number of selected spaces while the connection itself still reads
        `connected` and every credential check passes. Nothing else on any screen
        in this product moves when that happens.
        """
        if self.subscriptions_expected is None or not self.observable:
            return None
        return max(self.subscriptions_expected - self.subscriptions_live, 0)

    @property
    def renewal_due_within_minutes(self) -> float | None:
        """How long before the renewal loop must have run, in minutes.

        Half the lease ahead of expiry, so a failed renewal can be retried and
        still land. `None` when there is no expiry to count from.
        """
        if self.nearest_expiry_minutes is None:
            return None
        lease = GOOGLE_CHAT_SUBSCRIPTION.ttl_hours * 60
        return self.nearest_expiry_minutes - lease * (
            1 - GOOGLE_CHAT_SUBSCRIPTION.renewal_at_fraction_of_ttl
        )

    @property
    def expiry_is_permanent_loss(self) -> bool:
        """Whether letting a lease lapse costs delivery rather than time.

        True for Google Chat. The subscription is deleted and cannot be renewed,
        so the events published for that space while no subscription existed were
        never delivered anywhere and there is no backfill for them. Recorded as
        its own question for the same reason `drops_events_when_throttled` is:
        "we are behind" and "we lost that" are different incidents, and only the
        second one is a disclosure.
        """
        return not GOOGLE_CHAT_SUBSCRIPTION.expired_subscription_is_recoverable


def subscription_health(
    records: Sequence[SubscriptionRecord] | None,
    *,
    provider: ConnectorProvider = ConnectorProvider.GOOGLE_CHAT,
    expected: int | None = None,
    now: datetime | None = None,
) -> SubscriptionHealth:
    """Reduce a set of leases to counts, an age, and nothing else.

    Pure and synchronous, taking the records rather than reading them, because
    the tables behind them are created by a migration that has not landed and
    `migrations/` is not this module's to write. `records=None` is the honest
    reading until it does: empty breakdowns with a reason, never zeros — "0
    suspended, 0 expired" describes a healthy renewal loop and there is not one
    to describe.

    `expected` is the number of selected spaces, passed in rather than counted
    here. This module has no business enumerating a customer's spaces, and the
    caller that already knows how many it subscribed to can say so as an integer.
    """
    if records is None:
        return SubscriptionHealth(
            provider=provider,
            subscriptions_expected=expected,
            subscriptions_unobservable_reason=NO_SUBSCRIPTION_RECORD,
        )

    moment = now or datetime.now(UTC)

    states: dict[str, int] = {}
    categories: dict[str, int] = {}
    for item in records:
        states[item.state.value] = states.get(item.state.value, 0) + 1
        if item.suspension_category is not None:
            key = item.suspension_category.value
            categories[key] = categories.get(key, 0) + 1

    # Only live leases have an expiry worth counting down: a suspended one is
    # already not delivering and an expired one is already gone. Counting either
    # would make the nearest-expiry number *improve* at the moment a
    # subscription died.
    expiries = [
        item.expires_at
        for item in records
        if item.state is GoogleChatSubscriptionState.ACTIVE and item.expires_at is not None
    ]
    nearest = (min(expiries) - moment).total_seconds() / 60 if expiries else None

    return SubscriptionHealth(
        provider=provider,
        subscriptions_by_state=states,
        subscriptions_by_error_category=categories,
        subscriptions_expected=expected,
        nearest_expiry_minutes=nearest,
    )


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


connector_subscription_renewals = meter.create_counter(
    "cairn.connector.subscription_renewals",
    description="Subscription lease renewals attempted for a provider, by outcome",
)


def record_subscription_renewal(*, source: ConnectorProvider, outcome: str) -> None:
    """One renewal attempt on one lease.

    Counted rather than logged because it is the highest-frequency piece of
    machine work in this connector — twelve renewals per selected space per day,
    forever — and the only way to see the renewal loop failing before a lease
    lapses. A failed renewal is recoverable; a lapsed lease is not.

    Carries `source` and `outcome` and nothing else. There is deliberately no
    attribute for which lease was renewed: a subscription names a space, a space
    is a customer's conversation, and the telemetry allow-list has no entry that
    could carry one.
    """
    connector_subscription_renewals.add(1, safe({"source": source.value, "outcome": outcome}))


def record_subscription_suspended(*, source: ConnectorProvider, reason: SuspensionReason) -> None:
    """One suspended lease, reduced to a category before it can leave.

    Google's suspension reason is a closed set and would be safe to export, but
    it is not on the telemetry allow-list and this module does not own that file.
    `SUSPENSION_REASON_CATEGORY` maps every reason onto a `ConnectorErrorCategory`
    the exporter already accepts, so the alert fires with no new attribute — and
    the full reason stays inside the product, on the subscription aggregate,
    where an operator with the `engineering` or `security` role can read it.
    """
    record_connector_error(source=source, category=SUSPENSION_REASON_CATEGORY[reason])


__all__ = [
    "COUNT_WINDOW",
    "DELIVERY_UNOBSERVABLE_REASONS",
    "GOOGLE_CHAT_LIMITS",
    "GOOGLE_CHAT_SCOPES",
    "GOOGLE_CHAT_SUBSCRIPTION",
    "GOOGLE_MEET_LIMITS",
    "GOOGLE_MEET_SCOPES",
    "GOOGLE_MEET_TRANSCRIPT_SCOPES",
    "LIVE_STATES",
    "NO_DELIVERY_RECORD",
    "NO_SUBSCRIPTION_RECORD",
    "PROVIDERS",
    "RESTRICTED_SCOPE_REVERIFICATION_MONTHS",
    "SLACK_LIMITS",
    "SUBSCRIPTION_UNOBSERVABLE_REASONS",
    "SUSPENSION_REASON_CATEGORY",
    "ConnectionHealth",
    "ConnectionState",
    "ConnectorCategory",
    "ConnectorErrorCategory",
    "ConnectorFleet",
    "ConnectorHealth",
    "ConnectorProvider",
    "GoogleChatSubscriptionState",
    "OAuthScope",
    "ProviderLimits",
    "ProviderSpec",
    "ScopeTier",
    "SubscriptionHealth",
    "SubscriptionLimits",
    "SubscriptionRecord",
    "SuspensionReason",
    "configured_providers",
    "connector_health",
    "missing_credentials",
    "record_connector_delivery",
    "record_connector_error",
    "record_connector_rate_limited",
    "record_subscription_renewal",
    "record_subscription_suspended",
    "spec",
    "subscription_health",
]
