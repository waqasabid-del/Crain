"""One Workspace Events lease per selected space, kept alive by the maintenance loop.

A Google Chat subscription is **a lease, not a webhook registration**. It is
created for one space, it expires, and nothing about it is permanent — which
makes this file's subject the renewal, not the creation.

**The lease is four hours, and that is a choice.** CAIRN creates subscriptions
with ``payloadOptions.includeResource: true``, and Google caps such a
subscription at four hours unless the application holds domain-wide delegation —
an administrator granting one application the right to impersonate every user in
the organisation, which is a far larger grant than this product needs and is out
of scope. The alternative is ``includeResource: false``, which buys a seven-day
lease and costs a ``spaces.messages.get`` **per message**, against a ceiling of
3,000 reads per project per 60 seconds shared by every customer on the Cloud
project. A per-project ceiling everybody shares is a harder wall than a renewal
loop: crossing it throttles every tenant at once, and the events dropped in the
meantime are gone. So CAIRN keeps the resource on the event and renews often.
The constants live in `ops/connectors.GOOGLE_CHAT_SUBSCRIPTION` and are read
here rather than restated, so a runbook, an alert threshold and this loop cannot
drift apart.

**Nothing waits for a lifecycle event.** Google publishes an expiration reminder
twelve hours before a lease lapses, which at a four-hour lease is structurally
impossible — the reminder would have to precede the subscription. Google's own
guidance is to track ``expireTime`` and renew, so ``expire_time`` on the row is
the loop's only input and there is no code path here that reacts to a reminder.

**An expired subscription is deleted, permanently, and cannot be renewed.** That
is the single fact that shapes the state machine below: renewal and recreation
are different calls, a ``PATCH`` against a lapsed subscription is a 404, and the
events published for that space while no subscription existed were never
delivered anywhere and cannot be fetched back. Lapsing costs data, not time,
which is why the renewal margin is generous and why `renewal_due_at` is
asserted against it by a test rather than tuned by feel.

**Renewals are staggered, because Workspace Events publishes no rate limits.**
Every lease renews twelve times a day forever; multiplied by every selected space
in every customer, a single unstaggered sweep is exactly the shape most likely to
find an undocumented limit. Each subscription therefore has a deterministic
offset derived from its own id (`renewal_due_at`), spreading the herd across
passes, and calls inside one pass are separated by a short random delay.

**Suspension is not failure, and the distinction is the customer's.** Google
suspends a subscription it will still let us reactivate; the reason says whether
reactivating can possibly work, and `SUSPENSION_REASON_CATEGORY` — defined once,
in `ops/connectors.py`, next to the rest of the published facts — reduces it to
the closed category the product reports on. **No Google string reaches a column,
a log field or a span from this file.** Google's messages quote the resource that
failed, which here means a space's display name and the authorising person's
address.

**The local record is the authority for what CAIRN processes.** Deleting a
subscription marks the row before it calls Google and never reverts it, so a
customer who deselects a space or disconnects the connector stops being read
*immediately*, whether or not Google can be reached. The remote lease then dies
on its own within four hours because nothing renews it, and anything it delivers
in the meantime is refused by `resolve_space`.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol, final

import httpx
import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from cairn_api.config import Settings, get_settings
from cairn_api.connectors.credentials import SecretValue
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.gchat_models import (
    SPACE_NAME_PATTERN,
    GoogleChatSpaceSelection,
    GoogleChatSubscription,
    GoogleChatSubscriptionState,
)
from cairn_api.gchat.oauth import (
    REQUEST_TIMEOUT_SECONDS,
    GoogleChatApi,
    GoogleChatInstallError,
    GoogleChatInstallFailure,
    access_token_for,
)
from cairn_api.gchat.pubsub import PROVIDER, SpaceSubscription
from cairn_api.ops.connectors import (
    GOOGLE_CHAT_SUBSCRIPTION,
    SUSPENSION_REASON_CATEGORY,
    SubscriptionRecord,
    SuspensionReason,
    record_subscription_renewal,
)
from cairn_api.telemetry import spans

logger = structlog.get_logger(__name__)

#: The Workspace Events API. One version, pinned: ``v1`` is what the request and
#: response shapes below are written against.
API_BASE: Final = "https://workspaceevents.googleapis.com/v1"
SUBSCRIPTIONS_URL: Final = f"{API_BASE}/subscriptions"

#: The three event types CAIRN subscribes to, and the complete list.
#:
#: Messages only. There is deliberately no membership, reaction, space or
#: attachment event here: a subscription is created per selected space and the
#: product reads what was said in it, so an event type nobody consumes would be
#: traffic through the ingestion path carrying material nobody selected a space
#: for. ``updated`` and ``deleted`` are included because a record that shows an
#: edited message as it was first posted is a record that misquotes somebody.
EVENT_TYPES: Final[tuple[str, ...]] = (
    "google.workspace.chat.message.v1.created",
    "google.workspace.chat.message.v1.updated",
    "google.workspace.chat.message.v1.deleted",
)

#: The ``targetResource`` prefix. A full resource URI, not a bare space name —
#: Google rejects the second, with an error that does not say which.
TARGET_RESOURCE_PREFIX: Final = "//chat.googleapis.com/"

#: ``ttl: "0s"`` means "the maximum this subscription can have", on both create
#: and renew. It is **not** zero seconds, and it is the one string in this file
#: that reads as a bug to somebody who has not read the documentation.
MAX_TTL: Final = "0s"

#: The Pub/Sub topic Google publishes to, as ``projects/P/topics/T``.
#:
#: Read from the environment rather than from `Settings`, exactly as
#: `gchat/pubsub.py` reads its audience: Step 33 does not own ``config.py``.
#: Absent, nothing is created — a subscription pointed at no topic is a lease
#: that consumes quota and delivers nowhere.
TOPIC_VAR: Final = "CAIRN_GCHAT_EVENTS_TOPIC"

#: The lease, as CAIRN creates them.
TTL: Final = timedelta(hours=GOOGLE_CHAT_SUBSCRIPTION.ttl_hours)

#: How far ahead of expiry a lease becomes renewable: half the lease, two hours.
#: Two hours of slack means a renewal can fail outright, be retried on the next
#: pass, and still land — and a lapse cannot be retried at all.
RENEWAL_LEAD: Final = timedelta(hours=GOOGLE_CHAT_SUBSCRIPTION.renew_after_hours)

#: How far renewals are spread across passes. Deterministic per subscription —
#: see `renewal_due_at` — so the spread is a property of the row rather than of
#: the moment a pass happened to run, and so a test can assert the margin.
RENEWAL_JITTER: Final = timedelta(minutes=15)

#: How often the renewal pass runs, mirroring ``jobs/main.MAINTENANCE_INTERVAL_SECONDS``.
#: Stated here because the margin below is computed from it; a test asserts the
#: two agree, so shortening the maintenance loop cannot silently eat the margin.
PASS_INTERVAL: Final = timedelta(hours=1)

#: The worst case: a lease that became due immediately after a pass, with the
#: largest possible jitter, renewed on the following pass. Forty-five minutes.
#: Positive by construction, and asserted, because a negative margin here is a
#: renewal loop that lets leases lapse and calls it success.
MINIMUM_RENEWAL_MARGIN: Final = RENEWAL_LEAD - RENEWAL_JITTER - PASS_INTERVAL

#: Rows claimed per tenant per pass. A bound, so one customer with a thousand
#: spaces cannot hold a transaction open across every other customer's renewals.
RENEWAL_BATCH: Final = 100

#: The largest random pause between two calls inside one pass. Small, because it
#: is only breaking up simultaneity; the real spreading is `renewal_due_at`.
STAGGER_SECONDS: Final = 0.5

_SPACE_NAME = re.compile(SPACE_NAME_PATTERN)

#: Google's own subscription states, as strings on the wire.
_REMOTE_SUSPENDED: Final = "SUSPENDED"
_REMOTE_DELETED: Final = "DELETED"


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


class SubscriptionFailure(StrEnum):
    """Why a Workspace Events call did not do what was asked, as a bounded code.

    Coarser than Google's error space on purpose, and derived from the **status
    code alone**. The response body names the space and frequently the person,
    and this is the code path where the temptation to pass it through is
    strongest because the status is less informative — so the body is never read.

    ``GONE`` is the one worth its own value. A 404 on a renewal does not mean
    "try again", it means the lease lapsed and Google deleted it, and the only
    recovery is to create a new subscription. Folding it into a generic rejection
    produces a loop that patches a subscription that no longer exists, forever,
    while the space delivers nothing.
    """

    #: The subscription does not exist any more. Recreate; never patch.
    GONE = "gone"

    #: Google refused the call for this authorisation.
    PERMISSION_DENIED = "permission_denied"

    #: The standing authorisation is gone. Reconnect; nothing retries out of it.
    AUTHORISATION_EXPIRED = "authorisation_expired"

    #: Throttled. Time fixes this one and nothing else does.
    RATE_LIMITED = "rate_limited"

    #: Google was unreachable, slow, or answered with something unparseable.
    PROVIDER_UNAVAILABLE = "provider_unavailable"

    #: Google rejected the request itself — a malformed target, a topic it will
    #: not publish to, a subscription this client may not touch.
    REQUEST_REJECTED = "request_rejected"

    #: This deployment has no Pub/Sub topic, or no Google credentials. An
    #: operator problem, and it must not present as "Google said no".
    NOT_CONFIGURED = "not_configured"


#: What each failure reports as in the vocabulary the rest of the product reads.
#:
#: Total over `SubscriptionFailure`, asserted by a test, so a value added later
#: cannot arrive at a column as ``None`` and read as "nothing wrong".
_FAILURE_CATEGORIES: Mapping[SubscriptionFailure, ConnectorErrorCategory] = {
    # The lease is gone and the endpoint or target is what has to change. Not
    # `PROVIDER_UNAVAILABLE`: nothing about this is transient.
    SubscriptionFailure.GONE: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SubscriptionFailure.PERMISSION_DENIED: ConnectorErrorCategory.PERMISSION_REVOKED,
    SubscriptionFailure.AUTHORISATION_EXPIRED: ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
    SubscriptionFailure.RATE_LIMITED: ConnectorErrorCategory.RATE_LIMITED,
    SubscriptionFailure.PROVIDER_UNAVAILABLE: ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
    SubscriptionFailure.REQUEST_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SubscriptionFailure.NOT_CONFIGURED: ConnectorErrorCategory.CONFIGURATION_INVALID,
}

#: Categories a later pass may retry unattended.
#:
#: The others — a revoked permission, a lapsed authorisation, an invalid
#: configuration — are fixed by a person reconnecting, reselecting a space or
#: correcting a topic grant, and retrying them hourly forever spends a
#: customer's quota to produce the same refusal. Each of those paths ends in
#: `ensure_subscription`, which resets the row.
_RETRYABLE_CATEGORIES: frozenset[ConnectorErrorCategory] = frozenset(
    {
        ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
        ConnectorErrorCategory.RATE_LIMITED,
        ConnectorErrorCategory.UNKNOWN,
    }
)

#: Suspension reasons CAIRN may answer with `subscriptions.reactivate`.
#:
#: The endpoint family is here because every one of them is fixed *outside*
#: CAIRN — an IAM binding on the topic, a topic that was recreated, a quota that
#: refills — and once it is fixed the next pass reactivates with no human
#: touching CAIRN at all. The publisher principal for Workspace-Events-on-Chat is
#: **not confirmed** in Google's documentation, and granting the wrong one
#: surfaces here as ``ENDPOINT_PERMISSION_DENIED`` rather than as a configuration
#: error, so this is the path that recovers the most likely misconfiguration in
#: the whole connector. ``OTHER`` is included for the same reason it exists:
#: Google declining to say is not evidence that retrying cannot work.
#:
#: The rest are excluded because reactivating cannot succeed until a person
#: acts: a deleted space has nothing to subscribe to, and a withdrawn scope or a
#: failed credential needs a fresh authorisation. Reactivating those would
#: re-suspend within seconds and hide the reason behind a churn of state changes.
#:
#: **How long a suspended subscription stays reactivatable is not documented.**
#: This code assumes it dies at ``expire_time`` like any other lease — so a
#: suspended row is attempted on every pass rather than queued, and once it
#: lapses it is recreated rather than reactivated.
REACTIVATABLE_REASONS: frozenset[SuspensionReason] = frozenset(
    {
        SuspensionReason.ENDPOINT_PERMISSION_DENIED,
        SuspensionReason.ENDPOINT_NOT_FOUND,
        SuspensionReason.ENDPOINT_RESOURCE_EXHAUSTED,
        SuspensionReason.OTHER,
    }
)


def category_for(failure: SubscriptionFailure) -> ConnectorErrorCategory:
    """The bounded category a failure reports as.

    A function rather than a mapping other modules reach into, so there is one
    reader and no caller can grow a second opinion about what ``gone`` means.
    """
    return _FAILURE_CATEGORIES[failure]


@final
class SubscriptionError(Exception):
    """A Workspace Events call that did not do what was asked.

    Carries a bounded failure and its category and **nothing from Google**. The
    message is assembled from our own enum value, so even a traceback that ends
    up in a log line contains no space name and no address.
    """

    def __init__(self, failure: SubscriptionFailure) -> None:
        self.failure = failure
        self.category = _FAILURE_CATEGORIES[failure]
        super().__init__(f"google chat subscription: {failure.value}")


#: How an OAuth-layer failure arrives here. `access_token_for` raises
#: `GoogleChatInstallError`, which is the install vocabulary; translating at this
#: one boundary keeps the renewal loop speaking a single language rather than
#: catching two exception types at every call site.
_INSTALL_FAILURES: Mapping[GoogleChatInstallFailure, SubscriptionFailure] = {
    GoogleChatInstallFailure.AUTHORISATION_EXPIRED: SubscriptionFailure.AUTHORISATION_EXPIRED,
    GoogleChatInstallFailure.ACCESS_FORBIDDEN: SubscriptionFailure.PERMISSION_DENIED,
    GoogleChatInstallFailure.SCOPES_INSUFFICIENT: SubscriptionFailure.PERMISSION_DENIED,
    GoogleChatInstallFailure.SCOPES_UNEXPECTED: SubscriptionFailure.PERMISSION_DENIED,
    GoogleChatInstallFailure.RATE_LIMITED: SubscriptionFailure.RATE_LIMITED,
    GoogleChatInstallFailure.PROVIDER_UNAVAILABLE: SubscriptionFailure.PROVIDER_UNAVAILABLE,
    GoogleChatInstallFailure.NOT_CONFIGURED: SubscriptionFailure.NOT_CONFIGURED,
}


def _from_install_error(error: GoogleChatInstallError) -> SubscriptionError:
    """Translate an install-layer failure, defaulting to a rejected request."""
    return SubscriptionError(
        _INSTALL_FAILURES.get(error.failure, SubscriptionFailure.REQUEST_REJECTED)
    )


# ---------------------------------------------------------------------------
# The network boundary
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class RemoteSubscription:
    """One subscription as Google described it just now.

    A transport object. Note what is absent: no space display name, no
    ``suspensionReason`` string — the reason is parsed into `SuspensionReason`
    at the boundary and the unrecognised ones become ``OTHER``, so nothing
    downstream can store a word Google chose.
    """

    #: ``subscriptions/{id}``.
    name: str

    #: Google's ``expireTime``. ``None`` only if Google omitted it, which is not
    #: a shape this client is built for and is treated as "renew immediately".
    expire_time: datetime | None

    #: Reduced to the states CAIRN records. Google's ``STATE_UNSPECIFIED`` and an
    #: absent field both read as ``ACTIVE``: the call succeeded and returned a
    #: subscription, and treating that as broken would suspend a working lease.
    state: GoogleChatSubscriptionState

    #: Set only when ``state`` is ``SUSPENDED``.
    suspension_reason: SuspensionReason | None = None


class WorkspaceEventsApi(Protocol):
    """Every Workspace Events call this connector makes.

    A protocol with four methods, so a test supplies an object instead of
    patching a module global or intercepting a transport — the same split
    `gchat/oauth.py` uses, and for the same reason: "no unit test calls Google"
    becomes a property of the structure rather than of everyone remembering.

    Implementations raise `SubscriptionError` and nothing else.
    """

    async def create(
        self, *, access_token: SecretValue, space_name: str, topic: str
    ) -> RemoteSubscription | None:
        """Create a subscription for one space. ``None`` if the long-running
        operation has not completed — the caller leaves the row ``PENDING``."""
        ...

    async def renew(
        self, *, access_token: SecretValue, subscription_name: str
    ) -> RemoteSubscription | None:
        """Reset a lease to its maximum ``ttl``."""
        ...

    async def reactivate(
        self, *, access_token: SecretValue, subscription_name: str
    ) -> RemoteSubscription | None:
        """Bring a suspended subscription back. The expiry is **not** extended."""
        ...

    async def delete(self, *, access_token: SecretValue, subscription_name: str) -> None:
        """Delete a subscription. Idempotent: already gone is success."""
        ...


@final
class HttpWorkspaceEventsApi:
    """The real one. The only code in CAIRN that calls Workspace Events."""

    __slots__ = ()

    async def create(
        self, *, access_token: SecretValue, space_name: str, topic: str
    ) -> RemoteSubscription | None:
        payload = await self._request(
            "POST",
            SUBSCRIPTIONS_URL,
            access_token=access_token,
            json={
                "targetResource": f"{TARGET_RESOURCE_PREFIX}{space_name}",
                # A list rather than a set: this is the request body, and a set's
                # iteration order would make two identical installs send
                # different bytes.
                "eventTypes": list(EVENT_TYPES),
                "notificationEndpoint": {"pubsubTopic": topic},
                # The four-hour lease is the price of this line. See the module
                # docstring for what the seven-day alternative costs.
                "payloadOptions": {"includeResource": True},
                "ttl": MAX_TTL,
            },
        )
        return _remote_from_operation(payload)

    async def renew(
        self, *, access_token: SecretValue, subscription_name: str
    ) -> RemoteSubscription | None:
        payload = await self._request(
            "PATCH",
            f"{API_BASE}/{subscription_name}",
            access_token=access_token,
            # Only the ttl. Without the mask Google would treat every absent
            # field as cleared, including the event types.
            params={"updateMask": "ttl"},
            json={"ttl": MAX_TTL},
        )
        return _remote_from_operation(payload)

    async def reactivate(
        self, *, access_token: SecretValue, subscription_name: str
    ) -> RemoteSubscription | None:
        payload = await self._request(
            "POST",
            f"{API_BASE}/{subscription_name}:reactivate",
            access_token=access_token,
            json={},
        )
        return _remote_from_operation(payload)

    async def delete(self, *, access_token: SecretValue, subscription_name: str) -> None:
        try:
            await self._request(
                "DELETE", f"{API_BASE}/{subscription_name}", access_token=access_token
            )
        except SubscriptionError as error:
            if error.failure is SubscriptionFailure.GONE:
                # Already deleted is the outcome that was asked for. Raising here
                # would make a retry of a partially-applied deselection fail
                # forever on the one subscription that is already correct.
                return
            raise

    async def _request(
        self,
        method: str,
        url: str,
        *,
        access_token: SecretValue,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.request(
                    method,
                    url,
                    params=dict(params) if params else None,
                    json=dict(json) if json is not None else None,
                    # `reveal()` at the one point the credential has to leave the
                    # wrapper, which is what makes it greppable.
                    headers={"Authorization": f"Bearer {access_token.reveal()}"},
                )
            except httpx.HTTPError as exc:
                raise SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE) from exc
        return _body(response)


def _body(response: httpx.Response) -> Mapping[str, object]:
    """Read a Workspace Events response, mapping by **status code alone**.

    Deliberately never reads ``error.message``. That string quotes the target
    resource — a space, and with it the display name a customer chose — and the
    status code is enough for every action anyone can take.
    """
    status = response.status_code
    if status == httpx.codes.UNAUTHORIZED:
        raise SubscriptionError(SubscriptionFailure.AUTHORISATION_EXPIRED)
    if status == httpx.codes.FORBIDDEN:
        raise SubscriptionError(SubscriptionFailure.PERMISSION_DENIED)
    if status in (httpx.codes.NOT_FOUND, httpx.codes.GONE):
        raise SubscriptionError(SubscriptionFailure.GONE)
    if status == httpx.codes.TOO_MANY_REQUESTS:
        raise SubscriptionError(SubscriptionFailure.RATE_LIMITED)
    if status >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE)
    if status >= httpx.codes.BAD_REQUEST:
        raise SubscriptionError(SubscriptionFailure.REQUEST_REJECTED)

    try:
        payload: object = response.json()
    except ValueError as exc:
        raise SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE) from exc
    if not isinstance(payload, dict):
        # An HTML proxy page or an outage splash. Unavailability rather than a
        # rejected request, which would send an operator hunting our config.
        raise SubscriptionError(SubscriptionFailure.PROVIDER_UNAVAILABLE)
    return payload


def _remote_from_operation(payload: Mapping[str, object]) -> RemoteSubscription | None:
    """Read the ``Subscription`` out of a long-running ``Operation``.

    Create, patch and reactivate all return an ``Operation``. In practice Chat's
    complete synchronously and carry ``done: true`` with the subscription in
    ``response``; a body that is already a subscription is accepted too, so a
    future synchronous response does not read as an unfinished operation.

    ``None`` means "not finished". The caller leaves the row ``PENDING`` rather
    than inventing a subscription name, because a placeholder is a value the
    renewal loop would then try to renew.
    """
    response = payload.get("response")
    if isinstance(response, dict) and _text(response.get("name")):
        return _remote_from(response)
    if _text(payload.get("name")) and "eventTypes" in payload:
        return _remote_from(payload)
    return None


def _remote_from(payload: Mapping[str, object]) -> RemoteSubscription | None:
    name = _text(payload.get("name"))
    if name is None:
        return None
    raw_state = _text(payload.get("state")) or ""
    if raw_state == _REMOTE_DELETED:
        state = GoogleChatSubscriptionState.DELETED
    elif raw_state == _REMOTE_SUSPENDED:
        state = GoogleChatSubscriptionState.SUSPENDED
    else:
        state = GoogleChatSubscriptionState.ACTIVE
    return RemoteSubscription(
        name=name,
        expire_time=_parse_time(payload.get("expireTime")),
        state=state,
        suspension_reason=(
            _suspension_reason(payload.get("suspensionReason"))
            if state is GoogleChatSubscriptionState.SUSPENDED
            else None
        ),
    )


def _suspension_reason(raw: object) -> SuspensionReason:
    """Google's reason as a closed value. Anything unrecognised is ``OTHER``.

    The raw string is read here and goes no further — not into the exception,
    not into a log field, not into the row. A reason Google adds tomorrow is an
    ``OTHER`` we handle rather than a string in a column nobody reviewed.
    """
    if not isinstance(raw, str):
        return SuspensionReason.OTHER
    try:
        return SuspensionReason(raw.strip())
    except ValueError:
        return SuspensionReason.OTHER


def _parse_time(raw: object) -> datetime | None:
    """An RFC 3339 timestamp, always timezone-aware.

    Google sends up to nine fractional digits and `datetime.fromisoformat`
    accepts at most six, so the fraction is truncated rather than the whole
    timestamp discarded — losing nanoseconds on a four-hour lease costs nothing,
    and losing the expiry entirely would make the lease unrenewable.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    match = re.fullmatch(r"(.*\.\d{1,6})\d*(Z|[+-]\d{2}:?\d{2})", text)
    if match:
        text = f"{match.group(1)}{match.group(2)}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _text(value: object) -> str | None:
    """A non-empty string, or nothing."""
    return value if isinstance(value, str) and value else None


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class SubscriptionClient:
    """Everything a lifecycle operation needs from outside the database.

    Two protocols rather than one: `tokens` is the OAuth client that turns a
    stored refresh token into an access token, `events` is the Workspace Events
    client. They are separate services with separate failure modes, and merging
    them would mean a test double for one had to implement the other.
    """

    tokens: GoogleChatApi
    events: WorkspaceEventsApi

    #: ``projects/P/topics/T``. Held on the client rather than read at each call
    #: site, so there is one place a deployment's topic comes from.
    topic: str


