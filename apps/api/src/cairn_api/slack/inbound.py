"""Slack's half of the ingestion contract: the signature, the tenant, the channel.

Everything Slack-specific about receipt lives here, and nothing downstream of it
is Slack-specific at all — `ingestion/` owns the order, the `VerifiedEvent`, the
idempotency key and the enqueue, exactly as it does for GitHub.

Three things are worth reading closely.

**Verification.** Slack signs ``"v0:" + timestamp + ":" + body`` with the app's
signing secret. The timestamp is *inside* the signed string, which is what makes
the five-minute window meaningful: an attacker cannot replay yesterday's capture
by rewriting the header, because rewriting it invalidates the signature. Both
halves are enforced — a signature that verifies against a timestamp five minutes
and one second old is still refused, and so is one from the future, because
clock skew large enough to matter is indistinguishable from a forged timestamp.

**Tenancy.** The team id comes from the verified body, and is looked up against
`SourceConnection` rows that only an authenticated connect flow may write. There
is no default, no first-row fallback and no single-tenant assumption: a lookup
that finds nothing, finds a disconnected connection, or finds *two* connections
claiming one team is a refusal. The last case matters — two rows would mean one
workspace could be handed another's messages, and picking either one silently
starts the leak.

**Channel policy.** A customer selects which public channels CAIRN may read.
That selection is a consent boundary, so it is checked before anything is
stored, enqueued, or recorded — an event from an unselected channel leaves no
trace at all, which is the only version of "we do not read that channel" that is
actually true.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.ingestion import (
    IdempotencyKey,
    InboundRequest,
    ResolvedTenant,
    SourceMetadata,
    SourceMetadataError,
    VerificationError,
)

logger = structlog.get_logger(__name__)

#: This provider's name in `SourceMetadata`, on spans, and in logs.
PROVIDER = "slack"

SIGNATURE_HEADER = "X-Slack-Signature"
TIMESTAMP_HEADER = "X-Slack-Request-Timestamp"

#: Present on a retry, and only on a retry. Bounded values (an integer and a
#: short reason code), so both are safe to log.
RETRY_NUM_HEADER = "X-Slack-Retry-Num"
RETRY_REASON_HEADER = "X-Slack-Retry-Reason"

#: Set on a non-200 response to stop Slack retrying a *permanent* rejection.
#: Slack retries three times — immediately, at one minute, at five — which for
#: an unknown workspace or an unselected channel is three deliveries of data we
#: have already said we will not accept.
NO_RETRY_HEADER = "X-Slack-No-Retry"
NO_RETRY_VALUE = "1"

#: Slack's current signature version. Pinned rather than parsed: accepting
#: whatever version a header claims is how a future weaker scheme gets accepted
#: by an endpoint written before it existed.
SIGNATURE_VERSION = "v0"

#: Slack's documented replay window. Five minutes, applied symmetrically.
REPLAY_WINDOW_SECONDS = 300

#: Slack's event payloads are small — a message with blocks and attachments is
#: kilobytes. Capped far below the shared default because this endpoint is
#: unauthenticated and hashes whatever it is given.
MAX_PAYLOAD_BYTES = 1024 * 1024


def sign(body: bytes, timestamp: str, secret: str) -> str:
    """Slack's signature for these exact bytes at this exact timestamp.

    Shared with the verifier rather than duplicated in tests: a test that
    computes the signature its own way proves the test agrees with itself.
    """
    base = b"%s:%s:%s" % (SIGNATURE_VERSION.encode("ascii"), timestamp.encode("ascii"), body)
    digest = hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


@dataclass(frozen=True, slots=True)
class SlackInbound:
    """Verify a Slack delivery, and name it.

    `now` is injectable for one reason: the replay window is the control most
    worth testing, and the alternative to injecting a clock is a test that
    sleeps for five minutes.
    """

    secret: str

    now: Callable[[], float] = field(default=time.time)

    def verify(self, request: InboundRequest) -> None:
        """Prove the delivery came from Slack, on the raw bytes, before anything
        parses them.

        Every failure raises the same exception type with no distinguishing
        response, so a forger learns nothing about which part was wrong.
        """
        if not self.secret:
            # A blank secret makes every signature verifiable, which turns a
            # misconfiguration into an open write path. Refusing everything is
            # the only safe reading of "no secret configured".
            msg = "No Slack signing secret is configured"
            raise VerificationError(msg)

        timestamp = request.header(TIMESTAMP_HEADER)
        if not timestamp:
            msg = "Missing request timestamp"
            raise VerificationError(msg)

        try:
            sent_at = int(timestamp)
        except ValueError as exc:
            msg = "Malformed request timestamp"
            raise VerificationError(msg) from exc

        # Symmetric on purpose. A stale timestamp is a replay; a future one is a
        # clock we do not control being used to buy an arbitrarily long replay
        # window, and there is no legitimate delivery from the future.
        skew = self.now() - sent_at
        if abs(skew) > REPLAY_WINDOW_SECONDS:
            msg = "Request timestamp outside the replay window"
            raise VerificationError(msg)

        signature = request.header(SIGNATURE_HEADER)
        if not signature:
            msg = "Missing signature"
            raise VerificationError(msg)

        version, separator, _ = signature.partition("=")
        if not separator or version != SIGNATURE_VERSION:
            msg = f"Signature is not {SIGNATURE_VERSION}"
            raise VerificationError(msg)

        expected = sign(request.body, timestamp, self.secret)
        # Constant time: a byte-by-byte comparison leaks how much of a guess was
        # right, which is enough to forge one byte at a time.
        if not hmac.compare_digest(expected, signature):
            msg = "Signature does not match"
            raise VerificationError(msg)

    def read_source(self, request: InboundRequest) -> SourceMetadata:
        """Name the delivery, from the verified body.

        Slack puts everything that identifies an event in the JSON rather than
        in headers, so this parses — which is safe here and nowhere earlier,
        because `verify_and_mint` guarantees the bytes verified first.

        The account is **not** attached here. `team_id` is read in the endpoint
        and applied through `VerifiedEvent.attributed_to`, keeping "which
        workspace" a single, greppable decision.
        """
        try:
            decoded: object = json.loads(request.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = "A Slack delivery must be JSON"
            raise SourceMetadataError(msg) from exc

        if not isinstance(decoded, dict):
            msg = "A Slack delivery must be a JSON object"
            raise SourceMetadataError(msg)

        envelope_type = _text(decoded.get("type"))
        if envelope_type is None:
            msg = "A Slack delivery must carry an envelope type"
            raise SourceMetadataError(msg)

        return SourceMetadata(
            provider=PROVIDER,
            event_type=_event_type_of(decoded, envelope_type)[:64],
            # `event_id` is a *sibling* of `type` and `team_id`, not a field of
            # the nested event. The nested one does not exist; reading for it
            # produces a key that is `None` on every delivery, and an
            # idempotency key that is always derived is one that never
            # suppresses a retry Slack byte-varies.
            external_event_id=_text(decoded.get("event_id")),
        )

    def idempotency_key(self, request: InboundRequest, source: SourceMetadata) -> IdempotencyKey:
        """`event_id` where Slack sends one, a digest where it does not.

        `event_id` is stable across all three retries of a delivery, which is
        exactly what an idempotency key needs. `url_verification` and
        `app_rate_limited` carry none — neither is stored or enqueued, so a
        derived key exists only so the shared path has one.
        """
        if source.external_event_id is not None:
            return IdempotencyKey.from_provider(source.external_event_id)

        return IdempotencyKey.derive(
            provider=PROVIDER,
            external_account_id=source.external_account_id,
            event_type=source.event_type,
            body=request.body,
        )


class TeamNotResolvableError(LookupError):
    """A team id matched something other than exactly one connection."""


class SlackTeamResolver:
    """Tenant from `team_id`, via the connection the connect flow wrote.

    The row is kept after resolution because the caller needs it for three
    things the tenant alone cannot answer: which connection the channel policy
    applies to, where to record health, and which connection a teardown event
    switches off — and a teardown has to reach a connection that is *already*
    inactive.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self.connection: SourceConnection | None = None

    async def resolve(self, source: SourceMetadata) -> ResolvedTenant | None:
        team_id = source.external_account_id
        if team_id is None:
            return None

        matches = (
            await self._db.scalars(
                select(SourceConnection)
                .where(
                    SourceConnection.provider == ConnectorProvider.SLACK,
                    SourceConnection.external_account_id == team_id,
                )
                # Two is enough to know the answer is ambiguous, and stops one
                # malformed team id reading a whole table.
                .limit(2)
            )
        ).all()

        if len(matches) != 1:
            if len(matches) > 1:
                # Never "take the first". Two workspaces claiming one team means
                # either could be handed the other's messages, and whichever the
                # query happened to order first would start the leak silently.
                await logger.aerror(
                    "slack.ambiguous_team",
                    provider=PROVIDER,
                    count=len(matches),
                )
            return None

        self.connection = matches[0]
        return ResolvedTenant(
            tenant_id=self.connection.tenant_id,
            external_account_id=team_id,
            active=self.connection.is_active,
        )


