"""The restricted scope, the artifact boundary, and the encryption around both.

Step 36A's whole design was that it could not fetch anything: it held no Drive
scope, and it stored a digest rather than a name, so "we did not retrieve the
transcript" was a property of the data. Step 36B retrieves it, and this module is
where the capability that makes that possible is defined — deliberately in one
file, so the answer to "what lets CAIRN read a transcript" is one import away
rather than distributed across a router, a worker and a client.

**The scope is separate, explicit, and restricted.** ``drive.meet.readonly`` is
its own consent action with its own grant record (`db.gmeet_models.
GoogleMeetTranscriptGrant`), never added to the Meet connection's scopes. A
workspace that connected Google Meet has *not* granted transcript access, and
:func:`verify_granted_transcript_scopes` compares by set equality exactly as
`oauth.verify_granted_scopes` does — so a token carrying both grants is refused
rather than quietly accepted as "at least what we needed".

It is also the scope that changes this connector's release regime.
`oauth.SENSITIVE_SCOPE_RELEASE_GATE` said adding a Drive scope would move Meet
from SENSITIVE to RESTRICTED; :data:`RESTRICTED_SCOPE_RELEASE_GATE` is that
sentence coming true, and `ops/connectors.py` carries the operational half.

**Transcripts only, checked twice.** The declared artifact type is checked
against the resource-name shape — ``conferenceRecords/{c}/transcripts/{t}`` and
nothing else — and the content type is checked against
:data:`ALLOWED_CONTENT_TYPES`. Two checks rather than one because they fail
differently: a recording announced as a transcript fails the first, and a
transcript whose export silently returns audio fails the second. Neither check is
a substring test.

**Nothing here returns, logs or raises a Google string, a resource name, a
document id, a URL or a byte of transcript text.** Failures become an
:class:`ArtifactError` — ours, bounded — plus a ``ConnectorErrorCategory``.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol, final
from urllib.parse import urlencode

import httpx
import structlog

from cairn_api.config import Settings
from cairn_api.connectors.credentials import (
    CredentialCipher,
    SecretValue,
    get_cipher,
)
from cairn_api.db.connector_models import ConnectorErrorCategory
from cairn_api.db.gmeet_models import (
    CONFERENCE_REFERENCE_PATTERN,
    TRANSCRIPT_REFERENCE_PATTERN,
)
from cairn_api.gmeet.oauth import AUTHORIZE_URL, code_challenge_for

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# The restricted scope
# ---------------------------------------------------------------------------

#: The one scope transcript retrieval requests, and the complete list.
#:
#: ``drive.meet.readonly`` reads **only files Google Meet itself created** in the
#: authorising account's Drive. ``drive.readonly`` would work too and is the scope
#: a copied example reaches for; it also grants every other file in the account,
#: which is the difference between reading a transcript people consented to and
#: holding a key to their filing cabinet.
#:
#: A tuple rather than a set, because this string is sent to Google and a set's
#: iteration order would make the authorise URL differ between processes.
TRANSCRIPT_SCOPES: Final[tuple[str, ...]] = ("https://www.googleapis.com/auth/drive.meet.readonly",)

#: The allowlist as a set, for the equality check. Derived, so the two cannot
#: drift.
TRANSCRIPT_ALLOWED_SCOPES: Final[frozenset[str]] = frozenset(TRANSCRIPT_SCOPES)

#: Drive scopes that must never be requested or accepted for transcript access.
#:
#: Every one of them is broader than "the files Meet made". They are named
#: individually rather than matched by prefix because the prefix
#: ``.../auth/drive`` also matches the scope this module *does* want — which is
#: precisely the mistake `oauth.FORBIDDEN_SCOPE_PREFIXES` makes safe over there
#: and cannot make safe here.
FORBIDDEN_TRANSCRIPT_SCOPES: Final[frozenset[str]] = frozenset(
    f"https://www.googleapis.com/auth/{name}"
    for name in (
        # Drive, wider than Meet's own files.
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
        # Meet, beyond reading one space. `meetings.space.created` and
        # `.settings` can turn transcription on, and a tool that can cause the
        # artifact it is watching for is not a consent-gated observer.
        "meetings.space.created",
        "meetings.space.settings",
        # Calendar, attendance and identity — the same three families the
        # connection grant refuses, restated because this is a second grant and a
        # second chance to widen one.
        "calendar",
        "calendar.readonly",
        "calendar.events",
        "calendar.events.readonly",
        "admin.reports.audit.readonly",
        "admin.reports.usage.readonly",
        "admin.directory.user.readonly",
        "userinfo.email",
        "userinfo.profile",
        # Chat's scopes. One here would mean the two connectors had been merged
        # by accident, which is the shared-client failure `config.Settings`
        # refuses.
        "chat.spaces.readonly",
        "chat.messages.readonly",
    )
)

#: Whole families that must never appear, matched by prefix. ``drive`` is
#: deliberately **absent** — see :data:`FORBIDDEN_TRANSCRIPT_SCOPES`.
FORBIDDEN_TRANSCRIPT_SCOPE_PREFIXES: Final[tuple[str, ...]] = (
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/admin.",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/chat.",
)

#: **A release gate, not a note.**
#:
#: `oauth.SENSITIVE_SCOPE_RELEASE_GATE` records that Meet's connection scope is
#: SENSITIVE — Google OAuth verification, weeks, no third party — and that adding
#: a Drive scope would make it RESTRICTED. This is that sentence coming true.
#:
#: A RESTRICTED scope needs OAuth verification **plus** an independent CASA
#: security assessment ending in a Letter of Assessment, re-taken at least
#: annually, forever. Assessments run weeks to months and no amount of finished
#: code shortens one. **Transcript retrieval is not live and must not be described
#: as live** until that assessment is complete: what exists is the code path, and
#: a deployment that has not started the assessment cannot ship it.
RESTRICTED_SCOPE_RELEASE_GATE: Final = (
    "RELEASE GATE: https://www.googleapis.com/auth/drive.meet.readonly is a "
    "RESTRICTED scope. Publishing transcript retrieval requires Google OAuth app "
    "verification AND an independent third-party CASA security assessment ending "
    "in a Letter of Assessment, with re-verification at least every 12 months. "
    "This is a calendar constraint owned outside this repository: a deployment "
    "that has not started the assessment cannot ship transcript retrieval "
    "however finished the code is. Do not describe transcript retrieval as live "
    "until the Letter of Assessment exists. Until the app is published and "
    "verified the consent screen stays in Testing, where refresh tokens expire "
    "after 7 days and every customer connection breaks weekly."
)

#: The wording a workspace agrees to when it grants transcript access. Pinned on
#: the grant row, so a later change to the explanation does not silently
#: re-authorise anything under the new one.
TRANSCRIPT_CONSENT_POLICY_VERSION: Final = "2026-08-transcript-retrieval-1"


def is_forbidden_transcript_scope(scope: str) -> bool:
    """Whether this scope is one transcript access refuses to hold."""
    return scope in FORBIDDEN_TRANSCRIPT_SCOPES or scope.startswith(
        FORBIDDEN_TRANSCRIPT_SCOPE_PREFIXES
    )


def verify_granted_transcript_scopes(granted: frozenset[str]) -> None:
    """Refuse anything that is not exactly the one-scope transcript allowlist.

    **Equality, not containment**, for the same reason `oauth.
    verify_granted_scopes` uses equality: a token carrying more than was asked for
    is not a better grant, it is a capability nobody reviewed. In particular a
    response carrying *both* the Meet connection scope and this one means the two
    consent actions have been merged — which is the failure this whole module is
    shaped to prevent — and it is refused rather than accepted as sufficient.

    Raises:
        ArtifactError: ``SCOPE_FORBIDDEN``, ``SCOPE_INSUFFICIENT`` or
            ``SCOPE_UNEXPECTED``. No message names a scope.
    """
    if any(is_forbidden_transcript_scope(scope) for scope in granted):
        raise ArtifactError(ArtifactFailure.SCOPE_FORBIDDEN)
    if TRANSCRIPT_ALLOWED_SCOPES - granted:
        raise ArtifactError(ArtifactFailure.SCOPE_INSUFFICIENT)
    if granted - TRANSCRIPT_ALLOWED_SCOPES:
        raise ArtifactError(ArtifactFailure.SCOPE_UNEXPECTED)


#: What a workspace is agreeing to, returned before they reach Google's consent
#: screen. Written here rather than in the frontend because it is a statement
#: about what the backend does, and a claim about collection that lives only in a
#: React component is a claim nothing keeps true.
TRANSCRIPT_CONSENT_NOTICE: Final = (
    "This is a separate permission from connecting Google Meet, and it is the "
    "one that lets CAIRN read the transcript file Google Meet produced. It "
    "applies only to meetings where every invited person has already agreed, and "
    "CAIRN re-checks that agreement immediately before every retrieval — if "
    "anybody withdraws, nothing is collected. CAIRN never retrieves recordings, "
    "audio, video, smart notes or attendance, never joins a meeting, and never "
    "reads any other file in the Google account. Retrieved transcripts are "
    "stored encrypted, are not shown anywhere in the product at this stage, and "
    "are deleted at the end of your workspace's retention period."
)


def build_transcript_authorize_url(settings: Settings, *, state: str, code_verifier: str) -> str:
    """Where to send the customer for the **transcript** consent action.

    A separate URL on a separate OAuth client, requesting exactly one scope. It
    is not a variation of `oauth.build_authorize_url` with a wider scope list,
    and that is the point: two consent actions that share a URL builder are one
    consent action with an argument, and the argument is what somebody eventually
    defaults.

    ``access_type=offline`` **and** ``prompt=consent`` for the reason the
    connection flow needs both: without the second, a person who has consented
    before gets no refresh token, the exchange succeeds, and the grant dies an
    hour later. ``include_granted_scopes`` is deliberately absent — it would
    invite the union of every grant on the account into a response that is
    checked for equality.

    Raises:
        ArtifactError: ``NOT_CONFIGURED``, when this deployment has no transcript
            OAuth client. An operator's problem, and it must not read as "Google
            said no".
    """
    if not settings.google_meet_transcript_client_id:
        raise ArtifactError(ArtifactFailure.NOT_CONFIGURED)

    query = urlencode(
        {
            "client_id": settings.google_meet_transcript_client_id,
            "redirect_uri": settings.google_meet_transcript_redirect_uri,
            "response_type": "code",
            # Space-separated, per OAuth 2.0. Google accepts nothing else.
            "scope": " ".join(TRANSCRIPT_SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": code_challenge_for(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


# ---------------------------------------------------------------------------
# What may be downloaded, and how much of it
# ---------------------------------------------------------------------------

#: Content types a transcript may arrive as, and the complete list.
#:
#: Meet writes its transcript to a Google Doc, which is exported as ``text/plain``;
#: ``text/vtt`` is the caption form. Both are text. There is no member here for
#: audio, video, a PDF, a zip, or ``application/octet-stream`` — an artifact that
#: arrives as any of those is not the thing that was announced, and accepting it
#: "because the name looked right" is how a recording ends up in a transcript
#: store.
ALLOWED_CONTENT_TYPES: Final[frozenset[str]] = frozenset({"text/plain", "text/vtt"})

#: The declared Drive type a Meet transcript document carries before export.
#: Allowed as *metadata* and never as content: the export below is what turns it
#: into one of :data:`ALLOWED_CONTENT_TYPES`.
TRANSCRIPT_DOCUMENT_TYPE: Final = "application/vnd.google-apps.document"

#: What CAIRN exports the document as. One value, sent explicitly, because
#: Drive's default export for a document is not text.
EXPORT_CONTENT_TYPE: Final = "text/plain"

#: Content types that must never be accepted, named so the refusal is by
#: intention rather than by falling off the end of an allowlist. Matched by
#: prefix: ``audio/``, ``video/`` and Google's own media types cover every form a
#: recording arrives in.
FORBIDDEN_CONTENT_TYPE_PREFIXES: Final[tuple[str, ...]] = (
    "audio/",
    "video/",
    "application/vnd.google-apps.video",
    "application/vnd.google-apps.audio",
)

#: The ceiling on a transcript download, in bytes.
#:
#: A transcript is text: a three-hour meeting is a few hundred kilobytes. Five
#: mebibytes is generous by an order of magnitude and small enough that a
#: mislabelled recording hits the cap rather than the disk. Enforced **while
#: streaming**, not from ``Content-Length``, because a header is a claim.
MAX_TRANSCRIPT_BYTES: Final = 5 * 1024 * 1024

#: Ceiling on one Drive call. A download that hangs holds a worker.
DOWNLOAD_TIMEOUT_SECONDS: Final = 30.0

#: Ceiling on a metadata lookup, which is a small JSON document.
METADATA_TIMEOUT_SECONDS: Final = 10.0

#: How many bytes are read at a time. Small enough that the cap is enforced
#: within a chunk of it rather than after a whole response is in memory.
DOWNLOAD_CHUNK_BYTES: Final = 64 * 1024

#: The Meet API, for artifact metadata. ``v2`` is what the shapes below are
#: written against.
MEET_API_BASE: Final = "https://meet.googleapis.com/v2"

#: Drive's export endpoint. The only Drive call this connector makes.
DRIVE_API_BASE: Final = "https://www.googleapis.com/drive/v3"

_TRANSCRIPT_REFERENCE = re.compile(TRANSCRIPT_REFERENCE_PATTERN)
_CONFERENCE_REFERENCE = re.compile(CONFERENCE_REFERENCE_PATTERN)

#: A Drive file id, as Drive writes them. Validated before it reaches a URL so a
#: value from a provider response cannot become a path segment of CAIRN's
#: choosing.
_DOCUMENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


# ---------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------


class ArtifactFailure(StrEnum):
    """Why an artifact operation did not do what was asked, as a bounded code.

    Coarser than Google's error space on purpose, and derived from the **status
    code alone**. A Drive error body names the file that failed, which here is
    the transcript of a specific meeting.
    """

    #: The artifact does not exist any more. Terminal: Google deleted it, or the
    #: authorising account lost access to it.
    GONE = "gone"

    #: Google refused the call for this authorisation.
    PERMISSION_DENIED = "permission_denied"

    #: The standing authorisation is gone. Reconnect; nothing retries out of it.
    AUTHORISATION_EXPIRED = "authorisation_expired"

    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"

    #: Google rejected the request itself.
    REQUEST_REJECTED = "request_rejected"

    #: What Google described is not a transcript — a recording, audio, video,
    #: smart notes — or the shape of the reference is not a transcript's.
    NOT_A_TRANSCRIPT = "not_a_transcript"

    #: A transcript, and larger than :data:`MAX_TRANSCRIPT_BYTES`.
    TOO_LARGE = "too_large"

    #: The content type is not on :data:`ALLOWED_CONTENT_TYPES`.
    CONTENT_TYPE_NOT_ALLOWED = "content_type_not_allowed"

    #: What arrived does not match what was promised.
    CHECKSUM_MISMATCH = "checksum_mismatch"

    #: The artifact is there and is not the one that was announced.
    ARTIFACT_CHANGED = "artifact_changed"

    #: Less was granted than transcript retrieval needs.
    SCOPE_INSUFFICIENT = "scope_insufficient"

    #: **More** was granted than was asked for — including the case where the
    #: connection scope and this one arrived in one token.
    SCOPE_UNEXPECTED = "scope_unexpected"

    #: A scope on the forbidden list was granted.
    SCOPE_FORBIDDEN = "scope_forbidden"

    #: Transcript access has not been granted, or has been revoked.
    SCOPE_NOT_GRANTED = "scope_not_granted"

    #: Google Meet is not configured on this deployment.
    NOT_CONFIGURED = "not_configured"


#: What each failure reports as in the vocabulary the rest of the product reads.
#: Total over `ArtifactFailure`, asserted by a test, so a value added later cannot
#: arrive at a column as ``None`` and read as "nothing wrong".
_FAILURE_CATEGORIES: Mapping[ArtifactFailure, ConnectorErrorCategory] = {
    ArtifactFailure.GONE: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.PERMISSION_DENIED: ConnectorErrorCategory.PERMISSION_REVOKED,
    ArtifactFailure.AUTHORISATION_EXPIRED: ConnectorErrorCategory.AUTHENTICATION_EXPIRED,
    ArtifactFailure.RATE_LIMITED: ConnectorErrorCategory.RATE_LIMITED,
    ArtifactFailure.PROVIDER_UNAVAILABLE: ConnectorErrorCategory.PROVIDER_UNAVAILABLE,
    ArtifactFailure.REQUEST_REJECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.NOT_A_TRANSCRIPT: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.TOO_LARGE: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.CONTENT_TYPE_NOT_ALLOWED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.CHECKSUM_MISMATCH: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.ARTIFACT_CHANGED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.SCOPE_INSUFFICIENT: ConnectorErrorCategory.PERMISSION_REVOKED,
    ArtifactFailure.SCOPE_UNEXPECTED: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.SCOPE_FORBIDDEN: ConnectorErrorCategory.CONFIGURATION_INVALID,
    ArtifactFailure.SCOPE_NOT_GRANTED: ConnectorErrorCategory.PERMISSION_REVOKED,
    ArtifactFailure.NOT_CONFIGURED: ConnectorErrorCategory.CONFIGURATION_INVALID,
}

#: Failures a later pass may retry unattended. The others are fixed by a person
#: reconnecting, granting a scope, or by the artifact simply not existing, and
#: retrying them forever spends a customer's quota to be refused again.
RETRYABLE_FAILURES: Final[frozenset[ArtifactFailure]] = frozenset(
    {
        ArtifactFailure.PROVIDER_UNAVAILABLE,
        ArtifactFailure.RATE_LIMITED,
    }
)


def category_for(failure: ArtifactFailure) -> ConnectorErrorCategory:
    """The bounded category a failure reports as."""
    return _FAILURE_CATEGORIES[failure]


@final
class ArtifactError(Exception):
    """An artifact operation that did not do what was asked.

    Carries a bounded failure and its category and **nothing from Google**. The
    message is assembled from our own enum value, so even a traceback that reaches
    a log contains no file id, no meeting and no transcript text.
    """

    def __init__(self, failure: ArtifactFailure) -> None:
        self.failure = failure
        self.category = _FAILURE_CATEGORIES[failure]
        self.retryable = failure in RETRYABLE_FAILURES
        super().__init__(f"google meet artifact: {failure.value}")


# ---------------------------------------------------------------------------
# References, digests and the transcript test
# ---------------------------------------------------------------------------


def is_transcript_reference(reference: str) -> bool:
    """Whether this resource name is a Meet **transcript**.

    An allowlist on the shape. A recording is
    ``conferenceRecords/{c}/recordings/{r}`` and smart notes arrive under their
    own path, so this refuses both — and refuses whatever Google adds next —
    without anybody having to enumerate it.
    """
    return _TRANSCRIPT_REFERENCE.fullmatch(reference.strip()) is not None


def conference_reference_of(reference: str) -> str:
    """The ``conferenceRecords/{c}`` prefix of a transcript reference.

    Raises:
        ArtifactError: ``NOT_A_TRANSCRIPT``, when the value is not one. The value
            is never included in the error, the message or a log field.
    """
    trimmed = reference.strip()
    if not is_transcript_reference(trimmed):
        raise ArtifactError(ArtifactFailure.NOT_A_TRANSCRIPT)
    prefix = trimmed.rsplit("/transcripts/", 1)[0]
    if _CONFERENCE_REFERENCE.fullmatch(prefix) is None:  # pragma: no cover - unreachable
        raise ArtifactError(ArtifactFailure.NOT_A_TRANSCRIPT)
    return prefix


def digest_of(value: str) -> str:
    """SHA-256, hex. The form every provider identifier is compared in."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_allowed_content_type(content_type: str) -> bool:
    """Whether these bytes may be stored as a transcript.

    The type is normalised first — Google sends ``text/plain; charset=UTF-8`` —
    and then compared for **equality against the allowlist**, never with ``in``.
    ``"text/plain" in "audio/x-text/plain-ish"`` is true, and a check satisfiable
    by a type nobody allowed is not a check.
    """
    normalised = content_type.split(";", 1)[0].strip().casefold()
    if normalised.startswith(FORBIDDEN_CONTENT_TYPE_PREFIXES):
        return False
    return normalised in ALLOWED_CONTENT_TYPES


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------
#
# Both helpers go through `connectors/credentials.py` rather than reaching for
# Fernet directly. That module owns where the key comes from, refuses a deployed
# environment with no key, and refuses one holding the published development key
# — and a second key path here would be a second place for all three decisions to
# be got wrong. `SecretValue` is used for its behaviour rather than its name: it
# does not render itself in a `repr`, a log line or a Pydantic response, which is
# exactly the property a transcript needs.