def configured_topic(override: str | None = None, settings: Settings | None = None) -> str:
    """The Pub/Sub topic Google should publish to, or an empty string.

    Settings first, environment second. The setting is validated once at startup,
    which is where a malformed topic should be caught; the environment variable
    remains as an override so a deployment can point one worker at a different
    topic without a config change, and so this kept working while `config.py`
    was landing.
    """
    if override:
        return override

    resolved = settings or get_settings()
    from_settings = str(getattr(resolved, "google_chat_pubsub_topic", "") or "")
    return from_settings or os.environ.get(TOPIC_VAR, "")


def build_client(
    settings: Settings | None = None, *, topic: str | None = None
) -> SubscriptionClient | None:
    """The production client, or ``None`` when this deployment cannot subscribe.

    ``None`` rather than an exception, because the caller is a maintenance loop
    that runs on every deployment including the ones with no Google Chat
    credentials at all. A loop that raised there would fill the log with a
    failure nobody can act on and would mask the ones somebody can.

    A deployment with credentials but no topic returns ``None`` too: a
    subscription pointed at no topic is a lease that consumes quota and delivers
    nowhere, which reads as connected and produces nothing.
    """
    from cairn_api.gchat.oauth import HttpGoogleChatApi

    resolved = settings or get_settings()
    client_id = resolved.google_chat_client_id
    client_secret = resolved.google_chat_client_secret
    resolved_topic = configured_topic(topic, resolved)
    if not client_id or not client_secret or not resolved_topic:
        return None
    return SubscriptionClient(
        tokens=HttpGoogleChatApi(client_id=client_id, client_secret=client_secret),
        events=HttpWorkspaceEventsApi(),
        topic=resolved_topic,
    )


