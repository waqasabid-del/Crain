"""The Google Meet connector's tables, and what is deliberately missing from them.

Shaped like ``db/gchat_models.py``, because the OAuth half of the two connectors
is the same problem. The *subscription* half is not, and the difference is the
whole reason this file exists rather than a `provider` column on Chat's tables.

**A Meet subscription is attached to a consented meeting, not to a chosen
space.** Google Chat's permission model is "an admin ticked a space", and the
selection row *is* the permission. Meet's is Step 35's
:class:`~cairn_api.db.meeting_models.MeetingCaptureRequest`: every expected
participant has to have agreed, under the current policy wording, for a meeting
that has not moved. So :class:`GoogleMeetSubscription` points at a meeting
request and nothing else, and the code that creates one cannot be called without
a :class:`~cairn_api.meetings.guard.CollectionPermit`.

**There is no joining-code column, and there is no space-name column.** Step 35
already removed ``external_meeting_ref`` from every response for this reason: for
Google Meet that value is the meeting's joining code, which is a *credential* —
anybody holding it can enter the meeting. It is needed exactly once, at the
moment a subscription is created, and it is read from the permit at that moment
and never written down. A column here would put a live meeting credential in a
database, a backup, a staff diagnostics screen and a log line, in exchange for
saving one join.

**:class:`GoogleMeetArtifactSignal` still has no transcript column, no artifact
URI and no content column.** It records that Google said a transcript file exists
— a fact with a timestamp — and identifies it only by digest. Step 36A stops
there, and the announcement table keeps that shape unchanged.

**Step 36B adds retrieval, and it adds it beside that table rather than inside
it.** Three more tables, and the split between them is the design:

- :class:`GoogleMeetTranscriptGrant` is a *separate* authorisation record. A
  workspace that connected Google Meet has not thereby granted transcript access;
  the restricted Drive scope is its own consent action with its own row, and
  revoking it leaves the Meet connection intact.
- :class:`GoogleMeetTranscriptArtifact` is provenance and lifecycle. It holds
  which meeting, which lease, which announcement, when the platform generated the
  artifact, when CAIRN retrieved it, the checksum, the consent-policy version —
  and the provider reference **encrypted**, because retrieving something requires
  naming it and a plaintext column would put a durable handle to one specific
  meeting in a backup and a diagnostics screen.
- :class:`GoogleMeetTranscriptRaw` is the content, encrypted, in its own table
  with **no grant to the application role at all**. Its own table so that
  retention deletion removes the transcript and leaves the provenance standing:
  "this was collected, and it has since been deleted" is a different sentence from
  "this never happened", and only the first one is true.

Nothing here stores a credential (``connectors/credentials.py`` owns that), an
email address, a meeting title, a joining code, or a participant.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from cairn_api.db.connector_models import ConnectorErrorCategory

#: A Workspace Events subscription resource name: ``subscriptions/{id}``.
#:
#: The same shape Chat's subscriptions use, restated here rather than imported so
#: that a change to one connector's pattern cannot silently retype the other's
#: column.
SUBSCRIPTION_NAME_PATTERN = r"^subscriptions/[A-Za-z0-9_-]{1,120}$"

#: A Google Meet **space** resource name: ``spaces/{space}``.
#:
#: This is what a subscription's ``targetResource`` is built from, and it is
#: deliberately *not* a joining code. A joining code (``abc-defg-hij``) is a
#: credential; a space resource name is an opaque identifier. The pattern is
#: enforced where the value is used — see `gmeet/subscriptions.py` — and appears
#: here because that is where the two are distinguished in writing.
SPACE_NAME_PATTERN = r"^spaces/[A-Za-z0-9_-]{1,120}$"

#: A Meet **transcript** resource name: ``conferenceRecords/{c}/transcripts/{t}``.
#:
#: The only artifact reference this connector will act on. It is matched in order
#: to *allow*, which is the opposite way round from the joining code below and is
#: the point: a recording is ``conferenceRecords/{c}/recordings/{r}`` and smart
#: notes arrive under their own path, so an allowlist on the shape refuses both
#: without needing to enumerate what Google might add next.
TRANSCRIPT_REFERENCE_PATTERN = (
    r"^conferenceRecords/[A-Za-z0-9_-]{1,120}/transcripts/[A-Za-z0-9_-]{1,120}$"
)

#: The conference half of that name, matched so provenance can record which
#: conference an artifact belonged to — as a digest, never as the value.
CONFERENCE_REFERENCE_PATTERN = r"^conferenceRecords/[A-Za-z0-9_-]{1,120}$"

#: What a Meet joining code looks like. Matched in order to **refuse** it.
#:
#: Nothing in this connector ever accepts one: a value in this shape reaching the
#: subscription path means Step 35 stored a credential where it should have
#: stored a space resource name, and failing loudly there is the only way that
#: gets noticed before it reaches a Google request, a retry log and a trace.
JOINING_CODE_PATTERN = r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$"


def _values(enum_class: type[enum.Enum]) -> list[str]:
    """Store the enum's values, not its member names."""
    return [member.value for member in enum_class]


