"""Projects: the entity behind the string on a citation. Context, never control.

**What this deliberately is not.** Not a task board, not an assignment system,
not a progress meter, not a workload view. A project here is a named piece of
work with a *declared* state, a membership that says who is part of its context
and who put them there, and a claim over the citation strings that link
evidence to it. The rollup groups what the evidence says happened — delivered,
blockers, open questions, decisions — cited and newest first. There is no
percentage, no velocity, and no remaining-work figure, because CAIRN holds no
planned-work model and would have to invent one (md/05 §A.2).

The md/05 §B.2 commitments, on this feature's face:

1. Symmetric — every role reads identical bytes; the payload functions take
   no role, the finder's structural guarantee.
2. No scoring — membership rows carry identity, a self-recognisable role, and
   their own audit trail. Nothing on any project response counts, ranks or
   compares people; a test pins the member field set and greps the vocabulary.
3. Membership is context, never assignment: adding somebody states that they
   are part of this work's context, and the row records who said so. It
   assigns nothing and implies no obligation.
4. State is declared by an authorized human and stamped with who and when —
   never inferred from activity, which would make the state a judgement about
   the people producing the activity.
5. No silent membership: every add and remove is durable in the row itself
   (added_by, removed_by, timestamps), returned to every member, and removal
   preserves history rather than deleting it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import TenantDb, WorkspaceContext, requires
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    ProjectCreate,
    ProjectDetailResponse,
    ProjectFact,
    ProjectListResponse,
    ProjectMemberAdd,
    ProjectMemberEntry,
    ProjectRollup,
    ProjectSourceClaim,
    ProjectSourceClaimRequest,
    ProjectSummary,
    ProjectUpdate,
    RelatedFactSource,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.fact_models import Fact, FactSource
from cairn_api.db.identity_models import Person
from cairn_api.db.models import User
from cairn_api.db.project_models import Project, ProjectMember, ProjectSource, ProjectState
from cairn_api.projects import audit

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["projects"])

#: Which fact kinds feed which rollup group. `in_progress` is deliberately
#: absent: "what somebody is currently doing", grouped under a project banner,
#: reads as a live workload view of the people doing it — the feed carries
#: those facts individually, where they remain one person's own cited record.
_ROLLUP_KINDS: dict[str, str] = {
    "delivery": "delivered",
    "blocker": "blockers",
    "open_question": "open_questions",
    "decision": "decisions",
}


def _actor_name(user: User | None) -> str | None:
    """The workspace-visible name of an acting user. Both fields already appear
    on the members screen, so nothing new is disclosed here."""
    if user is None:
        return None
    return user.display_name or user.email


async def list_projects_payload(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    state: str | None = None,
    q: str | None = None,
    include_archived: bool = False,
) -> ProjectListResponse:
    """The portfolio, independent of any request context.

    Takes no role and no caller — symmetry guaranteed structurally, the
    finder's idiom. Alphabetical order, deliberately: any activity-derived
    order would quietly rank the work, and through it the people doing it.
    """
    query = select(Project).where(Project.tenant_id == tenant_id)
    if not include_archived:
        query = query.where(Project.archived_at.is_(None))
    if state is not None:
        query = query.where(Project.state == state)
    if q is not None and q.strip() != "":
        needle = f"%{q.strip()}%"
        query = query.where(Project.name.ilike(needle) | Project.purpose.ilike(needle))

    projects = (await session.scalars(query.order_by(func.lower(Project.name)))).all()
    return ProjectListResponse(
        projects=[
            ProjectSummary(
                id=project.id,
                name=project.name,
                purpose=project.purpose,
                state=project.state.value,
                state_declared_at=project.state_declared_at,
                archived_at=project.archived_at,
            )
            for project in projects
        ]
    )


async def project_detail_payload(
    session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectDetailResponse | None:
    """One project with its claims, its membership history, and the
    evidence-backed rollup. No role, no caller; `None` when it does not exist
    so the route can 404 without this function knowing about HTTP."""
    project = await _get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project is None:
        return None

    # Queried, not read off the relationships: `expire_on_commit=False` means a
    # collection loaded earlier in this session survives a write untouched, so
    # a claim released a moment ago would still be listed here. A query cannot
    # be stale.
    claims = sorted(
        (
            await session.scalars(
                select(ProjectSource).where(
                    ProjectSource.tenant_id == tenant_id,
                    ProjectSource.project_id == project_id,
                )
            )
        ).all(),
        key=lambda claim: claim.value,
    )
    members = sorted(
        (
            await session.scalars(
                select(ProjectMember).where(
                    ProjectMember.tenant_id == tenant_id,
                    ProjectMember.project_id == project_id,
                )
            )
        ).all(),
        key=lambda member: (member.created_at, str(member.id)),
    )

    users = await _users_by_id(
        session,
        {
            project.state_declared_by_user_id,
            *(claim.added_by_user_id for claim in claims),
            *(member.added_by_user_id for member in members),
            *(member.removed_by_user_id for member in members),
        },
    )
    people = {
        person.id: person
        for person in await session.scalars(
            select(Person).where(
                Person.tenant_id == tenant_id,
                Person.id.in_({member.person_id for member in members} or {uuid.uuid4()}),
            )
        )
    }

    return ProjectDetailResponse(
        id=project.id,
        name=project.name,
        purpose=project.purpose,
        state=project.state.value,
        state_declared_by=_actor_name(_lookup(users, project.state_declared_by_user_id)),
        state_declared_at=project.state_declared_at,
        archived_at=project.archived_at,
        sources=[
            ProjectSourceClaim(
                value=claim.value,
                added_by=_actor_name(_lookup(users, claim.added_by_user_id)),
                added_at=claim.created_at,
            )
            for claim in claims
        ],
        members=[
            ProjectMemberEntry(
                person_id=member.person_id,
                display_name=(
                    person.display_name if (person := people.get(member.person_id)) else None
                )
                or "Unnamed person",
                project_role=member.project_role,
                added_by=_actor_name(_lookup(users, member.added_by_user_id)),
                added_at=member.created_at,
                removed_by=_actor_name(_lookup(users, member.removed_by_user_id)),
                removed_at=member.removed_at,
            )
            for member in members
        ],
        rollup=await _rollup(
            session, tenant_id=tenant_id, values=[claim.value for claim in claims]
        ),
    )


async def _rollup(
    session: AsyncSession, *, tenant_id: uuid.UUID, values: list[str]
) -> ProjectRollup:
    """What the evidence says, grouped by kind. Live facts only, resolved
    through the mapping at read time — a claim made a minute ago reaches every
    fact that ever carried the string."""
    if not values:
        return ProjectRollup()

    rows = await session.execute(
        select(Fact)
        .join(FactSource, FactSource.fact_id == Fact.id)
        .where(
            Fact.tenant_id == tenant_id,
            Fact.valid_until.is_(None),
            FactSource.project.in_(values),
        )
        .distinct()
    )
    facts = [row[0] for row in rows.unique()]

    grouped: dict[str, list[Fact]] = {group: [] for group in _ROLLUP_KINDS.values()}
    for fact in facts:
        group = _ROLLUP_KINDS.get(fact.kind)
        if group is not None:
            grouped[group].append(fact)

    def entries(group_facts: list[Fact]) -> list[ProjectFact]:
        # Dated facts newest first, undated after, ids as the tiebreak - two
        # runs return identical bytes.
        dated = sorted(
            (fact for fact in group_facts if fact.occurred_at is not None),
            key=lambda fact: (fact.occurred_at, str(fact.id)),
            reverse=True,
        )
        undated = sorted(
            (fact for fact in group_facts if fact.occurred_at is None),
            key=lambda fact: str(fact.id),
        )
        return [
            ProjectFact(
                statement=fact.statement,
                certainty=fact.certainty,
                occurred_at=fact.occurred_at,
                sources=[
                    RelatedFactSource(
                        evidence_id=source.evidence_id,
                        source=source.source,
                        url=source.url,
                    )
                    for source in sorted(
                        fact.sources, key=lambda source: (source.source, source.evidence_id)
                    )
                ],
            )
            for fact in dated + undated
        ]

    return ProjectRollup(
        delivered=entries(grouped["delivered"]),
        blockers=entries(grouped["blockers"]),
        open_questions=entries(grouped["open_questions"]),
        decisions=entries(grouped["decisions"]),
    )


async def _get_project(
    session: AsyncSession, *, tenant_id: uuid.UUID, project_id: uuid.UUID
) -> Project | None:
    project: Project | None = await session.scalar(
        select(Project).where(Project.tenant_id == tenant_id, Project.id == project_id)
    )
    return project


async def _users_by_id(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, User]:
    real_ids = {user_id for user_id in ids if user_id is not None}
    if not real_ids:
        return {}
    users = await session.scalars(select(User).where(User.id.in_(real_ids)))
    return {user.id: user for user in users}


def _lookup(users: dict[uuid.UUID, User], user_id: uuid.UUID | None) -> User | None:
    """A nullable actor column resolved against the lookup table. Written out
    rather than keying the dict by `None`, so the table has one key type."""
    return None if user_id is None else users.get(user_id)


async def _reload(
    db: AsyncSession, *, context: WorkspaceContext, project_id: uuid.UUID
) -> ProjectDetailResponse:
    """Re-read a project after a write, for the response.

    Raises rather than asserting: `assert` disappears under `-O`, which would
    turn "the row I just committed is missing" into a `None` returned as a
    200. The 404 is the honest answer if it ever happens.

    The stale-collection hazard this used to have is handled where it belongs:
    `project_detail_payload` queries claims and membership explicitly rather
    than through the ORM relationships. The session factory sets
    `expire_on_commit=False`, so a relationship loaded before a write would
    still describe the state before it - a released claim listed, with its
    evidence, by the very call that released it.
    """
    payload = await project_detail_payload(db, tenant_id=context.tenant_id, project_id=project_id)
    if payload is None:
        raise _not_found()
    return payload


def _not_found() -> ProblemDetailError:
    """404, not 403 - the workspace-membership idiom, one level down. A caller
    who can reach this router is a member; a project id that is not theirs is
    indistinguishable from one that never existed."""
    return ProblemDetailError(
        status_code=status.HTTP_404_NOT_FOUND,
        title="Project not found",
        detail="No such project in this workspace.",
        problem_type="project-not-found",
    )


@router.get(
    "/{workspace_id}/projects",
    response_model=ProjectListResponse,
    summary="The workspace's projects, alphabetically",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def list_projects(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    state: Annotated[
        str | None, Query(pattern="^(active|paused|blocked|completed|unknown)$")
    ] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> ProjectListResponse:
    """Archived projects are excluded by default and included on request -
    excluded is not deleted, and their facts stay cited either way."""
    return await list_projects_payload(
        db, tenant_id=context.tenant_id, state=state, q=q, include_archived=include_archived
    )


@router.get(
    "/{workspace_id}/projects/{project_id}",
    response_model=ProjectDetailResponse,
    summary="One project: claims, membership history, evidence rollup",
    responses={404: {"description": "No such workspace or project."}},
)
async def get_project(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    project_id: uuid.UUID,
) -> ProjectDetailResponse:
    payload = await project_detail_payload(db, tenant_id=context.tenant_id, project_id=project_id)
    if payload is None:
        raise _not_found()
    return payload


@router.post(
    "/{workspace_id}/projects",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project, optionally claiming citation strings",
    responses={
        404: {"description": "No such workspace, or you are not a member."},
        409: {"description": "Name or source string already taken."},
    },
)
async def create_project(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    body: ProjectCreate,
) -> ProjectDetailResponse:
    await _ensure_name_free(db, tenant_id=context.tenant_id, name=body.name)

    project = Project(
        tenant_id=context.tenant_id,
        name=body.name.strip(),
        purpose=body.purpose,
    )
    db.add(project)
    await db.flush()

    for value in dict.fromkeys(body.source_strings):
        await _ensure_string_free(db, tenant_id=context.tenant_id, value=value)
        db.add(
            ProjectSource(
                tenant_id=context.tenant_id,
                project_id=project.id,
                value=value,
                added_by_user_id=context.user.id,
            )
        )
    await db.commit()

    await audit.record(audit.ProjectEvent.CREATED, sources=len(set(body.source_strings)))
    return await _reload(db, context=context, project_id=project.id)


@router.patch(
    "/{workspace_id}/projects/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Declare a state or reword the purpose",
    responses={404: {"description": "No such workspace or project."}},
)
async def update_project(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    project_id: uuid.UUID,
    body: ProjectUpdate,
) -> ProjectDetailResponse:
    project = await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    if project is None:
        raise _not_found()

    if body.purpose is not None:
        project.purpose = body.purpose
        await audit.record(audit.ProjectEvent.PURPOSE_CHANGED)

    if body.state is not None:
        # A declaration, so it is stamped: who said so, and when. Never
        # written by anything but this endpoint.
        project.state = ProjectState(body.state)
        project.state_declared_by_user_id = context.user.id
        project.state_declared_at = datetime.now(UTC)
        await audit.record(audit.ProjectEvent.STATE_DECLARED, state=body.state)

    await db.commit()
    return await _reload(db, context=context, project_id=project_id)


@router.post(
    "/{workspace_id}/projects/{project_id}/archive",
    response_model=ProjectDetailResponse,
    summary="Archive a project - close it, never delete it",
    responses={404: {"description": "No such workspace or project."}},
)
async def archive_project(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    project_id: uuid.UUID,
) -> ProjectDetailResponse:
    return await _set_archived(db, context=context, project_id=project_id, archived=True)


@router.post(
    "/{workspace_id}/projects/{project_id}/restore",
    response_model=ProjectDetailResponse,
    summary="Restore an archived project",
    responses={404: {"description": "No such workspace or project."}},
)
async def restore_project(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    project_id: uuid.UUID,
) -> ProjectDetailResponse:
    return await _set_archived(db, context=context, project_id=project_id, archived=False)


async def _set_archived(
    db: AsyncSession, *, context: WorkspaceContext, project_id: uuid.UUID, archived: bool
) -> ProjectDetailResponse:
    project = await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    if project is None:
        raise _not_found()

    if archived:
        project.archived_at = datetime.now(UTC)
        project.archived_by_user_id = context.user.id
        await audit.record(audit.ProjectEvent.ARCHIVED)
    else:
        project.archived_at = None
        project.archived_by_user_id = None
        await audit.record(audit.ProjectEvent.RESTORED)

    await db.commit()
    return await _reload(db, context=context, project_id=project_id)


@router.post(
    "/{workspace_id}/projects/{project_id}/sources",
    response_model=ProjectDetailResponse,
    summary="Claim a citation string for this project",
    responses={
        404: {"description": "No such workspace or project."},
        409: {"description": "Another project already claims this string."},
    },
)
async def claim_source(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    project_id: uuid.UUID,
    body: ProjectSourceClaimRequest,
) -> ProjectDetailResponse:
    project = await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    if project is None:
        raise _not_found()

    await _ensure_string_free(db, tenant_id=context.tenant_id, value=body.value)
    db.add(
        ProjectSource(
            tenant_id=context.tenant_id,
            project_id=project_id,
            value=body.value,
            added_by_user_id=context.user.id,
        )
    )
    await db.commit()
    await audit.record(audit.ProjectEvent.SOURCE_CLAIMED)

    return await _reload(db, context=context, project_id=project_id)


@router.post(
    "/{workspace_id}/projects/{project_id}/sources/release",
    response_model=ProjectDetailResponse,
    summary="Release a claimed string - the citations keep it as provenance",
    responses={404: {"description": "No such workspace, project, or claim."}},
)
async def release_source(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    project_id: uuid.UUID,
    body: ProjectSourceClaimRequest,
) -> ProjectDetailResponse:
    """A body-carrying POST rather than a DELETE with the value in the path:
    the values are repo names, and a slash in a path segment is a routing
    ambiguity nobody should have to escape their way around."""
    project = await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    if project is None:
        raise _not_found()

    claim = await db.scalar(
        select(ProjectSource).where(
            ProjectSource.tenant_id == context.tenant_id,
            ProjectSource.project_id == project_id,
            ProjectSource.value == body.value,
        )
    )
    if claim is None:
        raise _not_found()

    await db.delete(claim)
    await db.commit()
    await audit.record(audit.ProjectEvent.SOURCE_RELEASED)

    return await _reload(db, context=context, project_id=project_id)


@router.post(
    "/{workspace_id}/projects/{project_id}/members",
    response_model=ProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a person to the project's context - recorded, never silent",
    responses={
        404: {"description": "No such workspace, project, or person."},
        409: {"description": "Already an active member."},
    },
)
async def add_member(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    project_id: uuid.UUID,
    body: ProjectMemberAdd,
) -> ProjectDetailResponse:
    project = await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    if project is None:
        raise _not_found()

    person = await db.scalar(
        select(Person).where(Person.tenant_id == context.tenant_id, Person.id == body.person_id)
    )
    if person is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Person not found",
            detail="No such person in this workspace.",
            problem_type="person-not-found",
        )

    active = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.person_id == body.person_id,
            ProjectMember.removed_at.is_(None),
        )
    )
    if active is not None:
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Already a member",
            detail="This person is already an active member of the project.",
            problem_type="project-member-exists",
        )

    db.add(
        ProjectMember(
            tenant_id=context.tenant_id,
            project_id=project_id,
            person_id=body.person_id,
            project_role=body.project_role,
            added_by_user_id=context.user.id,
        )
    )
    await db.commit()
    await audit.record(audit.ProjectEvent.MEMBER_ADDED)

    return await _reload(db, context=context, project_id=project_id)


@router.delete(
    "/{workspace_id}/projects/{project_id}/members/{person_id}",
    response_model=ProjectDetailResponse,
    summary="Remove a person from the context - the history remains",
    responses={404: {"description": "No such workspace, project, or active membership."}},
)
async def remove_member(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.PROJECTS_MANAGE))],
    db: TenantDb,
    project_id: uuid.UUID,
    person_id: uuid.UUID,
) -> ProjectDetailResponse:
    """Removal closes the row - `removed_at`, `removed_by` - and the entry
    stays in the members list as history. A shrinking list must never look
    like a project that never had the person."""
    project = await _get_project(db, tenant_id=context.tenant_id, project_id=project_id)
    if project is None:
        raise _not_found()

    membership = await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.person_id == person_id,
            ProjectMember.removed_at.is_(None),
        )
    )
    if membership is None:
        raise _not_found()

    membership.removed_at = datetime.now(UTC)
    membership.removed_by_user_id = context.user.id
    await db.commit()
    await audit.record(audit.ProjectEvent.MEMBER_REMOVED)

    return await _reload(db, context=context, project_id=project_id)


async def _ensure_name_free(db: AsyncSession, *, tenant_id: uuid.UUID, name: str) -> None:
    existing = await db.scalar(
        select(Project).where(
            Project.tenant_id == tenant_id, func.lower(Project.name) == name.strip().lower()
        )
    )
    if existing is not None:
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Name already taken",
            detail="A project with this name already exists in the workspace.",
            problem_type="project-name-taken",
        )


async def _ensure_string_free(db: AsyncSession, *, tenant_id: uuid.UUID, value: str) -> None:
    claimed = await db.scalar(
        select(ProjectSource).where(
            ProjectSource.tenant_id == tenant_id, ProjectSource.value == value
        )
    )
    if claimed is not None:
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Source string already claimed",
            detail="Another project already claims this string; release it there first.",
            problem_type="source-string-claimed",
        )