def seal_reference(reference: str, *, cipher: CredentialCipher | None = None) -> str:
    """Encrypt an artifact resource name for storage."""
    return (cipher or get_cipher()).encrypt(SecretValue(reference))


def open_reference(ciphertext: str, *, cipher: CredentialCipher | None = None) -> str:
    """Decrypt a stored artifact resource name.

    Named so a reviewer scanning a diff finds every place a provider reference
    comes back into the clear. There are two: the download path and the retention
    sweep's audit of its own work.
    """
    return (cipher or get_cipher()).decrypt(ciphertext).reveal()


def seal_refresh_token(token: SecretValue, *, cipher: CredentialCipher | None = None) -> str:
    """Encrypt the transcript grant's refresh token.

    The same reviewed path `connectors.credentials.store_secret` uses, applied to
    the second row in this connector that holds a credential. It is a separate
    function rather than a call to `store_secret` because that one is typed to a
    `SourceConnection`, and widening it so a second model could be passed would
    make "which rows hold credentials" a question about a type parameter instead
    of a question a reader can answer by reading two function names.
    """
    return (cipher or get_cipher()).encrypt(token)


def open_refresh_token(ciphertext: str, *, cipher: CredentialCipher | None = None) -> SecretValue:
    """Decrypt the transcript grant's refresh token. Greppable, like `read_secret`."""
    return (cipher or get_cipher()).decrypt(ciphertext)


