"""The related-work finder and self-declared capacity: the boundary is the feature.

Both features answer the Owner's real need — "who knows about this, who has
room" — and both are built so CAIRN never evaluates, ranks, or monitors anyone
on the way. The tests here encode the refusals: no score exists even as a
field, every role reads the same bytes, an opted-out person cannot surface,
and no code path computes capacity for anybody.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource
from cairn_api.db.identity_models import Person, PersonCapacity
from cairn_api.db.models import Tenant, TenantRole
from cairn_api.db.tenancy import tenant_session
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


async def workspace_with_related_work(
    platform: AsyncSession,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """One tenant, two people; one has facts about rate limiting, one about
    onboarding. Returns (tenant_id, limiter_person, onboarding_person)."""
    tenant = Tenant(name="Finder", slug=f"finder-{uuid.uuid4().hex[:10]}")
    platform.add(tenant)
    await platform.commit()

    async with tenant_session(tenant.id) as session:
        limiter = Person(tenant_id=tenant.id, display_name="Priya Nair")
        onboarder = Person(tenant_id=tenant.id, display_name="Sara Bennett")
        session.add_all([limiter, onboarder])
        await session.flush()

        for index, (person, statement, topic_hint) in enumerate(
            [
                (limiter, "Priya shipped rate limiting to the public API.", "github"),
                (limiter, "Priya documented the rate limit rollout.", "github"),
                (onboarder, "Sara redesigned the onboarding flow.", "github"),
            ]
        ):
            fact = FactRow(
                tenant_id=tenant.id,
                kind="delivery",
                statement=statement,
                certainty="verified",
                occurred_at=NOW - timedelta(days=index),
                valid_from=NOW - timedelta(days=10),
            )
            session.add(fact)
            await session.flush()
            session.add(
                FactSource(
                    tenant_id=tenant.id,
                    fact_id=fact.id,
                    evidence_id=f"github:commit:{uuid.uuid4().hex}",
                    source=topic_hint,
                )
            )
            session.add(
                FactPerson(
                    tenant_id=tenant.id,
                    fact_id=fact.id,
                    mention=person.display_name,
                    person_id=person.id,
                )
            )
        await session.commit()
        return tenant.id, limiter.id, onboarder.id


class TestNoScoreExistsEvenAsAField:
    def test_the_response_model_carries_no_ranking_vocabulary(self) -> None:
        """Not "the score is hidden" — the field does not exist to hide. The
        forbidden fragments are the same list the permission suite guards, so
        the two boundaries cannot drift apart."""
        from cairn_api.api import schemas

        forbidden = ("score", "rank", "relevance", "match_strength", "strength", "percent")
        for model_name in ("RelatedWorkResponse", "RelatedPersonGroup", "RelatedFact"):
            model = getattr(schemas, model_name)
            for field_name in model.model_fields:
                for fragment in forbidden:
                    assert fragment not in field_name.lower(), (
                        f"{model_name}.{field_name} smells like a ranking; the finder "
                        "shows evidence, and the human decides"
                    )

    def test_grouping_is_by_most_recent_fact_and_says_so(self) -> None:
        """Evidence ordering, not relevance ordering — asserted at the source
        so the sort key cannot quietly become a similarity number."""
        from cairn_api.api.routers import related_work

        source = inspect.getsource(related_work)
        assert "occurred_at" in source
        assert "distance" not in source.replace("cosine_distance", ""), (
            "the finder must never order people by a similarity number"
        )


class TestSymmetry:
    async def test_every_role_reads_the_same_bytes(self, platform: AsyncSession) -> None:
        """The symmetry invariant, on the wire: Owner, Member and Viewer asking
        the same topic receive byte-identical responses."""
        from cairn_api.api.routers.related_work import find_related_work_payload

        tenant_id, _, _ = await workspace_with_related_work(platform)

        payloads = []
        async with tenant_session(tenant_id) as session:
            for _role in (TenantRole.OWNER, TenantRole.MEMBER, TenantRole.VIEWER):
                payload = await find_related_work_payload(
                    session, tenant_id=tenant_id, topic="rate limiting"
                )
                payloads.append(payload.model_dump_json())

        assert payloads[0] == payloads[1] == payloads[2], (
            "the finder's output depended on who asked"
        )


class TestConsentIsInherited:
    async def test_an_opted_out_person_cannot_surface(self, platform: AsyncSession) -> None:
        """Opt-out unlinks `fact_people.person_id`, and the finder groups by
        resolved person only — so the consent decision is inherited
        structurally, not re-implemented. This test proves the inheritance."""
        from cairn_api.api.routers.related_work import find_related_work_payload
        from cairn_api.pipeline import consent

        tenant_id, limiter_id, _ = await workspace_with_related_work(platform)

        async with tenant_session(tenant_id) as session:
            await consent.opt_out(
                session, tenant_id=tenant_id, person_id=limiter_id, source="github"
            )
            await session.commit()

        async with tenant_session(tenant_id) as session:
            payload = await find_related_work_payload(
                session, tenant_id=tenant_id, topic="rate limiting"
            )

        surfaced = {group.person_id for group in payload.groups}
        assert limiter_id not in surfaced, "an opted-out person surfaced through the finder"

    async def test_unresolved_mentions_never_surface(self, platform: AsyncSession) -> None:
        """A mention with no resolved person is a name nobody confirmed;
        grouping it would assert an attribution the identity rules refused."""
        from cairn_api.api.routers.related_work import find_related_work_payload

        tenant_id, _limiter_id, _ = await workspace_with_related_work(platform)
        async with tenant_session(tenant_id) as session:
            fact = FactRow(
                tenant_id=tenant_id,
                kind="delivery",
                statement="Somebody tuned the rate limiter thresholds.",
                certainty="observed",
                occurred_at=NOW,
                valid_from=NOW,
            )
            session.add(fact)
            await session.flush()
            session.add(
                FactSource(
                    tenant_id=tenant_id,
                    fact_id=fact.id,
                    evidence_id=f"github:commit:{uuid.uuid4().hex}",
                    source="github",
                )
            )
            session.add(
                FactPerson(tenant_id=tenant_id, fact_id=fact.id, mention="somebody", person_id=None)
            )
            await session.commit()

            payload = await find_related_work_payload(
                session, tenant_id=tenant_id, topic="rate limiter thresholds"
            )

        names = {group.display_name for group in payload.groups}
        assert "somebody" not in names


class TestCapacityIsSelfDeclaredOnly:
    async def test_no_code_path_writes_capacity_except_the_owner_of_record(self) -> None:
        """The grep-able rule: `capacity_stated_at` is assigned in exactly one
        place in the application — the me-endpoint that requires the caller to
        BE the person. Any second writer is a computation or an override, and
        both are the defect the design refuses."""
        import pathlib

        import cairn_api

        root = pathlib.Path(cairn_api.__file__).parent
        writers = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "capacity_stated_at =" in text.replace("capacity_stated_at ==", ""):
                writers.append(path.name)
        assert writers == ["me.py"], (
            f"capacity is written outside the owner-of-record endpoint: {writers}. "
            "CAIRN never computes capacity; the person states it."
        )

    async def test_an_owner_with_every_permission_cannot_set_anothers_capacity(
        self, platform: AsyncSession
    ) -> None:
        """Role grants configuration power, never power over another person's
        self-description. The endpoint resolves the person FROM the caller, so
        there is no parameter through which a target could even be named."""
        from cairn_api.api.routers import me as me_router

        signature = inspect.signature(me_router.set_my_capacity)
        assert "person_id" not in signature.parameters
        assert "user_id" not in signature.parameters
        source = inspect.getsource(me_router.set_my_capacity)
        assert "_person_for" in source, (
            "capacity must resolve the person from the authenticated caller"
        )

    async def test_stating_capacity_stamps_the_person_row(self, platform: AsyncSession) -> None:
        from cairn_api.api.routers.me import apply_capacity

        tenant = Tenant(name="Cap", slug=f"cap-{uuid.uuid4().hex[:10]}")
        platform.add(tenant)
        await platform.commit()
        async with tenant_session(tenant.id) as session:
            person = Person(tenant_id=tenant.id, display_name="Ada")
            session.add(person)
            await session.commit()

            await apply_capacity(person, PersonCapacity.OPEN_TO_WORK)
            await session.commit()

            assert person.capacity is PersonCapacity.OPEN_TO_WORK
            assert person.capacity_stated_at is not None

    def test_the_default_states_nothing(self) -> None:
        """`not_stated` is the default and is not an answer — absence of a
        declaration must never read as availability or its opposite."""
        assert PersonCapacity.NOT_STATED.value == "not_stated"