class GoogleMeetSubscriptionState(enum.StrEnum):
    """Where one meeting's event subscription is in its lifecycle.

    The same six states as Chat's, and deliberately a **separate enum**: they are
    two columns on two tables with two lifecycles, and one shared enum is one
    place where a Meet-only state added later would silently widen Chat's CHECK
    constraint.
    """

    #: A permit was issued, Google has not been asked yet.
    PENDING = "pending"

    ACTIVE = "active"

    #: Google stopped delivering but the subscription still exists.
    SUSPENDED = "suspended"

    #: Past ``expire_time`` with no renewal. Google deletes these; the row is
    #: kept so "why did this meeting produce nothing" has an answer.
    EXPIRED = "expired"

    #: Deleted at Google — by us when consent changed, or by Google after expiry.
    DELETED = "deleted"

    #: We could not create or renew it. ``error_category`` says why.
    ERROR = "error"


class GoogleMeetArtifactKind(enum.StrEnum):
    """What kind of artifact Google announced.

    One member, and the constraint that keeps it that way is the point: CAIRN
    subscribes to the transcript-file-generated event and to nothing else, so a
    second member here would mean somebody had widened the event tuple in
    `gmeet/subscriptions.py`. There is deliberately no ``RECORDING``, no
    ``SMART_NOTES``, and nothing about participants or attendance.
    """

    TRANSCRIPT = "transcript"


class GoogleMeetGrantKind(enum.StrEnum):
    """Which authorisation an in-flight install is asking for.

    Two members, and they are two consent conversations rather than two steps of
    one. ``CONNECTION`` is Step 36A: ``meetings.space.readonly``, which authorises
    a subscription and reads nothing. ``TRANSCRIPT`` is Step 36B:
    ``drive.meet.readonly``, which authorises reading the transcript file the
    platform produced.

    The column exists so the callback can tell them apart. Without it there is one
    redirect URI, one state table and two possible meanings — and the failure mode
    is a workspace that pressed "Connect Google Meet" ending up with transcript
    access because a later branch defaulted.
    """

    CONNECTION = "connection"
    TRANSCRIPT = "transcript"


class GoogleMeetTranscriptState(enum.StrEnum):
    """Where one announced transcript artifact is in its lifecycle.

    Every member is an outcome somebody can be shown. There is no ``UNKNOWN`` and
    no nullable state, because "we do not know what happened to this transcript"
    is not an answer this product may give about a meeting people consented to.
    """

    #: Google announced it; nothing has been asked of Drive. The state a row is
    #: born in, and the state it stays in on a deployment with no transcript
    #: grant.
    ANNOUNCED = "announced"

    #: Claimed by one worker for one attempt. Written before the network call, so
    #: a crash mid-download leaves a row that visibly stalled rather than one that
    #: silently never started.
    RETRIEVING = "retrieving"

    #: Retrieved, checksummed and stored.
    STORED = "stored"

    #: The gate said no. Terminal, and **not** a failure: somebody exercised a
    #: right the product promises them, or the artifact was not a transcript.
    REFUSED = "refused"

    #: A retryable failure. ``attempts`` and ``next_attempt_at`` say when.
    FAILED = "failed"

    #: Out of attempts. Terminal, kept, and never silently retried again.
    DEAD_LETTERED = "dead_lettered"

    #: The provider's artifact has gone or changed underneath us. Terminal, and
    #: recorded as what it is rather than deleted — see
    #: :class:`GoogleMeetTranscriptArtifact`.
    RETIRED = "retired"


