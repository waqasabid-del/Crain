"""One Workspace Events lease per **consented** meeting, re-checked on every pass.

A Google Meet subscription is a lease, not a webhook registration: it is created
for one meeting space, it expires, and nothing about it is permanent. So this
file's subject is the renewal, exactly as it is for Chat.

What makes it a different file rather than a `provider` column is the gate.

**A lease may exist only for a Step 35 capture request that is eligible right
now.** :func:`ensure_subscription` takes ``permit: CollectionPermit`` as a
*required keyword argument*, and a `CollectionPermit` cannot be constructed
outside `meetings.guard` — so there is no way to reach this code without having
asked whether every expected participant agreed, under the current policy
wording, for a meeting that has not moved. That is the same device
`ingestion.VerifiedEvent` uses, and it is here for the same reason: a check that
must be remembered is a check that is eventually forgotten.

**The gate is re-run on every renewal, not only at creation.** This is the half
that a Chat-shaped implementation gets wrong, because for Chat the permission
(the space selection) is checked by the ingestion path on every event and a lease
is only plumbing. For Meet the permission can be *withdrawn between the create
and the transcript* — that is precisely what withdrawal means — and a renewal
loop that only reads its own row would keep the lease alive across somebody
changing their mind. A refused re-check does not skip the renewal; it **tears the
subscription down**, locally first.

**An expired subscription is recreated only after the same re-check.** Recreation
is a new grant of collection, not a repair, and the fact that CAIRN used to be
allowed is not evidence that it still is.

**No joining code is ever stored.** For Google Meet, Step 35's
``external_meeting_ref`` is the meeting's joining code — a credential — which is
why Step 35 removed it from every response. It is read from the permit at the
moment a request is built and never written to a column, a log field or a span.
:func:`target_resource_for` refuses a value in joining-code shape outright rather
than sending it to Google, because the alternative is a credential in a request
body, a retry log and a trace.

**Only the transcript announcement is subscribed to.** :data:`EVENT_TYPES` has
one member and :data:`FORBIDDEN_EVENT_TYPES` names what is excluded and why: no
participant join or leave, no attendance, no recording, no smart notes, and no
user-wide subscription. A test asserts the second list and the first are
disjoint, and that nothing in the second appears in a create request.

**No Google string reaches a column, a log field or a span.** Google's messages
quote the resource that failed, which here means a meeting space and the
authorising person's address.
"""

from __future__ import annotations

import asyncio
import hashlib
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
from sqlalchemy import and_, func, or_, select
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
from cairn_api.db.gmeet_models import (
    JOINING_CODE_PATTERN,
    SPACE_NAME_PATTERN,
    GoogleMeetSubscription,
    GoogleMeetSubscriptionState,
)
from cairn_api.gmeet.oauth import (
    REQUEST_TIMEOUT_SECONDS,
    GoogleMeetApi,
    GoogleMeetInstallError,
    GoogleMeetInstallFailure,
    access_token_for,
)
from cairn_api.gmeet.pubsub import PROVIDER
from cairn_api.gmeet.retrieval import note_withdrawal
from cairn_api.meetings.guard import CollectionPermit, CollectionRefusedError, permit_collection
from cairn_api.ops.connectors import (
    SUSPENSION_REASON_CATEGORY,
    SuspensionReason,
    record_subscription_renewal,
)
from cairn_api.telemetry import spans

logger = structlog.get_logger(__name__)

#: The Workspace Events API. One version, pinned: ``v1`` is what the request and
#: response shapes below are written against.
API_BASE: Final = "https://workspaceevents.googleapis.com/v1"
SUBSCRIPTIONS_URL: Final = f"{API_BASE}/subscriptions"

#: The **one** event type CAIRN subscribes to, and the complete list.
#:
#: "A transcript file was generated." That is an announcement that an artifact
#: exists, produced by the meeting platform's own flow — not a transcript, not
#: its content, and not a request for either.
#:
#: A tuple of one rather than a bare string, so widening it is a visible edit in
#: a place with a test pointed at it.
EVENT_TYPES: Final[tuple[str, ...]] = ("google.workspace.meet.transcript.v2.fileGenerated",)

#: Event types this connector must never subscribe to, with the reason each one
#: is excluded. Asserted disjoint from :data:`EVENT_TYPES`, and asserted absent
#: from every create request, by `tests/test_gmeet_subscriptions.py`.
#:
#: **Participants.** ``participant.v2.joined`` and ``participant.v2.left`` are
#: attendance by another name: who was in the room and for how long. md/03 §5.4
#: and md/05 §B.3.3 forbid per-person meeting analytics — talk time,
#: participation scores, attendance ranking — and the honest way to make that
#: impossible is to never receive the events they would be computed from.
#:
#: **Recording and smart notes.** A recording is audio of people speaking and
#: "smart notes" is Google's own AI summary. CAIRN produces neither and ingests
#: neither; subscribing to the announcement would put both on a roadmap somebody
#: could implement without a new consent conversation.
#:
#: **Conference lifecycle.** ``conference.v2.started`` and ``ended`` are the
#: meeting's own timing, which is a per-meeting measurement nobody consented to
#: and which nothing in Step 36A reads.
#:
#: **User-wide subscriptions.** ``//meet.googleapis.com/users/{user}`` targets
#: every meeting a person attends rather than the one their colleagues agreed to.
#: It is not an event type, but it is the same mistake in the target field, and
#: `target_resource_for` refuses it.
FORBIDDEN_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "google.workspace.meet.participant.v2.joined",
        "google.workspace.meet.participant.v2.left",
        "google.workspace.meet.recording.v2.fileGenerated",
        "google.workspace.meet.smartNotes.v2.fileGenerated",
        "google.workspace.meet.conference.v2.started",
        "google.workspace.meet.conference.v2.ended",
    }
)

#: The ``targetResource`` prefix. A full resource URI, not a bare space name —
#: Google rejects the second, with an error that does not say which.
TARGET_RESOURCE_PREFIX: Final = "//meet.googleapis.com/"

#: The prefix a **user-wide** target would carry. Present so it can be refused by
#: name: a subscription on ``users/{user}`` receives every meeting that person
#: attends, including ones nobody in it consented to being read.
FORBIDDEN_TARGET_PREFIX: Final = "users/"

#: ``ttl: "0s"`` means "the maximum this subscription can have", on both create
#: and renew. It is **not** zero seconds, and it is the one string in this file
#: that reads as a bug to somebody who has not read the documentation.
MAX_TTL: Final = "0s"

