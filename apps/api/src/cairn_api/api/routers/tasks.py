"""Tasks: the board CAIRN keeps without keeping score.

**What this deliberately is not.** Not a productivity tracker, not a workload
monitor, not a burndown. A task is a unit of work with a title, a workflow
state, a priority, maybe an assignee and a due date — and an append-only,
categorical audit trail rendered back to every member as neutral sentences.

The md/05 §B.2 commitments, on this feature's face:

1. Symmetric — every role reads identical bytes; the payload functions take
   no role, the finder's structural guarantee.
2. No scoring — no response carries a count, a total, or a per-person
   aggregate; boards order by creation time, never by activity; events are
   never exposed grouped or ordered per person. A test greps the vocabulary.
3. The workflow is a closed table. Illegal moves are refused with a 409 that
   names both states, so the board's columns keep their meaning.
4. **Review is a second pair of eyes.** The user who moves a task
   in_review→done must differ from the user who sent it to review — that is
   the product's "test it" step, enforced by reading the audit back, and it
   is deliberately not softenable per workspace.
5. Done is terminal and archived is read-only: a wrongly-closed task is
   archived and a new one created, so history is never rewritten in place.
6. Task state is task state: nothing in this router ever writes ``projects``.
   A project's state is declared by a human (projects.py), not derived from
   its board.

**Permission choice, documented.** Reads gate on ``CONTENT_READ`` like every
other read. Writes gate on ``TASKS_WRITE`` — a member-level permission added
with this layer, because before it the Member and Viewer permission sets were
identical and the product needs "member and up may write tasks, Viewer may
not". ``PROJECTS_MANAGE`` (Admin+) would have made everyday task work an
administrative act, which is the wrong axis; it is used here only as the
"owner/admin may archive anybody's task" half of the archive rule.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import TenantDb, WorkspaceContext, requires
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    MyTasksResponse,
    TaskCreate,
    TaskDetailResponse,
    TaskEventEntry,
    TaskListResponse,
    TaskStateChange,
    TaskSummary,
    TaskUpdate,
)
from cairn_api.auth.permissions import Permission, has_permission
from cairn_api.db.identity_models import Person
from cairn_api.db.models import User
from cairn_api.db.project_models import Project, ProjectMember
from cairn_api.db.task_models import Task, TaskEvent, TaskEventKind, TaskPriority, TaskState
from cairn_api.tasks import audit

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["tasks"])

#: The workflow, closed. Anything not in this set is a 409 naming both
#: states. `done` appears in no key on purpose — done is terminal, and the
#: 409 for it explains the archive-and-recreate path instead.
_LEGAL_TRANSITIONS: frozenset[tuple[TaskState, TaskState]] = frozenset(
    {
        (TaskState.TODO, TaskState.IN_PROGRESS),
        (TaskState.TODO, TaskState.BLOCKED),
        (TaskState.IN_PROGRESS, TaskState.IN_REVIEW),
        (TaskState.IN_PROGRESS, TaskState.BLOCKED),
        (TaskState.BLOCKED, TaskState.IN_PROGRESS),
        (TaskState.BLOCKED, TaskState.TODO),
        (TaskState.IN_REVIEW, TaskState.IN_PROGRESS),
        (TaskState.IN_REVIEW, TaskState.DONE),
    }
)

#: How a state reads in a sentence. Column labels, shared by every workspace.
_STATE_LABELS: dict[TaskState, str] = {
    TaskState.TODO: "To do",
    TaskState.IN_PROGRESS: "In progress",
    TaskState.IN_REVIEW: "In review",
    TaskState.BLOCKED: "Blocked",
    TaskState.DONE: "Done",
}


def _actor_name(user: User | None) -> str:
    """The workspace-visible name of an acting user — both fields already
    appear on the members screen. A deleted account reads as what it is."""
    if user is None:
        return "A former member"
    return user.display_name or user.email


def _sentence(event: TaskEvent, actor: str) -> str:
    """One audit row as one neutral sentence — the change and who made it,
    never a judgement, a duration, or a count. Chosen here, once, so every
    reader gets the same words and no client re-derives the raw categories."""
    if event.kind is TaskEventKind.STATE_CHANGED:
        from_label = _STATE_LABELS.get(event.from_state, "?") if event.from_state else "?"
        to_label = _STATE_LABELS.get(event.to_state, "?") if event.to_state else "?"
        return f"{actor} moved this task from {from_label} to {to_label}."
    template = {
        TaskEventKind.CREATED: "{actor} created this task.",
        TaskEventKind.RETITLED: "{actor} retitled this task.",
        TaskEventKind.DESCRIBED: "{actor} updated the description.",
        TaskEventKind.REASSIGNED: "{actor} reassigned this task.",
        TaskEventKind.UNASSIGNED: "{actor} unassigned this task.",
        TaskEventKind.REPRIORITISED: "{actor} changed the priority.",
        TaskEventKind.RESCHEDULED: "{actor} changed the due date.",
        TaskEventKind.ARCHIVED: "{actor} archived this task.",
        TaskEventKind.RESTORED: "{actor} restored this task.",
    }[event.kind]
    return template.format(actor=actor)


async def _people_names(
    session: AsyncSession, tenant_id: uuid.UUID, person_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not person_ids:
        return {}
    people = await session.scalars(
        select(Person).where(Person.tenant_id == tenant_id, Person.id.in_(person_ids))
    )
    return {person.id: person.display_name or "Unnamed person" for person in people}


async def _users_by_id(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, User]:
    real_ids = {user_id for user_id in ids if user_id is not None}
    if not real_ids:
        return {}
    users = await session.scalars(select(User).where(User.id.in_(real_ids)))
    return {user.id: user for user in users}


def _summary(task: Task, assignee_names: dict[uuid.UUID, str]) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        project_id=task.project_id,
        title=task.title,
        description=task.description,
        state=task.state.value,
        priority=task.priority.value,
        assignee_person_id=task.assignee_person_id,
        assignee_name=(
            assignee_names.get(task.assignee_person_id)
            if task.assignee_person_id is not None
            else None
        ),
        due_on=task.due_on,
        created_at=task.created_at,
        archived_at=task.archived_at,
    )


async def list_tasks_payload(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID,
    state: str | None = None,
    include_archived: bool = False,
) -> TaskListResponse:
    """One project's board, independent of any request context.

    Takes no role and no caller — symmetry guaranteed structurally, the
    finder's idiom. Ordered by creation time then id, deliberately: creation
    order measures nothing, whereas any activity-derived order would quietly
    rank the work and, through it, the people doing it.
    """
    query = select(Task).where(Task.tenant_id == tenant_id, Task.project_id == project_id)
    if not include_archived:
        query = query.where(Task.archived_at.is_(None))
    if state is not None:
        query = query.where(Task.state == state)

    tasks = (await session.scalars(query.order_by(Task.created_at, Task.id))).all()
    names = await _people_names(
        session,
        tenant_id,
        {task.assignee_person_id for task in tasks if task.assignee_person_id is not None},
    )
    return TaskListResponse(tasks=[_summary(task, names) for task in tasks])


async def task_detail_payload(
    session: AsyncSession, *, tenant_id: uuid.UUID, task_id: uuid.UUID
) -> TaskDetailResponse | None:
    """One task with its audit trail rendered as sentences. No role, no
    caller; `None` when it does not exist so the route can 404 without this
    function knowing about HTTP.

    Events are queried, not read off a relationship: `expire_on_commit=False`
    means a collection loaded earlier in the session survives a write
    untouched, and a query cannot be stale. They render oldest-first — the
    order the story happened — keyed on (at, id) so two reads return
    identical bytes.
    """
    task: Task | None = await session.scalar(
        select(Task).where(Task.tenant_id == tenant_id, Task.id == task_id)
    )
    if task is None:
        return None

    events = (
        await session.scalars(
            select(TaskEvent)
            .where(TaskEvent.tenant_id == tenant_id, TaskEvent.task_id == task_id)
            .order_by(TaskEvent.at, TaskEvent.id)
        )
    ).all()

    users = await _users_by_id(
        session,
        {task.created_by_user_id, *(event.actor_user_id for event in events)},
    )
    names = await _people_names(
        session,
        tenant_id,
        {task.assignee_person_id} if task.assignee_person_id is not None else set(),
    )

    def lookup(user_id: uuid.UUID | None) -> User | None:
        return None if user_id is None else users.get(user_id)

    return TaskDetailResponse(
        id=task.id,
        project_id=task.project_id,
        title=task.title,
        description=task.description,
        state=task.state.value,
        priority=task.priority.value,
        assignee_person_id=task.assignee_person_id,
        assignee_name=(
            names.get(task.assignee_person_id) if task.assignee_person_id is not None else None
        ),
        due_on=task.due_on,
        created_by=(
            _actor_name(lookup(task.created_by_user_id))
            if task.created_by_user_id is not None
            else None
        ),
        created_at=task.created_at,
        archived_at=task.archived_at,
        events=[
            TaskEventEntry(
                sentence=_sentence(event, _actor_name(lookup(event.actor_user_id))),
                at=event.at,
            )
            for event in events
        ],
    )


async def my_tasks_payload(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID | None
) -> MyTasksResponse:
    """The caller's own tasks, grouped by column.

    Self-scoped by construction: the query keys on one Person id — the
    caller's own, resolved by the route — so this surface can only ever show
    someone their own work (the My Week idiom). `person_id` is None for a
    member whose commits have not been attributed to a Person yet; that is an
    ordinary state and returns empty groups, not an error.

    `done` carries the latest ten as a memory aid; the other groups list
    everything open, oldest-first like a board.
    """
    if person_id is None:
        return MyTasksResponse()

    tasks = (
        await session.scalars(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.assignee_person_id == person_id,
                Task.archived_at.is_(None),
            )
        )
    ).all()
    names = await _people_names(session, tenant_id, {person_id})

    open_states: dict[TaskState, list[Task]] = {
        TaskState.TODO: [],
        TaskState.IN_PROGRESS: [],
        TaskState.IN_REVIEW: [],
        TaskState.BLOCKED: [],
    }
    done: list[Task] = []
    for task in tasks:
        if task.state is TaskState.DONE:
            done.append(task)
        else:
            open_states[task.state].append(task)

    def ordered(group: list[Task]) -> list[TaskSummary]:
        return [
            _summary(task, names)
            for task in sorted(group, key=lambda task: (task.created_at, str(task.id)))
        ]

    latest_done = sorted(done, key=lambda task: (task.updated_at, str(task.id)), reverse=True)[:10]
    return MyTasksResponse(
        todo=ordered(open_states[TaskState.TODO]),
        in_progress=ordered(open_states[TaskState.IN_PROGRESS]),
        in_review=ordered(open_states[TaskState.IN_REVIEW]),
        blocked=ordered(open_states[TaskState.BLOCKED]),
        done=[_summary(task, names) for task in latest_done],
    )


def _not_found() -> ProblemDetailError:
    """404, not 403 — the workspace-membership idiom, one level down. A task
    id that is not this workspace's is indistinguishable from one that never
    existed."""
    return ProblemDetailError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Task not found",
        detail="No such task in this workspace.",
        problem_type="task-not-found",
    )


async def _get_task(db: AsyncSession, *, tenant_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task: Task | None = await db.scalar(
        select(Task).where(Task.tenant_id == tenant_id, Task.id == task_id)
    )
    if task is None:
        raise _not_found()
    return task


async def _get_project(db: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project: Project | None = await db.scalar(
        select(Project).where(Project.tenant_id == tenant_id, Project.id == project_id)
    )
    if project is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Project not found",
            detail="No such project in this workspace.",
            problem_type="project-not-found",
        )
    return project


async def _ensure_assignable(
    db: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID, person_id: uuid.UUID
) -> None:
    """An assignee must be an *active* member of the task's project.

    422, not 404: the request is well-formed and the person may well exist —
    the entity is simply not processable as an assignee here. Assignment
    follows membership because membership is the audited "part of this work's
    context" claim; assigning outside it would create silent membership by
    the back door.
    """
    member = await db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.tenant_id == tenant_id,
            ProjectMember.project_id == project_id,
            ProjectMember.person_id == person_id,
            ProjectMember.removed_at.is_(None),
        )
    )
    if member is None:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Assignee is not a project member",
            detail="The assignee must be an active member of this task's project.",
            problem_type="task-assignee-not-member",
        )


def _refuse_archived(task: Task) -> None:
    if task.archived_at is not None:
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Task is archived",
            detail="An archived task is read-only; restore it to make changes.",
            problem_type="task-archived",
        )


def _record(
    db: AsyncSession,
    task: Task,
    kind: TaskEventKind,
    actor_user_id: uuid.UUID,
    *,
    from_state: TaskState | None = None,
    to_state: TaskState | None = None,
) -> None:
    """Append one categorical audit row. The `at` stamp is set here rather
    than by the column default so that rows written by one request still
    order deterministically under (at, id)."""
    db.add(
        TaskEvent(
            tenant_id=task.tenant_id,
            task_id=task.id,
            kind=kind,
            actor_user_id=actor_user_id,
            from_state=from_state,
            to_state=to_state,
            at=datetime.now(UTC),
        )
    )


async def _reload(
    db: AsyncSession, *, context: WorkspaceContext, task_id: uuid.UUID
) -> TaskDetailResponse:
    """Re-read a task after a write, for the response. Raises rather than
    asserting — `assert` disappears under `-O` (projects.py's lesson)."""
    payload = await task_detail_payload(db, tenant_id=context.tenant_id, task_id=task_id)
    if payload is None:
        raise _not_found()
    return payload


@router.post(
    "/{workspace_id}/projects/{project_id}/tasks",
    response_model=TaskDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task on this project's board",
    responses={
        404: {"description": "No such workspace or project."},
        422: {"description": "The assignee is not an active member of the project."},
    },
)
async def create_task(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.TASKS_WRITE))],
    db: TenantDb,
    project_id: uuid.UUID,
    body: TaskCreate,
) -> TaskDetailResponse:
    await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    if body.assignee_person_id is not None:
        await _ensure_assignable(
            db,
            tenant_id=context.tenant_id,
            project_id=project_id,
            person_id=body.assignee_person_id,
        )

    task = Task(
        tenant_id=context.tenant_id,
        project_id=project_id,
        title=body.title.strip(),
        description=body.description,
        priority=TaskPriority(body.priority),
        assignee_person_id=body.assignee_person_id,
        due_on=body.due_on,
        created_by_user_id=context.user.id,
    )
    db.add(task)
    await db.flush()
    _record(db, task, TaskEventKind.CREATED, context.user.id)
    await db.commit()

    await audit.record(audit.TaskOpEvent.CREATED)
    return await _reload(db, context=context, task_id=task.id)


