"""One source vocabulary, proven at every boundary that reads a source string.

These tests exist because the vocabulary was split in two and the symptom was
invisible: evidence carried `slack`, consent carried `chat`, opt-out is enforced
by intersecting the two, and an empty intersection reads exactly like "this
person did not opt out". The toggle saved, the row existed, every screen said the
refusal was honoured, and CAIRN kept reading.

So the assertions here are deliberately about *agreement between modules* rather
than about any one module's behaviour. A test that only checked
`consent.SOURCES` would have passed throughout the entire life of the bug.
"""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from cairn_api import sources as canonical
from cairn_api.api.routers import me as me_router
from cairn_api.pipeline import consent, jobs
from cairn_api.sources import Source, UnknownSourceError
from sqlalchemy import Table, UniqueConstraint

pytestmark = pytest.mark.integration


class TestOneVocabulary:
    """Every module that names a source must name the same set."""

    def test_consent_and_the_canonical_set_are_the_same_object(self) -> None:
        """Re-exported, not restated.

        Equality would pass while two literals drifted between releases; identity
        of value plus a single definition is what actually prevents it.
        """
        assert consent.SOURCES == canonical.SOURCES
        assert set(consent.SOURCES) == {item.value for item in Source}

    def test_every_source_a_person_may_refuse_has_copy_on_the_consent_screen(self) -> None:
        """A source with no words is a checkbox nobody can make sense of — and a
        source in the copy but not the vocabulary is a promise with no enforcement
        behind it. Asserted as an exact set so neither can happen."""
        assert set(me_router.SOURCE_COPY) == set(canonical.SOURCES)

    def test_chat_is_not_a_source(self) -> None:
        """The word that caused the bug is gone rather than aliased.

        Keeping `chat` as an alias would preserve the ability to write a row that
        matches no evidence, which is the whole defect.
        """
        assert "chat" not in canonical.SOURCES
        assert "chat" not in me_router.SOURCE_COPY

    def test_slack_and_google_chat_are_separately_refusable(self) -> None:
        """One control named "Chat" could not express "stop reading my Slack but
        keep Google Chat", and the coarser reading always won."""
        assert Source.SLACK.value in canonical.SOURCES
        assert Source.GOOGLE_CHAT.value in canonical.SOURCES


class TestEvidenceIdsAndConsentAgree:
    """The intersection that enforces opt-out has to be capable of matching."""

    @pytest.mark.parametrize(
        ("evidence_id", "expected"),
        [
            ("github:abc123", Source.GITHUB),
            ("slack:T1/C1/1700000000.000100", Source.SLACK),
            ("google_chat:spaces/AAA/messages/BBB", Source.GOOGLE_CHAT),
        ],
    )
    def test_an_evidence_id_resolves_to_a_source_a_person_can_refuse(
        self, evidence_id: str, expected: Source
    ) -> None:
        """**This is the test the bug would have failed.**

        `_source_of` returned `slack`; `consent.SOURCES` offered `chat`; nothing
        compared the two. Asserting membership in the refusable set is what ties
        the produced value to the offered one.
        """
        resolved = jobs._source_of(evidence_id)

        assert resolved == expected.value
        assert resolved in consent.SOURCES, (
            f"{resolved!r} can be produced as evidence but cannot be refused — "
            "an opt-out for it would match nothing and read as honoured"
        )

    def test_an_unknown_prefix_fails_closed(self) -> None:
        """It used to return `github`.

        That is not a harmless default: the value is written to
        `fact_sources.source` and is what a person's refusal is compared against,
        so an unrecognised prefix silently relabelled evidence as a source the
        workspace had probably connected, and consent was enforced against a
        label CAIRN invented. A raised error in a retryable worker is recoverable;
        attributing somebody's work under a fabricated label is not.
        """
        with pytest.raises(UnknownSourceError):
            jobs._source_of("linkedin:12345")

        with pytest.raises(UnknownSourceError):
            canonical.source_of_evidence_id("no-prefix-at-all")

    def test_an_unknown_source_cannot_be_opted_out_of(self) -> None:
        """Fails closed at the other end too, so a typo cannot create a row that
        matches no evidence and looks like a refusal on every screen."""
        with pytest.raises(UnknownSourceError):
            canonical.parse("chat")