class ChannelPolicy(Protocol):
    """Whether a connection is allowed to read a given public channel.

    Narrow on purpose. The selection itself — which channels an admin ticked,
    when, and by whom — belongs with the connector's own tables; ingestion needs
    one question answered and should not be able to ask any others.
    """

    async def is_selected(self, connection_id: uuid.UUID, channel_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class StoredChannelPolicy:
    """The production policy: a channel is selected if a row says so.

    The presence of the row *is* the permission — `SlackChannelSelection` has no
    `enabled` column, so there is no second state to disagree with the first.
    Absence therefore means "not selected", which makes every failure mode of
    this lookup (no rows yet, a connection nobody configured, a channel added to
    Slack this morning) fail closed rather than open.

    Scoped by `connection_id` rather than by tenant: channel ids are unique per
    Slack workspace, not globally, so a tenant-scoped check would let a channel
    selected on one connection permit an identically-numbered channel on
    another.
    """

    db: AsyncSession

    async def is_selected(self, connection_id: uuid.UUID, channel_id: str) -> bool:
        # Delegated rather than re-queried. Two definitions of "which channels
        # are selected" is two places to get the scoping right, and the one that
        # drifts is always the one enforcing it.
        from cairn_api.slack.channels import selected_channel_ids

        return channel_id in await selected_channel_ids(self.db, connection_id=connection_id)


@dataclass(frozen=True, slots=True)
class StaticChannelPolicy:
    """A fixed set of selected channels, per connection.

    Used by tests, and by any wiring that has the selection in memory already.
    Kept here rather than in the test file so the protocol has a real
    implementation in the source tree that the protocol is checked against.
    """

    selections: Mapping[uuid.UUID, frozenset[str]]

    async def is_selected(self, connection_id: uuid.UUID, channel_id: str) -> bool:
        return channel_id in self.selections.get(connection_id, frozenset())


async def record_healthy_delivery(connection: SourceConnection) -> None:
    """A verified delivery arrived and was accepted for this connection.

    `last_successful_sync_at` is the number a customer means by "is it working",
    and the one a stalled-but-authorised connection cannot fake — so it is set
    only here, on the path where data actually arrived.
    """
    connection.last_successful_sync_at = datetime.now(UTC)
    connection.health = ConnectionHealth.HEALTHY
    connection.last_error_category = None


async def record_connection_error(
    connection: SourceConnection,
    category: ConnectorErrorCategory,
    *,
    health: ConnectionHealth,
) -> None:
    """Record a bounded failure category — never a provider message.

    Slack's error text quotes the request that failed, which means channel
    names, user handles and sometimes message fragments. `ConnectorErrorCategory`
    carries everything an operator or a customer can act on and none of what
    they must not see.
    """
    connection.last_error_category = category
    connection.last_error_at = datetime.now(UTC)
    connection.health = health


async def apply_teardown(connection: SourceConnection, event_type: str) -> bool:
    """Switch a connection off. Idempotent, and keyed on the connection alone.

    Slack sends `app_uninstalled` and `tokens_revoked` for the same teardown and
    guarantees no order between them, so whichever arrives first stops ingest and
    the second must be a no-op. Returns whether anything changed, so the caller
    can log the difference without inspecting the row.
    """
    if connection.disconnected_at is not None or connection.revoked_at is not None:
        return False

    now = datetime.now(UTC)
    if event_type == TOKENS_REVOKED_EVENT:
        # Their side stopping: reconnecting needs a fresh authorisation, and
        # showing this as merely "disconnected" produces the support ticket
        # where a customer presses a reconnect button that cannot work.
        connection.state = ConnectionState.REVOKED
        connection.revoked_at = now
    else:
        connection.state = ConnectionState.DISCONNECTED
        connection.disconnected_at = now

    connection.health = ConnectionHealth.UNKNOWN
    return True


#: The two teardown events, subscribed together. Both arrive as ordinary
#: `event_callback` envelopes.
APP_UNINSTALLED_EVENT = "app_uninstalled"
TOKENS_REVOKED_EVENT = "tokens_revoked"
TEARDOWN_EVENTS = frozenset({APP_UNINSTALLED_EVENT, TOKENS_REVOKED_EVENT})


def _event_type_of(payload: Mapping[str, Any], envelope_type: str) -> str:
    """The most specific name this delivery has.

    Reads the nested event's type *defensively*. `app_rate_limited` has no
    nested event at all, so `payload["event"]["type"]` raises — on the one
    delivery that means Slack is dropping this workspace's events, which is the
    worst possible time for the endpoint to 500.
    """
    if envelope_type != "event_callback":
        return envelope_type

    event = payload.get("event")
    if not isinstance(event, dict):
        return envelope_type

    return _text(event.get("type")) or envelope_type


def _text(value: object) -> str | None:
    """A non-empty string, or nothing. Never a coerced number or an object."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
