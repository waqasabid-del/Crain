"""The Google Meet install: authorise, come back, prove it was us, store the token.

Everything in this package that touches Google's OAuth endpoints is in this file,
behind :class:`GoogleMeetApi`. That is not tidiness — it is what makes "no unit
test calls Google" enforceable by construction, and it gives the failure
translation exactly one place to live.

This is `gchat/oauth.py`'s twin, and the four things that are *different* are the
four things worth reading before editing it.

**One scope, and it is the narrowest Google publishes for Meet.**
``meetings.space.readonly`` reads a meeting space's configuration. It is what
authorises a Workspace Events subscription on that space and nothing more. There
is deliberately **no Drive scope** — Meet transcripts and recordings are Drive
files, so ``drive.readonly`` is what "just let us fetch the transcript" means in
practice, and fetching is Step 36B with its own consent story. There is no
recording scope, no ``meetings.space.created``, no ``meetings.space.settings``,
and no broad Google scope. :data:`FORBIDDEN_SCOPES` names the ones that would
change what this connector *is*, and a test asserts none of them appears in the
authorise URL.

**A separate OAuth client from Google Chat, and this file will not share one.**
:func:`verify_granted_scopes` compares by set *equality* and the Chat connector
sends ``include_granted_scopes=true``. One shared client id therefore means a
person who authorised Chat gets Chat's scopes echoed into Meet's token response
— and both connectors then fail with ``SCOPES_UNEXPECTED``, Meet at install and
Chat at its next refresh. ``config.Settings`` refuses a shared client id
outright; this module reads ``google_meet_client_id`` and never Chat's.

**A refresh token is not guaranteed.** Google issues one only when
``access_type=offline`` **and** ``prompt=consent`` are both sent. A person who
consented before gets **no** ``refresh_token`` without the second — the exchange
succeeds, the connection looks perfect, and it dies an hour later. So a token
response without one is a hard failure at connect time.

**The consent screen's publishing status decides how long a connection lives.**
An external-user-type screen in "Testing" issues refresh tokens that expire in
seven days, and the symptom is ``invalid_grant`` on refresh, which reads exactly
like revocation. Recorded in :data:`TESTING_MODE_REFRESH_TOKEN_WARNING` rather
than in somebody's memory.

**Nothing here ever returns, logs or raises a Google error string.** Google's
messages quote the request that failed, which for this connector means a meeting
space and the authorising person's address. Failures become a
:class:`GoogleMeetInstallFailure` — ours, bounded — plus a
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
from typing import Final, Protocol, final
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
from cairn_api.db.gmeet_models import GoogleMeetOAuthState

logger = structlog.get_logger(__name__)

AUTHORIZE_URL: Final = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL: Final = "https://oauth2.googleapis.com/token"  # noqa: S105 — a URL, not a token

#: The OAuth scopes CAIRN requests for Google Meet, and the complete list.
#:
#: One entry. ``meetings.space.readonly`` reads a meeting space's configuration,
#: which is what authorises a Workspace Events subscription on that space. It
#: does not read a transcript, a recording, a participant list or an attendance
#: report, and CAIRN asks for nothing that does.
#:
#: Ordered rather than a set, because this is also the string sent to Google and
#: a set's iteration order would make the authorise URL differ between processes.
REQUIRED_SCOPES: Final[tuple[str, ...]] = (
    "https://www.googleapis.com/auth/meetings.space.readonly",
)

#: The allowlist as a set, for the equality check. Derived, so the two cannot
#: drift.
ALLOWED_SCOPES: Final[frozenset[str]] = frozenset(REQUIRED_SCOPES)

#: Scopes that must never be requested or accepted, pinned so the reasons survive
#: the next person editing a URL-building function.
#:
#: Three families, and each one changes what this connector is rather than how
#: well it works.
#:
#: **Drive.** A Meet transcript or recording *is* a Drive file, so every Drive
#: scope here is "fetch the artifact" wearing a different name. Retrieval is Step
#: 36B and has its own consent story; a Drive scope arriving in Step 36A would
#: mean a customer consented to artifact access during a step that promised only
#: to notice that an artifact exists. ``drive.file`` and ``drive.appdata`` are on
#: the list too, even though they are narrower, because a scope granted is a
#: capability held.
#:
#: **Meet write and settings.** ``meetings.space.created`` and
#: ``meetings.space.settings`` create and reconfigure meeting spaces. A tool that
#: can change a meeting's recording or transcription settings is a tool that can
#: cause the very artifact it is watching for, which is the opposite of a
#: consent-gated observer.
#:
#: **Breadth and identity.** ``calendar*`` reads what somebody is doing all week,
#: which is explicitly out of scope; ``admin.reports.audit.readonly`` is where
#: Meet *attendance* actually lives, and attendance is the analytic md/03 §5.4
#: forbids; ``userinfo.email`` and ``userinfo.profile`` would attach an address
#: to a connection that deliberately stores none.
FORBIDDEN_SCOPES: Final[frozenset[str]] = frozenset(
    f"https://www.googleapis.com/auth/{name}"
    for name in (
        # Drive — the transcript and the recording are Drive files.
        "drive",
        "drive.readonly",
        "drive.file",
        "drive.appdata",
        "drive.metadata",
        "drive.metadata.readonly",
        "drive.photos.readonly",
        "docs",
        "documents",
        "documents.readonly",
        # Meet, beyond reading one space.
        "meetings.space.created",
        "meetings.space.settings",
        # Calendar — out of scope for this step and for this product.
        "calendar",
        "calendar.readonly",
        "calendar.events",
        "calendar.events.readonly",
        # Attendance, by its real name.
        "admin.reports.audit.readonly",
        "admin.reports.usage.readonly",
        "admin.directory.user.readonly",
        # Identity CAIRN deliberately does not hold.
        "userinfo.email",
        "userinfo.profile",
        # Chat's scopes. Requesting one here would mean the two connectors had
        # been merged by accident, which is exactly the shared-client failure
        # `config.Settings` refuses.
        "chat.spaces.readonly",
        "chat.messages.readonly",
    )
)

#: Whole families that must never appear, matched by prefix.
#:
#: Google keeps adding members to all four, and an enumeration would silently
#: stop covering the new ones. ``cloud-platform`` is included because it is a
#: superset of essentially everything and is the scope a copied service-account
#: example reaches for.
FORBIDDEN_SCOPE_PREFIXES: Final[tuple[str, ...]] = (
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/admin.",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/chat.",
)

#: **A release gate, not a note.**
#:
#: ``meetings.space.readonly`` is classified by Google as a **sensitive** scope,
#: not a restricted one — so unlike Chat's ``chat.messages.readonly`` it needs
#: OAuth app verification but **not** an independent CASA security assessment.
#: That is weeks rather than months, and it is stated in code because the natural
#: assumption, having read the Chat connector, is that Meet carries the same
#: multi-month blocker and can therefore be deprioritised.
#:
#: The moment a Drive scope is added — which is what Step 36B's retrieval needs —
#: this becomes restricted and the CASA assessment applies. That sentence belongs
#: here rather than in the step that discovers it.
SENSITIVE_SCOPE_RELEASE_GATE: Final = (
    "RELEASE GATE: https://www.googleapis.com/auth/meetings.space.readonly is a "
    "SENSITIVE scope. Publishing this connector requires Google OAuth app "
    "verification (weeks), but not an independent CASA security assessment. "
    "Adding any Drive scope — which artifact retrieval needs — makes it "
    "RESTRICTED and adds the CASA assessment, so that decision is a launch "
    "decision rather than a code change."
)

#: The other fact that reads as a defect when it is actually configuration.
# The rule matches the name, not the value: "TOKEN" in a constant reads as a
# credential. This one is a sentence shown to an operator.
TESTING_MODE_REFRESH_TOKEN_WARNING: Final = (
    "While the Google consent screen is in Testing with an external user type, "  # noqa: S105
    "refresh tokens expire after 7 days, so every Google Meet connection breaks "
    "weekly until the app is published and verified. Google also allows at most "
    "100 refresh tokens per account per client ID; the oldest is invalidated "
    "silently."
)

#: How long an install may sit half-finished. One browser round trip through one
#: consent screen.
STATE_TTL: Final = timedelta(minutes=10)

#: Ceiling on a Google call. A request that hangs holds a worker while a customer
#: watches a spinner.
REQUEST_TIMEOUT_SECONDS: Final = 10.0

#: How long before an access token lapses we refresh it anyway. Without a margin,
#: a token fetched with two seconds of life left is used for a request that takes
#: three, and the failure is a 401 mid-call rather than a refresh nobody noticed.
ACCESS_TOKEN_REFRESH_MARGIN_SECONDS: Final = 60.0

#: Google's documented default. Only a fallback for a malformed response.
DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS: Final = 3600

#: PKCE verifier length in bytes before base64url encoding. 64 bytes encodes to
#: 86 characters, inside RFC 7636's 43-128 range with room to spare.
_PKCE_VERIFIER_BYTES: Final = 64


class GoogleMeetInstallFailure(StrEnum):
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
    #: missing ``prompt=consent`` against an account that consented before.
    REFRESH_TOKEN_MISSING = "refresh_token_missing"  # noqa: S105 — a failure code

    #: Less was granted than CAIRN needs.
    SCOPES_INSUFFICIENT = "scopes_insufficient"

    #: **More** was granted than CAIRN asked for. Also refused — and for Meet
    #: this is the shared-OAuth-client symptom, so it has its own sentence in
    #: `_FAILURE_DETAILS`.
    SCOPES_UNEXPECTED = "scopes_unexpected"

    #: A scope on the forbidden list was granted. Distinct from
    #: ``SCOPES_UNEXPECTED`` for operators only: an unexpected scope is usually a
    #: shared client id, while a *forbidden* one means somebody widened the
    #: authorise URL.
    SCOPES_FORBIDDEN = "scopes_forbidden"

    #: The stored refresh token no longer works — revoked, or lapsed because the
    #: consent screen is still in Testing. The response is "reconnect", not
    #: "retry".
    AUTHORISATION_EXPIRED = "authorisation_expired"

    #: Google refused a Meet call for this account after the install: the person
    #: lost access, or an admin narrowed the grant.
    ACCESS_FORBIDDEN = "access_forbidden"

    #: This workspace already has a Google Meet connection.
    ALREADY_CONNECTED = "already_connected"

    #: Google was unreachable, slow, or answered with something unparseable.
    PROVIDER_UNAVAILABLE = "provider_unavailable"

    #: Throttled. Time fixes this one and nothing else does.
    RATE_LIMITED = "rate_limited"

    #: Google Meet is not configured on this deployment. An operator problem, not
    #: the customer's, and it must not present as "Google said no".
    NOT_CONFIGURED = "not_configured"


#: What each failure means in the vocabulary the rest of the product reports on.
#:
#: Total over `GoogleMeetInstallFailure`, asserted by a test, so a value added
#: later cannot arrive at a column as ``None`` and read as "nothing wrong".
_FAILURE_CATEGORIES: Mapping[GoogleMeetInstallFailure, ConnectorErrorCategory] = {
    GoogleMeetInstallFailure.DECLINED: ConnectorErrorCategory.PERMISSION_REVOKED,
    GoogleMeetInstallFailure.ADMIN_POLICY_ENFORCED: ConnectorErrorCategory.PERMISSION_REVOKED,
    GoogleMeetInstallFailure.SCOPES_INSUFFICIENT: ConnectorErrorCategory.PERMISSION_REVOKED,
    GoogleMeetInstallFailure.ACCESS_FORBIDDEN: ConnectorErrorCategory.PERMISSION_REVOKED,
    GoogleMeetInstallFailure.STATE_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleMeetInstallFailure.EXCHANGE_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleMeetInstallFailure.REFRESH_TOKEN_MISSING: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleMeetInstallFailure.SCOPES_UNEXPECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleMeetInstallFailure.SCOPES_FORBIDDEN: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleMeetInstallFailure.ALREADY_CONNECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleMeetInstallFailure.NOT_CONFIGURED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    GoogleMeetInstallFailure.AUTHORISATION_EXPIRED: ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
    GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE: ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
    GoogleMeetInstallFailure.RATE_LIMITED: ConnectorErrorCategory.RATE_LIMITED,
}

#: Google's documented OAuth ``error`` values, mapped to ours. The lookup is
#: one-way and lossy on purpose: the key is consumed here and never stored.
_GOOGLE_ERROR_FAILURES: Mapping[str, GoogleMeetInstallFailure] = {
    "access_denied": GoogleMeetInstallFailure.DECLINED,
    "admin_policy_enforced": GoogleMeetInstallFailure.ADMIN_POLICY_ENFORCED,
    "disallowed_useragent": GoogleMeetInstallFailure.EXCHANGE_REJECTED,
    "org_internal": GoogleMeetInstallFailure.ADMIN_POLICY_ENFORCED,
    "redirect_uri_mismatch": GoogleMeetInstallFailure.EXCHANGE_REJECTED,
    "invalid_client": GoogleMeetInstallFailure.EXCHANGE_REJECTED,
    "invalid_request": GoogleMeetInstallFailure.EXCHANGE_REJECTED,
    "unauthorized_client": GoogleMeetInstallFailure.EXCHANGE_REJECTED,
    "unsupported_grant_type": GoogleMeetInstallFailure.EXCHANGE_REJECTED,
    "invalid_scope": GoogleMeetInstallFailure.SCOPES_INSUFFICIENT,
    # Expired, revoked, or already-redeemed code — and, on a refresh, a lapsed
    # refresh token. The two paths translate it differently, which is why this
    # table is not consulted directly by either.
    "invalid_grant": GoogleMeetInstallFailure.EXCHANGE_REJECTED,
    "rate_limit_exceeded": GoogleMeetInstallFailure.RATE_LIMITED,
    "internal_failure": GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE,
    "server_error": GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE,
    "temporarily_unavailable": GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE,
}

#: One sentence per failure, written here rather than at each raise site. This is
#: what makes them safe to put in a response: reviewed once, in one place, and
#: containing not one word Google chose.
_FAILURE_DETAILS: Mapping[GoogleMeetInstallFailure, str] = {
    GoogleMeetInstallFailure.DECLINED: (
        "The Google authorisation was declined. Nothing was connected."
    ),
    GoogleMeetInstallFailure.ADMIN_POLICY_ENFORCED: (
        "A Google Workspace administrator has blocked this access for your "
        "organisation. Nothing was connected; ask them to allow CAIRN."
    ),
    GoogleMeetInstallFailure.STATE_REJECTED: (
        "This connection link is no longer valid. Start again from your workspace settings."
    ),
    GoogleMeetInstallFailure.EXCHANGE_REJECTED: (
        "Google refused to complete the connection. Start again from your workspace settings."
    ),
    GoogleMeetInstallFailure.REFRESH_TOKEN_MISSING: (
        "Google did not issue the long-lived authorisation CAIRN needs, so "
        "nothing was connected. Remove CAIRN from your Google account's "
        "third-party access list and connect again."
    ),
    GoogleMeetInstallFailure.SCOPES_INSUFFICIENT: (
        "Google granted fewer permissions than CAIRN needs, so nothing was connected."
    ),
    GoogleMeetInstallFailure.SCOPES_UNEXPECTED: (
        "Google granted permissions CAIRN did not ask for, so nothing was "
        "connected. If Google Chat is also connected, check that the two use "
        "separate OAuth clients."
    ),
    GoogleMeetInstallFailure.SCOPES_FORBIDDEN: (
        "Google granted a permission CAIRN refuses to hold, so nothing was connected."
    ),
    GoogleMeetInstallFailure.AUTHORISATION_EXPIRED: (
        "CAIRN's authorisation for Google Meet is no longer accepted. Reconnect "
        "Google Meet from your workspace settings."
    ),
    GoogleMeetInstallFailure.ACCESS_FORBIDDEN: (
        "Google refused CAIRN access for this account. Reconnect Google Meet "
        "from your workspace settings."
    ),
    GoogleMeetInstallFailure.ALREADY_CONNECTED: (
        "A Google Meet account is already connected to another CAIRN workspace."
    ),
    GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE: (
        "Google could not be reached. Nothing was changed; try again shortly."
    ),
    GoogleMeetInstallFailure.RATE_LIMITED: (
        "Google is rate-limiting this account. Nothing was changed; try again shortly."
    ),
    GoogleMeetInstallFailure.NOT_CONFIGURED: "Google Meet is not configured on this deployment.",
}


def category_for(failure: GoogleMeetInstallFailure) -> ConnectorErrorCategory:
    """The bounded category a failure reports as.

    A function rather than a dict other modules reach into, so the mapping has
    one reader and no caller can grow a second opinion about what "declined"
    means.
    """
    return _FAILURE_CATEGORIES[failure]


def detail_for(failure: GoogleMeetInstallFailure) -> str:
    """The sentence a customer sees for a failure. Ours, always."""
    return _FAILURE_DETAILS[failure]


def failure_for_google_error(error: str) -> GoogleMeetInstallFailure:
    """Translate a redirect's ``error`` parameter, and discard it.

    Unknown values become ``DECLINED`` rather than ``EXCHANGE_REJECTED``: on the
    redirect specifically, the overwhelmingly likely meaning of an unrecognised
    ``error`` is the person pressing Cancel.
    """
    return _GOOGLE_ERROR_FAILURES.get(error, GoogleMeetInstallFailure.DECLINED)


class GoogleMeetInstallError(Exception):
    """An install that will not complete, expressed in terms safe to show.

    Carries no Google text. ``detail`` is a sentence written in this file and
    reviewed once, which is what makes it safe in a response.
    """

    def __init__(self, failure: GoogleMeetInstallFailure, detail: str | None = None) -> None:
        self.failure = failure
        self.category = _FAILURE_CATEGORIES[failure]
        self.detail = detail or _FAILURE_DETAILS[failure]
        super().__init__(f"{failure}: {self.detail}")


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
    #: what we asked for" is a set operation and cannot be answered with ``in``
    #: on a substring.
    granted_scopes: frozenset[str]

    #: Seconds of life in the access token, as Google reported it.
    expires_in: int


@final
@dataclass(frozen=True, slots=True)
class GoogleAccessToken:
    """One refreshed access token.

    Separate from :class:`GoogleTokenGrant` because a refresh response has no
    ``refresh_token`` — and a shared type with an optional field is one where
    "did we get a refresh token" has two right answers depending on which call
    produced the object.
    """

    access_token: SecretValue
    granted_scopes: frozenset[str]
    expires_in: int


class GoogleMeetApi(Protocol):
    """Everything this package does against Google's OAuth endpoints.

    Structural typing rather than a base class: a test double imports nothing
    from here to satisfy it, so nothing about the double can drift into
    production code.

    Implementations raise :class:`GoogleMeetInstallError` and nothing else.
    """

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> GoogleTokenGrant:
        """Trade an authorisation code for an access and refresh token."""
        ...

    async def refresh_access_token(self, *, refresh_token: SecretValue) -> GoogleAccessToken:
        """Trade a refresh token for a fresh access token."""
        ...


@final
class HttpGoogleMeetApi:
    """The real one. The only code in CAIRN that calls Google's OAuth endpoints for Meet."""

    __slots__ = ("_client_id", "_client_secret")

    def __init__(self, *, client_id: str, client_secret: str) -> None:
        if not client_id or not client_secret:
            # Refused at construction rather than at the call, so "Google Meet is
            # not configured" surfaces as a clear operator error before a
            # customer is sent to an authorise URL Google will reject.
            raise GoogleMeetInstallError(GoogleMeetInstallFailure.NOT_CONFIGURED)
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
                # Sent again even though Google already has it from the authorise
                # step: Google compares the two, and a mismatch is
                # `redirect_uri_mismatch` rather than a token issued against a URL
                # nobody registered.
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            on_invalid_grant=GoogleMeetInstallFailure.EXCHANGE_REJECTED,
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
            # the standing authorisation is gone and the answer is "reconnect".
            on_invalid_grant=GoogleMeetInstallFailure.AUTHORISATION_EXPIRED,
        )
        return _access_token_from(payload)

    async def _post_token(
        self, form: Mapping[str, str], *, on_invalid_grant: GoogleMeetInstallFailure
    ) -> Mapping[str, object]:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                response = await client.post(TOKEN_URL, data=dict(form))
            except httpx.HTTPError as exc:
                raise _unavailable() from exc
        return _token_body(response, on_invalid_grant=on_invalid_grant)


