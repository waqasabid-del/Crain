"""The understanding job — the pipeline's only production caller.

Ties `classify`, `extract`, `resolve`, `store` and `graph` to the GitHub webhook path (mirrors `github/jobs.py`'s registration pattern). One job per delivery, not per workspace/period — the smallest unit with a durable record, idempotency key and tenant already attached. Idempotency survives at-least-once delivery three ways: the evidence check (cheap, skips before any model call), Stage 3 (re-extraction merges via `resolve`), and `graph.build` (`ON CONFLICT DO NOTHING`). The check alone is defeated by a partial write; Stage 3 alone would cost a model call every redelivery — both are needed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.config import Settings, get_settings
from cairn_api.db.fact_models import FactSource
from cairn_api.db.github_models import WebhookDelivery
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import JobQueue, Priority
from cairn_api.jobs.runner import JobHandler, JobRegistry, registry
from cairn_api.pipeline import graph, store
from cairn_api.pipeline.classify import classify
from cairn_api.pipeline.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingProvider,
    HashingEmbedder,
    VertexEmbeddingProvider,
)
from cairn_api.pipeline.extract import extract
from cairn_api.pipeline.facts import Fact, SourceRef
from cairn_api.pipeline.provider import ModelProvider, ScriptedProvider, VertexProvider
from cairn_api.pipeline.spend import BudgetedProvider, ledger_for

logger = structlog.get_logger(__name__)

UNDERSTAND_JOB = "pipeline.understand"

#: Ceiling on evidence items per delivery — caps model spend and attacker-controlled input.
MAX_EVIDENCE_ITEMS = 20

#: Characters kept per evidence item; safe to truncate since this is extraction input, not a stored fact.
MAX_EVIDENCE_CHARS = 4_000


class DeliveryNotFoundError(LookupError):
    """No such delivery in this tenant: a retention sweep removed it, or the
    queue's tenant scoping failed."""


# --- The model boundary, chosen once ---


@dataclass(frozen=True, slots=True)
class Providers:
    """The two model dependencies the pipeline needs, and whether they are real."""

    model: ModelProvider
    embedder: EmbeddingProvider

    #: False when offline stand-ins are in use (not inferred via `isinstance`).
    live: bool


@lru_cache(maxsize=1)
def build_providers() -> Providers:
    """Model adapters by `CAIRN_MODEL_BACKEND` (`vertex`/`scripted`/`offline`).
    Offline is a refusal, not a degraded mode: incompleteness, not confident
    wrongness (md/09 §8). Cached to run once per process."""
    settings: Settings = get_settings()
    project = settings.gcp_project_id
    backend = settings.model_backend

    if backend == "scripted":
        # `config.py` refuses this value in any environment holding customer data.
        from cairn_api.evaluation.scripted import build_scripted_provider

        logger.warning(
            "pipeline.model_backend",
            backend="scripted",
            detail=(
                "Canned model output, for local development only. Facts and "
                "briefs produced here are demonstrations of the pipeline, not "
                "of a model."
            ),
        )
        return Providers(model=build_scripted_provider(), embedder=HashingEmbedder(), live=False)

    if project and backend in {"auto", "vertex"}:
        logger.info(
            "pipeline.model_backend",
            backend="vertex",
            project=project,
        )
        return Providers(
            model=VertexProvider(project_id=project),
            embedder=VertexEmbeddingProvider(project_id=project),
            live=True,
        )

    logger.warning(
        "pipeline.no_model_configured",
        backend="offline",
        detail=(
            "No model backend. The understanding pipeline is "
            "running without a model: events will be classified as unknown, no "
            "facts will be extracted, and every brief will be empty. Retrieval "
            "falls back to hashed embeddings, which is degraded but real."
        ),
    )
    return Providers(
        model=ScriptedProvider(model_name="offline"),
        embedder=HashingEmbedder(),
        live=False,
    )


# --- Evidence ---


@dataclass(frozen=True, slots=True)
class _Evidence:
    """One citable thing inside a delivery."""

    evidence_id: str
    text: str
    url: str | None
    occurred_at: datetime | None

    #: Read from the delivery, not the model — a fact filed under the wrong
    #: project is worse than one filed under none.
    project: str | None = None


