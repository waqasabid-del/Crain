"""Correction: the record belongs to the person it describes.

Step 22's exit criterion is **a correction supersedes the fact and appears in the
golden dataset**, and both halves are tested end to end here — the second by
harvesting a real correction into a `GoldenCase` and loading it through the same
`load_dataset` the release gate uses.

The rest is mostly about what a correction must *not* do. It must not delete the
wrong statement, because that is the only labelled example of a real failure this
system will ever get for free, and because "why did it say that?" has to stay
answerable to the person who asked. It must not let one member rewrite another's
record. And a denial must actually stop the fact reaching tomorrow's brief —
which is the case the schema originally made impossible to express.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactOrigin, FactPerson, FactSource
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import tenant_session
from cairn_api.domain import Certainty
from cairn_api.evaluation.cases import FailureMode, GoldenDataset
from cairn_api.evaluation.corrections import SkipReason, harvest
from cairn_api.pipeline.corrections import (
    CorrectionError,
    CorrectionKind,
    apply_correction,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
async def workspace(platform: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A workspace, a signed-in user, and the person CAIRN has linked to them."""
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name="Acme", slug=f"corr-{suffix}")
    user = User(email=f"priya-{suffix}@example.com")
    platform.add_all([tenant, user])
    await platform.flush()
    platform.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.MEMBER))

    person = Person(tenant_id=tenant.id, display_name="Priya Nair", user_id=user.id)
    platform.add(person)
    await platform.commit()
    return tenant.id, user.id, person.id


async def add_fact(
    tenant_id: uuid.UUID,
    person_id: uuid.UUID | None,
    *,
    statement: str = "Priya shipped rate limiting to production.",
    quote: str | None = "Merged PR #482: add rate limiting to the public API",
) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        row = FactRow(
            tenant_id=tenant_id,
            kind="delivery",
            statement=statement,
            certainty=Certainty.OBSERVED.value,
            origin=FactOrigin.EXTRACTED,
            occurred_at=MONDAY,
            valid_from=MONDAY,
            sources=[
                FactSource(
                    tenant_id=tenant_id,
                    source="github",
                    evidence_id="ev-pr-482",
                    url="https://github.com/acme/api/pull/482",
                    quote=quote,
                )
            ],
            people=[FactPerson(tenant_id=tenant_id, person_id=person_id, mention="Priya Nair")],
        )
        session.add(row)
        await session.commit()
        return row.id


