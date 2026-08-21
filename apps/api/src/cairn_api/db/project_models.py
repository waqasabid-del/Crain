"""The project layer: a real entity behind the string on a citation.

Until this module, a "project" was `fact_sources.project` — a nullable string a
model wrote on a citation. The dashboard needs honest data behind every card,
so a project becomes: a named entity with a declared state, an auditable
membership, and an explicit claim over the source strings that link evidence to
it. The raw string on the citation is never touched — it is provenance, and the
mapping resolves it rather than replacing it.

**Membership references ``Person``, not ``User``, deliberately.** Work is done
by people, and a contractor who never signs in has a ``Person`` and no ``User``
(identity_models.py). Facts already attach to ``Person`` via ``fact_people``;
project membership is context about the same work, so it lives on the same
axis. The *actor* columns (``added_by_user_id`` and friends) reference ``User``
because performing the action requires a session.

**Membership is context, never assignment.** A row here says "this person is
part of this project's context" — it carries who added them, when, and a role
*they* would recognise ("Frontend"). It does not carry, and must never grow,
any activity column: a per-member count on a membership row is the seed of a
per-person dashboard, which is the exact surface md/05 §B.3.3 forbids. A test
greps the response models for ranking vocabulary and pins the member response
to an allow-listed field set.
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
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _enum_values(enum_type: type[enum.StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class ProjectState(enum.StrEnum):
    """The state a human declared, never one the system inferred.

    ``UNKNOWN`` is the default and the honest one: a state nobody declared is
    unknown, not "active because commits happened" — inferring state from
    activity would make the state field a derived judgement about the people
    doing the activity. The one write path stamps who declared it and when,
    the same shape as a person's self-declared capacity.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named piece of work within one workspace.

    Archived, never deleted: ``archived_at`` closes it, its memberships and
    claimed strings stay readable, and the facts citing its strings remain
    cited — an archived project is history, and history stays answerable.
    """

    __tablename__ = "projects"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: One or two sentences of what this work is for. Display text, never parsed.
    purpose: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: See `ProjectState` — declared by an authorized human, never inferred.
    state: Mapped[ProjectState] = mapped_column(
        Enum(ProjectState, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=ProjectState.UNKNOWN,
        server_default=ProjectState.UNKNOWN.value,
    )

    #: Who declared the current state, and when. Null while `unknown` from
    #: backfill — nobody declared that, and the columns say so.
    state_declared_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    state_declared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    source_claims: Mapped[list[ProjectSource]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_projects_tenant_id", "tenant_id"),
        # Case-insensitive uniqueness per workspace, the tenants-slug idiom:
        # "Payments" and "payments" as two projects is a filing error waiting
        # to be cited.
        Index(
            "uq_projects_tenant_name_lower",
            "tenant_id",
            text("lower(name)"),
            unique=True,
        ),
    )


class ProjectMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person's place in a project's context. Auditable, history-preserving.

    No silent membership: every row carries who added it and when, removal sets
    ``removed_at``/``removed_by_user_id`` rather than deleting, and the API
    returns the history — so "who was on this, and who put them there?" is
    answerable from the data. NO activity columns, ever; see the module
    docstring.
    """

    __tablename__ = "project_members"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The Person, not the User — see the module docstring.
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: What the person does here, in words they would use themselves
    #: ("Frontend", "Design"). Free text, display only, never matched on.
    project_role: Mapped[str | None] = mapped_column(String(100), nullable=True)

    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Removal closes the row instead of deleting it. A shrinking member list
    #: must not read as a project that never had the person.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    project: Mapped[Project] = relationship(back_populates="members")

    __table_args__ = (
        # One *active* membership per person per project; a removed row does
        # not block re-adding, which is why the index is partial.
        Index(
            "uq_project_members_active",
            "project_id",
            "person_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_project_members_tenant_id", "tenant_id"),
        Index("ix_project_members_person_id", "person_id"),
    )


class ProjectSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A project's claim over one raw source string.

    ``value`` matches ``fact_sources.project`` verbatim — the string the
    pipeline wrote on citations (a repo name, most often). Linkage is resolved
    *through this mapping at read time*, never denormalised onto the fact rows:
    a claim made today reaches every fact that ever carried the string, and a
    released claim strands nothing, because there is exactly one copy of the
    linkage. The raw string on each citation is provenance and stays put.

    Unique per (tenant, value): one claimant per string, so resolution is
    deterministic and two projects can never both present the same evidence as
    their own.
    """

    __tablename__ = "project_sources"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: The exact string as it appears on citations. Same length as its column.
    value: Mapped[str] = mapped_column(String(200), nullable=False)

    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    project: Mapped[Project] = relationship(back_populates="source_claims")

    __table_args__ = (
        UniqueConstraint("tenant_id", "value", name="uq_project_sources_tenant_value"),
        Index("ix_project_sources_tenant_id", "tenant_id"),
        Index("ix_project_sources_project_id", "project_id"),
    )
