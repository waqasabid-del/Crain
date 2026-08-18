"""Asking every participant, and being unable to proceed until they all say yes.

**Nothing here records a meeting.** CAIRN never joins a meeting as a bot or a
participant (md/03 §4.2) and never produces a recording or a transcript. The only
artifact it may ever ingest is one the meeting platform itself created through
its own flow — and this module is the gate that decides whether it may ask for
even that.

**Why the strictest standard is the default rather than a setting.** Thirteen US
states require all-party consent (md/03 §3.1), the strictest applicable law
generally governs a multi-state call, and CAIRN's customers are distributed
teams — so the strict case is the ordinary case, not the exception. In those
states an employer *cannot* mandate AI recording over an employee's objection,
which is why there is no workspace-level toggle in this schema and no column an
administrator could set to mean "everyone agrees". The cost of the strict default
is a slower flow; the cost of error is criminal exposure.

**Consent here is an operating safeguard, not the EU lawful basis.** GDPR treats
employee consent as invalid in an employment context because of the power
imbalance; CAIRN's basis is legitimate interest with a documented assessment
(md/03 §3.3, md/05 §B.2.1). These records make that interest proportionate and
demonstrable. They are deliberately *not* described anywhere in the product as
the thing that makes processing lawful.

**No meeting title is stored, ever.** A calendar title is frequently the most
sensitive string in a workspace — "Priya performance review", "layoff planning",
"Dana 1:1 re: PIP" — and a participant does not need it to recognise a meeting
they were in. What identifies a request on screen is its time window and the
purpose its requester typed. That is a deliberate loss of convenience: a title
column would be read by everyone who can see the request, and the request is
seen by every participant.

**What can never be built on these tables**, restated because this is where a
well-meaning engineer would add it: talk time, participation scores, sentiment,
coaching, attendance ranking, or any per-person meeting analytic (md/03 §5.4,
md/05 §B.3.3). There is no duration column, no speaking column, and no attendance
outcome — only whether somebody agreed to be captured, which is a permission and
not a measurement.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Final

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: The consent wording a decision was made against.
#:
#: Stored on every decision, and compared on every eligibility check. If the
#: explanation of what CAIRN may receive changes, decisions taken against the old
#: wording stop counting — somebody who agreed to one thing has not agreed to a
#: different one, and silently carrying their answer forward would be the exact
#: move this whole module exists to prevent.
CONSENT_POLICY_VERSION: Final = "2026-08-18.1"

#: How long a decision survives a change to the meeting's time.
#:
#: Rescheduling by minutes is the same meeting; moving it a week is a different
#: commitment, and consent given for one afternoon is not consent for whenever it
#: eventually happens.
RESCHEDULE_TOLERANCE_MINUTES: Final = 60


class MeetingProvider(enum.StrEnum):
    """Which platform produced the meeting.

    Declared now and implemented later, so the column, its CHECK constraint and
    the eligibility gate exist before any provider code does — the order that
    makes it impossible to ship a connector that forgot to ask.
    """

    GOOGLE_MEET = "google_meet"
    ZOOM = "zoom"


class CaptureState(enum.StrEnum):
    """Where a capture request stands.

    `ELIGIBLE` is computed, never asserted: it is written only by the gate, and
    only when every currently expected participant holds a live acceptance for
    the current policy version. Nothing else in the product may set it.
    """

    #: Asked for; at least one participant has not yet agreed.
    PENDING = "pending"

    #: Every expected participant has agreed, under the current policy.
    ELIGIBLE = "eligible"

    #: Somebody declined or withdrew. Terminal for this request — a refusal is
    #: not a prompt to ask again, and re-asking is a new request somebody has to
    #: justify.
    REFUSED = "refused"

    #: The meeting's window passed without every agreement in place.
    EXPIRED = "expired"

    #: The requester called it off before anything was collected.
    CANCELLED = "cancelled"

    #: A later step retrieved the platform's artifact under this permission.
    COMPLETED = "completed"


class ParticipantStatus(enum.StrEnum):
    """Whether this person is currently expected in the meeting."""

    EXPECTED = "expected"

    #: No longer on the invitation. Kept rather than deleted: "who was asked?"
    #: must stay answerable after somebody is removed, and a deleted row would
    #: make a shrinking guest list look like a meeting that never had one.
    REMOVED = "removed"


class ParticipantSource(enum.StrEnum):
    """How CAIRN learnt this person was expected.

    Recorded because it bounds what the record is evidence *of*. A calendar told
    us; a person typed it. Neither is a consent, and the column exists partly so
    that no future reader mistakes a calendar invitation for one.
    """

    CALENDAR = "calendar"
    MANUAL = "manual"


class ConsentDecision(enum.StrEnum):
    """One person's answer.

    There is no `assumed`, `implied`, `inherited` or `default` member, and no
    boolean that could be initialised to true. Silence is `PENDING` forever —
    it never ages into agreement.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"

    #: Agreed, then changed their mind before anything was collected. Distinct
    #: from `DECLINED` because the product promises withdrawal is possible, and
    #: a record that cannot tell the two apart cannot demonstrate it.
    WITHDRAWN = "withdrawn"

    #: The meeting moved, or the wording changed. Not a refusal — the person has
    #: simply not answered *this* question, and must be asked again.
    EXPIRED = "expired"


class MeetingCaptureRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A request to be allowed to collect one meeting's platform artifact."""

    __tablename__ = "meeting_capture_requests"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )

    provider: Mapped[MeetingProvider] = mapped_column(
        Enum(
            MeetingProvider,
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    #: The platform's own stable id for the meeting. **Never a title and never a
    #: join URL**: a title is often the most sensitive string in a workspace, and
    #: a join link is a credential.
    external_meeting_ref: Mapped[str] = mapped_column(String(255), nullable=False)

    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: Why, in the requester's own words, shown to every participant before they
    #: answer. Bounded, and the only free text in this module — a person deciding
    #: whether to be recorded is entitled to know what it is for, and a purpose
    #: nobody had to write is a request nobody had to justify.
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)

    #: The wording in force when the request was made. A later change to the
    #: explanation invalidates decisions taken against this one.
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)

    state: Mapped[CaptureState] = mapped_column(
        Enum(
            CaptureState,
            native_enum=False,
            length=16,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=CaptureState.PENDING,
    )

    state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        # One live request per meeting, per workspace. Two requests for one
        # meeting would be two different sets of answers to the same question.
        Index(
            "uq_meeting_capture_live",
            "tenant_id",
            "provider",
            "external_meeting_ref",
            unique=True,
            postgresql_where=text("state NOT IN ('cancelled', 'refused', 'expired')"),
        ),
        Index("ix_meeting_capture_tenant", "tenant_id"),
    )


class MeetingParticipant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person expected in the meeting, and how CAIRN knows who they are."""

    __tablename__ = "meeting_participants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The CAIRN person, when the identity is resolved. **Null is a real state**,
    #: and a blocking one: an unresolved participant is somebody CAIRN cannot ask,
    #: so the meeting cannot become eligible while one exists. That is the honest
    #: consequence of not guessing — see Step 34.
    person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("people.id", ondelete="CASCADE"), nullable=True
    )

    #: The platform's own attendee id, kept only so the same person is not added
    #: twice. **Internal**, exactly as `fact_people.provider_account_id` is: it is
    #: a private provider identifier and never reaches a response, a log or a
    #: screen. Identity is never established by matching a display name, a
    #: calendar title or transcript text.
    provider_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ParticipantStatus] = mapped_column(
        Enum(
            ParticipantStatus,
            native_enum=False,
            length=16,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ParticipantStatus.EXPECTED,
    )

    source: Mapped[ParticipantSource] = mapped_column(
        Enum(
            ParticipantSource,
            native_enum=False,
            length=16,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # No duplicate person on one meeting, and no duplicate provider attendee.
        # Partial on each, because either identifier may legitimately be null.
        Index(
            "uq_meeting_participant_person",
            "meeting_id",
            "person_id",
            unique=True,
            postgresql_where=text("person_id IS NOT NULL"),
        ),
        Index(
            "uq_meeting_participant_account",
            "meeting_id",
            "provider_account_id",
            unique=True,
            postgresql_where=text("provider_account_id IS NOT NULL"),
        ),
        Index("ix_meeting_participant_meeting", "meeting_id"),
        Index("ix_meeting_participant_tenant", "tenant_id"),
    )


class MeetingConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One participant's answer, appended rather than edited.

    **Append-only.** Changing your mind writes a new row and supersedes the old
    one; nothing is updated in place and nothing is deleted. The history is the
    product's evidence that withdrawal was possible and honoured, and an
    `UPDATE`-in-place model cannot produce it. There is no DELETE grant.
    """

    __tablename__ = "meeting_consents"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_capture_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meeting_participants.id", ondelete="CASCADE"),
        nullable=False,
    )

    decision: Mapped[ConsentDecision] = mapped_column(
        Enum(
            ConsentDecision,
            native_enum=False,
            length=16,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    #: When the person actually answered. Null while pending — an unanswered
    #: request has no decision time, and defaulting it to "now" would make
    #: silence look like a considered answer.
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: The account that answered. **Must be the participant's own**: there is no
    #: code path and no route by which an administrator can answer for somebody
    #: else, which md/03 §3.1 requires — in all-party states an employer cannot
    #: mandate recording over an employee's objection, so a consent an employer
    #: could write would be worth nothing.
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)

    #: When a later decision replaced this one. Null on the live row.
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # **Exactly one live decision per participant per meeting.** Enforced by
        # the database, because the case that breaks a handler is two answers
        # arriving together — and the answer that loses a race must not be the
        # one the gate happens to read.
        Index(
            "uq_meeting_consent_live",
            "meeting_id",
            "participant_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_meeting_consent_meeting", "meeting_id"),
        Index("ix_meeting_consent_tenant", "tenant_id"),
    )