@router.get(
    "/{workspace_id}/projects/{project_id}/tasks",
    response_model=TaskListResponse,
    summary="One project's board, in creation order",
    responses={404: {"description": "No such workspace or project."}},
)
async def list_tasks(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    project_id: uuid.UUID,
    state: Annotated[
        str | None, Query(pattern="^(todo|in_progress|in_review|blocked|done)$")
    ] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> TaskListResponse:
    """Archived tasks are excluded by default and included on request —
    excluded is not deleted, and their audit trail stays readable either way."""
    await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    return await list_tasks_payload(
        db,
        tenant_id=context.tenant_id,
        project_id=project_id,
        state=state,
        include_archived=include_archived,
    )


@router.get(
    "/{workspace_id}/tasks/{task_id}",
    response_model=TaskDetailResponse,
    summary="One task, with its audit trail as sentences",
    responses={404: {"description": "No such workspace or task."}},
)
async def get_task(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    task_id: uuid.UUID,
) -> TaskDetailResponse:
    payload = await task_detail_payload(db, tenant_id=context.tenant_id, task_id=task_id)
    if payload is None:
        raise _not_found()
    return payload


@router.patch(
    "/{workspace_id}/tasks/{task_id}",
    response_model=TaskDetailResponse,
    summary="Edit a task's descriptive fields",
    responses={
        404: {"description": "No such workspace or task."},
        409: {"description": "The task is archived."},
        422: {"description": "The assignee is not an active member of the project."},
    },
)
async def update_task(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.TASKS_WRITE))],
    db: TenantDb,
    task_id: uuid.UUID,
    body: TaskUpdate,
) -> TaskDetailResponse:
    """Each changed field appends its own categorical audit event, so the
    trail says *what kind* of thing happened without quoting any content.
    Absent and null differ for the nullable fields — `model_fields_set`
    tells them apart, so omitting the assignee is not an unassignment."""
    task = await _get_task(db, tenant_id=context.tenant_id, task_id=task_id)
    _refuse_archived(task)

    sent = body.model_fields_set
    edited = False

    if body.title is not None and body.title.strip() != task.title:
        task.title = body.title.strip()
        _record(db, task, TaskEventKind.RETITLED, context.user.id)
        edited = True

    if body.description is not None and body.description != task.description:
        task.description = body.description
        _record(db, task, TaskEventKind.DESCRIBED, context.user.id)
        edited = True

    if body.priority is not None and TaskPriority(body.priority) is not task.priority:
        task.priority = TaskPriority(body.priority)
        _record(db, task, TaskEventKind.REPRIORITISED, context.user.id)
        edited = True

    if "due_on" in sent and body.due_on != task.due_on:
        task.due_on = body.due_on
        _record(db, task, TaskEventKind.RESCHEDULED, context.user.id)
        edited = True

    if "assignee_person_id" in sent and body.assignee_person_id != task.assignee_person_id:
        if body.assignee_person_id is None:
            task.assignee_person_id = None
            _record(db, task, TaskEventKind.UNASSIGNED, context.user.id)
        else:
            await _ensure_assignable(
                db,
                tenant_id=context.tenant_id,
                project_id=task.project_id,
                person_id=body.assignee_person_id,
            )
            task.assignee_person_id = body.assignee_person_id
            _record(db, task, TaskEventKind.REASSIGNED, context.user.id)
        edited = True

    await db.commit()
    if edited:
        await audit.record(audit.TaskOpEvent.EDITED)
    return await _reload(db, context=context, task_id=task_id)


