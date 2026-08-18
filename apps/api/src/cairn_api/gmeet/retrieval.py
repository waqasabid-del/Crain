"""Retrieving one consented transcript, and re-asking permission every single time.

`gmeet/artifacts.py` is the capability — the restricted scope, the Drive
boundary, the encryption. This module is the *gate* around it, and the whole file
is shaped by one rule:

**Before every metadata lookup, every download, every retry, every reprocess and
every queue action, consent is re-checked inside the transaction that would do
the writing.** Not once when the announcement arrived, not once when the
subscription was created — every time, on the far side of nothing. A transcript
exists for hours or days before anybody looks at it, and the whole point of
withdrawal is that it happens in that window.

The re-check is not a call this module remembers to make; it is a parameter it
cannot avoid. Every retrieval function takes ``permit: CollectionPermit`` as a
required keyword argument, exactly as `subscriptions.ensure_subscription` does,
and a `CollectionPermit` cannot be constructed outside `meetings.guard`. On top of
that, :func:`_gate` re-checks the four things the permit does *not* cover:

- the announcement maps to this exact active subscription **and** this meeting
  request, and the artifact digest on the row matches the announcement's;
- the workspace holds a live, unrevoked **transcript** grant — the connection
  grant is not it;
- nobody on the meeting has opted out of the meeting source, and no expected
  participant's identity has stopped resolving, since;
- the artifact is a **transcript**, checked on the reference shape, on the
  declared type and on the content type of what actually arrives.

Any failure collects nothing and emits a bounded operational outcome: a
`GoogleMeetRefusalReason` on the row, a counter, and a log line with a category in
it and nothing else. **No transcript text, speaker name, joining code, Drive id,
resource name, URL or provider error string reaches a log, a span, a response or a
test fixture.**

**What this module does not do.** It does not summarise, extract commitments,
diarise, identify speakers, or send a single byte to a model. It does not make the
transcript readable through the API: at this step a customer sees availability and
status, never content. Those are all later steps with their own consent
conversations, and a retrieval path that quietly grew one would be collecting
under a permission nobody gave.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final, final

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.config import Settings, get_settings
from cairn_api.connectors.credentials import SecretValue
from cairn_api.db.connector_models import (
    ConnectorErrorCategory,
    ConnectorProvider,
    SourceConnection,
)
from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.gmeet_models import (
    GoogleMeetArtifactKind,
    GoogleMeetArtifactSignal,
    GoogleMeetRefusalReason,
    GoogleMeetSubscription,
    GoogleMeetSubscriptionState,
    GoogleMeetTranscriptArtifact,
    GoogleMeetTranscriptGrant,
    GoogleMeetTranscriptRaw,
    GoogleMeetTranscriptState,
)
from cairn_api.db.meeting_models import (
    MeetingCaptureRequest,
    MeetingParticipant,
    ParticipantStatus,
)
from cairn_api.db.models import Tenant
from cairn_api.gmeet.artifacts import (
    ArtifactError,
    ArtifactFailure,
    HttpTranscriptArtifactApi,
    TranscriptArtifactApi,
    conference_reference_of,
    digest_of,
    is_transcript_reference,
    open_reference,
    open_refresh_token,
    read_capped,
    seal_content,
    seal_reference,
    verify_granted_transcript_scopes,
)
from cairn_api.gmeet.oauth import (
    ACCESS_TOKEN_REFRESH_MARGIN_SECONDS,
    GoogleMeetApi,
    GoogleMeetInstallError,
    GoogleMeetInstallFailure,
)
from cairn_api.gmeet.pubsub import PROVIDER
from cairn_api.meetings.guard import (
    CollectionPermit,
    CollectionRefusedError,
    permit_collection,
)
from cairn_api.sources import Source

logger = structlog.get_logger(__name__)

#: How many times a retryable failure is retried before the row dead-letters.
#:
#: Five, and then it stops. A transcript that cannot be fetched after five spaced
#: attempts is not going to be fetched by a sixth, and a queue that retries
#: forever spends a customer's quota to produce the same refusal — while hiding
#: the failures somebody could act on behind the ones nobody can.
MAX_ATTEMPTS: Final = 5

#: The first retry delay. Doubles per attempt, capped by :data:`MAX_RETRY_DELAY`.
BASE_RETRY_DELAY: Final = timedelta(minutes=5)

#: The ceiling on that doubling. A transcript is not urgent, and an hour between
#: attempts is well inside the window Google keeps the artifact.
MAX_RETRY_DELAY: Final = timedelta(hours=1)

#: Rows claimed per pass. A bound, so one workspace's backlog cannot hold a
#: transaction open across every other workspace's retrievals.
RETRIEVAL_BATCH: Final = 50

#: Rows purged per retention sweep, for the same reason `pipeline/retention.py`
#: caps its own: a first sweep over months of transcripts must drain across passes
#: rather than hold locks through one statement.
PURGE_BATCH: Final = 200

#: States a pass may claim. ``ANNOUNCED`` is a first attempt; ``FAILED`` is a
#: retry whose time has come. ``RETRIEVING`` is deliberately absent — a row
#: another worker holds is not a row to start again — and so is every terminal
#: state, which is what makes a refusal final.
CLAIMABLE_STATES: Final[frozenset[GoogleMeetTranscriptState]] = frozenset(
    {GoogleMeetTranscriptState.ANNOUNCED, GoogleMeetTranscriptState.FAILED}
)


class RetrievalOutcome(StrEnum):
    """What one pass did to one artifact. Bounded, because it is a log field."""

    #: Downloaded, checksummed, stored.
    RETRIEVED = "retrieved"

    #: Already retrieved. A redelivered announcement, a re-run pass, a reprocess
    #: of something that is already done.
    DUPLICATE = "duplicate"

    #: The gate said no. Terminal, and **not** a failure: somebody exercised a
    #: right the product promises them, or the thing announced was not a
    #: transcript. An aggregate that counted this as a failure would page an
    #: operator every time the product worked.
    REFUSED = "refused"

    #: A retryable failure, scheduled.
    RETRY_SCHEDULED = "retry_scheduled"

    #: Out of attempts.
    DEAD_LETTERED = "dead_lettered"

    #: The workspace has not granted transcript access. Not a refusal of consent
    #: and not a failure — it is the normal state of a deployment that has only
    #: connected Google Meet.
    NOT_AUTHORISED = "not_authorised"

    #: The provider's artifact has gone or changed. Recorded truthfully.
    RETIRED = "retired"


@final
@dataclass(frozen=True, slots=True)
class RetrievalPass:
    """What one pass did, in counts.

    Counts and nothing else: this is what a log line and a metric carry, and a
    field that could hold a meeting identifier is a field that eventually does.
    """

    considered: int = 0
    retrieved: int = 0
    refused: int = 0
    retried: int = 0
    dead_lettered: int = 0
    retired: int = 0

    def plus(self, other: RetrievalPass) -> RetrievalPass:
        """Two passes' counts, added. Tenant passes roll up this way."""
        return RetrievalPass(
            considered=self.considered + other.considered,
            retrieved=self.retrieved + other.retrieved,
            refused=self.refused + other.refused,
            retried=self.retried + other.retried,
            dead_lettered=self.dead_lettered + other.dead_lettered,
            retired=self.retired + other.retired,
        )


