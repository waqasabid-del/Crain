"""Workspace and membership endpoints.

Closes audit finding O4. The permission model was fully tested and consulted
from exactly one place — `invite_to_workspace`. Here every mutating route
declares its requirement in the signature via `requires(...)`, so the check is
part of the route definition rather than a line someone can forget to write.

**What is deliberately absent is as important as what is here.** There is no
endpoint returning activity, contribution counts, or anything else describing
how much a person did. Roles govern configuration; they do not govern how much
is visible about a person (md/05 §A.2, md/15 §2.2) — and a members list is
precisely where a `lastActive` field first gets added, because every other SaaS
product has one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from cairn_api.api.dependencies import (
    ClientAddress,
    CurrentMembership,
    EmailSenderDep,
    PlatformDb,
    RateLimiterDep,
    SettingsDep,
    TenantDb,
    WorkspaceContext,
    enforce_rate_limit,
    requires,
)
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.ratelimit import INVITE_ACCEPT_PER_ADDRESS
from cairn_api.api.schemas import (
    AcceptInvitationRequest,
    ConnectGitHubRequest,
    GitHubInstallationResponse,
    InvitationPreviewResponse,
    InvitationResponse,
    InviteRequest,
    MembershipResponse,
    WorkspaceResponse,
)
from cairn_api.auth.permissions import Permission
from cairn_api.auth.service import accept_invitation, invite_to_workspace, preview_invitation
from cairn_api.db.auth_models import Invitation
from cairn_api.db.github_models import GitHubInstallation
from cairn_api.db.models import Membership, Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.email import invitation_message, send_best_effort
from cairn_api.github.backfill import create_run
from cairn_api.github.jobs import enqueue

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="Read a workspace",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def get_workspace(context: CurrentMembership, db: TenantDb) -> WorkspaceResponse:
    """Return the workspace the caller is a member of.

    Read through the tenant-scoped session rather than the platform one, even
    though membership is already proven. Two reasons: privileged connections
    should stay rare enough that `grep platform_db` remains reviewable, and it
    means row-level security is exercised on the ordinary read path, where a
    policy regression would show up immediately rather than in the one endpoint
    that happens to be scoped.
    """
    tenant = await db.get(Tenant, context.tenant_id)
    if tenant is None:
        # Unreachable in practice — membership implies the row exists. If it
        # ever fires, tenant context was lost and RLS filtered the row out,
        # which is the failure mode worth being loud about rather than
        # returning an empty response.
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Workspace not found",
            detail="No workspace with that ID is available to you.",
            problem_type="workspace-not-found",
        )
    return WorkspaceResponse.model_validate(tenant)


@router.get(
    "/{workspace_id}/members",
    response_model=list[MembershipResponse],
    summary="List workspace members",
)
async def list_members(context: CurrentMembership, db: TenantDb) -> list[MembershipResponse]:
    """List everyone in the workspace, with their roles.

    Available to every member, including Viewers, and identical for all of them.
    That symmetry is deliberate and load-bearing: an Owner sees exactly what a
    Member sees. Adding a field here that only Admins receive would be the first
    step towards the visibility hierarchy this product exists not to have.
    """
    memberships = (
        await db.scalars(
            select(Membership)
            .options(joinedload(Membership.user))
            .where(Membership.tenant_id == context.tenant_id)
            .order_by(Membership.created_at)
        )
    ).all()

    return [
        MembershipResponse(
            user_id=membership.user_id,
            email=membership.user.email,
            display_name=membership.user.display_name,
            role=membership.role,
            joined_at=membership.created_at,
        )
        for membership in memberships
    ]


@router.get(
    "/{workspace_id}/invitations",
    response_model=list[InvitationResponse],
    summary="List outstanding invitations",
    responses={403: {"description": "Requires permission to invite."}},
)
async def list_invitations(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.MEMBERS_INVITE))],
    db: TenantDb,
) -> list[InvitationResponse]:
    """List invitations that are still redeemable.

    Gated on the permission to *invite* rather than a separate read permission.
    Who has been invited but not yet joined is administrative information, and a
    Viewer having it serves no purpose while disclosing hiring intent.

    Superseded and accepted invitations are excluded — an admin asking "who is
    still outstanding" means exactly the rows a new invitation would conflict
    with.
    """
    invitations = (
        await db.scalars(
            select(Invitation)
            .where(
                Invitation.tenant_id == context.tenant_id,
                Invitation.accepted_at.is_(None),
                Invitation.superseded_at.is_(None),
            )
            .order_by(Invitation.created_at.desc())
        )
    ).all()

    return [InvitationResponse.model_validate(invitation) for invitation in invitations]


@router.post(
    "/{workspace_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationResponse,
    summary="Invite someone to the workspace",
    responses={
        403: {"description": "Requires permission to invite, or the role outranks yours."},
        409: {"description": "That address is already a member."},
    },
)
async def create_invitation(
    body: InviteRequest,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.MEMBERS_INVITE))],
    db: TenantDb,
    settings: SettingsDep,
    sender: EmailSenderDep,
) -> InvitationResponse:
    """Issue an invitation.

    Two escalation paths are closed in the service layer and worth restating,
    because the route is where someone would be tempted to re-implement them:
    a Member cannot invite at all, and nobody — including an Admin — can invite
    at a role above their own. Ownership moves by explicit transfer.

    The caller's `Membership` is passed rather than a tenant ID and a user ID,
    so the three facts cannot disagree.

    **The token is not returned.** It goes to the invited address and nowhere
    else. Returning it would let anyone who can invite also redeem, collapsing
    "invite an address" into "prove control of it".
    """
    issued = await invite_to_workspace(
        db, inviter=context.membership, email=body.email, role=body.role
    )
    workspace = await db.get(Tenant, context.tenant_id)
    # Committed before the send rather than by the session's exit, so a relay
    # failure cannot roll back an invitation the response reports as issued.
    await db.commit()

    await logger.ainfo(
        "invitation_issued",
        tenant_id=str(context.tenant_id),
        invited_by=str(context.user.id),
        role=str(body.role),
    )
    await send_best_effort(
        sender,
        invitation_message(
            settings,
            to=body.email,
            token=issued.token,
            workspace_name=workspace.name if workspace else "your workspace",
        ),
        event="invitation",
    )
    return InvitationResponse.model_validate(issued.invitation)


@router.delete(
    "/{workspace_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw an invitation",
    responses={
        403: {"description": "Requires permission to invite."},
        404: {"description": "No such outstanding invitation."},
    },
)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.MEMBERS_INVITE))],
    db: TenantDb,
) -> None:
    """Withdraw an invitation that has not been accepted.

    Marks it superseded rather than deleting it. "We invited this person and
    then withdrew it" is exactly the sort of question an audit trail is kept to
    answer, and the partial unique index treats superseded rows as free, so the
    address can be invited again immediately.
    """
    invitation = await db.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.tenant_id == context.tenant_id,
            Invitation.accepted_at.is_(None),
            Invitation.superseded_at.is_(None),
        )
    )
    if invitation is None:
        # Also covers an invitation in another workspace: the tenant filter plus
        # row-level security means it is not merely forbidden, it is invisible.
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="Invitation not found",
            detail="No outstanding invitation with that ID.",
            problem_type="invitation-not-found",
        )

    invitation.superseded_at = datetime.now(UTC)
    await logger.ainfo(
        "invitation_withdrawn",
        tenant_id=str(context.tenant_id),
        withdrawn_by=str(context.user.id),
    )


# -- Invitation acceptance --------------------------------------------------
#
# Deliberately not under /workspaces/{workspace_id}. The person redeeming an
# invitation is not yet a member, so `CurrentMembership` — which every route
# above depends on — would reject them before the handler ran. The workspace is
# identified by the token, which is the only thing they actually hold.

invitations_router = APIRouter(prefix="/invitations", tags=["invitations"])


@invitations_router.get(
    "/preview",
    response_model=InvitationPreviewResponse,
    summary="See who is inviting you, and where, before accepting",
    responses={
        409: {"description": "Unknown, expired, superseded, or already-accepted invitation."}
    },
)
async def preview(
    db: PlatformDb,
    token: str = Query(min_length=1, max_length=256),
) -> InvitationPreviewResponse:
    """Read-only. Nothing is created, changed, or consumed by looking.

    Deliberately unauthenticated, same as `accept` below: the reader may not
    have an account yet, so there is no session to require.
    """
    result = await preview_invitation(db, token=token)
    return InvitationPreviewResponse(
        email=result.email,
        role=result.role,
        workspace_name=result.workspace_name,
        invited_by_name=result.invited_by_name,
    )


@invitations_router.post(
    "/accept",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkspaceResponse,
    summary="Redeem an invitation",
    responses={
        409: {"description": "Unknown, expired, superseded, or already-accepted invitation."},
        422: {"description": "A new account was required and the password is too short."},
        429: {"description": "Too many attempts from this address."},
    },
)
async def accept(
    body: AcceptInvitationRequest,
    request: Request,
    response: Response,
    db: PlatformDb,
    limiter: RateLimiterDep,
    address: ClientAddress,
) -> WorkspaceResponse:
    """Join the workspace an invitation names.

    **The invited person joins the existing workspace.** No workspace is created
    — that is the entire point of this endpoint and the mistake it exists to
    prevent. A signup path that creates a workspace for every new account turns
    one team into several isolated single-person workspaces, each showing an
    empty brief. Everyone can sign in, so it looks like it works.

    Runs on the platform connection because there is no membership yet, and so
    no tenant context to scope to. This is one of three routes that legitimately
    do.

    Note that redeeming does **not** issue a session. The caller proves control
    of the address by holding the token, which is not the same as proving they
    know the password; signing them in here would let anyone who intercepts an
    invitation link take over an existing account.
    """
    await enforce_rate_limit(
        request,
        response,
        limiter,
        key=f"invite-accept:{address}",
        limit=INVITE_ACCEPT_PER_ADDRESS,
    )

    membership = await accept_invitation(
        db,
        token=body.token,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    tenant = await db.get(Tenant, membership.tenant_id)
    if tenant is None:  # pragma: no cover — the membership's foreign key guarantees it
        msg = f"Membership {membership.id} references a missing tenant"
        raise RuntimeError(msg)
    await db.commit()

    await logger.ainfo(
        "invitation_accepted",
        tenant_id=str(membership.tenant_id),
        user_id=str(membership.user_id),
        role=str(membership.role),
    )

    return WorkspaceResponse.model_validate(tenant)


@router.post(
    "/{workspace_id}/integrations/github",
    status_code=status.HTTP_201_CREATED,
    response_model=GitHubInstallationResponse,
    summary="Connect a GitHub App installation to this workspace",
    responses={
        403: {"description": "Requires permission to connect integrations."},
        409: {"description": "That installation is already connected elsewhere."},
    },
)
async def connect_github(
    body: ConnectGitHubRequest,
    request: Request,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.INTEGRATIONS_CONNECT))],
    db: PlatformDb,
) -> GitHubInstallationResponse:
    """Bind an installation to this workspace and start its backfill.

    **The only way an installation is ever created**, and deliberately so. An
    audit found the webhook path could resolve an installation and nothing could
    create one, which made Steps 11 to 13 unreachable end to end — but the fix
    is not to let the webhook create it. An inbound webhook creating the mapping
    would mean whoever installed the app has their activity bound to a workspace
    nobody chose. This runs behind a session, a membership and a permission
    check, which is the point at which we know who asked.

    Runs on the platform connection because the installation table is read
    before tenant context exists on the webhook path, so its writes live
    platform-side too.
    """
    existing = await db.scalar(
        select(GitHubInstallation).where(GitHubInstallation.installation_id == body.installation_id)
    )
    if existing is not None and existing.tenant_id != context.tenant_id:
        # Globally unique by design: an installation belongs to one workspace,
        # and two claiming it would each receive the other's activity.
        raise ProblemDetailError(
            status_code=status.HTTP_409_CONFLICT,
            title="Installation already connected",
            detail="That GitHub installation is connected to another workspace.",
            problem_type="installation-already-connected",
        )

    if existing is None:
        installation = GitHubInstallation(
            tenant_id=context.tenant_id,
            installation_id=body.installation_id,
            account_login=body.account_login,
            account_type=body.account_type,
        )
        db.add(installation)
    else:
        # Reconnecting after an uninstall. The row is retained rather than
        # deleted precisely so this is a revival with its history intact.
        installation = existing
        installation.uninstalled_at = None
        installation.suspended_at = None
        installation.account_login = body.account_login

    await db.flush()

    runs = 0
    if body.repositories:
        # Backfill runs are tenant-scoped data, so they are written through a
        # scoped session even though the installation above is not.
        async with tenant_session(context.tenant_id) as scoped:
            for repository in body.repositories:
                run = await create_run(
                    scoped,
                    tenant_id=context.tenant_id,
                    installation_id=body.installation_id,
                    repository=repository,
                )
                if run is not None:
                    await enqueue(request.app.state.queue, run)
                    runs += 1

    await db.commit()
    await logger.ainfo(
        "github.installation_connected",
        tenant_id=str(context.tenant_id),
        installation_id=body.installation_id,
        backfill_runs=runs,
    )

    return GitHubInstallationResponse(
        id=installation.id,
        installation_id=installation.installation_id,
        account_login=installation.account_login,
        account_type=installation.account_type,
        active=installation.is_active,
        backfill_runs=runs,
    )


__all__ = ["invitations_router", "router"]
