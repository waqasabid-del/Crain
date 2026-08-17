"""The support-session lifecycle, in one place.

md/15 §5.2 states the model: requested by staff, approved by a workspace Owner
or Admin, time-boxed, scope-limited, and visible to the customer. Every rule
that decides whether access exists lives here rather than in a route, so a
second endpoint cannot reach a different answer.

**Staff never approve their own access.** The request and the decision are
separate endpoints, on separate connections, requiring separate identities — an
Owner or Admin of the workspace being opened.

**Configuration never widens to content.** A session approved for
`configuration_diagnostics` cannot read a statement, a brief or a citation. That
needs a second request, for `activity_content`, and a second approval.

**Break-glass is not implemented, and is not faked.** md/15 §5.2 permits access
without prior approval in a genuine emergency, on three conditions: immediate
customer notification, security-team review, and a permanent record. Email now
exists and the record would be straightforward, but there is no security-review
workflow and no escalation path — and a break-glass route with two of its three
conditions is an unapproved access path wearing a label. The column exists,
always false, so the customer-visible record can say "this was not break-glass"
truthfully. See md/16 Step 28 for the deferral.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.support_models import (
    SupportAccessEvent,
    SupportScope,
    SupportSession,
    SupportSessionStatus,
)
from cairn_api.internal import audit

logger = structlog.get_logger(__name__)

#: How long an approved session lasts when the request does not say (md/15 §5.2).
DEFAULT_MINUTES = 60

#: The longest any session may last. Enforced here and by a check constraint,
#: because a duration supplied by a caller is a duration an attacker chooses.
MAX_MINUTES = 240

#: The longest a content session may last.
#:
#: Shorter than the maximum on purpose: reading somebody's work is the access
#: this whole model exists to constrain, and four hours of it is standing access
#: with extra steps.
MAX_CONTENT_MINUTES = 60


class SupportError(Exception):
    """A support-session rule was broken. Carries a reader-facing message."""

    def __init__(self, message: str, *, problem_type: str) -> None:
        super().__init__(message)
        self.message = message
        self.problem_type = problem_type


async def request_session(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    requested_by_user_id: uuid.UUID,
    reason: str,
    scope: SupportScope,
    minutes: int = DEFAULT_MINUTES,
) -> SupportSession:
    """Record a staff request. Grants nothing.

    The returned session is `pending`: no access exists until somebody in the
    workspace approves it.
    """
    ceiling = MAX_CONTENT_MINUTES if scope is SupportScope.ACTIVITY_CONTENT else MAX_MINUTES
    if not 0 < minutes <= ceiling:
        raise SupportError(
            f"A {scope.value} session may last between 1 and {ceiling} minutes.",
            problem_type="support-duration-out-of-range",
        )

    row = SupportSession(
        tenant_id=tenant_id,
        requested_by_user_id=requested_by_user_id,
        reason=reason,
        requested_scope=scope,
        status=SupportSessionStatus.PENDING,
        requested_minutes=minutes,
    )
    session.add(row)
    await session.flush()

    await logger.ainfo(
        "support.requested",
        tenant_id=str(tenant_id),
        scope=scope.value,
        minutes=minutes,
    )
    return row


async def decide(
    session: AsyncSession,
    *,
    support_session: SupportSession,
    approver_user_id: uuid.UUID,
    approve: bool,
) -> SupportSession:
    """Approve or reject a pending request.

    The expiry is computed here from the server clock. A caller-supplied expiry
    is a caller-chosen one, and the whole point of a time box is that the
    subject of the access sets it.
    """
    if support_session.status is not SupportSessionStatus.PENDING:
        raise SupportError(
            "This request has already been decided.",
            problem_type="support-already-decided",
        )

    if support_session.requested_by_user_id == approver_user_id:
        # Unreachable through the API — staff and customers authenticate on
        # different routers — and asserted anyway, because the rule is the
        # feature (md/15 §5.2: "not granted by staff to themselves").
        raise SupportError(
            "The person who requested a session cannot approve it.",
            problem_type="support-self-approval",
        )

    now = datetime.now(UTC)
    support_session.decided_at = now
    support_session.decided_by_user_id = approver_user_id

    if not approve:
        support_session.status = SupportSessionStatus.REJECTED
        await logger.ainfo("support.rejected", tenant_id=str(support_session.tenant_id))
        return support_session

    support_session.status = SupportSessionStatus.APPROVED
    # Approving grants exactly what was asked for. Widening on approval would
    # mean a customer could be talked into more than the request they read.
    support_session.approved_scope = support_session.requested_scope
    support_session.expires_at = now + timedelta(minutes=support_session.requested_minutes)

    await logger.ainfo(
        "support.approved",
        tenant_id=str(support_session.tenant_id),
        scope=support_session.requested_scope.value,
        expires_at=support_session.expires_at.isoformat(),
    )
    return support_session


async def revoke(
    session: AsyncSession, *, support_session: SupportSession, revoker_user_id: uuid.UUID
) -> SupportSession:
    """End an approved session early.

    Revocation is available whatever the state, and is idempotent: somebody
    ending access under pressure should not have to read a status first.

    A rejection is not overwritten. Revoking an already-rejected request would
    replace "we said no" with "we ended it", and the customer-visible record is
    the one place that distinction is theirs to keep. The timestamp is still
    stamped, so the action is not lost either.
    """
    if support_session.revoked_at is None:
        support_session.revoked_at = datetime.now(UTC)
        support_session.revoked_by_user_id = revoker_user_id
        if support_session.status is not SupportSessionStatus.REJECTED:
            support_session.status = SupportSessionStatus.REVOKED
        await logger.ainfo(
            "support.revoked",
            tenant_id=str(support_session.tenant_id),
            revoked_by=str(revoker_user_id),
        )
    return support_session


async def lock_session(
    session: AsyncSession, *, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> SupportSession | None:
    """Read one session for update, so two decisions cannot race.

    Two Owners opening the same request and both clicking approve would
    otherwise both read `pending`, both pass the check, and the second would
    overwrite the first's expiry — a session lasting longer than either person
    agreed to. `FOR UPDATE` makes the second wait and then see the decision.
    """
    locked: SupportSession | None = await session.scalar(
        select(SupportSession)
        .where(SupportSession.id == session_id, SupportSession.tenant_id == tenant_id)
        .with_for_update()
    )
    return locked


async def active_session_for(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    staff_user_id: uuid.UUID,
    scope: SupportScope,
) -> SupportSession | None:
    """The session, if any, that lets this person read this scope right now.

    Every condition is checked together: the workspace, the requester, the
    approved scope, and the clock. A helper that answered "is there an approved
    session" without the other three would be the shape of the bug this exists
    to prevent.

    **Locked, because revocation races the read it is trying to stop.** Without
    `FOR UPDATE`, a customer clicking revoke while staff are mid-request commits
    against a row the gate has already read and passed, and the read completes
    under permission that no longer exists. The lock serialises the two: whoever
    reaches the row first wins, and the loser sees the other's outcome rather
    than a stale copy of it. Held only for the request that claimed it.
    """
    now = datetime.now(UTC)
    candidates = await session.scalars(
        select(SupportSession)
        .where(
            SupportSession.tenant_id == tenant_id,
            SupportSession.requested_by_user_id == staff_user_id,
            SupportSession.status == SupportSessionStatus.APPROVED,
            SupportSession.approved_scope == scope,
            SupportSession.revoked_at.is_(None),
            SupportSession.expires_at > now,
        )
        .with_for_update()
    )
    return next(iter(candidates), None)


async def resolve_participant_emails(user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Name the people in a support record, including the ones outside the workspace.

    **Why this needs a platform session.** The `users` policy shows a person only
    to contexts that share a workspace with them, and CAIRN staff are members of
    no customer workspace — that is the whole point of the support model. Read
    through the tenant session, the requester therefore resolves to nothing, and
    the customer's record of who asked to open their workspace says "unknown".
    A privacy record naming everybody except the person it is about is worse than
    no record: it reads as complete.

    The exposure is bounded by the ids, and the ids come from support rows
    row-level security already scoped to the caller's workspace: the staff member
    who asked about *your* workspace, and the colleague who decided. No caller
    supplies an id, so this cannot be turned into a directory.
    """
    if not user_ids:
        return {}

    from cairn_api.db.models import User
    from cairn_api.db.session import platform_session

    async with platform_session() as scoped:
        found = await scoped.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        return {row[0]: row[1] for row in found.all()}


async def record_access(
    session: AsyncSession,
    *,
    support_session: SupportSession,
    actor_user_id: uuid.UUID,
    scope: SupportScope,
    description: str,
) -> SupportAccessEvent:
    """Record that staff actually opened something, in both records.

    An approval is permission; this is use. Two rows, deliberately: the customer
    reads `support_access_events` in their own workspace, and the same fact goes
    into the Step 27 hash-chained internal log, which staff cannot rewrite. A
    customer-visible table alone would be a record the application role can
    update; the chain alone would be a record the customer cannot see.
    """
    event = SupportAccessEvent(
        tenant_id=support_session.tenant_id,
        session_id=support_session.id,
        scope=scope,
        description=description,
    )
    session.add(event)
    await session.flush()

    await audit.record(
        session,
        actor_user_id=actor_user_id,
        action="support.accessed",
        reason=support_session.reason,
        tenant_id=support_session.tenant_id,
        detail={"scope": scope.value, "session_id": str(support_session.id)},
    )

    await logger.ainfo(
        "support.accessed",
        tenant_id=str(support_session.tenant_id),
        scope=scope.value,
        description=description,
    )
    return event
