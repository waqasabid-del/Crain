"""Applying a resolution plan to the fact graph.

`resolve.py` decides; this module writes — kept separate so the rules are testable as pure functions. Supersession must be atomic: `ck_facts_supersession_is_complete` requires `valid_until` and `superseded_by_id` together, so the successor is flushed first. Nothing here deletes (tenant removal cascades). `apply` fetches only candidates a predicate proven to be a *superset* of `resolve()`'s rules could match (`_candidates`) — every choice there errs wide.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    any_,
    false,
    literal,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Text

from cairn_api import telemetry
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactOrigin, FactPerson, FactSource
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Membership
from cairn_api.domain import Certainty
from cairn_api.identity import external
from cairn_api.pipeline import mentions
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from cairn_api.pipeline.resolve import (
    MERGE_WINDOW,
    SUPERSEDES,
    Decision,
    Outcome,
    ResolutionPlan,
    resolve,
    subject_key,
    tokens,
)

logger = structlog.get_logger(__name__)

#: Most candidate facts one batch may pull into memory; a trip is logged
#: (`resolve.candidates_truncated`) rather than silently losing merges.
MAX_CANDIDATES = 5_000


async def load_current(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[Fact]:
    """Currently-valid facts, as resolution understands them; superseded rows
    are excluded, not filtered later."""
    rows = await session.scalars(_current(tenant_id))
    return [_to_domain(row) for row in rows]


def _current(tenant_id: uuid.UUID) -> Select[tuple[FactRow]]:
    """Currently-valid facts for one workspace, oldest first — `resolve()`
    breaks ties by position, so order must be deterministic."""
    return (
        select(FactRow)
        .where(FactRow.tenant_id == tenant_id, FactRow.valid_until.is_(None))
        .order_by(FactRow.occurred_at.nullsfirst(), FactRow.id)
    )


async def _candidates(
    session: AsyncSession, *, tenant_id: uuid.UUID, incoming: list[Fact]
) -> list[Fact]:
    """Currently-valid facts `resolve()` could possibly match this batch to.

    Must be a superset of `resolve()`'s rules — too narrow silently breaks
    merging/supersession (md/09 §3.2). Merge: kind + window + ≥1 shared token
    (real rule ≥3). Supersession: kind + ≥1 shared subject token, no time
    window. `ILIKE '%t%'` safely over-approximates "shares token".
    """
    if not incoming:
        return []

    branches: list[ColumnElement[bool]] = []
    for fact in incoming:
        window: ColumnElement[bool] = true()
        if fact.occurred_at is not None:
            window = or_(
                FactRow.occurred_at.is_(None),
                FactRow.occurred_at.between(
                    fact.occurred_at - MERGE_WINDOW, fact.occurred_at + MERGE_WINDOW
                ),
            )
        branches.append(
            and_(
                FactRow.kind == fact.kind.value,
                window,
                _mentions_any(tokens(fact.statement)),
            )
        )

        supersedable = SUPERSEDES.get(fact.kind, frozenset())
        if supersedable:
            branches.append(
                and_(
                    FactRow.kind.in_([kind.value for kind in supersedable]),
                    _mentions_any(subject_key(fact.statement)),
                )
            )

    # Newest first for the cut only; re-sorted below.
    statement = (
        _current(tenant_id)
        .where(or_(*branches))
        .order_by(None)
        .order_by(FactRow.occurred_at.desc().nullslast(), FactRow.id)
        .limit(MAX_CANDIDATES + 1)
    )
    rows = list(await session.scalars(statement))

    if len(rows) > MAX_CANDIDATES:
        rows = rows[:MAX_CANDIDATES]
        await logger.awarning(
            "resolve.candidates_truncated",
            tenant_id=str(tenant_id),
            incoming=len(incoming),
            ceiling=MAX_CANDIDATES,
        )

    # Back into `_current`'s order; datetime.min stands in for undated (NULLS FIRST).
    epoch = datetime.min.replace(tzinfo=UTC)
    rows.sort(key=lambda row: (row.occurred_at or epoch, row.id))
    return [_to_domain(row) for row in rows]


def _mentions_any(candidate_tokens: frozenset[str]) -> ColumnElement[bool]:
    """`statement ILIKE ANY (ARRAY[...])` for one fact's tokens: one array
    parameter per fact rather than one `OR` per token. An empty token set
    matches nothing, matching what `resolve()` would do."""
    if not candidate_tokens:
        return false()
    patterns = [f"%{token}%" for token in sorted(candidate_tokens)]
    return FactRow.statement.ilike(any_(literal(patterns, ARRAY(Text))))


async def apply(
    session: AsyncSession, *, tenant_id: uuid.UUID, incoming: list[Fact]
) -> ResolutionPlan:
    """Resolve a batch against the store and persist the outcome. Returns the
    plan as the audit trail behind a disputed brief."""
    with telemetry.stage("store", tenant_id=str(tenant_id)):
        current = await _candidates(session, tenant_id=tenant_id, incoming=incoming)
        plan = resolve(incoming, current)

        for decision in plan.decisions:
            if decision.outcome is Outcome.MERGED:
                await _apply_merge(session, tenant_id, decision)
            elif decision.outcome is Outcome.SUPERSEDES:
                await _apply_supersession(session, tenant_id, decision)
            else:
                await _insert(session, tenant_id, decision.fact)

            # Flushed per decision: a later decision may merge into a fact this loop just created.
            await session.flush()

        await logger.ainfo(
            "resolve.applied",
            tenant_id=str(tenant_id),
            **{
                outcome.value: sum(1 for d in plan.decisions if d.outcome is outcome)
                for outcome in Outcome
            },
        )
        return plan


async def _apply_merge(session: AsyncSession, tenant_id: uuid.UUID, decision: Decision) -> None:
    """Fold a duplicate into the fact already on record — no new row."""
    row = await session.get(FactRow, decision.merged_into)
    if row is None:
        # Resolved against a stale snapshot; insert rather than fail (a race duplicate beats a lost fact).
        await logger.awarning("resolve.merge_target_missing", fact_id=str(decision.merged_into))
        await _insert(session, tenant_id, decision.fact)
        return

    known = {(s.source, s.evidence_id) for s in row.sources}
    for ref in decision.fact.sources:
        if (ref.source, ref.evidence_id) not in known:
            row.sources.append(
                FactSource(
                    tenant_id=tenant_id,
                    source=ref.source,
                    evidence_id=ref.evidence_id,
                    quote=ref.quote,
                    url=ref.url,
                )
            )

    # Keyed on what the row actually stores, not on the incoming string. An
    # actor row has a null `mention`, so comparing incoming strings against
    # `{p.mention}` would find no match for a provider account and append a
    # duplicate on every reprocess — which the partial unique index would then
    # refuse, turning a redelivery into a failed job.
    existing = {_person_key(p) for p in row.people}
    for mention in decision.fact.people:
        if _incoming_key(mention) not in existing:
            row.people.append(_person_row(tenant_id, mention))

    row.certainty = decision.fact.certainty.value
    row.occurred_at = decision.fact.occurred_at


async def _apply_supersession(
    session: AsyncSession, tenant_id: uuid.UUID, decision: Decision
) -> None:
    """Store the new fact and close the one it replaces. The successor is
    flushed first so `superseded_by_id` points at a real row."""
    successor = await _insert(session, tenant_id, decision.fact)
    await session.flush()

    predecessor = await session.get(FactRow, decision.supersedes)
    if predecessor is None:
        await logger.awarning("resolve.supersede_target_missing", fact_id=str(decision.supersedes))
        return

    # Marked, never deleted (md/12 §6) — only the validity window closes.
    predecessor.valid_until = decision.fact.occurred_at or datetime.now(UTC)
    predecessor.superseded_by_id = successor.id
    predecessor.supersession_reason = decision.reason[:500]


async def _insert(session: AsyncSession, tenant_id: uuid.UUID, fact: Fact) -> FactRow:
    row = FactRow(
        id=fact.id,
        tenant_id=tenant_id,
        kind=fact.kind.value,
        statement=fact.statement,
        certainty=fact.certainty.value,
        origin=FactOrigin.EXTRACTED,
        occurred_at=fact.occurred_at,
        valid_from=fact.occurred_at or datetime.now(UTC),
        sources=[
            FactSource(
                tenant_id=tenant_id,
                source=ref.source,
                evidence_id=ref.evidence_id,
                quote=ref.quote,
                url=ref.url,
                project=ref.project,
            )
            for ref in fact.sources
        ],
        people=[_person_row(tenant_id, name) for name in fact.people],
    )
    session.add(row)
    return row


async def attach_people(session: AsyncSession, *, tenant_id: uuid.UUID, fact_id: uuid.UUID) -> None:
    """Resolve one stored fact's mentions to people; delegates to
    `attach_people_bulk` for a single implementation."""
    await attach_people_bulk(session, tenant_id=tenant_id, fact_ids=[fact_id])


async def _resolve_actors(
    session: AsyncSession, links: Sequence[FactPerson]
) -> dict[tuple[str | None, str | None], uuid.UUID]:
    """Every distinct provider account in this batch, resolved once.

    Deduplicated before the lookup because one delivery commonly produces
    several facts from the same author, and each would otherwise repeat the
    query. Only `ACTIVE` links resolve — `external.resolve_person` enforces
    that, so a revoked or disputed account falls through to unresolved here
    rather than being quietly honoured.
    """
    wanted = {
        (link.provider, link.provider_account_id)
        for link in links
        if link.provider_account_id is not None and link.provider is not None
    }
    found: dict[tuple[str | None, str | None], uuid.UUID] = {}
    for provider_value, account_id in wanted:
        try:
            provider = ConnectorProvider(provider_value)
        except ValueError:
            # Fails closed. An unrecognised provider is not attributed to
            # anybody, and the row stays as recorded provenance.
            continue
        person = await external.resolve_person(
            session, provider=provider, provider_account_id=account_id
        )
        if person is not None:
            found[(provider_value, account_id)] = person.id
    return found


def _person_key(row: FactPerson) -> tuple[str | None, str | None, str | None]:
    """What makes a stored `fact_people` row distinct, in either shape."""
    return (row.mention, row.provider, row.provider_account_id)


def _incoming_key(mention: str) -> tuple[str | None, str | None, str | None]:
    """The same key, computed from an incoming mention string."""
    actor = mentions.read_provider_actor(mention)
    if actor is None:
        return (mention, None, None)
    return (None, actor.provider.value, actor.account_id)


def _person_row(tenant_id: uuid.UUID, mention: str) -> FactPerson:
    """One `fact_people` row from one incoming mention string.

    **The sentinel never reaches the database.** The pipeline carries a provider
    account through the in-memory fact as `provider:{provider}:{account_id}`,
    because the extracted-fact model has one list for "who is this about". This
    is where that encoding stops: the row is written with structured `provider`
    and `provider_account_id` columns and a null `mention`, so nothing
    downstream — a serializer, an export, a log line, a correction screen — can
    render a private provider identifier as if it were somebody's name.
    """
    actor = mentions.read_provider_actor(mention)
    if actor is None:
        return FactPerson(tenant_id=tenant_id, mention=mention)
    return FactPerson(
        tenant_id=tenant_id,
        mention=None,
        provider=actor.provider.value,
        provider_account_id=actor.account_id,
    )


async def attach_people_bulk(
    session: AsyncSession, *, tenant_id: uuid.UUID, fact_ids: Sequence[uuid.UUID]
) -> None:
    """Resolve a whole batch of facts' mentions in one pass; replaces an N+1
    by loading facts in one `IN` query and deduplicating mentions first."""
    if not fact_ids:
        return

    rows = list(
        await session.scalars(
            select(FactRow).where(FactRow.tenant_id == tenant_id, FactRow.id.in_(fact_ids))
        )
    )
    links = [link for row in rows for link in row.people]
    if not links:
        return

    # Two kinds of row, resolved by two different rules, because the evidence
    # behind them is different in kind. A `mention` is text a model wrote — a
    # claim about who a statement concerns. An actor is the account the provider
    # itself named. Only the second may decide ownership.
    names = sorted({link.mention for link in links if link.mention is not None})
    resolution = await mentions.resolve_mentions(session, tenant_id=tenant_id, names=names)
    by_actor = await _resolve_actors(session, links)

    sources_by_fact = {row.id: {source.source for source in row.sources} for row in rows}
    opted_out = await _opt_outs_for(session, tenant_id, sources_by_fact)
    unnotified = await _unnotified_people(session, tenant_id)

    by_mention = {m.raw: m for m in resolution.mentions}
    for link in links:
        resolved = (
            by_actor.get((link.provider, link.provider_account_id))
            if link.provider_account_id is not None
            else None
        )
        match = by_mention.get(link.mention) if link.mention is not None else None
        person_id = resolved if resolved is not None else (match.person_id if match else None)
        # Only ever set, never cleared — a human-confirmed link must survive an automatic pass.
        if person_id is None or link.person_id is not None:
            continue

        # Opt-out enforced at attribution time, not read time, so nothing depends on remembering to filter later.
        blocked = opted_out.get(person_id, set())
        if blocked & sources_by_fact.get(link.fact_id, set()):
            continue

        # Legal obligation, no regional exception (md/05 §B.3.5): no attribution before first-capture notification.
        if person_id in unnotified:
            continue

        link.person_id = person_id


async def _unnotified_people(session: AsyncSession, tenant_id: uuid.UUID) -> set[uuid.UUID]:
    """People whose worker notification has not been served. Members only —
    a row with no linked user has no one CAIRN could notify."""
    rows = await session.scalars(
        select(Person.id)
        .join(Membership, Membership.user_id == Person.user_id)
        .where(
            Person.tenant_id == tenant_id,
            Membership.tenant_id == tenant_id,
            Membership.notified_at.is_(None),
        )
    )
    return set(rows)


async def reconcile_actor(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    person_id: uuid.UUID,
    provider: ConnectorProvider,
    provider_account_id: str,
) -> int:
    """Attribute the work this account already produced, to the person who just
    claimed it. Returns how many rows changed.

    Run when somebody confirms a provider account is theirs. Everything CAIRN
    recorded from that account before the confirmation is sitting unresolved —
    an honest blank, but a blank — and this is what fills it in.

    **Exact tuple only.** The `WHERE` is tenant, provider and account id, all
    three. There is no name, no handle, no content, no similarity and no model
    anywhere in this function; it moves rows that already carry the account the
    person just proved is theirs, and nothing else.

    **Never reassigns.** `person_id IS NULL` is part of the `WHERE`, so a fact
    already attributed to somebody — automatically or by their own correction —
    is untouched. Two people cannot both hold a live link to one account
    (`uq_external_identities_live_account`), so this cannot silently move work
    between colleagues; and if a link is ever transferred after a revocation,
    the previous owner's attributed history stays theirs rather than being
    retroactively rewritten. That is the conservative reading: the work *was*
    attributed to them at the time, and changing it later would edit a record
    somebody may already have corrected.

    **Idempotent and concurrency-safe by construction.** One `UPDATE` whose
    predicate excludes rows it has already changed, so a second run matches
    nothing and two concurrent runs cannot double-apply. Resumable for the same
    reason: an interrupted run leaves the remainder still matching.

    **Consent is enforced here too, not only at ingestion.** A person who opted
    out of Slack and then confirms their Slack account has not opted back in —
    reconciliation would otherwise be a back door that fills in exactly the
    history the refusal exists to prevent. Facts whose evidence comes from a
    source this person refused are excluded, and so is a person whose
    first-capture notification has not been served (md/05 §B.3.5).
    """
    refused = {
        source
        for (source,) in (
            await session.execute(
                select(SourceOptOut.source).where(
                    SourceOptOut.tenant_id == tenant_id,
                    SourceOptOut.person_id == person_id,
                )
            )
        ).all()
    }
    if person_id in await _unnotified_people(session, tenant_id):
        await logger.ainfo(
            "attribution.reconcile_skipped_unnotified",
            provider=provider.value,
        )
        return 0

    candidates = select(FactPerson.id).where(
        FactPerson.tenant_id == tenant_id,
        FactPerson.provider == provider.value,
        FactPerson.provider_account_id == provider_account_id,
        FactPerson.person_id.is_(None),
    )
    if refused:
        # Exclude any fact carrying evidence from a source this person refused.
        # `EXISTS` rather than a join so one fact with two sources, one of them
        # refused, is excluded once rather than counted twice.
        blocked_facts = (
            select(FactSource.fact_id)
            .where(
                FactSource.tenant_id == tenant_id,
                FactSource.source.in_(refused),
            )
            .scalar_subquery()
        )
        candidates = candidates.where(FactPerson.fact_id.notin_(blocked_facts))

    result = await session.execute(
        update(FactPerson)
        .where(FactPerson.id.in_(candidates.scalar_subquery()))
        .values(person_id=person_id)
        .returning(FactPerson.id)
    )
    changed = len(result.all())

    await logger.ainfo(
        "attribution.reconciled",
        provider=provider.value,
        # A count and a provider. Never the account id, never the person, never
        # a fact — this line is read by whoever operates the system, not by
        # somebody entitled to the workspace's contents.
        facts=changed,
        sources_refused=len(refused),
    )
    return changed


async def _opt_outs_for(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    sources_by_fact: dict[uuid.UUID, set[str]],
) -> dict[uuid.UUID, set[str]]:
    """Opt-outs relevant to this batch, keyed by person; scoped to the
    sources the batch touches rather than loading the workspace's full history."""
    sources = {source for values in sources_by_fact.values() for source in values}
    if not sources:
        return {}

    rows = await session.execute(
        select(SourceOptOut.person_id, SourceOptOut.source).where(
            SourceOptOut.tenant_id == tenant_id, SourceOptOut.source.in_(sources)
        )
    )

    blocked: dict[uuid.UUID, set[str]] = {}
    for person_id, source in rows:
        blocked.setdefault(person_id, set()).add(source)
    return blocked


def _to_domain(row: FactRow) -> Fact:
    """A stored row as resolution sees it."""
    return Fact(
        id=row.id,
        kind=FactKind(row.kind),
        statement=row.statement,
        sources=[
            SourceRef(
                evidence_id=source.evidence_id,
                source=source.source,
                quote=source.quote,
                url=source.url,
                project=source.project,
            )
            for source in row.sources
        ],
        certainty=Certainty(row.certainty),
        # Human mentions only. An actor row carries a provider account id and no
        # name, and the domain `Fact.people` is the list of names — putting an
        # account id in it would send a private provider identifier into the
        # brief, the feed and every export built from this mapping.
        people=[p.mention for p in row.people if p.mention is not None],
        resolved_actors=sum(
            1 for p in row.people if p.provider_account_id is not None and p.person_id is not None
        ),
        unresolved_actors=sum(
            1 for p in row.people if p.provider_account_id is not None and p.person_id is None
        ),
        occurred_at=row.occurred_at,
    )


#: Public alias: the API's brief endpoint needs the same row→domain mapping.
to_domain = _to_domain