class GoogleMeetRefusalReason(enum.StrEnum):
    """Why a retrieval collected nothing. A closed vocabulary, and ours.

    Bounded because it reaches a column, a log field and a status response. Not
    one member quotes Google, names a meeting, or carries a file identifier: a
    refusal reason is an operational fact, and everything that would make it
    identifying stays in the database.
    """

    #: `meetings.guard.permit_collection` refused — withdrawn, declined, added
    #: participant, changed wording, rescheduled, cancelled, expired. One member
    #: for all of them, because the guard deliberately does not tell its caller
    #: which, and a caller that could branch on it is one that could decide some
    #: refusals are worth ignoring.
    CONSENT_NOT_CURRENT = "consent_not_current"

    #: A person on this meeting has opted out of the meeting source since.
    OPTED_OUT = "opted_out"

    #: A participant's identity is no longer resolved to a person CAIRN may act
    #: for.
    IDENTITY_REVOKED = "identity_revoked"

    #: The workspace has not granted, or has revoked, transcript access.
    SCOPE_NOT_GRANTED = "scope_not_granted"

    #: The Meet connection is disconnected or revoked.
    CONNECTION_INACTIVE = "connection_inactive"

    #: The announcement does not belong to the subscription, the meeting or the
    #: workspace the row claims. One member, deliberately: telling a caller *which*
    #: of the three mismatched is telling it how to make the next one match.
    REFERENCE_MISMATCH = "reference_mismatch"

    #: The artifact is not a transcript — a recording, audio, video, smart notes,
    #: an attendance report. Refused on the declared type **and** on the MIME
    #: type, and this is the member both refusals report.
    NOT_A_TRANSCRIPT = "not_a_transcript"

    #: A transcript, but larger than CAIRN will download.
    TOO_LARGE = "too_large"

    #: What arrived did not match what was promised, in bytes or in digest.
    CHECKSUM_MISMATCH = "checksum_mismatch"

    #: Google no longer has the artifact it announced.
    ARTIFACT_GONE = "artifact_gone"

    #: The artifact is still there and is not the one that was announced.
    ARTIFACT_CHANGED = "artifact_changed"


def _refusal_values() -> str:
    """The refusal vocabulary as a SQL literal, for the CHECK constraint."""
    return "(" + ", ".join(f"'{member.value}'" for member in GoogleMeetRefusalReason) + ")"