async def _access_token(client: SubscriptionClient, connection: SourceConnection) -> SecretValue:
    """A usable access token, with the install vocabulary translated."""
    try:
        return await access_token_for(client.tokens, connection)
    except GoogleChatInstallError as error:
        raise _from_install_error(error) from error


# ---------------------------------------------------------------------------
# When a lease is due
# ---------------------------------------------------------------------------


def _renewal_offset(subscription_id: uuid.UUID) -> timedelta:
    """This subscription's place in the queue, derived from its own id.

    Deterministic rather than random, and that is the point. A random offset
    chosen per pass would move every lease every hour, so nothing would ever be
    reliably spread and no test could assert the margin. A digest of the id gives
    a stable position in the window that differs between subscriptions, between
    tenants, and between one space and the next in the same tenant.
    """
    digest = hashlib.sha256(subscription_id.bytes).digest()
    return timedelta(
        seconds=int.from_bytes(digest[:4], "big") % int(RENEWAL_JITTER.total_seconds())
    )


def renewal_due_at(subscription: GoogleChatSubscription) -> datetime | None:
    """When this lease should be renewed, or ``None`` if it has no expiry.

    Half a lease before expiry, plus this subscription's own offset. The offset
    is *added*, never subtracted, so the jitter can only ever move a renewal
    earlier relative to the expiry it is protecting — and the worst case is
    `MINIMUM_RENEWAL_MARGIN`, forty-five minutes of slack after allowing for a
    pass that just missed it.
    """
    if subscription.expire_time is None:
        return None
    return subscription.expire_time - RENEWAL_LEAD + _renewal_offset(subscription.id)