@router.post(
    "/{workspace_id}/tasks/{task_id}/state",
    response_model=TaskDetailResponse,
    summary="Move a task along the workflow",
    responses={
        404: {"description": "No such workspace or task."},
        409: {
            "description": "Illegal transition, archived task, terminal state, "
            "or the review handoff refused the same reviewer."
        },
    },
)
async def set_task_state(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.TASKS_WRITE))],
    db: TenantDb,
    task_id: uuid.UUID,
    body: TaskStateChange,
) -> TaskDetailResponse:
    task = await _get_task(db, tenant_id=context.tenant_id, task_id=task_id)
    _refuse_archived(task)

    target = TaskState(body.state)
    current = task.state

    if current is TaskState.DONE:
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Done is terminal",
            detail=(
                "A done task cannot change state. If it was closed wrongly, "
                "archive it and create a new task — the record of what was "
                "reviewed is never rewritten in place."
            ),
            problem_type="task-done-terminal",
        )

    if (current, target) not in _LEGAL_TRANSITIONS:
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Illegal transition",
            detail=f"A task cannot move from '{current.value}' to '{target.value}'.",
            problem_type="task-illegal-transition",
        )

    if current is TaskState.IN_REVIEW and target is TaskState.DONE:
        await _enforce_review_handoff(db, task=task, actor_user_id=context.user.id)

    task.state = target
    _record(
        db,
        task,
        TaskEventKind.STATE_CHANGED,
        context.user.id,
        from_state=current,
        to_state=target,
    )
    await db.commit()

    await audit.record(
        audit.TaskOpEvent.STATE_CHANGED, from_state=current.value, to_state=target.value
    )
    return await _reload(db, context=context, task_id=task_id)


