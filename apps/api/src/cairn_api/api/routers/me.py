"""My Week, and the correction that makes it the reader's own record.

md/05 §B.2.3 commits to **employee-owned records**, and that commitment is what
this router implements rather than describes. Two endpoints:

`GET /me/week` — what CAIRN believes about the person asking, and nothing else.
Not the team's activity filtered to them by the interface: the query itself is
scoped to their `Person`, so a bug here shows *less* than it should rather than
somebody else's record.

`POST /facts/{id}/correction` — one call, no review queue, no ticket. md/09 §9
makes correction an **input**: a person who was there disagreeing with a machine
is the strongest evidence this system can hold, and treating it as feedback to be
triaged would be treating the record as ours rather than theirs.

**No permission check on correcting, deliberately.** Every role can correct, and
the constraint is not the role but the subject: `POST` refuses a fact that does
not concern the caller. An Owner cannot rewrite what CAIRN said about somebody
else — which is the same symmetry rule the read endpoints follow (md/15 §2.2),
applied to writes. A permission would have made this a question of seniority,
which is exactly the wrong axis.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import CurrentMembership, TenantDb, WorkspaceContext, requires
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    CapacityResponse,
    CapacityUpdate,
    ConsentResponse,
    ConsentUpdate,
    ConsentUpdateResponse,
    CorrectionRequest,
    CorrectionResponse,
    FactPage,
    FactResponse,
    SourceConsent,
    WorkRoleResponse,
    WorkRoleUpdate,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson
from cairn_api.db.identity_models import Person, PersonCapacity
from cairn_api.pipeline import consent
from cairn_api.pipeline.corrections import CorrectionError, CorrectionKind, apply_correction

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["me"])

#: How far back "my week" reaches when nothing is asked for.
#:
#: Seven days, matching the name. A reader opening their own record is asking
#: "what did I do", and a month of it is a different question they did not ask.
DEFAULT_DAYS = 7


async def _person_for(db: TenantDb, context: WorkspaceContext) -> Person | None:
    """The `Person` record for the caller, if the identity graph has linked one.

    A user and a person are deliberately different things (md/01 §5.3): somebody
    can appear in commit history for months before they ever sign in, and the
    link is made when an identity is matched. So this can legitimately return
    `None` — for a member who has an account and whose commits have not been
    attributed to them yet.
    """
    person: Person | None = await db.scalar(select(Person).where(Person.user_id == context.user.id))
    return person


@router.get(
    "/{workspace_id}/me/week",
    response_model=FactPage,
    summary="What CAIRN believes about you",
    responses={
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def my_week(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    since: Annotated[datetime | None, Query(description="Defaults to seven days ago.")] = None,
    until: Annotated[datetime | None, Query(description="Defaults to now.")] = None,
) -> FactPage:
    """The caller's own record.

    **Scoped in the query, not in the response.** Filtering the team's facts down
    to the reader in the interface would mean one forgotten condition shows a
    person somebody else's record — the failure that turns a trust product into
    a surveillance complaint. Scoping the query means the same bug shows nothing.

    Superseded facts are excluded, so a correction takes effect the moment it is
    made. That is the point of the screen: a person who fixes something should
    see it fixed, not see their correction queued behind a nightly job.
    """
    person = await _person_for(db, context)
    if person is None:
        # An account with no attributed identity yet. An empty page is the
        # truthful answer and the interface says so in words — an error would
        # imply a fault where there is only a person who has not committed
        # anything under an address CAIRN has matched.
        return FactPage(items=[])

    end = until or datetime.now(UTC)
    start = since or (end - timedelta(days=DEFAULT_DAYS))

    rows = list(
        await db.scalars(
            select(FactRow)
            .join(FactPerson, FactPerson.fact_id == FactRow.id)
            .where(
                FactRow.tenant_id == context.tenant_id,
                FactPerson.person_id == person.id,
                FactRow.valid_until.is_(None),
                FactRow.occurred_at >= start,
                FactRow.occurred_at <= end,
            )
            .order_by(FactRow.occurred_at.desc())
        )
    )

    from cairn_api.api.routers.facts import _fact_response

    return FactPage(items=[_fact_response(row) for row in rows])


@router.post(
    "/{workspace_id}/facts/{fact_id}/correction",
    response_model=CorrectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Correct something CAIRN said about you",
    responses={
        403: {"description": "That fact is not about you."},
        404: {"description": "No such fact in this workspace."},
        409: {"description": "That fact has already been superseded."},
        422: {"description": "A reworded correction needs the corrected sentence."},
    },
)
async def correct(
    fact_id: uuid.UUID,
    body: CorrectionRequest,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
) -> CorrectionResponse:
    """Record a correction, superseding the fact it corrects.

    **The check is subject, not seniority.** A caller may correct a fact that
    concerns them and no other, whatever their role. An Owner rewriting what
    CAIRN said about somebody else would be the product taking a person's record
    away from them at exactly the moment it matters most.
    """
    person = await _person_for(db, context)
    if person is None:
        raise ProblemDetailError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Not your record",
            detail="CAIRN has not linked any activity to your account yet.",
            problem_type="not-your-record",
        )

    concerns_caller = await db.scalar(
        select(FactPerson.id).where(
            FactPerson.fact_id == fact_id, FactPerson.person_id == person.id
        )
    )
    if concerns_caller is None:
        # Deliberately 403 rather than 404. The caller can already see this fact
        # on the team's feed, so pretending it does not exist would be a lie
        # they can immediately disprove — and the honest message is the one that
        # explains the rule.
        raise ProblemDetailError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Not your record",
            detail=(
                "You can correct what CAIRN says about you. This is about "
                "somebody else, and their record is theirs to correct."
            ),
            problem_type="not-your-record",
        )

    try:
        replacement = await apply_correction(
            db,
            tenant_id=context.tenant_id,
            fact_id=fact_id,
            kind=CorrectionKind(body.kind),
            user_id=context.user.id,
            statement=body.statement,
            note=body.note,
        )
    except CorrectionError as exc:
        raise ProblemDetailError(
            status_code=(
                status.HTTP_409_CONFLICT
                if "superseded" in str(exc)
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            title="Correction could not be applied",
            detail=str(exc),
            problem_type="correction-rejected",
        ) from exc

    await db.commit()

    await logger.ainfo(
        "correction.recorded",
        tenant_id=str(context.tenant_id),
        fact_id=str(fact_id),
        kind=body.kind,
        replaced=replacement is not None,
    )

    return CorrectionResponse(
        corrected_fact_id=fact_id,
        replacement=_fact_or_none(replacement),
    )


#: What each source means, in the words the notification uses.
#:
#: Held here rather than in the interface so that every surface — the web app,
#: the notification email, a future mobile client — states the same thing. md/11
#: §4.1 requires the notification to say plainly what is tracked and what is
#: not; three copies of that sentence is three chances for one of them to be
#: out of date and wrong.
SOURCE_COPY: dict[str, tuple[str, str]] = {
    "github": (
        "GitHub",
        "Commit messages, pull request titles and reviews. Never the contents of your code.",
    ),
    # Two entries, not one "Chat". A person connects, authorises and disconnects
    # these separately, so one toggle could not express "stop reading my Slack
    # but keep Google Chat" — and the coarser reading always won.
    "slack": (
        "Slack",
        "Messages in the public channels your workspace connects. Never direct messages.",
    ),
    "google_chat": (
        "Google Chat",
        "Messages in the spaces your workspace connects. Never direct messages.",
    ),
    "meeting": (
        "Meetings",
        "Transcripts of meetings your workspace connects. Never audio, and never a recording.",
    ),
    "document": (
        "Documents",
        "Titles and change summaries of documents your workspace connects. Never their contents.",
    ),
}

#: What CAIRN contractually refuses to do (md/05 §B.3.4).
#:
#: Stated at the moment a person is deciding whether to opt out, which is when
#: they are most entitled to read it — not on a policy page they would have to
#: go looking for. Written as things CAIRN *will not do*, because a promise
#: phrased as a capability ("we support anonymised reporting") is one a reader
#: has to translate before they can trust it.
REFUSALS: tuple[str, ...] = (
    "CAIRN never scores or ranks people.",
    "CAIRN never compares one person's work with another's.",
    "CAIRN is never used to make employment decisions.",
    "Your record is yours: you can correct anything in it, and opt out of any source.",
    "Everyone in your workspace sees the same things about you that you see.",
)


async def apply_capacity(person: Person, capacity: PersonCapacity) -> None:
    """The one place `capacity_stated_at` is ever assigned.

    A test greps the codebase for a second writer; if you are adding one, you
    are either computing capacity (which CAIRN never does - the person states
    it) or overriding somebody's self-description (which no role may do).
    """
    from datetime import UTC, datetime

    from cairn_api.db.identity_models import PersonCapacity as Capacity

    person.capacity = capacity
    person.capacity_stated_at = None if capacity is Capacity.NOT_STATED else datetime.now(UTC)


@router.put(
    "/{workspace_id}/me/capacity",
    response_model=CapacityResponse,
    summary="State your own availability, or withdraw the statement",
    responses={
        404: {"description": "No such workspace, or no record to state it on."},
    },
)
async def set_my_capacity(
    body: CapacityUpdate, context: CurrentMembership, db: TenantDb
) -> CapacityResponse:
    """Self-declared capacity: the person states it, everybody sees it.

    **Self only, by construction rather than by a check** - the same shape as
    the work-role endpoint above. The person is resolved from the caller's own
    session; no parameter exists through which a target could be named, so an
    Owner with every permission still cannot set a colleague's capacity.
    Nothing anywhere computes this value: availability inferred from activity
    would be monitoring wearing a helpful face, and `PersonCapacity`'s
    docstring records why there is no history table either.
    """
    person = await _person_for(db, context)
    if person is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No record yet",
            detail=(
                "Capacity lives on your record, and this workspace has not "
                "created one for you yet - it appears with your first "
                "attributed activity or identity confirmation."
            ),
            problem_type="no-person-record",
        )

    await apply_capacity(person, PersonCapacity(body.capacity))
    await db.commit()

    await logger.ainfo(
        "capacity.stated",
        tenant_id=str(context.tenant_id),
        # The value is deliberately not logged: it is a statement about a
        # person, and the log store holds ids and counts only.
    )
    return CapacityResponse(
        capacity=person.capacity.value
        if hasattr(person.capacity, "value")
        else str(person.capacity),
        capacity_stated_at=person.capacity_stated_at,
    )


@router.get(
    "/{workspace_id}/me/role",
    response_model=WorkRoleResponse,
    summary="What the caller says they do",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def my_role(context: CurrentMembership) -> WorkRoleResponse:
    """The caller's own work role.

    Also on the session, which is where every screen reads it from. This exists
    for the one case the session does not cover: confirming what was saved
    without re-authenticating.
    """
    return WorkRoleResponse(work_role=context.membership.work_role)


@router.put(
    "/{workspace_id}/me/role",
    response_model=WorkRoleResponse,
    summary="Say what you do, or withdraw the answer",
    responses={
        404: {"description": "No such workspace, or you are not a member."},
        422: {"description": "Not a role CAIRN knows."},
    },
)
async def set_my_role(
    body: WorkRoleUpdate, context: CurrentMembership, db: TenantDb
) -> WorkRoleResponse:
    """Record what the caller does.

    **Self only, by construction rather than by a check.** The membership being
    written is the one the caller's own session resolved to; there is no path
    through this API that sets anybody else's. That absence is the design: an
    administrator who could label a colleague's role would be storing a
    management classification on their record, in a product whose position is
    that it does not do that (md/05 §B.2).

    **It changes emphasis and never access.** What CAIRN opens on, and how a
    person's own record is framed. Every role sees the same facts, and
    `test_roles.py` asserts it rather than trusting that nobody will wire a
    filter to this field later.

    **Null is accepted**, because withdrawing the answer has to be as easy as
    giving it — otherwise the only way out of a wrong guess is a different wrong
    guess.

    No permission is declared. Every role including Viewer may answer a question
    about themselves, and requiring one would mean a person's own description of
    their work was something the workspace granted them.
    """
    context.membership.work_role = body.work_role
    await db.commit()

    await logger.ainfo(
        "membership.work_role_set",
        tenant_id=str(context.tenant_id),
        # The value, not the person: this is a count of how the product is used,
        # and a log line pairing a name with a self-description is a record
        # nobody asked us to keep.
        work_role=body.work_role.value if body.work_role is not None else None,
    )
    return WorkRoleResponse(work_role=context.membership.work_role)


@router.get(
    "/{workspace_id}/me/sources",
    response_model=ConsentResponse,
    summary="What CAIRN may attribute to you, and what it never does",
    responses={
        403: {"description": "Requires permission to read content."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def my_sources(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
) -> ConsentResponse:
    """Every source, whether the caller has opted out, and the refusals.

    **Every source is listed, not only the connected ones.** md/11 §4.1 requires
    the notification to reach a person *before* any of their activity is
    captured, which means before their workspace has necessarily connected
    anything. An opt-out for a source nobody has connected yet is not pointless
    — it is a person deciding in advance, which is the strongest form the choice
    can take.

    **Serving this is what "notified" means**, and it is recorded here. Worker
    notification is a legal obligation before first capture with no regional
    exception, and an obligation nobody can evidence is one an Owner has to take
    on trust at the moment a works council asks them not to. This response *is*
    the notification — what is read, and the control for switching it off — so
    the moment it is delivered is the honest moment to stamp. Deliberately
    narrower than "they read it", which no software knows.
    """
    await _record_notification(db, context)

    person = await _person_for(db, context)
    opted_out: set[str] = set()
    if person is not None:
        opted_out = await consent.opted_out_sources(
            db, tenant_id=context.tenant_id, person_id=person.id
        )

    return ConsentResponse(
        sources=[
            SourceConsent(
                source=source,
                label=SOURCE_COPY[source][0],
                reads=SOURCE_COPY[source][1],
                opted_out=source in opted_out,
            )
            for source in consent.SOURCES
        ],
        refusals=list(REFUSALS),
    )


async def _record_notification(db: AsyncSession, context: WorkspaceContext) -> None:
    """Stamp the first delivery of the notification, and only the first.

    Never overwritten. The question an auditor asks is *when were they told*,
    and refreshing the screen a year later must not answer it with today.

    A commit here, on a GET, which is unusual enough to justify: the write is
    the receipt for the read, and losing it because the response happened not to
    be followed by another write would leave a person shown the notification and
    recorded as never having seen it — the failure that matters, in the
    direction that matters.
    """
    if context.membership.notified_at is not None:
        return

    context.membership.notified_at = datetime.now(UTC)
    await db.commit()

    await logger.ainfo(
        "consent.notification_served",
        tenant_id=str(context.tenant_id),
        user_id=str(context.user.id),
    )


@router.put(
    "/{workspace_id}/me/sources",
    response_model=ConsentUpdateResponse,
    summary="Opt out of a source, or back in",
    responses={
        403: {"description": "CAIRN has not linked any activity to your account yet."},
        422: {"description": "Unknown source."},
    },
)
async def set_source_consent(
    body: ConsentUpdate,
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
) -> ConsentUpdateResponse:
    """Record the caller's choice about one source.

    **A `PUT` of the desired state rather than two verbs.** The interface is a
    toggle, and a toggle that has to choose between `POST` and `DELETE` based on
    what it believes the current state to be is a toggle that gets it wrong
    after a stale page — turning "opt me out" into "opt me back in" at the worst
    possible moment.

    Only ever the caller's own consent. There is no workspace-level version of
    this endpoint, and there should not be: an Owner opting somebody else back
    in would be the product overriding a privacy decision on the person's
    behalf.
    """
    if body.source not in consent.SOURCES:
        raise ProblemDetailError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            title="Unknown source",
            detail=f"CAIRN does not read a source called {body.source!r}.",
            problem_type="unknown-source",
        )

    person = await _person_for(db, context)
    if person is None:
        # Nothing is attributed to them yet, so there is nothing to opt out of —
        # but the honest answer is not "done", because their choice would not be
        # recorded and would not apply when their identity is linked later.
        raise ProblemDetailError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Not your record yet",
            detail=(
                "CAIRN has not linked any activity to your account yet, so there "
                "is nothing to opt out of. This becomes available as soon as it has."
            ),
            problem_type="not-your-record",
        )

    unlinked = 0
    if body.opted_out:
        unlinked = await consent.opt_out(
            db, tenant_id=context.tenant_id, person_id=person.id, source=body.source
        )
    else:
        await consent.opt_in(
            db, tenant_id=context.tenant_id, person_id=person.id, source=body.source
        )

    await db.commit()

    await logger.ainfo(
        "consent.updated",
        tenant_id=str(context.tenant_id),
        source=body.source,
        opted_out=body.opted_out,
        unlinked=unlinked,
    )

    return ConsentUpdateResponse(source=body.source, opted_out=body.opted_out, unlinked=unlinked)


def _fact_or_none(row: FactRow | None) -> FactResponse | None:
    if row is None:
        return None
    from cairn_api.api.routers.facts import _fact_response

    return _fact_response(row)
