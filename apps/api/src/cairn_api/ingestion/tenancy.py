"""Which workspace an inbound event belongs to.

The rule this module exists to enforce: **the tenant comes from the account
identifier, resolved against a mapping an authenticated user created — never
from anything the request body claims.** A payload field named `tenant_id`,
`workspace`, `team` or `org` is data, not authority; honouring one would mean an
inbound webhook chooses whose workspace a stranger's activity lands in.

The mapping itself (GitHub's `github_installations`, and whatever Slack and
Chat get) is written only by a connect flow behind a session, a membership and a
permission check. Ingestion reads it and never writes it.

An account nobody has connected is a refusal, not a guess. The event is still
acknowledged at the HTTP layer — a provider retries a non-2xx, and retrying will
not make the account known — but it is attributed to nothing and enqueued
nowhere.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from cairn_api.ingestion.errors import UnknownAccountError
from cairn_api.ingestion.inbound import SourceMetadata


@dataclass(frozen=True, slots=True)
class ResolvedTenant:
    """A tenant, and the external account that pointed at it."""

    tenant_id: uuid.UUID

    #: Carried so a caller can log *why* this tenant was chosen without
    #: re-deriving it.
    external_account_id: str

    #: False when the integration exists but is switched off — suspended,
    #: uninstalled, consent withdrawn. Kept separate from "unknown" because the
    #: two mean different things to an operator and to a customer: one is a
    #: stranger, the other is a customer who turned us off, and capturing the
    #: second is a consent failure rather than a mystery.
    active: bool = True


class TenantResolver(Protocol):
    """Look up the workspace connected to an external account.

    Returns `None` rather than raising, so "nobody has connected this" is an
    ordinary answer a provider can act on. `resolve_tenant` turns it into the
    refusal for callers that would otherwise have to remember to check.
    """

    async def resolve(self, source: SourceMetadata) -> ResolvedTenant | None: ...


async def resolve_tenant(resolver: TenantResolver, source: SourceMetadata) -> ResolvedTenant:
    """The tenant for this event, or `UnknownAccountError`.

    Never falls back to a default, a first-row, or a single-tenant assumption.
    A wrong answer here is a cross-tenant data leak, and "no answer" is the only
    safe alternative to the right one.
    """
    if source.external_account_id is None:
        msg = f"A {source.provider} {source.event_type} event named no account"
        raise UnknownAccountError(msg)

    resolved = await resolver.resolve(source)
    if resolved is None:
        msg = f"No workspace is connected to {source.provider} account {source.external_account_id}"
        raise UnknownAccountError(msg)

    return resolved
