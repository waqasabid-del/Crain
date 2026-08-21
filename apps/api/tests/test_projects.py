"""The project layer, and the four promises it must keep.

*Symmetric.* Owner, Admin, Member and Viewer receive byte-identical project
data; the role gates writes only. Asserted the finder's way — the payload
functions take no role, so symmetry is structural rather than polite.

*Nothing measures a person.* A project response carries identity, a
self-recognisable role, and the audit trail of how a membership row came to be.
The field set is pinned and the vocabulary grepped, because the failure is
additive: nobody deletes the boundary, somebody adds a count beside a name.

*No silent membership.* Every add and remove is durable in the row itself and
visible to every member; removal closes the interval instead of deleting it.

*Declared, never inferred.* A project state is written by one endpoint and
stamped with who said so. A project nobody classified is `unknown`, and
`unknown` stays unknown however much activity its sources carry.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from cairn_api.api import schemas
from cairn_api.api.routers import projects as projects_router
from cairn_api.db.fact_models import Fact, FactSource
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.project_models import Project, ProjectMember, ProjectSource, ProjectState
from cairn_api.db.tenancy import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

#: Per class, not per module. The boundary tests below - the vocabulary grep,
#: the pinned field set, the rollup's missing kinds, the permission table - are
#: pure inspection of the code, and they are the tests most worth running when
#: somebody has no database in front of them. Marking the module would have
#: skipped exactly those, silently.
integration = pytest.mark.integration

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)

#: Resolved at import time - a filesystem call inside an async test runs on the
#: event loop, and this location never changes.
MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260821_1000_project_layer.py"
)


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


async def _person(session, tenant: Tenant, name: str) -> Person:
    person = Person(tenant_id=tenant.id, display_name=name)
    session.add(person)
    await session.flush()
    return person


async def _fact(session, tenant: Tenant, *, kind: str, statement: str, project: str, days: int):
    fact = Fact(
        tenant_id=tenant.id,
        kind=kind,
        statement=statement,
        certainty="verified",
        valid_from=NOW - timedelta(days=days),
        occurred_at=NOW - timedelta(days=days),
    )
    session.add(fact)
    await session.flush()
    session.add(
        FactSource(
            tenant_id=tenant.id,
            fact_id=fact.id,
            source="github",
            evidence_id=f"ev-{uuid.uuid4().hex[:8]}",
            url="https://github.com/acme/api/pull/1",
            project=project,
        )
    )
    await session.flush()
    return fact


@integration
class TestTenantIsolation:
    """The non-negotiable: one workspace's projects are invisible to another,
    enforced by the database rather than by a WHERE clause somebody might
    forget."""

    async def test_a_project_is_invisible_across_the_tenant_boundary(self, platform) -> None:
        first = await _tenant(platform, "first")
        second = await _tenant(platform, "second")
        await platform.commit()

        async with tenant_session(first.id) as session:
            session.add(Project(tenant_id=first.id, name="Payments"))
            await session.commit()

        async with tenant_session(second.id) as session:
            rows = (await session.scalars(select(Project))).all()
            assert rows == [], "another workspace's project was visible"

    async def test_rls_refuses_a_write_for_another_tenant(self, platform) -> None:
        first = await _tenant(platform, "rlsfirst")
        second = await _tenant(platform, "rlssecond")
        await platform.commit()

        async with tenant_session(first.id) as session:
            session.add(Project(tenant_id=second.id, name="Smuggled"))
            # `DBAPIError`, not `IntegrityError`: a policy refusal arrives as
            # an insufficient-privilege error, and naming the narrower class
            # would make this test pass for the wrong reason if the policy were
            # ever replaced by a constraint.
            with pytest.raises(DBAPIError):
                await session.commit()
            # The transaction is aborted; roll it back inside the block so the
            # context manager's own close does not raise over the real error.
            await session.rollback()

    async def test_membership_and_claims_are_isolated_too(self, platform) -> None:
        first = await _tenant(platform, "isofirst")
        second = await _tenant(platform, "isosecond")
        await platform.commit()

        async with tenant_session(first.id) as session:
            person = await _person(session, first, "Priya")
            project = Project(tenant_id=first.id, name="Ledger")
            session.add(project)
            await session.flush()
            session.add(
                ProjectMember(tenant_id=first.id, project_id=project.id, person_id=person.id)
            )
            session.add(ProjectSource(tenant_id=first.id, project_id=project.id, value="acme/api"))
            await session.commit()

        async with tenant_session(second.id) as session:
            assert (await session.scalars(select(ProjectMember))).all() == []
            assert (await session.scalars(select(ProjectSource))).all() == []


@integration
class TestTheGrantsAreAnAllowList:
    async def test_no_delete_on_projects_or_membership(self, platform) -> None:
        """Archive, not delete; close the interval, not erase the row. Both are
        privileges the application role simply does not hold."""
        rows = await platform.execute(
            text("""
                SELECT table_name, privilege_type
                FROM information_schema.role_table_grants
                WHERE grantee = 'cairn_app'
                  AND table_name IN ('projects', 'project_members', 'project_sources')
            """)
        )
        grants: dict[str, set[str]] = {}
        for table, privilege in rows:
            grants.setdefault(table, set()).add(privilege)

        assert grants["projects"] == {"SELECT", "INSERT", "UPDATE"}
        assert grants["project_members"] == {"SELECT", "INSERT", "UPDATE"}
        # A claim is configuration, not evidence: releasing one deletes the
        # mapping while every citation keeps its raw string.
        assert grants["project_sources"] == {"SELECT", "INSERT", "DELETE"}


class TestSymmetry:
    @integration
    async def test_every_role_reads_the_same_bytes(self, platform) -> None:
        """The finder's idiom: call the payload function once per role and
        compare the serialised strings. It takes no role argument, which is how
        the guarantee is structural."""
        tenant = await _tenant(platform, "sym")
        for role in (TenantRole.OWNER, TenantRole.ADMIN, TenantRole.MEMBER, TenantRole.VIEWER):
            await _user(platform, tenant, role)
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            project = Project(tenant_id=tenant.id, name="Rate limiting", state=ProjectState.ACTIVE)
            session.add(project)
            await session.flush()
            session.add(ProjectSource(tenant_id=tenant.id, project_id=project.id, value="acme/api"))
            await _fact(
                session,
                tenant,
                kind="delivery",
                statement="Rate limiting shipped to production.",
                project="acme/api",
                days=1,
            )
            await session.commit()
            project_id = project.id

        async with tenant_session(tenant.id) as session:
            # Four calls standing in for four roles: the function has nowhere
            # to put one, so the bytes cannot diverge.
            payloads = [
                (
                    await projects_router.project_detail_payload(
                        session, tenant_id=tenant.id, project_id=project_id
                    )
                ).model_dump_json()
                for _ in range(4)
            ]
            listings = [
                (
                    await projects_router.list_projects_payload(session, tenant_id=tenant.id)
                ).model_dump_json()
                for _ in range(4)
            ]

        assert len(set(payloads)) == 1, "project detail depended on who asked"
        assert len(set(listings)) == 1, "the portfolio depended on who asked"

    def test_the_payload_functions_take_no_caller(self) -> None:
        import inspect

        for function in (
            projects_router.project_detail_payload,
            projects_router.list_projects_payload,
        ):
            parameters = set(inspect.signature(function).parameters)
            for forbidden in ("role", "caller", "viewer", "user", "context"):
                assert forbidden not in parameters, (
                    f"{function.__name__} can see who is asking, so symmetry is a promise "
                    "rather than a structure"
                )


class TestNothingMeasuresAPerson:
    def test_no_response_model_carries_ranking_vocabulary(self) -> None:
        """The grep, in the finder's idiom. The failure this catches is
        additive: a `delivered_count` beside a person's name is one careless
        commit away, and it would be a per-person dashboard."""
        forbidden = (
            "score",
            "rank",
            "relevance",
            "strength",
            "percent",
            "monitor",
            "evaluate",
            "performance",
            "productivity",
            "velocity",
            "count",
            "total",
            "activity",
            "last_active",
        )
        for model_name in (
            "ProjectSummary",
            "ProjectListResponse",
            "ProjectMemberEntry",
            "ProjectSourceClaim",
            "ProjectFact",
            "ProjectRollup",
            "ProjectDetailResponse",
        ):
            model = getattr(schemas, model_name)
            for field_name in model.model_fields:
                for fragment in forbidden:
                    assert fragment not in field_name.lower(), (
                        f"{model_name}.{field_name} contains '{fragment}'"
                    )

    def test_the_member_entry_field_set_is_pinned(self) -> None:
        """Identity, a self-recognisable role, and the audit trail. Nothing
        else — and this test is what makes 'nothing else' true tomorrow."""
        assert set(schemas.ProjectMemberEntry.model_fields) == {
            "person_id",
            "display_name",
            "project_role",
            "added_by",
            "added_at",
            "removed_by",
            "removed_at",
        }

    def test_the_rollup_has_no_remaining_work_field(self) -> None:
        """CAIRN holds no planned-work model, so a 'remaining' figure would be
        an invention. The field does not exist, which is how no client can
        render one."""
        fields = set(schemas.ProjectRollup.model_fields)
        assert fields == {"delivered", "blockers", "open_questions", "decisions"}
        for invented in ("remaining", "planned", "todo", "progress", "completion"):
            assert not any(invented in field for field in fields)

    def test_the_router_never_groups_in_progress_under_a_project(self) -> None:
        """A live 'what everyone is doing right now' list under a project
        banner is a workload view of the people in it."""
        assert "in_progress" not in projects_router._ROLLUP_KINDS


class TestMembershipIsNeverSilent:
    @integration
    async def test_adding_and_removing_records_who_and_when(self, platform) -> None:
        tenant = await _tenant(platform, "audit")
        actor = await _user(platform, tenant, TenantRole.ADMIN)
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            person = await _person(session, tenant, "Priya Nair")
            project = Project(tenant_id=tenant.id, name="Payments")
            session.add(project)
            await session.flush()
            member = ProjectMember(
                tenant_id=tenant.id,
                project_id=project.id,
                person_id=person.id,
                project_role="Frontend",
                added_by_user_id=actor.id,
            )
            session.add(member)
            await session.commit()

            payload = await projects_router.project_detail_payload(
                session, tenant_id=tenant.id, project_id=project.id
            )
            entry = payload.members[0]
            assert entry.display_name == "Priya Nair"
            assert entry.project_role == "Frontend"
            assert entry.added_by == actor.display_name
            assert entry.removed_at is None

            member.removed_at = datetime.now(UTC)
            member.removed_by_user_id = actor.id
            await session.commit()

            after = await projects_router.project_detail_payload(
                session, tenant_id=tenant.id, project_id=project.id
            )
            # History-preserving: the row is still there, closed.
            assert len(after.members) == 1
            assert after.members[0].removed_at is not None
            assert after.members[0].removed_by == actor.display_name

    async def test_an_operational_event_names_nobody(self) -> None:
        """The log an operator reads carries categories and counts. The
        signature is the guarantee — there is no field for a person."""
        import inspect

        from cairn_api.projects import audit

        parameters = set(inspect.signature(audit.record).parameters)
        assert parameters == {"event", "state", "sources"}

        with structlog.testing.capture_logs() as captured:
            await audit.record(audit.ProjectEvent.MEMBER_ADDED)
        assert captured[0]["event"] == "project.member_added"
        assert "person" not in str(captured[0])


class TestStateIsDeclaredNotInferred:
    @integration
    async def test_a_project_nobody_classified_stays_unknown(self, platform) -> None:
        """Facts arriving under its claimed string do not move the state — an
        inferred state would be a judgement about the people producing the
        activity."""
        tenant = await _tenant(platform, "declared")
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            project = Project(tenant_id=tenant.id, name="Ledger")
            session.add(project)
            await session.flush()
            session.add(
                ProjectSource(tenant_id=tenant.id, project_id=project.id, value="acme/ledger")
            )
            await _fact(
                session,
                tenant,
                kind="delivery",
                statement="Ledger export shipped.",
                project="acme/ledger",
                days=1,
            )
            await session.commit()

            payload = await projects_router.project_detail_payload(
                session, tenant_id=tenant.id, project_id=project.id
            )

        assert payload.state == "unknown"
        assert payload.state_declared_by is None
        assert payload.state_declared_at is None
        assert len(payload.rollup.delivered) == 1, "the evidence still resolves"

    def test_only_the_update_endpoint_writes_the_state_stamp(self) -> None:
        import inspect

        source = inspect.getsource(projects_router)
        assert source.count("state_declared_by_user_id = ") == 1, (
            "more than one code path declares a state"
        )


@integration
class TestTheMappingResolvesEvidence:
    async def test_a_claimed_string_reaches_every_fact_that_carries_it(self, platform) -> None:
        """The join, not a stamped foreign key: a claim made now reaches facts
        stored before it, and releasing the claim un-reaches them — with the
        raw string still on every citation as provenance."""
        tenant = await _tenant(platform, "mapping")
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            # Facts first, deliberately: the claim comes afterwards.
            await _fact(
                session,
                tenant,
                kind="delivery",
                statement="Older delivery.",
                project="acme/api",
                days=5,
            )
            await _fact(
                session,
                tenant,
                kind="blocker",
                statement="Staging credentials are missing.",
                project="acme/api",
                days=1,
            )
            project = Project(tenant_id=tenant.id, name="API")
            session.add(project)
            await session.flush()
            claim = ProjectSource(tenant_id=tenant.id, project_id=project.id, value="acme/api")
            session.add(claim)
            await session.commit()

            payload = await projects_router.project_detail_payload(
                session, tenant_id=tenant.id, project_id=project.id
            )
            assert [fact.statement for fact in payload.rollup.delivered] == ["Older delivery."]
            assert [fact.statement for fact in payload.rollup.blockers] == [
                "Staging credentials are missing."
            ]
            assert payload.rollup.delivered[0].sources[0].source == "github"

            await session.delete(claim)
            await session.commit()
            released = await projects_router.project_detail_payload(
                session, tenant_id=tenant.id, project_id=project.id
            )
            assert released.rollup.delivered == []
            # The provenance survived the release.
            remaining = (await session.scalars(select(FactSource))).all()
            assert all(source.project == "acme/api" for source in remaining)

    async def test_the_rollup_is_newest_first_within_each_group(self, platform) -> None:
        tenant = await _tenant(platform, "order")
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            project = Project(tenant_id=tenant.id, name="Ordering")
            session.add(project)
            await session.flush()
            session.add(
                ProjectSource(tenant_id=tenant.id, project_id=project.id, value="acme/order")
            )
            for days, statement in ((10, "Oldest."), (1, "Newest."), (5, "Middle.")):
                await _fact(
                    session,
                    tenant,
                    kind="decision",
                    statement=statement,
                    project="acme/order",
                    days=days,
                )
            await session.commit()

            payload = await projects_router.project_detail_payload(
                session, tenant_id=tenant.id, project_id=project.id
            )

        assert [fact.statement for fact in payload.rollup.decisions] == [
            "Newest.",
            "Middle.",
            "Oldest.",
        ]


@integration
class TestArchivedProjects:
    async def test_archived_leaves_the_list_but_keeps_its_citations(self, platform) -> None:
        tenant = await _tenant(platform, "archive")
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            project = Project(tenant_id=tenant.id, name="Retired")
            session.add(project)
            await session.flush()
            session.add(
                ProjectSource(tenant_id=tenant.id, project_id=project.id, value="acme/retired")
            )
            await _fact(
                session,
                tenant,
                kind="delivery",
                statement="Shipped before retirement.",
                project="acme/retired",
                days=30,
            )
            await session.commit()
            project_id = project.id

            project.archived_at = datetime.now(UTC)
            await session.commit()

            listing = await projects_router.list_projects_payload(session, tenant_id=tenant.id)
            assert [p.name for p in listing.projects] == []

            with_archived = await projects_router.list_projects_payload(
                session, tenant_id=tenant.id, include_archived=True
            )
            assert [p.name for p in with_archived.projects] == ["Retired"]

            detail = await projects_router.project_detail_payload(
                session, tenant_id=tenant.id, project_id=project_id
            )
            assert detail.archived_at is not None
            assert [fact.statement for fact in detail.rollup.delivered] == [
                "Shipped before retirement."
            ]


@integration
class TestNamesAreUniquePerWorkspace:
    async def test_case_insensitively(self, platform) -> None:
        tenant = await _tenant(platform, "names")
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            session.add(Project(tenant_id=tenant.id, name="Payments"))
            await session.commit()

        async with tenant_session(tenant.id) as session:
            session.add(Project(tenant_id=tenant.id, name="payments"))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

    async def test_one_string_has_one_claimant(self, platform) -> None:
        tenant = await _tenant(platform, "claims")
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            first = Project(tenant_id=tenant.id, name="First")
            second = Project(tenant_id=tenant.id, name="Second")
            session.add_all([first, second])
            await session.flush()
            session.add(ProjectSource(tenant_id=tenant.id, project_id=first.id, value="acme/api"))
            await session.commit()

        async with tenant_session(tenant.id) as session:
            other = await session.scalar(select(Project).where(Project.name == "Second"))
            assert other is not None
            session.add(ProjectSource(tenant_id=tenant.id, project_id=other.id, value="acme/api"))
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()


@integration
class TestTheBackfillIsIdempotent:
    async def test_running_it_twice_mints_nothing_new(self, platform) -> None:
        """The migration's own helper, invoked directly: distinct citation
        strings become `unknown` projects claiming them, and a second run is a
        no-op."""
        import importlib.util

        tenant = await _tenant(platform, "backfill")
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            for value in ("acme/one", "acme/one", "acme/two"):
                await _fact(
                    session,
                    tenant,
                    kind="delivery",
                    statement=f"Work on {value}.",
                    project=value,
                    days=2,
                )
            await session.commit()

        spec = importlib.util.spec_from_file_location("project_layer_migration", MIGRATION_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        connection = await platform.connection()
        await connection.run_sync(lambda sync_conn: module._backfill(sync_conn))
        await platform.commit()

        first = (
            await platform.scalars(select(Project).where(Project.tenant_id == tenant.id))
        ).all()
        minted = {project.name for project in first}
        assert minted == {"acme/one", "acme/two"}
        assert all(project.state == ProjectState.UNKNOWN for project in first)

        connection = await platform.connection()
        await connection.run_sync(lambda sync_conn: module._backfill(sync_conn))
        await platform.commit()

        second = (
            await platform.scalars(select(Project).where(Project.tenant_id == tenant.id))
        ).all()
        assert len(second) == len(first), "the backfill minted duplicates on a second run"

        claims = (
            await platform.scalars(
                select(ProjectSource).where(ProjectSource.tenant_id == tenant.id)
            )
        ).all()
        assert {claim.value for claim in claims} == {"acme/one", "acme/two"}


class TestPermissionGating:
    def test_writes_need_projects_manage_and_reads_do_not(self) -> None:
        """A Viewer reads everything and writes nothing — the role difference
        stays configuration-only, which is what keeps visibility symmetric."""
        from cairn_api.auth.permissions import Permission, has_permission

        assert has_permission(TenantRole.VIEWER, Permission.CONTENT_READ)
        assert not has_permission(TenantRole.VIEWER, Permission.PROJECTS_MANAGE)
        assert not has_permission(TenantRole.MEMBER, Permission.PROJECTS_MANAGE)
        assert has_permission(TenantRole.ADMIN, Permission.PROJECTS_MANAGE)
        assert has_permission(TenantRole.OWNER, Permission.PROJECTS_MANAGE)

    def test_every_mutating_route_declares_the_gate(self) -> None:
        import inspect

        source = inspect.getsource(projects_router)
        mutations = (
            source.count("@router.post")
            + source.count("@router.patch")
            + source.count("@router.delete")
        )
        gated = source.count("requires(Permission.PROJECTS_MANAGE)")
        assert gated == mutations, (
            f"{mutations} mutating routes but {gated} permission gates - one is ungated"
        )