def seal_content(content: bytes, *, cipher: CredentialCipher | None = None) -> str:
    """Encrypt transcript bytes for the raw store.

    Base64 first, because the cipher's interface is text and a transcript is
    bytes — and because round-tripping through an encoding that cannot fail is
    safer than assuming a decode. The checksum callers store is computed over the
    **plaintext bytes**, so it describes the transcript rather than this envelope.
    """
    return (cipher or get_cipher()).encrypt(SecretValue(base64.b64encode(content).decode("ascii")))


def open_content(ciphertext: str, *, cipher: CredentialCipher | None = None) -> bytes:
    """Decrypt stored transcript bytes.

    The only way transcript content comes back into memory, and deliberately the
    only one: there is no property on the model that does it, so "where is a
    transcript decrypted" is answerable with grep.
    """
    return base64.b64decode((cipher or get_cipher()).decrypt(ciphertext).reveal())


# ---------------------------------------------------------------------------
# The network boundary
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class RemoteTranscript:
    """One transcript artifact as Google described it just now.

    A transport object, and note what is absent: no ``exportUri``, no share link,
    no owner, no participant list, no meeting title, no speaker. The document id
    is here because a download needs one; it never reaches a column, a log field
    or a response.
    """

    #: ``conferenceRecords/{c}/transcripts/{t}``, echoed back by Google.
    reference: str

    #: The Drive document Meet wrote the transcript into.
    document_id: str

    #: The Drive type of that document, before export.
    declared_type: str

    #: When the platform produced it, if Google said. ``None`` rather than a
    #: guess.
    generated_at: datetime | None = None