@final
class TranscriptRetrievalRefusedError(Exception):
    """The gate said no, with a bounded reason.

    Raised rather than returned for the reason `meetings.guard` raises: a refusal
    that must be checked is a refusal that can be ignored, and what is being
    guarded here is downloading a record of what people said.
    """

    def __init__(self, reason: GoogleMeetRefusalReason) -> None:
        self.reason = reason
        super().__init__(f"transcript retrieval refused: {reason.value}")


@final
@dataclass(frozen=True, slots=True)
class RetrievalClient:
    """Everything a retrieval needs from outside the database.

    Two protocols rather than one, exactly as `SubscriptionClient` holds two:
    `tokens` turns a stored refresh token into an access token, `artifacts` reads
    the artifact. Separate services, separate failure modes, and merging them
    would mean a test double for one had to implement the other.
    """

    tokens: GoogleMeetApi
    artifacts: TranscriptArtifactApi


def build_client(settings: Settings | None = None) -> RetrievalClient | None:
    """The production client, or ``None`` when this deployment cannot retrieve.

    ``None`` rather than an exception, because the caller is a maintenance loop
    that runs on every deployment including the ones with no Google Meet
    credentials. A loop that raised there would fill the log with a failure nobody
    can act on and mask the ones somebody can.

    Reads the **transcript** OAuth client, never the connection's. They are
    separate clients for the reason `config.Settings` refuses to let them be the
    same one: a shared client would expand the connection's grant at Google, and
    the connection's next refresh would then return both scope sets and be
    rejected by an equality check doing exactly its job.
    """
    from cairn_api.gmeet.oauth import HttpGoogleMeetApi

    resolved = settings or get_settings()
    client_id = resolved.google_meet_transcript_client_id
    client_secret = resolved.google_meet_transcript_client_secret
    if not client_id or not client_secret:
        return None
    return RetrievalClient(
        tokens=HttpGoogleMeetApi(client_id=client_id, client_secret=client_secret),
        artifacts=HttpTranscriptArtifactApi(),
    )


# ---------------------------------------------------------------------------
# The transcript grant
# ---------------------------------------------------------------------------


async def active_grant(
    db: AsyncSession, *, tenant_id: uuid.UUID, connection_id: uuid.UUID
) -> GoogleMeetTranscriptGrant | None:
    """This connection's live transcript grant, or nothing.

    Read fresh on every retrieval rather than cached on the connection: revoking
    transcript access has to take effect on the next action, and a cached boolean
    is a value that disagrees with the row somebody just changed.
    """
    grant: GoogleMeetTranscriptGrant | None = await db.scalar(
        select(GoogleMeetTranscriptGrant).where(
            GoogleMeetTranscriptGrant.tenant_id == tenant_id,
            GoogleMeetTranscriptGrant.connection_id == connection_id,
            GoogleMeetTranscriptGrant.revoked_at.is_(None),
        )
    )
    return grant


async def revoke_grant(
    db: AsyncSession, *, tenant_id: uuid.UUID, connection_id: uuid.UUID, now: datetime | None = None
) -> bool:
    """Withdraw transcript access. Returns whether anything was held.

    **Marks, never deletes.** "Transcript access was held between these dates" is
    what somebody asks after finding a stored transcript, and a deleted row cannot
    answer it. What stops immediately is every future retrieval: `_gate` reads
    this column, so the next action refuses whatever else is in flight.

    Deliberately does not delete stored transcripts. Withdrawal stops collection;
    what was already collected is governed by the documented retention policy, and
    a revocation that silently erased history would destroy the evidence that the
    revocation was honoured.
    """
    moment = now or datetime.now(UTC)
    result = await db.execute(
        update(GoogleMeetTranscriptGrant)
        .where(
            GoogleMeetTranscriptGrant.tenant_id == tenant_id,
            GoogleMeetTranscriptGrant.connection_id == connection_id,
            GoogleMeetTranscriptGrant.revoked_at.is_(None),
        )
        # Both halves, always. Marking a grant revoked while keeping its refresh
        # token leaves CAIRN holding a standing restricted-scope grant after the
        # customer asked it to stop, which is not a smaller version of the promise.
        .values(
            {
                GoogleMeetTranscriptGrant.revoked_at: moment,
                # The mapped attribute rather than the column name: an ORM-enabled
                # UPDATE synchronises its values back onto loaded instances by
                # attribute, and the string form of a private column silently has
                # no attribute to find.
                GoogleMeetTranscriptGrant._secret_ciphertext: None,
            }
        )
        .returning(GoogleMeetTranscriptGrant.id)
    )
    grant_ids = list(result.scalars().all())
    for grant_id in grant_ids:
        forget_transcript_token(grant_id)
    revoked = bool(grant_ids)
    if revoked:
        await logger.ainfo(
            "gmeet.transcript_access_revoked", tenant_id=str(tenant_id), provider=PROVIDER
        )
    return revoked


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