def _read_evidence(delivery: WebhookDelivery) -> list[_Evidence]:
    """Everything in a payload a fact could legitimately cite. Evidence ids
    are stable across redelivery (commit SHA; PR/issue number), which is
    what makes the idempotency check possible. Read defensively."""
    payload = delivery.payload
    project = _text(_dig(payload, "repository", "full_name"))
    repository = project or "unknown"  # ok in an evidence id, not as a filterable project name
    found: list[_Evidence] = []

    for commit in _commits(payload):
        sha = _text(commit.get("id"))
        message = _text(commit.get("message"))
        if not sha or not message:
            continue
        found.append(
            _Evidence(
                evidence_id=f"github:commit:{sha}",
                text=message,
                url=_text(commit.get("url")),
                occurred_at=_timestamp(commit.get("timestamp")),
            )
        )

    for key, label in (("pull_request", "pull_request"), ("issue", "issue")):
        item = payload.get(key)
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        title = _text(item.get("title"))
        if not isinstance(number, int) or not title:
            continue
        body = _text(item.get("body")) or ""
        found.append(
            _Evidence(
                evidence_id=f"github:{label}:{repository}#{number}",
                text=f"{delivery.action or 'updated'}: {title}\n\n{body}".strip(),  # action first: "opened" vs "closed" differ
                url=_text(item.get("html_url")),
                occurred_at=(
                    _timestamp(item.get("merged_at"))
                    or _timestamp(item.get("closed_at"))
                    or _timestamp(item.get("updated_at"))
                    or _timestamp(item.get("created_at"))
                ),
            )
        )

    comment = payload.get("comment")
    if isinstance(comment, dict):
        remark = _text(comment.get("body"))
        comment_id = comment.get("id")
        if remark and isinstance(comment_id, int):
            found.append(
                _Evidence(
                    evidence_id=f"github:comment:{repository}#{comment_id}",
                    text=remark,
                    url=_text(comment.get("html_url")),
                    occurred_at=_timestamp(comment.get("updated_at"))
                    or _timestamp(comment.get("created_at")),
                )
            )

    return [
        _Evidence(
            evidence_id=item.evidence_id,
            text=item.text[:MAX_EVIDENCE_CHARS],
            url=item.url,
            occurred_at=item.occurred_at,
            project=project,
        )
        for item in found[:MAX_EVIDENCE_ITEMS]
    ]


