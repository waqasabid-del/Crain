"""Service level objectives: the targets, and the arithmetic behind them.

"Slow" becomes a number somebody agreed to only if three things are true, and
each has a test here.

**The number exists and says where it comes from.** An objective with a target
and no measurement source is prose with a decimal point in it, so every
objective is walked and both are asserted.

**An objective the infrastructure cannot measure reports that, rather than
passing.** This is the one that matters most. Availability has no measurement
today — CAIRN stores no request log, deliberately — and the tempting shape is a
status page that shows four green rows and omits the fifth. `met` is `None` for
an unmeasured objective and the tests pin it, because the alternative is a
dashboard that reads healthy during an outage.

**The measurements count what they claim to.** Unprocessed deliveries count as
misses, or a pipeline that has stopped entirely reports a perfect completion
rate by having completed nothing.

The measurement tests run inside a tenant-scoped session on purpose. Row-level
security then bounds every count to rows this test created, which is what makes
the assertions exact while the rest of the suite is inserting deliveries into
the same database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.config import Settings
from cairn_api.db.github_models import DeliveryStatus, WebhookDelivery
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.ops import measure, slo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


# --------------------------------------------------------------------------
# The definitions
# --------------------------------------------------------------------------


class TestTheObjectivesAreReal:
    @pytest.mark.parametrize("objective", slo.OBJECTIVES, ids=lambda item: item.key)
    def test_every_objective_states_a_target_and_where_it_is_measured_from(
        self, objective: slo.ServiceLevelObjective
    ) -> None:
        """Both halves, or it is not an objective.

        A target with no source cannot be checked by anybody who did not write
        it, which means it is never checked.
        """
        assert objective.target > 0
        assert objective.window > timedelta(0)
        assert len(objective.measured_from) > 40, (
            f"{objective.key} does not say where its number comes from"
        )
        assert objective.rationale

    @pytest.mark.parametrize("objective", slo.OBJECTIVES, ids=lambda item: item.key)
    def test_an_unmeasurable_objective_says_why(self, objective: slo.ServiceLevelObjective) -> None:
        """Otherwise it is an objective nobody can make measurable.

        "Not measurable yet" with no reason is indistinguishable from an
        oversight, and gets deleted at the next tidy-up.
        """
        if objective.measurable:
            assert objective.unmeasurable_reason is None
            return
        assert objective.unmeasurable_reason
        assert len(objective.unmeasurable_reason) > 40

    def test_the_keys_are_unique(self) -> None:
        """They address rows on a screen and, eventually, alert rules."""
        keys = [objective.key for objective in slo.OBJECTIVES]
        assert len(set(keys)) == len(keys)

    def test_an_unmeasured_objective_is_neither_met_nor_breached(self) -> None:
        """The load-bearing assertion of this whole file.

        `False` pages somebody for missing instrumentation. `True` reports an
        outage as healthy. Only `None` is honest, and only `None` forces the
        reader to notice that nothing is being measured.
        """
        for objective in slo.OBJECTIVES:
            assert objective.met(None) is None

    def test_direction_decides_which_side_passes(self) -> None:
        """Both an availability ratio and an error ratio are ratios, and they
        want opposite comparisons. Inferring it from the unit would silently
        invert one of them."""
        assert slo.AVAILABILITY.met(0.999) is True
        assert slo.AVAILABILITY.met(0.98) is False
        assert slo.DELIVERY_ERROR_RATE.met(0.005) is True
        assert slo.DELIVERY_ERROR_RATE.met(0.05) is False

    def test_no_objective_measures_a_person(self) -> None:
        """A product boundary, not a preference (md/05 §B.2).

        The natural next objective for anybody who has run a support team is
        "time to respond", and it is exactly the metric CAIRN promises never to
        produce. Asserted on the text because the failure arrives as a
        well-intentioned addition.
        """
        forbidden = ("person", "people", "employee", "member", "user activity", "team member")
        for objective in slo.OBJECTIVES:
            haystack = f"{objective.key} {objective.title} {objective.measured_from}".lower()
            for word in forbidden:
                assert word not in haystack, f"{objective.key} measures people: {word!r}"

    def test_looking_up_an_unknown_objective_fails_loudly(self) -> None:
        assert slo.objective("availability") is slo.AVAILABILITY
        with pytest.raises(KeyError):
            slo.objective("time_to_reply")


# --------------------------------------------------------------------------
# The measurements
# --------------------------------------------------------------------------


@pytest.fixture
async def workspace(platform: AsyncSession) -> AsyncIterator[uuid.UUID]:
    tenant = Tenant(
        name="SLO Workspace",
        slug=f"slo-{uuid.uuid4().hex[:10]}",
        region="us-central1",
    )
    platform.add(tenant)
    await platform.commit()

    yield tenant.id

    await platform.delete(tenant)
    await platform.commit()


async def _deliveries(
    platform: AsyncSession,
    tenant_id: uuid.UUID,
    rows: list[tuple[timedelta, timedelta | None, DeliveryStatus]],
) -> None:
    """Insert deliveries at controlled ages.

    Through the privileged session, because the application role has no INSERT
    on this table — a webhook is written by the ingestion path before any tenant
    context exists. The *measurements* then read through a tenant-scoped
    session, which is what bounds them to these rows.

    `created_at` is a server default, so each row is written and then moved: the
    objectives are entirely about the distance between two timestamps, and a
    fixture that could not place them could not test anything.
    """
    now = datetime.now(UTC)
    for age, elapsed, status in rows:
        delivery = WebhookDelivery(
            tenant_id=tenant_id,
            delivery_id=str(uuid.uuid4()),
            event_type="push",
            payload={},
            status=status,
        )
        platform.add(delivery)
        await platform.flush()
        delivery.created_at = now - age
        delivery.processed_at = (now - age + elapsed) if elapsed is not None else None
    await platform.commit()


class TestPipelineCompletion:
    async def test_the_share_completed_inside_the_target_is_reported(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        await _deliveries(
            platform,
            workspace,
            [
                (timedelta(hours=2), timedelta(minutes=1), DeliveryStatus.PROCESSED),
                (timedelta(hours=2), timedelta(minutes=5), DeliveryStatus.PROCESSED),
                (timedelta(hours=2), timedelta(minutes=14), DeliveryStatus.PROCESSED),
                # Over the fifteen-minute target.
                (timedelta(hours=2), timedelta(minutes=40), DeliveryStatus.PROCESSED),
            ],
        )

        async with tenant_session(workspace) as session:
            result = await measure.measure(
                slo.PIPELINE_COMPLETION, session, Settings(environment="test")
            )

        assert result.measured == pytest.approx(0.75)
        assert result.met is False  # the target is 0.95

    async def test_an_unprocessed_delivery_counts_as_a_miss(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """The failure this objective exists to catch.

        Counting only processed rows lets a pipeline that has stopped entirely
        report 100%: the three deliveries it managed before it died all
        completed quickly, and the thousand it has not touched are invisible.
        """
        await _deliveries(
            platform,
            workspace,
            [
                (timedelta(hours=1), timedelta(minutes=2), DeliveryStatus.PROCESSED),
                (timedelta(hours=1), None, DeliveryStatus.ACCEPTED),
                (timedelta(hours=1), None, DeliveryStatus.ACCEPTED),
                (timedelta(hours=1), None, DeliveryStatus.ACCEPTED),
            ],
        )

        async with tenant_session(workspace) as session:
            result = await measure.measure(
                slo.PIPELINE_COMPLETION, session, Settings(environment="test")
            )

        assert result.measured == pytest.approx(0.25)

    async def test_work_outside_the_window_is_not_counted(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """A window is what stops one bad afternoon following the service
        around for a month, and one good hour hiding a bad one."""
        await _deliveries(
            platform,
            workspace,
            [
                (timedelta(days=9), timedelta(minutes=90), DeliveryStatus.PROCESSED),
                (timedelta(hours=1), timedelta(minutes=1), DeliveryStatus.PROCESSED),
            ],
        )

        async with tenant_session(workspace) as session:
            result = await measure.measure(
                slo.PIPELINE_COMPLETION, session, Settings(environment="test")
            )

        assert result.measured == pytest.approx(1.0)

    async def test_an_empty_window_reports_no_measurement_rather_than_success(
        self, workspace: uuid.UUID
    ) -> None:
        """Nothing happened is not "everything worked".

        Zero of zero is the shape that renders as a green 100% and reassures
        somebody that a pipeline receiving nothing at all is healthy.
        """
        async with tenant_session(workspace) as session:
            result = await measure.measure(
                slo.PIPELINE_COMPLETION, session, Settings(environment="test")
            )

        assert result.measured is None
        assert result.met is None
        assert result.note == "No deliveries in the window."


class TestErrorRate:
    async def test_failures_are_counted_and_unclaimed_deliveries_are_not(
        self, workspace: uuid.UUID, platform: AsyncSession
    ) -> None:
        """`unclaimed` is an unknown or suspended installation, not a fault.

        Counting it would make every uninstall look like an outage, which is how
        an error-rate alert becomes one nobody investigates.
        """
        await _deliveries(
            platform,
            workspace,
            [
                (timedelta(hours=1), timedelta(minutes=1), DeliveryStatus.PROCESSED),
                (timedelta(hours=1), timedelta(minutes=1), DeliveryStatus.PROCESSED),
                (timedelta(hours=1), None, DeliveryStatus.FAILED),
                (timedelta(hours=1), None, DeliveryStatus.UNCLAIMED),
            ],
        )

        async with tenant_session(workspace) as session:
            result = await measure.measure(
                slo.DELIVERY_ERROR_RATE, session, Settings(environment="test")
            )

        assert result.measured == pytest.approx(0.25)
        assert result.met is False


class TestUnmeasurableObjectives:
    @pytest.mark.parametrize(
        "objective", [slo.AVAILABILITY, slo.WEBHOOK_ACKNOWLEDGEMENT], ids=lambda item: item.key
    )
    async def test_they_report_unmeasurable_with_the_reason_and_never_a_number(
        self, objective: slo.ServiceLevelObjective, platform: AsyncSession
    ) -> None:
        result = await measure.measure(objective, platform, Settings(environment="test"))

        assert result.measured is None
        assert result.met is None, "an unmeasured objective must not report as met"
        assert result.note == objective.unmeasurable_reason


class TestQueueLatency:
    async def test_a_backend_with_no_durable_queue_reports_unmeasurable_not_zero(
        self, platform: AsyncSession
    ) -> None:
        """Zero would read as "nothing is waiting", which is the most
        reassuring possible rendering of "this cannot be seen from here"."""
        settings = Settings(environment="test", queue_backend="memory")

        result = await measure.measure(slo.QUEUE_FIRST_ATTEMPT, platform, settings)

        assert result.measured is None
        assert result.met is None
        assert result.note is not None
        assert "memory" in result.note

    async def test_an_empty_scheduler_reports_a_measured_zero(self, platform: AsyncSession) -> None:
        """Distinct from the case above: the table exists, it was read, and
        nothing is waiting. That is a measurement, and a passing one."""
        settings = Settings(environment="test", queue_backend="postgres")

        result = await measure.measure(slo.QUEUE_FIRST_ATTEMPT, platform, settings)

        assert result.measured is not None
        assert result.met is not None


class TestEveryObjectiveIsMeasurable:
    async def test_measure_all_returns_one_result_per_objective(
        self, platform: AsyncSession
    ) -> None:
        """A dispatch that silently dropped an objective would take a row off
        the status screen, and nobody notices a row that is not there."""
        results = await measure.measure_all(platform, Settings(environment="test"))

        assert len(results) == len(slo.OBJECTIVES)
        assert [item.objective.key for item in results] == [
            objective.key for objective in slo.OBJECTIVES
        ]

    async def test_no_measurable_objective_falls_through_without_a_measurement(
        self, platform: AsyncSession
    ) -> None:
        """The fall-through branch exists so an unfinished objective cannot take
        the operations screen down. It must never be reached in a shipped
        state — an objective marked measurable with no implementation is a row
        that says "measurable" and shows nothing.
        """
        results = await measure.measure_all(
            platform, Settings(environment="test", queue_backend="postgres")
        )

        unimplemented = [
            item.objective.key
            for item in results
            if item.note == "No measurement is implemented for this objective."
        ]
        assert unimplemented == []
