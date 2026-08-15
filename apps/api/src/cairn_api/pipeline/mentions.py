"""Resolving names a model extracted to people the workspace knows.

An identifier (email, handle) is a lookup; a name is not — colleagues share
names, and matching on one risks crediting one person's work to another. A
name matching exactly one person resolves as a proposal a person can correct,
never a confirmed identity (md/01 §5.3). A name matching two or more resolves
to neither: no tiebreak is better than a coin flip.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.identity_models import Identity, IdentityKind, Person

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_HANDLE = re.compile(r"^@?[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


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
