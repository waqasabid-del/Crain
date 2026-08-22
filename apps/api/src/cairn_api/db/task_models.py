"""Tasks: CAIRN's work-tracking layer. A board, never a scoreboard.

A task is a unit of work inside one project: a title, a workflow state, a
priority, maybe an assignee and a due date. The workflow is deliberately small
and the transitions are a closed table enforced at the API — a board whose
columns can be skipped is a board whose columns mean nothing.

**Assignment references ``Person``, not ``User``**, the project-membership
idiom (project_models.py): work is done by people, and a contractor who never
signs in still gets assigned tasks. The *actor* columns — who created a task,
who performed an audited change — reference ``User``, because performing an
action requires a session. ``assignee_person_id`` is nullable because
unassigned is a real state, not an error: a task waiting for someone to pick
it up must not be forced onto a person to exist.

**The audit is categorical, never narrative.** ``TaskEvent`` records *that*
a title changed, never the old title; *that* a task was reassigned, never from
whom to whom. The only structured payload is ``from_state``/``to_state`` on a
state change, because the transition table and the review-handoff rule are
enforced by reading it back. There is no free-text payload column, so an
identifier or a judgement has nowhere to land — the projects/audit.py
signature-is-the-guarantee idea, applied to rows.

**Nothing here measures a person.** Events are never exposed ordered or
aggregated per person; task lists order by creation, never by activity; and no
model in this module carries a count, a total, or a last-active anything. A
test greps the vocabulary and pins the payload shapes, because the failure
mode is additive — a "completed by" tally beside a name is one careless
commit away from a leaderboard (md/05 §B.3.3).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from cairn_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _enum_values(enum_type: type[enum.StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class TaskState(enum.StrEnum):
    """The workflow columns. Five, closed, and crossed only along the legal
    transitions the router enforces.

    ``DONE`` is terminal: a wrongly-closed task is archived and a new one
    created, so the record of what was reviewed and shipped is never rewritten
    in place. Review is a real step — moving in_review→done requires a
    *different* user from the one who sent it to review.
    """

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"


class TaskPriority(enum.StrEnum):
    """How urgent the work is — a property of the work, never of the person
    doing it. ``NORMAL`` is the default so that priority means something:
    a board where everything is urgent has no priority at all."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskEventKind(enum.StrEnum):
    """What can happen to a task. Closed, because a free-form event name is
    how a payload eventually grows one (projects/audit.py)."""

    CREATED = "created"
    RETITLED = "retitled"
    DESCRIBED = "described"
    REASSIGNED = "reassigned"
    UNASSIGNED = "unassigned"
    REPRIORITISED = "reprioritised"
    RESCHEDULED = "rescheduled"
    STATE_CHANGED = "state_changed"
    ARCHIVED = "archived"
    RESTORED = "restored"


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One unit of work inside one project.

    Archived, never deleted: ``archived_at`` closes it, its events stay
    readable, and the grants below back this up — the app role holds no DELETE
    on this table. Task state is task state only; nothing here ever writes
    ``projects`` — a project's state is declared by a human, not derived from
    its board (project_models.py).
    """

    __tablename__ = "tasks"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Every task belongs to a project. There is no inbox of orphan tasks —
    #: work without a project is work without context, and CAIRN's whole
    #: premise is that context is the product.
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    #: Display text, never parsed. Empty string rather than NULL so "no
    #: description" has exactly one representation.
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    state: Mapped[TaskState] = mapped_column(
        Enum(TaskState, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=TaskState.TODO,
        server_default=TaskState.TODO.value,
    )

    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
        default=TaskPriority.NORMAL,
        server_default=TaskPriority.NORMAL.value,
    )

    #: The Person, not the User — assignment follows project membership's
    #: axis (see the module docstring). Nullable: unassigned is a real state.
    assignee_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("people.id", ondelete="SET NULL"),
        nullable=True,
    )

    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    #: The actor who created it — a User, because creating requires a session.
    #: Nullable with SET NULL, the project-layer idiom: the task outlives the
    #: account that created it, and the column says honestly that it did.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_tasks_tenant_project", "tenant_id", "project_id"),
        Index("ix_tasks_tenant_assignee", "tenant_id", "assignee_person_id"),
    )


class TaskEvent(UUIDPrimaryKeyMixin, Base):
    """One thing that happened to a task. Append-only — the grants allow
    INSERT and SELECT and nothing else, so history cannot be edited even by
    correct code with a bug in it.

    Categorical by construction: a kind, an actor, and — for state changes
    only — the two states. No free-text payload column, so no title, no
    description, no person's name can ever land in the audit. Rendering into
    sentences happens at read time in the router, where the words are chosen
    once, neutrally, for everyone.
    """

    __tablename__ = "task_events"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[TaskEventKind] = mapped_column(
        Enum(TaskEventKind, native_enum=False, length=16, values_callable=_enum_values),
        nullable=False,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: Populated for ``state_changed`` only. These two columns are the whole
    #: reason the audit is structured at all: the review-handoff rule reads
    #: back who moved a task *to* in_review.
    from_state: Mapped[TaskState | None] = mapped_column(
        Enum(TaskState, native_enum=False, length=16, values_callable=_enum_values),
        nullable=True,
    )
    to_state: Mapped[TaskState | None] = mapped_column(
        Enum(TaskState, native_enum=False, length=16, values_callable=_enum_values),
        nullable=True,
    )

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (Index("ix_task_events_tenant_task", "tenant_id", "task_id"),)
