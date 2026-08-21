"""The Slack install: authorise, come back, prove it was us, store the token.

Everything in this package that touches the network is in this file, behind
:class:`SlackApi`. That is not tidiness — it is what makes "no unit test calls
Slack" enforceable by construction rather than by everyone remembering, and it
means the failure translation below has exactly one place to live.

**Three things about Slack's OAuth that this file is shaped by, and that are easy
to get wrong from the docs alone.**

*Every Web API call returns HTTP 200.* Failure is ``{"ok": false, "error": "..."}``
in the body. Code that checks ``response.status_code`` therefore treats every
failure as a success and then crashes on a missing key, several frames away from
the cause.

*Slack may grant fewer scopes than were asked for*, without failing the exchange.
The response's ``scope`` is a **comma-separated string**, not an array, and it is
the authority on what we actually got. An install that quietly proceeds with
``channels:read`` and no ``channels:history`` produces a connection that looks
perfect and delivers nothing, which md/05 §4 calls worse than an honest failure.
So the granted set is verified and the install is refused if it falls short.

*Denial is under-documented.* Slack's documentation does not state verbatim which
query parameter comes back when a person presses Cancel on the consent screen.
So the callback branches on the **presence of any** ``error`` parameter rather
than on the literal string ``access_denied`` — a defensive read that is correct
whichever word Slack sends, where an equality check against one string would
silently fall through to "exchange the code" with no code to exchange.

**Nothing here ever returns, logs or raises a Slack error string.** Slack's
messages quote the request that failed, which for this connector means team
names and — on the channel side — channel names. Failures are translated into
:class:`SlackInstallFailure` (ours, bounded) plus a ``ConnectorErrorCategory``
(already the closed set the rest of the product reports on), and the raw string
is discarded at the boundary rather than carried one frame further in case
somebody wants it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, final
from urllib.parse import urlencode

import httpx
import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.auth.tokens import generate_token, hash_token
from cairn_api.config import Settings
from cairn_api.connectors.credentials import SecretValue, clear_secret, store_secret
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.slack_models import SlackOAuthState

logger = structlog.get_logger(__name__)

AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
ACCESS_TOKEN_URL = "https://slack.com/api/oauth.v2.access"  # noqa: S105 — a URL, not a token

#: The bot scopes CAIRN requests, and the complete list.
#:
#: - ``channels:history`` — receive message events from public channels. Without
#:   it the app installs and no event ever arrives.
#: - ``channels:read`` — list public channels, so the customer can choose from a
#:   picker rather than paste ids out of Slack's URL bar.
#: - ``users:read`` — turn the ``U…`` author id on an event into a person, which
#:   is the whole of attribution. Without it every fact is by "someone".
#:
#: Ordered rather than a set, because this is also the string sent to Slack and a
#: set's iteration order would make the authorise URL differ between processes.
REQUIRED_BOT_SCOPES: tuple[str, ...] = ("channels:history", "channels:read", "users:read")

#: Scope prefixes that must never be requested, pinned so the reason survives.
#:
#: ``chat:write`` would let CAIRN post as itself — a coordination tool that can
#: speak in a channel is a tool people manage their appearance in front of.
#: ``groups``/``im``/``mpim`` are private channels and DMs, which are outside what
#: this product reads at all (md/05). ``channels:join`` and ``channels:manage``
#: would let the app decide its own reach, which is the customer's decision.
#: ``files:read`` and ``search:read`` reach content nobody selected a channel for.
#:
#: A test asserts none of these appears in the requested set, so widening the ask
#: is a deliberate edit to a list with reasons on it rather than a character
#: added to a string.
FORBIDDEN_SCOPE_PREFIXES: tuple[str, ...] = (
    "chat:write",
    "groups:",
    "im:",
    "mpim:",
    "channels:join",
    "channels:manage",
    "channels:write",
    "files:read",
    "search:read",
)

#: How long an install may sit half-finished.
#:
#: An install is one browser round trip through one consent screen. Ten minutes
#: covers a person who reads the screen, checks with a colleague and comes back;
#: an hour would be a CSRF window held open for nobody's benefit.
STATE_TTL = timedelta(minutes=10)

#: Ceiling on a Slack call. Slack's own inbound budget is three seconds, and a
#: request that hangs here holds a worker while a customer stares at a spinner.
REQUEST_TIMEOUT_SECONDS = 10.0


class SlackInstallFailure(StrEnum):
    """Why an install did not complete, as a bounded code.

    Reaches the customer's browser as a query parameter, so every value is a word
    we chose. The set is deliberately coarser than the causes: a state that was
    forged, replayed, or belonged to a different person all report
    ``state_rejected``, because telling a caller *which* of the three failed
    tells an attacker which half of the check to work on.
    """

    #: The person declined on Slack's consent screen — or Slack returned some
    #: other ``error`` parameter we do not enumerate. One value on purpose: see
    #: the module docstring on why the callback does not branch on the literal
    #: string ``access_denied``.
    DECLINED = "declined"

    #: The state was missing, unknown, expired, already used, or belonged to
    #: somebody else. Deliberately one code — see the class docstring.
    STATE_REJECTED = "state_rejected"

    #: Slack refused the exchange: a stale code, a redirect URI that does not
    #: match the registered one, a client id it does not recognise.
    EXCHANGE_REJECTED = "exchange_rejected"

    #: The install succeeded and granted less than CAIRN needs. Refused rather
    #: than accepted-and-degraded.
    SCOPES_INSUFFICIENT = "scopes_insufficient"

    #: That Slack workspace is already connected to a different CAIRN workspace.
    ALREADY_CONNECTED = "already_connected"

    #: Slack was unreachable, slow, or answered with something unparseable.
    PROVIDER_UNAVAILABLE = "provider_unavailable"

    #: Throttled. Time fixes this one and nothing else does.
    RATE_LIMITED = "rate_limited"

    #: Slack is not configured on this deployment. An operator problem, not the
    #: customer's, and it must not present as "Slack said no".
    NOT_CONFIGURED = "not_configured"


#: What each failure means in the vocabulary the rest of the product reports on.
#:
#: Mapped rather than passed around: `ConnectorErrorCategory` is what staff
#: diagnostics and the customer's own integrations screen read, and a failure
#: whose category is chosen at the raise site is one that eventually gets a
#: category chosen during an incident.
_FAILURE_CATEGORIES: Mapping[SlackInstallFailure, ConnectorErrorCategory] = {
    # The customer said no. Not an outage, and specifically *not* something an
    # operator should respond to by re-issuing credentials — the whole reason
    # `PERMISSION_REVOKED` is separate from `AUTHENTICATION_EXPIRED`.
    SlackInstallFailure.DECLINED: ConnectorErrorCategory.PERMISSION_REVOKED,
    SlackInstallFailure.SCOPES_INSUFFICIENT: ConnectorErrorCategory.PERMISSION_REVOKED,
    # Our own CSRF guard refusing, or Slack refusing our request shape. Both are
    # "something about this connection attempt is wrong", which is what
    # CONFIGURATION_INVALID says.
    SlackInstallFailure.STATE_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SlackInstallFailure.EXCHANGE_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SlackInstallFailure.ALREADY_CONNECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SlackInstallFailure.NOT_CONFIGURED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    SlackInstallFailure.PROVIDER_UNAVAILABLE: ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
    SlackInstallFailure.RATE_LIMITED: ConnectorErrorCategory.RATE_LIMITED,
}

#: Slack's documented ``error`` values, mapped to ours.
#:
#: The lookup is one-way and lossy on purpose: the key is consumed here and never
#: stored, logged or returned. Anything absent becomes ``EXCHANGE_REJECTED``,
#: which is the honest answer for "Slack refused and we do not have a better word
#: for it" — better than inventing a category from a string we did not expect.
_SLACK_ERROR_FAILURES: Mapping[str, SlackInstallFailure] = {
    "invalid_code": SlackInstallFailure.EXCHANGE_REJECTED,
    "bad_redirect_uri": SlackInstallFailure.EXCHANGE_REJECTED,
    "invalid_client_id": SlackInstallFailure.EXCHANGE_REJECTED,
    "invalid_scope": SlackInstallFailure.EXCHANGE_REJECTED,
    "unapproved_scope": SlackInstallFailure.SCOPES_INSUFFICIENT,
    "access_denied": SlackInstallFailure.DECLINED,
    "ratelimited": SlackInstallFailure.RATE_LIMITED,
    "rate_limited": SlackInstallFailure.RATE_LIMITED,
    "invalid_auth": SlackInstallFailure.EXCHANGE_REJECTED,
    "account_inactive": SlackInstallFailure.EXCHANGE_REJECTED,
    "token_revoked": SlackInstallFailure.EXCHANGE_REJECTED,
    "missing_scope": SlackInstallFailure.SCOPES_INSUFFICIENT,
    "fatal_error": SlackInstallFailure.PROVIDER_UNAVAILABLE,
    "service_unavailable": SlackInstallFailure.PROVIDER_UNAVAILABLE,
}


def category_for(failure: SlackInstallFailure) -> ConnectorErrorCategory:
    """The bounded category a failure reports as.

    A function rather than a dict other modules reach into, so the mapping has
    one reader and the router cannot grow a second opinion about what "declined"
    means.
    """
    return _FAILURE_CATEGORIES[failure]


def failure_for_slack_error(error: str) -> SlackInstallFailure:
    """Translate a Slack ``error`` value, and discard it.

    Public because the OAuth *callback* receives Slack errors as query parameters
    rather than in a response body, so the router needs this translation too —
    and it needs it to be the same one, or a denial would categorise differently
    depending on which half of the flow reported it.

    Unknown values become ``DECLINED`` rather than ``EXCHANGE_REJECTED`` here.
    On the callback specifically, the overwhelmingly likely meaning of an
    unrecognised ``error`` is the person pressing Cancel — Slack does not
    document the exact value, which is the whole reason this branch exists.
    """
    return _SLACK_ERROR_FAILURES.get(error, SlackInstallFailure.DECLINED)


class SlackInstallError(Exception):
    """An install that will not complete, expressed in terms safe to show.

    Carries no Slack text. ``detail`` is a sentence written here, in this file,
    reviewed once — which is what makes it safe to put in a response, and what
    stops a provider message reaching a customer's browser because it happened to
    be the most informative thing available at the raise site.
    """

    def __init__(self, failure: SlackInstallFailure, detail: str) -> None:
        self.failure = failure
        self.category = _FAILURE_CATEGORIES[failure]
        self.detail = detail
        super().__init__(f"{failure}: {detail}")


@final
@dataclass(frozen=True, slots=True)
class SlackChannel:
    """One public channel, as Slack described it just now.

    A transport object, never persisted. ``name`` exists so the picker is usable
    — an admin choosing between ``C0A1B2C3D4`` and ``C0A1B2C3D5`` is an admin who
    will select the wrong one — and it reaches exactly one place: the channel-list
    response, read by the Owner or Admin who is already looking at these names in
    Slack. It is not stored, not logged and not echoed back on any other endpoint.
    """

    id: str
    name: str

    #: Whether the CAIRN bot is in this channel *right now*.
    #:
    #: The single most important field on this object, and the one a picker
    #: without it makes unusable. ``channels:history`` grants the right to
    #: receive public-channel events, not to receive them from channels the bot
    #: was never added to — so a channel selected here with ``False`` here
    #: delivers nothing, silently, until a human runs ``/invite``.
    bot_is_member: bool


@final
@dataclass(frozen=True, slots=True)
class SlackTokenGrant:
    """What Slack handed back for one successful install."""

    #: The ``xoxb-`` bot token. A `SecretValue`, so the dataclass's generated
    #: ``repr`` — which is exactly what a traceback or a structlog rendering
    #: reaches for — prints the redaction placeholder instead of the token.
    bot_token: SecretValue

    #: Slack's team id, from the **nested** ``team.id``. Not the flat ``team_id``,
    #: which is a v1 field and absent from a v2 exchange: reading it yields
    #: ``None``, which then becomes an account id of "None" on a real connection.
    team_id: str

    #: The workspace's display name, for the integrations screen. Nullable
    #: because a missing name should render as the id rather than as a guess.
    team_label: str | None

    #: What was actually granted, parsed from the comma-separated ``scope``
    #: string. Frozen set rather than the raw string so "did we get what we need"
    #: is a set operation and cannot be answered with `in` on a substring —
    #: ``"channels:read" in "channels:read_only"`` is the bug that check invites.
    granted_scopes: frozenset[str]

    #: Slack's app id, used with the team id to form the installation identity.
    app_id: str

    @property
    def installation_id(self) -> str:
        """The provider's identity for *this authorisation*.

        Slack issues nothing that plays GitHub's installation-id role, so it is
        composed: app plus team. Composed this way rather than from something
        that changes on reinstall — the bot user id, say — precisely because
        ``source_connections`` makes ``(provider, installation_id)`` globally
        unique, and that constraint is what stops one Slack workspace being
        connected to two CAIRN workspaces and feeding each the other's activity.
        A per-install identifier would make a reinstall look like a different
        customer and let the second one through.
        """
        return f"{self.app_id}:{self.team_id}"


class SlackApi(Protocol):
    """Everything this package does over the network.

    A protocol with two methods, so a unit test supplies an object rather than
    patching a module global or intercepting a transport. Structural typing
    rather than a base class: the test double does not import anything from here
    to satisfy it, so nothing about the double can drift into production code.

    Implementations raise :class:`SlackInstallError` and nothing else — the
    translation from HTTP failures, ``ok: false`` bodies and unparseable
    responses happens at the boundary, so no caller ever sees an ``httpx``
    exception or a Slack error string.
    """

    async def exchange_code(self, *, code: str, redirect_uri: str) -> SlackTokenGrant:
        """Trade an install code for a bot token."""
        ...

    async def list_public_channels(self, *, token: SecretValue) -> tuple[SlackChannel, ...]:
        """List the workspace's non-archived public channels."""
        ...


