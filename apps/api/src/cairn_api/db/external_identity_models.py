"""One provider account, bound to one CAIRN person, on evidence a reader can check.

This table answers a single question — *whose activity is this?* — for GitHub,
Slack and Google Chat alike, and it is built so that the wrong answer is hard to
express rather than merely discouraged.

**The existing `identities` table is not this table, and merging them would be a
mistake.** An `Identity` is a *claim about an identifier* discovered by
inference: a commit arrives, its author email becomes a `PROPOSED` claim, and the
person may correct it later. That is the right shape for reconciling handles
*within* the source that produced them. It is the wrong shape for deciding that
a Slack account and a GitHub account are the same human, because the evidence for
that is categorically different: nothing in a Slack message is evidence about a
GitHub account. So `external_identities` never carries a proposal. A row exists
only when one of two things has happened, and both are named on the row itself.

**The two ways in, and there is no third.**

- `VERIFIED_EMAIL_MATCH` — the provider states an address, the provider states
  that it verified that address, and it equals the verified address of a signed-in
  CAIRN user in this workspace. Every clause is load-bearing. An address a
  provider merely *stores* is whatever the account holder typed; an address CAIRN
  has not verified is whatever the person typed here. Matching two unverified
  strings is matching two claims, not two people.
- `SELF_CONFIRMED` — the person signed in and said "that account is mine". The
  authenticated session is the evidence, and it is the only evidence that needs
  no provider cooperation at all.

**What can never link a person, stated as a closed list because a reader is
entitled to hold the product to it:** a display name, a similar display name, an
avatar, writing style, message content, an organisation chart, a role title, a
shared channel, working hours, or any model output. There is deliberately no
enum member such as `SUGGESTED` or `INFERRED` for a future author to reach for —
adding one is a schema migration and a conversation, which is the point.

**Unresolved is a first-class answer.** Activity whose provider account matches
no row here stays attributed to the provider account and to nobody. The tempting
alternative — attach it to the closest match — is how one person's work silently
becomes part of another person's record, and md/05 §B.2.3 makes that record the
person's own. A blank is honest; a plausible wrong name is not.

**Revocation preserves evidence.** Unlinking sets `revoked_at` and a reason and
keeps the row. Nothing is deleted, no historic provenance is rewritten, and the
event's provider actor id — recorded at ingestion, never derived from here —
still says exactly what arrived. What changes is who CAIRN currently believes
that account belongs to, which is the only thing that was ever a belief.

**Ownership is exclusive while it is live.** A partial unique index enforces one
active person per provider account per workspace, so a second claim on an
account somebody already holds is refused by the database rather than by a
handler somebody may forget to write. Revoked rows are excluded from that index,
so an account genuinely changing hands is possible — but only through an
explicit revocation that leaves its reason behind.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

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
from cairn_api.db.connector_models import ConnectorProvider


class IdentityVerification(enum.StrEnum):
    """How CAIRN came to believe this account belongs to this person.

    Stored rather than inferred, because "how do you know?" is the question the
    Trust Center has to answer in the person's own words, and reconstructing it
    later from timestamps would be a guess about a guess.
    """

    #: The provider confirmed an address it had verified, and it equalled the
    #: verified address of a CAIRN account in this workspace. Both verifications
    #: are required: either one alone compares a string to a claim.
    VERIFIED_EMAIL_MATCH = "verified_email_match"

    #: The person signed in and confirmed the account is theirs. Needs no
    #: provider cooperation, and is the only route available when a provider
    #: gives CAIRN no verified address at all — which is the common case.
    SELF_CONFIRMED = "self_confirmed"


class IdentityLinkState(enum.StrEnum):
    """Where this link stands now.

    Deliberately not a boolean. "Linked / not linked" cannot distinguish an
    account nobody has claimed from one somebody withdrew, and those need
    different words on screen and different behaviour in the pipeline.
    """

    #: Live. Activity from this provider account is attributed to this person.
    ACTIVE = "active"

    #: The person withdrew it, or an account changed hands. Attribution stops at
    #: once; the row, its reason and every fact it ever produced remain.
    REVOKED = "revoked"

    #: Somebody says this is wrong and it has not been settled. Attribution stops
    #: while it is disputed — the cost of pausing is a gap, and the cost of
    #: continuing is attributing work to someone who says it is not theirs.
    DISPUTED = "disputed"


class ExternalIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One provider account, bound to one person, with its evidence attached."""

    __tablename__ = "external_identities"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: `native_enum=False` with a CHECK constraint, matching `source_connections`
    #: exactly. A second spelling of the same concept — a Postgres enum here and
    #: a checked string there — would let the two tables disagree about what a
    #: provider is, and the disagreement would surface as a row that cannot be
    #: joined rather than as an error anybody could read.
    provider: Mapped[ConnectorProvider] = mapped_column(
        Enum(
            ConnectorProvider,
            native_enum=False,
            length=32,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    #: The provider's own stable id for the account — a GitHub node id, a Slack
    #: user id, a Google Chat member name. **Never a display name and never a
    #: handle**: both are renameable, and a permission keyed on a renameable
    #: string is silently granted or revoked by a rename.
    provider_account_id: Mapped[str] = mapped_column(String(255), nullable=False)

    #: The address the provider both supplied *and* stated it had verified, kept
    #: only when it was the evidence for the link. Null for every self-confirmed
    #: row: storing an address that proved nothing would be collecting a
    #: personal identifier for no purpose, which md/05 forbids and which would
    #: also make this column look like evidence to the next reader.
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    verification: Mapped[IdentityVerification] = mapped_column(
        Enum(
            IdentityVerification,
            name="identity_verification",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    state: Mapped[IdentityLinkState] = mapped_column(
        Enum(
            IdentityLinkState,
            name="identity_link_state",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=IdentityLinkState.ACTIVE,
    )

    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    #: Who caused the link. Always the person themselves or the system; there is
    #: no code path that lets an administrator write another member's link, and
    #: `SET NULL` keeps the row's history readable after an account is deleted.
    linked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Why, in the product's own bounded words rather than free prose from a
    #: provider. Read by a person looking at their own record, so it must never
    #: quote a third party's error text.
    revoked_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # **One live owner per provider account, per workspace.** Partial on
        # `state = 'active'` so a revoked link does not block an account that
        # genuinely moved to a new person — while an account somebody currently
        # holds cannot be claimed by a second person at all. Enforced here rather
        # than in a service, because the race between two simultaneous confirms
        # is decided in the database or not at all.
        Index(
            "uq_external_identities_live_account",
            "tenant_id",
            "provider",
            "provider_account_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
        ),
        Index("ix_external_identities_person_id", "person_id"),
        Index("ix_external_identities_tenant_id", "tenant_id"),
    )
