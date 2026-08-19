"""The identity graph. Two tables: a ``Person`` is a human (or bot); an
``Identity`` is a claim that a handle belongs to one. The system proposes, the
person confirms (md/01 §5.3, md/05) — never asserted as fact on a string match
alone. A person is not a user: a contractor who never signs in still has a
``Person`` and no ``User``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _enum_values(enum_type: type[enum.StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class PersonKind(enum.StrEnum):
    """Bots get records too: retained as context, excluded from attribution."""

    HUMAN = "human"
    BOT = "bot"

    #: Agent-assisted work is context on the work, not a judgement (md/01 §5.4).
    AGENT = "agent"


class IdentityKind(enum.StrEnum):
    """What sort of identifier a claim carries."""

    EMAIL = "email"
    GITHUB_LOGIN = "github_login"


class IdentityStatus(enum.StrEnum):
    """How much the link is trusted."""

    #: Inferred automatically. Used for attribution, and visible to the person
    #: as something they can correct.
    PROPOSED = "proposed"

    #: A person confirmed this identity is theirs.
    CONFIRMED = "confirmed"

    #: Retained — a deleted rejection is re-proposed by the next commit.
    REJECTED = "rejected"


class PersonCapacity(enum.StrEnum):
    """What a person says about their own availability. Self-declared only.

    Nobody infers this, computes it, or sets it for somebody else - the one
    write path is the owner-of-record endpoint, and a test greps that this
    stays true. There is deliberately NO history table behind it: a capacity
    timeline is a monitoring log wearing a scarf, and "current state, stated by
    the person, with when they said it" is the entire schema so that nothing
    can be trended, compared, or reviewed later.
    """

    OPEN_TO_WORK = "open_to_work"
    AT_CAPACITY = "at_capacity"
    NOT_STATED = "not_stated"


class Person(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A contributor within one workspace."""

    __tablename__ = "people"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Display only, never matched on.
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    kind: Mapped[PersonKind] = mapped_column(
        Enum(PersonKind, name="person_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PersonKind.HUMAN,
    )

    #: Self-declared availability. See `PersonCapacity` - the docstring there
    #: is load-bearing, especially the sentence about the history table that
    #: does not exist.
    capacity: Mapped[PersonCapacity] = mapped_column(
        Enum(PersonCapacity, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=PersonCapacity.NOT_STATED,
        server_default=PersonCapacity.NOT_STATED.value,
    )

    #: When the person themselves stated it. Null while `not_stated`.
    capacity_stated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    identities: Mapped[list[Identity]] = relationship(
        back_populates="person",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_people_tenant_id", "tenant_id"),
        Index("ix_people_user_id", "user_id"),
    )


class Identity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A claim that one identifier belongs to one person."""

    __tablename__ = "identities"

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

    kind: Mapped[IdentityKind] = mapped_column(
        Enum(IdentityKind, name="identity_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    #: Normalised (lower-cased, trimmed).
    value: Mapped[str] = mapped_column(String(320), nullable=False)

    status: Mapped[IdentityStatus] = mapped_column(
        Enum(
            IdentityStatus,
            name="identity_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=IdentityStatus.PROPOSED,
    )

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    person: Mapped[Person] = relationship(back_populates="identities")

    __table_args__ = (
        # Scoped per tenant, not globally.
        UniqueConstraint("tenant_id", "kind", "value", name="uq_identities_tenant_kind_value"),
        Index("ix_identities_person_id", "person_id"),
        Index("ix_identities_tenant_id", "tenant_id"),
    )