class GoogleMeetOAuthState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One in-flight Google Meet install, identified by an unguessable nonce.

    A twin of :class:`~cairn_api.db.gchat_models.GoogleChatOAuthState`, and a
    separate table rather than a ``provider`` column on that one. The two
    connectors have **separate OAuth clients** (see `config.Settings`), so an
    in-flight state belongs to exactly one of them; sharing a table would make a
    state issued for Chat redeemable at Meet's callback, which is a
    cross-connector replay with no other defence against it.
    """

    __tablename__ = "google_meet_oauth_states"

    #: Which workspace the install was started from. The redirect URI is
    #: registered with Google once and therefore cannot name a workspace, so this
    #: row is the **only** link between the browser coming back and the workspace
    #: that asked — which is why the callback reads the tenant here and never
    #: from the request.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: Who pressed Connect. Checked again on the callback, so a state handed to
    #: (or stolen by) a different person cannot be redeemed — being a member of
    #: the same workspace is not enough.
    initiated_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    #: SHA-256 of the nonce, never the nonce itself.
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: The PKCE ``code_verifier``, stored as issued and deliberately not hashed:
    #: it is a value CAIRN *presents to Google* rather than one it recognises, so
    #: there is no version of this column that is both hashed and usable. What
    #: bounds the exposure instead is lifetime and reach — the row is consumed or
    #: swept inside `oauth.STATE_TTL`, and this table has **no grant** to the
    #: application role at all.
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Stamped the moment the callback claims it, *before* the code is exchanged.
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Which of the two grants this install is for.
    #:
    #: **Written when the state is issued and read on the way back, never
    #: inferred.** Google's callback carries a ``scope`` parameter, and deciding
    #: what a person consented to by reading what Google says they granted is
    #: exactly backwards: the question is what CAIRN asked for and what the person
    #: pressed. A default of ``CONNECTION`` is the safe one — a state whose kind
    #: was somehow lost cannot be redeemed as transcript access.
    requested_grant: Mapped[GoogleMeetGrantKind] = mapped_column(
        Enum(GoogleMeetGrantKind, native_enum=False, length=16, values_callable=_values),
        nullable=False,
        default=GoogleMeetGrantKind.CONNECTION,
        server_default=GoogleMeetGrantKind.CONNECTION.value,
    )

    __table_args__ = (
        Index("ix_google_meet_oauth_states_tenant_id", "tenant_id"),
        Index("ix_google_meet_oauth_states_expires_at", "expires_at"),
    )

    def is_usable(self, *, now: datetime | None = None) -> bool:
        """Whether this state may still be redeemed. Computed, never stored."""
        moment = now or datetime.now(UTC)
        return self.consumed_at is None and self.expires_at > moment

    def __repr__(self) -> str:
        """Identity and lifecycle only — never the hash, never the verifier."""
        return (
            f"GoogleMeetOAuthState(id={self.id!r}, tenant_id={self.tenant_id!r}, "
            f"consumed={self.consumed_at is not None!r})"
        )

    __str__ = __repr__


class GoogleMeetSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One Workspace Events subscription, for one consented meeting.

    **A row here is not a permission.** The permission is the Step 35 capture
    request this points at, and it is re-read — through
    `meetings.guard.permit_collection` — on creation, on every renewal, and again
    inside the transaction that records an inbound receipt. A subscription that
    outlives a withdrawal therefore delivers into a workspace that refuses it,
    and lapses on its own because nothing renews it.

    Kept rather than deleted when a subscription ends: "why did this meeting
    produce nothing" is the question this table exists to answer, and Google has
    destroyed its own copy by then.
    """

    __tablename__ = "google_meet_subscriptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: CASCADE, because a subscription outliving its connection is a lease
    #: attached to no credential — and the next connection would inherit it.
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_connections.id", ondelete="CASCADE"), nullable=False
    )

    #: The Step 35 capture request whose unanimous consent authorises this.
    #:
    #: **Internal, and the only meeting identifier on this table.** There is no
    #: ``external_meeting_ref`` here on purpose: for Google Meet that value is
    #: the joining code, which is a credential. It is read from the permit at the
    #: moment a subscription is created and never written down.
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Google's own resource name for the subscription (``subscriptions/{id}``).
    #: Nullable, because the row exists from the moment a permit is issued and
    #: Google has not been asked yet — that is ``PENDING``, and a placeholder
    #: string would be a lie the renewal sweep would then try to renew.
    #:
    #: Globally unique where present: this is what an inbound push resolves
    #: against, so two rows claiming one subscription would be an event with two
    #: possible tenants.
    subscription_name: Mapped[str | None] = mapped_column(String(160), nullable=True)

    #: When Google will stop delivering without a renewal. The sweep's whole input.
    expire_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    state: Mapped[GoogleMeetSubscriptionState] = mapped_column(
        Enum(
            GoogleMeetSubscriptionState,
            native_enum=False,
            length=16,
            values_callable=_values,
        ),
        nullable=False,
        default=GoogleMeetSubscriptionState.PENDING,
    )

    #: Why it is suspended, errored or expired — as a **category**, never as
    #: Google's message. Google's errors quote the resource that failed, which
    #: for this connector is a meeting space and the authorising person's
    #: address.
    error_category: Mapped[ConnectorErrorCategory | None] = mapped_column(
        Enum(ConnectorErrorCategory, native_enum=False, length=32, values_callable=_values),
        nullable=True,
    )

    #: When the state above was last set. Separate from ``updated_at``, which
    #: moves on every write including a successful renewal.
    state_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: The last time a verified event actually arrived for this subscription.
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # One subscription per meeting. Two would mean two renewal schedules for
        # one consent decision and, when they disagree, a meeting still being
        # subscribed to after the row somebody looked at said it was not.
        UniqueConstraint("meeting_id", name="uq_google_meet_subscriptions_meeting"),
        # Globally unique, not per tenant: an inbound push carries a subscription
        # name and nothing else CAIRN may trust, so this constraint is what makes
        # "which workspace is this for" have exactly one answer.
        UniqueConstraint(
            "subscription_name", name="uq_google_meet_subscriptions_subscription_name"
        ),
        CheckConstraint(
            f"subscription_name IS NULL OR subscription_name ~ '{SUBSCRIPTION_NAME_PATTERN}'",
            name="ck_google_meet_subscriptions_subscription_name_is_a_resource_name",
        ),
        Index("ix_google_meet_subscriptions_tenant_id", "tenant_id"),
        Index("ix_google_meet_subscriptions_connection_id", "connection_id"),
        # The renewal sweep: "which leases lapse soon". State first, because the
        # sweep only ever looks at live ones.
        Index("ix_google_meet_subscriptions_state_expire_time", "state", "expire_time"),
    )

    def __repr__(self) -> str:
        """Internal ids and lifecycle. No meeting ref, no joining code, no Google words."""
        return (
            f"GoogleMeetSubscription(id={self.id!r}, meeting_id={self.meeting_id!r}, "
            f"state={self.state!r})"
        )

    __str__ = __repr__