async def _enforce_review_handoff(
    db: AsyncSession, *, task: Task, actor_user_id: uuid.UUID
) -> None:
    """Review means a second pair of eyes, structurally.

    The latest audit row that moved this task *to* in_review names the user
    who asked for review; the user closing the review must be somebody else.
    This is the product's "test it" step — the one place the workflow insists
    two humans took part — and it reads the append-only trail rather than a
    mutable column, so it cannot be gamed by an edit.
    """
    sent_to_review = await db.scalar(
        select(TaskEvent)
        .where(
            TaskEvent.tenant_id == task.tenant_id,
            TaskEvent.task_id == task.id,
            TaskEvent.kind == TaskEventKind.STATE_CHANGED,
            TaskEvent.to_state == TaskState.IN_REVIEW,
        )
        .order_by(TaskEvent.at.desc(), TaskEvent.id.desc())
        .limit(1)
    )
    if sent_to_review is not None and sent_to_review.actor_user_id == actor_user_id:
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Review needs a second pair of eyes",
            detail=(
                "The user who sent this task to review cannot be the one who "
                "approves it as done; review means somebody else looked."
            ),
            problem_type="task-review-handoff",
        )


@router.post(
    "/{workspace_id}/tasks/{task_id}/archive",
    response_model=TaskDetailResponse,
    summary="Archive a task — close it, never delete it",
    responses={
        403: {"description": "Only an owner, an admin, or the task's creator may archive."},
        404: {"description": "No such workspace or task."},
    },
)
async def archive_task(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.TASKS_WRITE))],
    db: TenantDb,
    task_id: uuid.UUID,
) -> TaskDetailResponse:
    return await _set_archived(db, context=context, task_id=task_id, archived=True)


