"""Confirming an account fills in its past, and refuses to fill in anyone else's.

Reconciliation is the moment with the most potential to do harm in this whole
step: a single `UPDATE` that decides a batch of existing records now belong to
somebody. Every test here is about a way it could reach a row it has no business
touching.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.consent_models import SourceOptOut
from cairn_api.db.external_identity_models import (
    ExternalIdentity,
    IdentityLinkState,
    IdentityVerification,
)
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactPerson, FactSource
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import tenant_session
from cairn_api.pipeline import store
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

SLACK_USER = "U0RECON01"
MONDAY = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)


class Workspace:
    """A tenant with one notified member and their person row."""

    def __init__(self, tenant_id: uuid.UUID, person_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.tenant_id = tenant_id
        self.person_id = person_id
        self.user_id = user_id


async def a_workspace(platform: AsyncSession, *, notified: bool = True) -> Workspace:
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name="Acme", slug=f"recon-{suffix}")
    user = User(email=f"ali-{suffix}@acme.example", email_verified_at=datetime.now(UTC))
    platform.add_all([tenant, user])
    await platform.flush()
    platform.add(
        Membership(
            tenant_id=tenant.id,
            user_id=user.id,
            role=TenantRole.MEMBER,
            notified_at=datetime.now(UTC) if notified else None,
        )
    )
    person = Person(tenant_id=tenant.id, display_name="Ali Rahman", user_id=user.id)
    platform.add(person)
    await platform.commit()
    return Workspace(tenant.id, person.id, user.id)


async def a_fact_from(
    tenant_id: uuid.UUID,
    *,
    provider: ConnectorProvider = ConnectorProvider.SLACK,
    account_id: str = SLACK_USER,
    source: str = "slack",
    person_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """One stored fact carrying a provider actor and no resolved person."""
    async with tenant_session(tenant_id) as session:
        row = FactRow(
            tenant_id=tenant_id,
            kind="delivery",
            statement="Shipped the auth fix.",
            certainty="verified",
            occurred_at=MONDAY,
            valid_from=MONDAY,
            sources=[
                FactSource(
                    tenant_id=tenant_id,
                    source=source,
                    evidence_id=f"{source}:message:{uuid.uuid4().hex[:12]}",
                    quote="Shipped the auth fix.",
                )
            ],
            people=[
                FactPerson(
                    tenant_id=tenant_id,
                    mention=None,
                    provider=provider.value,
                    provider_account_id=account_id,
                    person_id=person_id,
                )
            ],
        )
        session.add(row)
        await session.commit()
        return row.id


async def a_link(workspace: Workspace, *, account_id: str = SLACK_USER) -> None:
    async with tenant_session(workspace.tenant_id) as session:
        session.add(
            ExternalIdentity(
                tenant_id=workspace.tenant_id,
                person_id=workspace.person_id,
                provider=ConnectorProvider.SLACK,
                provider_account_id=account_id,
                provider_email=None,
                verification=IdentityVerification.SELF_CONFIRMED,
                state=IdentityLinkState.ACTIVE,
                linked_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def attributed(tenant_id: uuid.UUID, fact_id: uuid.UUID) -> uuid.UUID | None:
    async with tenant_session(tenant_id) as session:
        return await session.scalar(
            select(FactPerson.person_id).where(FactPerson.fact_id == fact_id)
        )


async def reconcile(workspace: Workspace, *, account_id: str = SLACK_USER) -> int:
    async with tenant_session(workspace.tenant_id) as session:
        changed = await store.reconcile_actor(
            session,
            tenant_id=workspace.tenant_id,
            person_id=workspace.person_id,
            provider=ConnectorProvider.SLACK,
            provider_account_id=account_id,
        )
        await session.commit()
        return changed


class TestItFillsInWhatTheAccountAlreadyProduced:
    async def test_unresolved_work_from_that_account_becomes_theirs(
        self, platform: AsyncSession
    ) -> None:
        workspace = await a_workspace(platform)
        fact_id = await a_fact_from(workspace.tenant_id)
        await a_link(workspace)

        assert await reconcile(workspace) == 1
        assert await attributed(workspace.tenant_id, fact_id) == workspace.person_id

    async def test_running_it_twice_changes_nothing_the_second_time(
        self, platform: AsyncSession
    ) -> None:
        """Idempotent by predicate, not by a flag somebody has to maintain: the
        `WHERE` excludes rows it has already changed, so a re-run matches none.
        """
        workspace = await a_workspace(platform)
        await a_fact_from(workspace.tenant_id)
        await a_link(workspace)

        assert await reconcile(workspace) == 1
        assert await reconcile(workspace) == 0

    async def test_it_touches_only_the_exact_account(self, platform: AsyncSession) -> None:
        """Tenant, provider and account id — all three, and nothing else."""
        workspace = await a_workspace(platform)
        mine = await a_fact_from(workspace.tenant_id, account_id=SLACK_USER)
        somebody_else = await a_fact_from(workspace.tenant_id, account_id="U0OTHER99")
        other_provider = await a_fact_from(
            workspace.tenant_id,
            provider=ConnectorProvider.GOOGLE_CHAT,
            account_id=SLACK_USER,
            source="google_chat",
        )
        await a_link(workspace)

        assert await reconcile(workspace) == 1
        assert await attributed(workspace.tenant_id, mine) == workspace.person_id
        assert await attributed(workspace.tenant_id, somebody_else) is None
        assert await attributed(workspace.tenant_id, other_provider) is None


class TestItNeverTakesWorkFromSomebodyElse:
    async def test_a_fact_already_attributed_is_left_alone(self, platform: AsyncSession) -> None:
        """The conservative reading, and deliberately so.

        The work *was* attributed to that person at the time, they may already
        have corrected it, and rewriting it retroactively would edit somebody's
        record on the strength of a claim made later by a different person.
        """
        workspace = await a_workspace(platform)
        colleague = await a_workspace(platform)
        # A fact from the same account, already owned by someone else.
        fact_id = await a_fact_from(workspace.tenant_id, person_id=colleague.person_id)
        await a_link(workspace)

        assert await reconcile(workspace) == 0
        assert await attributed(workspace.tenant_id, fact_id) == colleague.person_id

    async def test_another_workspace_is_never_reached(self, platform: AsyncSession) -> None:
        """The same Slack account id in two workspaces is two questions."""
        mine = await a_workspace(platform)
        theirs = await a_workspace(platform)
        their_fact = await a_fact_from(theirs.tenant_id)
        await a_link(mine)

        assert await reconcile(mine) == 0
        assert await attributed(theirs.tenant_id, their_fact) is None


class TestConsentSurvivesReconciliation:
    """The back door this function would otherwise be."""

    async def test_a_refused_source_is_not_filled_in(self, platform: AsyncSession) -> None:
        """**Confirming an account is not opting back in.**

        Somebody who refused Slack and later confirms their Slack account has
        said "this account is mine", not "read it after all". Without this,
        reconciliation would restore precisely the history the refusal exists to
        prevent — and it would do it in one statement, silently.
        """
        workspace = await a_workspace(platform)
        fact_id = await a_fact_from(workspace.tenant_id, source="slack")
        async with tenant_session(workspace.tenant_id) as session:
            session.add(
                SourceOptOut(
                    tenant_id=workspace.tenant_id,
                    person_id=workspace.person_id,
                    source="slack",
                )
            )
            await session.commit()
        await a_link(workspace)

        assert await reconcile(workspace) == 0
        assert await attributed(workspace.tenant_id, fact_id) is None

    async def test_refusing_one_source_leaves_another_reconcilable(
        self, platform: AsyncSession
    ) -> None:
        """Slack and Google Chat are separate refusals, so they must have
        separate effects — the whole point of retiring the single `chat` value.
        """
        workspace = await a_workspace(platform)
        chat_fact = await a_fact_from(
            workspace.tenant_id,
            provider=ConnectorProvider.SLACK,
            account_id=SLACK_USER,
            source="slack",
        )
        async with tenant_session(workspace.tenant_id) as session:
            session.add(
                SourceOptOut(
                    tenant_id=workspace.tenant_id,
                    person_id=workspace.person_id,
                    source="google_chat",
                )
            )
            await session.commit()
        await a_link(workspace)

        assert await reconcile(workspace) == 1
        assert await attributed(workspace.tenant_id, chat_fact) == workspace.person_id

    async def test_evidence_survives_a_refusal(self, platform: AsyncSession) -> None:
        """An opt-out removes attribution, never the record that something
        happened. The workspace's own history is not the person's to erase and
        not CAIRN's to quietly drop."""
        workspace = await a_workspace(platform)
        fact_id = await a_fact_from(workspace.tenant_id, source="slack")
        async with tenant_session(workspace.tenant_id) as session:
            session.add(
                SourceOptOut(
                    tenant_id=workspace.tenant_id,
                    person_id=workspace.person_id,
                    source="slack",
                )
            )
            await session.commit()
        await a_link(workspace)
        await reconcile(workspace)

        async with tenant_session(workspace.tenant_id) as session:
            fact = await session.get(FactRow, fact_id)
            assert fact is not None
            assert fact.statement == "Shipped the auth fix."
            assert len(fact.sources) == 1
            # The provider's own record of who produced it is untouched.
            [link] = fact.people
            assert link.provider_account_id == SLACK_USER
            assert link.person_id is None

    async def test_an_unnotified_person_is_not_reconciled(self, platform: AsyncSession) -> None:
        """md/05 §B.3.5: no attribution before first-capture notification, and no
        exception for a person who has just confirmed an account."""
        workspace = await a_workspace(platform, notified=False)
        fact_id = await a_fact_from(workspace.tenant_id)
        await a_link(workspace)

        assert await reconcile(workspace) == 0
        assert await attributed(workspace.tenant_id, fact_id) is None


