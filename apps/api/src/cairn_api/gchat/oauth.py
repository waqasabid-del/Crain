"""The Google Chat install: authorise, come back, prove it was us, store the token.

Everything in this package that touches the network is in this file, behind
:class:`GoogleChatApi`. That is not tidiness — it is what makes "no unit test
calls Google" enforceable by construction rather than by everyone remembering,
and it means the failure translation below has exactly one place to live.

**Five things about Google's OAuth that this file is shaped by, and that are easy
to get wrong from the documentation alone.**

*A refresh token is not guaranteed.* Google issues one only when
``access_type=offline`` **and** ``prompt=consent`` are both sent. A person who
consented to this app before gets **no** ``refresh_token`` on re-authorisation if
``prompt=consent`` is missing — the exchange succeeds, the connection looks
perfect, and it dies silently when the first access token lapses an hour later.
So a token response without a refresh token is a **hard failure at connect
time**, never a warning: see :func:`require_refresh_token`.

*The consent screen's publishing status changes how long a connection lives.*
An external-user-type screen in "Testing" issues refresh tokens that **expire in
seven days**. Until the app is published and verified, every connection breaks
weekly, and the symptom is ``invalid_grant`` on refresh — which reads like
revocation. There is also a ceiling of 100 refresh tokens per account per client
id, with the oldest silently invalidated. Both are recorded in
:data:`TESTING_MODE_REFRESH_TOKEN_WARNING` rather than in someone's memory.

*Users may grant a subset.* ``include_granted_scopes=true`` is sent and the token
response's ``scope`` is the authority on what was actually granted. CAIRN
verifies the granted set **equals** the allowlist before marking anything
connected — see :func:`verify_granted_scopes` for why equality rather than
containment.

*PKCE is documented for installed apps and merely recommended for confidential
web clients.* Google does not formally specify ``code_challenge`` for a web
client holding a secret. It is sent anyway — it is strictly better and costs one
hash — but it is deliberately **not** the only CSRF defence: the server-side,
single-use, user-bound ``state`` below is. Treating PKCE as the CSRF control
would be relying on a parameter Google does not promise to enforce for this
client type.

*Personal Gmail accounts cannot authorise this.* Google requires the account
configuring the Chat API to belong to a Workspace organisation. That surfaces as
a 403 on the first Chat call rather than as an OAuth error, so the install
**probes** ``spaces.list`` before recording anything and fails with
:attr:`GoogleChatInstallFailure.NOT_A_WORKSPACE_ACCOUNT` — an explicit sentence
at connect time instead of a mysterious silence a week later.

**Nothing here ever returns, logs or raises a Google error string.** Google's
messages quote the request that failed, which for this connector means space
display names and the authorising person's address. Failures become a
:class:`GoogleChatInstallFailure` (ours, bounded) plus a
``ConnectorErrorCategory``, and the raw string is discarded at the boundary.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
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
from cairn_api.connectors.credentials import SecretValue, clear_secret, read_secret, store_secret
from cairn_api.db.connector_models import (
    ConnectionHealth,
    ConnectionState,
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.gchat_models import GoogleChatOAuthState

logger = structlog.get_logger(__name__)

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 — a URL, not a token
SPACES_LIST_URL = "https://chat.googleapis.com/v1/spaces"

#: The OAuth scopes CAIRN requests, and the complete list.
#:
#: - ``chat.spaces.readonly`` — list the spaces the authorising person can see,
#:   so the customer chooses from a picker rather than pasting resource names.
#:   Google classifies this as **SENSITIVE**.
#: - ``chat.messages.readonly`` — this is what authorises the message-event
#:   subscription itself. Google classifies it as **RESTRICTED**; see
#:   :data:`RESTRICTED_SCOPE_RELEASE_GATE`.
#:
#: There is deliberately no third entry for Workspace Events. Google issues no
#: separate Events scope — the Chat scopes authorise the subscription — and a
#: connector that "just adds one to be safe" would be requesting a capability
#: that does not exist and failing the consent screen.
#:
#: Ordered rather than a set, because this is also the string sent to Google and
#: a set's iteration order would make the authorise URL differ between processes.
REQUIRED_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/chat.spaces.readonly",
    "https://www.googleapis.com/auth/chat.messages.readonly",
)

#: The allowlist as a set, for the equality check. Derived, so the two cannot
#: drift.
ALLOWED_SCOPES: frozenset[str] = frozenset(REQUIRED_SCOPES)

#: Scopes that must never be requested or accepted, pinned so the reasons
#: survive the next person editing a URL-building function.
#:
#: Every one of these is either a **write** capability (``chat.messages.create``,
#: ``chat.spaces.create``, ``chat.delete``, ``chat.import``,
#: ``chat.messages.reactions``) — a coordination tool that can speak or delete in
#: a space is a tool people manage their appearance in front of — or a
#: **breadth** capability (``chat.memberships*``, ``chat.users.*``,
#: ``chat.customemojis``) reaching material nobody selected a space for, or an
#: **impersonation** capability (``chat.admin.*``, ``chat.app.*``,
#: ``chat.bot``) that reads a whole domain rather than one person's spaces.
#:
#: ``chat.spaces`` and ``chat.messages`` without ``.readonly`` are on the list
#: because they are one deleted suffix away from the scopes we do request, which
#: is precisely how an over-broad scope ships.
FORBIDDEN_SCOPES: frozenset[str] = frozenset(
    f"https://www.googleapis.com/auth/{name}"
    for name in (
        "chat.bot",
        "chat.spaces",
        "chat.spaces.create",
        "chat.delete",
        "chat.import",
        "chat.messages",
        "chat.messages.create",
        "chat.messages.reactions",
        "chat.messages.reactions.create",
        "chat.messages.reactions.readonly",
        "chat.memberships",
        "chat.memberships.app",
        "chat.memberships.readonly",
        "chat.customemojis",
        "chat.customemojis.readonly",
        "chat.users.spacesettings",
        "chat.users.readstate",
        "chat.users.sections",
    )
)

#: Whole families that must never appear, matched by prefix.
#:
#: ``chat.admin.*`` reads every space in a domain as an administrator, and
#: ``chat.app.*`` acts as the Chat app rather than as the person who consented.
#: Prefixes rather than an enumeration because Google keeps adding members to
#: both families, and a list of names would silently stop covering the new ones.
FORBIDDEN_SCOPE_PREFIXES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/chat.admin.",
    "https://www.googleapis.com/auth/chat.app.",
)

#: **A release gate, not a note.** Recorded in code because it is the single fact
#: most likely to be discovered late and at the worst moment.
#:
#: ``chat.messages.readonly`` is a RESTRICTED scope. Before this connector can be
#: offered to customers outside the publishing organisation, Google requires app
#: verification **and** an independent security assessment (CASA, producing a
#: Letter of Assessment), repeated annually. There is no read-only Chat message
#: scope that avoids this — dropping to ``chat.spaces.readonly`` alone would
#: leave the connector unable to subscribe to messages at all, which is the whole
#: feature.
#:
#: Asserted by a test so it cannot be deleted quietly during a tidy-up.
RESTRICTED_SCOPE_RELEASE_GATE = (
    "RELEASE GATE: https://www.googleapis.com/auth/chat.messages.readonly is a "
    "RESTRICTED scope. Publishing this connector requires Google OAuth app "
    "verification plus an independent third-party security assessment (CASA), "
    "with annual re-verification. No read-only Chat message scope avoids this."
)

#: The other fact that reads as a defect when it is actually configuration.
#:
#: While the consent screen is in Testing with an external user type, refresh
#: tokens expire after seven days — so every connection breaks weekly and the
#: symptom is ``invalid_grant``, which is indistinguishable from a person
#: revoking access. Also: 100 refresh tokens per Google account per client id,
#: with the oldest silently invalidated.
# The rule matches the name, not the value: "TOKEN" in a constant reads as a
# credential. This one is a sentence shown to an operator.
TESTING_MODE_REFRESH_TOKEN_WARNING = (
    "While the Google consent screen is in Testing with an external user type, "  # noqa: S105
    "refresh tokens expire after 7 days, so every Google Chat connection breaks "
    "weekly until the app is published and verified. Google also allows at most "
    "100 refresh tokens per account per client ID; the oldest is invalidated "
    "silently."
)

#: How long an install may sit half-finished. One browser round trip through one
#: consent screen; an hour would be a CSRF window held open for nobody's benefit.
STATE_TTL = timedelta(minutes=10)

#: Ceiling on a Google call. A request that hangs holds a worker while a customer
#: watches a spinner.
REQUEST_TIMEOUT_SECONDS = 10.0

#: How long before an access token lapses we refresh it anyway.
#:
#: Without a margin, a token fetched with two seconds of life left is used for a
#: request that takes three — and the failure is a 401 in the middle of a listing
#: rather than a refresh nobody noticed.
ACCESS_TOKEN_REFRESH_MARGIN_SECONDS = 60.0

#: What Google returns when it declines to say. An hour is Google's documented
#: default; the value is only a fallback for a malformed response.
DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS = 3600

#: PKCE verifier length in bytes before base64url encoding. 64 bytes encodes to
#: 86 characters, inside RFC 7636's 43-128 range with room to spare.
_PKCE_VERIFIER_BYTES = 64

#: Google's maximum page size for ``spaces.list`` is 1000 and its guidance is to
#: stay well below it.
_SPACE_PAGE_SIZE = 100

#: Ten pages, so a thousand spaces. Past that the picker is not the problem.
_MAX_SPACE_PAGES = 10

#: Only named spaces. Direct messages and unnamed group chats are conversations
#: between individuals, which this product does not read at all — the same
#: boundary the Slack connector draws by requesting no ``im:`` or ``mpim:``
#: scope. Applied as a server-side filter *and* re-checked on the way in, because
#: a filter Google stops honouring must not silently widen what CAIRN offers.
_NAMED_SPACE_FILTER = 'spaceType = "SPACE"'
_NAMED_SPACE_TYPE = "SPACE"


class GoogleChatInstallFailure(StrEnum):
    """Why an install did not complete, as a bounded code.

    Reaches the customer's browser as a query parameter, so every value is a word
    we chose. The set is deliberately coarser than the causes: a state that was
    forged, replayed, or belonged to a different person all report
    ``state_rejected``, because telling a caller *which* of the three failed
    tells an attacker which half of the check to work on.
    """

    #: The person declined on Google's consent screen — or Google returned some
    #: other ``error`` parameter we do not enumerate. The callback branches on
    #: the *presence* of ``error``, never on the literal ``access_denied``.
    DECLINED = "declined"

    #: A Workspace administrator has blocked this scope for the organisation.
    #: Separate from ``declined`` because the person who can fix it is not the
    #: person who saw the screen.
    ADMIN_POLICY_ENFORCED = "admin_policy_enforced"

    #: The state was missing, unknown, expired, already used, or belonged to
    #: somebody else. Deliberately one code — see the class docstring.
    STATE_REJECTED = "state_rejected"

    #: Google refused the exchange: a stale or reused code, a redirect URI that
    #: does not match the registered one, a client id it does not recognise.
    EXCHANGE_REJECTED = "exchange_rejected"

    #: The exchange succeeded and carried no ``refresh_token``. Almost always a
    #: missing ``prompt=consent`` against an account that consented before. A
    #: hard failure, because the alternative is a connection that works for one
    #: hour and then dies with no event to explain it.
    REFRESH_TOKEN_MISSING = "refresh_token_missing"  # noqa: S105 — a failure code

    #: Less was granted than CAIRN needs. Refused rather than
    #: accepted-and-degraded.
    SCOPES_INSUFFICIENT = "scopes_insufficient"

    #: **More** was granted than CAIRN asked for. Also refused — see
    #: `verify_granted_scopes`.
    SCOPES_UNEXPECTED = "scopes_unexpected"

    #: The authorising account is not part of a Google Workspace organisation.
    #: Google requires that it is, and the symptom is otherwise a 403 with no
    #: connection to the decision that caused it.
    NOT_A_WORKSPACE_ACCOUNT = "not_a_workspace_account"

    #: The stored refresh token no longer works — revoked, or lapsed because the
    #: consent screen is still in Testing. Distinct from every other failure
    #: because the response is "reconnect", not "retry".
    AUTHORISATION_EXPIRED = "authorisation_expired"

    #: Google refused a Chat call for this account after the install: the person
    #: lost access, or an admin narrowed the grant.
    ACCESS_FORBIDDEN = "access_forbidden"

    #: This workspace already has a Google Chat connection, or a space is already
    #: being read by another CAIRN workspace.
    ALREADY_CONNECTED = "already_connected"

    #: Google was unreachable, slow, or answered with something unparseable.
    PROVIDER_UNAVAILABLE = "provider_unavailable"

    #: Throttled. Time fixes this one and nothing else does.
    RATE_LIMITED = "rate_limited"

    #: Google Chat is not configured on this deployment. An operator problem, not
    #: the customer's, and it must not present as "Google said no".
    NOT_CONFIGURED = "not_configured"


#: What each failure means in the vocabulary the rest of the product reports on.
#:
#: Mapped rather than chosen at the raise site: `ConnectorErrorCategory` is what
#: staff diagnostics and the customer's own integrations screen read, and a
#: failure whose category is picked where it is raised is one that eventually
#: gets a category picked during an incident.
_FAILURE_CATEGORIES: Mapping[GoogleChatInstallFailure, ConnectorErrorCategory] = {
    # The customer, or their administrator, said no. Not an outage, and
    # specifically not something an operator should answer by re-issuing
    # credentials — which is why `PERMISSION_REVOKED` is separate from
    # `AUTHENTICATION_EXPIRED`.
    GoogleChatInstallFailure.DECLINED: ConnectorErrorCategory.PERMISSION_REVOKED,
    GoogleChatInstallFailure.ADMIN_POLICY_ENFORCED: ConnectorErrorCategory.PERMISSION_REVOKED,
    GoogleChatInstallFailure.SCOPES_INSUFFICIENT: ConnectorErrorCategory.PERMISSION_REVOKED,
    GoogleChatInstallFailure.ACCESS_FORBIDDEN: ConnectorErrorCategory.PERMISSION_REVOKED,
    # Our own CSRF guard refusing, Google refusing our request shape, or a
    # response that is not the one this client is built for. All of them are
    # "something about this connection attempt is wrong".
    GoogleChatInstallFailure.STATE_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleChatInstallFailure.EXCHANGE_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleChatInstallFailure.REFRESH_TOKEN_MISSING: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleChatInstallFailure.SCOPES_UNEXPECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleChatInstallFailure.NOT_A_WORKSPACE_ACCOUNT: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleChatInstallFailure.ALREADY_CONNECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleChatInstallFailure.NOT_CONFIGURED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    # The one failure whose only remedy is a fresh authorisation.
    GoogleChatInstallFailure.AUTHORISATION_EXPIRED: ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
    GoogleChatInstallFailure.PROVIDER_UNAVAILABLE: ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
    GoogleChatInstallFailure.RATE_LIMITED: ConnectorErrorCategory.RATE_LIMITED,
}

#: Google's documented OAuth ``error`` values, mapped to ours.
#:
#: The lookup is one-way and lossy on purpose: the key is consumed here and never
#: stored, logged or returned.
_GOOGLE_ERROR_FAILURES: Mapping[str, GoogleChatInstallFailure] = {
    "access_denied": GoogleChatInstallFailure.DECLINED,
    "admin_policy_enforced": GoogleChatInstallFailure.ADMIN_POLICY_ENFORCED,
    "disallowed_useragent": GoogleChatInstallFailure.EXCHANGE_REJECTED,
    "org_internal": GoogleChatInstallFailure.ADMIN_POLICY_ENFORCED,
    "redirect_uri_mismatch": GoogleChatInstallFailure.EXCHANGE_REJECTED,
    "invalid_client": GoogleChatInstallFailure.EXCHANGE_REJECTED,
    "invalid_request": GoogleChatInstallFailure.EXCHANGE_REJECTED,
    "unauthorized_client": GoogleChatInstallFailure.EXCHANGE_REJECTED,
    "unsupported_grant_type": GoogleChatInstallFailure.EXCHANGE_REJECTED,
    "invalid_scope": GoogleChatInstallFailure.SCOPES_INSUFFICIENT,
    # Expired, revoked, or already-redeemed code — and, on a refresh, a refresh
    # token that has lapsed or been withdrawn. The exchange path and the refresh
    # path translate it differently, which is why this table is not consulted
    # directly by either: see `_exchange_failure` and `_refresh_failure`.
    "invalid_grant": GoogleChatInstallFailure.EXCHANGE_REJECTED,
    "rate_limit_exceeded": GoogleChatInstallFailure.RATE_LIMITED,
    "internal_failure": GoogleChatInstallFailure.PROVIDER_UNAVAILABLE,
    "server_error": GoogleChatInstallFailure.PROVIDER_UNAVAILABLE,
    "temporarily_unavailable": GoogleChatInstallFailure.PROVIDER_UNAVAILABLE,
}

#: One sentence per failure, written here rather than at each raise site. This is
#: what makes them safe to put in a response: reviewed once, in one place, and
#: containing not one word Google chose.
_FAILURE_DETAILS: Mapping[GoogleChatInstallFailure, str] = {
    GoogleChatInstallFailure.DECLINED: (
        "The Google authorisation was declined. Nothing was connected."
    ),
    GoogleChatInstallFailure.ADMIN_POLICY_ENFORCED: (
        "A Google Workspace administrator has blocked this access for your "
        "organisation. Nothing was connected; ask them to allow CAIRN."
    ),
    GoogleChatInstallFailure.STATE_REJECTED: (
        "This connection link is no longer valid. Start again from your workspace settings."
    ),
    GoogleChatInstallFailure.EXCHANGE_REJECTED: (
        "Google refused to complete the connection. Start again from your workspace settings."
    ),
    GoogleChatInstallFailure.REFRESH_TOKEN_MISSING: (
        "Google did not issue the long-lived authorisation CAIRN needs, so "
        "nothing was connected. Remove CAIRN from your Google account's "
        "third-party access list and connect again."
    ),
    GoogleChatInstallFailure.SCOPES_INSUFFICIENT: (
        "Google granted fewer permissions than CAIRN needs, so nothing was connected."
    ),
    GoogleChatInstallFailure.SCOPES_UNEXPECTED: (
        "Google granted permissions CAIRN did not ask for, so nothing was connected."
    ),
    GoogleChatInstallFailure.NOT_A_WORKSPACE_ACCOUNT: (
        "Google Chat can only be connected by an account in a Google Workspace "
        "organisation. A personal Google account cannot authorise this."
    ),
    GoogleChatInstallFailure.AUTHORISATION_EXPIRED: (
        "CAIRN's authorisation for Google Chat is no longer accepted. Reconnect "
        "Google Chat from your workspace settings."
    ),
    GoogleChatInstallFailure.ACCESS_FORBIDDEN: (
        "Google refused CAIRN access to this account's spaces. Reconnect Google "
        "Chat from your workspace settings."
    ),
    GoogleChatInstallFailure.ALREADY_CONNECTED: (
        "That Google Chat account or space is already connected to another CAIRN workspace."
    ),
    GoogleChatInstallFailure.PROVIDER_UNAVAILABLE: (
        "Google could not be reached. Nothing was changed; try again shortly."
    ),
    GoogleChatInstallFailure.RATE_LIMITED: (
        "Google is rate-limiting this account. Nothing was changed; try again shortly."
    ),
    GoogleChatInstallFailure.NOT_CONFIGURED: ("Google Chat is not configured on this deployment."),
}


def category_for(failure: GoogleChatInstallFailure) -> ConnectorErrorCategory:
    """The bounded category a failure reports as.

    A function rather than a dict other modules reach into, so the mapping has
    one reader and the router cannot grow a second opinion about what "declined"
    means.
    """
    return _FAILURE_CATEGORIES[failure]


def detail_for(failure: GoogleChatInstallFailure) -> str:
    """The sentence a customer sees for a failure. Ours, always."""
    return _FAILURE_DETAILS[failure]


def failure_for_google_error(error: str) -> GoogleChatInstallFailure:
    """Translate a redirect's ``error`` parameter, and discard it.

    Public because the callback receives Google's errors as query parameters
    rather than in a response body, so the router needs this translation too —
    and it needs it to be the same one, or a denial would categorise differently
    depending on which half of the flow reported it.

    Unknown values become ``DECLINED`` rather than ``EXCHANGE_REJECTED``. On the
    redirect specifically, the overwhelmingly likely meaning of an unrecognised
    ``error`` is the person pressing Cancel.
    """
    return _GOOGLE_ERROR_FAILURES.get(error, GoogleChatInstallFailure.DECLINED)


class GoogleChatInstallError(Exception):
    """An install that will not complete, expressed in terms safe to show.

    Carries no Google text. ``detail`` is a sentence written in this file and
    reviewed once — which is what makes it safe in a response, and what stops a
    provider message reaching a customer's browser because it happened to be the
    most informative thing available at the raise site.
    """

    def __init__(self, failure: GoogleChatInstallFailure, detail: str | None = None) -> None:
        self.failure = failure
        self.category = _FAILURE_CATEGORIES[failure]
        self.detail = detail or _FAILURE_DETAILS[failure]
        super().__init__(f"{failure}: {self.detail}")


@final
@dataclass(frozen=True, slots=True)
class GoogleChatSpace:
    """One space the authorising person can see, as Google described it just now.

    A transport object, never persisted — and note what is **absent**: there is
    no display name field anywhere on it.

    That is the one place this connector deliberately diverges from the Slack
    one, which does show channel names in its picker. A Chat space name is
    frequently the most sensitive string a customer holds ("Acme / Northwind
    diligence", "redundancy planning"), it is not something the API needs, and a
    field that exists is a field that ends up in a log line, an error body or a
    staff screen eventually. The picker is therefore a list of resource names,
    which is less convenient and cannot leak.
    """

    #: ``spaces/{space}``. The only durable identifier a Chat event carries, and
    #: the key every permission here is stored under.
    name: str

    #: Google's ``spaceType``. Carried so the picker can refuse anything that is
    #: not a named space even if Google's own filter stops working.
    space_type: str


@final
@dataclass(frozen=True, slots=True)
class GoogleTokenGrant:
    """What Google handed back for one successful authorisation."""

    #: Short-lived, and never stored. A `SecretValue`, so the dataclass's
    #: generated ``repr`` — exactly what a traceback or a structlog rendering
    #: reaches for — prints the redaction placeholder instead.
    access_token: SecretValue

    #: The durable credential, and the only one that reaches the database.
    refresh_token: SecretValue

    #: What was actually granted, parsed from the **space-separated** ``scope``
    #: string. A frozen set rather than the raw string, so "did we get exactly
    #: what we asked for" is a set operation and cannot be answered with ``in`` on
    #: a substring.
    granted_scopes: frozenset[str]

    #: Seconds of life in the access token, as Google reported it.
    expires_in: int


@final
@dataclass(frozen=True, slots=True)
class GoogleAccessToken:
    """One refreshed access token.

    Separate from :class:`GoogleTokenGrant` because a refresh response has no
    ``refresh_token`` — and a shared type with an optional field is one where
    "did we get a refresh token" becomes a question with two right answers
    depending on which call produced the object.
    """

    access_token: SecretValue
    granted_scopes: frozenset[str]
    expires_in: int


class GoogleChatApi(Protocol):
    """Everything this package does over the network.

    A protocol with three methods, so a unit test supplies an object rather than
    patching a module global or intercepting a transport. Structural typing
    rather than a base class: the test double imports nothing from here to
    satisfy it, so nothing about the double can drift into production code.

    Implementations raise :class:`GoogleChatInstallError` and nothing else — the
    translation from HTTP failures, error bodies and unparseable responses
    happens at the boundary, so no caller ever sees an ``httpx`` exception or a
    Google error string.
    """

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> GoogleTokenGrant:
        """Trade an authorisation code for an access and refresh token."""
        ...

    async def refresh_access_token(self, *, refresh_token: SecretValue) -> GoogleAccessToken:
        """Trade a refresh token for a fresh access token."""
        ...

    async def list_spaces(self, *, access_token: SecretValue) -> tuple[GoogleChatSpace, ...]:
        """List the named spaces the authorising person can see."""
        ...


@final
class HttpGoogleChatApi:
    """The real one. The only code in CAIRN that calls Google's Chat or OAuth endpoints."""

    __slots__ = ("_client_id", "_client_secret")

    def __init__(self, *, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            # Refused at construction rather than at the call, so "Google Chat is
            # not configured" surfaces as a clear operator error before a
            # customer is sent to an authorise URL Google will reject.
            raise GoogleChatInstallError(GoogleChatInstallFailure.NOT_CONFIGURED)
        self._client_id = client_id
        self._client_secret = client_secret

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> GoogleTokenGrant:
        """POST the token endpoint with the code, the secret and the PKCE verifier."""
        payload = await self._post_token(
            {
                "code": code,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                # Sent again even though Google already has it from the
                # authorise step: Google compares the two, and a mismatch is
                # `redirect_uri_mismatch` rather than a token issued against a
                # URL nobody registered.
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                # The PKCE half. Belt and braces alongside the client secret and
                # the server-side state — see the module docstring on why it is
                # sent but not relied on.
                "code_verifier": code_verifier,
            },
            on_invalid_grant=GoogleChatInstallFailure.EXCHANGE_REJECTED,
        )
        return _grant_from(payload)

    async def refresh_access_token(self, *, refresh_token: SecretValue) -> GoogleAccessToken:
        """POST the token endpoint with the stored refresh token."""
        payload = await self._post_token(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                # `reveal()` at the one point the credential has to leave the
                # wrapper. Greppable, which is the whole design of `SecretValue`.
                "refresh_token": refresh_token.reveal(),
                "grant_type": "refresh_token",
            },
            # The difference that matters. On an exchange, `invalid_grant` means
            # a stale code and the answer is "start again". On a refresh it means
            # the standing authorisation is gone — revoked, or lapsed because the
            # consent screen is still in Testing — and the answer is "reconnect".
            # Reporting the first for the second sends an operator looking at our
            # configuration for a fault that is in Google's console.
            on_invalid_grant=GoogleChatInstallFailure.AUTHORISATION_EXPIRED,
        )
        return _access_token_from(payload)

    async def list_spaces(self, *, access_token: SecretValue) -> tuple[GoogleChatSpace, ...]:
        """GET ``spaces.list``, following page tokens to the end."""
        spaces: list[GoogleChatSpace] = []
        page_token = ""
        # Bounded rather than `while True`. A provider that keeps returning a
        # page token — through a bug or a hostile response — would otherwise spin
        # forever inside a request handler.
        for _ in range(_MAX_SPACE_PAGES):
            params = {
                "pageSize": str(_SPACE_PAGE_SIZE),
                "filter": _NAMED_SPACE_FILTER,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = await self._get_chat(SPACES_LIST_URL, params, access_token=access_token)
            spaces.extend(_spaces_from(payload))
            page_token = _text(payload.get("nextPageToken")) or ""
            if not page_token:
                break
        return tuple(spaces)

    async def _post_token(
        self, form: Mapping[str, str], *, on_invalid_grant: GoogleChatInstallFailure
    ) -> Mapping[str, object]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(TOKEN_URL, data=dict(form))
            except httpx.HTTPError as exc:
                # `from None` deliberately absent: the chained exception stays
                # available to the logger and carries no Google error body — a
                # transport failure has no response to quote.
                raise _unavailable() from exc
        return _token_body(response, on_invalid_grant=on_invalid_grant)

    async def _get_chat(
        self, url: str, params: Mapping[str, str], *, access_token: SecretValue
    ) -> Mapping[str, object]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.get(
                    url,
                    params=dict(params),
                    headers={"Authorization": f"Bearer {access_token.reveal()}"},
                )
            except httpx.HTTPError as exc:
                raise _unavailable() from exc
        return _chat_body(response)


def _unavailable() -> GoogleChatInstallError:
    return GoogleChatInstallError(GoogleChatInstallFailure.PROVIDER_UNAVAILABLE)


def _parsed(response: httpx.Response) -> Mapping[str, object]:
    """A JSON object, or "the provider is unavailable".

    Anything that is not a JSON object — an HTML proxy error page, an outage
    splash — is treated as unavailability rather than as a rejected request,
    because a rejection would send an operator looking at our configuration for a
    fault that is not there.
    """
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise _unavailable() from exc
    if not isinstance(payload, dict):
        raise _unavailable()
    return payload


def _token_body(
    response: httpx.Response, *, on_invalid_grant: GoogleChatInstallFailure
) -> Mapping[str, object]:
    """Read an OAuth token response, translating any failure and discarding it.

    Unlike Slack, Google signals failure with the status code *and* an ``error``
    field, so both are consulted — the status first, because a 5xx frequently
    carries no parseable body at all.
    """
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise GoogleChatInstallError(GoogleChatInstallFailure.RATE_LIMITED)
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise _unavailable()

    payload = _parsed(response)

    if response.status_code >= httpx.codes.BAD_REQUEST:
        # The raw value is read here and goes no further — not into the
        # exception, not into a log field, not into a response. The habit of
        # "carry it just in case" is how a provider payload ends up rendered on a
        # customer's screen.
        raw = payload.get("error")
        if raw == "invalid_grant":
            raise GoogleChatInstallError(on_invalid_grant)
        failure = GoogleChatInstallFailure.EXCHANGE_REJECTED
        if isinstance(raw, str):
            failure = _GOOGLE_ERROR_FAILURES.get(raw, GoogleChatInstallFailure.EXCHANGE_REJECTED)
        raise GoogleChatInstallError(failure)

    return payload


def _chat_body(response: httpx.Response) -> Mapping[str, object]:
    """Read a Chat API response, mapping by status alone.

    Deliberately does **not** read Google's ``error.message``. That string names
    the space and frequently the person, and this is the one code path where the
    temptation to pass it through is strongest, because the status code alone is
    less informative. The status code is enough for every action anyone can take.
    """
    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise GoogleChatInstallError(GoogleChatInstallFailure.AUTHORISATION_EXPIRED)
    if response.status_code == httpx.codes.FORBIDDEN:
        # At connect time this is almost always a personal Google account; see
        # `ensure_workspace_account`, which is what performs that translation.
        raise GoogleChatInstallError(GoogleChatInstallFailure.ACCESS_FORBIDDEN)
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise GoogleChatInstallError(GoogleChatInstallFailure.RATE_LIMITED)
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise _unavailable()
    if response.status_code >= httpx.codes.BAD_REQUEST:
        raise GoogleChatInstallError(GoogleChatInstallFailure.EXCHANGE_REJECTED)
    return _parsed(response)


def _text(value: object) -> str | None:
    """A non-empty string, or nothing. Google omits or nulls absent fields."""
    return value if isinstance(value, str) and value else None


def _scopes_from(payload: Mapping[str, object]) -> frozenset[str]:
    """Parse the **space-separated** ``scope`` string.

    Space-separated, not comma-separated — that is OAuth 2.0's encoding and it is
    the opposite of Slack's. Splitting on the wrong character yields one long
    "scope" that matches nothing, and the install then fails as a scope shortfall
    with no hint that the parser is the problem.
    """
    raw = _text(payload.get("scope")) or ""
    return frozenset(part for part in raw.split(" ") if part)


def _lifetime_from(payload: Mapping[str, object]) -> int:
    """``expires_in`` as a positive integer, or Google's documented default."""
    raw = payload.get("expires_in")
    if isinstance(raw, bool):
        # `bool` is an `int` in Python, and `True` would become a one-second
        # lifetime that refreshes on every single call.
        return DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS


def _grant_from(payload: Mapping[str, object]) -> GoogleTokenGrant:
    """Build a grant, refusing anything that is not fully formed.

    The missing ``refresh_token`` is raised as its own failure rather than folded
    into "the response was malformed", because it is not malformed — it is the
    documented behaviour for a re-authorisation without ``prompt=consent``, it is
    the single most likely defect in this flow, and a customer told "Google's
    response was incomplete" has no way to act while a customer told to remove
    CAIRN from their account's access list does.
    """
    access = _text(payload.get("access_token"))
    refresh = _text(payload.get("refresh_token"))

    if access is None:
        raise GoogleChatInstallError(
            GoogleChatInstallFailure.EXCHANGE_REJECTED,
            "Google's response was missing information CAIRN needs, so nothing was connected.",
        )
    if refresh is None:
        raise GoogleChatInstallError(GoogleChatInstallFailure.REFRESH_TOKEN_MISSING)

    return GoogleTokenGrant(
        access_token=SecretValue(access),
        refresh_token=SecretValue(refresh),
        granted_scopes=_scopes_from(payload),
        expires_in=_lifetime_from(payload),
    )


def _access_token_from(payload: Mapping[str, object]) -> GoogleAccessToken:
    access = _text(payload.get("access_token"))
    if access is None:
        raise GoogleChatInstallError(GoogleChatInstallFailure.AUTHORISATION_EXPIRED)
    return GoogleAccessToken(
        access_token=SecretValue(access),
        granted_scopes=_scopes_from(payload),
        expires_in=_lifetime_from(payload),
    )


def _spaces_from(payload: Mapping[str, object]) -> list[GoogleChatSpace]:
    """Read one page of ``spaces.list``, skipping anything malformed.

    Re-applies the named-space filter locally. Google is already asked to filter
    server-side, and doing it twice is the difference between "we asked for named
    spaces" and "we only ever offer named spaces" — the first depends on a query
    parameter continuing to be honoured, and direct messages appearing in a
    picker is not a defect anyone would notice until somebody selected one.
    """
    raw = payload.get("spaces")
    if not isinstance(raw, list):
        return []

    spaces: list[GoogleChatSpace] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        space_type = _text(item.get("spaceType"))
        if name is None or space_type != _NAMED_SPACE_TYPE:
            continue
        spaces.append(GoogleChatSpace(name=name, space_type=space_type))
    return spaces


# -- PKCE -------------------------------------------------------------------


def new_code_verifier() -> str:
    """A fresh PKCE verifier.

    From ``secrets``, like every other nonce in CAIRN. ``token_urlsafe`` produces
    exactly the unreserved character set RFC 7636 allows, so no further
    sanitising is needed — and a verifier built by slicing a UUID would be both
    too short and drawn from a 16-character alphabet.
    """
    return secrets.token_urlsafe(_PKCE_VERIFIER_BYTES)


def code_challenge_for(verifier: str) -> str:
    """The S256 challenge for a verifier: base64url(SHA-256(verifier)), unpadded.

    Unpadded deliberately. RFC 7636 specifies base64url **without** trailing
    ``=``, and Google rejects the padded form — with an error that says the
    challenge is invalid rather than that it is padded.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# -- The authorise URL ------------------------------------------------------


def is_configured(settings: Settings) -> bool:
    """Whether this deployment holds Google Chat OAuth credentials.

    The same single predicate Slack's connector keeps, for the same reason: the
    install route's 503 and the integrations status route's ``configured`` flag
    have to be the same decision, or the screen offers a Connect button whose
    only possible outcome is a failure the reader reads as a fault.

    The client id alone. The secret is checked by `HttpGoogleChatApi` where it is
    used, and a status route must not read a secret to answer a boolean.
    """
    return bool(settings.google_chat_client_id)


def build_authorize_url(settings: Settings, *, state: str, code_verifier: str) -> str:
    """Where to send the customer's browser.

    Built from settings, never from the request. A redirect URI assembled from an
    attacker-supplied ``Host`` header sends the authorisation code — and
    therefore the account's refresh token — somewhere the attacker controls.

    ``access_type=offline`` **and** ``prompt=consent`` are both present and both
    required. Dropping the second is the silent failure this whole module warns
    about: a person who has consented before gets no refresh token, the exchange
    succeeds, and the connection dies an hour later with nothing to explain it.
    """
    if not is_configured(settings):
        raise GoogleChatInstallError(GoogleChatInstallFailure.NOT_CONFIGURED)

    query = urlencode(
        {
            "client_id": settings.google_chat_client_id,
            "redirect_uri": settings.google_chat_redirect_uri,
            "response_type": "code",
            # Space-separated, per OAuth 2.0. Google accepts nothing else.
            "scope": " ".join(REQUIRED_SCOPES),
            "state": state,
            # Without this there is no refresh token at all.
            "access_type": "offline",
            # Without this there is no refresh token on a *re*-authorisation,
            # which is the case nobody tests.
            "prompt": "consent",
            # So the token response's `scope` reports everything this client
            # holds, which is what `verify_granted_scopes` reads.
            "include_granted_scopes": "true",
            "code_challenge": code_challenge_for(code_verifier),
            "code_challenge_method": "S256",
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
) -> tuple[str, str, datetime]:
    """Start an install. Returns the nonce, the PKCE verifier and the expiry.

    The nonce is 256 bits from ``secrets`` — the same generator invitations and
    sessions use — and only its SHA-256 is stored. A predictable value here is a
    CSRF hole with extra steps: an attacker who can guess a state can hand a
    victim a callback URL that binds *the attacker's* Google account to the
    victim's CAIRN workspace, and from then on the attacker's spaces feed the
    victim's briefs.

    The verifier is issued and stored in the same row, because it belongs to the
    same in-flight install and keeping it anywhere else — a cookie, a cache —
    would let the two halves get out of step.
    """
    moment = now or datetime.now(UTC)

    # Clear this workspace's finished states first. Cheap, uses the expiry index,
    # and keeps the table from growing by one permanent row per abandoned
    # install. Scoped to the tenant so it cannot become a cross-tenant delete.
    await db.execute(
        delete(GoogleChatOAuthState).where(
            GoogleChatOAuthState.tenant_id == tenant_id,
            GoogleChatOAuthState.expires_at <= moment,
        )
    )

    nonce = generate_token()
    verifier = new_code_verifier()
    expires_at = moment + STATE_TTL
    db.add(
        GoogleChatOAuthState(
            tenant_id=tenant_id,
            initiated_by_user_id=user_id,
            state_hash=hash_token(nonce),
            code_verifier=verifier,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return nonce, verifier, expires_at


async def consume_state(
    db: AsyncSession,
    *,
    state: str,
    user_id: uuid.UUID,
    now: datetime | None = None,
) -> GoogleChatOAuthState:
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
        GoogleChatInstallError: Unknown, expired, already used, or someone
            else's. One failure code for all four, so the response does not tell
            an attacker which half of the check to work on.
    """
    moment = now or datetime.now(UTC)

    claimed: GoogleChatOAuthState | None = await db.scalar(
        update(GoogleChatOAuthState)
        .where(
            GoogleChatOAuthState.state_hash == hash_token(state),
            GoogleChatOAuthState.consumed_at.is_(None),
            GoogleChatOAuthState.expires_at > moment,
            GoogleChatOAuthState.initiated_by_user_id == user_id,
        )
        .values(consumed_at=moment)
        .returning(GoogleChatOAuthState)
    )
    if claimed is None:
        raise GoogleChatInstallError(GoogleChatInstallFailure.STATE_REJECTED)
    return claimed


# -- What was granted -------------------------------------------------------


def verify_granted_scopes(granted: frozenset[str]) -> None:
    """Refuse anything that is not exactly the two-scope allowlist.

    **Equality, not containment**, and the asymmetry with the Slack connector is
    deliberate. Slack accepts a superset because Slack routinely grants one and
    refusing would reject a perfectly good install. Google's story is different:
    every scope in the forbidden list is a capability over a company's
    conversations that CAIRN has decided not to hold, and ``chat.app.*`` and
    ``chat.admin.*`` read across a whole domain rather than one person's spaces.
    A token carrying one of those is not a better install — it is a token this
    product does not want to be holding, and the honest response is to refuse it
    rather than to store it and use two of its powers.

    The known cost is written down: ``include_granted_scopes=true`` means a
    Google account that has previously granted *other* scopes to this same client
    id can produce a superset here through no fault of the person authorising.
    That is acceptable because this client id exists for this connector alone and
    requests exactly these two scopes, so a third one arriving means something
    about the OAuth client has changed and a human should look at it.

    A set operation, not a substring test: ``"chat.spaces.readonly" in
    scope_string`` is also true of a longer scope, and a check satisfiable by a
    scope Google did not grant is not a check.

    Raises:
        GoogleChatInstallError: ``SCOPES_INSUFFICIENT`` when something is
            missing, ``SCOPES_UNEXPECTED`` when something extra arrived. Neither
            message names a scope — which permissions a product asks for is not
            something to disclose in a failure a stranger can trigger.
    """
    if ALLOWED_SCOPES - granted:
        raise GoogleChatInstallError(GoogleChatInstallFailure.SCOPES_INSUFFICIENT)
    if granted - ALLOWED_SCOPES:
        raise GoogleChatInstallError(GoogleChatInstallFailure.SCOPES_UNEXPECTED)


def require_refresh_token(payload: Mapping[str, object]) -> None:
    """Refuse a token response with no ``refresh_token``.

    Exposed separately from :func:`_grant_from` so the rule can be asserted
    without constructing a whole HTTP response, and so the reasoning has a name.
    A warning here instead of an error produces a connection that works for
    exactly one access-token lifetime and then stops, with the failure landing an
    hour later in a different part of the system.
    """
    if _text(payload.get("refresh_token")) is None:
        raise GoogleChatInstallError(GoogleChatInstallFailure.REFRESH_TOKEN_MISSING)


async def ensure_workspace_account(
    api: GoogleChatApi, *, access_token: SecretValue
) -> tuple[GoogleChatSpace, ...]:
    """Probe the Chat API once, and translate a refusal into a sentence.

    Google requires the account configuring the Chat API to belong to a Workspace
    organisation. A personal Gmail account can complete the whole OAuth flow
    perfectly and then be refused by every Chat call — so without this probe the
    customer gets a connection that reports success, an empty space picker, and
    no explanation anywhere.

    The listing is returned rather than discarded, because the caller wants it
    anyway and a second call would spend a customer's rate limit proving
    something already proved.

    Raises:
        GoogleChatInstallError: ``NOT_A_WORKSPACE_ACCOUNT`` on a refusal. Every
            other failure passes through unchanged — a timeout during the probe
            is a timeout, not a verdict about the customer's account.
    """
    try:
        return await api.list_spaces(access_token=access_token)
    except GoogleChatInstallError as error:
        if error.failure is GoogleChatInstallFailure.ACCESS_FORBIDDEN:
            # Narrowed at connect time only. Later in a connection's life a 403
            # means the person lost access or an admin narrowed the grant, and
            # telling them their account is not a Workspace account would be
            # wrong — which is why this translation lives here rather than in the
            # HTTP layer.
            raise GoogleChatInstallError(
                GoogleChatInstallFailure.NOT_A_WORKSPACE_ACCOUNT
            ) from error
        raise


# -- The connection ---------------------------------------------------------


def installation_id_for(settings: Settings, tenant_id: uuid.UUID) -> str:
    """The value ``source_connections.installation_id`` carries for this provider.

    **Read this before assuming it does what Slack's does.**

    Slack composes its installation id from the app and team ids, which makes the
    global ``(provider, installation_id)`` unique constraint genuinely prevent one
    Slack workspace being connected to two CAIRN workspaces. The two Chat scopes
    CAIRN requests carry **no account identity at all** — no customer id, no
    domain, no address — and CAIRN deliberately does not request an identity
    scope to obtain one. There is therefore nothing to compose that would
    identify the Google organisation, and a value that pretended to would be a
    constraint that looks like it prevents something and does not.

    So this composes the client id and the *CAIRN* tenant, which enforces exactly
    what it can honestly enforce: **one Google Chat connection per CAIRN
    workspace**. The property that actually matters for ingestion — one Chat
    space feeding at most one CAIRN workspace — is enforced instead by the global
    unique constraint on ``google_chat_space_selections.space_name``, where it can
    be checked against a real, globally unique identifier.
    """
    return f"{settings.google_chat_client_id}:{tenant_id}"


async def find_connection(db: AsyncSession, *, tenant_id: uuid.UUID) -> SourceConnection | None:
    """This workspace's Google Chat connection, connected or not."""
    # Annotated rather than returned inline: `scalar` is typed `Any`, and an
    # unannotated return would let this function silently start returning
    # something else the day the query changes.
    connection: SourceConnection | None = await db.scalar(
        select(SourceConnection).where(
            SourceConnection.tenant_id == tenant_id,
            SourceConnection.provider == ConnectorProvider.GOOGLE_CHAT,
        )
    )
    return connection


async def record_installation(
    db: AsyncSession,
    *,
    settings: Settings,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    grant: GoogleTokenGrant,
    now: datetime | None = None,
) -> SourceConnection:
    """Create or revive the Google Chat connection, and store the refresh token.

    Scope verification happens here, first, rather than at the call site. A caller
    that forgets it produces a connection that looks healthy and never delivers,
    and "the check is in the handler" holds only until the second handler.

    **Only the refresh token is stored.** The access token that came with it is
    short-lived and reconstructible from the refresh token in one call, so
    persisting it would put a second live credential in the database to save a
    round trip — and the row would then hold a value that is usually expired,
    which is worse than holding none.

    **Connecting starts no historical collection.** Same rule as ``connect_github``
    and the Slack install, and it matters here too: nothing is processed until a
    space is selected, and even then only from events that arrive afterwards.

    Raises:
        GoogleChatInstallError: Scopes were not exactly the allowlist, or this
            workspace's connection identity is already claimed.
    """
    verify_granted_scopes(grant.granted_scopes)
    moment = now or datetime.now(UTC)
    installation_id = installation_id_for(settings, tenant_id)

    existing = await db.scalar(
        select(SourceConnection).where(
            SourceConnection.provider == ConnectorProvider.GOOGLE_CHAT,
            SourceConnection.installation_id == installation_id,
        )
    )
    if existing is not None and existing.tenant_id != tenant_id:
        # Unreachable while `installation_id_for` includes the tenant, and kept
        # anyway: the unique constraint would otherwise surface as an
        # IntegrityError several frames later, and the day somebody makes the
        # installation id a real account identity this becomes the branch that
        # stops two workspaces claiming one Google organisation.
        raise GoogleChatInstallError(GoogleChatInstallFailure.ALREADY_CONNECTED)

    connection = existing
    if connection is None:
        connection = SourceConnection(
            tenant_id=tenant_id,
            provider=ConnectorProvider.GOOGLE_CHAT,
            external_account_id=installation_id,
            installation_id=installation_id,
        )
        db.add(connection)

    connection.external_account_id = installation_id
    # Deliberately null, forever. The only human-readable label Google would give
    # for this connection is the authorising person's email address or their
    # domain, and this connector stores neither. A workspace's integrations
    # screen shows "Google Chat", which is all it needs to say.
    connection.external_account_label = None
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

    # The one place a Google refresh token is written, and it goes through the
    # encrypting path. There is no branch here that stores it any other way.
    store_secret(connection, grant.refresh_token)
    # A revival must not inherit the previous authorisation's access token.
    forget_access_token(connection.id)
    await db.flush()

    await logger.ainfo(
        "gchat.connected",
        tenant_id=str(tenant_id),
        authorised_by=str(user_id),
        # Scope *names* are ours, not the customer's, so they are safe and they
        # are the field that makes "why is nothing arriving" answerable. No
        # token, no address, no space name.
        granted_scopes=sorted(grant.granted_scopes),
    )
    return connection


async def disconnect(connection: SourceConnection, *, now: datetime | None = None) -> None:
    """Stop collecting, and drop the credential.

    Both halves, always. Marking a connection disconnected while keeping its
    refresh token leaves CAIRN holding a standing grant to read a customer's
    conversations after they asked it to stop — which is not a smaller version of
    the promise, it is the opposite of it.

    ``DISCONNECTED`` rather than ``REVOKED``: this is our side stopping, and
    reconnecting is a click. Revoked is Google's side stopping and needs a fresh
    authorisation.

    **This does not delete anything already recorded**, and the endpoint says so.
    Facts derived from Chat messages remain, because they are part of a record
    other things cite; what stops is new collection.
    """
    connection.state = ConnectionState.DISCONNECTED
    connection.disconnected_at = now or datetime.now(UTC)
    clear_secret(connection)
    forget_access_token(connection.id)


# -- Access tokens ----------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class _CachedToken:
    expires_at: float
    token: SecretValue


#: Per-connection, in-process, never persisted.
#:
#: Keyed on the connection id — which is per-tenant — rather than on anything
#: Google supplies, so there is no key a second workspace could collide with.
#: Process-local because the alternative, a shared cache, would put live access
#: tokens in a store with its own lifetime and its own readers for the sake of
#: saving one token call.
_TOKEN_CACHE: dict[uuid.UUID, _CachedToken] = {}


def forget_access_token(connection_id: uuid.UUID) -> None:
    """Drop one connection's cached access token.

    Called on disconnect and on revival. A workspace that has asked CAIRN to stop
    must not leave a usable token sitting in this process's memory for the next
    hour, and "it expires soon" is not the answer to give somebody who just
    withdrew permission.
    """
    _TOKEN_CACHE.pop(connection_id, None)


def clear_access_token_cache() -> None:
    """Drop every cached token. For tests, which must not inherit each other's."""
    _TOKEN_CACHE.clear()


def mark_refresh_failure(
    connection: SourceConnection,
    error: GoogleChatInstallError,
    *,
    now: datetime | None = None,
) -> None:
    """Record on the connection that a refresh failed, in bounded terms.

    Two outcomes, and the difference is whether the customer has to do something.

    ``AUTHORISATION_EXPIRED`` means the standing grant is gone — revoked by the
    person, withdrawn by an administrator, or lapsed after seven days because the
    consent screen is still in Testing. Nothing retries its way out of that, so
    the connection is marked ``REVOKED``, ingestion stops immediately (the state
    is what `spaces.is_space_permitted` checks), and the dead refresh token is
    destroyed rather than kept for a retry that cannot work.

    Everything else — Google unreachable, throttled — leaves the connection
    authorised and marks it ``FAILING``, because it is not the customer's problem
    and a revocation would ask them to reconnect for an outage that will pass.

    The category is `ConnectorErrorCategory`, never Google's words, because this
    column is rendered on the customer's integrations screen and read by staff
    diagnostics.
    """
    moment = now or datetime.now(UTC)
    connection.last_error_category = error.category
    connection.last_error_at = moment
    connection.health = ConnectionHealth.FAILING
    forget_access_token(connection.id)

    if error.failure is GoogleChatInstallFailure.AUTHORISATION_EXPIRED:
        connection.state = ConnectionState.REVOKED
        connection.revoked_at = moment
        clear_secret(connection)


async def access_token_for(
    api: GoogleChatApi,
    connection: SourceConnection,
    *,
    now: float | None = None,
    at: datetime | None = None,
) -> SecretValue:
    """A usable access token for this connection, refreshing if needed.

    Cached in process for slightly less than its own lifetime, so a customer
    reloading the space picker does not spend a token call per reload. The margin
    is not decoration: a token handed out with two seconds left is a 401 in the
    middle of the next request rather than a refresh nobody noticed.

    On failure the connection is marked before the error propagates, so the
    reason is on the row even if the caller only rolls back and redirects. The
    caller commits — this function does not, because it is called from both a
    request handler and (in time) a worker, and a function that commits somebody
    else's transaction is a function that truncates their unit of work.

    Raises:
        GoogleChatInstallError: The refresh failed, or the connection holds no
            credential at all. ``AUTHORISATION_EXPIRED`` in the second case,
            because from the customer's side "we have no usable authorisation"
            and "the authorisation stopped working" call for the same action.
    """
    moment = now if now is not None else time.monotonic()

    cached = _TOKEN_CACHE.get(connection.id)
    if cached is not None and cached.expires_at > moment:
        return cached.token

    refresh_token = read_secret(connection)
    if refresh_token is None:
        error = GoogleChatInstallError(GoogleChatInstallFailure.AUTHORISATION_EXPIRED)
        mark_refresh_failure(connection, error, now=at)
        raise error

    try:
        refreshed = await api.refresh_access_token(refresh_token=refresh_token)
    except GoogleChatInstallError as error:
        mark_refresh_failure(connection, error, now=at)
        await logger.awarning(
            "gchat.token_refresh_failed",
            tenant_id=str(connection.tenant_id),
            reason=error.failure.value,
            category=error.category.value,
        )
        raise

    # Checked on every refresh, not only at connect. An administrator can narrow
    # a grant after the fact, and Google reports the narrowed set here — so a
    # connection that quietly lost `chat.messages.readonly` is caught on the next
    # refresh rather than by somebody noticing an empty feed.
    verify_granted_scopes(refreshed.granted_scopes)

    lifetime = max(refreshed.expires_in - ACCESS_TOKEN_REFRESH_MARGIN_SECONDS, 0.0)
    _TOKEN_CACHE[connection.id] = _CachedToken(
        expires_at=moment + lifetime, token=refreshed.access_token
    )
    return refreshed.access_token