def _unavailable() -> GoogleMeetInstallError:
    return GoogleMeetInstallError(GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE)


def _parsed(response: httpx.Response) -> Mapping[str, object]:
    """A JSON object, or "the provider is unavailable".

    Anything that is not a JSON object — an HTML proxy error page, an outage
    splash — is unavailability rather than a rejected request, because a
    rejection would send an operator looking at our configuration for a fault
    that is not there.
    """
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise _unavailable() from exc
    if not isinstance(payload, dict):
        raise _unavailable()
    return payload


def _token_body(
    response: httpx.Response, *, on_invalid_grant: GoogleMeetInstallFailure
) -> Mapping[str, object]:
    """Read an OAuth token response, translating any failure and discarding it.

    The status is consulted first, because a 5xx frequently carries no parseable
    body at all.
    """
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.RATE_LIMITED)
    if response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise _unavailable()

    payload = _parsed(response)

    if response.status_code >= httpx.codes.BAD_REQUEST:
        # The raw value is read here and goes no further — not into the
        # exception, not into a log field, not into a response.
        raw = payload.get("error")
        if raw == "invalid_grant":
            raise GoogleMeetInstallError(on_invalid_grant)
        failure = GoogleMeetInstallFailure.EXCHANGE_REJECTED
        if isinstance(raw, str):
            failure = _GOOGLE_ERROR_FAILURES.get(raw, GoogleMeetInstallFailure.EXCHANGE_REJECTED)
        raise GoogleMeetInstallError(failure)

    return payload


