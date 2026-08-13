"""ActivityEvent schema tests.

This schema is the narrowest waist in the system — four producers above it, one
Understanding layer below — so a defect here reaches everything.

The tests fall into three groups: that a well-formed event is accepted, that a
malformed one is rejected *with a message that explains why*, and that the
generated TypeScript has not drifted from the Python definition.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cairn_api.events import ActivityEvent, Certainty, event_key
from cairn_api.events.export_schema import SCHEMA_PATH, build_schema
from pydantic import ValidationError

REPO_ROOT = Path(__file__).parents[3]


def make_event(**overrides: Any) -> dict[str, Any]:
    """A minimal valid event, with overrides for the field under test."""
    base: dict[str, Any] = {
        "id": "delivery-abc123",
        "source": "/github/12345",
        "type": "ai.cairn.github.pull_request.merged.v1",
        "time": datetime(2026, 8, 14, 9, 30, tzinfo=UTC),
        "tenantid": uuid.uuid4(),
        "data": {
            "actor": {"raw_identity": "ali@acme.test"},
            "activity": {
                "category": "code",
                "action": "merged",
                "summary": "Merged PR #482: refactor auth token handling",
            },
            "provenance": {
                "source_url": "https://github.com/acme/api/pull/482",
                "certainty": "verified",
            },
        },
    }
    base.update(overrides)
    return base


class TestValidEvents:
    def test_accepts_a_minimal_well_formed_event(self) -> None:
        event = ActivityEvent(**make_event())
        assert event.specversion == "1.0"
        assert event.data.activity.action == "merged"

    def test_defaults_ingestedat_to_now(self) -> None:
        before = datetime.now(UTC)
        event = ActivityEvent(**make_event())
        assert before <= event.ingestedat <= datetime.now(UTC) + timedelta(seconds=1)

    def test_time_and_ingestedat_are_independent(self) -> None:
        """Backfill imports 90 days of history in minutes.

        If these were conflated, a brief would claim today's work that actually
        happened in March (md/12 §3.2).
        """
        happened = datetime(2026, 5, 1, tzinfo=UTC)
        event = ActivityEvent(**make_event(time=happened))
        assert event.time == happened
        assert event.ingestedat > happened

    def test_content_may_be_absent(self) -> None:
        """Missing content is normal, not degraded.

        Raw diffs stay out of the pipeline by default and non-work chat is
        excluded entirely, so most events legitimately carry no body.
        """
        event = ActivityEvent(**make_event())
        assert event.data.content.text is None
        assert event.data.content.metadata == {}

    def test_co_actors_are_first_class(self) -> None:
        # Squash merges erase collaborative work unless co-authorship is modelled.
        others = [uuid.uuid4(), uuid.uuid4()]
        payload = make_event()
        payload["data"]["actor"]["co_actors"] = others
        event = ActivityEvent(**payload)
        assert event.data.actor.co_actors == others

    def test_event_key_is_source_and_id(self) -> None:
        # The idempotency key for redelivery — the same delivery must upsert.
        event = ActivityEvent(**make_event())
        assert event_key(event) == ("/github/12345", "delivery-abc123")


class TestRejectedEvents:
    """Invalid events must fail with a message that explains the problem."""

    def test_requires_a_tenant(self) -> None:
        payload = make_event()
        del payload["tenantid"]
        with pytest.raises(ValidationError, match="tenantid"):
            ActivityEvent(**payload)

    def test_rejects_the_nil_tenant(self) -> None:
        with pytest.raises(ValidationError, match="not the nil UUID"):
            ActivityEvent(**make_event(tenantid=uuid.UUID(int=0)))

    def test_rejects_a_naive_timestamp(self) -> None:
        # A wall-clock reading with no offset silently misorders activity across
        # regions and daylight-saving boundaries.
        with pytest.raises(ValidationError, match="timezone-aware"):
            ActivityEvent(**make_event(time=datetime(2026, 8, 14, 9, 30)))

    def test_rejects_an_unversioned_type(self) -> None:
        # The version lives in the type so a breaking change produces a new type
        # rather than silently altering an existing one.
        with pytest.raises(ValidationError, match="pattern"):
            ActivityEvent(**make_event(type="ai.cairn.github.pull_request.merged"))

    def test_rejects_a_foreign_type_namespace(self) -> None:
        with pytest.raises(ValidationError, match="pattern"):
            ActivityEvent(**make_event(type="com.example.thing.happened.v1"))

    def test_rejects_unknown_fields(self) -> None:
        # A typo in a field name would otherwise be silently discarded along
        # with whatever it was meant to carry.
        with pytest.raises(ValidationError):
            ActivityEvent(**make_event(tenent_id=uuid.uuid4()))

    def test_rejects_an_empty_summary(self) -> None:
        payload = make_event()
        payload["data"]["activity"]["summary"] = ""
        with pytest.raises(ValidationError):
            ActivityEvent(**payload)

    @pytest.mark.parametrize("certainty", ["observed", "suggested"])
    def test_uncertain_claims_require_a_verifiable_source(self, certainty: str) -> None:
        """A hedged claim the reader cannot check is worse than no claim.

        Certainty tiers only earn trust if verification is one click away
        (md/03 §6). Surfacing "it sounded like Ali agreed" with nothing to open
        asks the user to accept an unreliable statement on faith.
        """
        payload = make_event()
        payload["data"]["provenance"] = {"certainty": certainty}
        with pytest.raises(ValidationError, match="requires a source_url"):
            ActivityEvent(**payload)

    def test_verified_claims_may_omit_a_source(self) -> None:
        # A verified claim comes from an unambiguous source by definition.
        payload = make_event()
        payload["data"]["provenance"] = {"certainty": "verified"}
        event = ActivityEvent(**payload)
        assert event.data.provenance.certainty is Certainty.VERIFIED

    def test_suggested_claim_with_a_transcript_reference_is_accepted(self) -> None:
        payload = make_event()
        payload["data"]["provenance"] = {
            "certainty": "suggested",
            "source_timestamp_ref": "00:14:32",
        }
        event = ActivityEvent(**payload)
        assert event.data.provenance.source_timestamp_ref == "00:14:32"


class TestCertainty:
    def test_has_exactly_three_tiers(self) -> None:
        assert len(Certainty) == 3

    def test_is_categorical_never_numeric(self) -> None:
        """Guards md/05 §A.2.1 — no confidence percentage may reach the interface."""
        for tier in Certainty:
            with pytest.raises(ValueError, match="could not convert"):
                float(tier.value)


class TestGeneratedArtefacts:
    """The Python model is the source of truth; drift must fail CI."""

    def test_checked_in_schema_matches_the_model(self) -> None:
        on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert on_disk == build_schema(), (
            "The committed JSON Schema is out of date. Run `make schema`."
        )

    @pytest.mark.slow
    def test_generated_typescript_matches_the_schema(self) -> None:
        """Regenerate and compare.

        Without this, a Python model change would leave the frontend types
        describing an event shape the backend no longer produces — a
        disagreement that type-checks cleanly on both sides.
        """
        generated = REPO_ROOT / "packages" / "types" / "src" / "generated" / "activity-event.ts"
        before = generated.read_text(encoding="utf-8")

        # pnpm resolves through a shim on Windows. Locating the executable
        # explicitly avoids shell=True, which would add a real injection surface
        # for the sake of convenience.
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            pytest.skip("pnpm not on PATH")

        result = subprocess.run(  # noqa: S603
            [pnpm, "--filter", "@cairn/types", "generate"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"Type generation failed:\n{result.stderr}"

        assert generated.read_text(encoding="utf-8") == before, (
            "Generated TypeScript types are out of date. Run `make schema`."
        )
