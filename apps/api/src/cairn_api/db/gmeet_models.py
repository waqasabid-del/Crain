"""The three tables the Google Meet connector adds, and what is missing from them.

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

**There is no transcript column, no artifact URI and no content column.**
:class:`GoogleMeetArtifactSignal` records that Google said a transcript file
exists — a fact with a timestamp — and identifies it only by digest. CAIRN does
not fetch it, and this schema is what makes "does not fetch it" checkable rather
than promised: there is nowhere to put the thing you would need in order to.

Nothing here stores a credential (``connectors/credentials.py`` owns that), an
email address, a meeting title, or a participant.
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
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
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
