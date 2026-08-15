"""Turning a webhook payload into credited people.

Joins trailers (contributors), the bot registry (people vs automation), and
identity resolution (several identifiers collapse into one person). Produces
the identity graph, not a contribution ledger — that belongs to the
understanding layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.identity_models import Person
from cairn_api.github.bots import partition
from cairn_api.github.trailers import Contributor, contributors_of
from cairn_api.identity.resolution import resolve

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class AttributionResult:
    """Who a payload credits, after filtering and resolution."""

    people: list[Person] = field(default_factory=list)
    bots: list[Person] = field(default_factory=list)
    commits_seen: int = 0
    unparseable: int = 0


def commits_from(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """`head_commit` is deliberately not read — it duplicates the tip already
    in `commits`.
    """
    raw = payload.get("commits")
    if not isinstance(raw, list):
        return []
    return [commit for commit in raw if isinstance(commit, dict)]


async def attribute(
    session: AsyncSession,
    payload: Mapping[str, Any],
    *,
    tenant_id: uuid.UUID,
    custom_bots: list[str] | None = None,
) -> AttributionResult:
    """Resolve everyone a payload credits to person records. `session` must
    already be tenant-scoped.
    """
    result = AttributionResult()
    seen_people: dict[uuid.UUID, Person] = {}
    seen_bots: dict[uuid.UUID, Person] = {}

    for commit in commits_from(payload):
        result.commits_seen += 1
        contributors = contributors_of(commit)

        if not contributors:
            result.unparseable += 1
            continue

        humans, bots = partition(contributors, custom_bots=custom_bots or [])
        await _resolve_into(session, humans, seen_people, tenant_id, custom_bots)
        await _resolve_into(session, bots, seen_bots, tenant_id, custom_bots)

    result.people = list(seen_people.values())
    result.bots = list(seen_bots.values())

    await logger.ainfo(
        "github.attributed",
        commits=result.commits_seen,
        people=len(result.people),
        bots=len(result.bots),
        unparseable=result.unparseable,
    )
    return result


async def _resolve_into(
    session: AsyncSession,
    contributors: list[Contributor],
    target: dict[uuid.UUID, Person],
    tenant_id: uuid.UUID,
    custom_bots: list[str] | None,
) -> None:
    """Dedup on the *person*, not the contributor."""
    for contributor in contributors:
        person = await resolve(session, contributor, tenant_id=tenant_id, custom_bots=custom_bots)
        target[person.id] = person