class TranscriptArtifactApi(Protocol):
    """Every provider call transcript retrieval makes.

    Two methods, and a test supplies an object rather than patching a module
    global — which is what makes "no unit test calls Google" a property of the
    structure rather than of everyone remembering.

    Implementations raise `ArtifactError` and nothing else.
    """

    async def describe(self, *, access_token: SecretValue, reference: str) -> RemoteTranscript:
        """Look up one transcript's metadata. Never a recording, never a list."""
        ...

    def download(
        self, *, access_token: SecretValue, artifact: RemoteTranscript
    ) -> AsyncIterator[bytes]:
        """Stream the exported transcript. The caller enforces the size cap."""
        ...


@final
class HttpTranscriptArtifactApi:
    """The real one. The only code in CAIRN that reads a Meet artifact.

    Two hosts and two calls: Meet's own API for the metadata, Drive's export for
    the bytes. There is no list call, no search, and no call that takes anything
    other than the one reference the announcement carried — a client that could
    enumerate a conference's artifacts is one a bug could point at a recording.
    """

    __slots__ = ()

    async def describe(self, *, access_token: SecretValue, reference: str) -> RemoteTranscript:
        if not is_transcript_reference(reference):
            # Refused before it becomes a URL. A reference of another shape here
            # means the caller has handed us a recording, and the request must not
            # be made at all rather than made and discarded.
            raise ArtifactError(ArtifactFailure.NOT_A_TRANSCRIPT)

        async with httpx.AsyncClient(timeout=METADATA_TIMEOUT_SECONDS) as client:
            try:
                response = await client.get(
                    f"{MEET_API_BASE}/{reference}",
                    # `reveal()` at the one point the credential has to leave the
                    # wrapper, which is what makes it greppable.
                    headers={"Authorization": f"Bearer {access_token.reveal()}"},
                )
            except httpx.HTTPError as exc:
                raise ArtifactError(ArtifactFailure.PROVIDER_UNAVAILABLE) from exc

        return _remote_from(_body(response), requested=reference)

    async def download(
        self, *, access_token: SecretValue, artifact: RemoteTranscript
    ) -> AsyncIterator[bytes]:
        """Export the document as text, streamed.

        Streamed rather than read whole, so the size cap is enforced against bytes
        that have arrived rather than against a ``Content-Length`` header — which
        is a claim by the sender and is absent altogether on a chunked response.
        """
        if _DOCUMENT_ID.fullmatch(artifact.document_id) is None:
            # A provider value about to become a path segment. Validated, so a
            # response carrying `../` cannot point this request somewhere else.
            raise ArtifactError(ArtifactFailure.REQUEST_REJECTED)

        async with (
            httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS) as client,
            client.stream(
                "GET",
                f"{DRIVE_API_BASE}/files/{artifact.document_id}/export",
                params={"mimeType": EXPORT_CONTENT_TYPE},
                headers={"Authorization": f"Bearer {access_token.reveal()}"},
            ) as response,
        ):
            _raise_for_status(response.status_code)
            declared = response.headers.get("content-type", "")
            if not is_allowed_content_type(declared):
                raise ArtifactError(ArtifactFailure.CONTENT_TYPE_NOT_ALLOWED)
            try:
                async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_BYTES):
                    yield chunk
            except httpx.HTTPError as exc:
                raise ArtifactError(ArtifactFailure.PROVIDER_UNAVAILABLE) from exc