async def record_availability(
    db: AsyncSession,
    *,
    permit: CollectionPermit,
    signal: GoogleMeetArtifactSignal,
    connection_id: uuid.UUID,
    artifact_reference: str,
    generated_at: datetime | None = None,
    now: datetime | None = None,
) -> GoogleMeetTranscriptArtifact | None:
    """Note that a consented transcript is available, and stop there.

    Called from the Pub/Sub receiver, on the far side of the gate it already runs
    — hence ``permit``, which is that gate's proof rather than a second copy of
    the check.

    **Returns ``None``, and writes nothing, on a workspace with no transcript
    grant.** That is the normal state, and it is what keeps Step 36A's promise
    intact for everybody who has not taken the second consent action: no reference
    is stored, encrypted or otherwise, so there is nothing on disk that could be
    used to fetch anything.

    **Nothing is downloaded here.** The receiver is answering Pub/Sub inside an
    acknowledgement deadline; a download in that path would either blow the
    deadline or be abandoned halfway. This writes a row in ``ANNOUNCED`` and the
    pass picks it up — and re-runs the whole gate when it does, because minutes
    will have passed.
    """
    moment = now or datetime.now(UTC)

    if not is_transcript_reference(artifact_reference):
        # A recording, smart notes, or something with a shape this connector does
        # not act on. Refused before a row exists, so there is nothing to explain
        # away later.
        await logger.ainfo(
            "gmeet.transcript_not_available",
            provider=PROVIDER,
            reason=GoogleMeetRefusalReason.NOT_A_TRANSCRIPT.value,
        )
        return None

    if permit.meeting_id != signal.meeting_id or permit.tenant_id != signal.tenant_id:
        # The permit authorises a different meeting or a different workspace from
        # the announcement it is being used with. Unreachable through the
        # receiver, and refused anyway: this is the argument that carries
        # authority, so it is checked against the thing it is being used with.
        await logger.ainfo(
            "gmeet.transcript_not_available",
            provider=PROVIDER,
            reason=GoogleMeetRefusalReason.REFERENCE_MISMATCH.value,
        )
        return None

    grant = await active_grant(db, tenant_id=signal.tenant_id, connection_id=connection_id)
    if grant is None:
        await logger.ainfo(
            "gmeet.transcript_not_available",
            provider=PROVIDER,
            reason=GoogleMeetRefusalReason.SCOPE_NOT_GRANTED.value,
        )
        return None

    meeting = await db.scalar(
        select(MeetingCaptureRequest).where(MeetingCaptureRequest.id == signal.meeting_id)
    )
    if meeting is None:  # pragma: no cover - the permit proves it existed a moment ago
        return None

    digest = digest_of(artifact_reference)
    if digest != signal.artifact_digest:
        # The announcement and the reference disagree about which artifact this
        # is. One of them is wrong and there is no way to tell which, so nothing
        # is stored.
        await logger.ainfo(
            "gmeet.transcript_not_available",
            provider=PROVIDER,
            reason=GoogleMeetRefusalReason.REFERENCE_MISMATCH.value,
        )
        return None

    statement = (
        insert(GoogleMeetTranscriptArtifact)
        .values(
            tenant_id=signal.tenant_id,
            signal_id=signal.id,
            subscription_id=signal.subscription_id,
            meeting_id=signal.meeting_id,
            provider=ConnectorProvider.GOOGLE_MEET.value,
            kind=GoogleMeetArtifactKind.TRANSCRIPT,
            artifact_digest=digest,
            conference_digest=digest_of(conference_reference_of(artifact_reference)),
            artifact_reference_ciphertext=seal_reference(artifact_reference),
            generated_at=generated_at,
            announced_at=signal.announced_at,
            consent_policy_version=meeting.policy_version,
            state=GoogleMeetTranscriptState.ANNOUNCED,
            state_changed_at=moment,
        )
        # `ON CONFLICT DO NOTHING`, not select-then-insert: Pub/Sub redelivers
        # while the first delivery is still in flight, and two concurrent inserts
        # of one key would both find nothing and the second would abort the
        # transaction.
        .on_conflict_do_nothing(constraint="uq_google_meet_transcript_artifacts_signal")
        .returning(GoogleMeetTranscriptArtifact.id)
    )
    artifact_id = await db.scalar(statement)
    if artifact_id is None:
        return None

    await logger.ainfo(
        "gmeet.transcript_available",
        tenant_id=str(signal.tenant_id),
        provider=PROVIDER,
        # The kind, not the artifact. There is one kind, and naming it is what
        # makes "a transcript became retrievable" auditable without naming which.
        kind=GoogleMeetArtifactKind.TRANSCRIPT.value,
    )
    stored: GoogleMeetTranscriptArtifact | None = await db.scalar(
        select(GoogleMeetTranscriptArtifact).where(GoogleMeetTranscriptArtifact.id == artifact_id)
    )
    return stored


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


async def _current_permit(
    db: AsyncSession, artifact: GoogleMeetTranscriptArtifact, *, now: datetime
) -> CollectionPermit | None:
    """Ask Step 35's gate again, right now. ``None`` means it said no.

    The tenant comes from the row rather than from an ambient session scope, which
    is what lets this run on the platform session the pass holds: the guard
    compares the meeting's own tenant against the one it was given and refuses a
    mismatch.

    The refusal reason is deliberately not returned. It is logged inside the guard
    as a bounded category, and a caller that could branch on it is a caller that
    could decide some refusals are worth ignoring.
    """
    try:
        return await permit_collection(
            db, tenant_id=artifact.tenant_id, meeting_id=artifact.meeting_id, now=now
        )
    except CollectionRefusedError:
        return None