def _text(value: object) -> str | None:
    """A non-empty string, or nothing. Google omits or nulls absent fields."""
    return value if isinstance(value, str) and value else None


def _scopes_from(payload: Mapping[str, object]) -> frozenset[str]:
    """Parse the **space-separated** ``scope`` string.

    Space-separated, not comma-separated — that is OAuth 2.0's encoding and the
    opposite of Slack's. Splitting on the wrong character yields one long "scope"
    that matches nothing, and the install then fails as a scope shortfall with no
    hint that the parser is the problem.
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
    documented behaviour for a re-authorisation without ``prompt=consent``, and a
    customer told to remove CAIRN from their account's access list can act while
    one told "Google's response was incomplete" cannot.
    """
    access = _text(payload.get("access_token"))
    refresh = _text(payload.get("refresh_token"))

    if access is None:
        raise GoogleMeetInstallError(
            GoogleMeetInstallFailure.EXCHANGE_REJECTED,
            "Google's response was missing information CAIRN needs, so nothing was connected.",
        )
    if refresh is None:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.REFRESH_TOKEN_MISSING)

    return GoogleTokenGrant(
        access_token=SecretValue(access),
        refresh_token=SecretValue(refresh),
        granted_scopes=_scopes_from(payload),
        expires_in=_lifetime_from(payload),
    )


