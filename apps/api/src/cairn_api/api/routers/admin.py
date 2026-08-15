"""Running a workspace without asking anyone for help.

Step 25's exit criterion is *an Owner can manage the workspace without
contacting support*, which is a support-cost target with a security consequence
attached: every task an administrator cannot do is a task a member of staff does
for them, in their data, on their word. The internal back-office (Step 27) exists
for the cases where that is genuinely necessary, and every case removed from that
list is one fewer reason for anybody at CAIRN to open a customer's workspace.

**Roles here govern configuration and never visibility.** Nothing in this module
tells an Owner more about a person than that person can see about themselves —
which rules out the field every other product's admin area has, and rules out one
this module was specifically tempted by. See `notification_status`.

**The dangerous operations are the ones with no undo**, and each is refused
rather than confirmed twice: a workspace cannot be left without an Owner, and
nobody can change their own role. Both are enforced here rather than in the
interface, because a confirmation dialog is a suggestion and a 422 is not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from cairn_api.api.dependencies import (
    CurrentMembership,
    PlatformDb,
    TenantDb,
    WorkspaceContext,
    requires,
)
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    IntegrationResponse,
    MembershipResponse,
    NotificationStatus,
    PersonNotification,
    PrivacySettings,
    PrivacyUpdate,
    RoleUpdate,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.github_models import GitHubInstallation
from cairn_api.db.models import Membership, Tenant, TenantRole
from cairn_api.pipeline import consent

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["administration"])

#: The shortest retention a workspace may set, in days.
#:
#: Seven, not one. Retention is enforced by deleting raw activity, and a window
#: shorter than the time it takes to notice a broken integration would destroy
#: the evidence needed to diagnose it — a setting whose main effect is to make
#: its own consequences unexplainable.
MIN_RETENTION_DAYS = 7

#: The longest. Two years, because "keep it forever" is a decision no interface
#: should let somebody make by dragging a slider: the data is other people's
#: activity, and the default is already twelve months (md/05 §B.4).
MAX_RETENTION_DAYS = 730


# --------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------


@router.patch(
    "/{workspace_id}/members/{user_id}",
    response_model=MembershipResponse,
    summary="Change what somebody may configure",
    responses={
        403: {"description": "Requires permission to change roles."},
        404: {"description": "No such member of this workspace."},
        422: {"description": "The change would leave no Owner, or is a self-demotion."},
    },
)
async def change_role(
    user_id: uuid.UUID,
    body: RoleUpdate,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.MEMBERS_CHANGE_ROLE))],
    db: TenantDb,
) -> MembershipResponse:
    """Change one member's role.

    **A role is about configuration, not about what they can see.** Moving
    somebody from Admin to Viewer takes away their ability to connect an
    integration; it takes away nothing about their colleagues' work, because
    there was never anything extra to take.

    Two refusals, both structural:

    - **Nobody changes their own role.** The realistic version of this is an
      Owner demoting themselves while tidying up and locking themselves out of
      billing on a Friday. There is a transfer flow for handing the workspace
      over; this is not it.
    - **The last Owner stays an Owner.** A workspace with no Owner cannot be
      given one from inside, so the recovery path is a support ticket — the exact
      thing this module exists to remove.
    """
    if user_id == context.user.id:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="You cannot change your own role",
            detail=(
                "Ask another Owner or Admin to change it. Changing your own role is how "
                "somebody locks themselves out of their own workspace."
            ),
            problem_type="self-role-change",
        )

    membership = await _member(db, context, user_id)

    if membership.role is TenantRole.OWNER and body.role is not TenantRole.OWNER:
        await _refuse_if_last_owner(db, context, user_id)

    previous = membership.role
    membership.role = body.role
    await db.commit()

    await logger.ainfo(
        "membership.role_changed",
        tenant_id=str(context.tenant_id),
        # Recorded because a role change is an authorisation event, and "who
        # granted this" is the question asked after an incident rather than
        # before one.
        actor_user_id=str(context.user.id),
        subject_user_id=str(user_id),
        previous=previous.value,
        role=body.role.value,
    )

    return _membership_response(membership)


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove somebody from this workspace",
    responses={
        403: {"description": "Requires permission to remove members."},
        404: {"description": "No such member of this workspace."},
        422: {"description": "The removal would leave the workspace with no Owner."},
    },
)
async def remove_member(
    user_id: uuid.UUID,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.MEMBERS_REMOVE))],
    db: TenantDb,
) -> None:
    """Remove a member's access.

    **Their record is not deleted with them.** The facts stay, still attributed,
    and this is the decision worth arguing with rather than the one it looks
    like. A leaver's work is the team's history — the decision they made in March
    is why the system is shaped as it is, and removing it on their last day
    rewrites the record for everyone still there.

    What ends is *access*: the membership row goes, the session it depends on
    stops resolving, and no new activity is captured because nothing links them
    to the workspace any more. Somebody who wants their record removed as well is
    exercising a different right (GDPR Article 17) through a different path,
    which is deliberately not an administrator's button.
    """
    membership = await _member(db, context, user_id)

    if membership.role is TenantRole.OWNER:
        await _refuse_if_last_owner(db, context, user_id)

    await db.delete(membership)
    await db.commit()

    await logger.ainfo(
        "membership.removed",
        tenant_id=str(context.tenant_id),
        actor_user_id=str(context.user.id),
        subject_user_id=str(user_id),
    )


async def _member(db: TenantDb, context: WorkspaceContext, user_id: uuid.UUID) -> Membership:
    membership = await db.scalar(
        select(Membership)
        .options(joinedload(Membership.user))
        .where(Membership.tenant_id == context.tenant_id, Membership.user_id == user_id)
    )
    if membership is None:
        # The tenant filter is redundant behind row-level security and stated
        # anyway: a 404 that depends on RLS alone becomes a 200 the day somebody
        # runs this query on a platform connection.
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not a member",
            detail="Nobody with that account is a member of this workspace.",
            problem_type="member-not-found",
        )
    return membership


async def _refuse_if_last_owner(
    db: TenantDb, context: WorkspaceContext, user_id: uuid.UUID
) -> None:
    """Refuse to remove the only Owner.

    Counted rather than assumed. "There must be another Owner, they invited
    three people" is the reasoning that empties a workspace.
    """
    remaining = await db.scalar(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.tenant_id == context.tenant_id,
            Membership.role == TenantRole.OWNER,
            Membership.user_id != user_id,
        )
    )
    if not remaining:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="This workspace needs an Owner",
            detail=(
                "Make somebody else an Owner first. A workspace with no Owner cannot be "
                "given one from inside it."
            ),
            problem_type="last-owner",
        )


def _membership_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        user_id=membership.user_id,
        email=membership.user.email,
        display_name=membership.user.display_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


# --------------------------------------------------------------------------
# Integrations
# --------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/integrations",
    response_model=list[IntegrationResponse],
    summary="What this workspace has connected",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def list_integrations(context: CurrentMembership, db: TenantDb) -> list[IntegrationResponse]:
    """Every integration, connected or not, and its state.

    Readable by every member rather than by administrators only. What is
    connected decides what CAIRN can see about the person reading — the same
    reasoning that puts the source list on the notification screen. Hiding it
    behind a role would mean a Viewer had to ask permission to find out what was
    being read about them.

    Disconnected installations are listed, not omitted: a gap in the feed is
    explained by "GitHub was disconnected on the 4th" and unexplained by silence.

    Read through the tenant-scoped connection even though the write below is
    platform-side. The application role has `SELECT` on this table behind a
    row-level-security policy, so the isolation is enforced by the database
    rather than by the `WHERE` clause being remembered.
    """
    installations = list(
        await db.scalars(
            select(GitHubInstallation)
            .where(GitHubInstallation.tenant_id == context.tenant_id)
            .order_by(GitHubInstallation.created_at)
        )
    )

    return [
        IntegrationResponse(
            source="github",
            account=installation.account_login,
            installation_id=installation.installation_id,
            connected_at=installation.created_at,
            disconnected_at=installation.uninstalled_at,
            suspended=installation.suspended_at is not None,
        )
        for installation in installations
    ]


@router.delete(
    "/{workspace_id}/integrations/github/{installation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop capturing activity from a GitHub installation",
    responses={
        403: {"description": "Requires permission to disconnect integrations."},
        404: {"description": "No such installation in this workspace."},
    },
)
async def disconnect_github(
    installation_id: int,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_DISCONNECT))],
    db: PlatformDb,
) -> None:
    """Stop capture from one installation.

    **Marked, not deleted**, and the two differ in what they promise. Marking
    stops every future delivery being processed — the ingestion path checks this
    already, because a suspended installation that kept delivering was treated as
    a consent problem rather than a bug. Deleting the row would additionally
    erase the record that the integration ever existed, which turns the months of
    activity it produced into facts with no explanation of where they came from.

    **What was already captured stays**, and the interface says so rather than
    letting an administrator discover it. Disconnecting is "stop reading", not
    "forget what you read": the second is a deletion request, it applies to
    everyone's shared history, and it is not a side effect of a button labelled
    *Disconnect*.

    This does not uninstall the GitHub App. CAIRN cannot revoke somebody else's
    installation, and pretending otherwise would leave an administrator believing
    they had removed an access grant that is still live on GitHub's side.
    """
    installation = await db.scalar(
        select(GitHubInstallation).where(
            GitHubInstallation.tenant_id == context.tenant_id,
            GitHubInstallation.installation_id == installation_id,
        )
    )
    if installation is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Not connected",
            detail="This workspace has no GitHub installation with that identifier.",
            problem_type="installation-not-found",
        )

    if installation.uninstalled_at is None:
        installation.uninstalled_at = datetime.now(UTC)
        await db.commit()

    await logger.ainfo(
        "integration.disconnected",
        tenant_id=str(context.tenant_id),
        actor_user_id=str(context.user.id),
        installation_id=installation_id,
    )


# --------------------------------------------------------------------------
# Privacy and data
# --------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/privacy",
    response_model=PrivacySettings,
    summary="Retention and region",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def get_privacy(context: CurrentMembership, db: TenantDb) -> PrivacySettings:
    """How long raw activity is kept, and where it lives.

    Readable by everybody for the same reason the integration list is: these are
    facts about what happens to the reader's own activity, and a person should
    not need a role to learn them.
    """
    tenant = await _tenant(db, context)
    return PrivacySettings(
        retention_days=tenant.retention_days,
        region=tenant.region,
        min_retention_days=MIN_RETENTION_DAYS,
        max_retention_days=MAX_RETENTION_DAYS,
    )


@router.put(
    "/{workspace_id}/privacy",
    response_model=PrivacySettings,
    summary="Change how long raw activity is kept",
    responses={
        403: {"description": "Requires permission to change workspace settings."},
        422: {"description": "The retention period is outside the permitted range."},
    },
)
async def set_privacy(
    body: PrivacyUpdate,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.WORKSPACE_SETTINGS))],
    db: TenantDb,
) -> PrivacySettings:
    """Set the retention period.

    **The setting is enforced by a sweep that deletes**, not by a filter that
    hides — see `retention.py`. A retention period nothing acts on is the worst
    kind of claim this product could make, because it is stated in the Trust &
    Privacy Center to an audience deciding whether to believe the rest of it.

    **Region is not changeable here**, and is returned so the interface can show
    it. Moving a workspace between regions is a data migration under compliance
    pressure (md/06 §6.3), not a dropdown — and a control that silently did
    nothing would be worse than its absence.

    Shortening the window takes effect on the next sweep, which will delete what
    has just fallen outside it. That is the honest consequence and the interface
    states it before the change, because "we deleted three months of raw activity
    because you typed 30" is not a thing to learn afterwards.
    """
    if not MIN_RETENTION_DAYS <= body.retention_days <= MAX_RETENTION_DAYS:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Retention period out of range",
            detail=(
                f"Raw activity is kept for between {MIN_RETENTION_DAYS} and "
                f"{MAX_RETENTION_DAYS} days."
            ),
            problem_type="retention-out-of-range",
        )

    tenant = await _tenant(db, context)
    previous = tenant.retention_days
    tenant.retention_days = body.retention_days
    await db.commit()

    await logger.ainfo(
        "workspace.retention_changed",
        tenant_id=str(context.tenant_id),
        actor_user_id=str(context.user.id),
        previous_days=previous,
        days=body.retention_days,
    )

    return PrivacySettings(
        retention_days=tenant.retention_days,
        region=tenant.region,
        min_retention_days=MIN_RETENTION_DAYS,
        max_retention_days=MAX_RETENTION_DAYS,
    )


async def _tenant(db: TenantDb, context: WorkspaceContext) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == context.tenant_id))
    if tenant is None:  # pragma: no cover — membership proves the tenant exists
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such workspace",
            detail="This workspace does not exist.",
            problem_type="workspace-not-found",
        )
    return tenant


# --------------------------------------------------------------------------
# Worker notification
# --------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/notifications",
    response_model=NotificationStatus,
    summary="Who has been told their activity may be captured",
    responses={
        403: {"description": "Requires permission to change workspace settings."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def notification_status(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.WORKSPACE_SETTINGS))],
    db: TenantDb,
) -> NotificationStatus:
    """Notification per person; opt-outs only as a number.

    **This is the asymmetry, and it is the most considered decision in the
    module.** md/15 §4.2 describes one screen showing "who has been notified, who
    has opted out". The first half is named per person and the second is not, and
    the two halves are different kinds of fact:

    - **Notification is the employer's obligation**, owed to each person
      individually before capture begins, with no regional exception. An Owner
      who cannot see that Priya has not been notified cannot discharge it, and
      cannot evidence it when a works council asks. So it is named.
    - **An opt-out is the person's own decision about their own record.** A list
      of names beside "opted out" is a list of employees who declined to be
      recorded, handed to the person who writes their review. It does not matter
      that no reasonable manager would misuse it; what matters is that a person
      deciding whether to opt out would have to weigh that possibility, which
      turns a privacy control into a career calculation and produces a low
      opt-out rate that means nothing.

    So the rate is reported and the names are not. That is also the number
    md/11 §7 makes the product's trust barometer and md/13 makes a phase gate —
    and a rate is exactly what a gate needs, where a list is not.

    The permission is `WORKSPACE_SETTINGS` rather than `CONTENT_READ`: whether a
    colleague has been notified is compliance administration rather than
    something everyone needs, and this endpoint names people.
    """
    memberships = list(
        await db.scalars(
            select(Membership)
            .options(joinedload(Membership.user))
            .where(Membership.tenant_id == context.tenant_id)
            .order_by(Membership.created_at)
        )
    )

    # Counted in the database rather than by loading rows and measuring the
    # list: the intent is a number, and a query that returns names is one
    # somebody later "just displays".
    opted_out_people = await db.scalar(
        select(func.count(func.distinct(SourceOptOut.person_id))).where(
            SourceOptOut.tenant_id == context.tenant_id
        )
    )

    return NotificationStatus(
        people=[
            PersonNotification(
                user_id=membership.user_id,
                email=membership.user.email,
                display_name=membership.user.display_name,
                notified_at=membership.notified_at,
            )
            for membership in memberships
        ],
        opted_out_count=int(opted_out_people or 0),
        member_count=len(memberships),
        sources=list(consent.SOURCES),
    )