def _raise_for_status(status: int) -> None:
    """Map a provider status to a bounded failure. **The body is never read.**"""
    if status == httpx.codes.UNAUTHORIZED:
        raise ArtifactError(ArtifactFailure.AUTHORISATION_EXPIRED)
    if status == httpx.codes.FORBIDDEN:
        raise ArtifactError(ArtifactFailure.PERMISSION_DENIED)
    if status in (httpx.codes.NOT_FOUND, httpx.codes.GONE):
        raise ArtifactError(ArtifactFailure.GONE)
    if status == httpx.codes.TOO_MANY_REQUESTS:
        raise ArtifactError(ArtifactFailure.RATE_LIMITED)
    if status == httpx.codes.REQUEST_ENTITY_TOO_LARGE:
        raise ArtifactError(ArtifactFailure.TOO_LARGE)
    if status >= httpx.codes.INTERNAL_SERVER_ERROR:
        raise ArtifactError(ArtifactFailure.PROVIDER_UNAVAILABLE)
    if status >= httpx.codes.BAD_REQUEST:
        raise ArtifactError(ArtifactFailure.REQUEST_REJECTED)


def _body(response: httpx.Response) -> Mapping[str, object]:
    """A JSON object, or a bounded failure. Mapped by status code alone."""
    _raise_for_status(response.status_code)
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise ArtifactError(ArtifactFailure.PROVIDER_UNAVAILABLE) from exc
    if not isinstance(payload, dict):
        # An HTML proxy page or an outage splash. Unavailability rather than a
        # rejected request, which would send an operator hunting our config.
        raise ArtifactError(ArtifactFailure.PROVIDER_UNAVAILABLE)
    return payload