def _access_token_from(payload: Mapping[str, object]) -> GoogleAccessToken:
    access = _text(payload.get("access_token"))
    if access is None:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.AUTHORISATION_EXPIRED)
    return GoogleAccessToken(
        access_token=SecretValue(access),
        granted_scopes=_scopes_from(payload),
        expires_in=_lifetime_from(payload),
    )


# -- PKCE -------------------------------------------------------------------


def new_code_verifier() -> str:
    """A fresh PKCE verifier.

    From ``secrets``, like every other nonce in CAIRN. ``token_urlsafe`` produces
    exactly the unreserved character set RFC 7636 allows.
    """
    return secrets.token_urlsafe(_PKCE_VERIFIER_BYTES)


def code_challenge_for(verifier: str) -> str:
    """The S256 challenge for a verifier: base64url(SHA-256(verifier)), **unpadded**.

    Unpadded deliberately. RFC 7636 specifies base64url without trailing ``=``,
    and Google rejects the padded form — with an error that says the challenge is
    invalid rather than that it is padded.
    """
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# -- The authorise URL ------------------------------------------------------


def build_authorize_url(settings: Settings, *, state: str, code_verifier: str) -> str:
    """Where to send the customer's browser.

    Built from settings, never from the request: a redirect URI assembled from an
    attacker-supplied ``Host`` header sends the authorisation code — and
    therefore the account's refresh token — somewhere the attacker controls.

    Reads ``google_meet_client_id`` and ``google_meet_redirect_uri``, never
    Chat's. Sharing either is the failure the module docstring opens with.

    ``access_type=offline`` **and** ``prompt=consent`` are both present and both
    required: dropping the second means a person who has consented before gets no
    refresh token, the exchange succeeds, and the connection dies an hour later.

    **``include_granted_scopes`` is deliberately absent**, which is the one line
    that differs from the Chat authorise URL. Chat sends it so its token response
    reports everything the client holds; here it would invite the union of every
    grant on this account into a response that is checked for equality, which is
    the precise mechanism that breaks two connectors sharing a client. Asking for
    incremental authorisation on a connector with exactly one scope buys nothing.
    """
    if not settings.google_meet_client_id:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.NOT_CONFIGURED)

    query = urlencode(
        {
            "client_id": settings.google_meet_client_id,
            "redirect_uri": settings.google_meet_redirect_uri,
            "response_type": "code",
            # Space-separated, per OAuth 2.0. Google accepts nothing else.
            "scope": " ".join(REQUIRED_SCOPES),
            "state": state,
            # Without this there is no refresh token at all.
            "access_type": "offline",
            # Without this there is no refresh token on a *re*-authorisation,
            # which is the case nobody tests.
            "prompt": "consent",
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

    The nonce is 256 bits from ``secrets`` and only its SHA-256 is stored. A
    predictable value here is a CSRF hole with extra steps: an attacker who can
    guess a state can hand a victim a callback URL that binds *the attacker's*
    Google account to the victim's CAIRN workspace.

    The verifier is issued and stored in the same row, because it belongs to the
    same in-flight install and keeping it anywhere else — a cookie, a cache —
    would let the two halves get out of step.
    """
    moment = now or datetime.now(UTC)

    # Clear this workspace's finished states first. Cheap, uses the expiry index,
    # and keeps the table from growing by one permanent row per abandoned
    # install. Scoped to the tenant so it cannot become a cross-tenant delete.
    await db.execute(
        delete(GoogleMeetOAuthState).where(
            GoogleMeetOAuthState.tenant_id == tenant_id,
            GoogleMeetOAuthState.expires_at <= moment,
        )
    )

    nonce = generate_token()
    verifier = new_code_verifier()
    expires_at = moment + STATE_TTL
    db.add(
        GoogleMeetOAuthState(
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
) -> GoogleMeetOAuthState:
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
        GoogleMeetInstallError: Unknown, expired, already used, or someone
            else's. One failure code for all four, so the response does not tell
            an attacker which half of the check to work on.
    """
    moment = now or datetime.now(UTC)

    claimed: GoogleMeetOAuthState | None = await db.scalar(
        update(GoogleMeetOAuthState)
        .where(
            GoogleMeetOAuthState.state_hash == hash_token(state),
            GoogleMeetOAuthState.consumed_at.is_(None),
            GoogleMeetOAuthState.expires_at > moment,
            GoogleMeetOAuthState.initiated_by_user_id == user_id,
        )
        .values(consumed_at=moment)
        .returning(GoogleMeetOAuthState)
    )
    if claimed is None:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.STATE_REJECTED)
    return claimed


# -- What was granted -------------------------------------------------------


def is_forbidden_scope(scope: str) -> bool:
    """Whether this scope is one CAIRN refuses to hold.

    Names first, then prefixes. A function rather than an inline test so the
    authorise URL, the grant check and the test that walks
    :data:`FORBIDDEN_SCOPES` all ask the same question.
    """
    return scope in FORBIDDEN_SCOPES or scope.startswith(FORBIDDEN_SCOPE_PREFIXES)


def verify_granted_scopes(granted: frozenset[str]) -> None:
    """Refuse anything that is not exactly the one-scope allowlist.

    **Equality, not containment.** Every scope on the forbidden list is a
    capability over a company's meetings that CAIRN has decided not to hold, and
    a Drive scope in particular would turn "notice that a transcript exists" into
    "read it". A token carrying one is not a better install; it is a token this
    product does not want to be holding, and the honest response is to refuse it
    rather than store it and use one of its powers.

    A set operation, not a substring test: ``"meetings.space.readonly" in
    scope_string`` is also true of a longer scope, and a check satisfiable by a
    scope Google did not grant is not a check.

    The forbidden check runs **first**, so a Drive grant reports
    ``SCOPES_FORBIDDEN`` rather than the blander ``SCOPES_UNEXPECTED``. The two
    read the same to a customer and differently to an operator: unexpected is
    usually a shared OAuth client, forbidden means somebody widened the authorise
    URL.

    Raises:
        GoogleMeetInstallError: ``SCOPES_FORBIDDEN``, ``SCOPES_INSUFFICIENT`` or
            ``SCOPES_UNEXPECTED``. No message names a scope — which permissions a
            product asks for is not something to disclose in a failure a stranger
            can trigger.
    """
    if any(is_forbidden_scope(scope) for scope in granted):
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.SCOPES_FORBIDDEN)
    if ALLOWED_SCOPES - granted:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.SCOPES_INSUFFICIENT)
    if granted - ALLOWED_SCOPES:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.SCOPES_UNEXPECTED)