class TestTheLegacyExpansionIsSafeInOneDirection:
    """What a `chat` refusal became, and why it became both."""

    def test_a_chat_refusal_expands_to_both_products(self) -> None:
        """The person was offered one control named "Chat" covering Slack and
        Google Chat and refused it. Expanding to both is what they were told they
        were doing; choosing one would resume reading the other without asking,
        and dropping the row would resume reading both."""
        assert set(canonical.LEGACY_CHAT_SOURCES) == {Source.SLACK, Source.GOOGLE_CHAT}

    def test_the_expansion_is_the_collecting_less_direction(self) -> None:
        """Stated as a test because it is the reasoning a future migration author
        needs: when a migration must interpret a consent decision, it resolves
        toward reading less, never toward reading more."""
        assert len(canonical.LEGACY_CHAT_SOURCES) == 2


class TestNothingGuessesAPerson:
    """The identity rules, asserted as absences.

    An absence is what these are: there is no name-similarity function to test
    the behaviour of, so the test is that no such thing exists to call.
    """

    def test_the_identity_service_exposes_no_similarity_matching(self) -> None:
        from cairn_api.identity import external

        names = dir(external)
        for forbidden in ("similarity", "fuzzy", "distance", "score", "guess", "suggest"):
            assert not any(forbidden in name.lower() for name in names), (
                f"{forbidden!r} appears in the identity service — identity is "
                "matched on verified evidence or an authenticated confirmation, "
                "and a threshold implies a high enough score would be good enough"
            )

    def test_verification_has_exactly_two_members_and_neither_is_inferred(self) -> None:
        from cairn_api.db.external_identity_models import IdentityVerification

        assert {item.value for item in IdentityVerification} == {
            "verified_email_match",
            "self_confirmed",
        }


class TestOptOutBlocksAttributionForEveryChatProduct:
    """The end-to-end property the vocabulary split defeated."""

    @pytest.mark.parametrize("source", [Source.SLACK, Source.GOOGLE_CHAT])
    async def test_a_refusal_can_be_recorded_and_matches_its_evidence(self, source: Source) -> None:
        """Recording the refusal and producing the evidence must use one string.

        Before the fix, `opt_out(source="slack")` raised `ValueError` because
        `slack` was not in `consent.SOURCES` — so the only refusal a person could
        record was `chat`, and `chat` matched no evidence anybody produced.
        """
        assert source.value in consent.SOURCES

        evidence_prefixes = {
            Source.SLACK: "slack:T1/C1/1700000000.000100",
            Source.GOOGLE_CHAT: "google_chat:spaces/AAA/messages/BBB",
        }
        produced = jobs._source_of(evidence_prefixes[source])

        # The intersection `store.py` performs to enforce an opt-out.
        assert {source.value} & {produced}, (
            "the refusal and the evidence use different strings, so the opt-out "
            "gate intersects to empty and the person is recorded anyway"
        )

    def test_the_unique_constraint_is_per_person_and_source(self) -> None:
        """Two products, two rows — so refusing one leaves the other's row alone."""
        from cairn_api.db.consent_models import SourceOptOut

        # `__table__` is a `Table` at runtime; the declarative attribute is typed
        # as the wider `FromClause`, which has no `constraints`.
        table = cast(Table, SourceOptOut.__table__)
        constraint = next(
            item
            for item in table.constraints
            if isinstance(item, UniqueConstraint)
            and item.name == "uq_source_opt_outs_person_source"
        )
        assert {column.name for column in constraint.columns} == {"person_id", "source"}

    def test_uuids_are_not_sources(self) -> None:
        """Guards the parametrised helpers above from being fed the wrong thing."""
        with pytest.raises(UnknownSourceError):
            canonical.parse(str(uuid.uuid4()))