async def _gate(
    db: AsyncSession,
    artifact: GoogleMeetTranscriptArtifact,
    *,
    permit: CollectionPermit,
    connection: SourceConnection,
    now: datetime,
) -> GoogleMeetTranscriptGrant:
    """Everything that must be true *right now*, or nothing is collected.

    Takes the permit rather than deriving one, so the caller provably asked, and
    then checks the four things the permit cannot know about. Order matters only
    in that the cheapest local checks run before anything that could reach a
    network — a refused artifact must never cost a provider call.

    Raises:
        TranscriptRetrievalRefusedError: with a bounded reason. Never with a meeting, a
            participant, a reference or a provider string.
    """
    if permit.meeting_id != artifact.meeting_id or permit.tenant_id != artifact.tenant_id:
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.REFERENCE_MISMATCH)
    if connection.tenant_id != artifact.tenant_id:
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.REFERENCE_MISMATCH)
    if connection.provider is not ConnectorProvider.GOOGLE_MEET:
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.REFERENCE_MISMATCH)
    if not connection.is_active:
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.CONNECTION_INACTIVE)

    if artifact.kind is not GoogleMeetArtifactKind.TRANSCRIPT:
        # Unreachable while the CHECK constraint stands, and checked anyway: this
        # is the assertion the whole step rests on, and a defence that exists only
        # in the schema is one an ORM-level bug walks past.
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.NOT_A_TRANSCRIPT)

    # -- the announcement, the lease and the meeting must be one chain ---------
    signal = await db.scalar(
        select(GoogleMeetArtifactSignal).where(GoogleMeetArtifactSignal.id == artifact.signal_id)
    )
    if (
        signal is None
        or signal.tenant_id != artifact.tenant_id
        or signal.meeting_id != artifact.meeting_id
        or signal.subscription_id != artifact.subscription_id
        or signal.artifact_digest != artifact.artifact_digest
        or signal.kind is not GoogleMeetArtifactKind.TRANSCRIPT
    ):
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.REFERENCE_MISMATCH)

    subscription = await db.scalar(
        select(GoogleMeetSubscription).where(
            GoogleMeetSubscription.id == artifact.subscription_id,
            GoogleMeetSubscription.tenant_id == artifact.tenant_id,
        )
    )
    if (
        subscription is None
        or subscription.meeting_id != artifact.meeting_id
        or subscription.connection_id != connection.id
    ):
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.REFERENCE_MISMATCH)
    if subscription.state in {
        GoogleMeetSubscriptionState.DELETED,
        GoogleMeetSubscriptionState.EXPIRED,
    }:
        # A lease CAIRN has stopped honouring. `remove_subscription` marks the row
        # `DELETED` before it calls Google precisely so that a withdrawal takes
        # effect whether or not Google is reachable, and retrieving under a lease
        # in that state would step around it.
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.CONSENT_NOT_CURRENT)

    # -- the second, separate consent -----------------------------------------
    grant = await active_grant(db, tenant_id=artifact.tenant_id, connection_id=connection.id)
    if grant is None:
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.SCOPE_NOT_GRANTED)

    # -- opt-out and identity, which the meeting gate does not cover -----------
    await _check_people(db, artifact, now=now)

    return grant


async def _check_people(
    db: AsyncSession, artifact: GoogleMeetTranscriptArtifact, *, now: datetime
) -> None:
    """Refuse if anybody expected has opted out or stopped resolving.

    `meetings.eligibility` answers "did everybody agree to *this meeting*". This
    answers two questions it does not ask, and both can change in the window
    between an announcement and a retrieval:

    **Source opt-out.** A person who has opted out of the meeting source has said
    "do not use meetings to build a record of me" — a standing choice, made once,
    that applies to every meeting rather than to one. Collecting a transcript they
    are in would be honouring the narrow consent and ignoring the broad refusal.

    **Identity.** An expected participant whose identity no longer resolves to a
    person is somebody CAIRN can no longer say it asked. Step 34 refuses to decide
    an identity by inference, and the consequence of that is refusing here rather
    than proceeding on a resolution that has since been withdrawn.
    """
    _ = now
    participants = list(
        (
            await db.scalars(
                select(MeetingParticipant).where(
                    MeetingParticipant.meeting_id == artifact.meeting_id,
                    MeetingParticipant.tenant_id == artifact.tenant_id,
                    MeetingParticipant.status == ParticipantStatus.EXPECTED,
                )
            )
        ).all()
    )
    if not participants:
        # An empty expected list is not unanimity; it is a meeting nobody was
        # asked about. The permit should already have refused this, and refusing
        # again costs nothing and closes the case where it did not.
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.CONSENT_NOT_CURRENT)

    person_ids = [item.person_id for item in participants if item.person_id is not None]
    if len(person_ids) != len(participants):
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.IDENTITY_REVOKED)

    opted_out = await db.scalar(
        select(SourceOptOut.id).where(
            SourceOptOut.tenant_id == artifact.tenant_id,
            SourceOptOut.person_id.in_(person_ids),
            SourceOptOut.source == Source.MEETING.value,
        )
    )
    if opted_out is not None:
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.OPTED_OUT)


# ---------------------------------------------------------------------------
# Recording an outcome
# ---------------------------------------------------------------------------


def _refuse(
    artifact: GoogleMeetTranscriptArtifact,
    reason: GoogleMeetRefusalReason,
    *,
    now: datetime,
    state: GoogleMeetTranscriptState = GoogleMeetTranscriptState.REFUSED,
) -> None:
    """Record a terminal refusal on the row, and schedule nothing.

    ``next_attempt_at`` is cleared explicitly. A terminal row carrying a retry
    time is a row a later pass picks up, and the refusal would then be re-derived
    every hour for as long as the row exists.
    """
    artifact.state = state
    artifact.refusal_reason = reason
    artifact.state_changed_at = now
    artifact.next_attempt_at = None


def _retry_delay(attempts: int) -> timedelta:
    """Exponential, capped. Deterministic, so a test can assert the schedule."""
    delay: timedelta = BASE_RETRY_DELAY * (2 ** max(attempts - 1, 0))
    return min(delay, MAX_RETRY_DELAY)


def _fail(
    artifact: GoogleMeetTranscriptArtifact,
    error: ArtifactError,
    *,
    now: datetime,
) -> RetrievalOutcome:
    """Record a failure, and decide whether anything will try again.

    A non-retryable failure dead-letters immediately rather than burning four
    attempts on a refusal that cannot change — a revoked permission is fixed by a
    person, not by waiting.
    """
    artifact.attempts += 1
    artifact.error_category = error.category
    artifact.state_changed_at = now

    if not error.retryable or artifact.attempts >= MAX_ATTEMPTS:
        artifact.state = GoogleMeetTranscriptState.DEAD_LETTERED
        artifact.next_attempt_at = None
        return RetrievalOutcome.DEAD_LETTERED

    artifact.state = GoogleMeetTranscriptState.FAILED
    artifact.next_attempt_at = now + _retry_delay(artifact.attempts)
    return RetrievalOutcome.RETRY_SCHEDULED


