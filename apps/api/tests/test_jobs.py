"""Background job tests.

Two concerns, tested separately:

- **The envelope** — that a job cannot exist without naming its tenant.
- **The runner** — that a handler cannot reach the database outside that tenant.

The second group is the important one. CAIRN is almost entirely background work,
so this is where the isolation guarantee is actually load-bearing, and where a
failure would be silent: no user is watching a queue worker.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import get_tenant_context
from cairn_api.jobs import JobEnvelope, JobRegistry, UnknownJobTypeError, run_job
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


class TestJobEnvelope:
    """The envelope makes an untenanted job unrepresentable."""

    def test_requires_a_tenant(self) -> None:
        with pytest.raises(ValidationError, match="tenant_id"):
            JobEnvelope(job_type="brief.generate")  # type: ignore[call-arg]

    def test_rejects_the_nil_uuid(self) -> None:
        """The all-zero UUID parses cleanly and means nothing.

        It is exactly what an uninitialised variable or a buggy default
        produces, so it must be refused at the boundary rather than allowed to
        become a job running against a tenant that does not exist.
        """
        with pytest.raises(ValidationError, match="not the nil UUID"):
            JobEnvelope(job_type="brief.generate", tenant_id=uuid.UUID(int=0))

    def test_rejects_unknown_fields(self) -> None:
        # A typo in a field name would otherwise be silently ignored, and the
        # value it was meant to carry would vanish.
        with pytest.raises(ValidationError):
            JobEnvelope(
                job_type="brief.generate",
                tenant_id=uuid.uuid4(),
                tenat_id="typo",  # type: ignore[call-arg]
            )

    def test_is_immutable(self) -> None:
        envelope = JobEnvelope(job_type="brief.generate", tenant_id=uuid.uuid4())
        with pytest.raises(ValidationError):
            envelope.tenant_id = uuid.uuid4()

    def test_retry_produces_a_new_envelope(self) -> None:
        first = JobEnvelope(job_type="brief.generate", tenant_id=uuid.uuid4())
        second = first.next_attempt()

        assert first.attempt == 1
        assert second.attempt == 2
        assert second.job_id == first.job_id, "A retry is the same job, not a new one"
        assert second.enqueued_at == first.enqueued_at, (
            "enqueued_at must keep its original value so queue latency stays measurable"
        )

    def test_carries_a_stable_id_for_idempotent_consumption(self) -> None:
        envelope = JobEnvelope(job_type="brief.generate", tenant_id=uuid.uuid4())
        assert envelope.job_id is not None


class TestJobRegistry:
    def test_resolves_a_registered_handler(self) -> None:
        registry = JobRegistry()

        @registry.register("test.job")
        async def handler(session: AsyncSession, envelope: JobEnvelope) -> None: ...

        assert registry.resolve("test.job") is handler

    def test_unknown_job_type_raises(self) -> None:
        """A dropped job is indistinguishable from a completed one."""
        registry = JobRegistry()
        with pytest.raises(UnknownJobTypeError, match="No handler registered"):
            registry.resolve("nope")

    def test_duplicate_registration_raises(self) -> None:
        # Otherwise two modules could disagree about what a job does, with the
        # winner decided by import order.
        registry = JobRegistry()

        @registry.register("test.job")
        async def first(session: AsyncSession, envelope: JobEnvelope) -> None: ...

        with pytest.raises(ValueError, match="already registered"):

            @registry.register("test.job")
            async def second(session: AsyncSession, envelope: JobEnvelope) -> None: ...


@pytest.mark.integration
@pytest.mark.isolation
class TestRunnerIsolation:
    """The tests that matter. A handler must not reach another tenant's data."""

    _unassigned_id: uuid.UUID

    @pytest.fixture
    async def two_tenants(self, platform: AsyncSession) -> AsyncIterator[tuple[Tenant, Tenant]]:
        acme = Tenant(name="Acme", slug="acme-jobs")
        globex = Tenant(name="Globex", slug="globex-jobs")
        platform.add_all([acme, globex])
        await platform.flush()

        acme_user = User(email="ali@acme-jobs.test")
        globex_user = User(email="jordan@globex-jobs.test")
        # Exists platform-wide but belongs to no workspace yet, so a job can
        # legitimately add them to one.
        unassigned = User(email="new.hire@acme-jobs.test")
        platform.add_all([acme_user, globex_user, unassigned])
        await platform.flush()
        self._unassigned_id = unassigned.id

        platform.add_all(
            [
                Membership(tenant_id=acme.id, user_id=acme_user.id, role=TenantRole.OWNER),
                Membership(tenant_id=globex.id, user_id=globex_user.id, role=TenantRole.OWNER),
            ]
        )
        await platform.commit()

        yield acme, globex

        await platform.execute(delete(Membership))
        await platform.execute(delete(User))
        await platform.execute(delete(Tenant))
        await platform.commit()

    async def test_handler_receives_a_scoped_session(
        self, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """The handler's session is already bound to the job's tenant.

        It does not have to establish context, and cannot forget to.
        """
        acme, _ = two_tenants
        registry = JobRegistry()
        observed: list[uuid.UUID | None] = []

        @registry.register("test.observe")
        async def handler(session: AsyncSession, envelope: JobEnvelope) -> None:
            observed.append(await get_tenant_context(session))

        await run_job(
            JobEnvelope(job_type="test.observe", tenant_id=acme.id),
            job_registry=registry,
        )

        assert observed == [acme.id]

    async def test_handler_cannot_see_another_tenants_data(
        self, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """The core guarantee, exercised through the background path.

        Both tenants have exactly one membership. A handler running for Acme
        must count one, not two — and would count two if context were missing.
        """
        acme, _ = two_tenants
        registry = JobRegistry()
        counts: list[int] = []

        @registry.register("test.count")
        async def handler(session: AsyncSession, envelope: JobEnvelope) -> None:
            result = await session.scalar(select(func.count()).select_from(Membership))
            counts.append(result or 0)

        await run_job(
            JobEnvelope(job_type="test.count", tenant_id=acme.id),
            job_registry=registry,
        )

        assert counts == [1], "A background job saw across the tenant boundary"

    async def test_consecutive_jobs_do_not_leak_context(
        self, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        """The failure mode connection pooling would produce.

        Two jobs for different tenants run in sequence and very likely reuse the
        same pooled connection. If context were session-scoped rather than
        transaction-scoped, the second job would inherit the first tenant's
        scope — a cross-tenant leak that only appears once traffic is real.
        """
        acme, globex = two_tenants
        registry = JobRegistry()
        seen: list[uuid.UUID | None] = []

        @registry.register("test.sequence")
        async def handler(session: AsyncSession, envelope: JobEnvelope) -> None:
            seen.append(await get_tenant_context(session))

        for tenant in (acme, globex, acme):
            await run_job(
                JobEnvelope(job_type="test.sequence", tenant_id=tenant.id),
                job_registry=registry,
            )

        assert seen == [acme.id, globex.id, acme.id]

    async def test_a_failing_handler_rolls_back(self, two_tenants: tuple[Tenant, Tenant]) -> None:
        """A partially applied job would be worse than a failed one."""
        acme, _ = two_tenants
        registry = JobRegistry()

        @registry.register("test.explode")
        async def handler(session: AsyncSession, envelope: JobEnvelope) -> None:
            # A legitimate tenant-scoped write: adding an existing person to
            # this workspace. Creating the user itself would be a platform
            # operation and is correctly refused by RLS.
            session.add(Membership(tenant_id=envelope.tenant_id, user_id=self._unassigned_id))
            await session.flush()
            msg = "handler failed after writing"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="handler failed"):
            await run_job(
                JobEnvelope(job_type="test.explode", tenant_id=acme.id),
                job_registry=registry,
            )

        # The runner must not swallow the error, and the write must not survive.
        registry2 = JobRegistry()
        found: list[int] = []

        @registry2.register("test.check")
        async def check(session: AsyncSession, envelope: JobEnvelope) -> None:
            result = await session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.user_id == self._unassigned_id)
            )
            found.append(result or 0)

        await run_job(
            JobEnvelope(job_type="test.check", tenant_id=acme.id),
            job_registry=registry2,
        )

        assert found == [0], "A failed job left data behind"

    async def test_unknown_job_type_raises_rather_than_silently_dropping(
        self, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        acme, _ = two_tenants
        with pytest.raises(UnknownJobTypeError):
            await run_job(
                JobEnvelope(job_type="test.nonexistent", tenant_id=acme.id),
                job_registry=JobRegistry(),
            )