def require_refresh_token(payload: Mapping[str, object]) -> None:
    """Refuse a token response with no ``refresh_token``.

    Exposed separately from :func:`_grant_from` so the rule can be asserted
    without constructing a whole HTTP response, and so the reasoning has a name.
    A warning here instead of an error produces a connection that works for
    exactly one access-token lifetime and then stops.
    """
    if _text(payload.get("refresh_token")) is None:
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.REFRESH_TOKEN_MISSING)


# -- The connection ---------------------------------------------------------


def installation_id_for(settings: Settings, tenant_id: uuid.UUID) -> str:
    """The value ``source_connections.installation_id`` carries for this provider.

    Composes the **Meet** client id and the CAIRN tenant, which enforces exactly
    what it can honestly enforce: one Google Meet connection per CAIRN workspace.

    The single scope CAIRN requests carries no account identity at all — no
    customer id, no domain, no address — and CAIRN deliberately does not request
    an identity scope to obtain one, so there is nothing to compose that would
    identify the Google organisation. A value that pretended to would be a
    constraint that looks like it prevents something and does not.

    Reading ``google_chat_client_id`` here instead would make one workspace's two
    Google connections produce the same installation identity, which is the
    second half of the shared-client failure `config.Settings` refuses.
    """
    return f"{settings.google_meet_client_id}:{tenant_id}"


