"""Stored transcripts becoming facts — the read that consent gates.

This closes the gap `gmeet_push.install` left on purpose. When that comment was
written, publishing work would have meant a broker payload carrying a transcript
resource name, and no reader existed to receive one. Both facts have changed:
the reader is this module, and it runs on the worker's maintenance loop beside
`retrieval.retrieve_pending_transcripts` — through a platform session, because
`google_meet_transcript_raw` grants the application role nothing at all. Nothing
here is ever handed to the job broker, so the property that comment protected —
no transcript identifier in any broker payload — holds structurally: there is no
payload anywhere.

**Consent gates the read, not just the fetch.** Reading stored ciphertext into
the pipeline is a *use* of the recording, so `meetings.guard.permit_collection`
is re-asked inside the same transaction that decrypts — the permit pattern, the
required-keyword shape, every time. A participant who withdrew between download
and understanding parks the artifact as ``REFUSED`` with
``CONSENT_NOT_CURRENT``: the state whose own docstring says "somebody exercised
a right", because that is what happened.

**Certainty is capped at `suggested` in code, after extraction.** md/03's ~30%
speaker-misattribution figure is why meeting-derived is the definition of the
Suggested tier; a prompt rule would make the cap a request the model may
decline, and this cap is a property of the row.

**Retention still wins.** An artifact past ``retention_expires_at`` or already
purged is skipped cleanly — reading past expiry would make understanding extend
a transcript's life, and the promise is the reverse. Facts already extracted
keep their citations after the purge: provenance stays, the raw text goes.

**Nothing about the content escapes.** No transcript text, speaker name or
fragment reaches a log, a span, a counter attribute or an error message.
Decryption happens here, inside the transaction, and the plaintext dies with the
local variable.

Cost, at Session 4's rates: transcripts split into ≤4,000-character parts on
line boundaries, then run through the same model rounds as every other source —
20 evidence items a round. A one-hour meeting (~50k characters) is ~13 parts:
one round, roughly the token cost of a large push (~30k tokens, about a cent on
gpt-4o-mini). A three-hour all-hands is ~2 rounds. Nothing is truncated; the
26-commit push taught that lesson once already.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn_api.db.gmeet_models import (
    GoogleMeetRefusalReason,
    GoogleMeetTranscriptArtifact,
    GoogleMeetTranscriptRaw,
    GoogleMeetTranscriptState,
)
from cairn_api.domain import Certainty
from cairn_api.gmeet.artifacts import open_content
from cairn_api.meetings.guard import CollectionRefusedError, permit_collection
from cairn_api.pipeline import graph, store
from cairn_api.pipeline.classify import classify
from cairn_api.pipeline.extract import extract
from cairn_api.pipeline.facts import Fact
from cairn_api.pipeline.jobs import (
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_ITEMS,
    Providers,
    build_providers,
)
from cairn_api.pipeline.spend import BudgetedProvider, ledger_for

logger = structlog.get_logger(__name__)

#: Transcripts read per maintenance pass. Model calls run on this loop, so the
#: batch is small on purpose: a backlog drains over hours rather than one pass
#: monopolising the worker the way a fairness-managed path never could.
UNDERSTAND_BATCH = 3

#: The source every part of a transcript cites. `sources.py` parses the prefix.
_SOURCE = "meeting"


@dataclass(slots=True)
class UnderstandingOutcome:
    """Counts only — nothing here may describe a meeting."""

    considered: int = 0
    understood: int = 0
    refused: int = 0
    skipped: int = 0


def evidence_parts(text: str, *, artifact_id: uuid.UUID) -> list[tuple[str, str]]:
    """Split a transcript into citable parts, losing nothing.

    Parts break on line boundaries where possible — a speaker turn cut
    mid-sentence reads as two half-quotes — and every character lands in exactly
    one part, in order. Ids are ``meeting:{artifact_id}#pN``: stable across
    re-reads (which is what makes the idempotency check answer twice), opaque to
    anybody outside this database, and parsed by `sources.py` as
    `Source.MEETING` — the value that was declared and never produced until now.
    """
    parts: list[tuple[str, str]] = []
    remaining = text
    number = 1
    while remaining:
        if len(remaining) <= MAX_EVIDENCE_CHARS:
            piece, remaining = remaining, ""
        else:
            window = remaining[: MAX_EVIDENCE_CHARS + 1]
            split = window.rfind("\n")
            if split <= 0:
                split = MAX_EVIDENCE_CHARS
            piece, remaining = remaining[:split], remaining[split:]
            if remaining.startswith("\n") and piece:
                piece, remaining = piece + "\n", remaining[1:]
        parts.append((f"meeting:{artifact_id}#p{number}", piece))
        number += 1
    return parts


async def understand_stored_transcripts(
    db: AsyncSession,
    *,
    providers: Providers | None = None,
    now: datetime | None = None,
    limit: int = UNDERSTAND_BATCH,
) -> UnderstandingOutcome:
    """Read every STORED transcript the gate still permits, once each.

    The session must be platform-side, as the maintenance loop's is; every
    query below carries the artifact's own ``tenant_id`` explicitly, exactly as
    `retrieval` does.
    """
    moment = now or datetime.now(UTC)
    resolved = providers or build_providers()
    outcome = UnderstandingOutcome()

    artifacts = list(
        await db.scalars(
            select(GoogleMeetTranscriptArtifact)
            .where(GoogleMeetTranscriptArtifact.state == GoogleMeetTranscriptState.STORED)
            .order_by(GoogleMeetTranscriptArtifact.created_at)
            .limit(limit)
        )
    )

    for artifact in artifacts:
        outcome.considered += 1

        # Retention wins, and understanding must not extend a transcript's
        # life: past expiry the raw bytes are the purge sweep's to delete,
        # never this module's to read — even when the sweep has not run yet.
        expired = (
            artifact.retention_expires_at is not None and artifact.retention_expires_at <= moment
        )
        raw = await db.scalar(
            select(GoogleMeetTranscriptRaw).where(
                GoogleMeetTranscriptRaw.tenant_id == artifact.tenant_id,
                GoogleMeetTranscriptRaw.artifact_id == artifact.id,
            )
        )
        if expired or artifact.raw_purged_at is not None or raw is None:
            outcome.skipped += 1
            await logger.ainfo(
                "gmeet.understanding_skipped",
                artifact_id=str(artifact.id),
                tenant_id=str(artifact.tenant_id),
                # A category, never a description.
                reason="retention_expired" if expired else "raw_unavailable",
            )
            continue

        # The read is a use of the recording, so the gate is re-asked here,
        # inside the transaction that decrypts — not remembered from the
        # announcement, not remembered from the download.
        try:
            await permit_collection(
                db, tenant_id=artifact.tenant_id, meeting_id=artifact.meeting_id, now=moment
            )
        except CollectionRefusedError:
            artifact.state = GoogleMeetTranscriptState.REFUSED
            artifact.refusal_reason = GoogleMeetRefusalReason.CONSENT_NOT_CURRENT
            artifact.state_changed_at = moment
            outcome.refused += 1
            await logger.ainfo(
                "gmeet.understanding_refused",
                artifact_id=str(artifact.id),
                tenant_id=str(artifact.tenant_id),
                reason=GoogleMeetRefusalReason.CONSENT_NOT_CURRENT.value,
            )
            continue

        text = open_content(raw.content_ciphertext).decode("utf-8", errors="replace")
        facts_written = await _understand_one(db, artifact, text, providers=resolved)

        artifact.state = GoogleMeetTranscriptState.UNDERSTOOD
        artifact.state_changed_at = moment
        outcome.understood += 1
        await logger.ainfo(
            "gmeet.understanding_applied",
            artifact_id=str(artifact.id),
            tenant_id=str(artifact.tenant_id),
            facts=facts_written,
        )

    return outcome


async def _understand_one(
    db: AsyncSession,
    artifact: GoogleMeetTranscriptArtifact,
    text: str,
    *,
    providers: Providers,
) -> int:
    """Stages 1-3 over one transcript's parts, in model-sized rounds."""
    parts = evidence_parts(text, artifact_id=artifact.id)
    ledger = ledger_for(str(artifact.tenant_id))
    budgeted = BudgetedProvider(inner=providers.model, ledger=ledger)
    written = 0

    for start in range(0, len(parts), MAX_EVIDENCE_ITEMS):
        batch = parts[start : start + MAX_EVIDENCE_ITEMS]
        content = "\n".join(f"[{eid}] ({_SOURCE}) {part}" for eid, part in batch)

        classification = await classify(budgeted.for_stage("classify"), content=content)
        if not classification.event_class.should_extract:
            continue

        result = await extract(
            budgeted.for_stage("extract"),
            content=content,
            known_evidence={eid: _SOURCE for eid, _ in batch},
        )
        if not result.facts:
            continue

        capped = [_suggested(fact, artifact) for fact in result.facts]
        plan = await store.apply(db, tenant_id=artifact.tenant_id, incoming=capped)
        await db.flush()
        await store.attach_people_bulk(
            db,
            tenant_id=artifact.tenant_id,
            fact_ids=[decision.merged_into or decision.fact.id for decision in plan.decisions],
        )
        written += len(plan.decisions)

    if written:
        await graph.build(
            db,
            tenant_id=artifact.tenant_id,
            embedder=providers.embedder,
            model_name=providers.embedder.model_name,
        )
    return written


def _suggested(fact: Fact, artifact: GoogleMeetTranscriptArtifact) -> Fact:
    """The certainty cap, and the provenance date.

    Enforced here rather than asked of the prompt: whatever the extractor
    claimed, a meeting-derived fact is `suggested` — md/03's ~30% speaker
    misattribution is the definition of the tier, not a tuning choice. The
    fact is dated from the meeting's own timeline, never from now.
    """
    return fact.model_copy(
        update={
            "certainty": Certainty.SUGGESTED,
            "occurred_at": artifact.generated_at or artifact.announced_at,
        }
    )
