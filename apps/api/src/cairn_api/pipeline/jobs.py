"""The understanding job — the pipeline's only production caller.

Ties `classify`, `extract`, `resolve`, `store` and `graph` to the GitHub webhook path (mirrors `github/jobs.py`'s registration pattern). One job per delivery, not per workspace/period — the smallest unit with a durable record, idempotency key and tenant already attached. Idempotency survives at-least-once delivery three ways: the evidence check (cheap, skips before any model call), Stage 3 (re-extraction merges via `resolve`), and `graph.build` (`ON CONFLICT DO NOTHING`). The check alone is defeated by a partial write; Stage 3 alone would cost a model call every redelivery — both are needed.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import structlog
from opentelemetry import metrics
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api import sources as canonical
from cairn_api.config import Settings, get_settings
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.fact_models import FactSource
from cairn_api.db.github_models import WebhookDelivery
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.queue import JobQueue, Priority
from cairn_api.jobs.runner import JobHandler, JobRegistry, registry
from cairn_api.pipeline import graph, store
from cairn_api.pipeline.classify import classify
from cairn_api.pipeline.embeddings import (
    EmbeddingProvider,
    HashingEmbedder,
    OpenAIEmbeddingProvider,
    VertexEmbeddingProvider,
)
from cairn_api.pipeline.extract import extract
from cairn_api.pipeline.facts import Fact, SourceRef
from cairn_api.pipeline.mentions import ProviderActor
from cairn_api.pipeline.provider import (
    ModelProvider,
    OpenAIProvider,
    ScriptedProvider,
    VertexProvider,
)
from cairn_api.pipeline.spend import BudgetedProvider, ledger_for
from cairn_api.pipeline.spend_store import process_spend_store
from cairn_api.telemetry.attributes import safe

logger = structlog.get_logger(__name__)

meter = metrics.get_meter("cairn.pipeline")

#: Every time a cap changes what the pipeline would otherwise have done.
#:
#: One counter with an `outcome`, rather than one per cap, so "is anything being
#: capped anywhere" is a single query. `chunked` means a delivery needed more
#: than one model round and got them; `chars_truncated` means a message was cut
#: and marked. Neither is an error, and both are things somebody reading a thin
#: brief needs to be able to check.
evidence_capped = meter.create_counter(
    "cairn.pipeline.evidence_capped",
    description="Deliveries whose evidence hit a size cap",
)

UNDERSTAND_JOB = "pipeline.understand"

#: Evidence items per *model round* — caps prompt size, model spend and how much
#: attacker-controlled input reaches one call.
#:
#: **A batch size, not a limit on what is read.** It used to be
#: `found[:MAX_EVIDENCE_ITEMS]`, which silently discarded everything past the
#: twentieth item: a real 26-commit push produced facts for 20 commits, and the
#: six that vanished included a co-authored one, so two people's work
#: disappeared with no log line, no counter and no marker anywhere. Raising the
#: number would only have moved the cliff.
MAX_EVIDENCE_ITEMS = 20

#: Characters kept per evidence item; safe to truncate since this is extraction
#: input, not a stored fact.
#:
#: Unlike the item cap this one cannot be chunked away. A commit message is one
#: piece of evidence under one id, and splitting it would either duplicate that
#: id — breaking the idempotency check, which is set containment over ids — or
#: invent one that cites nothing real. So it stays a cap and becomes an honest
#: one: counted, logged, and marked in the text.
MAX_EVIDENCE_CHARS = 4_000

#: Appended when the cap above bites, so the *model* is told it is reading a
#: fragment. Without it, extraction summarises a message that stops mid-word and
#: states the result with the confidence of a complete one.
TRUNCATION_MARKER = "\n[truncated]"


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
    """The process's model adapters, built once.

    Cached, and therefore parameterless: `Settings` is not hashable, so an
    injectable argument would have to be excluded from the cache key — which is
    the kind of cache that returns one caller's providers to another. The
    selection itself lives in `select_providers`, which takes settings and
    caches nothing, so a test can exercise every branch without reaching into
    the cache or the environment.
    """
    return select_providers(get_settings())


def select_providers(settings: Settings) -> Providers:
    """Model adapters by `CAIRN_MODEL_BACKEND`
    (`openai`/`vertex`/`scripted`/`offline`). Offline is a refusal, not a
    degraded mode: incompleteness, not confident wrongness (md/09 §8)."""
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

    if backend == "openai":
        # `config.py` refuses this value without a key, in every environment, so
        # reaching here means one is present.
        logger.info(
            "pipeline.model_backend",
            backend="openai",
            model=settings.openai_model,
        )
        return Providers(
            model=OpenAIProvider(
                api_key=settings.openai_api_key.get_secret_value(),
                model=settings.openai_model,
            ),
            embedder=OpenAIEmbeddingProvider(api_key=settings.openai_api_key.get_secret_value()),
            live=True,
        )

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

    #: The provider's own stable id for whoever produced this — a Slack `U…`, a
    #: Chat `users/…`, a GitHub numeric user id. **Never a handle, a display
    #: name or an address**: those are renameable, and attribution keyed on a
    #: renameable string is silently reassigned by somebody else's rename.
    #:
    #: `None` is ordinary and means the provider did not state an author on this
    #: payload — a push event names the pusher, not the author of each commit,
    #: and attributing a commit to whoever pushed it would be wrong.
    actor: ProviderActor | None = None


def _actor(provider: ConnectorProvider, account_id: str | None) -> ProviderActor | None:
    """One provider account, or nothing.

    A missing author is not an error: it is a payload on which the provider did
    not state one, and the honest record of that is an absence rather than a
    guess. Nothing here falls back to a name, a handle or the workspace's only
    other member.
    """
    cleaned = (account_id or "").strip()
    if not cleaned:
        return None
    return ProviderActor(provider=provider, account_id=cleaned)


def _read_slack_evidence(delivery: WebhookDelivery) -> list[_Evidence]:
    """One public-channel message, as something a fact can cite.

    Slack's identity is `(team, channel, ts)` — `ts` is unique per channel only,
    so a shorter id would collide the moment two channels are selected. The same
    id is what an edit updates and a delete retires, which is why it is built
    from the message's own timestamp rather than the delivery's.

    Deletes carry no text by design: the citation must stop resolving, and
    returning nothing is how a retired statement leaves the record rather than
    standing as current. Bot messages and unselected channels never reach here —
    `slack/events.py` drops them before the delivery is recorded.
    """
    payload = delivery.payload
    event = payload.get("event")
    if not isinstance(event, dict):
        return []

    subtype = _text(event.get("subtype"))
    if subtype == "message_deleted":
        return []

    inner = event.get("message") if subtype == "message_changed" else event
    if not isinstance(inner, dict):
        return []

    # The edited message's own author, for the same reason the timestamp below
    # is the inner one: on an edit the outer envelope describes the editor.
    author = _text(inner.get("user"))
    text = _text(inner.get("text"))
    # The edited message's own timestamp, never the outer one: the outer `ts` is
    # when the edit happened, and citing it would file the correction as a
    # second statement instead of replacing the first.
    ts = _text(inner.get("ts")) or _text(event.get("ts"))
    channel = _text(event.get("channel"))
    team = _text(payload.get("team_id"))
    if not text or not ts or not channel or not team:
        return []

    return [
        _Evidence(
            evidence_id=f"slack:message:{team}:{channel}:{ts}",
            text=text[:MAX_EVIDENCE_CHARS],
            # Slack sends no permalink on the event and CAIRN holds no scope to
            # ask for one, so the citation carries no link rather than a guessed
            # URL. An evidence id a reader cannot click is honest; a fabricated
            # one is not.
            url=None,
            occurred_at=_slack_timestamp(ts),
            # Slack has no equivalent of a repository, and inventing one from the
            # channel would make a filterable project out of a name the event
            # does not even carry.
            project=None,
            actor=_actor(ConnectorProvider.SLACK, author),
        )
    ]


def _read_gchat_evidence(delivery: WebhookDelivery) -> list[_Evidence]:
    """One Google Chat space message, as something a fact can cite.

    Chat's identity is the message **resource name** —
    `spaces/{space}/messages/{message}` — which is globally unique and identical
    across the create, every edit and the delete of one message. That is what
    makes an edit update the statement it corrects rather than filing a second
    one beside it.

    Deletes carry no evidence by design, exactly as Slack's do: the citation must
    stop resolving, and returning nothing is how a retired statement leaves the
    record rather than standing as current. Google's documented delete payload
    still echoes `text` and `sender`; that is boilerplate about a message that no
    longer exists, and re-reading it would resurrect the claim the deletion
    retracted.

    Bot messages and unpermitted spaces never reach here — `gchat/events.py`
    drops them before the delivery is recorded.
    """
    payload = delivery.payload

    # The CloudEvent type, stored beside the resource because Chat's three
    # payload shapes are identical and the body carries no type of its own.
    if (_text(payload.get("event_type")) or "").endswith(".deleted"):
        return []

    message = payload.get("message")
    if not isinstance(message, dict):
        return []

    name = _text(message.get("name"))
    text = _text(message.get("text"))
    # `users/{id}` — Google's opaque resource name. `gchat/events.py` has already
    # dropped anything whose sender type is not HUMAN, so this is a person's
    # account or the message never reached storage.
    sender = _text(_dig(message, "sender", "name"))
    if not name or not text:
        return []

    return [
        _Evidence(
            evidence_id=f"google_chat:message:{name}",
            text=text[:MAX_EVIDENCE_CHARS],
            # `chat.google.com/room/{space}/{message}` — built from the resource
            # name rather than fetched, since asking Chat for a link would be an
            # API call per delivery for a URL whose shape is stable. `None` if
            # the name is not that shape: an unclickable evidence id is honest,
            # a fabricated link is not.
            url=_gchat_permalink(name),
            occurred_at=_timestamp(message.get("createTime")),
            # Chat has no equivalent of a repository, and inventing one from the
            # space would make a filterable project out of an opaque id.
            project=None,
            actor=_actor(ConnectorProvider.GOOGLE_CHAT, sender),
        )
    ]


#: `spaces/{space}/messages/{message}` — four segments, and exactly four.
_GCHAT_NAME_SEGMENTS = 4


def _gchat_permalink(message_name: str) -> str | None:
    parts = message_name.split("/")
    if len(parts) != _GCHAT_NAME_SEGMENTS or parts[0] != "spaces" or parts[2] != "messages":
        return None
    return f"https://chat.google.com/room/{parts[1]}/{parts[3]}"


def _source_of(evidence_id: str) -> str:
    """Which source a citation came from, read from the id it already carries.

    The id is minted with its provider prefix at the moment the evidence is
    read, so this cannot drift from the thing it describes — unlike a parallel
    argument threaded down from the caller, which is what it replaced.

    **Fails closed on an unknown prefix.** This used to return `"github"` for
    anything unrecognised. That value is written to `fact_sources.source` and is
    what the opt-out gate compares a person's refusal against, so an unknown
    prefix silently relabelled evidence as a source the workspace had probably
    connected — and consent was then enforced against a label CAIRN invented.
    """
    return canonical.source_of_evidence_id(evidence_id).value


def _slack_timestamp(ts: str) -> datetime | None:
    """Slack's `ts` is unix seconds with a per-channel counter after the dot."""
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError):
        return None