def _commits(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Commits in a push payload. `head_commit` deliberately not read — it
    duplicates the tip already in `commits`."""
    raw = payload.get("commits")
    if not isinstance(raw, list):
        return []
    return [commit for commit in raw if isinstance(commit, dict)]


def _dig(payload: Mapping[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _timestamp(value: Any) -> datetime | None:
    """Parse a GitHub timestamp, or nothing — never "now" (would let backfilled history retire current state)."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _render(evidence: Iterable[_Evidence]) -> str:
    """The data block: one line per evidence item, id first — same shape as
    the evaluation harness and `live_check`."""
    return "\n".join(f"[{item.evidence_id}] (github) {item.text}" for item in evidence)


def _with_provenance(facts: list[Fact], index: Mapping[str, _Evidence]) -> list[Fact]:
    """Attach the URL and quoted span to every citation (filled in from our
    payload, not the model — a fabrication carrying a link is more
    convincing), and date the fact from the evidence, not now."""
    dated: list[Fact] = []
    for fact in facts:
        cited = [index[ref.evidence_id] for ref in fact.sources if ref.evidence_id in index]
        sources = [_enrich(ref, index.get(ref.evidence_id)) for ref in fact.sources]
        occurred = next((item.occurred_at for item in cited if item.occurred_at is not None), None)
        dated.append(fact.model_copy(update={"sources": sources, "occurred_at": occurred}))
    return dated


def _enrich(ref: SourceRef, item: _Evidence | None) -> SourceRef:
    """One citation, with the link and the span filled in where we have them."""
    if item is None:
        # Unreachable in practice (`extract` drops facts citing unseen evidence); handled, not asserted.
        return ref
    return SourceRef(
        evidence_id=ref.evidence_id,
        source=ref.source,
        quote=item.text[:2000],  # span verification (Step 18) needs text, not an artefact pointer
        url=item.url,
        project=item.project,
    )


# --- The handler ---


def make_handler(
    *,
    providers: Providers | None = None,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> JobHandler:
    """Build the handler, bound to the model adapters it will use.

    A factory (like `github/jobs.py`): the job runner's signature provides
    only a session, so anything else is closed over at wiring time.
    `providers` is injectable so a test can drive the real path with a
    scripted model.
    """
    resolved = providers or build_providers()

    async def handle_understanding(session: AsyncSession, envelope: JobEnvelope) -> None:
        delivery_id = envelope.payload.get("delivery_id")
        if not isinstance(delivery_id, str):
            msg = f"Job {envelope.job_id} has no delivery_id"
            raise DeliveryNotFoundError(msg)

        # Session is tenant-scoped; row-level security filters out any other workspace's delivery.
        delivery = await session.scalar(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        if delivery is None:
            msg = f"Delivery {delivery_id} not found for tenant {envelope.tenant_id}"
            raise DeliveryNotFoundError(msg)

        await _understand(
            session,
            delivery,
            tenant_id=envelope.tenant_id,
            providers=resolved,
            model_name=model_name,
        )

    return handle_understanding


async def _understand(
    session: AsyncSession,
    delivery: WebhookDelivery,
    *,
    tenant_id: uuid.UUID,
    providers: Providers,
    model_name: str,
) -> None:
    """Stages 1 to 3 over one delivery, then the graph. Stage 4 is
    deliberately absent — synthesis runs per period (md/09 §2), on the read
    path in `api/routers/facts.py`."""
    evidence = _read_evidence(delivery)
    if not evidence:
        await logger.adebug(
            "understand.no_evidence",
            delivery_id=delivery.delivery_id,
            event_type=delivery.event_type,
        )
        return

    index = {item.evidence_id: item for item in evidence}

    if await _already_understood(session, tenant_id=tenant_id, evidence_ids=list(index)):
        await logger.adebug("understand.already_applied", delivery_id=delivery.delivery_id)
        return

    # Per-tenant ledger so one workspace's runaway backfill can't deny the model to others (spend.py).
    ledger = ledger_for(str(tenant_id))
    budgeted = BudgetedProvider(inner=providers.model, ledger=ledger)

    content = _render(evidence)

    classification = await classify(budgeted.for_stage("classify"), content=content)
    if not classification.event_class.should_extract:
        await logger.ainfo(
            "understand.skipped",
            delivery_id=delivery.delivery_id,
            event_class=classification.event_class.value,
        )
        return

    result = await extract(
        budgeted.for_stage("extract"),
        content=content,
        known_evidence=dict.fromkeys(index, "github"),
    )
    if not result.facts:
        await logger.ainfo(
            "understand.nothing_extracted",
            delivery_id=delivery.delivery_id,
            abstained=result.abstained,
            live_model=providers.live,  # distinguishes "extracted nothing" from "no model" (an outage)
            spend_exceeded=ledger.exceeded,
            diagnostics=result.diagnostics[:5],
        )
        return

    facts = _with_provenance(result.facts, index)

    plan = await store.apply(session, tenant_id=tenant_id, incoming=facts)
    await session.flush()

    await store.attach_people_bulk(
        session,
        tenant_id=tenant_id,
        fact_ids=[decision.merged_into or decision.fact.id for decision in plan.decisions],
    )

    update = await graph.build(  # graph last: edges derive from people/supersession, just written
        session, tenant_id=tenant_id, embedder=providers.embedder, model_name=model_name
    )

    await logger.ainfo(
        "understand.applied",
        delivery_id=delivery.delivery_id,
        event_type=delivery.event_type,
        evidence=len(evidence),
        facts=len(plan.decisions),
        edges=update.edges_written,
        embeddings=update.embeddings_written,
        model_calls=ledger.total_calls,
        model_tokens=ledger.total_tokens,
    )


async def _already_understood(
    session: AsyncSession, *, tenant_id: uuid.UUID, evidence_ids: list[str]
) -> bool:
    """Whether every piece of this delivery's evidence is already cited.

    Only ever allowed to *skip* work — a wrong answer costs a redundant model
    call, never a lost fact. Set containment against the facts themselves,
    not a marker column, so partial coverage (a crash mid-write) correctly
    returns False and lets Stage 3 fold the repeats back in.
    """
    cited = set(
        await session.scalars(
            select(FactSource.evidence_id).where(
                FactSource.tenant_id == tenant_id,
                FactSource.evidence_id.in_(evidence_ids),
            )
        )
    )
    return cited.issuperset(evidence_ids)


# --- Publishing and registration ---


async def publish(queue: JobQueue, *, tenant_id: uuid.UUID, delivery_id: str) -> None:
    """Enqueue understanding for one delivery. `STANDARD`: not `INTERACTIVE`
    (nobody watches a spinner for this), not `BULK` (this *is* the live
    event, md/06 §6B.3)."""
    await queue.publish(
        JobEnvelope(
            job_type=UNDERSTAND_JOB,
            tenant_id=tenant_id,
            payload={"delivery_id": delivery_id},
        ),
        priority=Priority.STANDARD,
    )


def register(
    target: JobRegistry | None = None,
    *,
    providers: Providers | None = None,
) -> None:
    """Register the understanding handler, explicitly — never by import side
    effect. This module's own history is the argument: an import-time
    registry looked populated in tests (imported by the evaluation harness)
    and was empty in the worker.
    """
    (target or registry).register(UNDERSTAND_JOB)(make_handler(providers=providers))