def is_due(subscription: GoogleChatSubscription, *, now: datetime) -> bool:
    """Whether this pass should touch this subscription.

    Anything that is not ``ACTIVE`` is due immediately: a pending create, a
    suspension waiting on reactivation and an expired lease are all states where
    a space is delivering nothing, and waiting for a renewal window that is
    computed from an expiry it may not even have would be waiting for nothing.
    """
    if subscription.state is not GoogleChatSubscriptionState.ACTIVE:
        return True
    due = renewal_due_at(subscription)
    return due is None or due <= now


# ---------------------------------------------------------------------------
# Health, per space and per connection
# ---------------------------------------------------------------------------

#: States in which a space is not receiving events. ``PENDING`` is deliberately
#: absent: it is the window between selecting a space and Google acknowledging a
#: subscription, which is normal for seconds and is not a fault.
BROKEN_STATES: frozenset[GoogleChatSubscriptionState] = frozenset(
    {
        GoogleChatSubscriptionState.SUSPENDED,
        GoogleChatSubscriptionState.EXPIRED,
        GoogleChatSubscriptionState.ERROR,
    }
)


async def _connection_subscriptions(
    db: AsyncSession, *, tenant_id: uuid.UUID, connection_id: uuid.UUID
) -> Sequence[GoogleChatSubscription]:
    """Every subscription for one connection that has not been deleted."""
    rows = await db.scalars(
        select(GoogleChatSubscription).where(
            GoogleChatSubscription.tenant_id == tenant_id,
            GoogleChatSubscription.connection_id == connection_id,
            GoogleChatSubscription.state != GoogleChatSubscriptionState.DELETED,
        )
    )
    return rows.all()


