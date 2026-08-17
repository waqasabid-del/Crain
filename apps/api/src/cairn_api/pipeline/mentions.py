"""Resolving names a model extracted to people the workspace knows.

An identifier (email, handle) is a lookup; a name is not — colleagues share
names, and matching on one risks crediting one person's work to another. A
name matching exactly one person resolves as a proposal a person can correct,
never a confirmed identity (md/01 §5.3). A name matching two or more resolves
to neither: no tiebreak is better than a coin flip.

**A provider actor id is not a name and must never be resolved as one.** Slack
and Google Chat state on the event itself who sent the message — `U…` and
`users/…` respectively — and that string is evidence of an account, not of a
human. It is carried through the pipeline as a `fact_people.mention` in the
`provider:{provider}:{account_id}` form minted below, and it resolves to a
person *only* through `identity/external.resolve_person`, which reads an active
link somebody actually made. Everything in this module that matches on a
display name refuses to touch such a mention, and `_resolve_one` says so out
loud rather than relying on the caller to have partitioned correctly: a Slack id
that fell through to name matching would be attribution by string similarity
wearing an identifier's clothes.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Final, final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.identity_models import Identity, IdentityKind, Person

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HANDLE = re.compile(r"^@?[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")

#: Marks a mention as a provider account id rather than a name a model wrote.
#:
#: A prefix rather than a separate column because `fact_people` already holds
#: exactly one string per mention and adding a column is a migration; a prefix
#: rather than a bare id because `U12345` is indistinguishable from a nickname,
#: and the whole point is that the two are never confused. `provider:` cannot
#: be produced by the extractor's people list without a colon-bearing "name",
#: and even then `read_provider_actor` rejects an unknown provider value.
PROVIDER_ACTOR_PREFIX: Final = "provider:"

#: `fact_people.mention` is `String(255)`; a longer token could not be stored.
#: An account id that does not fit here could not be linked either —
#: `external_identities.provider_account_id` is the same width — so refusing to
#: mint the mention loses nothing that could ever have resolved.
MAX_MENTION_LENGTH: Final = 255


@final
@dataclass(frozen=True, slots=True)
class ProviderActor:
    """The account a provider said produced an event, verbatim.

    Recorded provenance: this is what arrived on the wire. It is never derived
    from CAIRN's own tables, never rewritten when a link is made or ended, and
    never replaced by a person's name — so "who did the provider say this was?"
    stays answerable after every later correction.
    """

    provider: ConnectorProvider

    #: The provider's own opaque id. Never a handle, display name or address.
    account_id: str

    @property
    def mention(self) -> str:
        """The `fact_people.mention` form of this actor."""
        return f"{PROVIDER_ACTOR_PREFIX}{self.provider.value}:{self.account_id}"


def provider_actor_mention(provider: ConnectorProvider, account_id: str | None) -> str | None:
    """The mention for one provider account, or `None` if there is nothing to
    record. Absent and unstorable both yield `None`: neither is an error, and a
    delivery with no actor is a fact whose author the provider did not state."""
    cleaned = (account_id or "").strip()
    if not cleaned:
        return None
    mention = ProviderActor(provider=provider, account_id=cleaned).mention
    return mention if len(mention) <= MAX_MENTION_LENGTH else None


def is_provider_actor(mention: str) -> bool:
    """Whether this mention is a provider account id rather than a name."""
    return mention.startswith(PROVIDER_ACTOR_PREFIX)


def read_provider_actor(mention: str) -> ProviderActor | None:
    """Parse a stored mention back into the account it records.

    `None` for anything this module did not mint — including a mention that
    merely starts with the prefix but names a provider that does not exist. The
    strictness matters because the return value decides which table is consulted
    for a person, and a permissive parse would send an arbitrary string to the
    identity lookup.
    """
    if not is_provider_actor(mention):
        return None
    provider_value, separator, account_id = mention[len(PROVIDER_ACTOR_PREFIX) :].partition(":")
    if not separator or not account_id:
        return None
    try:
        provider = ConnectorProvider(provider_value)
    except ValueError:
        return None
    return ProviderActor(provider=provider, account_id=account_id)


@dataclass(frozen=True, slots=True)
class Mention:
    raw: str

    #: The person it resolved to, if exactly one match existed.
    person_id: uuid.UUID | None = None

    #: Why it did not resolve; kept so "who is Sam?" stays answerable.
    unresolved_reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.person_id is not None


@dataclass
class MentionResolution:
    mentions: list[Mention] = field(default_factory=list)

    @property
    def person_ids(self) -> list[uuid.UUID]:
        return [m.person_id for m in self.mentions if m.person_id is not None]

    @property
    def unresolved(self) -> list[Mention]:
        return [m for m in self.mentions if not m.resolved]


async def resolve_mentions(
    session: AsyncSession, *, tenant_id: uuid.UUID, names: list[str]
) -> MentionResolution:
    """Map extracted names to people, resolving only what is unambiguous."""
    result = MentionResolution()
    for raw in names:
        cleaned = raw.strip()
        if not cleaned:
            continue
        result.mentions.append(await _resolve_one(session, tenant_id, cleaned))
    return result


async def _resolve_one(session: AsyncSession, tenant_id: uuid.UUID, raw: str) -> Mention:
    kind = _identifier_kind(raw)
    if kind is not None:
        value = raw.lstrip("@").lower()
        identity = await session.scalar(
            select(Identity).where(
                Identity.tenant_id == tenant_id,
                Identity.kind == kind,
                func.lower(Identity.value) == value,
            )
        )
        if identity is not None:
            return Mention(raw=raw, person_id=identity.person_id)
        # Not retried as a name: "ali@acme.test" isn't a display name.
        return Mention(raw=raw, unresolved_reason="identifier not in the identity graph")

    matches = list(
        await session.scalars(
            select(Person).where(
                Person.tenant_id == tenant_id,
                func.lower(Person.display_name) == raw.lower(),
            )
        )
    )
    if len(matches) == 1:
        return Mention(raw=raw, person_id=matches[0].id)
    if len(matches) > 1:
        # No tiebreak: any heuristic here risks attributing one person's work to another.
        return Mention(raw=raw, unresolved_reason=f"{len(matches)} people share this name")
    return Mention(raw=raw, unresolved_reason="no person with this name")


def _identifier_kind(raw: str) -> IdentityKind | None:
    if _EMAIL.match(raw):
        return IdentityKind.EMAIL
    if raw.startswith("@") and _HANDLE.match(raw):
        return IdentityKind.GITHUB_LOGIN
    return None