def _remote_from(payload: Mapping[str, object], *, requested: str) -> RemoteTranscript:
    """Read a Meet transcript resource, refusing anything that is not one.

    Three refusals, and the middle one is the important one: Google's answer must
    name the artifact that was *asked for*. A response describing a different
    resource is either a proxy serving somebody else's cache or an artifact that
    changed underneath us, and both are `ARTIFACT_CHANGED` rather than data to
    store.
    """
    name = _text(payload.get("name"))
    if name is None or not is_transcript_reference(name):
        raise ArtifactError(ArtifactFailure.NOT_A_TRANSCRIPT)
    if name != requested.strip():
        raise ArtifactError(ArtifactFailure.ARTIFACT_CHANGED)

    destination = payload.get("docsDestination")
    document = _text(destination.get("document")) if isinstance(destination, dict) else None
    if document is None:
        # A transcript with no document is one Meet has not finished writing, or
        # one exported somewhere this connector does not read. Neither is a
        # transcript CAIRN can retrieve.
        raise ArtifactError(ArtifactFailure.NOT_A_TRANSCRIPT)

    declared = _text(payload.get("mimeType")) or TRANSCRIPT_DOCUMENT_TYPE
    if declared.split(";", 1)[0].strip().casefold().startswith(FORBIDDEN_CONTENT_TYPE_PREFIXES):
        # Announced as a transcript, described as media. Refused on the declared
        # type as well as on the downloaded one, because the two lie separately.
        raise ArtifactError(ArtifactFailure.NOT_A_TRANSCRIPT)

    return RemoteTranscript(
        reference=name,
        document_id=document,
        declared_type=declared,
        generated_at=_parse_time(payload.get("startTime")),
    )