async def refresh_connection_health(
    db: AsyncSession, connection: SourceConnection, *, now: datetime | None = None
) -> ConnectionHealth:
    """Recompute a connection's health from its spaces, and record it.

    **One broken space is not a healthy connection, and it is not a wholly
    broken one either.** A connection with four delivering spaces and one whose
    renewal failed is ``DEGRADED``: reporting it healthy hides a permanent hole
    in a customer's record, and reporting it failing sends somebody to reconnect
    an authorisation that is perfectly fine. `ConnectionHealth` already has the
    word for the middle case, and this is what it is for.

    Recovery does **not** invent a green tick. When nothing is broken any more,
    health returns to ``HEALTHY`` only if data has actually arrived at some
    point; otherwise ``UNKNOWN``, because a lease that exists has proved nothing
    about delivery. `pubsub.record_healthy_delivery` is the only thing entitled
    to claim otherwise, and it runs when a message actually lands.
    """
    moment = now or datetime.now(UTC)
    subscriptions = await _connection_subscriptions(
        db, tenant_id=connection.tenant_id, connection_id=connection.id
    )

    broken = [item for item in subscriptions if item.state in BROKEN_STATES]
    delivering = [
        item for item in subscriptions if item.state is GoogleChatSubscriptionState.ACTIVE
    ]

    if not broken:
        connection.health = (
            ConnectionHealth.HEALTHY
            if connection.last_successful_sync_at is not None
            else ConnectionHealth.UNKNOWN
        )
        connection.last_error_category = None
        return connection.health

    connection.health = ConnectionHealth.DEGRADED if delivering else ConnectionHealth.FAILING
    # The most recently changed broken space decides the category. An older
    # failure's category would describe a problem somebody has already fixed.
    latest = max(broken, key=lambda item: item.state_changed_at or moment)
    connection.last_error_category = latest.suspension_category or ConnectorErrorCategory.UNKNOWN
    connection.last_error_at = moment
    return connection.health


async def subscription_records(
    db: AsyncSession, *, tenant_id: uuid.UUID
) -> tuple[SubscriptionRecord, ...]:
    """One workspace's leases, reduced to what operations may know.

    The wiring `ops/connectors.subscription_health` was written to receive: a
    state, a category and an expiry per lease, and **no identifier at all**. The
    reduction happens in this comprehension rather than in the read model, so the
    type an operator's screen is built on has nowhere to put a space name.
    """
    rows = await db.scalars(
        select(GoogleChatSubscription).where(GoogleChatSubscription.tenant_id == tenant_id)
    )
    return tuple(
        SubscriptionRecord(
            state=row.state,
            suspension_category=row.suspension_category,
            expires_at=row.expire_time,
        )
        for row in rows.all()
    )


async def _subscription_for_space(
    db: AsyncSession, *, space_name: str
) -> GoogleChatSubscription | None:
    """The subscription row for a space, if there is one.

    Deliberately not scoped by tenant, and safe to be: a space resource name is
    globally unique and `google_chat_space_selections` carries a global unique
    constraint on it, so this resolves to one workspace's row or to none.
    """
    row: GoogleChatSubscription | None = await db.scalar(
        select(GoogleChatSubscription).where(GoogleChatSubscription.space_name == space_name)
    )
    return row


async def is_space_delivering(db: AsyncSession, *, space_name: str) -> bool:
    """Whether CAIRN currently expects events for this space.

    Narrower than "is it permitted". A space whose renewal failed is still
    permitted — the customer selected it and has not changed their mind — but it
    is not delivering, and a screen that conflates the two tells a customer their
    feed is fine while it has a hole in it.
    """
    row = await _subscription_for_space(db, space_name=space_name)
    return row is not None and row.state is GoogleChatSubscriptionState.ACTIVE


# ---------------------------------------------------------------------------
# What ingestion is allowed to ask
# ---------------------------------------------------------------------------


async def resolve_space(db: AsyncSession, *, space_name: str) -> SpaceSubscription | None:
    """Which workspace, if any, may have this space read right now.

    The hook `gchat/pubsub.StoredSpaceRegistry` resolves by name, and the only
    question ingestion is allowed to ask.

    **The selection is the authority.** No selection row means ``None`` —
    unknown, deselected and never-selected are one answer, because from
    ingestion's side they are one decision. The subscription row is consulted
    only to *withdraw* permission, never to grant it: a lease that outlived a
    deselection must read nothing, which is why `remove_subscription` marks the
    row before it calls Google and why a failed remote delete cannot leave a
    space readable.

    ``active=False`` rather than ``None`` when the space is still selected but
    must not be read — the connection was disconnected or revoked, or CAIRN
    deleted the subscription. The two are kept apart because one is a stranger
    and the other is a customer who turned us off, and capturing the second is a
    consent failure rather than a mystery.
    """
    found = (
        await db.execute(
            select(GoogleChatSpaceSelection, SourceConnection)
            .join(SourceConnection, SourceConnection.id == GoogleChatSpaceSelection.connection_id)
            .where(GoogleChatSpaceSelection.space_name == space_name)
        )
    ).first()
    if found is None:
        return None

    selection, connection = found
    subscription = await _subscription_for_space(db, space_name=space_name)
    stopped = subscription is not None and subscription.state is GoogleChatSubscriptionState.DELETED

    return SpaceSubscription(
        tenant_id=selection.tenant_id,
        connection_id=selection.connection_id,
        space_name=selection.space_name,
        active=connection.is_active and not stopped,
    )


# ---------------------------------------------------------------------------
# Create, on selection
# ---------------------------------------------------------------------------


async def _locked_subscription(
    db: AsyncSession, *, tenant_id: uuid.UUID, connection_id: uuid.UUID, space_name: str
) -> GoogleChatSubscription | None:
    """This space's row, locked for the rest of the transaction.

    ``FOR UPDATE`` because everything that follows is check-then-act: two admins
    selecting the same space at the same moment would otherwise both read "no
    lease", both call Google, and leave one row pointing at one of two leases —
    with the other renewing nothing and delivering forever.
    """
    row: GoogleChatSubscription | None = await db.scalar(
        select(GoogleChatSubscription)
        .where(
            GoogleChatSubscription.tenant_id == tenant_id,
            GoogleChatSubscription.connection_id == connection_id,
            GoogleChatSubscription.space_name == space_name,
        )
        .with_for_update()
    )
    return row


def _apply_remote(
    subscription: GoogleChatSubscription, remote: RemoteSubscription, *, now: datetime
) -> None:
    """Record what Google just said about this lease, as categories only."""
    subscription.subscription_name = remote.name
    subscription.expire_time = remote.expire_time
    subscription.state = remote.state
    subscription.state_changed_at = now
    subscription.suspension_category = (
        SUSPENSION_REASON_CATEGORY[remote.suspension_reason or SuspensionReason.OTHER]
        if remote.state is GoogleChatSubscriptionState.SUSPENDED
        else None
    )


def _mark_failure(
    subscription: GoogleChatSubscription, error: SubscriptionError, *, now: datetime
) -> None:
    """Record a failure against the precise space it happened to."""
    subscription.state = (
        # A 404 is not a failure to renew, it is the lease having already gone.
        # Recorded as `EXPIRED` so the next pass creates rather than patches.
        GoogleChatSubscriptionState.EXPIRED
        if error.failure is SubscriptionFailure.GONE
        else GoogleChatSubscriptionState.ERROR
    )
    subscription.suspension_category = error.category
    subscription.state_changed_at = now


def _is_live(subscription: GoogleChatSubscription, *, now: datetime) -> bool:
    """Whether this row already describes a lease Google is honouring."""
    return (
        subscription.state is GoogleChatSubscriptionState.ACTIVE
        and subscription.subscription_name is not None
        and subscription.expire_time is not None
        and subscription.expire_time > now
    )


