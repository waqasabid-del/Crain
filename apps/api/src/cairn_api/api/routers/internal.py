"""The internal back-office.

Two rules govern everything here, and both are structural rather than
procedural.

**Staff never see customer content.** These endpoints return configuration,
health and counts — never a fact, a statement, a brief or a person's activity.
Reading a workspace's work requires an approved, time-boxed support session
(Step 28, md/15 §5.2), which no staff role can grant itself. A test walks every
response model on this router and fails if a content field appears.

**Every mutating action is recorded before it is performed.** The record is a
dependency (`audited`), so it is part of the route's signature rather than a
line a handler can forget, and `test_internal.py` enumerates the router and
fails if any non-GET route lacks it. The same shape as `requires(...)` on the
customer API, for the same reason.

The staff UI is deliberately not part of the customer application. Shipping
back-office screens in the bundle a customer downloads would contradict the
product's central claim; it belongs in a separate app.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import CurrentUser, PlatformDb, SettingsDep
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.routers.facts import _fact_response
from cairn_api.api.schemas import (
    AuditEntryResponse,
    AuditVerification,
    ConnectorFleetView,
    EvaluationSummary,
    FactResponse,
    ModelSpend,
    ModelSpendLine,
    PipelineHealth,
    QueueHealth,
    SloObjective,
    SloStatus,
    StaffTenantDetail,
    StaffTenantSummary,
    SubscriptionHealthView,
    SubscriptionInspection,
    SupportSessionRequest,
    SupportSessionResponse,
)
from cairn_api.config import Settings
from cairn_api.db.backfill_models import BackfillRun, BackfillState
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.github_models import GitHubInstallation, WebhookDelivery
from cairn_api.db.models import Membership, Tenant, User
from cairn_api.db.staff_models import InternalAuditEntry, StaffMember, StaffRole
from cairn_api.db.support_models import SupportScope, SupportSession
from cairn_api.db.tenancy import tenant_session
from cairn_api.gchat import subscriptions as gchat_subscriptions
from cairn_api.internal import audit, support
from cairn_api.ops import connectors as connector_ops
from cairn_api.ops import measure
from cairn_api.pipeline.spend import SPEND_SIGNALS

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

#: How recent a delivery must be for ingestion to count as healthy.
#:
#: Six hours rather than minutes: a small team's repository is quiet overnight
#: and at weekends, and an operator paged for a quiet Sunday learns to ignore
#: the signal.
INGESTION_STALE_AFTER = timedelta(hours=6)

DEFAULT_PAGE = 50
MAX_PAGE = 200

#: Roles that may identify an account at all.
#:
#: Everyone, including billing: a billing operator who cannot find a workspace
#: cannot bill it. What that role cannot reach is anything past the name —
#: ingestion health and the audit log are separate routes with separate rules.
ANY_STAFF = (StaffRole.SUPPORT, StaffRole.BILLING, StaffRole.ENGINEERING, StaffRole.SECURITY)


class StaffContext:
    """A member of staff, and the record of what they are doing."""

    __slots__ = ("member", "user")

    def __init__(self, user: Any, member: StaffMember) -> None:
        self.user = user
        self.member = member


async def current_staff(caller: CurrentUser, db: PlatformDb) -> StaffContext:
    """Resolve the caller to an active staff member, or refuse.

    404 rather than 403 for a non-member: the existence of a back-office is not
    something an ordinary customer's session should be able to confirm.
    """
    member = await db.scalar(
        select(StaffMember).where(
            StaffMember.user_id == caller.user.id, StaffMember.revoked_at.is_(None)
        )
    )
    if member is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not found",
            detail="No such endpoint.",
            problem_type="not-found",
        )
    return StaffContext(caller.user, member)


CurrentStaff = Annotated[StaffContext, Depends(current_staff)]


def requires_staff(*roles: StaffRole) -> Callable[[StaffContext], StaffContext]:
    """Restrict a route to particular staff roles."""

    def dependency(staff: CurrentStaff) -> StaffContext:
        if staff.member.role not in roles:
            raise ProblemDetailError(
                status_code=status.HTTP_403_FORBIDDEN,
                title="Insufficient staff role",
                detail=f"This action requires one of: {', '.join(role.value for role in roles)}.",
                problem_type="staff-role-required",
            )
        return staff

    return dependency


def audited(action: str) -> Callable[..., Coroutine[Any, Any, StaffContext]]:
    """Record this action before the handler runs.

    A dependency rather than a call inside each handler, so the record appears
    in the route's signature and cannot be omitted by someone adding an endpoint
    in a hurry. The reason is a required query parameter for the same purpose:
    an action nobody had to justify is one nobody can review.

    **The entry records an attempt, not an outcome**, and is committed before
    the handler runs so that a handler which then fails cannot take the record
    with it. Sharing the action's transaction would have meant a rollback erased
    the evidence — the case where the record matters most.

    The consequence is deliberate and worth stating plainly: an entry means
    somebody with staff access asked for this action, not that it succeeded.
    """

    async def dependency(
        request: Request,
        staff: CurrentStaff,
        db: PlatformDb,
        reason: Annotated[
            str,
            Query(
                min_length=3,
                max_length=500,
                description="Why this action is being taken. Recorded permanently.",
            ),
        ],
    ) -> StaffContext:
        tenant_id = request.path_params.get("tenant_id")
        await audit.record(
            db,
            actor_user_id=staff.user.id,
            action=action,
            reason=reason,
            tenant_id=uuid.UUID(tenant_id) if tenant_id else None,
            detail={"path": request.url.path, "method": request.method},
        )
        await db.commit()
        return staff

    return dependency


# --------------------------------------------------------------------------
# Operations
#
# Metadata only, and structurally so: every response model here holds counts,
# ages and categories. `test_telemetry.py` and `test_internal.py` both assert
# that no field on this router can carry a statement, a brief or a payload.
#
# md/15 §6 gives pipeline health, cost and evaluation to Engineering. Security
# is included because an incident is when this data is most needed and least
# convenient to request.
# --------------------------------------------------------------------------

OPERATIONS_ROLES = (StaffRole.ENGINEERING, StaffRole.SECURITY)


@router.get(
    "/operations/pipeline",
    response_model=PipelineHealth,
    summary="Ingestion health across every workspace",
)
async def pipeline_health(
    db: PlatformDb,
    staff: Annotated[StaffContext, Depends(requires_staff(*OPERATIONS_ROLES))],
) -> PipelineHealth:
    """Counts and ages, no tenant named.

    Deliberately platform-wide: a per-workspace view of what a customer is
    producing is a support session's business, not a dashboard's.
    """
    hour_ago = datetime.now(UTC) - timedelta(hours=1)

    recent = await db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.created_at >= hour_ago)
    )
    unprocessed = await db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.processed_at.is_(None))
    )
    oldest = await db.scalar(
        select(func.min(WebhookDelivery.created_at)).where(WebhookDelivery.processed_at.is_(None))
    )
    workspaces = await db.scalar(
        select(func.count(func.distinct(WebhookDelivery.tenant_id))).where(
            WebhookDelivery.created_at >= hour_ago
        )
    )
    facts = await db.scalar(
        select(func.count()).select_from(FactRow).where(FactRow.created_at >= hour_ago)
    )

    _ = staff
    return PipelineHealth(
        deliveries_last_hour=int(recent or 0),
        deliveries_unprocessed=int(unprocessed or 0),
        oldest_unprocessed_minutes=(
            (datetime.now(UTC) - oldest).total_seconds() / 60 if oldest else None
        ),
        facts_last_hour=int(facts or 0),
        workspaces_ingesting=int(workspaces or 0),
    )


@router.get(
    "/operations/queue",
    response_model=QueueHealth,
    summary="Queue and backfill state",
)
async def queue_health(
    db: PlatformDb,
    settings: SettingsDep,
    staff: Annotated[StaffContext, Depends(requires_staff(*OPERATIONS_ROLES))],
) -> QueueHealth:
    """Read from the durable record.

    Queue depth from the broker would be per-instance and momentary; the rows
    waiting in PostgreSQL are the same on every replica.
    """
    active = await db.scalar(
        select(func.count()).select_from(BackfillRun).where(BackfillRun.completed_at.is_(None))
    )
    failed = await db.scalar(
        select(func.count())
        .select_from(BackfillRun)
        .where(BackfillRun.state == BackfillState.FAILED)
    )
    waiting = await db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.processed_at.is_(None))
    )

    # The scheduler's own numbers, and only when it is the configured backend.
    # Starvation is what Step 30 prevents, so an operator needs to be able to
    # see it happening rather than learn about it from a customer.
    scheduled_waiting = scheduled_running = tenants_waiting = 0
    longest_wait_minutes: float | None = None

    if settings.queue_backend == "postgres":
        from cairn_api.jobs.postgres import PostgresJobQueue

        scheduler = PostgresJobQueue()
        depth = await scheduler.depth()
        fairness = await scheduler.fairness()

        scheduled_waiting = depth.pending
        scheduled_running = depth.in_flight
        tenants_waiting = fairness.tenants_waiting
        longest_wait_minutes = fairness.max_wait_seconds / 60

    _ = staff
    return QueueHealth(
        backfill_runs_active=int(active or 0),
        backfill_runs_failed=int(failed or 0),
        deliveries_awaiting_processing=int(waiting or 0),
        in_memory_broker=settings.queue_backend == "memory",
        scheduled_waiting=scheduled_waiting,
        scheduled_running=scheduled_running,
        tenants_waiting=tenants_waiting,
        longest_wait_minutes=longest_wait_minutes,
    )


@router.get(
    "/operations/spend",
    response_model=ModelSpend,
    summary="What the model boundary cost this process, and how close it is to the ceiling",
)
async def model_spend(
    settings: SettingsDep,
    staff: Annotated[StaffContext, Depends(requires_staff(*OPERATIONS_ROLES))],
) -> ModelSpend:
    """The spend counters and the ceiling signals.

    **The ceiling numbers are now cluster-wide, not per-replica**: enforcement
    reads and writes the durable `spend_counters` rows, so what refuses work on
    any replica is the same total this screen would show. The *signal* counters
    below (warnings, refusals, closest approach) remain this replica's own view
    — they count log-worthy moments, which are per-process by nature — and the
    response shape is unchanged so the dashboards reading it keep working.

    Read from `SPEND_SIGNALS` rather than from a ledger. A ledger belongs to one
    unit of work and is discarded with it, so building a fresh one here — which
    is what this endpoint used to do — reported zero however much the process
    had spent, and the screen could not have shown a cost incident if one had
    been happening while it was open.
    """
    from cairn_api.pipeline.jobs import build_providers

    providers = build_providers()
    signals = SPEND_SIGNALS.snapshot()

    _ = staff
    return ModelSpend(
        live=providers.live,
        backend=type(providers.model).__name__,
        total_calls=SPEND_SIGNALS.total_calls,
        total_tokens=SPEND_SIGNALS.total_tokens,
        by_stage=[
            ModelSpendLine(
                stage=signal.stage,
                calls=signal.calls,
                tokens=signal.tokens,
                warnings=signal.warnings,
                refusals=signal.refusals,
                closest_approach=signal.closest_approach,
            )
            for signal in signals
        ],
        ceiling_tokens=settings.model_max_tokens_per_tenant,
        ceiling_calls=settings.model_max_calls_per_tenant,
        warnings=SPEND_SIGNALS.warnings,
        refusals=SPEND_SIGNALS.refusals,
        workspaces_refused=SPEND_SIGNALS.workspaces_refused,
        note=(
            "Counted in this process since it started. On N replicas the real "
            "figure is higher. Ceilings are per workspace per unit of work."
        ),
    )


@router.get(
    "/operations/slo",
    response_model=SloStatus,
    summary="Each service level objective, its target, and what it currently reads",
)
async def slo_status(
    db: PlatformDb,
    settings: SettingsDep,
    staff: Annotated[StaffContext, Depends(requires_staff(*OPERATIONS_ROLES))],
) -> SloStatus:
    """The objectives, measured where the infrastructure allows it.

    An objective this deployment cannot measure reports `measurable: false` and
    says why. Nothing here substitutes the target for a missing measurement:
    an operator who reads a fabricated number acts on it, and the action is
    always "nothing is wrong".
    """
    measurements = await measure.measure_all(db, settings)

    _ = staff
    return SloStatus(
        measured_at=datetime.now(UTC),
        objectives=[
            SloObjective(
                key=item.objective.key,
                title=item.objective.title,
                rationale=item.objective.rationale,
                target=item.objective.target,
                unit=item.objective.unit.value,
                direction=item.objective.direction.value,
                window_minutes=item.objective.window.total_seconds() / 60,
                measured_from=item.objective.measured_from,
                measurable=item.objective.measurable,
                measured=item.measured,
                met=item.met,
                note=item.note,
            )
            for item in measurements
        ],
        unmeasurable=sum(1 for item in measurements if not item.objective.measurable),
        # `met is False` rather than `not met`: an objective with no measurement
        # is `None`, and counting it as breaching would page for missing
        # instrumentation while counting it as met hides an outage.
        breaching=sum(1 for item in measurements if item.met is False),
    )


@router.get(
    "/operations/evaluation",
    response_model=EvaluationSummary,
    summary="The last recorded evaluation run",
)
async def evaluation_summary(
    staff: Annotated[StaffContext, Depends(requires_staff(*OPERATIONS_ROLES))],
) -> EvaluationSummary:
    """Scores and failure modes from the committed baseline.

    The cases stay in the repository. A dashboard that showed the golden cases
    would be exporting the customer corrections they were built from.
    """
    from cairn_api.evaluation.gate import BASELINE_PATH

    _ = staff
    if not BASELINE_PATH.exists():
        return EvaluationSummary(
            available=False,
            note="No baseline recorded. Run `make eval` to produce one.",
        )

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    modes = baseline.get("failure_modes", {})
    return EvaluationSummary(
        available=True,
        cases=int(baseline.get("cases", 0)),
        passed=int(baseline.get("passed", 0)),
        failed=int(baseline.get("failed", 0)),
        failure_modes={str(key): int(value) for key, value in modes.items()},
    )


@router.get(
    "/operations/connectors",
    response_model=ConnectorFleetView,
    summary="Whether each source is delivering",
)
async def connector_health(
    db: PlatformDb,
    settings: SettingsDep,
    staff: Annotated[StaffContext, Depends(requires_staff(*OPERATIONS_ROLES))],
) -> ConnectorFleetView:
    """Per-source health, answered without reading anything a source delivered.

    Step 32 adds Slack and Google Chat, at which point "is ingestion working"
    stops being one number and becomes a per-provider question. The tempting way
    to answer it is to look at what came in; that is the one thing an operator
    may never do, so every figure here is a count, an age or a category from a
    closed set.

    Platform-wide and naming no workspace, like the other operations surfaces.
    A per-workspace view of what a customer is producing is a support session's
    business, not a dashboard's.
    """
    _ = staff
    fleet = await connector_ops.connector_health(db, settings)
    view = ConnectorFleetView.model_validate(fleet, from_attributes=True)
    view.subscriptions = await _google_chat_subscription_health(db, settings)
    return view


async def _google_chat_subscription_health(
    db: AsyncSession, settings: Settings
) -> SubscriptionHealthView:
    """Google Chat's lease health, fleet-wide.

    Composed here rather than inside `connector_ops.connector_health` because
    `gchat` imports `ops.connectors` for `SubscriptionRecord`; reading the leases
    from inside the read model would make that a cycle. The route is the layer
    that already knows about both.

    **An unconfigured deployment reports unobservable, not zero.** With no
    credentials there can be no leases, and "0 live, 0 suspended, 0 expired" is
    indistinguishable on a screen from a renewal loop that is working — which is
    the most reassuring possible rendering of "this connector was never set up".
    `subscription_health(None)` says so instead.

    Read on the platform session the route already holds. Under a tenant-scoped
    session row-level security would narrow the leases to one workspace and the
    result would still be labelled as the fleet.
    """
    configured = ConnectorProvider.GOOGLE_CHAT in connector_ops.configured_providers(settings)
    records = await gchat_subscriptions.fleet_subscription_records(db) if configured else None
    expected = await gchat_subscriptions.fleet_selected_space_count(db) if configured else None

    health = connector_ops.subscription_health(
        records, provider=ConnectorProvider.GOOGLE_CHAT, expected=expected
    )
    return SubscriptionHealthView(
        provider=health.provider.value,
        subscriptions_by_state=dict(health.subscriptions_by_state),
        subscriptions_by_error_category=dict(health.subscriptions_by_error_category),
        subscriptions_expected=health.subscriptions_expected,
        subscriptions_live=health.subscriptions_live,
        subscriptions_suspended=health.subscriptions_suspended,
        subscriptions_expired=health.subscriptions_expired,
        subscriptions_missing=health.subscriptions_missing,
        nearest_expiry_minutes=health.nearest_expiry_minutes,
        renewal_due_within_minutes=health.renewal_due_within_minutes,
        expiry_is_permanent_loss=health.expiry_is_permanent_loss,
        observable=health.observable,
        subscriptions_unobservable_reason=health.subscriptions_unobservable_reason,
    )


# --------------------------------------------------------------------------
# Consent gates
#
# Defined before the routes that use them. Below their first use, the names
# do not resolve when FastAPI reads the postponed annotations, and the
# dependency is dropped silently — which removes the gate rather than
# failing loudly.
# --------------------------------------------------------------------------


class GrantedAccess:
    """An approved session and the person using it."""

    __slots__ = ("session", "staff")

    def __init__(self, session: SupportSession, staff: StaffContext) -> None:
        self.session = session
        self.staff = staff


def _requires_session(scope: SupportScope, *roles: StaffRole) -> Callable[..., Any]:
    """Build the gate for one scope.

    Every condition is checked together — this workspace, this requester, this
    approved scope, not revoked, not expired — because a gate that checks four of
    five is a gate that opens. A `configuration_diagnostics` session never
    satisfies the content gate: widening needs a second request and a second
    approval (md/15 §5.2).
    """

    # Bound outside the signature deliberately. `from __future__ import
    # annotations` makes every annotation a string, and a string containing
    # `roles` cannot be resolved later — the closure's locals are not in module
    # globals, so FastAPI fell back to treating `staff` as a query parameter.
    role_check = requires_staff(*roles)

    async def dependency(
        tenant_id: uuid.UUID,
        db: PlatformDb,
        staff: StaffContext = Depends(role_check),
    ) -> GrantedAccess:
        session = await support.active_session_for(
            db, tenant_id=tenant_id, staff_user_id=staff.user.id, scope=scope
        )
        if session is None:
            raise ProblemDetailError(
                status_code=status.HTTP_403_FORBIDDEN,
                title="No approved support session",
                detail=(
                    f"This needs a support session approved for {scope.value} by that "
                    "workspace, and it must not have expired."
                ),
                problem_type="support-session-required",
            )
        return GrantedAccess(session, staff)

    return dependency


active_content_session = _requires_session(
    SupportScope.ACTIVITY_CONTENT, StaffRole.SUPPORT, StaffRole.ENGINEERING
)

active_configuration_session = _requires_session(
    SupportScope.CONFIGURATION_DIAGNOSTICS,
    StaffRole.SUPPORT,
    StaffRole.ENGINEERING,
    StaffRole.BILLING,
)


# --------------------------------------------------------------------------
# Tenants
# --------------------------------------------------------------------------


@router.get(
    "/tenants",
    response_model=list[StaffTenantSummary],
    summary="Every workspace, with its configuration and health",
)
async def list_tenants(
    staff: Annotated[StaffContext, Depends(requires_staff(*ANY_STAFF))],
    db: PlatformDb,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> list[StaffTenantSummary]:
    """List workspaces by name or slug.

    Reads are not audited. An audit log that records every list view fills with
    noise and buries the entries that matter — and a read of configuration is
    not the thing md/15 §5 exists to constrain. Reading a customer's *work*
    requires a support session, which is audited, approved and time-boxed.
    """
    statement = select(Tenant).order_by(Tenant.created_at.desc()).limit(limit)
    if search:
        pattern = f"%{search.lower()}%"
        statement = statement.where(
            func.lower(Tenant.name).like(pattern) | func.lower(Tenant.slug).like(pattern)
        )

    tenants = list(await db.scalars(statement))
    members = await _member_counts(db, [tenant.id for tenant in tenants])

    _ = staff
    return [
        StaffTenantSummary(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            region=tenant.region,
            created_at=tenant.created_at,
            member_count=members.get(tenant.id, 0),
        )
        for tenant in tenants
    ]


@router.get(
    "/tenants/{tenant_id}",
    response_model=StaffTenantDetail,
    summary="One workspace: configuration, integrations, and ingestion health",
    responses={404: {"description": "No such workspace."}},
)
async def get_tenant(
    tenant_id: uuid.UUID,
    granted: Annotated[GrantedAccess, Depends(active_configuration_session)],
    db: PlatformDb,
) -> StaffTenantDetail:
    """Everything an operator needs to diagnose a workspace, and nothing more.

    Counts, timestamps and connection state — no statement, no brief, no
    person's activity. The distinction is the product's central claim, so it is
    enforced by what this response model can hold rather than by care.
    """
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such workspace",
            detail="No workspace with that identifier.",
            problem_type="tenant-not-found",
        )

    members = await _member_counts(db, [tenant_id])
    installations = list(
        await db.scalars(
            select(GitHubInstallation).where(GitHubInstallation.tenant_id == tenant_id)
        )
    )
    last_delivery = await db.scalar(
        select(func.max(WebhookDelivery.created_at)).where(WebhookDelivery.tenant_id == tenant_id)
    )
    unprocessed = await db.scalar(
        select(func.count())
        .select_from(WebhookDelivery)
        .where(WebhookDelivery.tenant_id == tenant_id, WebhookDelivery.processed_at.is_(None))
    )
    running_backfills = await db.scalar(
        select(func.count())
        .select_from(BackfillRun)
        .where(BackfillRun.tenant_id == tenant_id, BackfillRun.completed_at.is_(None))
    )

    connected = [item for item in installations if item.uninstalled_at is None]
    stale = last_delivery is not None and datetime.now(UTC) - last_delivery > INGESTION_STALE_AFTER

    await support.record_access(
        db,
        support_session=granted.session,
        actor_user_id=granted.staff.user.id,
        scope=SupportScope.CONFIGURATION_DIAGNOSTICS,
        description="Read workspace settings and ingestion health",
    )
    await db.commit()

    return StaffTenantDetail(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        region=tenant.region,
        created_at=tenant.created_at,
        member_count=members.get(tenant_id, 0),
        retention_days=tenant.retention_days,
        github_connected=len(connected),
        github_disconnected=len(installations) - len(connected),
        last_delivery_at=last_delivery,
        unprocessed_deliveries=int(unprocessed or 0),
        running_backfills=int(running_backfills or 0),
        ingestion_stale=stale,
    )


@router.get(
    "/tenants/{tenant_id}/subscription",
    response_model=SubscriptionInspection,
    summary="Billing state, read without touching the payment provider",
    responses={404: {"description": "No such workspace."}},
)
async def inspect_subscription(
    tenant_id: uuid.UUID,
    granted: Annotated[GrantedAccess, Depends(active_configuration_session)],
    db: PlatformDb,
) -> SubscriptionInspection:
    """What CAIRN believes about this workspace's plan.

    md/15 screen 31 exists so an operator answering "why were we charged this"
    does not open Stripe and act on what they see there. Billing is not
    implemented (Step 31), so this reports what is known — seats and the plan
    CAIRN holds — and says plainly that no provider is connected, rather than
    inventing a subscription to fill the screen.
    """
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such workspace",
            detail="No workspace with that identifier.",
            problem_type="tenant-not-found",
        )

    members = await _member_counts(db, [tenant_id])

    await support.record_access(
        db,
        support_session=granted.session,
        actor_user_id=granted.staff.user.id,
        scope=SupportScope.CONFIGURATION_DIAGNOSTICS,
        description="Read the subscription inspector",
    )
    await db.commit()

    return SubscriptionInspection(
        tenant_id=tenant_id,
        seats_in_use=members.get(tenant_id, 0),
        plan="unbilled",
        provider_connected=False,
        note=(
            "Billing is not implemented. Seats are counted from memberships; no "
            "payment provider holds a subscription for this workspace."
        ),
    )


# --------------------------------------------------------------------------
# The audit log
# --------------------------------------------------------------------------


@router.get(
    "/audit",
    response_model=list[AuditEntryResponse],
    summary="What staff have done",
)
async def read_audit_log(
    staff: Annotated[StaffContext, Depends(requires_staff(StaffRole.SECURITY))],
    db: PlatformDb,
    tenant_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE,
) -> list[AuditEntryResponse]:
    """The log, newest first, optionally for one workspace."""
    statement = select(InternalAuditEntry).order_by(InternalAuditEntry.sequence.desc()).limit(limit)
    if tenant_id is not None:
        statement = statement.where(InternalAuditEntry.tenant_id == tenant_id)

    _ = staff
    return [
        AuditEntryResponse(
            sequence=entry.sequence,
            occurred_at=entry.occurred_at,
            actor_user_id=entry.actor_user_id,
            action=entry.action,
            tenant_id=entry.tenant_id,
            reason=entry.reason,
            detail=entry.detail,
            checksum=entry.entry_hash,
        )
        for entry in await db.scalars(statement)
    ]


@router.get(
    "/audit/verify",
    response_model=AuditVerification,
    summary="Check the audit chain end to end",
)
async def verify_audit_log(
    staff: Annotated[StaffContext, Depends(requires_staff(StaffRole.SECURITY))],
    db: PlatformDb,
) -> AuditVerification:
    """Walk every link and report the first break.

    Exposed as an endpoint rather than left to a script because the question it
    answers — "has this record been altered" — is one a customer may ask, and an
    answer that requires database access is one only staff can produce.
    """
    result = await audit.verify(db)

    if not result.intact:
        await logger.aerror(
            "internal.audit_chain_broken",
            broken_at=result.broken_at,
            entries=result.entries,
            checked_by=str(staff.user.id),
        )

    return AuditVerification(
        entries=result.entries,
        intact=result.intact,
        broken_at=result.broken_at,
        reason=result.reason,
    )


# --------------------------------------------------------------------------
# Support sessions
# --------------------------------------------------------------------------


@router.post(
    "/tenants/{tenant_id}/support-sessions",
    response_model=SupportSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ask a workspace for permission to look at it",
    responses={
        403: {"description": "Requires a support or engineering role."},
        404: {"description": "No such workspace."},
        422: {"description": "The requested duration is out of range."},
    },
)
async def request_support_session(
    tenant_id: uuid.UUID,
    body: SupportSessionRequest,
    db: PlatformDb,
    staff: Annotated[
        StaffContext,
        Depends(requires_staff(StaffRole.SUPPORT, StaffRole.ENGINEERING, StaffRole.BILLING)),
    ],
    audited_by: Annotated[StaffContext, Depends(audited("support.requested"))],
) -> SupportSessionResponse:
    """Request access. Grants nothing.

    The session is created `pending`. Only an Owner or Admin of that workspace
    can make it live, which is the whole model: staff ask, customers decide
    (md/15 §5.2).
    """
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such workspace",
            detail="No workspace with that identifier.",
            problem_type="tenant-not-found",
        )

    try:
        row = await support.request_session(
            db,
            tenant_id=tenant_id,
            requested_by_user_id=staff.user.id,
            reason=body.reason,
            scope=body.scope,
            minutes=body.minutes,
        )
    except support.SupportError as error:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="That request cannot be made",
            detail=error.message,
            problem_type=error.problem_type,
        ) from error

    await db.commit()
    _ = audited_by
    return _support_response(row, requested_by=staff.user.email)


@router.get(
    "/support-sessions",
    response_model=list[SupportSessionResponse],
    summary="The caller's own support requests and their status",
)
async def my_support_sessions(
    db: PlatformDb,
    staff: Annotated[
        StaffContext,
        Depends(
            requires_staff(
                StaffRole.SUPPORT,
                StaffRole.ENGINEERING,
                StaffRole.BILLING,
                StaffRole.SECURITY,
            )
        ),
    ],
) -> list[SupportSessionResponse]:
    """Only the caller's own requests.

    The minimum needed to act: whether the workspace said yes, and until when. A
    staff member has no reason to read what a colleague asked another customer
    for — that is the security role's view, through the audit log.
    """
    rows = list(
        await db.scalars(
            select(SupportSession)
            .where(SupportSession.requested_by_user_id == staff.user.id)
            .order_by(SupportSession.requested_at.desc())
            .limit(MAX_PAGE)
        )
    )
    return [_support_response(row, requested_by=staff.user.email) for row in rows]


@router.get(
    "/tenants/{tenant_id}/support/activity",
    response_model=list[FactResponse],
    summary="Read a workspace's activity under an approved content session",
    responses={403: {"description": "No approved, unexpired content session."}},
)
async def read_activity_under_support(
    tenant_id: uuid.UUID,
    db: PlatformDb,
    granted: Annotated[GrantedAccess, Depends(active_content_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[FactResponse]:
    """The only path from staff to customer content, and it records itself.

    The read happens through a tenant-scoped session, so row-level security
    still decides what is visible — the approval decides whether the door opens,
    not whether isolation applies.
    """
    async with tenant_session(tenant_id) as scoped:
        rows = list(
            await scoped.scalars(
                select(FactRow)
                .where(FactRow.tenant_id == tenant_id, FactRow.valid_until.is_(None))
                .order_by(FactRow.occurred_at.desc().nullslast())
                .limit(limit)
            )
        )
        facts = [_fact_response(row) for row in rows]

    await support.record_access(
        db,
        support_session=granted.session,
        actor_user_id=granted.staff.user.id,
        scope=SupportScope.ACTIVITY_CONTENT,
        description=f"Read {len(facts)} recorded activity statements",
    )
    await db.commit()

    return facts


def _support_response(row: SupportSession, *, requested_by: str) -> SupportSessionResponse:
    return SupportSessionResponse(
        id=row.id,
        requested_by=requested_by,
        reason=row.reason,
        requested_scope=row.requested_scope,
        approved_scope=row.approved_scope,
        status=row.status,
        active=row.is_active(),
        requested_minutes=row.requested_minutes,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        break_glass=row.break_glass,
        events=[],
    )


# --------------------------------------------------------------------------
# Staff management
# --------------------------------------------------------------------------


@router.post(
    "/staff/{user_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Grant back-office access",
    responses={403: {"description": "Requires the admin staff role."}},
)
async def grant_staff(
    user_id: uuid.UUID,
    role: Annotated[StaffRole, Query()],
    db: PlatformDb,
    staff: Annotated[StaffContext, Depends(requires_staff(StaffRole.SECURITY))],
    audited_by: Annotated[StaffContext, Depends(audited("staff.granted"))],
) -> None:
    """Make somebody staff.

    The first staff member is created by a migration or by hand — deliberately,
    since an endpoint that can bootstrap the first one is an endpoint that can
    bootstrap an attacker.
    """
    subject = await db.scalar(select(User).where(User.id == user_id))
    if subject is None:
        # Otherwise the foreign key rejects the insert and an operator sees a
        # 500 for a typo in a UUID.
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such account",
            detail="Nobody has an account with that identifier.",
            problem_type="user-not-found",
        )

    existing = await db.scalar(select(StaffMember).where(StaffMember.user_id == user_id))
    if existing is not None:
        existing.role = role
        existing.revoked_at = None
    else:
        db.add(StaffMember(user_id=user_id, role=role))

    await db.commit()
    _ = staff, audited_by


@router.delete(
    "/staff/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke back-office access",
    responses={
        403: {"description": "Requires the admin staff role."},
        404: {"description": "Not a staff member."},
    },
)
async def revoke_staff(
    user_id: uuid.UUID,
    db: PlatformDb,
    staff: Annotated[StaffContext, Depends(requires_staff(StaffRole.SECURITY))],
    audited_by: Annotated[StaffContext, Depends(audited("staff.revoked"))],
) -> None:
    """Revoke access, keeping the row.

    "Was this person staff in March" is a question an audit asks, and a deleted
    row cannot answer it.
    """
    if user_id == staff.user.id:
        # The realistic version is somebody tidying up and locking themselves
        # out of the tool they would use to undo it.
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="You cannot revoke your own access",
            detail="Ask another security-role colleague to revoke it.",
            problem_type="self-revocation",
        )

    member = await db.scalar(select(StaffMember).where(StaffMember.user_id == user_id))
    if member is None or member.revoked_at is not None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not staff",
            detail="That account does not have back-office access.",
            problem_type="staff-not-found",
        )

    if member.role is StaffRole.SECURITY:
        remaining = await db.scalar(
            select(func.count())
            .select_from(StaffMember)
            .where(
                StaffMember.role == StaffRole.SECURITY,
                StaffMember.revoked_at.is_(None),
                StaffMember.user_id != user_id,
            )
        )
        if not remaining:
            # Only the security role can grant staff access, so removing the
            # last one leaves an installation nobody can administer from inside.
            raise ProblemDetailError(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                title="This is the last security-role account",
                detail="Grant the security role to somebody else first.",
                problem_type="last-security-staff",
            )

    member.revoked_at = datetime.now(UTC)
    await db.commit()
    _ = staff, audited_by


async def _member_counts(db: AsyncSession, tenant_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Membership counts for several workspaces in one query."""
    if not tenant_ids:
        return {}

    rows = await db.execute(
        select(Membership.tenant_id, func.count().label("members"))
        .where(Membership.tenant_id.in_(tenant_ids))
        .group_by(Membership.tenant_id)
    )
    return {row.tenant_id: row.members for row in rows}
