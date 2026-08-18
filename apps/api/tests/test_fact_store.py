"""The fact graph, against PostgreSQL.

`test_resolve.py` covers the rules; this covers what reaches disk. Three things
can only be checked here:

- **supersession is a two-row invariant.** A closed validity window with no
  successor is a fact that vanishes from every brief with nothing to explain
  the absence, and the constraint preventing it lives in the schema.
- **a merge writes no second row.** In-memory the plan says `MERGED`; only the
  database can show that the store did not quietly insert anyway.
- **nothing deletes.** The superseded row is still there afterwards, with its
  statement, its sources and its people.

And, since `apply` stopped loading the whole workspace, a fourth:

- **the candidate query is a superset of what `resolve()` can match.** Narrowing
  it wrongly is the one failure in this module with no symptom: a duplicate
  quietly becomes a second row, a superseded fact quietly stays current, and
  nothing anywhere reports it. `TestCandidateSelection` is therefore written as
  a differential test — resolve the same batch against the candidate set and
  against the full scan it replaced, and assert the two plans are identical —
  rather than as assertions about which rows come back, which would only
  restate the implementation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource
from cairn_api.db.identity_models import Identity, IdentityKind, Person
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.domain import Certainty
from cairn_api.pipeline import store
from cairn_api.pipeline.facts import Fact, FactKind, SourceRef
from cairn_api.pipeline.mentions import resolve_mentions
from cairn_api.pipeline.resolve import Decision, Outcome, resolve
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

MONDAY = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


def fact(
    statement: str,
    *,
    kind: FactKind = FactKind.DECISION,
    source: str = "github",
    evidence_id: str = "ev-1",
    certainty: Certainty = Certainty.VERIFIED,
    people: list[str] | None = None,
    at: datetime | None = MONDAY,
) -> Fact:
    return Fact(
        kind=kind,
        statement=statement,
        sources=[SourceRef(evidence_id=evidence_id, source=source)],
        certainty=certainty,
        people=people or [],
        occurred_at=at,
    )


@pytest.fixture
async def tenant_id(platform: AsyncSession) -> uuid.UUID:
    tenant = Tenant(name="Acme", slug=f"fact-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.commit()
    return tenant.id


async def count(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(FactRow).where(FactRow.tenant_id == tenant_id)
        )
    ) or 0


class TestPersistingResolution:
    async def test_one_decision_from_two_sources_writes_one_row(self, tenant_id: uuid.UUID) -> None:
        """The exit criterion, on disk rather than in a plan."""
        statement = "The team decided to use Postgres for the event store."
        async with tenant_session(tenant_id) as session:
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    fact(statement, source="meeting", evidence_id="ev-standup"),
                    fact(statement, source="chat", evidence_id="ev-thread"),
                ],
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            assert await count(session, tenant_id) == 1
            row = (await session.scalars(select(FactRow))).one()
            assert {s.source for s in row.sources} == {"meeting", "chat"}

    async def test_a_second_batch_merges_into_the_first(self, tenant_id: uuid.UUID) -> None:
        """Resolution reads the store, not only its own batch.

        Two mentions of one decision usually arrive minutes apart in separate
        events. A resolver that only deduplicated within a batch would produce
        a duplicate for every one of them.
        """
        statement = "The team decided to use Postgres for the event store."
        async with tenant_session(tenant_id) as session:
            await store.apply(
                session, tenant_id=tenant_id, incoming=[fact(statement, source="meeting")]
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            plan = await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[fact(statement, source="chat", evidence_id="ev-2")],
            )
            await session.commit()
            assert plan.decisions[0].outcome is Outcome.MERGED

        async with tenant_session(tenant_id) as session:
            assert await count(session, tenant_id) == 1

    async def test_a_superseded_fact_is_marked_not_deleted(self, tenant_id: uuid.UUID) -> None:
        """The other half of the exit criterion."""
        async with tenant_session(tenant_id) as session:
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    fact(
                        "Ali is working on the authentication rewrite.",
                        kind=FactKind.IN_PROGRESS,
                        people=["ali"],
                    )
                ],
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    fact(
                        "Ali is working on the billing rewrite.",
                        kind=FactKind.IN_PROGRESS,
                        evidence_id="ev-2",
                        people=["ali"],
                        at=MONDAY + timedelta(days=21),
                    )
                ],
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            rows = list(await session.scalars(select(FactRow).order_by(FactRow.occurred_at)))
            # Both rows survive. History is the product feature here: "what did
            # we think last Tuesday" is unanswerable in a store that overwrites.
            assert len(rows) == 2

            earlier, later = rows
            assert "authentication" in earlier.statement
            assert earlier.valid_until is not None
            assert earlier.superseded_by_id == later.id
            assert earlier.supersession_reason
            # Its provenance is intact — a superseded fact must still be
            # explainable to whoever is disputing the brief that carried it.
            assert earlier.sources

            assert later.valid_until is None
            assert later.superseded_by_id is None

    async def test_only_currently_valid_facts_are_loaded_for_resolution(
        self, tenant_id: uuid.UUID
    ) -> None:
        """A fact whose validity ended must not be superseded a second time."""
        async with tenant_session(tenant_id) as session:
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    fact(
                        "Ali is working on the authentication rewrite.",
                        kind=FactKind.IN_PROGRESS,
                        people=["ali"],
                    )
                ],
            )
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    fact(
                        "Ali is working on the billing rewrite.",
                        kind=FactKind.IN_PROGRESS,
                        evidence_id="ev-2",
                        people=["ali"],
                        at=MONDAY + timedelta(days=21),
                    )
                ],
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            current = await store.load_current(session, tenant_id=tenant_id)
            assert len(current) == 1
            assert "billing" in current[0].statement


class TestCandidateSelection:
    """The narrowed candidate query, checked against the full scan it replaced.

    Every test here asserts *agreement*, not membership. What matters is not
    which rows the predicate returns but that resolving against them reaches the
    same decision the old whole-workspace scan did — for merges, for
    supersessions, and for conflicts. A test asserting "the query returned three
    rows" would pass a rewrite that returned the wrong three.
    """

    @staticmethod
    async def assert_agrees(
        session: AsyncSession, tenant_id: uuid.UUID, incoming: list[Fact]
    ) -> list[Decision]:
        """Resolve one batch both ways and require identical plans."""
        full = await store.load_current(session, tenant_id=tenant_id)
        narrow = await store._candidates(session, tenant_id=tenant_id, incoming=incoming)

        def summarise(decisions: list[Decision]) -> list[tuple[object, ...]]:
            return [
                (d.fact.id, d.outcome, d.merged_into, d.supersedes, d.conflicts_with)
                for d in decisions
            ]

        wide_plan = resolve(incoming, full)
        narrow_plan = resolve(incoming, narrow)
        assert summarise(narrow_plan.decisions) == summarise(wide_plan.decisions)
        return narrow_plan.decisions

    @staticmethod
    async def noise(session: AsyncSession, tenant_id: uuid.UUID, count: int = 40) -> None:
        """Facts sharing no content with anything a test sends in.

        Present so the candidate query has something to *exclude*. Without it,
        every agreement test would pass with the narrowing deleted.
        """
        await store.apply(
            session,
            tenant_id=tenant_id,
            incoming=[
                fact(
                    f"Rotated the certificate for cluster nineteen-{index}.",
                    kind=FactKind.DELIVERY,
                    evidence_id=f"noise-{index}",
                    at=MONDAY - timedelta(days=index),
                )
                for index in range(count)
            ],
        )
        await session.flush()

    async def test_a_duplicate_still_finds_its_merge_target(self, tenant_id: uuid.UUID) -> None:
        statement = "The team decided to use Postgres for the event store."
        async with tenant_session(tenant_id) as session:
            await self.noise(session, tenant_id)
            await store.apply(
                session, tenant_id=tenant_id, incoming=[fact(statement, source="meeting")]
            )
            await session.flush()

            incoming = [fact(statement, source="chat", evidence_id="ev-2")]
            [decision] = await self.assert_agrees(session, tenant_id, incoming)
            assert decision.outcome is Outcome.MERGED

    async def test_supersession_reaches_back_past_the_merge_window(
        self, tenant_id: uuid.UUID
    ) -> None:
        """The clause most likely to be got wrong, tested in the direction that fails.

        `_find_superseded` applies no time bound at all, so a candidate query
        that reused the merge window would strand every fact older than a
        fortnight as permanently current — the "Ali is working on
        authentication" failure, reintroduced by a performance fix.
        """
        async with tenant_session(tenant_id) as session:
            await self.noise(session, tenant_id)
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    fact(
                        "Ali is working on the authentication rewrite.",
                        kind=FactKind.IN_PROGRESS,
                        people=["ali"],
                        at=MONDAY - timedelta(days=240),
                    )
                ],
            )
            await session.flush()

            incoming = [
                fact(
                    "Ali is working on the billing rewrite.",
                    kind=FactKind.IN_PROGRESS,
                    evidence_id="ev-2",
                    people=["ali"],
                    at=MONDAY,
                )
            ]
            [decision] = await self.assert_agrees(session, tenant_id, incoming)
            assert decision.outcome is Outcome.SUPERSEDES

    async def test_a_contradiction_with_no_ordering_is_still_seen(
        self, tenant_id: uuid.UUID
    ) -> None:
        """A conflict is reached through the same branch as a supersession.

        Losing it would be worse than losing a supersession: the two statements
        would both be stored as current with nothing marking them as disagreeing.
        """
        async with tenant_session(tenant_id) as session:
            await self.noise(session, tenant_id)
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[
                    fact(
                        "The event store will use Kafka.",
                        kind=FactKind.DECISION,
                        at=MONDAY,
                    )
                ],
            )
            await session.flush()

            incoming = [
                fact(
                    "The event store will use Postgres instead.",
                    kind=FactKind.DECISION,
                    evidence_id="ev-2",
                    at=MONDAY,
                )
            ]
            [decision] = await self.assert_agrees(session, tenant_id, incoming)
            assert decision.outcome is Outcome.CONFLICT

    async def test_an_undated_fact_on_either_side_is_never_excluded_by_time(
        self, tenant_id: uuid.UUID
    ) -> None:
        """`_within_window` compares an undated fact to everything.

        A SQL window written without the `occurred_at IS NULL` escape would drop
        exactly the facts from sources that do not timestamp reliably — and
        duplicates that never merge look like real repeated activity.
        """
        statement = "The team decided to use Postgres for the event store."
        async with tenant_session(tenant_id) as session:
            await self.noise(session, tenant_id)
            await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[fact(statement, source="meeting", at=None)],
            )
            await session.flush()

            # Dated incoming against an undated stored fact, and the reverse.
            [dated] = await self.assert_agrees(
                session, tenant_id, [fact(statement, source="chat", evidence_id="ev-2")]
            )
            assert dated.outcome is Outcome.MERGED

            [undated] = await self.assert_agrees(
                session,
                tenant_id,
                [fact(statement, source="document", evidence_id="ev-3", at=None)],
            )
            assert undated.outcome is Outcome.MERGED

    async def test_punctuated_and_cased_tokens_survive_the_sql_round_trip(
        self, tenant_id: uuid.UUID
    ) -> None:
        """`auth.py`, `v2.1` and `feature/rate-limit` are single tokens.

        They are also the ones a naive `to_tsvector` predicate would split, and
        the case difference is what a `LIKE` on the raw column would miss. Both
        would drop the merge silently.
        """
        statement = "Merged feature/rate-limit into Auth.PY for release V2.1."
        async with tenant_session(tenant_id) as session:
            await self.noise(session, tenant_id)
            await store.apply(
                session, tenant_id=tenant_id, incoming=[fact(statement, source="meeting")]
            )
            await session.flush()

            [decision] = await self.assert_agrees(
                session,
                tenant_id,
                [fact(statement.lower(), source="chat", evidence_id="ev-2")],
            )
            assert decision.outcome is Outcome.MERGED

    async def test_the_candidate_set_is_actually_smaller_than_the_workspace(
        self, tenant_id: uuid.UUID
    ) -> None:
        """The test that stops every other test in this class from being vacuous.

        Agreement is trivially true for a query that returns everything, which
        is precisely the query being replaced.
        """
        async with tenant_session(tenant_id) as session:
            await self.noise(session, tenant_id, count=60)
            await session.flush()

            incoming = [fact("The team decided to use Postgres for the event store.")]
            full = await store.load_current(session, tenant_id=tenant_id)
            narrow = await store._candidates(session, tenant_id=tenant_id, incoming=incoming)

            assert len(full) >= 60
            assert len(narrow) < len(full) / 10

    async def test_an_empty_batch_asks_the_database_nothing(self, tenant_id: uuid.UUID) -> None:
        """An empty `OR` list is an always-false predicate, and a wasted round trip."""
        async with tenant_session(tenant_id) as session:
            assert await store._candidates(session, tenant_id=tenant_id, incoming=[]) == []

    async def test_a_statement_with_no_content_tokens_matches_nothing(
        self, tenant_id: uuid.UUID
    ) -> None:
        """Nothing but stopwords must not become "match every fact".

        `resolve()` could not have merged it either — `MIN_SHARED_TOKENS` cannot
        be met by an empty token set — so returning everything would be pure
        cost. The check is that the empty case fails closed rather than open.
        """
        async with tenant_session(tenant_id) as session:
            await self.noise(session, tenant_id)
            await session.flush()

            incoming = [fact("It is the ...", kind=FactKind.DELIVERY)]
            narrow = await store._candidates(session, tenant_id=tenant_id, incoming=incoming)
            assert narrow == []
            await self.assert_agrees(session, tenant_id, incoming)


class TestRacesAgainstTheSnapshot:
    """What happens when the fact a decision names is gone by the time it lands.

    `resolve()` decides against a snapshot; the writes happen afterwards. In
    between, another worker can supersede the fact that was going to absorb a
    merge, and a tenant deletion can remove a predecessor outright. Neither is
    common and both are why the code has the branch — an untested error path is
    a branch nobody has ever seen run.
    """

    async def test_a_merge_whose_target_vanished_becomes_an_insert(
        self, tenant_id: uuid.UUID
    ) -> None:
        """Losing a fact to a race is worse than an occasional duplicate.

        The same trade the thresholds make: a visible duplicate can be reported,
        a dropped fact cannot.
        """
        incoming = fact("The team decided to use Postgres for the event store.")
        decision = Decision(
            fact=incoming,
            outcome=Outcome.MERGED,
            merged_into=uuid.uuid4(),  # never existed; indistinguishable from removed
            reason="same decision already recorded",
        )

        async with tenant_session(tenant_id) as session:
            await store._apply_merge(session, tenant_id, decision)
            await session.commit()

        async with tenant_session(tenant_id) as session:
            rows = list(await session.scalars(select(FactRow)))
            assert [row.id for row in rows] == [incoming.id]
            assert rows[0].sources, "the fact arrived without the provenance it came with"

    async def test_a_supersession_whose_predecessor_vanished_still_stores_the_successor(
        self, tenant_id: uuid.UUID
    ) -> None:
        """The new fact is the half that must survive.

        Abandoning it because the row it replaced is gone would drop the current
        state of the workspace in order to avoid a dangling pointer.
        """
        incoming = fact(
            "Ali is working on the billing rewrite.",
            kind=FactKind.IN_PROGRESS,
            people=["ali"],
        )
        decision = Decision(
            fact=incoming,
            outcome=Outcome.SUPERSEDES,
            supersedes=uuid.uuid4(),
            reason="later in_progress about the same subject",
        )

        async with tenant_session(tenant_id) as session:
            await store._apply_supersession(session, tenant_id, decision)
            await session.commit()

        async with tenant_session(tenant_id) as session:
            rows = list(await session.scalars(select(FactRow)))
            assert [row.id for row in rows] == [incoming.id]
            # Stored as current, with no half-written supersession behind it —
            # a closed validity window pointing at nothing is the state
            # `supersession_is_complete` exists to make impossible.
            assert rows[0].valid_until is None
            assert rows[0].superseded_by_id is None


class TestSchemaInvariants:
    async def test_a_fact_cannot_expire_without_a_successor(self, tenant_id: uuid.UUID) -> None:
        """Half a supersession is worse than none.

        A closed validity window with nothing to point at is a fact that has
        silently left every brief, with no record of what replaced it.
        """
        async with tenant_session(tenant_id) as session:
            row = FactRow(
                tenant_id=tenant_id,
                kind="decision",
                statement="Chose Postgres.",
                certainty="verified",
                valid_from=MONDAY,
                valid_until=MONDAY + timedelta(days=1),
            )
            session.add(row)
            with pytest.raises(IntegrityError, match="supersession_is_complete"):
                await session.flush()
            await session.rollback()

    async def test_a_fact_cannot_supersede_itself(self, tenant_id: uuid.UUID) -> None:
        async with tenant_session(tenant_id) as session:
            row = FactRow(
                tenant_id=tenant_id,
                kind="decision",
                statement="Chose Postgres.",
                certainty="verified",
                valid_from=MONDAY,
            )
            session.add(row)
            await session.flush()

            row.valid_until = MONDAY + timedelta(days=1)
            row.superseded_by_id = row.id
            with pytest.raises(IntegrityError, match="no_self_supersession"):
                await session.flush()
            await session.rollback()

    async def test_one_source_cites_a_fact_once(self, tenant_id: uuid.UUID) -> None:
        """Reprocessing an event after a redeploy must not inflate corroboration.

        Two rows for one citation would read as independent confirmation — and
        corroboration promotes certainty, so the duplicate would make the system
        sound more sure because a worker restarted.
        """
        async with tenant_session(tenant_id) as session:
            row = FactRow(
                tenant_id=tenant_id,
                kind="decision",
                statement="Chose Postgres.",
                certainty="verified",
                valid_from=MONDAY,
                sources=[
                    FactSource(tenant_id=tenant_id, source="github", evidence_id="ev-1"),
                    FactSource(tenant_id=tenant_id, source="github", evidence_id="ev-1"),
                ],
            )
            session.add(row)
            with pytest.raises(IntegrityError, match="fact_source_evidence"):
                await session.flush()
            await session.rollback()

    async def test_facts_are_invisible_to_another_workspace(
        self, platform: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """Row-level security, on the newest tables.

        Every table added since the isolation work has to be checked, because a
        table created without a policy is readable by every tenant and nothing
        in the application would report it.
        """
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(tenant_id) as session:
            await store.apply(
                session, tenant_id=tenant_id, incoming=[fact("Chose Postgres for the store.")]
            )
            await session.commit()

        async with tenant_session(other.id) as session:
            assert await count(session, tenant_id) == 0
            assert (await session.scalars(select(FactRow))).all() == []


class TestMentionResolution:
    @pytest.fixture
    async def people(self, platform: AsyncSession, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
        ali = Person(tenant_id=tenant_id, display_name="Ali Hassan")
        priya = Person(tenant_id=tenant_id, display_name="Priya Nair")
        platform.add_all([ali, priya])
        await platform.flush()
        platform.add(
            Identity(
                tenant_id=tenant_id,
                person_id=ali.id,
                kind=IdentityKind.GITHUB_LOGIN,
                value="alihassan",
            )
        )
        await platform.commit()
        return {"ali": ali.id, "priya": priya.id}

    async def test_a_handle_resolves(
        self, tenant_id: uuid.UUID, people: dict[str, uuid.UUID]
    ) -> None:
        async with tenant_session(tenant_id) as session:
            resolution = await resolve_mentions(session, tenant_id=tenant_id, names=["@alihassan"])
        assert resolution.person_ids == [people["ali"]]

    async def test_an_exact_display_name_resolves_to_nobody(
        self, tenant_id: uuid.UUID, people: dict[str, uuid.UUID]
    ) -> None:
        """**A name is not evidence of identity, even an exact and unique one.**

        This test asserted the opposite until Step 34, and the behaviour it
        described was the last path by which a string a model wrote could decide
        whose record something joined. Uniqueness was never the safeguard it
        looked like: two colleagues called Sam are one rename apart, a new hire
        can collide with an existing person tomorrow, and the model writes the
        name from message text an outsider may have influenced.

        Ownership now comes from a provider account the person confirmed, or from
        an identifier in the identity graph. The name is still *kept* — the row
        below still carries it, so "who did the model mean?" stays answerable and
        correctable — it simply no longer attributes.
        """
        async with tenant_session(tenant_id) as session:
            resolution = await resolve_mentions(session, tenant_id=tenant_id, names=["priya nair"])

        assert resolution.person_ids == []
        assert resolution.unresolved[0].unresolved_reason == "a name is not evidence of identity"

    async def test_an_ambiguous_name_resolves_to_nobody(
        self, platform: AsyncSession, tenant_id: uuid.UUID, people: dict[str, uuid.UUID]
    ) -> None:
        """No tiebreak.

        Every available one — most recent activity, most commits — is a guess,
        and being wrong credits one colleague's work to another.
        """
        platform.add(Person(tenant_id=tenant_id, display_name="Ali Hassan"))
        await platform.commit()

        async with tenant_session(tenant_id) as session:
            resolution = await resolve_mentions(session, tenant_id=tenant_id, names=["Ali Hassan"])

        assert resolution.person_ids == []
        # The reason changed with the rule: ambiguity is no longer *why* a name
        # fails to attribute, because a name never attributes now. Keeping the
        # old wording would describe a tiebreak that no longer runs.
        assert resolution.unresolved[0].unresolved_reason == "a name is not evidence of identity"

    async def test_an_unknown_name_is_kept_rather_than_dropped(
        self, tenant_id: uuid.UUID, people: dict[str, uuid.UUID]
    ) -> None:
        async with tenant_session(tenant_id) as session:
            resolution = await resolve_mentions(session, tenant_id=tenant_id, names=["Sam"])

        assert resolution.unresolved[0].raw == "Sam"
        assert not resolution.unresolved[0].resolved

    async def test_an_unresolved_mention_still_reaches_the_fact_row(
        self, tenant_id: uuid.UUID, people: dict[str, uuid.UUID]
    ) -> None:
        """ "Who is Sam?" is answerable from a stored mention and not from a
        dropped one."""
        async with tenant_session(tenant_id) as session:
            plan = await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[fact("Shipped the rate limiter.", people=["@alihassan", "Sam"])],
            )
            await store.attach_people(
                session, tenant_id=tenant_id, fact_id=plan.decisions[0].fact.id
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            links = list(await session.scalars(select(FactPerson)))
            by_mention = {link.mention: link for link in links}
            assert by_mention["@alihassan"].person_id == people["ali"]
            assert by_mention["Sam"].person_id is None

    async def test_attaching_people_never_clears_an_existing_link(
        self, tenant_id: uuid.UUID, people: dict[str, uuid.UUID]
    ) -> None:
        """A person id already on the row may have been put there by a human.

        An automatic pass that cleared it would undo a correction — and the
        correction is the one piece of data the system did not have to guess.
        """
        async with tenant_session(tenant_id) as session:
            plan = await store.apply(
                session,
                tenant_id=tenant_id,
                incoming=[fact("Shipped the rate limiter.", people=["Sam"])],
            )
            await session.flush()
            link = (await session.scalars(select(FactPerson))).one()
            link.person_id = people["priya"]
            await session.flush()

            await store.attach_people(
                session, tenant_id=tenant_id, fact_id=plan.decisions[0].fact.id
            )
            await session.flush()

            refreshed = (await session.scalars(select(FactPerson))).one()
            assert refreshed.person_id == people["priya"]