async def ensure_subscription(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    *,
    space_name: str,
    now: datetime | None = None,
) -> GoogleChatSubscription:
    """One subscription for one selected space. Idempotent, and exactly one.

    Called when a space is selected, and safe to call again for a space that is
    already subscribed — it returns the existing lease without spending a call.
    That matters more than it sounds: a picker submits the whole selected set, so
    every save re-asserts every space, and a create per assertion would
    accumulate leases nobody renews.

    The row is written **before** Google is called, in ``PENDING``, so a crash
    between the two leaves a space that visibly has no lease yet rather than one
    that silently never had one. ``uq_google_chat_subscriptions_connection_space``
    is what makes "exactly one" true under concurrency; the ``FOR UPDATE`` above
    is what makes it true without an integrity error reaching a customer.

    Raises:
        SubscriptionError: Google refused, or this deployment has no topic. The
            row is left carrying the category — a space that failed to subscribe
            with a reason on it is worth more than a space with no row.
    """
    moment = now or datetime.now(UTC)
    if not _SPACE_NAME.fullmatch(space_name):
        # A display name, or a bare id with the prefix stripped. Either would
        # create a lease that matches no inbound event.
        raise SubscriptionError(SubscriptionFailure.REQUEST_REJECTED)
    if not client.topic:
        raise SubscriptionError(SubscriptionFailure.NOT_CONFIGURED)

    subscription = await _locked_subscription(
        db, tenant_id=connection.tenant_id, connection_id=connection.id, space_name=space_name
    )
    if subscription is None:
        subscription = GoogleChatSubscription(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            space_name=space_name,
            state=GoogleChatSubscriptionState.PENDING,
            state_changed_at=moment,
        )
        db.add(subscription)
        await db.flush()
    elif _is_live(subscription, now=moment):
        return subscription
    else:
        subscription.state = GoogleChatSubscriptionState.PENDING
        subscription.suspension_category = None
        subscription.state_changed_at = moment
        await db.flush()

    await _create_remote(db, client, connection, subscription, now=moment)
    return subscription


async def _create_remote(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleChatSubscription,
    *,
    now: datetime,
) -> None:
    """Create the lease at Google and record the outcome on the row."""
    try:
        token = await _access_token(client, connection)
        remote = await client.events.create(
            access_token=token, space_name=subscription.space_name, topic=client.topic
        )
    except SubscriptionError as error:
        _mark_failure(subscription, error, now=now)
        await db.flush()
        await refresh_connection_health(db, connection, now=now)
        await logger.awarning(
            "gchat.subscription_create_failed",
            tenant_id=str(connection.tenant_id),
            provider=PROVIDER,
            error_category=error.category.value,
        )
        raise

    if remote is None:
        # The long-running operation has not completed. The row stays ``PENDING``
        # with no subscription name — a placeholder would be a lie the renewal
        # loop would then try to renew — and the next pass asks again.
        await db.flush()
        return

    _apply_remote(subscription, remote, now=now)
    await db.flush()
    await refresh_connection_health(db, connection, now=now)
    await logger.ainfo(
        "gchat.subscription_created",
        tenant_id=str(connection.tenant_id),
        provider=PROVIDER,
        count=1,
    )


# ---------------------------------------------------------------------------
# Delete, on unselection and on disconnect
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class RemovalOutcome:
    """What a deletion actually managed to do.

    Two fields, because they are two facts. ``blocked`` is always true once this
    returns — the local record stops CAIRN reading the space whatever Google
    says. ``remote_deleted`` is whether the lease at Google is gone too; when it
    is false the lease lapses on its own inside the four-hour TTL because nothing
    renews it, and anything it publishes meanwhile is refused by `resolve_space`.
    """

    blocked: bool
    remote_deleted: bool
    error_category: ConnectorErrorCategory | None = None


async def remove_subscription(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    *,
    space_name: str,
    now: datetime | None = None,
) -> RemovalOutcome:
    """Stop reading one space: locally first, remotely second.

    **The order is the whole point.** The row is marked ``DELETED`` and flushed
    before Google is called, so a customer who deselects a space stops being read
    the moment the statement lands — not once Google acknowledges, not after a
    retry, and not conditionally on the network. A remote delete that fails is
    recorded as a category and leaves the local block standing.

    Reversing the order produces the one failure this product cannot have: a
    withdrawn permission that keeps taking data because a third party was
    unreachable.
    """
    moment = now or datetime.now(UTC)
    subscription = await _locked_subscription(
        db, tenant_id=connection.tenant_id, connection_id=connection.id, space_name=space_name
    )
    if subscription is None:
        return RemovalOutcome(blocked=True, remote_deleted=True)

    remote_name = subscription.subscription_name
    subscription.state = GoogleChatSubscriptionState.DELETED
    subscription.state_changed_at = moment
    subscription.suspension_category = None
    # Flushed here, deliberately, before a single byte goes to Google.
    await db.flush()

    if remote_name is None:
        return RemovalOutcome(blocked=True, remote_deleted=True)

    try:
        token = await _access_token(client, connection)
        await client.events.delete(access_token=token, subscription_name=remote_name)
    except SubscriptionError as error:
        await logger.awarning(
            "gchat.subscription_remote_delete_failed",
            tenant_id=str(connection.tenant_id),
            provider=PROVIDER,
            error_category=error.category.value,
        )
        return RemovalOutcome(blocked=True, remote_deleted=False, error_category=error.category)

    return RemovalOutcome(blocked=True, remote_deleted=True)


async def remove_all_subscriptions(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    *,
    now: datetime | None = None,
) -> tuple[RemovalOutcome, ...]:
    """Stop reading every space on this connection. What a disconnect calls.

    Every space is blocked locally even if the first remote delete fails: the
    loop does not stop on an error, because a disconnect that gave up halfway
    would leave the remaining spaces readable for the sake of tidy error
    handling.
    """
    moment = now or datetime.now(UTC)
    subscriptions = await _connection_subscriptions(
        db, tenant_id=connection.tenant_id, connection_id=connection.id
    )
    outcomes = [
        await remove_subscription(db, client, connection, space_name=item.space_name, now=moment)
        for item in subscriptions
    ]
    await logger.ainfo(
        "gchat.subscriptions_removed",
        tenant_id=str(connection.tenant_id),
        provider=PROVIDER,
        count=len(outcomes),
    )
    return tuple(outcomes)


# ---------------------------------------------------------------------------
# The renewal pass
# ---------------------------------------------------------------------------


class RenewalAction(StrEnum):
    """What one pass did to one lease. Bounded, because it is a log field."""

    RENEWED = "renewed"
    RECREATED = "recreated"
    REACTIVATED = "reactivated"

    #: Touched and left alone — a long-running create that has not completed.
    UNCHANGED = "unchanged"

    #: This precise space is not delivering, and the row says why as a category.
    FAILED = "failed"


@final
@dataclass(frozen=True, slots=True)
class RenewalPass:
    """What one pass did, in counts.

    Counts and nothing else, for the reason `ops/connectors.py` gives at length:
    this is what a log line and a metric carry, and a field that could hold a
    space name is a field that eventually does.
    """

    considered: int = 0
    renewed: int = 0
    recreated: int = 0
    reactivated: int = 0
    unchanged: int = 0
    failed: int = 0

    @property
    def changed(self) -> int:
        """Leases this pass actually did something to."""
        return self.renewed + self.recreated + self.reactivated

    def plus(self, other: RenewalPass) -> RenewalPass:
        """Two passes' counts, added. Tenant passes roll up this way."""
        return RenewalPass(
            considered=self.considered + other.considered,
            renewed=self.renewed + other.renewed,
            recreated=self.recreated + other.recreated,
            reactivated=self.reactivated + other.reactivated,
            unchanged=self.unchanged + other.unchanged,
            failed=self.failed + other.failed,
        )


