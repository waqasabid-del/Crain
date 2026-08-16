"""Support access, from the customer's side.

md/15 §5.2: access is requested by CAIRN staff and *approved by the workspace*.
This router is the approving half — the only place a support session can become
live — and the record the customer reads afterwards.

**The history needs no permission beyond membership.** Who looked at your
workspace is not administrative information. A Viewer has the same stake in it
as an Owner, and a record only managers can read is one the people it concerns
have to take on trust.

**Deciding needs `SUPPORT_SESSION_DECIDE`**, held by Owner and Admin. Approval is
an explicit action on an explicit request, never implied by reading it.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import CurrentMembership, TenantDb, WorkspaceContext, requires
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    SupportAccessEventResponse,
    SupportDecision,
    SupportSessionResponse,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.models import User
from cairn_api.db.support_models import SupportSession
from cairn_api.internal import support

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["support"])

DEFAULT_HISTORY = 50
MAX_HISTORY = 200


@router.get(
    "/{workspace_id}/support-sessions",
    response_model=list[SupportSessionResponse],
    summary="Every time CAIRN staff asked to look at this workspace",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def list_support_sessions(
    context: CurrentMembership,
    db: TenantDb,
    limit: Annotated[int, Query(ge=1, le=MAX_HISTORY)] = DEFAULT_HISTORY,
) -> list[SupportSessionResponse]:
    """The workspace's own support history, newest first.

    Readable by every member. Row-level security scopes it to this workspace, so
    the isolation is the database's rather than this query's to remember.
    """
    rows = list(
        await db.scalars(
            select(SupportSession)
            .where(SupportSession.tenant_id == context.tenant_id)
            .order_by(SupportSession.requested_at.desc())
            .limit(limit)
        )
    )
    return await _responses(db, rows)


@router.post(
    "/{workspace_id}/support-sessions/{session_id}/decision",
    response_model=SupportSessionResponse,
    summary="Approve or reject a support request",
    responses={
        403: {"description": "Requires permission to decide support access."},
        404: {"description": "No such request in this workspace."},
        422: {"description": "The request has already been decided."},
    },
)
async def decide_support_session(
    session_id: uuid.UUID,
    body: SupportDecision,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.SUPPORT_SESSION_DECIDE))],
    db: TenantDb,
) -> SupportSessionResponse:
    """Let CAIRN staff in, or refuse.

    The expiry is set here from the server clock, using the minutes the request
    asked for. Nothing a caller sends decides how long access lasts.
    """
    row = await _session_or_404(db, context, session_id)

    try:
        await support.decide(
            db, support_session=row, approver_user_id=context.user.id, approve=body.approve
        )
    except support.SupportError as error:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="That decision cannot be recorded",
            detail=error.message,
            problem_type=error.problem_type,
        ) from error

    await db.commit()

    await logger.ainfo(
        "support.decided",
        tenant_id=str(context.tenant_id),
        approved=body.approve,
        decided_by=str(context.user.id),
    )
    return (await _responses(db, [row]))[0]


@router.post(
    "/{workspace_id}/support-sessions/{session_id}/revoke",
    response_model=SupportSessionResponse,
    summary="End support access now",
    responses={
        403: {"description": "Requires permission to decide support access."},
        404: {"description": "No such request in this workspace."},
    },
)
async def revoke_support_session(
    session_id: uuid.UUID,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.SUPPORT_SESSION_DECIDE))],
    db: TenantDb,
) -> SupportSessionResponse:
    """Withdraw access before it expires.

    Idempotent, and available whatever the state: somebody ending access under
    pressure should not have to read a status first.
    """
    row = await _session_or_404(db, context, session_id)
    await support.revoke(db, support_session=row, revoker_user_id=context.user.id)
    await db.commit()
    return (await _responses(db, [row]))[0]


async def _session_or_404(
    db: AsyncSession, context: WorkspaceContext, session_id: uuid.UUID
) -> SupportSession:
    """The session, locked for update.

    Every caller of this helper is about to decide something, and two Owners
    deciding at once must not both see `pending`.
    """
    row = await support.lock_session(db, tenant_id=context.tenant_id, session_id=session_id)
    if row is None:
        # The tenant filter is redundant behind row-level security and stated
        # anyway: a 404 that depends on RLS alone becomes a 200 the day somebody
        # runs this query on a platform connection.
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such support request",
            detail="This workspace has no support request with that identifier.",
            problem_type="support-session-not-found",
        )
    return row


async def _responses(db: AsyncSession, rows: list[SupportSession]) -> list[SupportSessionResponse]:
    """Attach the human names a customer needs to read the record.

    Staff are shown by email rather than by id: "approved access for someone" is
    not an answer anybody can act on. One query for every name rather than one
    per row.
    """
    ids = {row.requested_by_user_id for row in rows} | {
        row.decided_by_user_id for row in rows if row.decided_by_user_id
    }
    emails: dict[uuid.UUID, str] = {}
    if ids:
        found = await db.execute(select(User.id, User.email).where(User.id.in_(ids)))
        emails = dict(found.all())  # type: ignore[arg-type]

    return [
        SupportSessionResponse(
            id=row.id,
            requested_by=emails.get(row.requested_by_user_id, "unknown@cairn.dev"),
            reason=row.reason,
            requested_scope=row.requested_scope,
            approved_scope=row.approved_scope,
            status=row.status,
            active=row.is_active(),
            requested_minutes=row.requested_minutes,
            requested_at=row.requested_at,
            decided_at=row.decided_at,
            decided_by=emails.get(row.decided_by_user_id) if row.decided_by_user_id else None,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            break_glass=row.break_glass,
            events=[
                SupportAccessEventResponse(
                    occurred_at=event.occurred_at,
                    scope=event.scope,
                    description=event.description,
                )
                for event in sorted(row.events, key=lambda item: item.occurred_at)
            ],
        )
        for row in rows
    ]