def _commit_text(commit: Mapping[str, Any], message: str) -> str:
    """The commit message, with the author it is credited to named above it.

    **The message alone loses the author.** `Co-authored-by:` trailers are in the
    message, but the author is not — they live in `commit.author`, which nothing
    rendered. The first real delivery produced a fact crediting the co-author and
    omitting the person who wrote the commit: one half of a pair credited, which
    is md/01 §5.1's failure arriving from the side nobody guarded.

    Not an `actor`, deliberately. An actor is a stable provider account id, and
    `commit.author` offers a login and an address that the account holder can
    change at will. Naming them in the text keeps this a claim the payload made,
    which extraction weighs and a person can correct, rather than provenance the
    system asserts.
    """
    author = commit.get("author")
    name = _text(author.get("name")) if isinstance(author, dict) else ""
    if not name:
        # Absent stays absent. A commit with no author named is a commit with no
        # author named, and inventing a label for it is the guess this avoids.
        return message
    return f"Author: {name}" + chr(10) + message


def _bounded(text: str, *, delivery_id: str) -> str:
    """Apply the per-item character cap, visibly.

    Returns the text unchanged when it fits. When it does not, the cut is
    marked, logged and counted — the same treatment the item cap gets, for the
    same reason: a cap nobody can see is indistinguishable from a short commit
    message, and the person who notices is the one whose work was summarised
    from half a sentence.
    """
    if len(text) <= MAX_EVIDENCE_CHARS:
        return text

    logger.info(
        "evidence.truncated",
        delivery_id=delivery_id,
        # Lengths, never the text: this is a commit message, which is customer
        # content and stays out of the log store.
        original_chars=len(text),
        kept_chars=MAX_EVIDENCE_CHARS,
    )
    evidence_capped.add(1, safe({"outcome": "chars_truncated"}))
    return text[:MAX_EVIDENCE_CHARS] + TRUNCATION_MARKER