#: The lease CAIRN plans for, in hours.
#:
#: Meet's subscriptions do not carry Chat's four-hour ceiling, because CAIRN does
#: not ask for ``includeResource`` here — there is no resource it wants inlined.
#: The number is used only to compute the renewal margin below; the *actual*
#: expiry always comes from Google's ``expireTime`` on the row, because a
#: constant that disagreed with Google would produce a lease that lapses while
#: the loop believes it has days left.
TTL_HOURS: Final = 168.0
TTL: Final = timedelta(hours=TTL_HOURS)

#: How far ahead of expiry a lease becomes renewable: half the lease. Half rather
#: than an hour, so a renewal can fail outright, be retried on many later passes,
#: and still land — and a lapse cannot be retried at all.
RENEWAL_LEAD: Final = timedelta(hours=TTL_HOURS / 2)

#: How far renewals are spread across passes. Deterministic per subscription —
#: see :func:`renewal_due_at` — so the spread is a property of the row rather
#: than of the moment a pass happened to run, and so a test can assert the margin.
RENEWAL_JITTER: Final = timedelta(minutes=15)

#: How often the renewal pass runs, mirroring ``jobs/main.MAINTENANCE_INTERVAL_SECONDS``.
#: Stated here because the margin below is computed from it; a test asserts the
#: two agree, so shortening the maintenance loop cannot silently eat the margin.
PASS_INTERVAL: Final = timedelta(hours=1)

#: The worst case: a lease that became due immediately after a pass, with the
#: largest possible jitter, renewed on the following pass. Positive by
#: construction, and asserted, because a negative margin here is a renewal loop
#: that lets leases lapse and calls it success.
MINIMUM_RENEWAL_MARGIN: Final = RENEWAL_LEAD - RENEWAL_JITTER - PASS_INTERVAL

#: Rows claimed per tenant per pass. A bound, so one customer cannot hold a
#: transaction open across every other customer's renewals.
RENEWAL_BATCH: Final = 100

#: The largest random pause between two calls inside one pass. Small, because it
#: is only breaking up simultaneity; the real spreading is `renewal_due_at`.
STAGGER_SECONDS: Final = 0.5

_SPACE_NAME = re.compile(SPACE_NAME_PATTERN)
_JOINING_CODE = re.compile(JOINING_CODE_PATTERN)

#: Google's own subscription states, as strings on the wire.
_REMOTE_SUSPENDED: Final = "SUSPENDED"
_REMOTE_DELETED: Final = "DELETED"


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


class SubscriptionFailure(StrEnum):
    """Why a Workspace Events call did not do what was asked, as a bounded code.

    Coarser than Google's error space on purpose, and derived from the **status
    code alone**. The response body names the meeting space and frequently the
    person, and this is the code path where the temptation to pass it through is
    strongest because the status is less informative — so the body is never read.
    """

    #: The subscription does not exist any more. Recreate; never patch. A 404 on
    #: a renewal does not mean "try again", it means the lease lapsed and Google
    #: deleted it, and folding it into a generic rejection produces a loop that
    #: patches a subscription that no longer exists, forever.
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

    #: The meeting reference CAIRN holds is not a meeting **space** resource
    #: name. Its own value rather than `REQUEST_REJECTED`, because the two have
    #: different fixes and one of them is urgent: a joining code in this position
    #: means a credential is stored where an identifier belongs.
    MEETING_REF_UNUSABLE = "meeting_ref_unusable"

    #: This deployment has no Pub/Sub topic, or no Google Meet credentials. An
    #: operator problem, and it must not present as "Google said no".
    NOT_CONFIGURED = "not_configured"


#: What each failure reports as in the vocabulary the rest of the product reads.
#:
#: Total over `SubscriptionFailure`, asserted by a test, so a value added later
#: cannot arrive at a column as ``None`` and read as "nothing wrong".
_FAILURE_CATEGORIES: Mapping[SubscriptionFailure, ConnectorErrorCategory] = {
    SubscriptionFailure.GONE: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SubscriptionFailure.PERMISSION_DENIED: ConnectorErrorCategory.PERMISSION_REVOKED,
    SubscriptionFailure.AUTHORISATION_EXPIRED: ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
    SubscriptionFailure.RATE_LIMITED: ConnectorErrorCategory.RATE_LIMITED,
    SubscriptionFailure.PROVIDER_UNAVAILABLE: ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
    SubscriptionFailure.REQUEST_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SubscriptionFailure.MEETING_REF_UNUSABLE: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SubscriptionFailure.NOT_CONFIGURED: ConnectorErrorCategory.CONFIGURATION_INVALID,
}

#: Categories a later pass may retry unattended.
#:
#: The others — a revoked permission, a lapsed authorisation, an invalid
#: configuration — are fixed by a person reconnecting or correcting a topic
#: grant, and retrying them hourly forever spends a customer's quota to produce
#: the same refusal.
_RETRYABLE_CATEGORIES: Final[frozenset[ConnectorErrorCategory]] = frozenset(
    {
        ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
        ConnectorErrorCategory.RATE_LIMITED,
        ConnectorErrorCategory.UNKNOWN,
    }
)