@router.post(
    "/{workspace_id}/tasks/{task_id}/restore",
    response_model=TaskDetailResponse,
    summary="Restore an archived task",
    responses={
        403: {"description": "Only an owner, an admin, or the task's creator may restore."},
        404: {"description": "No such workspace or task."},
    },
)
async def restore_task(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.TASKS_WRITE))],
    db: TenantDb,
    task_id: uuid.UUID,
) -> TaskDetailResponse:
    return await _set_archived(db, context=context, task_id=task_id, archived=False)


async def _set_archived(
    db: AsyncSession, *, context: WorkspaceContext, task_id: uuid.UUID, archived: bool
) -> TaskDetailResponse:
    """Archive/restore is the one write with a second, in-handler gate:
    owner/admin (who hold PROJECTS_MANAGE) or the task's own creator. A
    member closing somebody else's task would be a quiet judgement about
    that work; closing your own mistake is housekeeping."""
    task = await _get_task(db, tenant_id=context.tenant_id, task_id=task_id)

    creator = task.created_by_user_id == context.user.id
    if not creator and not has_permission(context.role, Permission.PROJECTS_MANAGE):
        raise ProblemDetailError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Not allowed",
            detail="Only an owner, an admin, or the task's creator may archive or restore it.",
            problem_type="task-archive-forbidden",
        )

    if archived:
        if task.archived_at is None:
            task.archived_at = datetime.now(UTC)
            _record(db, task, TaskEventKind.ARCHIVED, context.user.id)
            await audit.record(audit.TaskOpEvent.ARCHIVED)
    else:
        if task.archived_at is not None:
            task.archived_at = None
            _record(db, task, TaskEventKind.RESTORED, context.user.id)
            await audit.record(audit.TaskOpEvent.RESTORED)

    await db.commit()
    return await _reload(db, context=context, task_id=task_id)


@router.get(
    "/{workspace_id}/me/tasks",
    response_model=MyTasksResponse,
    summary="My own tasks, grouped by column",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def list_my_tasks(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
) -> MyTasksResponse:
    """Empty groups, not a 404, for a caller with no `Person` row: a user and
    a person are different things (md/01 §5.3), and having no attributed
    Person yet is an ordinary state, not an error."""
    person: Person | None = await db.scalar(select(Person).where(Person.user_id == context.user.id))
    return await my_tasks_payload(
        db,
        tenant_id=context.tenant_id,
        person_id=person.id if person is not None else None,
    )
