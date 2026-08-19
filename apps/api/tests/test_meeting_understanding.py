"""Meeting transcripts becoming facts — the deliberate gap, closed deliberately.

Transcripts were announced, downloaded, encrypted, stored and purged, and never
became facts: `pipeline/jobs.py::_read_evidence` had no meeting branch, and
`gmeet_push.install()` mounted no job type on purpose, because a queued job
would have carried a transcript resource name in its payload.

This suite proves the closure honours every reason the gap existed:

- Understanding runs on the maintenance loop beside retrieval, through a
  platform session — the raw table grants the application role nothing, and
  **nothing is ever queued**, so the property `gmeet_push` protected (no
  artifact identifier in any queue payload) holds because there is no payload.
- Consent gates the READ. The permit is re-acquired inside the transaction that
  decrypts, so a participant who withdrew between download and understanding
  causes a refusal — the most important test in this file.
- Certainty is capped at `suggested` in code, after extraction, whatever the
  extractor claimed. md/03's ~30% speaker-misattribution figure is why
  meeting-derived is the *definition* of the Suggested tier.
- Retention still wins: expired or purged is a clean refusal, and facts already
  extracted keep their citations after the raw text goes.
- Long transcripts chunk rather than truncate — a one-hour meeting must not
  silently lose its second half, which is the same defect the GitHub cap had.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
import structlog.testing
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.gmeet_models import (
    GoogleMeetRefusalReason,
    GoogleMeetTranscriptArtifact,
    GoogleMeetTranscriptState,
)
from cairn_api.domain import Certainty
from cairn_api.gmeet import retrieval, understanding
from cairn_api.pipeline.embeddings import HashingEmbedder
from cairn_api.pipeline.jobs import MAX_EVIDENCE_CHARS, Providers
from cairn_api.pipeline.provider import ScriptedProvider, instructed
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_gmeet_transcripts import (
    NOW,
    Scenario,
    a_client,
    a_scenario,
    announce,
    artifact_of,
    raw_of,
    withdraw,
)

pytestmark = pytest.mark.integration

#: What the fake Drive serves in these tests, diarised the way Meet exports are.
DIARISED = (
    b"Ada: The launch moves to Thursday, decided.\n"
    b"Speaker 2: someone should probably tell support.\n"
)


def scripted(*, certainty: str = "verified") -> Providers:
    """A provider whose extractor names the diarised speaker and — the point —
    claims a certainty the pipeline must refuse to honour."""
    provider = ScriptedProvider(default='{"class": "substantive"}')
    provider.when(
        instructed("Extract the facts"),
        lambda request: (
            '{"facts": [{"kind": "decision", '
            '"statement": "The launch moves to Thursday.", '
            f'"evidence_ids": ["{_first_evidence_id(request.untrusted_data)}"], '
            f'"people": ["Ada"], "certainty": "{certainty}"}}]}}'
        ),
    )
    return Providers(model=provider, embedder=HashingEmbedder(), live=False)


def _first_evidence_id(untrusted: str) -> str:
    """The first `[meeting:...]` id in the rendered block."""
    for line in untrusted.splitlines():
        if line.startswith("[meeting:"):
            return line[1 : line.index("]")]
    return "meeting:none"


async def stored_scenario(
    platform: AsyncSession, *, content: bytes = DIARISED
) -> tuple[Scenario, GoogleMeetTranscriptArtifact]:
    """A consented meeting whose transcript is retrieved and STORED."""
    from test_gmeet_transcripts import FakeArtifacts

    scenario = await a_scenario(platform)
    await announce(platform, scenario)
    await retrieval.retrieve_pending_transcripts(
        platform, client=a_client(files=FakeArtifacts(content=content)), now=NOW
    )
    await platform.commit()
    artifact = await artifact_of(platform, scenario)
    assert artifact is not None and artifact.state is GoogleMeetTranscriptState.STORED
    return scenario, artifact


async def facts_for(platform: AsyncSession, tenant_id: uuid.UUID) -> list[FactRow]:
    return list(await platform.scalars(select(FactRow).where(FactRow.tenant_id == tenant_id)))


class TestAConsentedTranscriptBecomesSuggestedFacts:
    async def test_the_stored_transcript_produces_a_cited_meeting_fact(
        self, platform: AsyncSession
    ) -> None:
        scenario, artifact = await stored_scenario(platform)

        outcome = await understanding.understand_stored_transcripts(
            platform, providers=scripted(), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()

        assert outcome.understood == 1
        facts = await facts_for(platform, scenario.tenant_id)
        assert facts, "the transcript produced no fact"
        [fact] = facts
        assert fact.sources[0].source == "meeting"
        assert fact.sources[0].evidence_id.startswith(f"meeting:{artifact.id}#p")

    async def test_certainty_is_capped_at_suggested_in_code(self, platform: AsyncSession) -> None:
        """**The extractor said `verified`. The row must say `suggested`.**

        ~30% speaker misattribution in multi-person calls is why meeting-derived
        is the definition of the Suggested tier (md/03). A prompt rule would
        make the cap a request; this test makes it a property.
        """
        scenario, _ = await stored_scenario(platform)

        await understanding.understand_stored_transcripts(
            platform,
            tenant_id=scenario.tenant_id,
            providers=scripted(certainty="verified"),
            now=NOW,
        )
        await platform.commit()

        [fact] = await facts_for(platform, scenario.tenant_id)
        assert Certainty(fact.certainty) is Certainty.SUGGESTED

    async def test_the_artifact_is_marked_understood_and_not_reread(
        self, platform: AsyncSession
    ) -> None:
        """A second pass must not spend a second model run on the same bytes."""
        scenario, _ = await stored_scenario(platform)

        first = await understanding.understand_stored_transcripts(
            platform, providers=scripted(), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()
        second = await understanding.understand_stored_transcripts(
            platform, providers=scripted(), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()

        assert (first.understood, second.understood) == (1, 0)
        artifact = await artifact_of(platform, scenario)
        assert artifact is not None
        assert artifact.state is GoogleMeetTranscriptState.UNDERSTOOD
        assert len(await facts_for(platform, scenario.tenant_id)) == 1


class TestConsentGatesTheRead:
    async def test_a_withdrawal_between_download_and_understanding_refuses(
        self, platform: AsyncSession
    ) -> None:
        """**The most important test in this file.**

        The transcript is already stored — collected under unanimous consent
        that was real at the time. One participant withdraws afterwards. Reading
        the stored bytes into the pipeline is a *use* of the recording, so the
        permit is re-asked inside the reading transaction and the answer is no:
        no fact, no model call recorded against the meeting, and the artifact
        parked as REFUSED — the state whose docstring says "somebody exercised a
        right", because that is exactly what happened.
        """
        scenario, _ = await stored_scenario(platform)
        await withdraw(platform, scenario)

        outcome = await understanding.understand_stored_transcripts(
            platform, providers=scripted(), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()

        assert outcome.refused == 1
        assert outcome.understood == 0
        assert await facts_for(platform, scenario.tenant_id) == []
        artifact = await artifact_of(platform, scenario)
        assert artifact is not None
        assert artifact.state is GoogleMeetTranscriptState.REFUSED
        assert artifact.refusal_reason is GoogleMeetRefusalReason.CONSENT_NOT_CURRENT


class TestRetentionStillWins:
    async def test_a_purged_transcript_is_a_clean_refusal_not_an_error(
        self, platform: AsyncSession
    ) -> None:
        scenario, artifact = await stored_scenario(platform)
        # Retention closes and the sweep runs before understanding ever did.
        artifact.retention_expires_at = NOW - timedelta(days=1)
        await platform.commit()
        await retrieval.purge_expired_transcripts(platform, now=NOW)
        await platform.commit()
        assert await raw_of(platform, scenario) is None

        outcome = await understanding.understand_stored_transcripts(
            platform, providers=scripted(), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()

        assert outcome.understood == 0
        assert outcome.skipped >= 1
        assert await facts_for(platform, scenario.tenant_id) == []

    async def test_facts_survive_the_purge_with_citations_intact(
        self, platform: AsyncSession
    ) -> None:
        """Provenance keeps the citation; the raw text goes."""
        scenario, artifact = await stored_scenario(platform)
        await understanding.understand_stored_transcripts(
            platform, providers=scripted(), tenant_id=scenario.tenant_id, now=NOW
        )
        await platform.commit()

        artifact.retention_expires_at = NOW - timedelta(days=1)
        await platform.commit()
        await retrieval.purge_expired_transcripts(platform, now=NOW)
        await platform.commit()

        assert await raw_of(platform, scenario) is None
        [fact] = await facts_for(platform, scenario.tenant_id)
        assert fact.sources[0].evidence_id.startswith("meeting:")


class TestLongTranscriptsChunkRatherThanTruncate:
    async def test_every_part_of_a_long_transcript_is_citable(self, platform: AsyncSession) -> None:
        """A one-hour meeting is ~50k characters. The old evidence cap would
        have kept the first 4,000 and dropped the rest with nothing logged —
        the same silent loss the 26-commit push had, on the most sensitive
        content the product holds."""
        line = b"Ada: We agreed the retention sweep ships this week.\n"
        long_transcript = line * 1000  # ~52k chars
        _scenario, artifact = await stored_scenario(platform, content=long_transcript)

        items = understanding.evidence_parts(long_transcript.decode(), artifact_id=artifact.id)

        assert len(items) > 1, "a long transcript must split, not truncate"
        assert all(len(text) <= MAX_EVIDENCE_CHARS for _, text in items)
        rebuilt = "".join(text for _, text in items)
        assert rebuilt == long_transcript.decode(), "no character may be lost"
        assert [eid for eid, _ in items] == [
            f"meeting:{artifact.id}#p{n}" for n in range(1, len(items) + 1)
        ]

    def test_parts_split_on_line_boundaries_where_possible(self) -> None:
        """A speaker turn cut mid-sentence reads as two half-quotes."""
        artifact_id = uuid.uuid4()
        text = ("Ada: yes.\n" * 900) + "Ben: final line without newline"
        items = understanding.evidence_parts(text, artifact_id=artifact_id)
        for _, part in items[:-1]:
            assert part.endswith("\n"), "splits should land on line boundaries"


class TestNoContentEscapes:
    async def test_no_log_line_carries_transcript_text(self, platform: AsyncSession) -> None:
        """The no-body-logging discipline, applied to the most sensitive text
        this product will ever hold."""
        _scenario, _ = await stored_scenario(platform)

        with structlog.testing.capture_logs() as captured:
            await understanding.understand_stored_transcripts(
                platform, providers=scripted(), tenant_id=_scenario.tenant_id, now=NOW
            )
        await platform.commit()

        rendered = repr(captured)
        assert "launch moves to Thursday" not in rendered
        assert "Speaker 2" not in rendered
        assert "Ada" not in rendered

    def test_nothing_in_the_module_publishes_to_a_queue(self) -> None:
        """The property `gmeet_push` protected, preserved structurally: there is
        no queue payload because there is no queue. If somebody adds one, this
        fails and sends them to the docstrings that explain the constraint."""
        import inspect

        source = inspect.getsource(understanding)
        assert "queue" not in source.lower().replace("no queue", "").replace("never queued", ""), (
            "meeting understanding must not touch a queue; see gmeet_push.install"
        )
