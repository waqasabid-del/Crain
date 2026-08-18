"""Meeting capture consent, over HTTP.

**Nothing here records a meeting.** CAIRN never joins one as a bot or a
participant (md/03 §4.2) and produces no recording and no transcript. There is no
provider integration behind these routes and none may be added until they exist:
this is the permission a future connector will have to hold, built first so it is
impossible to ship a connector that forgot to ask.

**Five routes, and the shape of the set is the design.** Two of them are `/me/`
routes that take no subject at all, and they are the *only* places a consent
decision is ever written. There is deliberately no route by which an Owner or an
Admin can answer for somebody — not gated behind a permission, not available to
the workspace's creator, absent. md/03 §3.1 records that in all-party states an
employer cannot mandate recording over an employee's objection, so a consent an
employer could write would be worth nothing; a route that could write one would
therefore be a route that manufactures worthless evidence and calls it consent.

**Eligibility is never asserted by a caller.** It is computed by
`meetings.eligibility.check` — the single gate — and written by
`meetings.service`. No request body on this router has a state, a flag or an
override, and no handler works out for itself whether everybody agreed.

**A participant never learns who else declined or is silent.** The workspace view
returns counts and states; the self view returns the caller's own answer. Neither
returns another person's decision, id, name or address, and the gate's
`public_message` says "somebody" precisely so that refusing costs nobody
anything.

**Staff have no access.** There is no internal route into any of this, and the
existing consent-gated support session is the only path CAIRN staff have into a
workspace at all.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status

from cairn_api.api.dependencies import CurrentMembership, TenantDb, WorkspaceContext, requires
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    MeetingCaptureCreateRequest,
    MeetingCaptureListResponse,
    MeetingCaptureResponse,
    MeetingDecisionRequest,
    MeetingStateCounts,
    MyMeetingRequestListResponse,
    MyMeetingRequestResponse,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.meeting_models import CaptureState, ConsentDecision
from cairn_api.meetings import service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["meetings"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: What the workspace view cannot answer, stated in the response.
#:
#: The reader most entitled to know this screen holds no per-person decisions is
#: the participant who is not looking at it, and the only way to make that
#: promise checkable from outside is to publish it beside the data.
WORKSPACE_NOTICE = (
    "Counts and states only. CAIRN cannot show you who agreed, who declined or "
    "who has not answered — a screen that named them would make refusing cost "
    "something, and a refusal that costs something is not a free choice. Nobody "
    "in this workspace can answer on somebody else's behalf, including you: "
    "every decision is written by the participant's own signed-in session."
)

#: The promise the participant's own screen makes.
SELF_NOTICE = (
    "Your answer, and nobody else's. You can change your mind at any time before "
    "anything is collected, and each answer is added to the record rather than "
    "replacing the last one. CAIRN never joins your meeting and never records "
    "it; agreeing means only that it may later receive a transcript the meeting "
    "platform itself produced. If anybody invited does not agree, nothing is "
    "collected at all."
)

#: The three answers a person may give, mapped to what is stored.
#:
#: An explicit table rather than a cast: the stored vocabulary also contains
#: `pending` and `expired`, and a `ConsentDecision(value)` here would be one
#: typo away from letting a caller file silence as an answer.
_DECISIONS = {
    "accepted": ConsentDecision.ACCEPTED,
    "declined": ConsentDecision.DECLINED,
    "withdrawn": ConsentDecision.WITHDRAWN,
}


@router.post(
    "/{workspace_id}/meetings/capture-requests",
    response_model=MeetingCaptureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ask everybody in a meeting whether CAIRN may collect it",
    responses={
        403: {"description": "Requires permission to manage workspace settings."},
        404: {"description": "No such workspace, or you are not a member."},
        409: {"description": "That meeting already has an open capture request."},
        422: {"description": "The window, or one of the people named, is not usable."},
    },
)
async def create_capture_request(
    body: MeetingCaptureCreateRequest,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.WORKSPACE_SETTINGS))],
    db: TenantDb,
) -> MeetingCaptureResponse:
    """Create the question. It grants nothing.

    The request lands `pending` with no consent rows at all, and stays there
    until every expected participant has affirmatively agreed from their own
    session. Silence never ages into agreement, so a request created and then
    forgotten collects nothing, forever.

    Gated on `WORKSPACE_SETTINGS` (Owner and Admin) because *asking* is a
    configuration action. What that gate emphatically does not confer is any
    ability to answer — see the module docstring.
    """
    try:
        view = await service.create_request(
            db,
            tenant_id=context.tenant_id,
            requested_by_user_id=context.user.id,
            provider=body.provider,
            external_meeting_ref=body.external_meeting_ref,
            scheduled_start=body.scheduled_start,
            scheduled_end=body.scheduled_end,
            purpose=body.purpose,
            person_ids=body.participant_person_ids,
        )
    except service.MeetingError as error:
        raise _problem(error) from error

    await db.commit()

    await logger.ainfo(
        "meeting.capture_requested",
        tenant_id=str(context.tenant_id),
        provider=body.provider.value,
        # A count and a provider. Never the meeting reference, never a person:
        # telemetry leaves the erasure path, and a meeting id there is a
        # participant identifier in a store nobody can clear.
        participants=len(view.expected),
    )
    return _response(view)


@router.get(
    "/{workspace_id}/meetings/capture-requests",
    response_model=MeetingCaptureListResponse,
    summary="Capture requests in this workspace, and where they stand",
    responses={
        403: {"description": "Requires permission to manage workspace settings."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def list_capture_requests(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.WORKSPACE_SETTINGS))],
    db: TenantDb,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> MeetingCaptureListResponse:
    """The list and the totals, with no per-person answer anywhere in either.

    Read-only, including the eligibility it reports: the gate is consulted for
    display and nothing is written, so opening this screen cannot change what
    CAIRN believes it is allowed to do.
    """
    views = await service.list_requests(db, tenant_id=context.tenant_id, limit=limit)

    # Counted into named fields rather than a map keyed by the enum: a state
    # added to the model would then be a compile-time hole here rather than a key
    # a client silently never sees.
    counts = Counter(view.meeting.state for view in views)

    return MeetingCaptureListResponse(
        requests=[_response(view) for view in views],
        totals=MeetingStateCounts(
            pending=counts[CaptureState.PENDING],
            eligible=counts[CaptureState.ELIGIBLE],
            refused=counts[CaptureState.REFUSED],
            expired=counts[CaptureState.EXPIRED],
            cancelled=counts[CaptureState.CANCELLED],
            completed=counts[CaptureState.COMPLETED],
        ),
        notice=WORKSPACE_NOTICE,
    )


@router.post(
    "/{workspace_id}/meetings/capture-requests/{meeting_id}/cancel",
    response_model=MeetingCaptureResponse,
    summary="Call off a capture request",
    responses={
        403: {"description": "Requires permission to manage workspace settings."},
        404: {"description": "No such capture request in this workspace."},
        422: {"description": "The request is already closed."},
    },
)
async def cancel_capture_request(
    meeting_id: uuid.UUID,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.WORKSPACE_SETTINGS))],
    db: TenantDb,
) -> MeetingCaptureResponse:
    """Withdraw the question.

    Only an open request can be cancelled. A refused one is already closed, and
    cancelling it would replace "somebody said no" with a tidier word — the
    record has to keep saying refused, because that is what the product may later
    have to demonstrate it honoured.
    """
    try:
        view = await service.cancel(db, tenant_id=context.tenant_id, meeting_id=meeting_id)
    except service.MeetingError as error:
        raise _problem(error) from error

    await db.commit()
    return _response(view)


@router.get(
    "/{workspace_id}/me/meeting-requests",
    response_model=MyMeetingRequestListResponse,
    summary="Meetings you have been asked about",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def my_meeting_requests(
    context: CurrentMembership,
    db: TenantDb,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> MyMeetingRequestListResponse:
    """The caller's own invitations to answer, and nobody else's.

    **Self only by construction rather than by a check.** The person is resolved
    from the caller's session; there is no subject parameter, no filter and no
    flag that widens it, so no role has a route through which to read what a
    colleague was asked or how they answered.

    **No permission is declared**, and requiring one would be the wrong axis.
    Every role including Viewer may answer a question about their own presence in
    a meeting, and making that a grant would mean a person's own consent was
    something the workspace let them have.
    """
    views = await service.my_requests(
        db,
        tenant_id=context.tenant_id,
        caller_user_id=context.user.id,
        limit=limit,
    )
    return MyMeetingRequestListResponse(
        requests=[_self_response(view) for view in views],
        notice=SELF_NOTICE,
    )


@router.post(
    "/{workspace_id}/me/meeting-requests/{meeting_id}/decision",
    response_model=MyMeetingRequestResponse,
    summary="Agree, refuse, or take your agreement back",
    responses={
        404: {"description": "You have no meeting request with that identifier."},
        422: {"description": "The request is closed, or that answer does not apply."},
    },
)
async def decide_meeting_request(
    meeting_id: uuid.UUID,
    body: MeetingDecisionRequest,
    context: CurrentMembership,
    db: TenantDb,
) -> MyMeetingRequestResponse:
    """Record the caller's own answer, and recompute what it makes possible.

    **The only route in the product that writes a consent decision.** The user id
    stored in `decided_by_user_id` is the one the session cookie resolved to, and
    the body has no field that could name anybody else — so an administrator
    calling this records their own answer to their own invitation, or gets a 404.

    **404, not 403, for a decision that is not the caller's.** Whether a meeting
    exists is not a non-participant's to confirm, and a 403 would confirm it —
    turning this into a way of discovering which colleagues are in a meeting
    somebody asked to capture.

    **Append-only.** Changing your mind supersedes the previous row and inserts a
    new one; nothing is updated in place and nothing is deleted, because the
    history is the product's only evidence that withdrawal was possible and
    honoured.
    """
    try:
        view = await service.record_decision(
            db,
            tenant_id=context.tenant_id,
            meeting_id=meeting_id,
            caller_user_id=context.user.id,
            decision=_DECISIONS[body.decision.value],
        )
    except service.MeetingError as error:
        raise _problem(error) from error

    await db.commit()

    await logger.ainfo(
        "meeting.decision_recorded",
        tenant_id=str(context.tenant_id),
        # The answer and the resulting standing. Never who gave it — a decision
        # attributable in telemetry is a decision with a social cost, and this
        # log leaves the erasure path.
        decision=body.decision.value,
        state=view.meeting.state.value,
    )
    return _self_response(view)


def _response(view: service.MeetingView) -> MeetingCaptureResponse:
    """The workspace's view: counts and standing, never a person.

    `accepted_count` is withheld once a request is refused. With the refusal
    already visible, a count of acceptances identifies the person who refused by
    arithmetic — which is exactly the disclosure the whole module is shaped to
    prevent, arrived at by subtraction rather than by a name.
    """
    refused = view.meeting.state is CaptureState.REFUSED
    return MeetingCaptureResponse(
        id=view.meeting.id,
        provider=view.meeting.provider,
        scheduled_start=view.meeting.scheduled_start,
        scheduled_end=view.meeting.scheduled_end,
        purpose=view.meeting.purpose,
        state=view.meeting.state,
        policy_version=view.meeting.policy_version,
        requested_at=view.meeting.created_at,
        participant_count=len(view.expected),
        accepted_count=None if refused else view.accepted,
        eligible=view.eligibility.allowed,
        reason=view.eligibility.reason,
        message=view.eligibility.public_message,
    )


def _self_response(view: service.MyMeetingView) -> MyMeetingRequestResponse:
    """The participant's view: their own answer, and the request's standing.

    There is no field here that could carry another participant's decision, and
    none that names anybody at all. The standing is shown because somebody who
    was asked is entitled to know whether anything will be collected; who caused
    that standing is not theirs to learn.
    """
    return MyMeetingRequestResponse(
        id=view.meeting.id,
        provider=view.meeting.provider,
        scheduled_start=view.meeting.scheduled_start,
        scheduled_end=view.meeting.scheduled_end,
        purpose=view.meeting.purpose,
        state=view.meeting.state,
        policy_version=view.meeting.policy_version,
        participant_count=view.participant_count,
        my_decision=view.decision.decision if view.decision is not None else None,
        my_decided_at=view.decision.decided_at if view.decision is not None else None,
        can_decide=view.meeting.state in service.OPEN,
        message=view.eligibility.public_message,
    )


def _problem(error: service.MeetingError) -> ProblemDetailError:
    """One translation, so a rule cannot be a 404 on one route and a 422 on another."""
    return ProblemDetailError(
        status_code=error.status_code,
        title=_TITLES.get(error.status_code, "That request cannot be recorded"),
        detail=error.message,
        problem_type=error.problem_type,
    )


_TITLES = {
    status.HTTP_404_NOT_FOUND: "No such meeting request",
    status.HTTP_409_CONFLICT: "That meeting already has a request",
}