async def _store(
    db: AsyncSession,
    artifact: GoogleMeetTranscriptArtifact,
    *,
    content: bytes,
    checksum: str,
    content_type: str,
    now: datetime,
) -> None:
    """Write the bytes to the protected raw store, encrypted, with a retention date.

    The raw row is written with ``ON CONFLICT DO NOTHING`` on the artifact, so a
    retry that raced with a completed attempt cannot produce two copies of one
    transcript — the unique constraint decides, not the order the two workers
    happened to run in.
    """
    retention_days = await db.scalar(
        select(Tenant.retention_days).where(Tenant.id == artifact.tenant_id)
    )
    await db.execute(
        insert(GoogleMeetTranscriptRaw)
        .values(
            tenant_id=artifact.tenant_id,
            artifact_id=artifact.id,
            content_ciphertext=seal_content(content),
            content_checksum=checksum,
            content_bytes=len(content),
            stored_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_google_meet_transcript_raw_artifact")
    )

    artifact.state = GoogleMeetTranscriptState.STORED
    artifact.state_changed_at = now
    artifact.retrieved_at = now
    artifact.content_type = content_type
    artifact.content_bytes = len(content)
    artifact.content_checksum = checksum
    artifact.refusal_reason = None
    artifact.error_category = None
    artifact.next_attempt_at = None
    # Stored rather than computed on read: shortening a workspace's retention
    # period later must not retroactively claim a transcript was already due for
    # deletion when it was not.
    artifact.retention_expires_at = now + timedelta(days=int(retention_days or 0))


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class _CachedToken:
    expires_at: float
    token: SecretValue


#: Per-grant, in-process, never persisted — and **the transcript grant's own**,
#: not a shared cache with `gmeet/oauth.py`.
#:
#: Keyed on the grant id, so there is no key the connection's cache could collide
#: with. A shared dictionary would let a connection access token — which carries
#: `meetings.space.readonly` and not the Drive scope — be handed to a download,
#: and Google would refuse it with an error naming neither.
_TOKEN_CACHE: dict[uuid.UUID, _CachedToken] = {}


def forget_transcript_token(grant_id: uuid.UUID) -> None:
    """Drop one grant's cached access token. Called on revocation.

    A workspace that has withdrawn transcript access must not leave a usable
    token in this process's memory for the next hour.
    """
    _TOKEN_CACHE.pop(grant_id, None)


def clear_transcript_token_cache() -> None:
    """Drop every cached transcript token. For tests, which must not inherit each other's."""
    _TOKEN_CACHE.clear()


async def _access_token(
    client: RetrievalClient,
    grant: GoogleMeetTranscriptGrant,
    *,
    now: float | None = None,
) -> SecretValue:
    """A usable access token **for the transcript grant**, refreshing if needed.

    Deliberately not `oauth.access_token_for`: that one reads the *connection's*
    refresh token, which carries `meetings.space.readonly` and cannot download
    anything. The two credentials are separate at Google and separate here, which
    is what makes revoking transcript access revoke something rather than clear a
    flag beside a token that still works.

    The granted scope set is verified on **every** refresh, not only at the
    consent action. An administrator can widen or narrow a grant afterwards and
    Google reports the current set here, so a grant that quietly acquired a
    broader Drive scope is refused on the next refresh rather than used.
    """
    moment = now if now is not None else time.monotonic()

    cached = _TOKEN_CACHE.get(grant.id)
    if cached is not None and cached.expires_at > moment:
        return cached.token

    ciphertext = grant._secret_ciphertext
    if ciphertext is None:
        raise ArtifactError(ArtifactFailure.SCOPE_NOT_GRANTED)

    try:
        refreshed = await client.tokens.refresh_access_token(
            refresh_token=open_refresh_token(ciphertext)
        )
    except GoogleMeetInstallError as error:
        raise ArtifactError(
            _INSTALL_FAILURES.get(error.failure, ArtifactFailure.REQUEST_REJECTED)
        ) from error

    verify_granted_transcript_scopes(refreshed.granted_scopes)

    lifetime = max(refreshed.expires_in - ACCESS_TOKEN_REFRESH_MARGIN_SECONDS, 0.0)
    _TOKEN_CACHE[grant.id] = _CachedToken(
        expires_at=moment + lifetime, token=refreshed.access_token
    )
    return refreshed.access_token


#: How an OAuth-layer failure arrives here. Translating at this one boundary keeps
#: the retrieval path speaking a single language rather than catching two
#: exception types at every call site.
_INSTALL_FAILURES: Final[dict[GoogleMeetInstallFailure, ArtifactFailure]] = {
    GoogleMeetInstallFailure.AUTHORISATION_EXPIRED: ArtifactFailure.AUTHORISATION_EXPIRED,
    GoogleMeetInstallFailure.ACCESS_FORBIDDEN: ArtifactFailure.PERMISSION_DENIED,
    GoogleMeetInstallFailure.SCOPES_INSUFFICIENT: ArtifactFailure.SCOPE_INSUFFICIENT,
    GoogleMeetInstallFailure.SCOPES_UNEXPECTED: ArtifactFailure.SCOPE_UNEXPECTED,
    GoogleMeetInstallFailure.SCOPES_FORBIDDEN: ArtifactFailure.SCOPE_FORBIDDEN,
    GoogleMeetInstallFailure.RATE_LIMITED: ArtifactFailure.RATE_LIMITED,
    GoogleMeetInstallFailure.PROVIDER_UNAVAILABLE: ArtifactFailure.PROVIDER_UNAVAILABLE,
    GoogleMeetInstallFailure.NOT_CONFIGURED: ArtifactFailure.NOT_CONFIGURED,
}

#: Provider failures that mean the artifact itself is gone or is not what was
#: announced. Recorded as a retirement rather than as a failure, because there is
#: nothing wrong with CAIRN and nothing a retry can do.
_RETIRING_FAILURES: Final[dict[ArtifactFailure, GoogleMeetRefusalReason]] = {
    ArtifactFailure.GONE: GoogleMeetRefusalReason.ARTIFACT_GONE,
    ArtifactFailure.ARTIFACT_CHANGED: GoogleMeetRefusalReason.ARTIFACT_CHANGED,
    ArtifactFailure.NOT_A_TRANSCRIPT: GoogleMeetRefusalReason.NOT_A_TRANSCRIPT,
    ArtifactFailure.CONTENT_TYPE_NOT_ALLOWED: GoogleMeetRefusalReason.NOT_A_TRANSCRIPT,
    ArtifactFailure.TOO_LARGE: GoogleMeetRefusalReason.TOO_LARGE,
    ArtifactFailure.CHECKSUM_MISMATCH: GoogleMeetRefusalReason.CHECKSUM_MISMATCH,
    ArtifactFailure.SCOPE_NOT_GRANTED: GoogleMeetRefusalReason.SCOPE_NOT_GRANTED,
}


async def retrieve_artifact(
    db: AsyncSession,
    client: RetrievalClient,
    connection: SourceConnection,
    artifact: GoogleMeetTranscriptArtifact,
    *,
    permit: CollectionPermit,
    now: datetime | None = None,
) -> RetrievalOutcome:
    """Retrieve one transcript, having re-asked permission first.

    **``permit`` is required and cannot be forged**, exactly as it is on
    `subscriptions.ensure_subscription`. A `CollectionPermit` is issued only by
    `meetings.guard.permit_collection`, so there is no way to reach this function
    without having asked whether every participant still agrees — and
    :func:`_gate` re-checks everything the permit does not cover before a single
    byte is requested.

    Never raises for a provider failure: the outcome is recorded on the row it
    happened to, so a pass over fifty transcripts does not stop at the first one
    Google refuses.
    """
    moment = now or datetime.now(UTC)

    if artifact.state is GoogleMeetTranscriptState.STORED:
        # Already done. A redelivered announcement, a re-run pass, a reprocess of
        # something finished — all one answer, and none of them downloads a second
        # copy.
        return RetrievalOutcome.DUPLICATE

    try:
        grant = await _gate(db, artifact, permit=permit, connection=connection, now=moment)
    except TranscriptRetrievalRefusedError as refusal:
        _refuse(artifact, refusal.reason, now=moment)
        await db.flush()
        await logger.ainfo(
            "gmeet.transcript_retrieval_refused",
            tenant_id=str(artifact.tenant_id),
            provider=PROVIDER,
            reason=refusal.reason.value,
        )
        return (
            RetrievalOutcome.NOT_AUTHORISED
            if refusal.reason is GoogleMeetRefusalReason.SCOPE_NOT_GRANTED
            else RetrievalOutcome.REFUSED
        )

    artifact.state = GoogleMeetTranscriptState.RETRIEVING
    artifact.state_changed_at = moment
    # Flushed before the network call, so a crash mid-download leaves a row that
    # visibly stalled rather than one that silently never started.
    await db.flush()

    try:
        # The reference comes back into the clear here and nowhere else on this
        # path. It is not assigned to anything that outlives the call, not
        # logged, and not returned.
        reference = open_reference(artifact.artifact_reference_ciphertext)
        token = await _access_token(client, grant)
        remote = await client.artifacts.describe(access_token=token, reference=reference)
        if digest_of(remote.reference) != artifact.artifact_digest:
            # Google answered about a different artifact than the one announced.
            raise ArtifactError(ArtifactFailure.ARTIFACT_CHANGED)
        retrieved = await read_capped(
            client.artifacts.download(access_token=token, artifact=remote)
        )
    except ArtifactError as error:
        retiring = _RETIRING_FAILURES.get(error.failure)
        if retiring is not None:
            _refuse(artifact, retiring, now=moment, state=GoogleMeetTranscriptState.RETIRED)
            artifact.error_category = error.category
            await db.flush()
            await logger.ainfo(
                "gmeet.transcript_retired",
                tenant_id=str(artifact.tenant_id),
                provider=PROVIDER,
                reason=retiring.value,
            )
            return RetrievalOutcome.RETIRED

        outcome = _fail(artifact, error, now=moment)
        await db.flush()
        await logger.awarning(
            "gmeet.transcript_retrieval_failed",
            tenant_id=str(artifact.tenant_id),
            provider=PROVIDER,
            # A category and an outcome. There is no field here a transcript, a
            # reference or a Google sentence could reach.
            error_category=error.category.value,
            outcome=outcome.value,
        )
        return outcome

    await _store(
        db,
        artifact,
        content=retrieved.content,
        checksum=retrieved.checksum,
        content_type=retrieved.content_type,
        now=moment,
    )
    await db.flush()

    await logger.ainfo(
        "gmeet.transcript_retrieved",
        tenant_id=str(artifact.tenant_id),
        provider=PROVIDER,
        kind=GoogleMeetArtifactKind.TRANSCRIPT.value,
        # A size, because "did anything arrive" is the operational question. Not
        # the checksum, which is derived from content, and not the type beyond the
        # allowlist member it matched.
        content_bytes=retrieved.byte_length,
        content_type=retrieved.content_type,
    )
    return RetrievalOutcome.RETRIEVED


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


async def _claimable(
    db: AsyncSession, *, tenant_id: uuid.UUID | None, now: datetime, limit: int
) -> Sequence[GoogleMeetTranscriptArtifact]:
    """Rows this pass may touch, claimed for the rest of the transaction.

    ``FOR UPDATE SKIP LOCKED``, the same mechanism the job queue uses: a second
    worker running this pass at the same moment sees the locked rows as absent and
    retrieves none of them, rather than waiting to retrieve them a second time.
    That is the only claim that holds when the two passes are in different
    processes on different machines.
    """
    statement = (
        select(GoogleMeetTranscriptArtifact)
        .where(
            GoogleMeetTranscriptArtifact.state.in_(sorted(CLAIMABLE_STATES)),
            GoogleMeetTranscriptArtifact.withdrawn_at.is_(None),
            (GoogleMeetTranscriptArtifact.next_attempt_at.is_(None))
            | (GoogleMeetTranscriptArtifact.next_attempt_at <= now),
        )
        # Oldest announcement first, so a truncated batch drops the newest rather
        # than starving the one that has been waiting longest.
        .order_by(GoogleMeetTranscriptArtifact.announced_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if tenant_id is not None:
        statement = statement.where(GoogleMeetTranscriptArtifact.tenant_id == tenant_id)
    return (await db.scalars(statement)).all()


async def retrieve_pending_transcripts(
    db: AsyncSession,
    *,
    client: RetrievalClient | None = None,
    tenant_id: uuid.UUID | None = None,
    now: datetime | None = None,
    limit: int = RETRIEVAL_BATCH,
) -> RetrievalPass:
    """The retrieval pass the maintenance loop runs.

    Returns an empty pass, silently, when this deployment has no Google Meet
    credentials: the maintenance loop runs everywhere, and a warning nobody can
    act on hides the ones somebody can.

    **The gate runs per artifact, inside this transaction, immediately before the
    retrieval it authorises** — not once for the batch. Two transcripts for the
    same meeting, and a withdrawal that lands between them, must produce one
    retrieval and one refusal.
    """
    moment = now or datetime.now(UTC)
    resolved = client or build_client()
    if resolved is None:
        return RetrievalPass()

    claimed = await _claimable(db, tenant_id=tenant_id, now=moment, limit=limit)
    if not claimed:
        return RetrievalPass()

    total = RetrievalPass(considered=len(claimed))
    for artifact in claimed:
        permit = await _current_permit(db, artifact, now=moment)
        if permit is None:
            # Withdrawn, declined, cancelled, rescheduled, expired, re-worded —
            # one answer to all six, recorded on the row and never retried.
            _refuse(artifact, GoogleMeetRefusalReason.CONSENT_NOT_CURRENT, now=moment)
            await db.flush()
            await logger.ainfo(
                "gmeet.transcript_retrieval_refused",
                tenant_id=str(artifact.tenant_id),
                provider=PROVIDER,
                reason=GoogleMeetRefusalReason.CONSENT_NOT_CURRENT.value,
            )
            total = total.plus(RetrievalPass(refused=1))
            continue

        connection = await _connection_for(db, artifact)
        if connection is None:
            _refuse(artifact, GoogleMeetRefusalReason.CONNECTION_INACTIVE, now=moment)
            await db.flush()
            total = total.plus(RetrievalPass(refused=1))
            continue

        outcome = await retrieve_artifact(
            db, resolved, connection, artifact, permit=permit, now=moment
        )
        total = total.plus(_tally(outcome))

    await logger.ainfo(
        "gmeet.transcript_retrieval_pass",
        provider=PROVIDER,
        considered=total.considered,
        retrieved=total.retrieved,
        refused=total.refused,
        outcome="degraded" if total.dead_lettered else "ok",
    )
    return total


def _tally(outcome: RetrievalOutcome) -> RetrievalPass:
    """One outcome as a one-row pass. Keeps the counting in one place."""
    return RetrievalPass(
        retrieved=1 if outcome is RetrievalOutcome.RETRIEVED else 0,
        refused=1 if outcome in {RetrievalOutcome.REFUSED, RetrievalOutcome.NOT_AUTHORISED} else 0,
        retried=1 if outcome is RetrievalOutcome.RETRY_SCHEDULED else 0,
        dead_lettered=1 if outcome is RetrievalOutcome.DEAD_LETTERED else 0,
        retired=1 if outcome is RetrievalOutcome.RETIRED else 0,
    )


async def _connection_for(
    db: AsyncSession, artifact: GoogleMeetTranscriptArtifact
) -> SourceConnection | None:
    """The Meet connection this artifact's lease hangs off, or nothing."""
    subscription = await db.scalar(
        select(GoogleMeetSubscription).where(
            GoogleMeetSubscription.id == artifact.subscription_id,
            GoogleMeetSubscription.tenant_id == artifact.tenant_id,
        )
    )
    if subscription is None:
        return None
    connection: SourceConnection | None = await db.scalar(
        select(SourceConnection).where(
            SourceConnection.id == subscription.connection_id,
            SourceConnection.tenant_id == artifact.tenant_id,
            SourceConnection.provider == ConnectorProvider.GOOGLE_MEET,
        )
    )
    return connection


async def reprocess_artifact(
    db: AsyncSession,
    client: RetrievalClient,
    *,
    tenant_id: uuid.UUID,
    artifact_id: uuid.UUID,
    now: datetime | None = None,
) -> RetrievalOutcome:
    """Try one artifact again, on purpose.

    An operator action, and it goes through **exactly** the same gate as the
    automatic pass — the permit is obtained here, freshly, rather than passed in.
    A reprocess entry point that trusted its caller would be the way a withdrawn
    meeting gets collected: somebody re-runs a batch to fix an unrelated problem,
    and the row that was refused for a reason comes along with it.

    A dead-lettered row is deliberately reachable this way and an already-stored
    row is not: the first is a failure somebody has since fixed, and the second is
    a second download of a transcript CAIRN already holds.
    """
    moment = now or datetime.now(UTC)
    artifact = await db.scalar(
        select(GoogleMeetTranscriptArtifact)
        .where(
            GoogleMeetTranscriptArtifact.id == artifact_id,
            GoogleMeetTranscriptArtifact.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if artifact is None:
        raise TranscriptRetrievalRefusedError(GoogleMeetRefusalReason.REFERENCE_MISMATCH)
    if artifact.state is GoogleMeetTranscriptState.STORED:
        return RetrievalOutcome.DUPLICATE
    if artifact.withdrawn_at is not None:
        # Consent stopped after this row was created. A reprocess must not be the
        # way that decision gets walked back.
        return RetrievalOutcome.REFUSED

    permit = await _current_permit(db, artifact, now=moment)
    if permit is None:
        _refuse(artifact, GoogleMeetRefusalReason.CONSENT_NOT_CURRENT, now=moment)
        await db.flush()
        return RetrievalOutcome.REFUSED

    connection = await _connection_for(db, artifact)
    if connection is None:
        _refuse(artifact, GoogleMeetRefusalReason.CONNECTION_INACTIVE, now=moment)
        await db.flush()
        return RetrievalOutcome.REFUSED

    return await retrieve_artifact(db, client, connection, artifact, permit=permit, now=moment)


# ---------------------------------------------------------------------------
# Withdrawal after the fact, and retention
# ---------------------------------------------------------------------------


async def note_withdrawal(
    db: AsyncSession, *, tenant_id: uuid.UUID, meeting_id: uuid.UUID, now: datetime | None = None
) -> int:
    """Consent stopped. Stop everything future, and rewrite nothing past.

    Every artifact for the meeting is stamped ``withdrawn_at``, which removes it
    from the pass and from reprocessing. Rows that had not been retrieved are also
    refused outright, so they do not sit in ``ANNOUNCED`` looking like work.

    **Stored transcripts are not deleted here, and that is deliberate.** Deletion
    is the retention path's job and runs to a published schedule; a withdrawal
    that silently erased what had already been collected would also erase the
    evidence that the withdrawal was honoured, and would make "we deleted it"
    something the customer has to take on faith rather than something the record
    shows. Returns the number of artifacts affected.
    """
    moment = now or datetime.now(UTC)
    artifacts = list(
        (
            await db.scalars(
                select(GoogleMeetTranscriptArtifact)
                .where(
                    GoogleMeetTranscriptArtifact.tenant_id == tenant_id,
                    GoogleMeetTranscriptArtifact.meeting_id == meeting_id,
                    GoogleMeetTranscriptArtifact.withdrawn_at.is_(None),
                )
                .with_for_update()
            )
        ).all()
    )
    for artifact in artifacts:
        artifact.withdrawn_at = moment
        if (
            artifact.state in CLAIMABLE_STATES
            or artifact.state is GoogleMeetTranscriptState.RETRIEVING
        ):
            _refuse(artifact, GoogleMeetRefusalReason.CONSENT_NOT_CURRENT, now=moment)

    if artifacts:
        await db.flush()
        await logger.ainfo(
            "gmeet.transcript_withdrawn",
            tenant_id=str(tenant_id),
            provider=PROVIDER,
            count=len(artifacts),
        )
    return len(artifacts)


async def purge_expired_transcripts(
    db: AsyncSession, *, now: datetime | None = None, limit: int = PURGE_BATCH
) -> int:
    """Delete raw transcripts whose retention window has closed.

    **The bytes go and the provenance stays.** The raw row is deleted and
    ``raw_purged_at`` is stamped on the artifact, so a workspace can still be told
    that a transcript existed, when it was collected and when it was deleted. That
    is the sentence a retention policy has to be able to produce; "no record at
    all" would be indistinguishable from never having collected it.

    Deleted rather than filtered, for the reason `pipeline/retention.py` gives:
    the period is published, and a published deletion that only hides the row is
    not a deletion. Bounded per pass so a first sweep drains across passes rather
    than holding locks through one statement.
    """
    moment = now or datetime.now(UTC)
    due = list(
        (
            await db.scalars(
                select(GoogleMeetTranscriptArtifact)
                .where(
                    GoogleMeetTranscriptArtifact.retention_expires_at.is_not(None),
                    GoogleMeetTranscriptArtifact.retention_expires_at <= moment,
                    GoogleMeetTranscriptArtifact.raw_purged_at.is_(None),
                )
                .order_by(GoogleMeetTranscriptArtifact.retention_expires_at.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    if not due:
        return 0

    await db.execute(
        delete(GoogleMeetTranscriptRaw).where(
            GoogleMeetTranscriptRaw.artifact_id.in_([item.id for item in due])
        )
    )
    for artifact in due:
        artifact.raw_purged_at = moment
    await db.flush()

    await logger.ainfo(
        "gmeet.transcript_retention_swept",
        provider=PROVIDER,
        count=len(due),
        capped=len(due) >= limit,
    )
    return len(due)


async def delete_transcript(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    artifact_id: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    """Delete one stored transcript ahead of its retention date, on request.

    The controlled path, and the only one: there is no endpoint that deletes by
    meeting, by workspace or by date range, because a bulk deletion surface is how
    an inconvenient record disappears under time pressure. Returns whether
    anything was deleted.

    The provenance row survives, exactly as it does under the retention sweep.
    """
    moment = now or datetime.now(UTC)
    artifact = await db.scalar(
        select(GoogleMeetTranscriptArtifact)
        .where(
            GoogleMeetTranscriptArtifact.id == artifact_id,
            GoogleMeetTranscriptArtifact.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if artifact is None or artifact.raw_purged_at is not None:
        return False

    await db.execute(
        delete(GoogleMeetTranscriptRaw).where(
            GoogleMeetTranscriptRaw.tenant_id == tenant_id,
            GoogleMeetTranscriptRaw.artifact_id == artifact_id,
        )
    )
    artifact.raw_purged_at = moment
    await db.flush()
    await logger.ainfo(
        "gmeet.transcript_deleted", tenant_id=str(tenant_id), provider=PROVIDER, count=1
    )
    return True


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@final
@dataclass(frozen=True, slots=True)
class TranscriptStatus:
    """What a customer may be told about one transcript. **Availability, never content.**

    Every field is a state, a time, a count or a bounded reason. There is nowhere
    here to put a transcript, a speaker, a resource name, a Drive id or a
    checksum — the last of those is absent deliberately, because a checksum of a
    known-format document is a value somebody can confirm a guess against.
    """

    artifact_id: uuid.UUID
    meeting_id: uuid.UUID
    state: GoogleMeetTranscriptState
    refusal_reason: GoogleMeetRefusalReason | None
    error_category: ConnectorErrorCategory | None
    announced_at: datetime
    generated_at: datetime | None
    retrieved_at: datetime | None
    content_bytes: int | None

    #: Whether the raw transcript is still held. False after the retention sweep
    #: or a deletion, which is a different fact from never having collected it.
    content_held: bool

    retention_expires_at: datetime | None
    withdrawn_at: datetime | None


async def transcript_statuses(
    db: AsyncSession, *, tenant_id: uuid.UUID, meeting_id: uuid.UUID | None = None
) -> tuple[TranscriptStatus, ...]:
    """One workspace's transcript states. Read-only, and content-free by construction.

    Selects the columns a status may carry rather than the row, so a column added
    to the table later cannot appear in a response by default — the same reason
    `api/schemas.py` exists at all.
    """
    statement = select(GoogleMeetTranscriptArtifact).where(
        GoogleMeetTranscriptArtifact.tenant_id == tenant_id
    )
    if meeting_id is not None:
        statement = statement.where(GoogleMeetTranscriptArtifact.meeting_id == meeting_id)
    rows = (
        await db.scalars(statement.order_by(GoogleMeetTranscriptArtifact.announced_at.desc()))
    ).all()

    return tuple(
        TranscriptStatus(
            artifact_id=item.id,
            meeting_id=item.meeting_id,
            state=item.state,
            refusal_reason=item.refusal_reason,
            error_category=item.error_category,
            announced_at=item.announced_at,
            generated_at=item.generated_at,
            retrieved_at=item.retrieved_at,
            content_bytes=item.content_bytes,
            content_held=item.retrieved_at is not None and item.raw_purged_at is None,
            retention_expires_at=item.retention_expires_at,
            withdrawn_at=item.withdrawn_at,
        )
        for item in rows
    )


__all__ = [
    "CLAIMABLE_STATES",
    "MAX_ATTEMPTS",
    "RetrievalClient",
    "RetrievalOutcome",
    "RetrievalPass",
    "TranscriptRetrievalRefusedError",
    "TranscriptStatus",
    "active_grant",
    "build_client",
    "delete_transcript",
    "note_withdrawal",
    "purge_expired_transcripts",
    "record_availability",
    "reprocess_artifact",
    "retrieve_artifact",
    "retrieve_pending_transcripts",
    "revoke_grant",
    "transcript_statuses",
]
