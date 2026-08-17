"""Linking a provider account to a person, and refusing to guess.

Every rule in `db/external_identity_models.py` has a function here, and the
functions are deliberately narrow: there is no `link()` that takes a verification
method as an argument, because a single entry point is a single place for a
future caller to pass the wrong one. `link_by_verified_email` cannot be called
with an unverified address, and `confirm_own_account` cannot be called on behalf
of somebody else — the signatures make both impossible rather than checked.

**What is not in this module, and never will be:** any comparison of display
names, any similarity or distance function, any read of message content, any
model call. There is nothing to disable and no threshold to tune, because a
threshold implies that a high enough score would be good enough, and for "is this
the same human" it is not.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, final

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.external_identity_models import (
    ExternalIdentity,
    IdentityLinkState,
    IdentityVerification,
)
from cairn_api.db.identity_models import Person
from cairn_api.db.models import User

logger = structlog.get_logger(__name__)

#: The bounded reasons a link can end. Free prose would eventually carry a
#: provider's error text, and a provider's error text quotes the resource that
#: failed — which for these providers is a person's address or a space's name.
REASON_WITHDRAWN: Final = "The person withdrew this link."
REASON_DISPUTED: Final = "The person said this account is not theirs."

REVOCATION_REASONS: Final[frozenset[str]] = frozenset({REASON_WITHDRAWN, REASON_DISPUTED})


class IdentityConflictError(Exception):
    """Somebody else already holds this provider account in this workspace.

    Its own exception rather than a bare `IntegrityError` because the caller has
    to answer it differently: this is a 409 that will never succeed on retry, not
    a transient failure. The message deliberately does not name the other person
    — telling one member which colleague holds an account is a disclosure the
    person asking has no claim to.
    """


@final
@dataclass(frozen=True, slots=True)
class AttributionHealth:
    """How much of this workspace's activity has an owner, in counts only.

    **No per-person figures, by construction.** There is no field here that could
    carry a name, and no field that counts anybody's activity — md/05 §B.2 rules
    out contribution counts and rankings, and an "unresolved by person" breakdown
    is a leaderboard with the ranking left as an exercise for the reader.
    """

    #: Live links, by provider value.
    resolved_by_provider: dict[str, int]

    #: Links the person withdrew or disputed, by provider value.
    unresolved_by_provider: dict[str, int]

    disputed: int
    revoked: int


async def resolve_person(
    session: AsyncSession,
    *,
    provider: ConnectorProvider,
    provider_account_id: str,
) -> Person | None:
    """Who this provider account belongs to, or `None`.

    `None` is a complete answer and callers must render it as one. The activity
    stays attributed to the provider account, which is exactly what arrived, and
    to nobody — never to the nearest match, because "nearest" is the mechanism by
    which one person's work joins another person's record.

    Only `ACTIVE` links resolve. A revoked or disputed row is retained as
    evidence that the link existed, and reading it here would make revocation
    cosmetic.

    The session must be tenant-scoped: row-level security is what stops this
    resolving against another workspace's link, so there is deliberately no
    `tenant_id` argument for a caller to pass wrongly.
    """
    row = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == provider,
            ExternalIdentity.provider_account_id == provider_account_id,
            ExternalIdentity.state == IdentityLinkState.ACTIVE,
        )
    )
    if row is None:
        return None
    return await session.get(Person, row.person_id)


async def identities_for_person(
    session: AsyncSession, *, person_id: uuid.UUID
) -> Sequence[ExternalIdentity]:
    """Every link this person has ever had, live or ended, newest first.

    Ended links are included on purpose. A person looking at their own record is
    entitled to see that an account was once attributed to them and no longer is
    — hiding it would make the history less checkable at exactly the moment
    somebody is checking it.
    """
    rows = await session.scalars(
        select(ExternalIdentity)
        .where(ExternalIdentity.person_id == person_id)
        .order_by(ExternalIdentity.linked_at.desc())
    )
    return list(rows.all())


async def link_by_verified_email(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: ConnectorProvider,
    provider_account_id: str,
    provider_verified_email: str,
) -> ExternalIdentity | None:
    """Link automatically, and only on two verifications that agree.

    The argument is named `provider_verified_email` rather than `email` because
    the name is the contract: a caller holding an address the provider did *not*
    mark verified has nothing to pass here. An address a provider merely stores
    is whatever the account holder typed into a settings page, and matching it
    against CAIRN's records compares two unverified claims.

    The CAIRN side must be verified too — `email_verified_at IS NOT NULL` means
    somebody received mail at that address and proved it. Without that clause,
    anyone who could sign up with a colleague's address could inherit their
    provider account.

    Returns `None` rather than raising when there is no match. No match is the
    ordinary case, not a failure: most provider accounts belong to people who
    have not signed in, and most providers never supply a verified address at
    all.

    A conflict — somebody else already holds this account — is raised, because
    silently doing nothing would leave the caller believing the link was made.
    """
    address = provider_verified_email.strip().lower()
    if not address:
        return None

    user_id: uuid.UUID | None = await session.scalar(
        select(User.id).where(
            func.lower(User.email) == address,
            User.email_verified_at.is_not(None),
        )
    )
    if user_id is None:
        return None

    person_id: uuid.UUID | None = await session.scalar(
        select(Person.id).where(Person.user_id == user_id)
    )
    if person_id is None:
        return None

    return await _insert(
        session,
        tenant_id=tenant_id,
        person_id=person_id,
        provider=provider,
        provider_account_id=provider_account_id,
        provider_email=address,
        verification=IdentityVerification.VERIFIED_EMAIL_MATCH,
        actor_user_id=None,
    )


async def confirm_own_account(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    person: Person,
    actor_user_id: uuid.UUID,
    provider: ConnectorProvider,
    provider_account_id: str,
) -> ExternalIdentity:
    """The person says an account is theirs, from an authenticated session.

    `person` and `actor_user_id` are both required and must refer to the same
    human — the caller proves that by resolving the person *from* the session,
    which is why this function takes a `Person` rather than a `person_id` it
    would have to trust. There is no administrative variant of this function, and
    that is the point: md/05 makes the record the person's own, so an Owner
    claiming a member's account would be an override of the one thing the product
    promises cannot be overridden.

    Raises `IdentityConflictError` when somebody else holds the account. The refusal
    names nobody: which colleague holds an account is not the asker's to know.
    """
    if person.user_id != actor_user_id:
        # Defence in depth. The route resolves the person from the session, so
        # reaching here means a caller passed a mismatched pair, and the right
        # answer to that is a refusal rather than a link.
        raise IdentityConflictError("A person may only confirm their own accounts.")

    return await _insert(
        session,
        tenant_id=tenant_id,
        person_id=person.id,
        provider=provider,
        provider_account_id=provider_account_id,
        provider_email=None,
        verification=IdentityVerification.SELF_CONFIRMED,
        actor_user_id=actor_user_id,
    )


async def end_link(
    session: AsyncSession,
    *,
    identity: ExternalIdentity,
    actor_user_id: uuid.UUID,
    disputed: bool = False,
) -> ExternalIdentity:
    """Stop attributing this account, and keep every trace that it happened.

    Updates `state`; deletes nothing. The row, its verification method, when it
    was linked and why it ended all survive, and so does every fact the link ever
    produced — the facts carry the provider actor id recorded at ingestion, which
    was never derived from this table and is not rewritten now.

    `disputed` separates "this was mine and I am unlinking it" from "this was
    never mine". Both stop attribution immediately; only the second says the
    original link was wrong, and a person deserves to have that distinction
    recorded in their own words rather than flattened into one.

    Already-ended links are returned unchanged rather than raising. Revoking
    twice is a double-click, not an error, and re-stamping the timestamp would
    move the moment attribution actually stopped.
    """
    if identity.state is not IdentityLinkState.ACTIVE:
        return identity

    identity.state = IdentityLinkState.DISPUTED if disputed else IdentityLinkState.REVOKED
    identity.revoked_at = datetime.now(UTC)
    identity.revoked_reason = REASON_DISPUTED if disputed else REASON_WITHDRAWN
    identity.revoked_by_user_id = actor_user_id
    await session.flush()

    await logger.ainfo(
        "identity.external_link_ended",
        provider=identity.provider.value,
        state=identity.state.value,
        # No account id, no address, no person: a category and a provider are
        # everything an operator needs and everything telemetry may carry.
        disputed=disputed,
    )
    return identity


async def attribution_health(session: AsyncSession) -> AttributionHealth:
    """Counts for the workspace's administrators, and nothing per person.

    Answers "is attribution working here", which an Owner needs in order to ask
    members to confirm their own accounts. It cannot answer "who is most active",
    "who has not linked anything" or "how much did each person do", because it
    counts links rather than activity and never groups by person.
    """
    rows = (
        await session.execute(
            select(
                ExternalIdentity.provider,
                ExternalIdentity.state,
                func.count(),
            ).group_by(ExternalIdentity.provider, ExternalIdentity.state)
        )
    ).all()

    resolved: dict[str, int] = {}
    unresolved: dict[str, int] = {}
    disputed = 0
    revoked = 0
    for provider, state, count in rows:
        key = provider.value if isinstance(provider, ConnectorProvider) else str(provider)
        if state is IdentityLinkState.ACTIVE:
            resolved[key] = resolved.get(key, 0) + count
            continue
        unresolved[key] = unresolved.get(key, 0) + count
        if state is IdentityLinkState.DISPUTED:
            disputed += count
        else:
            revoked += count

    return AttributionHealth(
        resolved_by_provider=resolved,
        unresolved_by_provider=unresolved,
        disputed=disputed,
        revoked=revoked,
    )


async def _insert(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    person_id: uuid.UUID,
    provider: ConnectorProvider,
    provider_account_id: str,
    provider_email: str | None,
    verification: IdentityVerification,
    actor_user_id: uuid.UUID | None,
) -> ExternalIdentity:
    """Write the link, letting the database decide the race.

    The existence check and the insert are not separated by an `if`: two confirms
    arriving together would both pass a check-then-act and the second would break
    the unique index anyway. Attempting the insert and translating the violation
    is the version that is correct under concurrency, which is the only condition
    where this matters.
    """
    existing = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == provider,
            ExternalIdentity.provider_account_id == provider_account_id,
            ExternalIdentity.state == IdentityLinkState.ACTIVE,
        )
    )
    if existing is not None:
        if existing.person_id == person_id:
            # Already theirs. Idempotent rather than an error: confirming twice
            # is a double-click, and a second row would be a second claim.
            return existing
        raise IdentityConflictError("That account is already linked to somebody in this workspace.")

    row = ExternalIdentity(
        tenant_id=tenant_id,
        person_id=person_id,
        provider=provider,
        provider_account_id=provider_account_id,
        provider_email=provider_email,
        verification=verification,
        state=IdentityLinkState.ACTIVE,
        linked_at=datetime.now(UTC),
        linked_by_user_id=actor_user_id,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as error:
        # The index caught a race the read above could not see. Same answer as
        # the checked case, so a caller cannot tell the two apart and cannot come
        # to depend on which one fired.
        await session.rollback()
        raise IdentityConflictError(
            "That account is already linked to somebody in this workspace."
        ) from error

    await logger.ainfo(
        "identity.external_link_created",
        provider=provider.value,
        verification=verification.value,
        # Never the account id and never the address: both identify a person to
        # anybody who can read the log store, which is outside the erasure path.
        self_confirmed=verification is IdentityVerification.SELF_CONFIRMED,
    )
    return row