class GoogleMeetArtifactSignal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Google said a transcript file exists. That is the entire record.

    **Nothing here can be used to fetch anything**, and that is the design rather
    than an omission. The row holds a digest of the artifact's resource name, not
    the name; there is no URI, no file id, no conference record id, no
    participant, no duration and no content. Step 36A subscribes to the
    announcement and stops there — retrieval is a later step with its own
    consent story, and a schema that could hold the pointer is a schema in which
    "we did not fetch it" is a claim about the code rather than about the data.

    The digest exists for one reason: idempotency. Pub/Sub delivers at least
    once and Workspace Events may republish, so the same announcement can arrive
    twice; a stable, non-reversible key makes the second one a no-op without
    keeping the identifier that made it stable.
    """

    __tablename__ = "google_meet_artifact_signals"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: The subscription that delivered it, and through it the connection.
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("google_meet_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The consented meeting. Carried so a later step that *does* retrieve can
    #: re-run the gate against the same request this signal was recorded under.
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[GoogleMeetArtifactKind] = mapped_column(
        Enum(GoogleMeetArtifactKind, native_enum=False, length=16, values_callable=_values),
        nullable=False,
    )

    #: SHA-256, hex, of the artifact resource name Google named. **Never the name
    #: itself.** A Meet transcript resource name embeds the conference record id,
    #: which is a durable handle to a specific meeting; hashing costs nothing and
    #: makes this column useless to anybody who obtains it, including us.
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    #: When CAIRN accepted the announcement. Distinct from ``created_at`` only in
    #: intent, and kept because "when did Google say this existed" is the fact,
    #: while ``created_at`` is when a row happened to be written.
    announced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # One row per announcement per workspace. Tenant-scoped rather than
        # global because the digest is derived from a provider identifier and a
        # global constraint would let one workspace's row silently suppress
        # another's — a cross-tenant side channel for the sake of a narrower
        # index.
        UniqueConstraint(
            "tenant_id", "artifact_digest", name="uq_google_meet_artifact_signals_digest"
        ),
        Index("ix_google_meet_artifact_signals_tenant_id", "tenant_id"),
        Index("ix_google_meet_artifact_signals_meeting", "meeting_id"),
        Index("ix_google_meet_artifact_signals_subscription", "subscription_id"),
    )

    def __repr__(self) -> str:
        """Ids and kind. The digest is not printed — it is still a provider-derived value."""
        return (
            f"GoogleMeetArtifactSignal(id={self.id!r}, meeting_id={self.meeting_id!r}, "
            f"kind={self.kind!r})"
        )

    __str__ = __repr__


class GoogleMeetTranscriptGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One workspace's **separate** authorisation to read transcript files.

    A row here is the answer to a question nobody was asked when they connected
    Google Meet. ``meetings.space.readonly`` authorises a subscription; reading
    the file the platform produced needs ``drive.meet.readonly``, which is a
    **restricted** scope, and folding it into the connection grant would mean a
    workspace acquiring artifact access by pressing a button labelled something
    else.

    So it is its own table rather than a second entry in
    ``source_connections.scopes``. Three consequences follow, and each one is why:

    - The Meet connection can exist with no row here, which is the normal state
      and the state every deployment starts in.
    - Revoking transcript access deletes nothing else. ``revoked_at`` is set, the
      subscriptions keep running, and the connector goes back to recording only
      that a transcript exists.
    - "Has this workspace consented to transcript retrieval" is a query against a
      row somebody's click created, not an inference from a scope string that a
      token response happened to carry.

    **No token lives here.** The refresh token is the connection's, encrypted on
    ``source_connections`` by ``connectors/credentials.py``; this row records the
    consent, not the credential.
    """

    __tablename__ = "google_meet_transcript_grants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: CASCADE: a grant outliving the connection it was authorised on is consent
    #: attached to no credential, and the next connection would inherit it.
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_connections.id", ondelete="CASCADE"), nullable=False
    )

    #: Who pressed the second button. RESTRICT rather than SET NULL: a grant with
    #: nobody's name on it is a grant nobody can be asked about.
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    #: What Google actually granted, sorted. Stored because the equality check ran
    #: against it once, and an operator asking "what does CAIRN hold on this
    #: account" deserves an answer from the database rather than from a constant.
    granted_scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Set when the workspace withdraws transcript access, or when the connection
    #: is disconnected. The row is kept: "transcript access was held between these
    #: dates" is what somebody asks after finding a stored transcript.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: The wording in force when this was granted. A later change to the
    #: explanation does not silently re-authorise anything under the new one.
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)

    #: This grant's **own** refresh token, encrypted, on its own row.
    #:
    #: Not the connection's. Transcript access is authorised on a separate OAuth
    #: client (`config.Settings.google_meet_transcript_client_id`), so the
    #: credential it produces is a different credential with a different scope
    #: set — which is what makes revoking transcript access actually revoke
    #: something rather than set a flag beside a token that still works.
    #:
    #: Leading underscore for the reason `source_connections._secret_ciphertext`
    #: has one: it keeps the column out of `vars()`, a debugger, structlog's dict
    #: rendering and a serialiser somebody points at the model. Reading it is a
    #: function call in `gmeet/artifacts.py` — an import, a call, and a line in a
    #: diff somebody can review.
    _secret_ciphertext: Mapped[str | None] = mapped_column(
        "secret_ciphertext", String(2048), nullable=True
    )

    __table_args__ = (
        # One row per connection outright. Two would be two answers to one
        # question, and the code would read whichever the query ordered first.
        UniqueConstraint("connection_id", name="uq_google_meet_transcript_grants_connection"),
        Index("ix_google_meet_transcript_grants_tenant_id", "tenant_id"),
    )

    @property
    def is_granted(self) -> bool:
        """Whether transcript access is held right now. Computed, never stored.

        A boolean column would be a value that can disagree with ``revoked_at``,
        and the disagreement would be discovered by a retrieval that should not
        have happened.
        """
        return self.revoked_at is None

    def __repr__(self) -> str:
        """Ids and lifecycle. No scopes, no address, no token."""
        return (
            f"GoogleMeetTranscriptGrant(id={self.id!r}, tenant_id={self.tenant_id!r}, "
            f"revoked={self.revoked_at is not None!r})"
        )

    __str__ = __repr__