class TestACorrectionSupersedes:
    """The first half of the criterion."""

    async def test_a_rewording_supersedes_and_keeps_both(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            replacement = await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.REWORDED,
                user_id=user_id,
                statement="Priya reviewed the rate limiting change; Tom shipped it.",
            )
            await session.commit()
            assert replacement is not None
            replacement_id = replacement.id

        async with tenant_session(tenant_id) as session:
            original = await session.get(FactRow, fact_id)
            corrected = await session.get(FactRow, replacement_id)

            assert original is not None
            assert corrected is not None

            # The wrong statement is kept. It is the only labelled example of a
            # real failure this system gets for free, and deleting it makes
            # "why did it say that?" unanswerable to the person who asked.
            assert original.statement == "Priya shipped rate limiting to production."
            assert original.valid_until is not None
            assert original.superseded_by_id == corrected.id
            assert original.supersession_reason

            assert corrected.origin is FactOrigin.CORRECTION
            assert corrected.corrected_by_user_id == user_id
            # A person who was there is the strongest evidence this system holds.
            assert corrected.certainty == Certainty.VERIFIED.value
            # Provenance is inherited: the person re-read the same pull request
            # rather than inventing a claim, and a fact with no source cannot
            # exist.
            assert [source.evidence_id for source in corrected.sources] == ["ev-pr-482"]

    async def test_a_denial_stops_the_fact_reaching_tomorrows_brief(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """The case the schema originally made impossible.

        `ck_facts_supersession_is_complete` required a successor for any closed
        validity window, so "this did not happen" could only be expressed by
        inventing a replacement sentence nobody wrote or by leaving the denied
        fact valid and watching it reappear. The constraint was narrowed to
        permit a retirement *that names a person*.
        """
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            replacement = await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.DID_NOT_HAPPEN,
                user_id=user_id,
            )
            await session.commit()
            assert replacement is None

        async with tenant_session(tenant_id) as session:
            original = await session.get(FactRow, fact_id)
            assert original is not None

            assert original.valid_until is not None, "a denied fact is still current"
            assert original.superseded_by_id is None
            assert original.origin is FactOrigin.CORRECTION
            assert original.corrected_by_user_id == user_id

            # And it is genuinely out of the set synthesis reads.
            current = list(
                await session.scalars(select(FactRow).where(FactRow.valid_until.is_(None)))
            )
            assert fact_id not in {row.id for row in current}

    async def test_a_rewording_without_wording_is_refused(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            with pytest.raises(CorrectionError, match="corrected sentence"):
                await apply_correction(
                    session,
                    tenant_id=tenant_id,
                    fact_id=fact_id,
                    kind=CorrectionKind.REWORDED,
                    user_id=user_id,
                    statement="   ",
                )

    async def test_correcting_an_already_superseded_fact_is_refused(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """Two successors to one fact leaves two claimants to the same history."""
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.REWORDED,
                user_id=user_id,
                statement="Priya reviewed the change.",
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            with pytest.raises(CorrectionError, match="already been superseded"):
                await apply_correction(
                    session,
                    tenant_id=tenant_id,
                    fact_id=fact_id,
                    kind=CorrectionKind.DID_NOT_HAPPEN,
                    user_id=user_id,
                )

    async def test_a_fact_in_another_workspace_cannot_be_corrected(
        self, platform: AsyncSession, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(other.id) as session:
            with pytest.raises(CorrectionError, match="No such fact"):
                await apply_correction(
                    session,
                    tenant_id=other.id,
                    fact_id=fact_id,
                    kind=CorrectionKind.DID_NOT_HAPPEN,
                    user_id=user_id,
                )


class TestACorrectionBecomesEvaluationData:
    """The second half of the criterion — md/10 §2.1's "moat", made real."""

    async def test_a_rewording_becomes_a_golden_case_the_gate_can_load(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.WRONG_PERSON,
                user_id=user_id,
                statement="Tom shipped rate limiting to production.",
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            found = await harvest(session, tenant_id=tenant_id)

        assert len(found.cases) == 1
        [case] = found.cases

        # The evidence is the *source material*, not the sentence under test. A
        # case whose evidence is the claim would ask the pipeline to reproduce
        # an answer it was handed, and would pass forever.
        assert case.evidence[0].content == "Merged PR #482: add rate limiting to the public API"
        assert case.expected_claims[0].summary == "Tom shipped rate limiting to production."
        assert case.expected_claims[0].must_cite == [case.evidence[0].id]
        # Pre-classified into the taxonomy the failure report already uses.
        assert case.targets == [FailureMode.MISATTRIBUTION]
        assert "origin:correction" in case.tags
        # The rationale is what a reviewer reads before committing it, so it
        # carries both sentences rather than "a user corrected this".
        assert "CAIRN said" in case.rationale

        # And it is a case the release gate can actually load — the same
        # validation `load_dataset` applies to the committed files.
        dataset = GoldenDataset(version="0.2.0-corrections", cases=found.cases)
        assert len(dataset) == 1

    async def test_a_denial_becomes_an_abstention_case(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """The right behaviour was to say nothing.

        Abstention is a first-class outcome rather than an empty answer, and a
        dataset with no cases rewarding it trains the system to guess.
        """
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.DID_NOT_HAPPEN,
                user_id=user_id,
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            found = await harvest(session, tenant_id=tenant_id)

        [case] = found.cases
        assert case.expects_abstention is True
        assert case.expected_claims == []
        assert case.targets == [FailureMode.FABRICATION]

    async def test_a_wording_only_change_is_skipped_with_a_reason(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """A dataset of preference disagreements measures nothing.

        It would train the pipeline toward one person's writing style and call
        the result quality.
        """
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.REWORDED,
                user_id=user_id,
                # The same content words, reordered and repunctuated.
                statement="To production, Priya shipped rate limiting!",
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            found = await harvest(session, tenant_id=tenant_id)

        assert found.cases == []
        assert found.skipped[0].reason is SkipReason.WORDING_ONLY

    async def test_a_correction_with_no_retained_span_is_skipped_loudly(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """The concrete cost of `quote` being optional, reported not hidden.

        Without a span the only text available is the fact's own statement, and
        a case whose evidence is the sentence under test is circular. Several of
        these in one export means extraction is discarding spans — a defect
        upstream of anything the dataset can measure.
        """
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id, quote=None)

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.REWORDED,
                user_id=user_id,
                statement="Tom shipped it, not Priya.",
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            found = await harvest(session, tenant_id=tenant_id)

        assert found.cases == []
        assert found.skipped[0].reason is SkipReason.NO_EVIDENCE_TEXT

    async def test_corrections_do_not_cross_workspaces(
        self, platform: AsyncSession, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.WRONG_PERSON,
                user_id=user_id,
                statement="Tom shipped rate limiting to production.",
            )
            await session.commit()

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(other.id) as session:
            found = await harvest(session, tenant_id=other.id)

        assert found.cases == []
        assert found.skipped == []


class TestMyWeekIsOnlyMine:
    async def test_the_query_is_scoped_to_the_reader_not_filtered_afterwards(
        self, platform: AsyncSession, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """Scoping in the query means a bug shows *less*, not somebody else.

        Filtering the team's facts down to the reader in the interface is the
        version where one forgotten condition turns a trust product into a
        surveillance complaint.
        """
        tenant_id, _user_id, person_id = workspace

        colleague = Person(tenant_id=tenant_id, display_name="Tom Reilly")
        platform.add(colleague)
        await platform.commit()

        mine = await add_fact(tenant_id, person_id)
        theirs = await add_fact(tenant_id, colleague.id, statement="Tom reviewed the migration.")

        async with tenant_session(tenant_id) as session:
            rows = list(
                await session.scalars(
                    select(FactRow)
                    .join(FactPerson, FactPerson.fact_id == FactRow.id)
                    .where(
                        FactPerson.person_id == person_id,
                        FactRow.valid_until.is_(None),
                    )
                )
            )

        ids = {row.id for row in rows}
        assert mine in ids
        assert theirs not in ids

    async def test_a_correction_takes_effect_immediately(
        self, workspace: tuple[uuid.UUID, uuid.UUID, uuid.UUID]
    ) -> None:
        """A person who fixes something should see it fixed.

        Not see their correction queued behind a nightly job — which is the
        difference between a record they own and a request they filed.
        """
        tenant_id, user_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await apply_correction(
                session,
                tenant_id=tenant_id,
                fact_id=fact_id,
                kind=CorrectionKind.REWORDED,
                user_id=user_id,
                statement="Priya reviewed the rate limiting change.",
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            rows = list(
                await session.scalars(
                    select(FactRow)
                    .join(FactPerson, FactPerson.fact_id == FactRow.id)
                    .where(
                        FactPerson.person_id == person_id,
                        FactRow.valid_until.is_(None),
                    )
                )
            )

        statements = [row.statement for row in rows]
        assert statements == ["Priya reviewed the rate limiting change."]


def test_the_correction_window_is_seven_days() -> None:
    """ "My week" means a week.

    A month of it is a different question the reader did not ask, and a default
    that quietly widens is how a personal record becomes a performance history.
    """
    from cairn_api.api.routers.me import DEFAULT_DAYS

    assert timedelta(days=DEFAULT_DAYS) == timedelta(weeks=1)
