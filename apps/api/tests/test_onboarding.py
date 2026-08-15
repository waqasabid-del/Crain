"""The first ten minutes, from the API's side.

Step 20's exit criterion is *under ten minutes from signup to first real output,
and never an empty state*. The second half is what this endpoint exists to make
possible: a workspace connected ninety seconds ago has no brief, and the screen
needs something true to say instead of "nothing yet".

So the tests here are mostly about the **stage** the endpoint reports, because
that is the one value the interface switches on. Getting it wrong does not throw
— it shows a reader a spinner that never resolves, or an empty page while an
import is running perfectly well underneath.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.api.routers.onboarding import OnboardingStage, get_onboarding
from cairn_api.api.schemas import OnboardingResponse
from cairn_api.db.backfill_models import BackfillRun, BackfillState
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource
from cairn_api.db.github_models import GitHubInstallation
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.session import platform_session
from cairn_api.db.tenancy import tenant_session
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)


class _Context:
    """The dependency's resolved workspace context, without the HTTP layer.

    The route is called directly rather than through the app, because what is
    under test is the stage derivation — and driving it through a request would
    add a session cookie, a membership lookup and a permission check to every
    case, none of which is what these assertions are about. The permission
    itself is covered by the router's shared dependency tests.
    """

    def __init__(self, tenant_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id


@pytest.fixture
async def tenant_id(platform: AsyncSession) -> uuid.UUID:
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name="Acme", slug=f"onboard-{suffix}")
    user = User(email=f"owner-{suffix}@example.com")
    platform.add_all([tenant, user])
    await platform.flush()
    platform.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.OWNER))
    await platform.commit()
    return tenant.id


async def connect(platform: AsyncSession, tenant_id: uuid.UUID) -> GitHubInstallation:
    installation = GitHubInstallation(
        tenant_id=tenant_id,
        installation_id=880_000 + uuid.uuid4().int % 90_000,
        account_login="acme-inc",
        account_type="Organization",
    )
    platform.add(installation)
    await platform.commit()
    return installation


async def add_run(
    tenant_id: uuid.UUID,
    *,
    installation_id: int,
    repository: str,
    state: BackfillState,
    commits: int = 0,
) -> None:
    """Create a backfill run.

    `installation_id` is threaded through rather than hardcoded because
    `uq_backfill_runs_active` keeps one live run per (installation, repository)
    *globally*, not per tenant. A shared constant made these tests pass alone
    and collide when run together — the flakiness that trains people to re-run
    CI, caught here by the constraint doing its job.
    """
    async with tenant_session(tenant_id) as session:
        session.add(
            BackfillRun(
                tenant_id=tenant_id,
                installation_id=installation_id,
                repository=repository,
                state=state,
                since=NOW - timedelta(days=90),
                commits_imported=commits,
            )
        )
        await session.commit()


async def add_fact(tenant_id: uuid.UUID, *, superseded: bool = False) -> None:
    async with tenant_session(tenant_id) as session:
        row = FactRow(
            tenant_id=tenant_id,
            kind="delivery",
            statement="Priya shipped rate limiting.",
            certainty="verified",
            occurred_at=NOW,
            valid_from=NOW,
            sources=[FactSource(tenant_id=tenant_id, source="github", evidence_id="ev-1")],
        )
        session.add(row)
        await session.flush()

        if superseded:
            successor = FactRow(
                tenant_id=tenant_id,
                kind="delivery",
                statement="Priya shipped rate limiting to production.",
                certainty="verified",
                occurred_at=NOW + timedelta(days=1),
                valid_from=NOW + timedelta(days=1),
                sources=[FactSource(tenant_id=tenant_id, source="github", evidence_id="ev-2")],
            )
            session.add(successor)
            await session.flush()
            row.valid_until = NOW + timedelta(days=1)
            row.superseded_by_id = successor.id
        await session.commit()


async def read(tenant_id: uuid.UUID) -> OnboardingResponse:
    async with tenant_session(tenant_id) as db, platform_session() as platform:
        return await get_onboarding(_Context(tenant_id), db, platform)  # type: ignore[arg-type]


class TestStage:
    async def test_a_new_workspace_is_told_to_connect_something(self, tenant_id: uuid.UUID) -> None:
        state = await read(tenant_id)

        assert state.stage == OnboardingStage.NOT_CONNECTED
        assert state.connected is False
        assert state.account_login is None

    async def test_connected_with_nothing_imported_yet_is_importing(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """The hardest moment for the interface, and the one this exists for.

        Zero of everything, and the screen still has to say something true.
        """
        installation = await connect(platform, tenant_id)
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/api",
            state=BackfillState.RUNNING,
        )

        state = await read(tenant_id)

        assert state.stage == OnboardingStage.IMPORTING
        assert state.importing is True
        assert state.commits_imported == 0
        assert state.account_login == "acme-inc"

    async def test_facts_available_while_the_import_continues(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """`understanding`, not `ready` — and the distinction is the promise.

        "Under ten minutes to first output" is only achievable for a team with
        five years of history because first output does not wait for a finished
        import. The screen offers the brief as soon as a fact exists.
        """
        installation = await connect(platform, tenant_id)
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/api",
            state=BackfillState.RUNNING,
            commits=900,
        )
        await add_fact(tenant_id)

        state = await read(tenant_id)

        assert state.stage == OnboardingStage.UNDERSTANDING
        assert state.importing is True
        assert state.facts_available == 1

    async def test_a_finished_import_with_facts_is_ready(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        installation = await connect(platform, tenant_id)
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/api",
            state=BackfillState.COMPLETED,
            commits=42,
        )
        await add_fact(tenant_id)

        state = await read(tenant_id)

        assert state.stage == OnboardingStage.READY
        assert state.importing is False

    async def test_a_finished_import_that_found_nothing_is_ready_not_importing(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """The case that produces a spinner nobody can escape.

        Every run finished and no fact came out. Reporting `importing` here
        would leave the screen waiting forever for something that already
        happened; the honest answer is that the repositories were quiet.
        """
        installation = await connect(platform, tenant_id)
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/api",
            state=BackfillState.COMPLETED,
        )

        state = await read(tenant_id)

        assert state.stage == OnboardingStage.READY
        assert state.importing is False
        assert state.facts_available == 0

    async def test_a_throttled_run_still_counts_as_importing(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """Throttled is waiting, not stopped.

        GitHub's secondary rate limit parks a run and it resumes on its own.
        Reporting it as finished would tell the reader their history import was
        complete when two thirds of it had not been read.
        """
        installation = await connect(platform, tenant_id)
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/api",
            state=BackfillState.THROTTLED,
        )

        state = await read(tenant_id)

        assert state.importing is True
        assert state.stage == OnboardingStage.IMPORTING


class TestCounters:
    async def test_progress_is_reported_per_repository_with_no_percentage(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """No percentage anywhere, and that is deliberate.

        GitHub does not say how many commits a repository holds before it is
        walked, so any percentage would be invented — and an invented one always
        stalls near the end, which reads as broken rather than as unknown.
        """
        installation = await connect(platform, tenant_id)
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/api",
            state=BackfillState.RUNNING,
            commits=900,
        )
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/web",
            state=BackfillState.COMPLETED,
            commits=384,
        )

        state = await read(tenant_id)

        assert state.commits_imported == 1284
        assert len(state.repositories) == 2
        assert {item.repository for item in state.repositories} == {
            "acme-inc/api",
            "acme-inc/web",
        }
        assert [item.finished for item in state.repositories].count(True) == 1
        # The response carries no field that could be rendered as a percentage.
        assert not any("percent" in field for field in state.model_dump())

    async def test_superseded_facts_are_not_counted(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """A count that included them would climb during a correction.

        The workspace would appear to be growing at the moment it was fixing
        itself, which is the opposite of what the number is read as meaning.
        """
        await connect(platform, tenant_id)
        await add_fact(tenant_id, superseded=True)

        state = await read(tenant_id)

        assert state.facts_available == 1

    async def test_another_workspace_sees_none_of_it(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """The isolation check, on the newest endpoint.

        It reads across two connections — the platform one for the installation
        and the tenant-scoped one for runs and facts — so it is exactly the
        shape where a missing filter goes unnoticed.
        """
        installation = await connect(platform, tenant_id)
        await add_run(
            tenant_id,
            installation_id=installation.installation_id,
            repository="acme-inc/api",
            state=BackfillState.RUNNING,
            commits=900,
        )
        await add_fact(tenant_id)

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        state = await read(other.id)

        assert state.connected is False
        assert state.repositories == []
        assert state.commits_imported == 0
        assert state.facts_available == 0
