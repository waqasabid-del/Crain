"""Cross-source identity, from the reader's own side.

Four endpoints, and the shape of the set is the design. Three of them are
`/me/` routes that take no subject at all, and the fourth returns counts. There
is deliberately no route anywhere in this router that reads or writes another
member's links — not gated behind a permission, not available to an Owner,
absent. md/05 §B.2.3 makes a person's record their own, and a record an
administrator can rewrite is not owned by the person it describes.

**What links a person, stated as a closed list.** A provider supplies an
address it has itself verified and it equals the verified address of a signed-in
CAIRN account; or the person signs in and says the account is theirs. Nothing
else — not a matching display name, not a similar handle, not a shared channel,
not a model's opinion. `identity/external.py` has no function that would accept
any of those, so this router has nothing to call for them.

**Unresolved is a first-class answer.** Activity from an account nobody has
claimed stays attributed to the account and to nobody. The alternative — attach
it to the closest match — is how one person's work silently joins another
person's record, and a blank is honest where a plausible wrong name is not.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import CurrentMembership, TenantDb, WorkspaceContext, requires
from cairn_api.api.errors import ProblemDetailError
from cairn_api.api.schemas import (
    AttributionHealthResponse,
    ConfirmIdentityRequest,
    ExternalIdentityResponse,
    IdentityProposalResponse,
    MyIdentitiesResponse,
    RevokeIdentityRequest,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.external_identity_models import (
    ExternalIdentity,
    IdentityLinkState,
    IdentityVerification,
)
from cairn_api.db.identity_models import Identity, IdentityStatus, Person
from cairn_api.identity import external
from cairn_api.pipeline import store

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["identities"])

#: The two ways in, in the words a reader gets on the screen where it matters.
#:
#: Held here rather than in the interface so the web app, a future mobile client
#: and any support answer state the same rule. A second copy is a second chance
#: for one of them to describe a looser rule than the code enforces.
LINK_NOTICE = (
    "CAIRN links an account to you in exactly two ways: a source tells us an "
    "address it has verified and it matches your verified CAIRN address, or you "
    "sign in and confirm the account is yours. A matching name, a similar "
    "handle or a shared channel never links anyone. Activity from an account "
    "nobody has confirmed stays attributed to that account and to no person."
)

#: What the administrator's view cannot answer, stated in the response.
#:
#: In the payload rather than in the interface because a limit that lives in one
#: client is a limit the next client does not know about — and the reader most
#: entitled to know this screen holds no per-person data is the member who is
#: not looking at it.
HEALTH_NOTICE = (
    "Counts only. CAIRN cannot show you which people are unresolved, how much "
    "any person did, or any per-person breakdown. Attribution health is a "
    "question about connections, not about colleagues."
)


@router.get(
    "/{workspace_id}/me/identities",
    response_model=MyIdentitiesResponse,
    summary="Which source accounts CAIRN believes are yours",
    responses={404: {"description": "No such workspace, or you are not a member."}},
)
async def my_identities(context: CurrentMembership, db: TenantDb) -> MyIdentitiesResponse:
    """The caller's own links, the caller's own proposals, and the rule.

    **`proposals` is not a menu of unclaimed accounts, and must never become
    one.** It returns only the `PROPOSED` rows of the existing `identities`
    table that are *already attached to the caller's own `Person`* — identifiers
    CAIRN inferred were theirs and is showing them so they can correct it.

    Listing the workspace's *unresolved* provider accounts here is the thing
    this whole step exists to prevent. Handing every member a list of
    colleagues' unclaimed accounts next to a "that's me" button is the
    claim-a-colleague attack served as a feature: the second person to look at
    the list takes whatever the first has not claimed, the link is recorded as
    `SELF_CONFIRMED`, and from then on somebody else's work is in their record
    with CAIRN's own evidence field vouching for it. The exclusive index would
    not stop it — it only decides who gets there first. So the query is scoped
    to `Person.user_id == caller` and there is no parameter, no filter and no
    flag that widens it.

    **Ended links are shown.** A person is entitled to see that an account was
    once attributed to them and no longer is — hiding it makes the record less
    checkable at exactly the moment somebody is checking it.
    """
    person = await _person_for(db, context)
    if person is None:
        # An account with no attributed activity yet. Empty is the truthful
        # answer, and the notice still tells them the rule — which is the part
        # they are most likely to have come here to read.
        return MyIdentitiesResponse(identities=[], proposals=[], notice=LINK_NOTICE)

    links = await external.identities_for_person(db, person_id=person.id)

    proposals = list(
        await db.scalars(
            select(Identity)
            .where(
                Identity.person_id == person.id,
                Identity.status == IdentityStatus.PROPOSED,
            )
            .order_by(Identity.value)
        )
    )

    return MyIdentitiesResponse(
        identities=[_response(row) for row in links],
        proposals=[IdentityProposalResponse(kind=row.kind, value=row.value) for row in proposals],
        notice=LINK_NOTICE,
    )


@router.post(
    "/{workspace_id}/me/identities",
    response_model=ExternalIdentityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm a source account is yours",
    responses={
        403: {"description": "CAIRN has not linked any activity to your account yet."},
        404: {"description": "No such workspace, or you are not a member."},
        409: {"description": "That account is already linked to somebody in this workspace."},
    },
)
async def confirm_identity(
    body: ConfirmIdentityRequest,
    context: CurrentMembership,
    db: TenantDb,
) -> ExternalIdentityResponse:
    """Record that the caller owns a provider account.

    **Self only, by construction rather than by a check.** The `Person` written
    is the one the caller's own session resolved to; the request body has no
    subject field, and there is no second route that takes one. That absence is
    the design — an Owner who could confirm a colleague's account would be
    writing evidence, in CAIRN's own words, that a member's work belongs to
    whoever the Owner chose.

    **No permission is declared**, and requiring one would be the wrong axis.
    Every role including Viewer may answer a question about themselves, and
    making that a grant would mean a person's own account was something the
    workspace let them have.

    Idempotent when the account is already theirs: confirming twice is a
    double-click, not a second claim.

    Refused with 409 when somebody else holds the account, and the refusal names
    nobody. Which colleague holds an account is not the asker's to know — saying
    so would turn this endpoint into an oracle for mapping accounts to people.
    """
    person = await _person_for(db, context)
    if person is None:
        # Nothing is attributed to them yet, so there is no record to attach the
        # account to. "Done" would be a lie — the confirmation would be
        # discarded and the next commit would still resolve to nobody.
        raise ProblemDetailError(
            status_code=status.HTTP_403_FORBIDDEN,
            title="Not your record yet",
            detail=(
                "CAIRN has not linked any activity to your account yet, so there "
                "is nothing to confirm against. This becomes available as soon as "
                "it has."
            ),
            problem_type="not-your-record",
        )

    try:
        row = await external.confirm_own_account(
            db,
            tenant_id=context.tenant_id,
            person=person,
            actor_user_id=context.user.id,
            provider=body.provider,
            provider_account_id=body.provider_account_id,
        )
    except external.IdentityConflictError as error:
        raise _conflict() from error

    # Everything this account produced before the confirmation is sitting
    # unresolved. Reconciling in the same transaction means the link and the
    # attribution it justifies land together — a commit between them would leave
    # a window in which the person owns the account and none of its work, and a
    # failure after it would leave that window open permanently.
    reconciled = await store.reconcile_actor(
        db,
        tenant_id=context.tenant_id,
        person_id=person.id,
        provider=body.provider,
        provider_account_id=body.provider_account_id,
    )
    await db.commit()

    await logger.ainfo(
        "identity.confirmed",
        provider=body.provider.value,
        # A count and a provider. Never the account id, never the person.
        reconciled=reconciled,
    )

    await logger.ainfo(
        "identity.self_confirmed",
        tenant_id=str(context.tenant_id),
        # The provider, and nothing that identifies the account or the person.
        # Telemetry leaves the erasure path, so an account id here is a personal
        # identifier in a store nobody can clear.
        provider=body.provider.value,
    )
    return _response(row)


@router.post(
    "/{workspace_id}/me/identities/{identity_id}/revoke",
    response_model=ExternalIdentityResponse,
    summary="Stop attributing one of your source accounts to you",
    responses={
        404: {"description": "No such link of yours in this workspace."},
    },
)
async def revoke_identity(
    identity_id: uuid.UUID,
    body: RevokeIdentityRequest,
    context: CurrentMembership,
    db: TenantDb,
) -> ExternalIdentityResponse:
    """End a link, keeping the row and its evidence.

    **Only the caller's own links.** The lookup is filtered by the caller's
    `Person`, so another member's link is a 404 rather than a permission error —
    from outside, a link that is not yours is indistinguishable from one that
    does not exist, which is also what row-level security gives us across
    workspaces.

    Nothing is deleted. The row, its verification method, when it was linked and
    why it ended all survive, and so does every fact the link ever produced —
    facts carry the provider actor id recorded at ingestion, which was never
    derived from this table and is not rewritten now.

    Idempotent: an already-ended link is returned unchanged rather than
    erroring. Re-stamping the timestamp would move the moment attribution
    actually stopped, which is the one thing the row exists to record.
    """
    person = await _person_for(db, context)
    row = await _own_identity_or_404(db, person, identity_id)

    await external.end_link(db, identity=row, actor_user_id=context.user.id, disputed=body.disputed)

    # Ending the link and un-attributing its work are one action, in one
    # transaction. Doing only the first leaves "I unlinked that account" and
    # "that work is still filed under my name" both true on the same screen, and
    # the person can see the second. Nothing is deleted — the fact, its sources
    # and the account that produced it all remain; only CAIRN's claim about
    # whose it is goes away.
    detached = await store.detach_actor(
        db,
        tenant_id=context.tenant_id,
        person_id=row.person_id,
        provider=row.provider,
        provider_account_id=row.provider_account_id,
    )
    await db.commit()

    await logger.ainfo(
        "identity.link_ended",
        provider=row.provider.value,
        disputed=body.disputed,
        detached=detached,
    )

    return _response(row)


@router.get(
    "/{workspace_id}/attribution-health",
    response_model=AttributionHealthResponse,
    summary="Whether attribution is working in this workspace",
    responses={
        403: {"description": "Requires permission to manage workspace settings."},
        404: {"description": "No such workspace, or you are not a member."},
    },
)
async def workspace_attribution_health(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.WORKSPACE_SETTINGS))],
    db: TenantDb,
) -> AttributionHealthResponse:
    """Counts, so an Owner can tell whether to ask members to confirm accounts.

    **Owner and Admin, and counts only.** The gate is `WORKSPACE_SETTINGS`
    rather than a new permission because this is a fact about the workspace's
    configuration — how many source accounts have an owner — and inventing an
    `identities.view` permission would make *how much is visible about people* a
    function of role, which md/05 §B.3.3 and `permissions.py` both refuse.

    The gate is therefore doing much less work than it looks like it is. What
    actually protects members is the return type: `attribution_health` groups by
    provider and state and never by person, so there is no name, no id, no
    address and no activity volume to withhold. An Admin reading this learns
    exactly one thing a member could not — a count — and md/15 §2.3's rule that
    an Admin may not see more *about a member* than the member sees is intact
    because nothing here is about a member at all.
    """
    health = await external.attribution_health(db)
    return AttributionHealthResponse(
        resolved_by_provider=health.resolved_by_provider,
        unresolved_by_provider=health.unresolved_by_provider,
        disputed=health.disputed,
        revoked=health.revoked,
        notice=HEALTH_NOTICE,
    )


async def _person_for(db: AsyncSession, context: WorkspaceContext) -> Person | None:
    """The `Person` for the caller's session, and no other.

    A user and a person are different things (md/01 §5.3): somebody can appear
    in commit history for months before they ever sign in. `None` is therefore a
    legitimate answer, not a fault — and it is the *only* way a caller's person
    is ever chosen, which is what makes every route in this module self-only.
    """
    person: Person | None = await db.scalar(select(Person).where(Person.user_id == context.user.id))
    return person


async def _own_identity_or_404(
    db: AsyncSession, person: Person | None, identity_id: uuid.UUID
) -> ExternalIdentity:
    """One link, if it is the caller's.

    The `person_id` predicate is stated even though row-level security already
    scopes the query to the workspace: RLS separates customers, and this
    separates colleagues. A 404 that depended on RLS alone would become a 200
    the day somebody ran this query on a platform connection.
    """
    row: ExternalIdentity | None = None
    if person is not None:
        row = await db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.id == identity_id,
                ExternalIdentity.person_id == person.id,
            )
        )
    if row is None:
        raise ProblemDetailError(
            status_code=status.HTTP_404_NOT_FOUND,
            title="No such link",
            detail="You have no linked account with that identifier.",
            problem_type="identity-not-found",
        )
    return row


def _conflict() -> ProblemDetailError:
    """The 409, naming nobody.

    A stable `type` so a client can branch on it without parsing prose, and a
    detail that says an account is taken without saying by whom. Naming the
    holder would let anyone map provider accounts to colleagues one refused
    request at a time.
    """
    return ProblemDetailError(
        status_code=status.HTTP_409_CONFLICT,
        title="That account is already linked",
        detail=(
            "Somebody in this workspace has already confirmed that account. If "
            "you believe it is yours, ask them to unlink it first."
        ),
        problem_type="identity-already-linked",
    )


def _response(row: ExternalIdentity) -> ExternalIdentityResponse:
    return ExternalIdentityResponse(
        id=row.id,
        provider=row.provider,
        provider_account_id=row.provider_account_id,
        verification=row.verification,
        state=row.state,
        linked_at=row.linked_at,
        revoked_at=row.revoked_at,
        revoked_reason=row.revoked_reason,
        explanation=_explain(row),
    )


def _explain(row: ExternalIdentity) -> str:
    """How CAIRN knows, in a sentence, with no number in it.

    Composed from the stored `verification` rather than reconstructed from
    timestamps, so the answer to "how do you know?" is the thing that was
    actually recorded at the time and not a later guess about a guess.

    **Never a percentage and never a score.** md/05 §A.2.1 makes certainty
    categorical: there are two ways a link exists and both are stateable in
    words. A number here would imply a threshold, a threshold implies that a
    high enough score is good enough, and for "is this the same human" it is
    not.
    """
    when = row.linked_at.date().isoformat()

    if row.verification is IdentityVerification.SELF_CONFIRMED:
        how = (
            f"You confirmed on {when}, while signed in to CAIRN, that this "
            "account is yours. Your signed-in session is the evidence."
        )
    else:
        how = (
            f"On {when}, this source supplied an email address that it had "
            "itself verified, and that address matched the address you verified "
            "on your CAIRN account. Both verifications were required."
        )

    if row.state is IdentityLinkState.ACTIVE:
        return how

    ended = (
        "You said this account is not yours, so CAIRN stopped attributing it."
        if row.state is IdentityLinkState.DISPUTED
        else "You unlinked this account, so CAIRN stopped attributing it."
    )
    # The evidence sentence is kept rather than replaced. What CAIRN once
    # believed and why is part of the record a person is entitled to check,
    # and an ended link that no longer says how it began cannot be audited.
    return f"{how} {ended} The record of the link is kept."
