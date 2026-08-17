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
from datetime import UTC, datetime

import pytest
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import get_tenant_context
from cairn_api.jobs import JobEnvelope, JobRegistry, UnknownJobTypeError, run_job
from pydantic import ValidationError
from sqlalchemy import delete, func, select, update
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


class TestTheCorrelationId:
    """The durable half of "follow this webhook to the brief it produced".

    `traceparent` links spans and exists only while a tracer is installed, which
    is nowhere by default. This one is always there, is carried through the
    queue, and lands in the logs.
    """

    def test_every_job_has_one_even_with_no_origin(self) -> None:
        # Scheduled work, backfill and anything built in a test have no
        # originating request. None of them may be the job with no id.
        envelope = JobEnvelope(job_type="brief.generate", tenant_id=uuid.uuid4())

        assert len(envelope.correlation_id) == 32

    def test_a_retry_keeps_it(self) -> None:
        first = JobEnvelope(job_type="brief.generate", tenant_id=uuid.uuid4())

        assert first.next_attempt().correlation_id == first.correlation_id

    def test_it_does_not_replace_the_traceparent(self) -> None:
        """Both, always: one links spans across a tracer, the other survives
        without one."""
        fields = JobEnvelope.model_fields

        assert "traceparent" in fields
        assert "correlation_id" in fields

    def test_an_id_that_is_not_opaque_is_refused(self) -> None:
        """It is stamped on spans, so an envelope carrying a sentence in this
        field would be a leak. Refusing to parse is the failure people notice."""
        with pytest.raises(ValidationError, match="correlation_id"):
            JobEnvelope(
                job_type="brief.generate",
                tenant_id=uuid.uuid4(),
                correlation_id="Priya shipped the payments migration",
            )

    def test_a_unit_of_work_binds_it_into_the_log_context(self) -> None:
        """`grep <correlation_id>` only reconstructs the path if every line
        beneath the job carries it without being handed the value."""
        import structlog
        from cairn_api.telemetry import correlation

        seen: list[object] = []
        envelope = JobEnvelope(job_type="brief.generate", tenant_id=uuid.uuid4())

        with correlation.correlated(envelope.correlation_id):
            seen.append(structlog.contextvars.get_contextvars().get("correlation_id"))

        assert seen == [envelope.correlation_id]
        # And unbound afterwards: a worker handles many jobs in one process, and
        # a leaked id would label the next job's lines with this one's path.
        assert "correlation_id" not in structlog.contextvars.get_contextvars()


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
        # Unique per run — see the same fix in `test_tenant_isolation.py`.
        suffix = uuid.uuid4().hex[:8]
        acme = Tenant(name="Acme", slug=f"acme-jobs-{suffix}")
        globex = Tenant(name="Globex", slug=f"globex-jobs-{suffix}")
        platform.add_all([acme, globex])
        await platform.flush()

        acme_user = User(email=f"ali-{suffix}@acme-jobs.test")
        globex_user = User(email=f"jordan-{suffix}@globex-jobs.test")
        # Exists platform-wide but belongs to no workspace yet, so a job can
        # legitimately add them to one.
        unassigned = User(email=f"new.hire-{suffix}@acme-jobs.test")
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

        ids = [acme.id, globex.id]
        user_ids = [acme_user.id, globex_user.id, unassigned.id]
        # Scoped to what this fixture created.
        #
        # It used to be `DELETE FROM tenants` with no predicate, which removed every
        # workspace in the database — including ones another module had committed
        # and was still using. That is invisible while one file runs at a time and
        # produces "duplicate key" errors at *setup* of an unrelated test as soon as
        # two files share a session, which is the hardest kind of failure to place.
        await platform.execute(delete(Membership).where(Membership.tenant_id.in_(ids)))
        await platform.execute(delete(User).where(User.id.in_(user_ids)))
        await platform.execute(delete(Tenant).where(Tenant.id.in_(ids)))
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

    async def test_a_successful_handler_commits(
        self, two_tenants: tuple[Tenant, Tenant], platform: AsyncSession
    ) -> None:
        """The happy path, which had no coverage at all.

        `tenant_session` commits on success. Nothing verified that — deleting
        the commit would have left every background write in the product a
        silent no-op with the whole suite still green.
        """
        acme, _ = two_tenants
        registry = JobRegistry()
        marked = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)

        @registry.register("test.notify")
        async def handler(session: AsyncSession, envelope: JobEnvelope) -> None:
            # A legitimate tenant-scoped write: recording that a member has been
            # told their activity may be captured (md/05 §B.3.5). Creating a
            # membership is a platform operation and correctly refused here.
            await session.execute(
                update(Membership)
                .where(Membership.tenant_id == envelope.tenant_id)
                .values(notified_at=marked)
            )

        await run_job(
            JobEnvelope(job_type="test.notify", tenant_id=acme.id),
            job_registry=registry,
        )

        # Read back on a *different* connection, so this proves a commit rather
        # than uncommitted state visible to the same transaction.
        persisted = await platform.scalar(
            select(Membership.notified_at).where(Membership.tenant_id == acme.id)
        )
        assert persisted == marked, "A successful job did not commit its work"

    async def test_a_failing_handler_rolls_back(
        self, two_tenants: tuple[Tenant, Tenant], platform: AsyncSession
    ) -> None:
        """A partially applied job would be worse than a failed one."""
        acme, _ = two_tenants
        registry = JobRegistry()

        @registry.register("test.explode")
        async def handler(session: AsyncSession, envelope: JobEnvelope) -> None:
            await session.execute(
                update(Membership)
                .where(Membership.tenant_id == envelope.tenant_id)
                .values(notified_at=datetime(2026, 1, 1, tzinfo=UTC))
            )
            # Prove the write actually happened before the failure. Without
            # this, the assertion below passes whether the rollback worked or
            # the write never occurred at all.
            written = await session.scalar(
                select(Membership.notified_at).where(Membership.tenant_id == envelope.tenant_id)
            )
            assert written is not None

            msg = "handler failed after writing"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="handler failed"):
            await run_job(
                JobEnvelope(job_type="test.explode", tenant_id=acme.id),
                job_registry=registry,
            )

        survived = await platform.scalar(
            select(Membership.notified_at).where(Membership.tenant_id == acme.id)
        )
        assert survived is None, "A failed job left data behind"

    async def test_unknown_job_type_raises_rather_than_silently_dropping(
        self, two_tenants: tuple[Tenant, Tenant]
    ) -> None:
        acme, _ = two_tenants
        with pytest.raises(UnknownJobTypeError):
            await run_job(
                JobEnvelope(job_type="test.nonexistent", tenant_id=acme.id),
                job_registry=JobRegistry(),
            )
