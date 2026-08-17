"""Per-source opt-out — the half of Step 23 that has to be real.

md/11 §7 makes the opt-out rate the product's trust barometer, and md/13 makes it
a phase gate: above 10% and the plan pauses. A number like that only means
something if the control behind it works, so these tests are about what an
opt-out actually does rather than about whether the row is written.

The properties worth stating up front, because they are choices rather than
consequences:

- **It is retroactive.** The promise is "you control this", not "you control
  this from now on".
- **It removes the attribution, not the work.** The pull request still exists and
  the team's history is intact; CAIRN simply stops saying it was them.
- **Opting back in restores nothing.** Re-linking would mean CAIRN had kept a
  record of what it was told not to attribute.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource
from cairn_api.db.identity_models import Identity, IdentityKind, Person
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.pipeline import consent, store
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
async def workspace(platform: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    tenant = Tenant(name="Acme", slug=f"consent-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.flush()

    person = Person(tenant_id=tenant.id, display_name="Priya Nair")
    platform.add(person)
    await platform.flush()
    platform.add(
        Identity(
            tenant_id=tenant.id,
            person_id=person.id,
            kind=IdentityKind.GITHUB_LOGIN,
            value="priyanair",
        )
    )
    await platform.commit()
    return tenant.id, person.id


async def add_fact(
    tenant_id: uuid.UUID,
    person_id: uuid.UUID | None,
    *,
    source: str = "github",
    statement: str = "Priya shipped rate limiting.",
    second_source: str | None = None,
) -> uuid.UUID:
    sources = [
        FactSource(tenant_id=tenant_id, source=source, evidence_id=f"ev-{uuid.uuid4().hex[:8]}")
    ]
    if second_source is not None:
        sources.append(
            FactSource(
                tenant_id=tenant_id,
                source=second_source,
                evidence_id=f"ev-{uuid.uuid4().hex[:8]}",
            )
        )

    async with tenant_session(tenant_id) as session:
        row = FactRow(
            tenant_id=tenant_id,
            kind="delivery",
            statement=statement,
            certainty="verified",
            occurred_at=MONDAY,
            valid_from=MONDAY,
            sources=sources,
            people=[FactPerson(tenant_id=tenant_id, person_id=person_id, mention="Priya Nair")],
        )
        session.add(row)
        await session.commit()
        return row.id


async def attributions(tenant_id: uuid.UUID, person_id: uuid.UUID) -> set[uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        rows = await session.scalars(
            select(FactPerson.fact_id).where(FactPerson.person_id == person_id)
        )
        return set(rows)


class TestOptOutIsPerSource:
    """The exit criterion: "opt-out works per source"."""

    async def test_opting_out_of_one_source_leaves_the_others_alone(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, person_id = workspace
        from_github = await add_fact(tenant_id, person_id, source="github")
        from_chat = await add_fact(
            tenant_id, person_id, source="chat", statement="Priya raised the staging blocker."
        )

        async with tenant_session(tenant_id) as session:
            unlinked = await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await session.commit()

        assert unlinked == 1
        remaining = await attributions(tenant_id, person_id)
        assert from_github not in remaining
        assert from_chat in remaining

    async def test_the_work_survives_only_the_attribution_goes(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Deleting the fact would hand one person the power to erase shared history.

        The precedent is already in the system: bot activity is retained as
        repository context and excluded from human attribution (md/01 §5.2).
        """
        tenant_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            fact = await session.get(FactRow, fact_id)
            assert fact is not None
            assert fact.statement == "Priya shipped rate limiting."
            assert fact.valid_until is None, "the team's history was retired, not just unlinked"

            # The mention survives with no person behind it — the same shape an
            # unresolved mention already has, which is the honest description of
            # what CAIRN is now allowed to know.
            [link] = fact.people
            assert link.mention == "Priya Nair"
            assert link.person_id is None

    async def test_a_fact_from_two_sources_is_unlinked_if_either_is_opted_out(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Corroboration must not keep an attribution alive.

        A decision mentioned in a meeting *and* a chat thread is one fact citing
        both. Requiring every source to match would let one mention from a
        source somebody did not opt out of preserve the attribution — which is
        not what they were promised.
        """
        tenant_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id, source="meeting", second_source="chat")

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="meeting"
            )
            await session.commit()

        assert fact_id not in await attributions(tenant_id, person_id)

    async def test_opting_out_twice_is_opting_out_once(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A double-tapped toggle must not read as two people losing trust.

        The opt-out rate is the barometer md/11 §7 watches; counting one
        person's second tap would move the number that pauses the roadmap.
        """
        tenant_id, person_id = workspace
        await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            rows = list(await session.scalars(select(SourceOptOut)))
        assert len(rows) == 1

    async def test_an_unknown_source_is_refused(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, person_id = workspace
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ValueError, match="Unknown source"):
                await consent.opt_out(
                    session, tenant_id=tenant_id, person_id=person_id, source="telepathy"
                )


class TestOptOutAppliesToNewActivity:
    async def test_a_new_fact_is_never_attributed_to_an_opted_out_person(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Enforced where attribution is *made*, not only where it is read.

        A read-time filter leaves the link in the database and relies on every
        future query remembering to exclude it. The promise was that CAIRN would
        not attribute their activity — not that it would attribute it quietly.
        """
        tenant_id, person_id = workspace

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await session.commit()

        fact_id = await add_fact(tenant_id, None)

        async with tenant_session(tenant_id) as session:
            await store.attach_people(session, tenant_id=tenant_id, fact_id=fact_id)
            await session.commit()

        async with tenant_session(tenant_id) as session:
            fact = await session.get(FactRow, fact_id)
            assert fact is not None
            [link] = fact.people
            assert link.person_id is None, "an opted-out person was attributed anyway"
            assert link.mention == "Priya Nair"

    async def test_activity_from_a_source_they_kept_is_still_attributed(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """The opt-out is per source, on the write path as well as the read one."""
        tenant_id, person_id = workspace

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await session.commit()

        fact_id = await add_fact(tenant_id, None, source="chat")

        async with tenant_session(tenant_id) as session:
            await store.attach_people(session, tenant_id=tenant_id, fact_id=fact_id)
            await session.commit()

        assert fact_id in await attributions(tenant_id, person_id)


class TestOptingBackIn:
    async def test_future_activity_is_attributed_again(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, person_id = workspace

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await consent.opt_in(session, tenant_id=tenant_id, person_id=person_id, source="github")
            await session.commit()

        fact_id = await add_fact(tenant_id, None)
        async with tenant_session(tenant_id) as session:
            await store.attach_people(session, tenant_id=tenant_id, fact_id=fact_id)
            await session.commit()

        assert fact_id in await attributions(tenant_id, person_id)

    async def test_what_was_unlinked_stays_unlinked(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Restoring old attributions would mean CAIRN had kept a record of what
        it was told not to attribute.

        The person can see the difference, because their record starts from the
        day they changed their mind — which is the honest outcome and the one
        the opt-out promised.
        """
        tenant_id, person_id = workspace
        fact_id = await add_fact(tenant_id, person_id)

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await consent.opt_in(session, tenant_id=tenant_id, person_id=person_id, source="github")
            await session.commit()

        assert fact_id not in await attributions(tenant_id, person_id)


class TestScope:
    async def test_the_choice_is_reported_back(
        self, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, person_id = workspace

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="meeting"
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            sources = await consent.opted_out_sources(
                session, tenant_id=tenant_id, person_id=person_id
            )
        assert sources == {"meeting"}

    async def test_one_workspace_cannot_see_another_s_choices(
        self, platform: AsyncSession, workspace: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        tenant_id, person_id = workspace

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=person_id, source="github"
            )
            await session.commit()

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(other.id) as session:
            rows = list(await session.scalars(select(SourceOptOut)))
        assert rows == []

    def test_every_source_the_product_reads_can_be_opted_out_of(self) -> None:
        """md/11 §4.1: the notification offers per-source opt-out, before any
        activity is captured.

        A source the pipeline can read but the notification cannot refuse is a
        gap in the promise. This used to assert plain equality with the
        evaluation dataset's taxonomy, which held while the two happened to
        coincide — and stopped holding the moment production learned to tell
        Slack from Google Chat.

        **They are related, not identical, and the difference is the point.** The
        evaluation taxonomy names *categories of evidence* for measuring
        extraction quality; `consent.SOURCES` names *products a customer
        connects, authorises and disconnects*. One evaluation category, `chat`,
        corresponds to two such products. Asserting equality again would force
        one of them to be wrong: either the fixtures claim a Slack provenance
        they never had, or consent loses the ability to refuse one chat product
        without the other.

        So the assertion is coverage in both directions, which is the property
        the promise actually needs.
        """
        from cairn_api import sources as canonical
        from cairn_api.evaluation.cases import Source as EvaluationSource

        #: The one category that is two products. Every other name is shared.
        bridge = {"chat": {item.value for item in canonical.LEGACY_CHAT_SOURCES}}

        measurable = {
            value
            for source in EvaluationSource
            for value in bridge.get(source.value, {source.value})
        }

        assert measurable == set(consent.SOURCES), (
            "a source the pipeline can read but nobody can refuse, or a source "
            "somebody can refuse that no evaluation case covers"
        )