async def find_connection(db: AsyncSession, *, tenant_id: uuid.UUID) -> SourceConnection | None:
    """This workspace's Google Meet connection, connected or not."""
    connection: SourceConnection | None = await db.scalar(
        select(SourceConnection).where(
            SourceConnection.tenant_id == tenant_id,
            SourceConnection.provider == ConnectorProvider.GOOGLE_MEET,
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
    """Create or revive the Google Meet connection, and store the refresh token.

    Scope verification happens here, first, rather than at the call site. A caller
    that forgets it produces a connection that looks healthy and holds a
    capability nobody reviewed.

    **Only the refresh token is stored.** The access token is short-lived and
    reconstructible in one call, so persisting it would put a second live
    credential in the database to save a round trip.

    **Connecting subscribes to nothing.** This is the sharpest difference from
    every other connector in CAIRN: a connected Google Meet account permits
    exactly zero collection. A subscription exists only for a Step 35 capture
    request whose every participant has agreed, and it is created by
    `subscriptions.ensure_subscription`, which cannot be called without a
    `CollectionPermit`.

    Raises:
        GoogleMeetInstallError: Scopes were not exactly the allowlist, or this
            workspace's connection identity is already claimed.
    """
    verify_granted_scopes(grant.granted_scopes)
    moment = now or datetime.now(UTC)
    installation_id = installation_id_for(settings, tenant_id)

    existing = await db.scalar(
        select(SourceConnection).where(
            SourceConnection.provider == ConnectorProvider.GOOGLE_MEET,
            SourceConnection.installation_id == installation_id,
        )
    )
    if existing is not None and existing.tenant_id != tenant_id:
        # Unreachable while `installation_id_for` includes the tenant, and kept
        # anyway: the unique constraint would otherwise surface as an
        # IntegrityError several frames later.
        raise GoogleMeetInstallError(GoogleMeetInstallFailure.ALREADY_CONNECTED)

    connection = existing
    if connection is None:
        connection = SourceConnection(
            tenant_id=tenant_id,
            provider=ConnectorProvider.GOOGLE_MEET,
            external_account_id=installation_id,
            installation_id=installation_id,
        )
        db.add(connection)

    connection.external_account_id = installation_id
    # Deliberately null, forever. The only human-readable label Google would give
    # is the authorising person's email address or their domain, and this
    # connector stores neither.
    connection.external_account_label = None
    # Sorted, so two identical installs produce identical rows.
    connection.scopes = sorted(grant.granted_scopes)
    connection.state = ConnectionState.CONNECTED
    connection.connected_at = moment
    connection.disconnected_at = None
    connection.revoked_at = None
    # Not HEALTHY. Nothing has arrived and nothing *can* arrive until a meeting is
    # consented to, so a green tick here would be a claim about a feed that does
    # not exist yet.
    connection.health = ConnectionHealth.UNKNOWN
    connection.last_error_category = None
    connection.last_error_at = None
    connection.authorised_by_user_id = user_id
    connection.authorised_at = moment

    # The one place a Google Meet refresh token is written, and it goes through
    # the encrypting path.
    store_secret(connection, grant.refresh_token)
    # A revival must not inherit the previous authorisation's access token.
    forget_access_token(connection.id)
    await db.flush()

    await logger.ainfo(
        "gmeet.connected",
        tenant_id=str(tenant_id),
        authorised_by=str(user_id),
        # Scope *names* are ours, not the customer's, so they are safe and they
        # are the field that makes "why is nothing arriving" answerable.
        granted_scopes=sorted(grant.granted_scopes),
    )
    return connection


async def disconnect(connection: SourceConnection, *, now: datetime | None = None) -> None:
    """Stop collecting, and drop the credential.

    Both halves, always. Marking a connection disconnected while keeping its
    refresh token leaves CAIRN holding a standing grant after the customer asked
    it to stop, which is not a smaller version of the promise.

    ``DISCONNECTED`` rather than ``REVOKED``: this is our side stopping, and
    reconnecting is a click.
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


#: Per-connection, in-process, never persisted — and **Meet's own**, not a shared
#: cache with `gchat/oauth.py`.
#:
#: Keyed on the connection id, which is per-tenant and per-provider, so there is
#: no key another connector or another workspace could collide with. A shared
#: dictionary would let a Chat access token be handed to a Meet call, which
#: Google would refuse with a scope error that names neither connector.
_TOKEN_CACHE: dict[uuid.UUID, _CachedToken] = {}


def forget_access_token(connection_id: uuid.UUID) -> None:
    """Drop one connection's cached access token.

    Called on disconnect and on revival. A workspace that has asked CAIRN to stop
    must not leave a usable token in this process's memory for the next hour.
    """
    _TOKEN_CACHE.pop(connection_id, None)


def clear_access_token_cache() -> None:
    """Drop every cached Meet token. For tests, which must not inherit each other's."""
    _TOKEN_CACHE.clear()


def mark_refresh_failure(
    connection: SourceConnection,
    error: GoogleMeetInstallError,
    *,
    now: datetime | None = None,
) -> None:
    """Record on the connection that a refresh failed, in bounded terms.

    ``AUTHORISATION_EXPIRED`` means the standing grant is gone — revoked, or
    lapsed after seven days because the consent screen is still in Testing.
    Nothing retries its way out of that, so the connection is marked ``REVOKED``
    and the dead refresh token is destroyed rather than kept for a retry that
    cannot work.

    Everything else leaves the connection authorised and marks it ``FAILING``,
    because it is not the customer's problem and a revocation would ask them to
    reconnect for an outage that will pass.
    """
    moment = now or datetime.now(UTC)
    connection.last_error_category = error.category
    connection.last_error_at = moment
    connection.health = ConnectionHealth.FAILING
    forget_access_token(connection.id)

    if error.failure is GoogleMeetInstallFailure.AUTHORISATION_EXPIRED:
        connection.state = ConnectionState.REVOKED
        connection.revoked_at = moment
        clear_secret(connection)


async def access_token_for(
    api: GoogleMeetApi,
    connection: SourceConnection,
    *,
    now: float | None = None,
    at: datetime | None = None,
) -> SecretValue:
    """A usable access token for this connection, refreshing if needed.

    Cached in process for slightly less than its own lifetime. The margin is not
    decoration: a token handed out with two seconds left is a 401 in the middle of
    the next request rather than a refresh nobody noticed.

    On failure the connection is marked before the error propagates, so the reason
    is on the row even if the caller only rolls back. The caller commits — this
    function does not, because it is called from both a request handler and a
    worker, and a function that commits somebody else's transaction truncates
    their unit of work.

    Raises:
        GoogleMeetInstallError: The refresh failed, or the connection holds no
            credential at all.
    """
    moment = now if now is not None else time.monotonic()

    cached = _TOKEN_CACHE.get(connection.id)
    if cached is not None and cached.expires_at > moment:
        return cached.token

    refresh_token = read_secret(connection)
    if refresh_token is None:
        error = GoogleMeetInstallError(GoogleMeetInstallFailure.AUTHORISATION_EXPIRED)
        mark_refresh_failure(connection, error, now=at)
        raise error

    try:
        refreshed = await api.refresh_access_token(refresh_token=refresh_token)
    except GoogleMeetInstallError as error:
        mark_refresh_failure(connection, error, now=at)
        await logger.awarning(
            "gmeet.token_refresh_failed",
            tenant_id=str(connection.tenant_id),
            reason=error.failure.value,
            category=error.category.value,
        )
        raise

    # Checked on every refresh, not only at connect. An administrator can widen or
    # narrow a grant after the fact, and Google reports the current set here — so
    # a connection that quietly acquired a Drive scope is caught on the next
    # refresh rather than by somebody noticing it in a console.
    verify_granted_scopes(refreshed.granted_scopes)

    lifetime = max(refreshed.expires_in - ACCESS_TOKEN_REFRESH_MARGIN_SECONDS, 0.0)
    _TOKEN_CACHE[connection.id] = _CachedToken(
        expires_at=moment + lifetime, token=refreshed.access_token
    )
    return refreshed.access_token