def _text(value: object) -> str | None:
    """A non-empty string, or nothing."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _parse_time(raw: object) -> datetime | None:
    """An RFC 3339 timestamp, always timezone-aware.

    Google sends up to nine fractional digits and `datetime.fromisoformat` accepts
    at most six, so the fraction is truncated rather than the timestamp discarded:
    losing nanoseconds costs nothing, and losing the generation time entirely
    would leave provenance with a hole.
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


# ---------------------------------------------------------------------------
# Reading the stream
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class RetrievedContent:
    """What a download actually produced. Bytes, a length and a checksum."""

    content: bytes
    checksum: str
    content_type: str

    @property
    def byte_length(self) -> int:
        return len(self.content)


async def read_capped(
    chunks: AsyncIterator[bytes],
    *,
    content_type: str = EXPORT_CONTENT_TYPE,
    max_bytes: int = MAX_TRANSCRIPT_BYTES,
) -> RetrievedContent:
    """Read a stream to the cap, checksumming as it goes.

    **The cap is checked before each chunk is kept, not after the body is in
    memory.** A generous ceiling enforced after the fact is not a ceiling: the
    failure it is there to prevent — a mislabelled recording, a compression bomb,
    a provider bug — has already happened by the time the length is known.

    The digest is computed over the same bytes that are stored, in the same pass,
    so it describes what was written rather than what was expected.
    """
    if not is_allowed_content_type(content_type):
        raise ArtifactError(ArtifactFailure.CONTENT_TYPE_NOT_ALLOWED)

    digest = hashlib.sha256()
    parts: list[bytes] = []
    total = 0
    async for chunk in chunks:
        total += len(chunk)
        if total > max_bytes:
            # Refused here rather than truncated. A truncated transcript is a
            # record of a meeting that stops in the middle with nothing saying so,
            # which is worse than not having one.
            raise ArtifactError(ArtifactFailure.TOO_LARGE)
        digest.update(chunk)
        parts.append(chunk)

    return RetrievedContent(
        content=b"".join(parts),
        checksum=digest.hexdigest(),
        content_type=content_type.split(";", 1)[0].strip().casefold(),
    )


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "DOWNLOAD_TIMEOUT_SECONDS",
    "FORBIDDEN_CONTENT_TYPE_PREFIXES",
    "FORBIDDEN_TRANSCRIPT_SCOPES",
    "MAX_TRANSCRIPT_BYTES",
    "RESTRICTED_SCOPE_RELEASE_GATE",
    "RETRYABLE_FAILURES",
    "TRANSCRIPT_ALLOWED_SCOPES",
    "TRANSCRIPT_CONSENT_NOTICE",
    "TRANSCRIPT_CONSENT_POLICY_VERSION",
    "TRANSCRIPT_SCOPES",
    "ArtifactError",
    "ArtifactFailure",
    "HttpTranscriptArtifactApi",
    "RemoteTranscript",
    "RetrievedContent",
    "TranscriptArtifactApi",
    "build_transcript_authorize_url",
    "category_for",
    "conference_reference_of",
    "digest_of",
    "is_allowed_content_type",
    "is_forbidden_transcript_scope",
    "is_transcript_reference",
    "open_content",
    "open_reference",
    "open_refresh_token",
    "read_capped",
    "seal_content",
    "seal_reference",
    "seal_refresh_token",
    "verify_granted_transcript_scopes",
]