def _tally(actions: Sequence[RenewalAction], *, considered: int) -> RenewalPass:
    return RenewalPass(
        considered=considered,
        renewed=sum(1 for item in actions if item is RenewalAction.RENEWED),
        recreated=sum(1 for item in actions if item is RenewalAction.RECREATED),
        reactivated=sum(1 for item in actions if item is RenewalAction.REACTIVATED),
        unchanged=sum(1 for item in actions if item is RenewalAction.UNCHANGED),
        failed=sum(1 for item in actions if item is RenewalAction.FAILED),
    )


def _claimable(now: datetime) -> ColumnElement[bool]:
    """Which leases a pass may touch.

    A live lease inside its renewal window, plus every lease that is not live at
    all: a pending create, a suspension, an expiry. ``ERROR`` rows are included
    only when the category is one a retry could clear — a revoked permission or
    an invalid configuration is fixed by a person reconnecting or reselecting,
    and retrying it hourly forever spends a customer's quota to be refused again.
    """
    horizon = now + RENEWAL_LEAD
    return or_(
        and_(
            GoogleChatSubscription.state == GoogleChatSubscriptionState.ACTIVE,
            or_(
                GoogleChatSubscription.expire_time <= horizon,
                # No expiry on a live lease is a row we cannot reason about.
                # Renewing it is the safe reading: the cost is one call.
                GoogleChatSubscription.expire_time.is_(None),
            ),
        ),
        GoogleChatSubscription.state.in_(
            [
                GoogleChatSubscriptionState.PENDING,
                GoogleChatSubscriptionState.SUSPENDED,
                GoogleChatSubscriptionState.EXPIRED,
            ]
        ),
        and_(
            GoogleChatSubscription.state == GoogleChatSubscriptionState.ERROR,
            GoogleChatSubscription.suspension_category.in_(sorted(_RETRYABLE_CATEGORIES)),
        ),
    )


async def tenants_with_due_subscriptions(
    db: AsyncSession, *, now: datetime | None = None
) -> tuple[uuid.UUID, ...]:
    """Which workspaces have a lease worth looking at.

    The pass is driven per tenant rather than as one global sweep, and that is
    not decoration. Every statement that touches a subscription then carries a
    tenant predicate, one customer's Google outage cannot consume the batch that
    another customer's renewals needed, and the log line an operator reads
    already says whose renewals they were.
    """
    moment = now or datetime.now(UTC)
    rows = await db.scalars(
        select(GoogleChatSubscription.tenant_id).where(_claimable(moment)).distinct()
    )
    return tuple(rows.all())


