"""The task layer, and the promises that make it a board and not a scoreboard.

*The workflow is a closed table.* Every legal move is pinned, every illegal
move is a 409 that names both states, done is terminal, archived is read-only.

*Review is a second pair of eyes.* The user who sent a task to review cannot
be the one who approves it as done — enforced by reading the append-only
audit back, and tested with the same user and with a different one.

*Symmetric.* Owner, Admin, Member and Viewer receive byte-identical task
data; the payload functions take no role, so symmetry is structural.

*Nothing measures a person.* No counts, no per-person aggregates, creation
order only; the vocabulary is grepped with clean word-boundary regexes (a
previous guard silently matched nothing because of pasted control
characters — this one asserts its own sanity first).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime

import pytest
from cairn_api.api import schemas
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.routers import tasks as tasks_router
from cairn_api.api.schemas import TaskCreate, TaskStateChange, TaskUpdate
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.project_models import Project, ProjectMember
from cairn_api.db.task_models import Task, TaskEvent, TaskEventKind, TaskState
from cairn_api.db.tenancy import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

#: Per class, not per module — the boundary tests (vocabulary, signatures,
#: the transition table, the permission table) are pure inspection and must
#: run without a database. See test_projects.py.
integration = pytest.mark.integration


async def _tenant(platform, slug: str) -> Tenant:
    tenant = Tenant(name=f"Workspace {slug}", slug=f"{slug}-{uuid.uuid4().hex[:8]}")
    platform.add(tenant)
    await platform.flush()
    return tenant


async def _user(platform, tenant: Tenant, role: TenantRole) -> User:
    user = User(email=f"{uuid.uuid4().hex[:10]}@example.com", display_name=f"{role.value} person")
    platform.add(user)
    await platform.flush()
    platform.add(Membership(tenant_id=tenant.id, user_id=user.id, role=role))
    await platform.flush()
    return user


def _context(user: User, tenant: Tenant, role: TenantRole):
    from cairn_api.api.dependencies import WorkspaceContext

    return WorkspaceContext(
        user=user, membership=Membership(tenant_id=tenant.id, user_id=user.id, role=role)
    )


async def _project(session, tenant: Tenant, name: str) -> Project:
    project = Project(tenant_id=tenant.id, name=name)
    session.add(project)
    await session.flush()
    return project


async def _person(session, tenant: Tenant, name: str, *, user_id=None) -> Person:
    person = Person(tenant_id=tenant.id, display_name=name, user_id=user_id)
    session.add(person)
    await session.flush()
    return person


async def _member(session, tenant: Tenant, project: Project, person: Person) -> ProjectMember:
    membership = ProjectMember(tenant_id=tenant.id, project_id=project.id, person_id=person.id)
    session.add(membership)
    await session.flush()
    return membership


async def _task(
    session,
    tenant: Tenant,
    project: Project,
    *,
    title: str = "Rate-limit the public API's unauthenticated endpoints",
    state: TaskState = TaskState.TODO,
    creator: User | None = None,
    assignee: Person | None = None,
) -> Task:
    task = Task(
        tenant_id=tenant.id,
        project_id=project.id,
        title=title,
        state=state,
        created_by_user_id=creator.id if creator is not None else None,
        assignee_person_id=assignee.id if assignee is not None else None,
    )
    session.add(task)
    await session.flush()
    return task


async def _board(platform, slug: str = "t"):
    """One tenant, one owner-role user, one project — the common stage."""
    tenant = await _tenant(platform, slug)
    user = await _user(platform, tenant, TenantRole.OWNER)
    await platform.commit()
    async with tenant_session(tenant.id) as session:
        project = await _project(session, tenant, f"Project {uuid.uuid4().hex[:6]}")
        await session.commit()
        project_id = project.id
    return tenant, user, project_id


async def _move(tenant, user, task_id, state: str, *, role=TenantRole.OWNER):
    async with tenant_session(tenant.id) as session:
        return await tasks_router.set_task_state(
            _context(user, tenant, role), session, task_id, TaskStateChange(state=state)
        )


@integration
class TestTenantIsolation:
    async def test_a_task_is_invisible_across_the_tenant_boundary(self, platform) -> None:
        acme = await _tenant(platform, "acme")
        globex = await _tenant(platform, "globex")
        await platform.commit()

        async with tenant_session(acme.id) as session:
            project = await _project(session, acme, "Payments")
            await _task(session, acme, project)
            await session.commit()

        async with tenant_session(globex.id) as session:
            visible = (await session.scalars(select(Task))).all()
            assert visible == [], "jordan@globex can see acme's board"

    async def test_rls_refuses_a_write_for_another_tenant(self, platform) -> None:
        acme = await _tenant(platform, "acme2")
        globex = await _tenant(platform, "globex2")
        await platform.commit()

        async with tenant_session(acme.id) as session:
            project = await _project(session, acme, "Payments")
            await session.commit()
            project_id = project.id

        async with tenant_session(globex.id) as session:
            session.add(Task(tenant_id=acme.id, project_id=project_id, title="Smuggled task"))
            with pytest.raises(DBAPIError):
                await session.commit()
            # The transaction is aborted; roll it back inside the block so the
            # context manager's own close does not raise over the real error.
            await session.rollback()

    async def test_events_are_isolated_too(self, platform) -> None:
        acme = await _tenant(platform, "acme3")
        globex = await _tenant(platform, "globex3")
        actor = await _user(platform, acme, TenantRole.MEMBER)
        await platform.commit()

        async with tenant_session(acme.id) as session:
            project = await _project(session, acme, "Payments")
            task = await _task(session, acme, project, creator=actor)
            session.add(
                TaskEvent(
                    tenant_id=acme.id,
                    task_id=task.id,
                    kind=TaskEventKind.CREATED,
                    actor_user_id=actor.id,
                    at=datetime.now(UTC),
                )
            )
            await session.commit()

        async with tenant_session(globex.id) as session:
            assert (await session.scalars(select(TaskEvent))).all() == []


@integration
class TestTheGrantsAreAnAllowList:
    async def test_tasks_cannot_be_deleted_and_events_cannot_be_touched(self, platform) -> None:
        """Tasks archive; events append. Neither is a promise — both are
        privileges the application role simply does not hold."""
        rows = await platform.execute(
            text("""
                SELECT table_name, privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = 'cairn_app'
                  AND table_name IN ('tasks', 'task_events')
            """)
        )
        grants: dict[str, set[str]] = {}
        for table, privilege in rows:
            grants.setdefault(table, set()).add(privilege)

        assert grants["tasks"] == {"SELECT", "INSERT", "UPDATE"}
        # Append-only: the review handoff reads this history back, so its
        # immutability is what makes "a second pair of eyes" enforceable.
        assert grants["task_events"] == {"SELECT", "INSERT"}

    async def test_the_database_refuses_an_event_update(self, platform) -> None:
        tenant = await _tenant(platform, "append")
        await platform.commit()
        async with tenant_session(tenant.id) as session:
            project = await _project(session, tenant, "Audit")
            task = await _task(session, tenant, project)
            session.add(
                TaskEvent(
                    tenant_id=tenant.id,
                    task_id=task.id,
                    kind=TaskEventKind.CREATED,
                    at=datetime.now(UTC),
                )
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            with pytest.raises((DBAPIError, ProgrammingError)):
                await session.execute(text("UPDATE task_events SET kind = 'archived'"))
                await session.commit()


class TestSymmetry:
    @integration
    async def test_every_role_reads_the_same_bytes(self, platform) -> None:
        tenant = await _tenant(platform, "sym")
        creator = await _user(platform, tenant, TenantRole.OWNER)
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            project = await _project(session, tenant, "Rate limiting")
            person = await _person(session, tenant, "Priya Sharma")
            await _member(session, tenant, project, person)
            task = await _task(session, tenant, project, creator=creator, assignee=person)
            session.add(
                TaskEvent(
                    tenant_id=tenant.id,
                    task_id=task.id,
                    kind=TaskEventKind.CREATED,
                    actor_user_id=creator.id,
                    at=datetime.now(UTC),
                )
            )
            await session.commit()
            task_id, project_id = task.id, project.id

        async with tenant_session(tenant.id) as session:
            details = [
                (
                    await tasks_router.task_detail_payload(
                        session, tenant_id=tenant.id, task_id=task_id
                    )
                ).model_dump_json()
                for _ in range(4)
            ]
            listings = [
                (
                    await tasks_router.list_tasks_payload(
                        session, tenant_id=tenant.id, project_id=project_id
                    )
                ).model_dump_json()
                for _ in range(4)
            ]

        assert len(set(details)) == 1, "task detail depended on who asked"
        assert len(set(listings)) == 1, "the board depended on who asked"

    def test_the_payload_functions_take_no_caller(self) -> None:
        import inspect

        for function in (
            tasks_router.list_tasks_payload,
            tasks_router.task_detail_payload,
            tasks_router.my_tasks_payload,
        ):
            parameters = set(inspect.signature(function).parameters)
            for forbidden in ("role", "caller", "viewer", "user", "context"):
                assert forbidden not in parameters, (
                    f"{function.__name__} can see who is asking, so symmetry is a promise "
                    "rather than a structure"
                )


class TestNothingMeasuresAPerson:
    #: Compiled once, word-boundaried, and sanity-checked below: a previous
    #: guard silently matched nothing because of pasted control characters.
    FORBIDDEN = re.compile(
        r"\b(score|rank|top|most|leaderboard|productivity|performance|velocity)\b",
        re.IGNORECASE,
    )

    def test_the_guard_itself_matches(self) -> None:
        """A vocabulary guard that cannot match its own vocabulary is worse
        than none — it certifies clean what it never read."""
        assert self.FORBIDDEN.search("a Leaderboard of tasks")
        assert self.FORBIDDEN.search("velocity")
        assert not self.FORBIDDEN.search("stopwatch")  # no substring false hits

    def test_no_task_model_carries_ranking_vocabulary(self) -> None:
        for model_name in (
            "TaskSummary",
            "TaskListResponse",
            "TaskEventEntry",
            "TaskDetailResponse",
            "MyTasksResponse",
        ):
            model = getattr(schemas, model_name)
            for field_name in model.model_fields:
                assert not self.FORBIDDEN.search(field_name), (
                    f"{model_name}.{field_name} carries ranking vocabulary"
                )
                for extra in ("count", "total", "activity", "last_active"):
                    assert extra not in field_name.lower(), (
                        f"{model_name}.{field_name} contains '{extra}'"
                    )

    def test_a_rendered_payload_carries_no_ranking_vocabulary(self) -> None:
        """The grep on actual bytes, not just field names: sentences are
        server-rendered, so the words themselves are part of the contract."""
        entry = schemas.TaskEventEntry(sentence="Ali moved this task.", at=datetime.now(UTC))
        detail = schemas.TaskDetailResponse(
            id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            title="Migrate invoice PDFs to the new template",
            description="",
            state="todo",
            priority="normal",
            created_at=datetime.now(UTC),
            events=[entry],
        )
        assert not self.FORBIDDEN.search(detail.model_dump_json())

    def test_every_event_sentence_is_neutral(self) -> None:
        """Every kind the enum can hold, rendered and grepped."""
        for kind in TaskEventKind:
            event = TaskEvent(
                tenant_id=uuid.uuid4(),
                task_id=uuid.uuid4(),
                kind=kind,
                from_state=TaskState.IN_PROGRESS,
                to_state=TaskState.IN_REVIEW,
                at=datetime.now(UTC),
            )
            sentence = tasks_router._sentence(event, "Ali")
            assert not self.FORBIDDEN.search(sentence), f"{kind}: {sentence!r}"

    def test_the_summary_field_set_is_pinned(self) -> None:
        assert set(schemas.TaskSummary.model_fields) == {
            "id",
            "project_id",
            "title",
            "description",
            "state",
            "priority",
            "assignee_person_id",
            "assignee_name",
            "due_on",
            "created_at",
            "archived_at",
        }

    def test_my_tasks_groups_are_states_not_metrics(self) -> None:
        assert set(schemas.MyTasksResponse.model_fields) == {
            "todo",
            "in_progress",
            "in_review",
            "blocked",
            "done",
        }


class TestTheTransitionTableIsClosed:
    def test_the_legal_set_is_exactly_the_designed_eight(self) -> None:
        """Pinned as data: adding a shortcut edge is a product decision, and
        this test is where that decision becomes visible."""
        s = TaskState
        designed = frozenset(
            {
                (s.TODO, s.IN_PROGRESS),
                (s.TODO, s.BLOCKED),
                (s.IN_PROGRESS, s.IN_REVIEW),
                (s.IN_PROGRESS, s.BLOCKED),
                (s.BLOCKED, s.IN_PROGRESS),
                (s.BLOCKED, s.TODO),
                (s.IN_REVIEW, s.IN_PROGRESS),
                (s.IN_REVIEW, s.DONE),
            }
        )
        actual = tasks_router._LEGAL_TRANSITIONS
        assert actual == designed

    def test_done_is_a_source_of_nothing(self) -> None:
        assert not any(source is TaskState.DONE for source, _ in tasks_router._LEGAL_TRANSITIONS), (
            "done grew an outgoing edge; done is terminal"
        )


@integration
class TestWorkflowEnforcement:
    async def test_the_full_legal_walk(self, platform) -> None:
        """One task crosses all eight legal edges (with a second reviewer for
        the final approval), and its state is what each move said."""
        tenant, alice, project_id = await _board(platform, "walk")
        bob = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            task = await _task(
                session,
                tenant,
                (await session.get(Project, project_id)),
                title="Harden the webhook signature check",
            )
            await session.commit()
            task_id = task.id

        walk = [
            ("blocked", alice),  # todo -> blocked
            ("todo", alice),  # blocked -> todo
            ("in_progress", alice),  # todo -> in_progress
            ("blocked", alice),  # in_progress -> blocked
            ("in_progress", alice),  # blocked -> in_progress
            ("in_review", alice),  # in_progress -> in_review
            ("in_progress", alice),  # in_review -> in_progress (sent back)
            ("in_review", alice),  # in_progress -> in_review
            ("done", bob),  # in_review -> done, by somebody else
        ]
        for state, actor in walk:
            payload = await _move(tenant, actor, task_id, state)
            assert payload.state == state

    @pytest.mark.parametrize(
        ("start", "target"),
        [
            ("todo", "in_review"),
            ("todo", "done"),
            ("in_progress", "todo"),
            ("in_progress", "done"),
            ("blocked", "in_review"),
            ("blocked", "done"),
            ("in_review", "todo"),
            ("in_review", "blocked"),
        ],
    )
    async def test_every_illegal_move_is_a_409_naming_both_states(
        self, platform, start: str, target: str
    ) -> None:
        tenant, user, project_id = await _board(platform, "illegal")
        async with tenant_session(tenant.id) as session:
            task = await _task(
                session,
                tenant,
                (await session.get(Project, project_id)),
                state=TaskState(start),
            )
            await session.commit()
            task_id = task.id

        with pytest.raises(ProblemDetailError) as excinfo:
            await _move(tenant, user, task_id, target)
        assert excinfo.value.status_code == 409
        assert start in excinfo.value.detail and target in excinfo.value.detail

    @pytest.mark.parametrize("target", ["todo", "in_progress", "in_review", "blocked"])
    async def test_done_is_terminal_and_says_what_to_do_instead(
        self, platform, target: str
    ) -> None:
        tenant, user, project_id = await _board(platform, "done")
        async with tenant_session(tenant.id) as session:
            task = await _task(
                session, tenant, (await session.get(Project, project_id)), state=TaskState.DONE
            )
            await session.commit()
            task_id = task.id

        with pytest.raises(ProblemDetailError) as excinfo:
            await _move(tenant, user, task_id, target)
        assert excinfo.value.status_code == 409
        assert "archive" in excinfo.value.detail.lower()

    async def test_an_archived_task_refuses_state_changes(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "archst")
        async with tenant_session(tenant.id) as session:
            task = await _task(session, tenant, (await session.get(Project, project_id)))
            task.archived_at = datetime.now(UTC)
            await session.commit()
            task_id = task.id

        with pytest.raises(ProblemDetailError) as excinfo:
            await _move(tenant, user, task_id, "in_progress")
        assert excinfo.value.status_code == 409

    async def test_an_archived_task_refuses_edits(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "arched")
        async with tenant_session(tenant.id) as session:
            task = await _task(session, tenant, (await session.get(Project, project_id)))
            task.archived_at = datetime.now(UTC)
            await session.commit()
            task_id = task.id

        async with tenant_session(tenant.id) as session:
            with pytest.raises(ProblemDetailError) as excinfo:
                await tasks_router.update_task(
                    _context(user, tenant, TenantRole.OWNER),
                    session,
                    task_id,
                    TaskUpdate(title="New title"),
                )
        assert excinfo.value.status_code == 409

    async def test_moving_a_task_never_writes_the_project(self, platform) -> None:
        """Task state is task state: a project's state is declared by a
        human, never derived from its board."""
        tenant, user, project_id = await _board(platform, "noproj")
        async with tenant_session(tenant.id) as session:
            task = await _task(session, tenant, (await session.get(Project, project_id)))
            await session.commit()
            task_id = task.id

        await _move(tenant, user, task_id, "in_progress")

        async with tenant_session(tenant.id) as session:
            project = await session.get(Project, project_id)
            assert project.state.value == "unknown"
            assert project.state_declared_by_user_id is None


@integration
class TestTheReviewHandoff:
    async def _reviewed_task(self, platform, slug: str):
        tenant, alice, project_id = await _board(platform, slug)
        async with tenant_session(tenant.id) as session:
            task = await _task(session, tenant, (await session.get(Project, project_id)))
            await session.commit()
            task_id = task.id
        await _move(tenant, alice, task_id, "in_progress")
        await _move(tenant, alice, task_id, "in_review")
        return tenant, alice, task_id

    async def test_the_same_user_cannot_approve_their_own_review(self, platform) -> None:
        tenant, alice, task_id = await self._reviewed_task(platform, "same")
        with pytest.raises(ProblemDetailError) as excinfo:
            await _move(tenant, alice, task_id, "done")
        assert excinfo.value.status_code == 409
        assert "somebody else" in excinfo.value.detail

    async def test_a_second_user_can(self, platform) -> None:
        tenant, _alice, task_id = await self._reviewed_task(platform, "second")
        bob = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()
        payload = await _move(tenant, bob, task_id, "done", role=TenantRole.MEMBER)
        assert payload.state == "done"

    async def test_the_latest_review_request_is_the_one_that_counts(self, platform) -> None:
        """Alice sends it to review, Bob sends it back, Bob re-requests
        review — now *Bob* is the requester, and Bob may not approve."""
        tenant, alice, task_id = await self._reviewed_task(platform, "latest")
        bob = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()

        await _move(tenant, bob, task_id, "in_progress", role=TenantRole.MEMBER)
        await _move(tenant, bob, task_id, "in_review", role=TenantRole.MEMBER)

        with pytest.raises(ProblemDetailError):
            await _move(tenant, bob, task_id, "done", role=TenantRole.MEMBER)
        payload = await _move(tenant, alice, task_id, "done")
        assert payload.state == "done"


class TestPermissionGating:
    def test_members_write_and_viewers_do_not(self) -> None:
        """The reason TASKS_WRITE exists: before it, Member and Viewer held
        identical sets, and 'member and up may write tasks' was unstateable."""
        from cairn_api.auth.permissions import Permission, has_permission

        assert has_permission(TenantRole.OWNER, Permission.TASKS_WRITE)
        assert has_permission(TenantRole.ADMIN, Permission.TASKS_WRITE)
        assert has_permission(TenantRole.MEMBER, Permission.TASKS_WRITE)
        assert not has_permission(TenantRole.VIEWER, Permission.TASKS_WRITE)
        assert has_permission(TenantRole.VIEWER, Permission.CONTENT_READ)

    def test_every_mutating_route_declares_the_gate(self) -> None:
        import inspect

        source = inspect.getsource(tasks_router)
        mutations = source.count("@router.post") + source.count("@router.patch")
        gated = source.count("requires(Permission.TASKS_WRITE)")
        assert gated == mutations, (
            f"{mutations} mutating routes but {gated} TASKS_WRITE gates - one is ungated"
        )

    def test_the_permission_has_no_monitoring_vocabulary(self) -> None:
        from cairn_api.auth.permissions import Permission

        assert Permission.TASKS_WRITE.value == "tasks.write"


@integration
class TestAssignment:
    async def test_the_assignee_must_be_an_active_project_member(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "assign")
        async with tenant_session(tenant.id) as session:
            outsider = await _person(session, tenant, "Not On This Project")
            await session.commit()
            outsider_id = outsider.id

        async with tenant_session(tenant.id) as session:
            with pytest.raises(ProblemDetailError) as excinfo:
                await tasks_router.create_task(
                    _context(user, tenant, TenantRole.OWNER),
                    session,
                    project_id,
                    TaskCreate(title="Ship it", assignee_person_id=outsider_id),
                )
        assert excinfo.value.status_code == 422

    async def test_a_removed_member_is_not_assignable(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "removed")
        async with tenant_session(tenant.id) as session:
            project = await session.get(Project, project_id)
            person = await _person(session, tenant, "Former member")
            membership = await _member(session, tenant, project, person)
            membership.removed_at = datetime.now(UTC)
            await session.commit()
            person_id = person.id

        async with tenant_session(tenant.id) as session:
            with pytest.raises(ProblemDetailError) as excinfo:
                await tasks_router.create_task(
                    _context(user, tenant, TenantRole.OWNER),
                    session,
                    project_id,
                    TaskCreate(title="Ship it", assignee_person_id=person_id),
                )
        assert excinfo.value.status_code == 422

    async def test_unassigned_is_a_real_state(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "unassigned")
        async with tenant_session(tenant.id) as session:
            payload = await tasks_router.create_task(
                _context(user, tenant, TenantRole.OWNER),
                session,
                project_id,
                TaskCreate(title="Triage the flaky nightly build"),
            )
        assert payload.assignee_person_id is None
        assert payload.assignee_name is None


@integration
class TestEveryEditLeavesItsOwnEvent:
    async def test_each_changed_field_emits_its_kind(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "events")
        async with tenant_session(tenant.id) as session:
            project = await session.get(Project, project_id)
            person = await _person(session, tenant, "Priya Sharma")
            await _member(session, tenant, project, person)
            await session.commit()
            person_id = person.id

        async with tenant_session(tenant.id) as session:
            created = await tasks_router.create_task(
                _context(user, tenant, TenantRole.OWNER),
                session,
                project_id,
                TaskCreate(title="Migrate invoice PDFs to the new template"),
            )
            task_id = created.id

        edits = [
            (TaskUpdate(title="Migrate invoice PDFs"), TaskEventKind.RETITLED),
            (TaskUpdate(description="Use the 2026 template."), TaskEventKind.DESCRIBED),
            (TaskUpdate(priority="high"), TaskEventKind.REPRIORITISED),
            (TaskUpdate(due_on=date(2026, 9, 1)), TaskEventKind.RESCHEDULED),
            (TaskUpdate(assignee_person_id=person_id), TaskEventKind.REASSIGNED),
            (TaskUpdate(assignee_person_id=None), TaskEventKind.UNASSIGNED),
        ]
        for body, _ in edits:
            async with tenant_session(tenant.id) as session:
                await tasks_router.update_task(
                    _context(user, tenant, TenantRole.OWNER), session, task_id, body
                )

        async with tenant_session(tenant.id) as session:
            kinds = [
                event.kind
                for event in (
                    await session.scalars(
                        select(TaskEvent)
                        .where(TaskEvent.task_id == task_id)
                        .order_by(TaskEvent.at, TaskEvent.id)
                    )
                ).all()
            ]
        assert kinds == [TaskEventKind.CREATED, *(kind for _, kind in edits)]

    async def test_an_unchanged_field_emits_nothing(self, platform) -> None:
        """Sending the same title back is not a retitle; an omitted assignee
        is not an unassignment."""
        tenant, user, project_id = await _board(platform, "noop")
        async with tenant_session(tenant.id) as session:
            created = await tasks_router.create_task(
                _context(user, tenant, TenantRole.OWNER),
                session,
                project_id,
                TaskCreate(title="Rotate the staging TLS certificates"),
            )
            task_id = created.id

        async with tenant_session(tenant.id) as session:
            await tasks_router.update_task(
                _context(user, tenant, TenantRole.OWNER),
                session,
                task_id,
                TaskUpdate(title="Rotate the staging TLS certificates"),
            )

        async with tenant_session(tenant.id) as session:
            events = (
                await session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id))
            ).all()
        assert [event.kind for event in events] == [TaskEventKind.CREATED]

    async def test_events_render_as_sentences_with_actor_names(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "sentences")
        async with tenant_session(tenant.id) as session:
            created = await tasks_router.create_task(
                _context(user, tenant, TenantRole.OWNER),
                session,
                project_id,
                TaskCreate(title="Add retry with backoff to the Slack poster"),
            )
            task_id = created.id
        await _move(tenant, user, task_id, "in_progress")

        async with tenant_session(tenant.id) as session:
            detail = await tasks_router.task_detail_payload(
                session, tenant_id=tenant.id, task_id=task_id
            )
        sentences = [event.sentence for event in detail.events]
        assert sentences[0] == "owner person created this task."
        assert sentences[1] == "owner person moved this task from To do to In progress."


@integration
class TestArchiveAndRestore:
    async def test_the_creator_may_archive_their_own_task(self, platform) -> None:
        tenant, _owner, project_id = await _board(platform, "arch1")
        member = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()
        async with tenant_session(tenant.id) as session:
            created = await tasks_router.create_task(
                _context(member, tenant, TenantRole.MEMBER),
                session,
                project_id,
                TaskCreate(title="Remove the deprecated v0 export endpoint"),
            )
            task_id = created.id

        async with tenant_session(tenant.id) as session:
            payload = await tasks_router.archive_task(
                _context(member, tenant, TenantRole.MEMBER), session, task_id
            )
        assert payload.archived_at is not None

    async def test_a_member_cannot_archive_somebody_elses_task(self, platform) -> None:
        tenant, owner, project_id = await _board(platform, "arch2")
        member = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()
        async with tenant_session(tenant.id) as session:
            created = await tasks_router.create_task(
                _context(owner, tenant, TenantRole.OWNER),
                session,
                project_id,
                TaskCreate(title="Document the ingestion retry semantics"),
            )
            task_id = created.id

        async with tenant_session(tenant.id) as session:
            with pytest.raises(ProblemDetailError) as excinfo:
                await tasks_router.archive_task(
                    _context(member, tenant, TenantRole.MEMBER), session, task_id
                )
        assert excinfo.value.status_code == 403

    async def test_an_admin_may_archive_and_restore_any_task(self, platform) -> None:
        tenant, owner, project_id = await _board(platform, "arch3")
        admin = await _user(platform, tenant, TenantRole.ADMIN)
        await platform.commit()
        async with tenant_session(tenant.id) as session:
            created = await tasks_router.create_task(
                _context(owner, tenant, TenantRole.OWNER),
                session,
                project_id,
                TaskCreate(title="Backfill missing evidence URLs"),
            )
            task_id = created.id

        async with tenant_session(tenant.id) as session:
            archived = await tasks_router.archive_task(
                _context(admin, tenant, TenantRole.ADMIN), session, task_id
            )
            assert archived.archived_at is not None
        async with tenant_session(tenant.id) as session:
            restored = await tasks_router.restore_task(
                _context(admin, tenant, TenantRole.ADMIN), session, task_id
            )
            assert restored.archived_at is None

    async def test_archived_tasks_leave_the_board_but_not_the_record(self, platform) -> None:
        tenant, owner, project_id = await _board(platform, "arch4")
        async with tenant_session(tenant.id) as session:
            created = await tasks_router.create_task(
                _context(owner, tenant, TenantRole.OWNER),
                session,
                project_id,
                TaskCreate(title="Prune orphaned webhook subscriptions"),
            )
            task_id = created.id
        async with tenant_session(tenant.id) as session:
            await tasks_router.archive_task(
                _context(owner, tenant, TenantRole.OWNER), session, task_id
            )

        async with tenant_session(tenant.id) as session:
            board = await tasks_router.list_tasks_payload(
                session, tenant_id=tenant.id, project_id=project_id
            )
            assert all(task.id != task_id for task in board.tasks)
            everything = await tasks_router.list_tasks_payload(
                session, tenant_id=tenant.id, project_id=project_id, include_archived=True
            )
            assert any(task.id == task_id for task in everything.tasks)


@integration
class TestMyTasks:
    async def test_grouped_by_state_and_scoped_to_my_person(self, platform) -> None:
        tenant = await _tenant(platform, "mine")
        me = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            project = await _project(session, tenant, "Billing")
            my_person = await _person(session, tenant, "Me", user_id=me.id)
            other = await _person(session, tenant, "Somebody Else")
            for person in (my_person, other):
                await _member(session, tenant, project, person)
            for state in (
                TaskState.TODO,
                TaskState.IN_PROGRESS,
                TaskState.IN_REVIEW,
                TaskState.BLOCKED,
                TaskState.DONE,
            ):
                await _task(
                    session,
                    tenant,
                    project,
                    title=f"Mine, {state.value}",
                    state=state,
                    assignee=my_person,
                )
            await _task(session, tenant, project, title="Not mine", assignee=other)
            await session.commit()
            my_person_id = my_person.id

        async with tenant_session(tenant.id) as session:
            payload = await tasks_router.my_tasks_payload(
                session, tenant_id=tenant.id, person_id=my_person_id
            )

        assert [task.title for task in payload.todo] == ["Mine, todo"]
        assert [task.title for task in payload.in_progress] == ["Mine, in_progress"]
        assert [task.title for task in payload.in_review] == ["Mine, in_review"]
        assert [task.title for task in payload.blocked] == ["Mine, blocked"]
        assert [task.title for task in payload.done] == ["Mine, done"]

    async def test_done_carries_only_the_latest_ten(self, platform) -> None:
        tenant = await _tenant(platform, "ten")
        me = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            project = await _project(session, tenant, "Cleanup")
            my_person = await _person(session, tenant, "Me", user_id=me.id)
            await _member(session, tenant, project, my_person)
            for index in range(12):
                await _task(
                    session,
                    tenant,
                    project,
                    title=f"Done thing {index}",
                    state=TaskState.DONE,
                    assignee=my_person,
                )
            await session.commit()
            my_person_id = my_person.id

        async with tenant_session(tenant.id) as session:
            payload = await tasks_router.my_tasks_payload(
                session, tenant_id=tenant.id, person_id=my_person_id
            )
        assert len(payload.done) == 10

    async def test_no_person_row_means_empty_groups_not_404(self, platform) -> None:
        tenant = await _tenant(platform, "noperson")
        await platform.commit()
        async with tenant_session(tenant.id) as session:
            payload = await tasks_router.my_tasks_payload(
                session, tenant_id=tenant.id, person_id=None
            )
        assert payload == schemas.MyTasksResponse()


@integration
class TestBoardOrderIsCreationOrder:
    async def test_the_board_orders_by_created_at_never_by_activity(self, platform) -> None:
        board_stage = await _board(platform, "order")
        tenant, project_id = board_stage[0], board_stage[2]
        titles = ["First filed", "Second filed", "Third filed"]
        base = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
        async with tenant_session(tenant.id) as session:
            project = await session.get(Project, project_id)
            for index, title in enumerate(titles):
                task = await _task(session, tenant, project, title=title)
                task.created_at = base.replace(minute=index)
            await session.commit()

        # Touch the first task last — activity must not reorder anything.
        async with tenant_session(tenant.id) as session:
            first = await session.scalar(select(Task).where(Task.title == "First filed"))
            first.priority = first.priority  # no-op write path; order key is created_at
            await session.commit()

        async with tenant_session(tenant.id) as session:
            board = await tasks_router.list_tasks_payload(
                session, tenant_id=tenant.id, project_id=project_id
            )
        assert [task.title for task in board.tasks] == titles


async def _create(tenant, user, project_id, body: TaskCreate, *, role=TenantRole.OWNER):
    async with tenant_session(tenant.id) as session:
        return await tasks_router.create_task(
            _context(user, tenant, role), session, project_id, body
        )


async def _events(tenant, task_id) -> list[TaskEvent]:
    async with tenant_session(tenant.id) as session:
        rows = await session.scalars(
            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.at)
        )
        return list(rows)


class TestCreatingIntoAColumnIsSchemaGated:
    """Every column on the board has an "Add task"; `blocked` has none, and
    the schema is where that is decided."""

    def test_each_creatable_column_is_accepted(self) -> None:
        for state in ("todo", "in_progress", "in_review", "done"):
            assert TaskCreate(title="Ship it", state=state).state == state

    def test_todo_is_still_the_default(self) -> None:
        assert TaskCreate(title="Ship it").state == "todo"

    def test_blocked_is_not_creatable(self) -> None:
        """A task is blocked by something that happened to it — there is no
        honest history in which it begins blocked."""
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            TaskCreate(title="Ship it", state="blocked")

    def test_a_nonsense_state_is_refused(self) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            TaskCreate(title="Ship it", state="shipped")

    def test_viewers_still_cannot_create_in_any_column(self) -> None:
        import inspect

        from cairn_api.auth.permissions import Permission, has_permission

        assert not has_permission(TenantRole.VIEWER, Permission.TASKS_WRITE)
        assert "requires(Permission.TASKS_WRITE)" in inspect.getsource(tasks_router.create_task)


@integration
class TestCreatingIntoAColumn:
    async def test_a_task_lands_in_the_column_it_was_created_in(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "landing")
        for state in ("todo", "in_progress", "in_review", "done"):
            payload = await _create(
                tenant, user, project_id, TaskCreate(title=f"Opened in {state}", state=state)
            )
            assert payload.state == state
            async with tenant_session(tenant.id) as session:
                task = await session.get(Task, payload.id)
                assert task.state.value == state

    @pytest.mark.parametrize(
        ("state", "sentence"),
        [
            ("todo", "owner person created this task."),
            ("in_progress", "owner person created this task, already in progress."),
            ("in_review", "owner person created this task, already in review."),
            ("done", "owner person recorded this task as already done."),
        ],
    )
    async def test_the_event_says_how_the_task_got_there(
        self, platform, state: str, sentence: str
    ) -> None:
        tenant, user, project_id = await _board(platform, f"say{state}")
        payload = await _create(
            tenant, user, project_id, TaskCreate(title="Restore the nightly backup", state=state)
        )
        assert [entry.sentence for entry in payload.events] == [sentence]

    async def test_creation_never_synthesises_a_walk(self, platform) -> None:
        """One creation, one event — not a chain of invented moves through
        columns the task never sat in."""
        tenant, user, project_id = await _board(platform, "nowalk")
        payload = await _create(
            tenant, user, project_id, TaskCreate(title="Ship the importer", state="in_review")
        )
        events = await _events(tenant, payload.id)
        assert [event.kind for event in events] == [TaskEventKind.CREATED]
        assert events[0].from_state is None
        assert events[0].to_state is TaskState.IN_REVIEW

    async def test_done_on_create_is_recorded_not_reviewed(self, platform) -> None:
        """Recording already-finished work is a different act from approving
        a review, and the trail must say which one happened — forever."""
        tenant, user, project_id = await _board(platform, "recorded")
        payload = await _create(
            tenant, user, project_id, TaskCreate(title="Renew the TLS certificate", state="done")
        )
        events = await _events(tenant, payload.id)
        assert [event.kind for event in events] == [TaskEventKind.RECORDED_DONE]
        assert not any(event.kind is TaskEventKind.STATE_CHANGED for event in events)
        sentences = [entry.sentence for entry in payload.events]
        assert sentences == ["owner person recorded this task as already done."]
        # Never the transition's wording: no move to Done happened.
        assert "moved this task" not in sentences[0]

    async def test_the_assignee_rule_still_applies_with_a_state(self, platform) -> None:
        tenant, user, project_id = await _board(platform, "createassign")
        async with tenant_session(tenant.id) as session:
            outsider = await _person(session, tenant, "Not On This Project")
            await session.commit()
            outsider_id = outsider.id

        with pytest.raises(ProblemDetailError) as excinfo:
            await _create(
                tenant,
                user,
                project_id,
                TaskCreate(title="Ship it", state="in_progress", assignee_person_id=outsider_id),
            )
        assert excinfo.value.status_code == 422


@integration
class TestCreatingInReviewDoesNotDodgeTheHandoff:
    """The create endpoint must not become a way around the one rule that
    insists two humans took part."""

    async def test_the_creator_cannot_approve_the_review_they_opened(self, platform) -> None:
        tenant, alice, project_id = await _board(platform, "dodge")
        payload = await _create(
            tenant, alice, project_id, TaskCreate(title="Audit the RLS grants", state="in_review")
        )
        with pytest.raises(ProblemDetailError) as excinfo:
            await _move(tenant, alice, payload.id, "done")
        assert excinfo.value.status_code == 409
        assert "somebody else" in excinfo.value.detail

    async def test_a_second_user_may(self, platform) -> None:
        tenant, alice, project_id = await _board(platform, "dodge2")
        payload = await _create(
            tenant, alice, project_id, TaskCreate(title="Audit the RLS grants", state="in_review")
        )
        bob = await _user(platform, tenant, TenantRole.MEMBER)
        await platform.commit()
        moved = await _move(tenant, bob, payload.id, "done", role=TenantRole.MEMBER)
        assert moved.state == "done"

    async def test_the_state_endpoint_still_refuses_the_illegal_moves(self, platform) -> None:
        """Creating into a column places a task; it never widens the
        transition table. Done stays terminal."""
        tenant, user, project_id = await _board(platform, "terminal")
        payload = await _create(
            tenant, user, project_id, TaskCreate(title="Renew the TLS certificate", state="done")
        )
        with pytest.raises(ProblemDetailError) as excinfo:
            await _move(tenant, user, payload.id, "todo")
        assert excinfo.value.status_code == 409