def _chunks(evidence: list[_Evidence]) -> Iterator[list[_Evidence]]:
    """The delivery's evidence, in model-sized batches, losing nothing.

    Order is preserved and every item appears in exactly one chunk, so the
    chunk boundaries are a function of the stored payload alone. That is what
    makes a redelivery land on the same boundaries as the first attempt, and
    therefore what lets each chunk's idempotency check answer for the same set
    of evidence ids twice.
    """
    for start in range(0, len(evidence), MAX_EVIDENCE_ITEMS):
        yield evidence[start : start + MAX_EVIDENCE_ITEMS]


def _read_evidence(delivery: WebhookDelivery) -> list[_Evidence]:
    """Everything in a payload a fact could legitimately cite. Evidence ids
    are stable across redelivery (commit SHA; PR/issue number), which is
    what makes the idempotency check possible. Read defensively."""
    payload = delivery.payload

    # Slack deliveries are shaped nothing like GitHub's, and the GitHub reader
    # would silently find no evidence in one — an ingested message that never
    # reaches a brief, with no error anywhere.
    if _text(payload.get("type")) in {"event_callback", "app_rate_limited"}:
        return _read_slack_evidence(delivery)
    # Google Chat deliveries are shaped like neither. The marker is written by
    # the receipt path (`gchat/events.stored_payload`) rather than inferred from
    # the resource, so a Chat payload cannot be mistaken for a GitHub one that
    # happens to have a `message` field.
    if _text(payload.get("type")) == "google_chat_event":
        return _read_gchat_evidence(delivery)
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
                text=_commit_text(commit, message),
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
        # `user.id` — GitHub's stable numeric id, never `user.login`, which the
        # account holder can change at any time. Commits below deliberately get
        # no actor: a push payload names the pusher, not the author of each
        # commit, and attributing somebody's commit to whoever pushed it is
        # exactly the wrong-person failure this step exists to prevent.
        author_id = _dig(item, "user", "id")
        actor = _actor(ConnectorProvider.GITHUB, str(author_id) if author_id else None)
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
                actor=actor,
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

    # Rebuilt only to stamp the repository, which is read once for the whole
    # payload. **Every other field must be carried across explicitly** — this
    # loop silently dropped the actor the first time it was added, and a dropped
    # actor is not a visible failure: it is a fact that quietly belongs to
    # nobody, which is exactly what an unattributable event looks like.
    return [
        _Evidence(
            evidence_id=item.evidence_id,
            text=_bounded(item.text, delivery_id=delivery.delivery_id),
            url=item.url,
            occurred_at=item.occurred_at,
            project=project,
            actor=item.actor,
        )
        for item in found
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
        dated.append(
            fact.model_copy(
                update={
                    "sources": sources,
                    "occurred_at": occurred,
                    "people": _people_with_actors(fact.people, cited),
                }
            )
        )
    return dated


def _people_with_actors(mentioned: list[str], cited: list[_Evidence]) -> list[str]:
    """The model's mentions, plus the provider accounts the payload actually named.

    **These two lists are different kinds of thing and are deliberately both
    kept.** What the model wrote is a claim about who a statement concerns, and a
    person reading their own record is entitled to see and correct it. The
    provider account is recorded provenance: it is who the provider said produced
    the evidence, it is not derived from any CAIRN table, and it is the only one
    of the two that may decide ownership — `resolve_mentions` sends it to the
    external-identity table and sends the model's names nowhere.

    Actors first, so the row that can resolve is written before the ones that
    cannot; order is otherwise immaterial and duplicates are dropped because
    `fact_people` is unique on `(fact_id, mention)`.
    """
    actors = [item.actor.mention for item in cited if item.actor is not None]
    seen: set[str] = set()
    ordered: list[str] = []
    for mention in [*actors, *mentioned]:
        if mention in seen:
            continue
        seen.add(mention)
        ordered.append(mention)
    return ordered


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
    model_name: str | None = None,
) -> JobHandler:
    """Build the handler, bound to the model adapters it will use.

    A factory (like `github/jobs.py`): the job runner's signature provides
    only a session, so anything else is closed over at wiring time.
    `providers` is injectable so a test can drive the real path with a
    scripted model.
    """
    resolved = providers or build_providers()
    # **Taken from the embedder, not defaulted.** This defaulted to the hashing
    # name whichever embedder it was handed, so selecting a real one wrote
    # OpenAI or Vertex vectors into the `hashing-v1` partition — two
    # incomparable geometries under one label, with nothing raised and nothing
    # logged. The only repair afterwards is to re-embed everything, because the
    # rows cannot be told apart.
    stored_under = model_name or resolved.embedder.model_name

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
            model_name=stored_under,
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

    batches = list(_chunks(evidence))
    if len(batches) > 1:
        # Said out loud, once, before any of it runs. The number that matters to
        # a reader is how many rounds this delivery takes, because that is the
        # difference between "the brief is thin" and "the brief is still being
        # written".
        await logger.ainfo(
            "understand.chunked",
            delivery_id=delivery.delivery_id,
            event_type=delivery.event_type,
            evidence=len(evidence),
            chunks=len(batches),
            chunk_size=MAX_EVIDENCE_ITEMS,
        )
        evidence_capped.add(1, safe({"outcome": "chunked"}))

    for number, batch in enumerate(batches, start=1):
        await _understand_chunk(
            session,
            delivery,
            batch,
            tenant_id=tenant_id,
            providers=providers,
            model_name=model_name,
            chunk=number,
            chunks=len(batches),
        )


