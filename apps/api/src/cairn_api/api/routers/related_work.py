"""The related-work finder: evidence of who has touched a topic. Nothing more.

**What this deliberately is not.** Not a ranking, not a recommender, not an
allocator, not a skills database. CAIRN shows evidence of related work — cited
facts, grouped by the person they credit — and the person's own self-stated
capacity beside it, and the human decides. There is no score, no percentage,
no match strength, no ordering by relevance: groups are ordered by most recent
related fact, which is a property of the evidence, and the UI says so in those
words. A person-level relevance number does not exist even internally in the
response model, because a field that exists gets displayed eventually, and a
displayed number between people is a ranking whatever the label says
(md/05 §B.2.2).

The six commitments of md/05 §B.2, on this feature's face:

1. Symmetric — Owner, Member and Viewer asking the same topic receive
   byte-identical responses; the handler never consults the caller's role.
2. No scoring — see above, and the test that greps the response model.
3. Employee-owned — everything shown is facts the person can already see,
   correct and annotate on their own record; nothing new is asserted here.
4. Non-code work surfaces exactly as code does: the search runs over facts,
   and a mentoring fact is a fact.
5. Opt-in inherited structurally: opting out of a source unlinks
   `fact_people.person_id`, and this endpoint groups by resolved person only,
   so an opted-out person cannot surface and an unresolved mention never
   appears. Absence is not data — a person with no related facts is simply not
   in the response, and "unrelated" is never asserted.
6. No training — deterministic retrieval; the topic is embedded and searched,
   no generative model is called, and the topic string follows the same
   no-content-in-telemetry rule as everything else: it is never logged.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.api.dependencies import TenantDb, WorkspaceContext, requires
from cairn_api.api.schemas import (
    RelatedFact,
    RelatedFactSource,
    RelatedPersonGroup,
    RelatedWorkResponse,
)
from cairn_api.auth.permissions import Permission
from cairn_api.db.fact_models import FactPerson
from cairn_api.db.identity_models import Person
from cairn_api.pipeline.jobs import build_providers
from cairn_api.pipeline.retrieval import retrieve

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/workspaces", tags=["related-work"])

#: Bounded like every other free-text input that reaches an embedding call.
MAX_TOPIC_LENGTH = 500


async def find_related_work_payload(
    session: AsyncSession, *, tenant_id: uuid.UUID, topic: str
) -> RelatedWorkResponse:
    """The finder, independent of any request context.

    Takes no role, no caller, no viewer — which is how symmetry is guaranteed
    structurally rather than checked politely. The route below adds
    authentication and nothing else.
    """
    providers = build_providers()
    retrieval = await retrieve(
        session,
        tenant_id=tenant_id,
        question=topic,
        embedder=providers.embedder,
    )

    fact_ids = [item.fact.id for item in retrieval.facts]
    facts_by_id = {item.fact.id: item.fact for item in retrieval.facts}

    people_rows: dict[uuid.UUID, Person] = {}
    facts_by_person: dict[uuid.UUID, list[uuid.UUID]] = {}
    if fact_ids:
        links = await session.execute(
            select(FactPerson.fact_id, Person)
            .join(Person, Person.id == FactPerson.person_id)
            .where(
                FactPerson.tenant_id == tenant_id,
                FactPerson.fact_id.in_(fact_ids),
                # Resolved people only: an unresolved mention is a name nobody
                # confirmed, and opt-out unlinks this column - both consent
                # decisions inherited in one condition.
                FactPerson.person_id.is_not(None),
            )
        )
        for fact_id, person in links:
            people_rows[person.id] = person
            facts_by_person.setdefault(person.id, []).append(fact_id)

    groups = []
    for person_id, person_fact_ids in facts_by_person.items():
        person = people_rows[person_id]
        related = sorted(
            {facts_by_id[fact_id] for fact_id in person_fact_ids},
            key=lambda fact: (fact.occurred_at is None, fact.occurred_at),
            reverse=True,
        )
        groups.append(
            RelatedPersonGroup(
                person_id=person_id,
                display_name=person.display_name or "Unnamed person",
                capacity=person.capacity,
                capacity_stated_at=person.capacity_stated_at,
                facts=[
                    RelatedFact(
                        statement=fact.statement,
                        certainty=fact.certainty,
                        occurred_at=fact.occurred_at,
                        sources=[
                            RelatedFactSource(
                                evidence_id=source.evidence_id,
                                source=source.source,
                                url=source.url,
                            )
                            for source in fact.sources
                        ],
                    )
                    for fact in related
                ],
            )
        )

    # Most recent related fact first - evidence ordering, stated as such in the
    # UI. Ties broken by name so two runs return identical bytes.
    groups.sort(
        key=lambda group: (
            group.facts[0].occurred_at is None,
            group.facts[0].occurred_at,
            group.display_name,
        ),
        reverse=True,
    )

    return RelatedWorkResponse(topic=topic, groups=groups)


@router.get(
    "/{workspace_id}/related-work",
    response_model=RelatedWorkResponse,
    summary="Find who has worked on related things, with evidence",
)
async def find_related_work(
    context: Annotated[WorkspaceContext, Depends(requires(Permission.CONTENT_READ))],
    db: TenantDb,
    topic: Annotated[str, Query(min_length=2, max_length=MAX_TOPIC_LENGTH)],
) -> RelatedWorkResponse:
    """See the module docstring for everything this refuses to be.

    The topic is deliberately not logged: it is free text about somebody's
    work, and the telemetry allow-list has no slot for it. The count is
    observable; the words are not.
    """
    payload = await find_related_work_payload(db, tenant_id=context.tenant_id, topic=topic)
    await logger.ainfo(
        "related_work.searched",
        tenant_id=str(context.tenant_id),
        groups=len(payload.groups),
    )
    return payload