@final
class HttpSlackApi:
    """The real one. The only code in CAIRN that calls slack.com."""

    __slots__ = ("_client_id", "_client_secret")

    def __init__(self, *, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            # Refused at construction rather than at the call, so "Slack is not
            # configured" surfaces as a clear operator error before a customer
            # is sent to an authorise URL that Slack will reject.
            raise SlackInstallError(
                SlackInstallFailure.NOT_CONFIGURED,
                "Slack is not configured on this deployment.",
            )
        self._client_id = client_id
        self._client_secret = client_secret

    async def exchange_code(self, *, code: str, redirect_uri: str) -> SlackTokenGrant:
        """POST ``oauth.v2.access``, then believe only what the body says."""
        payload = await self._post(
            ACCESS_TOKEN_URL,
            {
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                # Sent again on the exchange even though Slack already has it
                # from the authorise step: Slack compares the two, and a mismatch
                # is `bad_redirect_uri` rather than a token issued against a URL
                # nobody registered.
                "redirect_uri": redirect_uri,
            },
        )
        return _grant_from(payload)

    async def list_public_channels(self, *, token: SecretValue) -> tuple[SlackChannel, ...]:
        """GET ``conversations.list``, following cursors to the end."""
        channels: list[SlackChannel] = []
        cursor = ""
        # Bounded rather than `while True`. A provider that keeps returning a
        # cursor — through a bug or a hostile response — would otherwise spin
        # forever inside a request handler.
        for _ in range(_MAX_CHANNEL_PAGES):
            params = {
                "types": "public_channel",
                # Archived channels are not places work is happening, and every
                # one of them is a row in a picker somebody has to scroll past.
                "exclude_archived": "true",
                "limit": str(_CHANNEL_PAGE_SIZE),
            }
            if cursor:
                params["cursor"] = cursor
            payload = await self._get(_CONVERSATIONS_LIST_URL, params, token=token)
            channels.extend(_channels_from(payload))
            cursor = _next_cursor(payload)
            if not cursor:
                break
        return tuple(channels)

    async def _post(self, url: str, form: Mapping[str, str]) -> Mapping[str, object]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(url, data=dict(form))
            except httpx.HTTPError as exc:
                # `from None` deliberately absent: the chained exception stays
                # available to the logger, and it carries no Slack error body —
                # a transport failure has no response to quote.
                raise _unavailable() from exc
        return _body(response)

    async def _get(
        self, url: str, params: Mapping[str, str], *, token: SecretValue
    ) -> Mapping[str, object]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.get(
                    url,
                    params=dict(params),
                    # `reveal()` at the one point the token has to leave the
                    # wrapper. Greppable, which is the whole design of
                    # `SecretValue`.
                    headers={"Authorization": f"Bearer {token.reveal()}"},
                )
            except httpx.HTTPError as exc:
                raise _unavailable() from exc
        return _body(response)


_CONVERSATIONS_LIST_URL = "https://slack.com/api/conversations.list"

#: Slack's maximum is 1000 and its own guidance is to stay well under it; 200 is
#: the value Slack's docs use in examples and the one least likely to be throttled.
_CHANNEL_PAGE_SIZE = 200

#: Ten pages, so two thousand channels. Past that the picker is not the problem.
_MAX_CHANNEL_PAGES = 10


def _unavailable() -> SlackInstallError:
    return SlackInstallError(
        SlackInstallFailure.PROVIDER_UNAVAILABLE,
        "Slack could not be reached. Nothing was changed; try again shortly.",
    )


def _body(response: httpx.Response) -> Mapping[str, object]:
    """Read a Slack response, checking ``ok`` rather than the status code.

    HTTP 429 is the one status that carries meaning on its own — Slack sends it
    with a ``Retry-After`` and frequently an empty body — so it is handled before
    the body is parsed. Everything else arrives as 200 with ``ok: false``, which
    is why no other status branch exists here: adding one would create a second
    place failures are detected, and the second place is always the one that
    misses a case.
    """
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise SlackInstallError(
            SlackInstallFailure.RATE_LIMITED,
            "Slack is rate-limiting this workspace. Nothing was changed; try again shortly.",
        )

    try:
        parsed: object = response.json()
    except ValueError as exc:
        # Slack served something that is not JSON — a proxy error page, an
        # outage splash. Treated as the provider being unavailable rather than as
        # a rejected request, because a rejection would send an operator looking
        # at our configuration for a fault that is not there.
        raise _unavailable() from exc

    if not isinstance(parsed, dict):
        raise _unavailable()

    if parsed.get("ok") is not True:
        # `is not True` rather than `not parsed.get("ok")`, so a missing key, a
        # null, and the string "false" are all failures. A truthiness check would
        # accept `"ok": "false"` as success.
        raise _rejected(parsed.get("error"))

    return parsed


def _rejected(error: object) -> SlackInstallError:
    """Translate Slack's ``error`` into ours, discarding the original.

    The raw value is read here and goes no further — not into the exception, not
    into a log field, not into a response. Slack's error strings are short but
    the surrounding response is not, and the habit of "carry it just in case" is
    how a provider payload ends up rendered on a customer's screen.
    """
    failure = SlackInstallFailure.EXCHANGE_REJECTED
    if isinstance(error, str):
        failure = _SLACK_ERROR_FAILURES.get(error, SlackInstallFailure.EXCHANGE_REJECTED)
    return SlackInstallError(failure, _REJECTION_DETAILS[failure])


#: One sentence per failure, written here rather than at each raise site.
_REJECTION_DETAILS: Mapping[SlackInstallFailure, str] = {
    SlackInstallFailure.DECLINED: ("The Slack authorisation was declined. Nothing was connected."),
    SlackInstallFailure.STATE_REJECTED: (
        "This install link is no longer valid. Start again from your workspace settings."
    ),
    SlackInstallFailure.EXCHANGE_REJECTED: (
        "Slack refused to complete the install. Start again from your workspace settings."
    ),
    SlackInstallFailure.SCOPES_INSUFFICIENT: (
        "Slack granted fewer permissions than CAIRN needs, so nothing was connected."
    ),
    SlackInstallFailure.ALREADY_CONNECTED: (
        "That Slack workspace is already connected to another CAIRN workspace."
    ),
    SlackInstallFailure.PROVIDER_UNAVAILABLE: (
        "Slack could not be reached. Nothing was changed; try again shortly."
    ),
    SlackInstallFailure.RATE_LIMITED: (
        "Slack is rate-limiting this workspace. Nothing was changed; try again shortly."
    ),
    SlackInstallFailure.NOT_CONFIGURED: ("Slack is not configured on this deployment."),
}


def _text(value: object) -> str | None:
    """A non-empty string, or nothing. Slack sends ``null`` for absent fields."""
    return value if isinstance(value, str) and value else None


def _grant_from(payload: Mapping[str, object]) -> SlackTokenGrant:
    """Build a grant, refusing anything that is not fully formed.

    Every field is checked because a partially-read response produces a
    connection that exists and cannot work — an empty ``team_id`` matches no
    inbound event, and an empty token authenticates as nobody while the
    integrations screen says "connected".
    """
    token = _text(payload.get("access_token"))
    app_id = _text(payload.get("app_id"))

    # **Nested**, not the flat `team_id`. The flat field is v1; a v2 exchange
    # does not carry it, so reading it gives `None` and the connection ends up
    # keyed on nothing.
    team = payload.get("team")
    team_id = _text(team.get("id")) if isinstance(team, dict) else None
    team_label = _text(team.get("name")) if isinstance(team, dict) else None

    # A **comma-separated string**, not an array. Splitting a list gives
    # characters; iterating a string gives characters too, which is the version
    # that fails silently by never matching a scope.
    raw_scope = _text(payload.get("scope")) or ""
    granted = frozenset(part.strip() for part in raw_scope.split(",") if part.strip())

    if token is None or team_id is None or app_id is None:
        raise SlackInstallError(
            SlackInstallFailure.EXCHANGE_REJECTED,
            "Slack's response was missing information CAIRN needs, so nothing was connected.",
        )

    return SlackTokenGrant(
        bot_token=SecretValue(token),
        team_id=team_id,
        team_label=team_label,
        granted_scopes=granted,
        app_id=app_id,
    )


def _channels_from(payload: Mapping[str, object]) -> list[SlackChannel]:
    """Read one page of ``conversations.list``, skipping anything malformed."""
    raw = payload.get("channels")
    if not isinstance(raw, list):
        return []

    channels: list[SlackChannel] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        channel_id = _text(item.get("id"))
        if channel_id is None:
            continue
        channels.append(
            SlackChannel(
                id=channel_id,
                # Falls back to the id rather than to an empty string: a picker
                # row with a blank label is one a customer cannot choose between.
                name=_text(item.get("name")) or channel_id,
                bot_is_member=item.get("is_member") is True,
            )
        )
    return channels


def _next_cursor(payload: Mapping[str, object]) -> str:
    metadata = payload.get("response_metadata")
    if not isinstance(metadata, dict):
        return ""
    return _text(metadata.get("next_cursor")) or ""


# -- The authorise URL ------------------------------------------------------


def is_configured(settings: Settings) -> bool:
    """Whether this deployment holds Slack OAuth credentials.

    **One predicate, read by both halves of the same answer.** The install route
    refuses with a 503 when it is false, and the integrations status route
    reports it so the interface can say "Not set up" *before* somebody presses
    Connect. When those two were separate expressions the screen could offer a
    control whose only outcome was a failure dialog — which is what the reader
    then read as CAIRN being broken.

    The client id alone, because that is what the guard has always been and what
    `build_authorize_url` cannot do without. The secret is checked where it is
    used, by `HttpSlackApi`, and is never read here: a status route must not
    touch a secret to answer a boolean.
    """
    return bool(settings.slack_client_id)


def build_authorize_url(settings: Settings, *, state: str) -> str:
    """Where to send the customer's browser.

    Built from settings, never from the request. A redirect URI assembled from an
    attacker-supplied ``Host`` header sends the install code — and therefore the
    workspace's bot token — somewhere the attacker controls, which is the same
    defect `public_app_url` exists to avoid for verification links.

    ``user_scope`` is deliberately absent, not empty. Sending it empty is
    harmless today and is one character away from requesting permissions in a
    *person's* name rather than the app's, which is a category of access this
    product does not want to hold.
    """
    if not is_configured(settings):
        raise SlackInstallError(
            SlackInstallFailure.NOT_CONFIGURED,
            "Slack is not configured on this deployment.",
        )
    query = urlencode(
        {
            "client_id": settings.slack_client_id,
            "scope": ",".join(REQUIRED_BOT_SCOPES),
            "redirect_uri": settings.slack_redirect_uri,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


# -- The state parameter ----------------------------------------------------


async def issue_state(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Start an install. Returns the nonce and when it lapses.

    The nonce is 256 bits from ``secrets`` — the same generator invitations and
    sessions use — and only its SHA-256 is stored. A predictable value here is a
    CSRF hole with extra steps: an attacker who can guess a state can hand a
    victim a callback URL that binds *the attacker's* Slack workspace to the
    victim's CAIRN workspace, and from then on the attacker's channels feed the
    victim's briefs.
    """
    moment = now or datetime.now(UTC)

    # Clear this workspace's finished states first. Cheap, uses the expiry index,
    # and keeps the table from growing by one permanent row per abandoned
    # install. Scoped to the tenant so it cannot become a cross-tenant delete.
    await db.execute(
        delete(SlackOAuthState).where(
            SlackOAuthState.tenant_id == tenant_id,
            SlackOAuthState.expires_at <= moment,
        )
    )

    nonce = generate_token()
    expires_at = moment + STATE_TTL
    db.add(
        SlackOAuthState(
            tenant_id=tenant_id,
            initiated_by_user_id=user_id,
            state_hash=hash_token(nonce),
            expires_at=expires_at,
        )
    )
    await db.flush()
    return nonce, expires_at


async def consume_state(
    db: AsyncSession,
    *,
    state: str,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> SlackOAuthState:
    """Claim a state exactly once, or refuse.

    **One statement, not read-then-write.** The ``UPDATE ... WHERE consumed_at IS
    NULL ... RETURNING`` is what makes single-use true under concurrency: two
    callbacks arriving together would both pass a separate "is it unused" read
    and both proceed, which is precisely the replay this exists to stop.

    The user check is part of the same predicate. Being a member of the same
    workspace is not enough — the person who finishes an install must be the
    person who started it, or a state leaked through a shared screen or a proxy
    log is redeemable by whoever picked it up.

    Raises:
        SlackInstallError: Unknown, expired, already used, or someone else's.
            One failure code for all four, so the response does not tell an
            attacker which half of the check to work on.
    """
    moment = now or datetime.now(UTC)

    claimed = await db.scalar(
        update(SlackOAuthState)
        .where(
            SlackOAuthState.state_hash == hash_token(state),
            SlackOAuthState.consumed_at.is_(None),
            SlackOAuthState.expires_at > moment,
            SlackOAuthState.initiated_by_user_id == user_id,
        )
        .values(consumed_at=moment)
        .returning(SlackOAuthState)
    )
    if claimed is None:
        raise SlackInstallError(
            SlackInstallFailure.STATE_REJECTED,
            _REJECTION_DETAILS[SlackInstallFailure.STATE_REJECTED],
        )
    return claimed


# -- The connection ---------------------------------------------------------


def verify_granted_scopes(grant: SlackTokenGrant) -> None:
    """Refuse an install that was granted less than CAIRN needs.

    Slack can grant a subset without failing the exchange — an admin narrowing
    the request on the consent screen, or an enterprise policy trimming it. The
    result is an install that reports success and delivers nothing, and the
    customer discovers it a week later from an empty brief rather than from us.

    A set difference, not a substring test: ``"channels:read" in scope_string``
    is also true for ``channels:read_only``, and a check that can be satisfied by
    a scope Slack does not have is not a check.

    Raises:
        SlackInstallError: One or more required scopes were not granted. The
            message names none of them — which scopes a product asks for is not
            something to disclose in a failure a stranger can trigger.
    """
    missing = set(REQUIRED_BOT_SCOPES) - grant.granted_scopes
    if missing:
        raise SlackInstallError(
            SlackInstallFailure.SCOPES_INSUFFICIENT,
            _REJECTION_DETAILS[SlackInstallFailure.SCOPES_INSUFFICIENT],
        )


async def find_connection(db: AsyncSession, *, tenant_id: uuid.UUID) -> SourceConnection | None:
    """This workspace's Slack connection, connected or not."""
    # Annotated rather than returned inline: `scalar` is typed `Any`, and an
    # unannotated return would let this function silently start returning
    # something else the day the query changes.
    connection: SourceConnection | None = await db.scalar(
        select(SourceConnection).where(
            SourceConnection.tenant_id == tenant_id,
            SourceConnection.provider == ConnectorProvider.SLACK,
        )
    )
    return connection


async def record_installation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    grant: SlackTokenGrant,
    now: datetime | None = None,
) -> SourceConnection:
    """Create or revive the Slack connection, and store the bot token.

    Scope verification happens here, first, rather than at the call site. A
    caller that forgets it produces a connection that looks healthy and never
    delivers, and "the check is in the handler" holds only until the second
    handler.

    **Connecting starts no historical collection.** Same rule as
    ``connect_github``, and it matters more here: Slack's ``conversations.history``
    would happily return years of messages from every channel, and a connector
    that reaches back on its own has read a great deal that nobody selected a
    channel for. Nothing is processed until a channel is selected, and even then
    only from events that arrive afterwards.

    Raises:
        SlackInstallError: Scopes fell short, or that Slack workspace already
            belongs to a different CAIRN workspace.
    """
    verify_granted_scopes(grant)
    moment = now or datetime.now(UTC)

    existing = await db.scalar(
        select(SourceConnection).where(
            SourceConnection.provider == ConnectorProvider.SLACK,
            SourceConnection.installation_id == grant.installation_id,
        )
    )
    if existing is not None and existing.tenant_id != tenant_id:
        # The `(provider, installation_id)` unique constraint would refuse this
        # anyway, as an IntegrityError several frames later. Caught here so the
        # customer gets a sentence instead of a 500 — and so the reason is
        # recorded in one place: two workspaces claiming one Slack team would
        # each receive the other's activity.
        raise SlackInstallError(
            SlackInstallFailure.ALREADY_CONNECTED,
            _REJECTION_DETAILS[SlackInstallFailure.ALREADY_CONNECTED],
        )

    connection = existing
    if connection is None:
        connection = SourceConnection(
            tenant_id=tenant_id,
            provider=ConnectorProvider.SLACK,
            external_account_id=grant.team_id,
            installation_id=grant.installation_id,
        )
        db.add(connection)

    connection.external_account_label = grant.team_label
    connection.external_account_id = grant.team_id
    # Sorted, so two identical installs produce identical rows and a diff of the
    # column means the grant actually changed.
    connection.scopes = sorted(grant.granted_scopes)
    connection.state = ConnectionState.CONNECTED
    connection.connected_at = moment
    connection.disconnected_at = None
    connection.revoked_at = None
    # Not HEALTHY. Nothing has arrived yet, and a connection that reports health
    # it has not measured is the exact failure `ConnectionHealth.UNKNOWN` exists
    # for — a green tick over a feed that never starts.
    connection.health = ConnectionHealth.UNKNOWN
    connection.last_error_category = None
    connection.last_error_at = None
    connection.authorised_by_user_id = user_id
    connection.authorised_at = moment

    # The one place a Slack bot token is written, and it goes through the
    # encrypting path. There is no branch here that stores it any other way.
    store_secret(connection, grant.bot_token)
    await db.flush()

    await logger.ainfo(
        "slack.connected",
        tenant_id=str(tenant_id),
        authorised_by=str(user_id),
        # Scope *names* are ours, not the customer's, so they are safe and they
        # are the field that makes "why is nothing arriving" answerable. The team
        # id, the team name and the token are all deliberately absent.
        granted_scopes=sorted(grant.granted_scopes),
    )
    return connection


async def disconnect(connection: SourceConnection, *, now: datetime | None = None) -> None:
    """Stop collecting, and drop the credential.

    Both halves, always. Marking a connection disconnected while keeping its
    token leaves CAIRN holding a live grant to read a customer's conversations
    after they asked it to stop — which is not a smaller version of the promise,
    it is the opposite of it.

    ``DISCONNECTED`` rather than ``REVOKED``: this is our side stopping, and
    reconnecting is a click. Revoked is Slack's side stopping and needs a fresh
    authorisation.

    **This does not delete anything already recorded**, and the endpoint says so.
    Facts derived from Slack messages remain, because they are part of a record
    other things cite; what stops is new collection. Claiming otherwise would be
    the easier sentence to write and a false one.
    """
    connection.state = ConnectionState.DISCONNECTED
    connection.disconnected_at = now or datetime.now(UTC)
    clear_secret(connection)