class GoogleMeetTranscriptArtifact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One announced transcript, its provenance, and what happened to it.

    **Immutable provenance, mutable lifecycle.** The provenance columns —
    provider, meeting, conference and artifact digests, generated time, retrieved
    time, checksum, consent-policy version — are written once and never edited;
    what moves is the state, the attempt counter and the retention stamps. That
    split is what lets a withdrawal after a completed retrieval stop future
    processing without rewriting history: it sets ``withdrawn_at`` and leaves every
    fact about what was already collected exactly where it was.

    **The artifact reference is encrypted, and it is the only reversible provider
    identifier in this schema.** Step 36A stored a digest and nothing else, because
    it never needed to name the artifact again. Retrieval does — a download
    requires a resource name, a retry requires it a second time — and a Meet
    transcript resource name embeds the conference record id, which is a durable
    handle to one specific meeting. So it is encrypted with the connector key, and
    the digest is kept beside it as the idempotency key, so every query that only
    needs to *recognise* an artifact decrypts nothing.

    **There is no content column here.** The bytes live in
    :class:`GoogleMeetTranscriptRaw`, which has its own table and no grant, so
    deleting the transcript at the end of its retention period does not delete the
    record that it existed.
    """

    __tablename__ = "google_meet_transcript_artifacts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: The announcement this came from. One artifact per announcement, enforced
    #: below: a redelivered or republished event must not produce a second
    #: download of the same file.
    signal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("google_meet_artifact_signals.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The lease that delivered it, and through it the connection whose credential
    #: a download uses. Re-checked against the announcement on every retrieval.
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("google_meet_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The Step 35 capture request whose unanimous consent authorises this, and the
    #: row the gate is re-run against before every retrieval action.
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: ``google_meet``. A literal column rather than an implied fact, because
    #: provenance that has to be inferred from which table a row is in stops being
    #: provenance the moment a second provider arrives.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    #: Transcript. The CHECK below is what makes "no recordings" a property of the
    #: data: there is no value this column may hold that names one.
    kind: Mapped[GoogleMeetArtifactKind] = mapped_column(
        Enum(GoogleMeetArtifactKind, native_enum=False, length=16, values_callable=_values),
        nullable=False,
    )

    #: SHA-256, hex, of the artifact resource name — the same value
    #: `GoogleMeetArtifactSignal.artifact_digest` holds, restated so the two can be
    #: compared without decrypting anything. A mismatch is a signal and an artifact
    #: wired to each other by mistake.
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    #: SHA-256, hex, of the ``conferenceRecords/{c}`` prefix. Provenance: which
    #: conference this transcript belonged to, in a form that identifies nothing to
    #: anybody who obtains the row.
    conference_digest: Mapped[str] = mapped_column(String(64), nullable=False)

    #: The resource name, encrypted with the connector key. Never selected into a
    #: response, never logged, read only by the download path.
    artifact_reference_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)

    #: When the platform produced the artifact — the source timestamp reference.
    #: Nullable, because Google does not always carry it on the announcement and a
    #: fabricated time is worse than an absent one.
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: When CAIRN accepted the announcement.
    announced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: When the bytes were stored. The other half of the provenance pair: an
    #: artifact generated on Tuesday and retrieved on Friday is a different fact
    #: from one retrieved as it appeared.
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: The consent wording in force on the capture request, copied rather than
    #: joined: the whole point of a policy version is that it pins what somebody
    #: agreed to, and a join would report today's.
    consent_policy_version: Mapped[str] = mapped_column(String(32), nullable=False)

    state: Mapped[GoogleMeetTranscriptState] = mapped_column(
        Enum(GoogleMeetTranscriptState, native_enum=False, length=16, values_callable=_values),
        nullable=False,
        default=GoogleMeetTranscriptState.ANNOUNCED,
    )

    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Why nothing was collected, from the closed vocabulary. Null while a row is
    #: still in play, and on a row that succeeded.
    refusal_reason: Mapped[GoogleMeetRefusalReason | None] = mapped_column(
        Enum(GoogleMeetRefusalReason, native_enum=False, length=32, values_callable=_values),
        nullable=True,
    )

    #: A category, never Google's message. Google's Drive errors quote the file
    #: that failed, which here is the transcript of a specific meeting.
    error_category: Mapped[ConnectorErrorCategory | None] = mapped_column(
        Enum(ConnectorErrorCategory, native_enum=False, length=32, values_callable=_values),
        nullable=True,
    )

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: When a failed retrieval becomes retryable. Null means "not scheduled", which
    #: is what a terminal state leaves behind — a dead-lettered row carrying a retry
    #: time is a row something will eventually pick up.
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: The MIME type of what was actually downloaded, from the allowlist. Stored so
    #: "what is in the raw store" is answerable without opening it.
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)

    content_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: SHA-256, hex, of the retrieved bytes, computed over the stream as it
    #: arrives, so it describes what was stored rather than what was expected.
    content_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: When the raw bytes may be deleted. Derived from the workspace's retention
    #: period at the moment of storage, and stored rather than computed on read, so
    #: that shortening the period later cannot retroactively claim a transcript was
    #: already due for deletion when it was not.
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    #: When the raw bytes were actually deleted. The provenance row stays.
    raw_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: When consent stopped, if it stopped **after** this artifact was retrieved.
    #: Stops every future processing path and deletes nothing on its own: the
    #: documented retention policy decides when the bytes go, and a withdrawal that
    #: silently rewrote the record would destroy the evidence that the withdrawal
    #: was honoured.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # One artifact per announcement. The announcement table is already
        # idempotent on the digest, so this is the second lock on the same door: a
        # redelivery cannot produce a second download.
        UniqueConstraint("signal_id", name="uq_google_meet_transcript_artifacts_signal"),
        # And one per artifact per workspace, tenant-scoped for the reason the
        # signal table's constraint is: a global one would let one workspace's row
        # silently suppress another's.
        UniqueConstraint(
            "tenant_id", "artifact_digest", name="uq_google_meet_transcript_artifacts_digest"
        ),
        CheckConstraint(
            "artifact_digest ~ '^[0-9a-f]{64}$'",
            name="artifact_digest_shape",
        ),
        CheckConstraint(
            "conference_digest ~ '^[0-9a-f]{64}$'",
            name="conference_digest_shape",
        ),
        # The column that makes "transcripts only" true of the data. A recording,
        # audio, video or smart-notes row cannot be written here at all.
        CheckConstraint("kind = 'transcript'", name="kind_is_transcript"),
        CheckConstraint("provider = 'google_meet'", name="provider_is_meet"),
        CheckConstraint(
            "content_bytes IS NULL OR content_bytes >= 0",
            name="content_bytes_non_negative",
        ),
        CheckConstraint(
            "content_checksum IS NULL OR content_checksum ~ '^[0-9a-f]{64}$'",
            name="content_checksum_shape",
        ),
        Index("ix_google_meet_transcript_artifacts_tenant_id", "tenant_id"),
        Index("ix_google_meet_transcript_artifacts_meeting", "meeting_id"),
        # The retrieval pass: "what is waiting, and what is retryable now".
        Index("ix_google_meet_transcript_artifacts_state_next_attempt", "state", "next_attempt_at"),
        # The retention sweep.
        Index(
            "ix_google_meet_transcript_artifacts_retention", "retention_expires_at", "raw_purged_at"
        ),
    )

    def __repr__(self) -> str:
        """Ids and lifecycle. No reference, no digest, no checksum, no Google words."""
        return (
            f"GoogleMeetTranscriptArtifact(id={self.id!r}, meeting_id={self.meeting_id!r}, "
            f"state={self.state!r})"
        )

    __str__ = __repr__


class GoogleMeetTranscriptRaw(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The transcript itself, encrypted, in the one table nothing may read.

    **A separate table for one reason: so that deletion is possible.** Retention
    ends and these rows go; the provenance beside them stays, and a workspace can
    still be told that a transcript existed, was collected, and has since been
    deleted. A content column on the artifact row would force the same deletion to
    erase the record of the collection, which is not a smaller version of honesty.

    **No grant to the application role at all**, which is stronger than every other
    table in this connector. Every write is platform-side — the retrieval worker
    resolves a subscription to a workspace before any tenant context could exist —
    and there is no product surface that reads it: at this step customers see
    availability and status, never content. A privilege nothing uses is the one an
    injection gets to use first, and what it would reach here is a verbatim record
    of what people said in a meeting.

    Encrypted with the same connector key as every stored credential, through the
    same reviewed path, so a deployment that has not configured one refuses to
    start rather than writing transcripts in the clear.
    """

    __tablename__ = "google_meet_transcript_raw"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    #: One blob per artifact, and CASCADE. A transcript whose provenance row was
    #: deleted is a transcript nobody can say anything about.
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("google_meet_transcript_artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Fernet ciphertext. There is deliberately no plaintext accessor on this
    #: model: reading it is a function call in `gmeet/artifacts.py`, which is what
    #: makes "where is a transcript decrypted" answerable with grep.
    content_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)

    #: Of the plaintext, so integrity can be rechecked without a second copy.
    content_checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    content_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("artifact_id", name="uq_google_meet_transcript_raw_artifact"),
        CheckConstraint(
            "content_checksum ~ '^[0-9a-f]{64}$'",
            name="checksum_shape",
        ),
        Index("ix_google_meet_transcript_raw_tenant_id", "tenant_id"),
    )

    def __repr__(self) -> str:
        """Ids and size. Never the ciphertext, never the checksum, never a byte of it."""
        return (
            f"GoogleMeetTranscriptRaw(id={self.id!r}, artifact_id={self.artifact_id!r}, "
            f"bytes={self.content_bytes!r})"
        )

    __str__ = __repr__
