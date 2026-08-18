"""Resolving contributor identities to people.

Given a `Contributor` — an address, maybe a login, maybe a name — find or create
the `Person` it belongs to.

**The matching rules, in order, and why they stop where they do:**

1. **Exact identity match.** The address or login is already claimed. This is
   the overwhelming majority of resolutions after the first week.
2. **Cross-identifier match.** A commit carries both an address and a login, and
   one of them is already known. That links the other to the same person — which
   is how a personal weekend address gets attached to the same human as a work
   address, without anyone doing anything.
3. **Nothing else.** No name matching, no fuzzy addresses, no "same domain and
   similar handle".

Rule 3 is the important one. Names are the worst available identity key: two
people share one, one person uses three, transliteration varies, and display
names are freely editable. Matching on a name is precisely how one colleague's
work is attributed to another — and the person who notices is the one whose work
was taken.

**Every automatic link is PROPOSED, never CONFIRMED.** The system proposes, the
person confirms (md/01 §5.3). A proposed identity is used for attribution — the
product would be useless otherwise — but it is visibly provisional and the person
can correct it. A confirmed one was affirmed by a human, and automatic inference
never upgrades it.

**A rejection is permanent.** Someone who says "that address is not mine" must
not be asked again by the next commit carrying it. A rejected identity is
retained and never re-proposed, and never silently re-attached to anyone else
either — re-proposing it to a different person would be the same mistake with a
new victim.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.identity_models import (
    Identity,
    IdentityKind,
    IdentityStatus,
    Person,
    PersonKind,
)
from cairn_api.db.models import User
from cairn_api.github.bots import is_ai_agent, is_bot
from cairn_api.github.trailers import Contributor

logger = structlog.get_logger(__name__)


def _claims(contributor: Contributor) -> list[tuple[IdentityKind, str]]:
    """The identifiers this contributor asserts, most specific first.

    A GitHub login before an address: it is issued by GitHub, unique, and stable
    across the several addresses one account may commit under. An address can be
    shared (a team alias) or reused after someone leaves.
    """
    claims: list[tuple[IdentityKind, str]] = []
    if contributor.login:
        claims.append((IdentityKind.GITHUB_LOGIN, contributor.login.strip().lower()))
    claims.append((IdentityKind.EMAIL, contributor.email.strip().lower()))
    return claims


async def _find_identity(session: AsyncSession, kind: IdentityKind, value: str) -> Identity | None:
    found: Identity | None = await session.scalar(
        select(Identity).where(Identity.kind == kind, Identity.value == value)
    )
    return found


def _kind_for(contributor: Contributor, *, custom_bots: list[str]) -> PersonKind:
    if is_ai_agent(contributor):
        return PersonKind.AGENT
    if is_bot(contributor, custom=custom_bots):
        return PersonKind.BOT
    return PersonKind.HUMAN


async def resolve(
    session: AsyncSession,
    contributor: Contributor,
    *,
    tenant_id: uuid.UUID,
    custom_bots: list[str] | None = None,
) -> Person:
    """Find or create the person this contributor is.

    Both a lookup and a learning step: a contributor arriving with a known login
    and an unknown address teaches the graph that the address belongs to the
    same person. That is the mechanism by which fragmented records converge
    without anyone being asked to do anything.

    The session must already be tenant-scoped. Row-level security means a lookup
    cannot reach another workspace's people, so `tenant_id` here is for the rows
    this function *writes* — the policy's `WITH CHECK` would reject a mismatched
    one, but failing at the database is a worse error message than not making
    the mistake.
    """
    bots = custom_bots or []
    claims = _claims(contributor)

    matched: Person | None = None
    for kind, value in claims:
        existing = await _find_identity(session, kind, value)
        if existing is None:
            continue
        if existing.status is IdentityStatus.REJECTED:
            # Somebody said this identifier is not theirs. Not evidence about
            # anyone else either — re-attaching it to a different person would
            # be the same mistake with a new victim.
            continue
        matched = await session.get(Person, existing.person_id)
        if matched is not None:
            break

    if matched is None:
        matched = Person(
            tenant_id=tenant_id,
            display_name=contributor.name,
            kind=_kind_for(contributor, custom_bots=bots),
        )
        session.add(matched)
        await session.flush()
        await logger.ainfo(
            "identity.person_created",
            person_id=str(matched.id),
            kind=matched.kind.value,
            # Identifiers are not logged: an address in the log store escapes
            # the erasure path the product promises.
            has_login=contributor.login is not None,
        )
    elif matched.display_name is None and contributor.name:
        # Fill a blank name, never overwrite one. A later commit with a
        # different spelling should not rename someone who has already been
        # identified, and a person who corrected their own name should not have
        # it reverted by the next push.
        matched.display_name = contributor.name

    await _attach_claims(session, matched, claims, tenant_id=tenant_id)
    await _link_account(session, matched, claims)
    return matched


async def _link_account(
    session: AsyncSession,
    person: Person,
    claims: list[tuple[IdentityKind, str]],
) -> None:
    """Connect this person to the account that signs in as them, if there is one.

    Without this link the employee-owned record has no owner. `me/week` and the
    correction endpoints both resolve the caller with
    `Person.user_id == current user`, so a person nobody linked can never read
    their own record and can never correct it — md/05 §B.2.3's central promise
    with no reachable path. Nothing else in the application ever set this column,
    which is why the layer existed and production never called it.

    **Matched on a verified address only.** A commit's author email is whatever
    the author's git config says, so linking on an unverified address would let
    anyone who can push a commit claim a colleague's record — including the
    right to rewrite it. Requiring `email_verified_at` means the address has been
    proved by somebody who received mail at it.

    Row-level security does the rest: the session is tenant-scoped, and the
    `users` policy only reveals accounts sharing a workspace with the current
    context, so a matching address in another company's workspace is invisible
    here rather than merely unmatched.

    Never overwrites, in both directions. Re-pointing an existing link would
    move ownership of a record between people, which is a merge decision, not an
    inference — and so would attaching an account that another person row in
    this workspace already holds. `uq_people_tenant_user` enforces the second
    case, and enforcing it here as well is not belt-and-braces: the index raises
    inside the delivery job, which then retries, fails identically, and
    dead-letters, so one person appearing in a commit stops that workspace
    ingesting anything at all.
    """
    if person.user_id is not None:
        return

    addresses = [value for kind, value in claims if kind is IdentityKind.EMAIL]
    if not addresses:
        return

    user_id: uuid.UUID | None = await session.scalar(
        select(User.id).where(
            func.lower(User.email).in_([address.lower() for address in addresses]),
            User.email_verified_at.is_not(None),
        )
    )
    if user_id is None:
        return

    # The account may already belong to another person row here — a workspace
    # whose accounts were linked before any commit arrived has exactly this
    # shape, since nothing writes an identity row for the address in that path.
    holder: uuid.UUID | None = await session.scalar(
        select(Person.id).where(
            Person.tenant_id == person.tenant_id,
            Person.user_id == user_id,
            Person.id != person.id,
        )
    )
    if holder is not None:
        await logger.ainfo(
            "identity.account_already_held",
            person_id=str(person.id),
            holder_person_id=str(holder),
            detail=(
                "A verified address matched an account another person record in "
                "this workspace already holds. Declined rather than merged: "
                "moving an account between person records is a merge decision."
            ),
        )
        return

    person.user_id = user_id
    await session.flush()
    await logger.ainfo(
        "identity.person_linked_to_account",
        person_id=str(person.id),
        # The address itself is deliberately absent: an address in the log store
        # escapes the erasure path the product promises.
        user_id=str(user_id),
    )


async def _attach_claims(
    session: AsyncSession,
    person: Person,
    claims: list[tuple[IdentityKind, str]],
    *,
    tenant_id: uuid.UUID,
) -> None:
    """Record any identifier not already linked.

    This is where rule 2 does its work: a contributor with a known login and a
    new address attaches the address to the same person, so the next commit from
    that address resolves by rule 1.
    """
    for kind, value in claims:
        existing = await _find_identity(session, kind, value)
        if existing is not None:
            if existing.person_id != person.id and existing.status is not IdentityStatus.REJECTED:
                # Two people hold the same identifier. Reachable only through a
                # manual merge or a data repair gone wrong, and it means one
                # person's work is being split or another's absorbed.
                await logger.awarning(
                    "identity.conflicting_claim",
                    kind=kind.value,
                    existing_person_id=str(existing.person_id),
                    resolved_person_id=str(person.id),
                )
            continue

        session.add(
            Identity(
                tenant_id=tenant_id,
                person_id=person.id,
                kind=kind,
                value=value,
                # Proposed, never confirmed. Automatic inference does not get to
                # assert a fact about whose work this is.
                status=IdentityStatus.PROPOSED,
            )
        )

    await session.flush()


async def confirm(session: AsyncSession, identity: Identity, *, confirmed_by: uuid.UUID) -> None:
    """Record that a person affirmed an identity as theirs."""
    identity.status = IdentityStatus.CONFIRMED
    identity.confirmed_at = datetime.now(UTC)
    identity.confirmed_by_user_id = confirmed_by


async def reject(session: AsyncSession, identity: Identity, *, rejected_by: uuid.UUID) -> None:
    """Record that an identity is not this person's.

    The row is kept, not deleted. A deleted rejection is re-proposed by the next
    commit carrying the same address, so the person corrects the same mistake
    forever and eventually stops correcting it.
    """
    identity.status = IdentityStatus.REJECTED
    identity.confirmed_at = datetime.now(UTC)
    identity.confirmed_by_user_id = rejected_by


async def merge(session: AsyncSession, *, keep: Person, absorb: Person) -> Person:
    """Merge two person records into one.

    The correction someone makes when the graph has split them in two — the
    common case being a personal address that never shared a commit with their
    work identity, so no automatic rule could ever link them.

    Deliberately manual. An automatic version would need to match on names,
    which is the one rule this module refuses.
    """
    if keep.id == absorb.id:
        return keep

    # Both collections loaded explicitly before either is touched. Accessing a
    # relationship that has not been loaded triggers a lazy load, which under
    # asyncio raises MissingGreenlet rather than silently doing IO.
    await session.refresh(absorb, attribute_names=["identities"])
    await session.refresh(keep, attribute_names=["identities"])

    identities = list(absorb.identities)
    # Moved through the relationship, not by assigning `person_id`.
    #
    # `Person.identities` cascades delete-orphan. Setting the foreign key column
    # leaves the ORM believing the rows still belong to `absorb`, so deleting
    # `absorb` cascaded to them — the merge silently destroyed the identities it
    # existed to preserve, and the person came out with fewer than they started.
    for identity in identities:
        absorb.identities.remove(identity)
        keep.identities.append(identity)

    if keep.display_name is None:
        keep.display_name = absorb.display_name
    if keep.user_id is None:
        keep.user_id = absorb.user_id

    await session.delete(absorb)
    await session.flush()

    await logger.ainfo(
        "identity.people_merged",
        kept_person_id=str(keep.id),
        absorbed_person_id=str(absorb.id),
        identities_moved=len(identities),
    )
    return keep