async def _understand_chunk(
    session: AsyncSession,
    delivery: WebhookDelivery,
    evidence: list[_Evidence],
    *,
    tenant_id: uuid.UUID,
    providers: Providers,
    model_name: str,
    chunk: int,
    chunks: int,
) -> None:
    """One model round over one batch of a delivery's evidence.

    **Sequential in this job rather than one queued job per chunk.** The
    alternative was re-enqueuing, which is this repository's idiom elsewhere
    (`github/jobs.py` re-enqueues a backfill batch rather than looping) and
    keeps every job inside its five-minute lease. It was rejected here for one
    reason: it needs a queue threaded into this handler, and this handler is
    wired in two places without one. A wiring gap would then drop the tail of a
    push exactly as the old slice did — the same defect, arrived at by a longer
    route, and just as quiet.

    The cost is honest: a very large push holds a worker for several rounds, and
    if it outlives the lease another worker reclaims it and repeats work. That
    is waste, not corruption — every chunk is idempotent and Stage 3 merges
    repeats — and waste is recoverable in a way a missing fact is not.
    """
    index = {item.evidence_id: item for item in evidence}

    # Asked per chunk, not per delivery. Over the whole delivery this would
    # answer "no" while any chunk was outstanding and re-run every chunk on
    # every redelivery; over one chunk it skips exactly the work already done.
    if await _already_understood(session, tenant_id=tenant_id, evidence_ids=list(index)):
        await logger.adebug(
            "understand.already_applied",
            delivery_id=delivery.delivery_id,
            chunk=chunk,
            chunks=chunks,
        )
        return

    # Per-tenant ledger so one workspace's runaway backfill can't deny the model to others (spend.py).
    ledger = ledger_for(str(tenant_id))
    budgeted = BudgetedProvider(
        inner=providers.model,
        ledger=ledger,
        # The durable half: period counters shared by every replica, so a
        # restart cannot re-grant a ceiling. See pipeline/spend_store.py.
        store=process_spend_store(),
        tenant_id=tenant_id,
    )

    content = _render(evidence)

    classification = await classify(budgeted.for_stage("classify"), content=content)
    if not classification.event_class.should_extract:
        await logger.ainfo(
            "understand.skipped",
            delivery_id=delivery.delivery_id,
            event_class=classification.event_class.value,
            chunk=chunk,
            chunks=chunks,
        )
        return

    result = await extract(
        budgeted.for_stage("extract"),
        content=content,
        # Read from the evidence id rather than assumed. Hardcoding "github"
        # filed every Slack message as a commit, which is wrong on the Trust
        # page, wrong in a per-source opt-out, and wrong in the one place a
        # reader checks whether a statement came from somewhere they agreed to.
        known_evidence={item: _source_of(item) for item in index},
    )
    if not result.facts:
        await logger.ainfo(
            "understand.nothing_extracted",
            delivery_id=delivery.delivery_id,
            chunk=chunk,
            chunks=chunks,
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
        chunk=chunk,
        chunks=chunks,
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
    event, md/06 §6B.3).

    The envelope inherits the correlation id of the job that is publishing it —
    `run_job` binds it, `JobEnvelope` picks it up — so the webhook, the delivery
    job and this understanding job share one id all the way to the brief. It is
    inherited rather than passed because a parameter is a thing every future
    caller can forget, and the one that forgets is the chain that breaks."""
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