#: Suspension reasons CAIRN may answer with ``subscriptions.reactivate``.
#:
#: Every one of them is fixed *outside* CAIRN — an IAM binding on the topic, a
#: topic that was recreated, a quota that refills — and once it is fixed the next
#: pass reactivates with nobody touching CAIRN. The rest are excluded because
#: reactivating cannot succeed until a person acts, and doing it anyway would
#: re-suspend within seconds and hide the reason behind a churn of state changes.
REACTIVATABLE_REASONS: Final[frozenset[SuspensionReason]] = frozenset(
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
    up in a log line contains no meeting space and no address.
    """

    def __init__(self, failure: SubscriptionFailure) -> None:
        self.failure = failure
        self.category = _FAILURE_CATEGORIES[failure]
        super().__init__(f"google meet subscription: {failure.value}")


#: How an OAuth-layer failure arrives here. Translating at this one boundary
#: keeps the renewal loop speaking a single language rather than catching two
#: exception types at every call site.
_INSTALL_FAILURES: Mapping[GoogleMeetInstallFailure, SubscriptionFailure] = {
    GoogleMeetInstallFailure.AUTHORISATION_EXPIRED: SubscriptionFailure.AUTHORISATION_EXPIRED,
    GoogleMeetInstallFailure.ACCESS_FORBIDDEN: SubscriptionFailure.PERMISSION_DENIED,
    GoogleMeetInstallFailure.SCOPES_INSUFFICIENT: SubscriptionFailure.PERMISSION_DENIED,
    GoogleMeetInstallFailure.SCOPES_UNEXPECTED: SubscriptionFailure.PERMISSION_DENIED,
    GoogleMeetInstallFailure.SCOPES_FORBIDDEN: SubscriptionFailure.PERMISSION_DENIED,
    GoogleMeetInstallFailure.RATE_LIMITED: SubscriptionFailure.RATE_LIMITED,
    GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE: SubscriptionFailure.PROVIDER_UNAVAILABLE,
    GoogleMeetInstallFailure.NOT_CONFIGURED: SubscriptionFailure.NOT_CONFIGURED,
}


def _from_install_error(error: GoogleMeetInstallError) -> SubscriptionError:
    """Translate an install-layer failure, defaulting to a rejected request."""
    return SubscriptionError(
        _INSTALL_FAILURES.get(error.failure, SubscriptionFailure.REQUEST_REJECTED)
    )


# ---------------------------------------------------------------------------
# The target resource
# ---------------------------------------------------------------------------


def target_resource_for(permit: CollectionPermit) -> str:
    """The ``targetResource`` for one consented meeting, built from the permit.

    Takes the **permit** rather than a string, so the only way to obtain a target
    is to have passed the consent gate — a helper taking a bare reference would
    be one a caller could reach for without one.

    Three refusals, and the middle one is the reason this function exists rather
    than an f-string at the call site.

    A value in **joining-code shape** (``abc-defg-hij``) is refused outright.
    That is a credential: anyone holding it can enter the meeting. It must never
    be sent to Google in a request body that lands in a retry log and a trace,
    and finding one here means Step 35 stored a credential where a space resource
    name belongs — a defect that has to fail loudly rather than work.

    A **user-wide** target (``users/{user}``) is refused because it subscribes to
    every meeting that person attends, including the ones nobody in them agreed
    to being read. It is not an event type, but it is the same widening in a
    different field.

    Anything that is not ``spaces/{space}`` is refused because it would create a
    lease that matches no inbound event, which reads as connected and delivers
    nothing.

    Raises:
        SubscriptionError: ``MEETING_REF_UNUSABLE``. The value is never included
            in the error, the message or a log field.
    """
    reference = permit.external_meeting_ref.strip()

    if _JOINING_CODE.fullmatch(reference):
        raise SubscriptionError(SubscriptionFailure.MEETING_REF_UNUSABLE)
    if reference.startswith(FORBIDDEN_TARGET_PREFIX):
        raise SubscriptionError(SubscriptionFailure.MEETING_REF_UNUSABLE)
    if not _SPACE_NAME.fullmatch(reference):
        raise SubscriptionError(SubscriptionFailure.MEETING_REF_UNUSABLE)

    return f"{TARGET_RESOURCE_PREFIX}{reference}"


# ---------------------------------------------------------------------------
# The network boundary
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class RemoteSubscription:
    """One subscription as Google described it just now.

    A transport object. Note what is absent: no target resource, no
    ``suspensionReason`` string — the reason is parsed into `SuspensionReason` at
    the boundary and unrecognised ones become ``OTHER``, so nothing downstream can
    store a word Google chose or a meeting Google named.
    """

    #: ``subscriptions/{id}``.
    name: str

    #: Google's ``expireTime``. ``None`` only if Google omitted it, which is not
    #: a shape this client is built for and is treated as "renew immediately".
    expire_time: datetime | None

    #: Reduced to the states CAIRN records. ``STATE_UNSPECIFIED`` and an absent
    #: field both read as ``ACTIVE``: the call succeeded and returned a
    #: subscription, and treating that as broken would suspend a working lease.
    state: GoogleMeetSubscriptionState

    #: Set only when ``state`` is ``SUSPENDED``.
    suspension_reason: SuspensionReason | None = None


class WorkspaceEventsApi(Protocol):
    """Every Workspace Events call this connector makes.

    A protocol with four methods, so a test supplies an object instead of
    patching a module global or intercepting a transport — which is what makes
    "no unit test calls Google" a property of the structure rather than of
    everyone remembering.

    Implementations raise `SubscriptionError` and nothing else.
    """

    async def create(
        self, *, access_token: SecretValue, target_resource: str, topic: str
    ) -> RemoteSubscription | None:
        """Create a subscription for one meeting space. ``None`` if the
        long-running operation has not completed — the caller leaves the row
        ``PENDING``."""
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
    """The real one. The only code in CAIRN that calls Workspace Events for Meet."""

    __slots__ = ()

    async def create(
        self, *, access_token: SecretValue, target_resource: str, topic: str
    ) -> RemoteSubscription | None:
        payload = await self._request(
            "POST",
            SUBSCRIPTIONS_URL,
            access_token=access_token,
            json={
                "targetResource": target_resource,
                # A list rather than a set: this is the request body, and a set's
                # iteration order would make two identical requests send
                # different bytes.
                "eventTypes": list(EVENT_TYPES),
                "notificationEndpoint": {"pubsubTopic": topic},
                # **No `payloadOptions`.** Chat asks for `includeResource: true`
                # so a message arrives inline; there is nothing here CAIRN wants
                # inlined, and asking for the resource would deliver transcript
                # metadata this step has no consent to hold.
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
            # field as cleared, including the event types — which would widen
            # this subscription by omission.
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
                # would make a retry of a partially-applied withdrawal fail
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
    resource — a meeting space — and the status code is enough for every action
    anyone can take.
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

    Create, patch and reactivate all return an ``Operation``. A body that is
    already a subscription is accepted too, so a synchronous response does not
    read as an unfinished operation.

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
        state = GoogleMeetSubscriptionState.DELETED
    elif raw_state == _REMOTE_SUSPENDED:
        state = GoogleMeetSubscriptionState.SUSPENDED
    else:
        state = GoogleMeetSubscriptionState.ACTIVE
    return RemoteSubscription(
        name=name,
        expire_time=_parse_time(payload.get("expireTime")),
        state=state,
        suspension_reason=(
            _suspension_reason(payload.get("suspensionReason"))
            if state is GoogleMeetSubscriptionState.SUSPENDED
            else None
        ),
    )


def _suspension_reason(raw: object) -> SuspensionReason:
    """Google's reason as a closed value. Anything unrecognised is ``OTHER``.

    The raw string is read here and goes no further. A reason Google adds
    tomorrow is an ``OTHER`` we handle rather than a string in a column nobody
    reviewed.
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
    timestamp discarded — losing nanoseconds costs nothing, and losing the expiry
    entirely would make the lease unrenewable.
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

    Two protocols rather than one: `tokens` turns a stored refresh token into an
    access token, `events` is the Workspace Events client. They are separate
    services with separate failure modes, and merging them would mean a test
    double for one had to implement the other.
    """

    tokens: GoogleMeetApi
    events: WorkspaceEventsApi

    #: ``projects/P/topics/T``, and **Meet's own topic**. Held on the client
    #: rather than read at each call site, so there is one place a deployment's
    #: topic comes from — and pointing it at Chat's topic would deliver Meet
    #: announcements into Chat's receiver, which would refuse them for the wrong
    #: reason.
    topic: str


def configured_topic(override: str | None = None, settings: Settings | None = None) -> str:
    """The Pub/Sub topic Google should publish Meet events to, or an empty string."""
    if override:
        return override
    resolved = settings or get_settings()
    return str(getattr(resolved, "google_meet_pubsub_topic", "") or "")


def build_client(
    settings: Settings | None = None, *, topic: str | None = None
) -> SubscriptionClient | None:
    """The production client, or ``None`` when this deployment cannot subscribe.

    ``None`` rather than an exception, because the caller is a maintenance loop
    that runs on every deployment including the ones with no Google Meet
    credentials at all. A loop that raised there would fill the log with a failure
    nobody can act on and would mask the ones somebody can.

    A deployment with credentials but no topic returns ``None`` too: a
    subscription pointed at no topic is a lease that consumes quota and delivers
    nowhere, which reads as working and produces nothing.
    """
    from cairn_api.gmeet.oauth import HttpGoogleMeetApi

    resolved = settings or get_settings()
    client_id = resolved.google_meet_client_id
    client_secret = resolved.google_meet_client_secret
    resolved_topic = configured_topic(topic, resolved)
    if not client_id or not client_secret or not resolved_topic:
        return None
    return SubscriptionClient(
        tokens=HttpGoogleMeetApi(client_id=client_id, client_secret=client_secret),
        events=HttpWorkspaceEventsApi(),
        topic=resolved_topic,
    )


async def _access_token(client: SubscriptionClient, connection: SourceConnection) -> SecretValue:
    """A usable access token, with the install vocabulary translated."""
    try:
        return await access_token_for(client.tokens, connection)
    except GoogleMeetInstallError as error:
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
    tenants, and between one meeting and the next in the same tenant.
    """
    digest = hashlib.sha256(subscription_id.bytes).digest()
    return timedelta(
        seconds=int.from_bytes(digest[:4], "big") % int(RENEWAL_JITTER.total_seconds())
    )


def renewal_due_at(subscription: GoogleMeetSubscription) -> datetime | None:
    """When this lease should be renewed, or ``None`` if it has no expiry.

    Half a lease before expiry, plus this subscription's own offset. The offset is
    *added*, never subtracted, so the jitter can only ever move a renewal earlier
    relative to the expiry it is protecting — and the worst case is
    :data:`MINIMUM_RENEWAL_MARGIN` after allowing for a pass that just missed it.
    """
    if subscription.expire_time is None:
        return None
    return subscription.expire_time - RENEWAL_LEAD + _renewal_offset(subscription.id)


def is_due(subscription: GoogleMeetSubscription, *, now: datetime) -> bool:
    """Whether this pass should touch this subscription.

    Anything that is not ``ACTIVE`` is due immediately: a pending create, a
    suspension waiting on reactivation and an expired lease are all states where a
    meeting is delivering nothing, and waiting for a renewal window computed from
    an expiry it may not even have would be waiting for nothing.
    """
    if subscription.state is not GoogleMeetSubscriptionState.ACTIVE:
        return True
    due = renewal_due_at(subscription)
    return due is None or due <= now


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

#: States in which a meeting is not being watched. ``PENDING`` is deliberately
#: absent: it is the window between a permit being issued and Google
#: acknowledging, which is normal for seconds and is not a fault.
BROKEN_STATES: Final[frozenset[GoogleMeetSubscriptionState]] = frozenset(
    {
        GoogleMeetSubscriptionState.SUSPENDED,
        GoogleMeetSubscriptionState.EXPIRED,
        GoogleMeetSubscriptionState.ERROR,
    }
)


async def _connection_subscriptions(
    db: AsyncSession, *, tenant_id: uuid.UUID, connection_id: uuid.UUID
) -> Sequence[GoogleMeetSubscription]:
    """Every subscription for one connection that has not been deleted."""
    rows = await db.scalars(
        select(GoogleMeetSubscription).where(
            GoogleMeetSubscription.tenant_id == tenant_id,
            GoogleMeetSubscription.connection_id == connection_id,
            GoogleMeetSubscription.state != GoogleMeetSubscriptionState.DELETED,
        )
    )
    return rows.all()


async def refresh_connection_health(
    db: AsyncSession, connection: SourceConnection, *, now: datetime | None = None
) -> ConnectionHealth:
    """Recompute a connection's health from its leases, and record it.

    One broken meeting is not a healthy connection and is not a wholly broken one
    either: a connection with four live leases and one whose renewal failed is
    ``DEGRADED``. Reporting it healthy hides a permanent hole; reporting it
    failing sends somebody to reconnect an authorisation that is fine.

    Recovery does **not** invent a green tick. When nothing is broken any more,
    health returns to ``HEALTHY`` only if a delivery has actually arrived at some
    point; otherwise ``UNKNOWN``, because a lease that exists has proved nothing.
    """
    moment = now or datetime.now(UTC)
    subscriptions = await _connection_subscriptions(
        db, tenant_id=connection.tenant_id, connection_id=connection.id
    )

    broken = [item for item in subscriptions if item.state in BROKEN_STATES]
    delivering = [
        item for item in subscriptions if item.state is GoogleMeetSubscriptionState.ACTIVE
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
    # The most recently changed broken lease decides the category. An older
    # failure's category would describe a problem somebody has already fixed.
    latest = max(broken, key=lambda item: item.state_changed_at or moment)
    connection.last_error_category = latest.error_category or ConnectorErrorCategory.UNKNOWN
    connection.last_error_at = moment
    return connection.health


# ---------------------------------------------------------------------------
# Create, on unanimous consent
# ---------------------------------------------------------------------------


async def _locked_subscription(
    db: AsyncSession, *, tenant_id: uuid.UUID, meeting_id: uuid.UUID
) -> GoogleMeetSubscription | None:
    """This meeting's row, locked for the rest of the transaction.

    ``FOR UPDATE`` because everything that follows is check-then-act: two
    consents landing at the same moment would otherwise both read "no lease",
    both call Google, and leave one row pointing at one of two leases — with the
    other renewing nothing and delivering forever.
    """
    row: GoogleMeetSubscription | None = await db.scalar(
        select(GoogleMeetSubscription)
        .where(
            GoogleMeetSubscription.tenant_id == tenant_id,
            GoogleMeetSubscription.meeting_id == meeting_id,
        )
        .with_for_update()
    )
    return row


def _apply_remote(
    subscription: GoogleMeetSubscription, remote: RemoteSubscription, *, now: datetime
) -> None:
    """Record what Google just said about this lease, as categories only."""
    subscription.subscription_name = remote.name
    subscription.expire_time = remote.expire_time
    subscription.state = remote.state
    subscription.state_changed_at = now
    subscription.error_category = (
        SUSPENSION_REASON_CATEGORY[remote.suspension_reason or SuspensionReason.OTHER]
        if remote.state is GoogleMeetSubscriptionState.SUSPENDED
        else None
    )


def _mark_failure(
    subscription: GoogleMeetSubscription, error: SubscriptionError, *, now: datetime
) -> None:
    """Record a failure against the precise meeting it happened to."""
    subscription.state = (
        # A 404 is not a failure to renew, it is the lease having already gone.
        # Recorded as `EXPIRED` so the next pass creates rather than patches.
        GoogleMeetSubscriptionState.EXPIRED
        if error.failure is SubscriptionFailure.GONE
        else GoogleMeetSubscriptionState.ERROR
    )
    subscription.error_category = error.category
    subscription.state_changed_at = now


def _is_live(subscription: GoogleMeetSubscription, *, now: datetime) -> bool:
    """Whether this row already describes a lease Google is honouring."""
    return (
        subscription.state is GoogleMeetSubscriptionState.ACTIVE
        and subscription.subscription_name is not None
        and subscription.expire_time is not None
        and subscription.expire_time > now
    )


async def subscription_summary(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> tuple[dict[str, int], datetime | None]:
    """This connection's subscriptions as counts, and the soonest live expiry.

    Counts rather than rows, because the caller is a status screen and a row
    carries a meeting reference — which for Meet is the joining code. There is
    deliberately no way to ask this function *which* meetings are subscribed:
    that question belongs to the consent surface, where the people involved
    answered it, not to a connector's health line.

    The expiry is read from live subscriptions only. A suspended or expired lease
    has no countdown worth showing, and including one would make the nearest
    expiry *improve* at the moment a subscription died.
    """
    rows = (
        await db.execute(
            select(GoogleMeetSubscription.state, func.count())
            .where(
                GoogleMeetSubscription.tenant_id == tenant_id,
                GoogleMeetSubscription.connection_id == connection_id,
                GoogleMeetSubscription.state != GoogleMeetSubscriptionState.DELETED,
            )
            .group_by(GoogleMeetSubscription.state)
        )
    ).all()
    counts = {
        (state.value if isinstance(state, GoogleMeetSubscriptionState) else str(state)): count
        for state, count in rows
    }

    nearest: datetime | None = await db.scalar(
        select(func.min(GoogleMeetSubscription.expire_time)).where(
            GoogleMeetSubscription.tenant_id == tenant_id,
            GoogleMeetSubscription.connection_id == connection_id,
            GoogleMeetSubscription.state == GoogleMeetSubscriptionState.ACTIVE,
            GoogleMeetSubscription.expire_time.is_not(None),
        )
    )
    return counts, nearest


async def ensure_subscription(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    *,
    permit: CollectionPermit,
    now: datetime | None = None,
) -> GoogleMeetSubscription:
    """One subscription for one consented meeting. Idempotent, and exactly one.

    **``permit`` is required and cannot be forged.** A `CollectionPermit` is
    issued only by `meetings.guard.permit_collection`, which loads the capture
    request, its participants and their live consents and refuses anything short
    of unanimous, current, unexpired agreement. Taking it as a parameter rather
    than calling the gate here is deliberate: a function that *calls* a check can
    be copied without it, and a function that *requires the proof* cannot be
    called without one.

    Safe to call again for a meeting that is already subscribed — it returns the
    existing lease without spending a call. The row is written **before** Google
    is asked, in ``PENDING``, so a crash between the two leaves a meeting that
    visibly has no lease yet rather than one that silently never had one.

    Raises:
        SubscriptionError: the permit's meeting reference is not a meeting space
            resource name, this deployment has no topic, or Google refused. The
            row is left carrying the category — a meeting that failed to
            subscribe with a reason on it is worth more than a meeting with no
            row.
    """
    moment = now or datetime.now(UTC)

    if permit.tenant_id != connection.tenant_id:
        # A permit for one workspace being used to subscribe on another's
        # credential. Unreachable through the router, and refused anyway: this is
        # the one argument that carries authority, so it is checked against the
        # thing it is being used with rather than trusted.
        raise SubscriptionError(SubscriptionFailure.REQUEST_REJECTED)

    # Built first, so a joining code is refused before a row exists — a
    # `PENDING` row for a meeting that can never be subscribed to would be
    # retried by every later pass, forever.
    target = target_resource_for(permit)

    if not client.topic:
        raise SubscriptionError(SubscriptionFailure.NOT_CONFIGURED)

    subscription = await _locked_subscription(
        db, tenant_id=connection.tenant_id, meeting_id=permit.meeting_id
    )
    if subscription is None:
        subscription = GoogleMeetSubscription(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            meeting_id=permit.meeting_id,
            state=GoogleMeetSubscriptionState.PENDING,
            state_changed_at=moment,
        )
        db.add(subscription)
        await db.flush()
    elif _is_live(subscription, now=moment):
        return subscription
    else:
        subscription.state = GoogleMeetSubscriptionState.PENDING
        subscription.error_category = None
        subscription.state_changed_at = moment
        await db.flush()

    await _create_remote(db, client, connection, subscription, target=target, now=moment)
    return subscription


async def _create_remote(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleMeetSubscription,
    *,
    target: str,
    now: datetime,
) -> None:
    """Create the lease at Google and record the outcome on the row."""
    try:
        token = await _access_token(client, connection)
        remote = await client.events.create(
            access_token=token, target_resource=target, topic=client.topic
        )
    except SubscriptionError as error:
        _mark_failure(subscription, error, now=now)
        await db.flush()
        await refresh_connection_health(db, connection, now=now)
        await logger.awarning(
            "gmeet.subscription_create_failed",
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
        "gmeet.subscription_created",
        tenant_id=str(connection.tenant_id),
        provider=PROVIDER,
        count=1,
    )


# ---------------------------------------------------------------------------
# Delete, on withdrawal and on disconnect
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class RemovalOutcome:
    """What a deletion actually managed to do.

    Two fields, because they are two facts. ``blocked`` is always true once this
    returns — the local record stops CAIRN accepting anything for the meeting
    whatever Google says. ``remote_deleted`` is whether the lease at Google is
    gone too; when it is false the lease lapses on its own because nothing renews
    it, and anything it publishes meanwhile is refused by the receiver.
    """

    blocked: bool
    remote_deleted: bool
    error_category: ConnectorErrorCategory | None = None


async def remove_subscription(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    *,
    meeting_id: uuid.UUID,
    now: datetime | None = None,
) -> RemovalOutcome:
    """Stop watching one meeting: locally first, remotely second.

    **The order is the whole point.** The row is marked ``DELETED`` and flushed
    before Google is called, so somebody withdrawing consent stops being watched
    the moment the statement lands — not once Google acknowledges, not after a
    retry, and not conditionally on the network. A remote delete that fails is
    recorded as a category and leaves the local block standing.

    Reversing the order produces the one failure this product cannot have: a
    withdrawn permission that keeps taking data because a third party was
    unreachable.
    """
    moment = now or datetime.now(UTC)
    subscription = await _locked_subscription(
        db, tenant_id=connection.tenant_id, meeting_id=meeting_id
    )
    if subscription is None:
        return RemovalOutcome(blocked=True, remote_deleted=True)

    remote_name = subscription.subscription_name
    subscription.state = GoogleMeetSubscriptionState.DELETED
    subscription.state_changed_at = moment
    subscription.error_category = None
    # Flushed here, deliberately, before a single byte goes to Google.
    await db.flush()

    if remote_name is None:
        return RemovalOutcome(blocked=True, remote_deleted=True)

    try:
        token = await _access_token(client, connection)
        await client.events.delete(access_token=token, subscription_name=remote_name)
    except SubscriptionError as error:
        await logger.awarning(
            "gmeet.subscription_remote_delete_failed",
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
    """Stop watching every meeting on this connection. What a disconnect calls.

    Every meeting is blocked locally even if the first remote delete fails: the
    loop does not stop on an error, because a disconnect that gave up halfway
    would leave the remaining meetings watched for the sake of tidy error
    handling.
    """
    moment = now or datetime.now(UTC)
    subscriptions = await _connection_subscriptions(
        db, tenant_id=connection.tenant_id, connection_id=connection.id
    )
    outcomes = [
        await remove_subscription(db, client, connection, meeting_id=item.meeting_id, now=moment)
        for item in subscriptions
    ]
    await logger.ainfo(
        "gmeet.subscriptions_removed",
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

    #: Consent is no longer unanimous, current and unexpired. The lease was torn
    #: down rather than renewed. **Not** ``FAILED``: nothing went wrong, somebody
    #: exercised a right the product promises them, and an aggregate that counted
    #: it as a failure would page an operator every time it worked.
    WITHDRAWN = "withdrawn"

    #: This precise meeting is not being watched, and the row says why.
    FAILED = "failed"


@final
@dataclass(frozen=True, slots=True)
class RenewalPass:
    """What one pass did, in counts.

    Counts and nothing else: this is what a log line and a metric carry, and a
    field that could hold a meeting identifier is a field that eventually does.
    """

    considered: int = 0
    renewed: int = 0
    recreated: int = 0
    reactivated: int = 0
    unchanged: int = 0
    withdrawn: int = 0
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
            withdrawn=self.withdrawn + other.withdrawn,
            failed=self.failed + other.failed,
        )


def _tally(actions: Sequence[RenewalAction], *, considered: int) -> RenewalPass:
    return RenewalPass(
        considered=considered,
        renewed=sum(1 for item in actions if item is RenewalAction.RENEWED),
        recreated=sum(1 for item in actions if item is RenewalAction.RECREATED),
        reactivated=sum(1 for item in actions if item is RenewalAction.REACTIVATED),
        unchanged=sum(1 for item in actions if item is RenewalAction.UNCHANGED),
        withdrawn=sum(1 for item in actions if item is RenewalAction.WITHDRAWN),
        failed=sum(1 for item in actions if item is RenewalAction.FAILED),
    )


def _claimable(now: datetime) -> ColumnElement[bool]:
    """Which leases a pass may touch.

    A live lease inside its renewal window, plus every lease that is not live at
    all: a pending create, a suspension, an expiry. ``ERROR`` rows are included
    only when the category is one a retry could clear — a revoked permission or an
    invalid configuration is fixed by a person, and retrying it hourly forever
    spends a customer's quota to be refused again.

    ``DELETED`` is absent, which is what makes a withdrawal final: once the local
    row is marked deleted, no pass will ever look at it again.
    """
    horizon = now + RENEWAL_LEAD
    return or_(
        and_(
            GoogleMeetSubscription.state == GoogleMeetSubscriptionState.ACTIVE,
            or_(
                GoogleMeetSubscription.expire_time <= horizon,
                # No expiry on a live lease is a row we cannot reason about.
                # Renewing it is the safe reading: the cost is one call.
                GoogleMeetSubscription.expire_time.is_(None),
            ),
        ),
        GoogleMeetSubscription.state.in_(
            [
                GoogleMeetSubscriptionState.PENDING,
                GoogleMeetSubscriptionState.SUSPENDED,
                GoogleMeetSubscriptionState.EXPIRED,
            ]
        ),
        and_(
            GoogleMeetSubscription.state == GoogleMeetSubscriptionState.ERROR,
            GoogleMeetSubscription.error_category.in_(sorted(_RETRYABLE_CATEGORIES)),
        ),
    )


async def tenants_with_due_subscriptions(
    db: AsyncSession, *, now: datetime | None = None
) -> tuple[uuid.UUID, ...]:
    """Which workspaces have a lease worth looking at.

    The pass is driven per tenant rather than as one global sweep: every statement
    that touches a subscription then carries a tenant predicate, one customer's
    Google outage cannot consume the batch another customer's renewals needed, and
    the consent re-check below needs a tenant to check against.
    """
    moment = now or datetime.now(UTC)
    rows = await db.scalars(
        select(GoogleMeetSubscription.tenant_id).where(_claimable(moment)).distinct()
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
    """Renew, recreate, reactivate — or tear down — one workspace's leases.

    **Concurrency-safe by claim, not by convention.** The rows are selected ``FOR
    UPDATE SKIP LOCKED``, so a second worker running the same pass at the same
    moment sees the locked rows as absent and renews none of them rather than
    waiting to renew them a second time. That is the same mechanism the job queue
    uses to lease work, and it is the only one that holds when the two passes are
    in different processes on different machines.

    **Consent is re-checked before every single renewal.** See
    :func:`_renew_one`.
    """
    moment = now or datetime.now(UTC)
    claimed = (
        await db.scalars(
            select(GoogleMeetSubscription)
            .where(GoogleMeetSubscription.tenant_id == tenant_id, _claimable(moment))
            # Soonest to lapse first: if a batch is truncated, what it drops is
            # the lease with the most time left.
            .order_by(GoogleMeetSubscription.expire_time.asc().nulls_first())
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
        # Per lease, not per pass. `RenewalAction` is a bounded StrEnum, so
        # `outcome` stays a closed set and no meeting, tenant or Google string can
        # reach the counter through it.
        record_subscription_renewal(source=ConnectorProvider.GOOGLE_MEET, outcome=action.value)
        actions.append(action)

    outcome = _tally(actions, considered=len(claimed))
    await logger.ainfo(
        "gmeet.subscription_renewal_pass",
        tenant_id=str(tenant_id),
        provider=PROVIDER,
        count=outcome.changed,
        withdrawn=outcome.withdrawn,
        # Categories and counts. There is no field here a meeting could reach.
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

    Returns an empty pass when this deployment has no Google Meet credentials or
    no Pub/Sub topic, silently: the maintenance loop runs everywhere, and a
    warning nobody can act on hides the ones somebody can.

    One tenant's failure does not end the sweep.
    """
    moment = now or datetime.now(UTC)
    resolved = client or build_client()
    if resolved is None:
        return RenewalPass()

    total = RenewalPass()
    for tenant_id in await tenants_with_due_subscriptions(db, now=moment):
        async with spans.astage("gmeet_renewal", tenant_id=str(tenant_id), provider=PROVIDER):
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
                    "gmeet.subscription_renewal_failed",
                    tenant_id=str(tenant_id),
                    provider=PROVIDER,
                    error_category=error.category.value,
                )
                # A pass that dies before it reaches a lease counts once here.
                # Without this the worst failure — a whole tenant renewing nothing
                # — is the only one absent from the counter.
                record_subscription_renewal(
                    source=ConnectorProvider.GOOGLE_MEET, outcome=RenewalAction.FAILED.value
                )
                outcome = RenewalPass(considered=1, failed=1)
        total = total.plus(outcome)
    return total


async def _connections_for(
    db: AsyncSession, *, tenant_id: uuid.UUID, rows: Sequence[GoogleMeetSubscription]
) -> Mapping[uuid.UUID, SourceConnection]:
    """The connections these leases belong to, read once for the whole batch."""
    ids = {item.connection_id for item in rows}
    found = await db.scalars(
        select(SourceConnection).where(
            SourceConnection.tenant_id == tenant_id,
            SourceConnection.id.in_(ids),
            SourceConnection.provider == ConnectorProvider.GOOGLE_MEET,
        )
    )
    return {item.id: item for item in found.all()}


async def _stagger(seconds: float) -> None:
    """Break up simultaneity inside one pass.

    Random rather than fixed: a fixed delay keeps two workers that started
    together in lockstep, which is the herd with extra steps.
    """
    if seconds > 0:
        await asyncio.sleep(random.uniform(0, seconds))  # noqa: S311 — jitter, not a secret


def _needs_creation(subscription: GoogleMeetSubscription, *, now: datetime) -> bool:
    """Whether this lease has to be created rather than renewed.

    **An expired subscription is deleted at Google and cannot be renewed** — a
    ``PATCH`` against one is a 404, forever. So a row with no subscription name, a
    row marked ``EXPIRED``, and a row whose expiry has simply passed all take the
    create path. The last of the three is the one a renewal loop misses: nothing
    marked it expired, the state still reads ``ACTIVE``, and the lease is gone all
    the same.
    """
    if subscription.subscription_name is None:
        return True
    if subscription.state is GoogleMeetSubscriptionState.EXPIRED:
        return True
    return subscription.expire_time is not None and subscription.expire_time <= now


async def _current_permit(
    db: AsyncSession, subscription: GoogleMeetSubscription, *, now: datetime
) -> CollectionPermit | None:
    """Ask Step 35's gate again, right now. ``None`` means it said no.

    **This is the line that makes withdrawal work.** A subscription is created
    against a permit issued at one moment; consent can be withdrawn, a
    participant can be added, the policy wording can change, the meeting can be
    rescheduled or cancelled — and every one of those must stop the lease rather
    than wait for it to lapse on its own.

    `permit_collection` is passed the tenant from the row rather than trusting an
    ambient session scope, which is what lets this run on the platform session
    the maintenance loop holds: the gate compares the meeting's own tenant
    against the one it was given and refuses a mismatch as ``SCOPE_MISMATCH``.

    The refusal reason is deliberately **not** returned. It is logged inside the
    guard as a bounded category, and a caller that could branch on it is a caller
    that could decide some refusals are worth ignoring.
    """
    try:
        return await permit_collection(
            db,
            tenant_id=subscription.tenant_id,
            meeting_id=subscription.meeting_id,
            now=now,
        )
    except CollectionRefusedError:
        return None


async def _renew_one(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleMeetSubscription,
    *,
    now: datetime,
) -> RenewalAction:
    """Bring one lease back to full life — or take it down, if consent has moved.

    The consent re-check happens **first**, before the access token, before the
    call to Google, and before any decision about renew-versus-recreate. Doing it
    afterwards would mean a withdrawn meeting still spent a call extending the
    lease it was about to lose.

    Never raises: a pass over fifty meetings must not stop at the first one Google
    refuses, and the refusal is recorded on the row it happened to.
    """
    permit = await _current_permit(db, subscription, now=now)
    if permit is None:
        # Not an error. Somebody withdrew, declined, was added late, the wording
        # changed, the meeting moved or it was cancelled — and the answer to all
        # six is the same: stop. Torn down locally first, exactly as an explicit
        # withdrawal is.
        await remove_subscription(
            db, client, connection, meeting_id=subscription.meeting_id, now=now
        )
        # Step 36B: the same decision applies to anything already retrieved for
        # this meeting. Stamping it stops every future processing path and
        # rewrites nothing — deletion is the retention policy's job, and a
        # withdrawal that silently erased what was collected would also erase the
        # evidence that the withdrawal was honoured.
        await note_withdrawal(
            db,
            tenant_id=subscription.tenant_id,
            meeting_id=subscription.meeting_id,
            now=now,
        )
        await refresh_connection_health(db, connection, now=now)
        await logger.ainfo(
            "gmeet.subscription_withdrawn",
            tenant_id=str(connection.tenant_id),
            provider=PROVIDER,
            count=1,
        )
        return RenewalAction.WITHDRAWN

    if _needs_creation(subscription, now=now):
        # Recreation is a *new* grant of collection, and it happens only on the
        # far side of the check above.
        return await _recreate(db, client, connection, subscription, permit=permit, now=now)

    name = subscription.subscription_name or ""
    reactivating = subscription.state is GoogleMeetSubscriptionState.SUSPENDED
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
            # deleted it; the only recovery is a new subscription — under the
            # permit obtained above, which is still the current one.
            _mark_failure(subscription, error, now=now)
            await db.flush()
            return await _recreate(db, client, connection, subscription, permit=permit, now=now)
        await _record_failure(db, connection, subscription, error, now=now)
        return RenewalAction.FAILED

    if remote is None:
        # An operation that has not completed. Nothing is written, because the row
        # still describes the lease Google is honouring.
        return RenewalAction.UNCHANGED

    _apply_remote(subscription, remote, now=now)
    await db.flush()

    if remote.state is not GoogleMeetSubscriptionState.ACTIVE:
        return await _handle_not_active(
            db, client, connection, subscription, remote, now=now, already_tried=reactivating
        )

    await refresh_connection_health(db, connection, now=now)
    return RenewalAction.REACTIVATED if reactivating else RenewalAction.RENEWED


async def _recreate(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleMeetSubscription,
    *,
    permit: CollectionPermit,
    now: datetime,
) -> RenewalAction:
    """Create a fresh lease for a meeting whose old one is gone.

    Takes the permit rather than re-deriving one, so the recreation is provably
    the same consent decision the caller checked a few lines earlier — and so
    this function cannot be called from anywhere that has not checked.
    """
    try:
        target = target_resource_for(permit)
    except SubscriptionError as error:
        _mark_failure(subscription, error, now=now)
        await db.flush()
        return RenewalAction.FAILED

    subscription.state = GoogleMeetSubscriptionState.PENDING
    subscription.error_category = None
    subscription.state_changed_at = now
    await db.flush()

    try:
        await _create_remote(db, client, connection, subscription, target=target, now=now)
    except SubscriptionError:
        # `_create_remote` has already recorded the category on the row and
        # recomputed the connection's health.
        return RenewalAction.FAILED
    return (
        RenewalAction.RECREATED
        if subscription.state is GoogleMeetSubscriptionState.ACTIVE
        else RenewalAction.UNCHANGED
    )


async def _handle_not_active(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleMeetSubscription,
    remote: RemoteSubscription,
    *,
    now: datetime,
    already_tried: bool,
) -> RenewalAction:
    """Google answered, and the lease is not delivering.

    ``SUSPENDED`` is reduced to its category and, where `REACTIVATABLE_REASONS`
    says reactivating can work, answered with one ``subscriptions.reactivate``.
    One attempt, not a loop: a subscription that suspends again immediately is
    telling us the cause is still there.
    """
    reason = remote.suspension_reason or SuspensionReason.OTHER
    reactivatable = (
        remote.state is GoogleMeetSubscriptionState.SUSPENDED
        and not already_tried
        and reason in REACTIVATABLE_REASONS
    )
    if reactivatable:
        return await _reactivate(db, client, connection, subscription, now=now)

    await refresh_connection_health(db, connection, now=now)
    await logger.awarning(
        "gmeet.subscription_not_delivering",
        tenant_id=str(connection.tenant_id),
        provider=PROVIDER,
        error_category=(
            SUSPENSION_REASON_CATEGORY[reason]
            if remote.state is GoogleMeetSubscriptionState.SUSPENDED
            else ConnectorErrorCategory.CONFIGURATION_INVALID
        ).value,
    )
    return RenewalAction.FAILED


async def _reactivate(
    db: AsyncSession,
    client: SubscriptionClient,
    connection: SourceConnection,
    subscription: GoogleMeetSubscription,
    *,
    now: datetime,
) -> RenewalAction:
    """One reactivation attempt.

    **The expiry is not extended by this call** — a reactivated subscription keeps
    the expiry it had when it was suspended, so the very next pass may well have
    to renew it too. That is why reactivation is part of the renewal loop rather
    than a separate schedule.
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
    if revived.state is not GoogleMeetSubscriptionState.ACTIVE:
        # Suspended again, for the same reason or a new one. Recorded, not
        # retried: the cause is outside CAIRN.
        return RenewalAction.FAILED
    return RenewalAction.REACTIVATED


async def _record_failure(
    db: AsyncSession,
    connection: SourceConnection,
    subscription: GoogleMeetSubscription,
    error: SubscriptionError,
    *,
    now: datetime,
) -> None:
    """Mark the precise meeting, then recompute the connection around it."""
    _mark_failure(subscription, error, now=now)
    await db.flush()
    await refresh_connection_health(db, connection, now=now)
    await logger.awarning(
        "gmeet.subscription_renewal_failed",
        tenant_id=str(connection.tenant_id),
        provider=PROVIDER,
        error_category=error.category.value,
    )