class TestEndingALinkTakesTheAttributionWithIt:
    """The half a browser test found missing.

    `end_link` stopped *future* attribution while everything already attributed
    stayed on the person's record — so "I unlinked that account" and "that work
    is still filed under my name" were both true on the same screen, and the
    second is the one the person can see.
    """

    async def test_unlinking_clears_what_the_account_was_attributed_to(
        self, platform: AsyncSession
    ) -> None:
        workspace = await a_workspace(platform)
        fact_id = await a_fact_from(workspace.tenant_id)
        await a_link(workspace)
        assert await reconcile(workspace) == 1

        async with tenant_session(workspace.tenant_id) as session:
            detached = await store.detach_actor(
                session,
                tenant_id=workspace.tenant_id,
                person_id=workspace.person_id,
                provider=ConnectorProvider.SLACK,
                provider_account_id=SLACK_USER,
            )
            await session.commit()

        assert detached == 1
        assert await attributed(workspace.tenant_id, fact_id) is None

    async def test_the_evidence_and_the_provider_record_survive(
        self, platform: AsyncSession
    ) -> None:
        """Nothing is deleted. The workspace's history is not the person's to
        erase, and a disputed link means the attribution was wrong — not that
        the work was imaginary."""
        workspace = await a_workspace(platform)
        fact_id = await a_fact_from(workspace.tenant_id)
        await a_link(workspace)
        await reconcile(workspace)

        async with tenant_session(workspace.tenant_id) as session:
            await store.detach_actor(
                session,
                tenant_id=workspace.tenant_id,
                person_id=workspace.person_id,
                provider=ConnectorProvider.SLACK,
                provider_account_id=SLACK_USER,
            )
            await session.commit()

        async with tenant_session(workspace.tenant_id) as session:
            fact = await session.get(FactRow, fact_id)
            assert fact is not None
            assert fact.statement == "Shipped the auth fix."
            assert len(fact.sources) == 1
            [link] = fact.people
            # The provider's own record of who produced it is untouched; only
            # CAIRN's claim about whose it is has gone.
            assert link.provider_account_id == SLACK_USER
            assert link.person_id is None

    async def test_it_leaves_a_colleagues_attribution_alone(self, platform: AsyncSession) -> None:
        """Scoped to this person and this account, so unlinking cannot reach
        work somebody else owns."""
        workspace = await a_workspace(platform)
        colleague = await a_workspace(platform)
        theirs = await a_fact_from(workspace.tenant_id, person_id=colleague.person_id)

        async with tenant_session(workspace.tenant_id) as session:
            detached = await store.detach_actor(
                session,
                tenant_id=workspace.tenant_id,
                person_id=workspace.person_id,
                provider=ConnectorProvider.SLACK,
                provider_account_id=SLACK_USER,
            )
            await session.commit()

        assert detached == 0
        assert await attributed(workspace.tenant_id, theirs) == colleague.person_id