async def renew_tenant_subscriptions(
    db: AsyncSession,
    client: SubscriptionClient,
    *,
    tenant_id: uuid.UUID,
    now: datetime | None = None,
    limit: int = RENEWAL_BATCH,
    stagger_seconds: float = STAGGER_SECONDS,
) -> RenewalPass:
    """Renew, recreate and reactivate one workspace's leases.

    **Concurrency-safe by claim, not by convention.** The rows are selected
    ``FOR UPDATE SKIP LOCKED``, so a second worker running the same pass at the
    same moment sees the locked rows as absent and renews none of them rather
    than waiting to renew them a second time. That is the same mechanism the job
    queue uses to lease work, and it is the only one that holds when the two
    passes are in different processes on different machines — an in-process lock,
    an "already renewing" flag or a check-then-act read all fail there.

    The claim is held for the pass's transaction, which spans the calls to
    Google. That is a deliberate trade: the alternative is releasing the lock
    before the network call, which puts the double-renewal back exactly where it
    was. The batch is bounded so the transaction cannot grow without limit.
    """
    moment = now or datetime.now(UTC)
    claimed = (
        await db.scalars(
            select(GoogleChatSubscription)
            .where(GoogleChatSubscription.tenant_id == tenant_id, _claimable(moment))
            # Soonest to lapse first: if a batch is truncated, what it drops is
            # the lease with the most time left.
            .order_by(GoogleChatSubscription.expire_time.asc().nulls_first())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()

    due = [item for item in claimed if is_due(item, now=moment)]
    if not due:
        return RenewalPass(considered=len(claimed))

    connections = await _connections_for(db, tenant_id=tenant_id, rows=due)

    actions: list[RenewalAction] = []
    for index, subscription in enumerate(due):
        connection = connections.get(subscription.connection_id)
        if connection is None or not connection.is_active:
            # A disconnected or revoked connection has no leases worth renewing,
            # and renewing one would be CAIRN re-arming a feed the customer
            # switched off. `remove_all_subscriptions` has already blocked them.
            continue
        if index:
            await _stagger(stagger_seconds)
        action = await _renew_one(db, client, connection, subscription, now=moment)
        # Per lease, not per pass: a pass that renews forty leases and fails one
        # is a healthy pass in every aggregate and a lapsed space to one customer.
        # `RenewalAction` is a bounded StrEnum, so `outcome` stays a closed set
        # and no space, tenant or Google string can reach the counter through it.
        record_subscription_renewal(source=ConnectorProvider.GOOGLE_CHAT, outcome=action.value)
        actions.append(action)

    outcome = _tally(actions, considered=len(claimed))
    await logger.ainfo(
        "gchat.subscription_renewal_pass",
        tenant_id=str(tenant_id),
        provider=PROVIDER,
        count=outcome.changed,
        # Categories and counts. There is no field here a space could reach.
        outcome="degraded" if outcome.failed else "ok",
    )
    return outcome


async def renew_expiring_subscriptions(
    db: AsyncSession,
    *,
    client: SubscriptionClient | None = None,
    now: datetime | None = None,
    limit: int = RENEWAL_BATCH,
    stagger_seconds: float = STAGGER_SECONDS,
) -> RenewalPass:
    """The renewal pass the maintenance loop runs. One call, every tenant.

    Returns an empty pass when this deployment has no Google Chat credentials or
    no Pub/Sub topic, silently: the maintenance loop runs everywhere, including
    deployments with no Chat connector at all, and a warning nobody can act on is
    a warning that hides the ones somebody can.

    One tenant's failure does not end the sweep. A `SubscriptionError` that
    escapes a tenant's pass is caught, counted and logged as a category, because
    the next tenant's leases lapse just as permanently as this one's.
    """
    moment = now or datetime.now(UTC)
    resolved = client or build_client()
    if resolved is None:
        return RenewalPass()

    total = RenewalPass()
    for tenant_id in await tenants_with_due_subscriptions(db, now=moment):
        async with spans.astage("gchat_renewal", tenant_id=str(tenant_id), provider=PROVIDER):
            try:
                outcome = await renew_tenant_subscriptions(
                    db,
                    resolved,
                    tenant_id=tenant_id,
                    now=moment,
                    limit=limit,
                    stagger_seconds=stagger_seconds,
                )
            except SubscriptionError as error:
                await logger.awarning(
                    "gchat.subscription_renewal_failed",
                    tenant_id=str(tenant_id),
                    provider=PROVIDER,
                    error_category=error.category.value,
                )
                # A pass that dies before it reaches a lease counts once here.
                # Without this the worst failure — a whole tenant renewing
                # nothing — is the only one absent from the renewal counter, and
                # the alert that exists to catch lapses stays quiet through it.
                record_subscription_renewal(
                    source=ConnectorProvider.GOOGLE_CHAT, outcome=RenewalAction.FAILED.value
                )
                outcome = RenewalPass(considered=1, failed=1)
        total = total.plus(outcome)
    return total


async def _connections_for(
    db: AsyncSession, *, tenant_id: uuid.UUID, rows: Sequence[GoogleChatSubscription]
) -> Mapping[uuid.UUID, SourceConnection]:
    """The connections these leases belong to, read once for the whole batch."""
    ids = {item.connection_id for item in rows}
    found = await db.scalars(
        select(SourceConnection).where(
            SourceConnection.tenant_id == tenant_id,
            SourceConnection.id.in_(ids),
            SourceConnection.provider == ConnectorProvider.GOOGLE_CHAT,
        )
    )
    return {item.id: item for item in found.all()}


async def _stagger(seconds: float) -> None:
    """Break up simultaneity inside one pass.

    Workspace Events publishes no request-rate limits, so the only defence
    against finding one is not to arrive all at once. Random rather than fixed:
    a fixed delay keeps two workers that started together in lockstep, which is
    the herd with extra steps.
    """
    if seconds > 0:
        await asyncio.sleep(random.uniform(0, seconds))  # noqa: S311 — jitter, not a secret


def _needs_creation(subscription: GoogleChatSubscription, *, now: datetime) -> bool:
    """Whether this lease has to be created rather than renewed.

    **An expired subscription is deleted at Google and cannot be renewed** — a
    ``PATCH`` against one is a 404, forever. So a row with no subscription name,
    a row Google or a previous pass marked ``EXPIRED``, and a row whose expiry
    has simply passed all take the create path. The last of the three is the one
    a renewal loop misses: nothing marked it expired, the state still reads
    ``ACTIVE``, and the lease is gone all the same.
    """
    if subscription.subscription_name is None:
        return True
    if subscription.state is GoogleChatSubscriptionState.EXPIRED:
        return True
    return subscription.expire_time is not None and subscription.expire_time <= now


async def _renew_one(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleChatSubscription,
    *,
    now: datetime,
) -> RenewalAction:
    """Bring one lease back to full life, whatever state it is in.

    Never raises: a pass over fifty spaces must not stop at the first one Google
    refuses, and the refusal is recorded on the row it happened to.
    """
    if _needs_creation(subscription, now=now):
        return await _recreate(db, client, connection, subscription, now=now)

    name = subscription.subscription_name or ""
    reactivating = subscription.state is GoogleChatSubscriptionState.SUSPENDED
    try:
        token = await _access_token(client, connection)
        remote = (
            await client.events.reactivate(access_token=token, subscription_name=name)
            if reactivating
            else await client.events.renew(access_token=token, subscription_name=name)
        )
    except SubscriptionError as error:
        if error.failure is SubscriptionFailure.GONE:
            # The lease lapsed between the last pass and this one. Google has
            # deleted it; the only recovery is a new subscription.
            _mark_failure(subscription, error, now=now)
            await db.flush()
            return await _recreate(db, client, connection, subscription, now=now)
        await _record_failure(db, connection, subscription, error, now=now)
        return RenewalAction.FAILED

    if remote is None:
        # An operation that has not completed. Nothing is written, because the
        # row still describes the lease Google is honouring.
        return RenewalAction.UNCHANGED

    _apply_remote(subscription, remote, now=now)
    await db.flush()

    if remote.state is not GoogleChatSubscriptionState.ACTIVE:
        return await _handle_not_active(
            db, client, connection, subscription, remote, now=now, already_tried=reactivating
        )

    await refresh_connection_health(db, connection, now=now)
    return RenewalAction.REACTIVATED if reactivating else RenewalAction.RENEWED


async def _recreate(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleChatSubscription,
    *,
    now: datetime,
) -> RenewalAction:
    """Create a fresh lease for a space whose old one is gone."""
    try:
        await _create_remote(db, client, connection, subscription, now=now)
    except SubscriptionError:
        # `_create_remote` has already recorded the category on the row and
        # recomputed the connection's health.
        return RenewalAction.FAILED
    return (
        RenewalAction.RECREATED
        if subscription.state is GoogleChatSubscriptionState.ACTIVE
        else RenewalAction.UNCHANGED
    )


async def _handle_not_active(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleChatSubscription,
    remote: RemoteSubscription,
    *,
    now: datetime,
    already_tried: bool,
) -> RenewalAction:
    """Google answered, and the lease is not delivering.

    ``DELETED`` at Google with a selection still in place means the lease is
    simply gone, and the next pass creates a new one — never a patch.

    ``SUSPENDED`` is reduced to its category and, where `REACTIVATABLE_REASONS`
    says reactivating can work, answered with one ``subscriptions.reactivate``.
    One attempt, not a loop: a subscription that suspends again immediately is
    telling us the cause is still there, and a second call in the same pass would
    only spend quota to be told so twice.
    """
    reason = remote.suspension_reason or SuspensionReason.OTHER
    reactivatable = (
        remote.state is GoogleChatSubscriptionState.SUSPENDED
        and not already_tried
        and reason in REACTIVATABLE_REASONS
    )
    if reactivatable:
        return await _reactivate(db, client, connection, subscription, now=now)

    await refresh_connection_health(db, connection, now=now)
    await logger.awarning(
        "gchat.subscription_not_delivering",
        tenant_id=str(connection.tenant_id),
        provider=PROVIDER,
        error_category=(
            SUSPENSION_REASON_CATEGORY[reason]
            if remote.state is GoogleChatSubscriptionState.SUSPENDED
            else ConnectorErrorCategory.CONFIGURATION_INVALID
        ).value,
    )
    return RenewalAction.FAILED


async def _reactivate(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleChatSubscription,
    *,
    now: datetime,
) -> RenewalAction:
    """One reactivation attempt.

    **The expiry is not extended by this call** — a reactivated subscription
    keeps the expiry it had when it was suspended, so the very next pass may well
    have to renew it too. That is why reactivation is part of the renewal loop
    rather than a separate schedule.
    """
    try:
        token = await _access_token(client, connection)
        revived = await client.events.reactivate(
            access_token=token, subscription_name=subscription.subscription_name or ""
        )
    except SubscriptionError as error:
        await _record_failure(db, connection, subscription, error, now=now)
        return RenewalAction.FAILED

    if revived is None:
        return RenewalAction.UNCHANGED

    _apply_remote(subscription, revived, now=now)
    await db.flush()
    await refresh_connection_health(db, connection, now=now)
    if revived.state is not GoogleChatSubscriptionState.ACTIVE:
        # Suspended again, for the same reason or a new one. Recorded, not
        # retried: the cause is outside CAIRN.
        return RenewalAction.FAILED
    return RenewalAction.REACTIVATED


async def _record_failure(
    db: AsyncSession,
    connection: SourceConnection,
    subscription: GoogleChatSubscription,
    error: SubscriptionError,
    *,
    now: datetime,
) -> None:
    """Mark the precise space, then recompute the connection around it."""
    _mark_failure(subscription, error, now=now)
    await db.flush()
    await refresh_connection_health(db, connection, now=now)
    await logger.awarning(
        "gchat.subscription_renewal_failed",
        tenant_id=str(connection.tenant_id),
        provider=PROVIDER,
        error_category=error.category.value,
    )
