"""Whose work is this? Answered from the provider's own account id, or not at all.

These tests follow the identifier the provider actually sent — a Slack `U…`, a
Google Chat `users/…`, a GitHub numeric user id — from the stored delivery all
the way to `fact_people.person_id`, through the production reader and the
production mention resolver rather than through a harness built for the purpose.

That distinction is the reason the file exists. Before this step the whole
identity layer was reachable only from tests: `resolve_person` had no production
caller, Slack's author id was written to `webhook_deliveries.payload` and never
read again, and attribution for Slack and Chat happened to work only when the
model wrote somebody's name into a fact and exactly one person in the workspace
had that display name. Every layer passed its own tests; nothing joined them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.external_identity_models import (
    ExternalIdentity,
    IdentityLinkState,
    IdentityVerification,
)
from cairn_api.db.github_models import WebhookDelivery
from cairn_api.db.identity_models import Person
from cairn_api.db.models import Tenant
from cairn_api.db.tenancy import tenant_session
from cairn_api.identity import external
from cairn_api.pipeline import jobs, mentions
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

SLACK_USER = "U0ALICE99"
CHAT_USER = "users/1122334455"
GITHUB_USER = "5550001"


def _slack_delivery(user: str | None = SLACK_USER) -> WebhookDelivery:
    """A stored Slack delivery, shaped as the receipt path writes one."""
    event: dict[str, object] = {
        "type": "message",
        "channel": "C0ENG",
        "ts": "1700000000.000100",
        "text": "Shipped the auth fix.",
    }
    if user is not None:
        event["user"] = user
    return WebhookDelivery(
        delivery_id=f"slack-{uuid.uuid4().hex[:12]}",
        event_type="message",
        payload={"type": "event_callback", "team_id": "T0ACME", "event": event},
    )


def _chat_delivery(sender: str | None = CHAT_USER) -> WebhookDelivery:
    message: dict[str, object] = {
        "name": "spaces/AAA/messages/BBB",
        "text": "Reviewed the migration.",
        "createTime": "2026-08-17T09:00:00Z",
    }
    if sender is not None:
        message["sender"] = {"name": sender, "type": "HUMAN"}
    return WebhookDelivery(
        delivery_id=f"gchat-{uuid.uuid4().hex[:12]}",
        event_type="google.workspace.chat.message.v1.created",
        payload={
            "type": "google_chat_event",
            "event_type": "google.workspace.chat.message.v1.created",
            "message": message,
        },
    )


def _github_delivery(user_id: int | None = int(GITHUB_USER)) -> WebhookDelivery:
    user = {"id": user_id, "login": "alice"} if user_id is not None else None
    return WebhookDelivery(
        delivery_id=f"gh-{uuid.uuid4().hex[:12]}",
        event_type="pull_request",
        action="opened",
        payload={
            "repository": {"full_name": "acme/api"},
            "pull_request": {
                "number": 42,
                "title": "Add the auth fix",
                "body": "",
                "html_url": "https://github.com/acme/api/pull/42",
                "user": user,
            },
        },
    )


class TestTheProviderActorSurvivesToTheEvidence:
    """Receipt → stored payload → the production reader."""

    def test_a_slack_user_id_is_read_from_the_delivery(self) -> None:
        [evidence] = jobs._read_evidence(_slack_delivery())

        assert evidence.actor is not None
        assert evidence.actor.provider is ConnectorProvider.SLACK
        assert evidence.actor.account_id == SLACK_USER

    def test_a_google_chat_sender_is_read_from_the_delivery(self) -> None:
        [evidence] = jobs._read_evidence(_chat_delivery())

        assert evidence.actor is not None
        assert evidence.actor.provider is ConnectorProvider.GOOGLE_CHAT
        assert evidence.actor.account_id == CHAT_USER

    def test_a_github_pull_request_carries_the_stable_numeric_id(self) -> None:
        """`user.id`, never `user.login`.

        A login is renameable, and attribution keyed on a renameable string is
        reassigned by somebody else's rename.
        """
        [evidence] = jobs._read_evidence(_github_delivery())

        assert evidence.actor is not None
        assert evidence.actor.account_id == GITHUB_USER
        assert "alice" not in evidence.actor.mention

    def test_a_push_commit_carries_no_actor(self) -> None:
        """A push names the pusher, not the author of each commit.

        Attributing somebody's commit to whoever pushed it is precisely the
        wrong-person failure this step exists to prevent, so the honest record is
        an absence.
        """
        delivery = WebhookDelivery(
            delivery_id=f"gh-{uuid.uuid4().hex[:12]}",
            event_type="push",
            payload={
                "repository": {"full_name": "acme/api"},
                "sender": {"id": 999, "login": "someone-else"},
                "commits": [{"id": "a" * 40, "message": "Fix the thing", "url": None}],
            },
        )

        [evidence] = jobs._read_evidence(delivery)

        assert evidence.actor is None

    def test_a_payload_with_no_author_yields_no_actor(self) -> None:
        """Absent is not an error and must not become a guess."""
        assert jobs._read_evidence(_slack_delivery(user=None))[0].actor is None
        assert jobs._read_evidence(_chat_delivery(sender=None))[0].actor is None


class TestTheActorReachesTheFactAsAMention:
    """The evidence's actor becomes a `fact_people` row that can resolve."""

    def test_the_actor_is_added_to_the_people_of_a_fact_that_cites_it(self) -> None:
        evidence = jobs._read_evidence(_slack_delivery())
        [item] = evidence

        people = jobs._people_with_actors(["Ali"], evidence)

        assert item.actor is not None
        assert item.actor.mention in people
        # The model's own words are kept beside it: they are a claim about who a
        # statement concerns, correctable by the person, and they decide nothing.
        assert "Ali" in people

    def test_the_mention_encodes_provider_and_account_and_parses_back(self) -> None:
        mention = mentions.ProviderActor(
            provider=ConnectorProvider.SLACK, account_id=SLACK_USER
        ).mention

        parsed = mentions.read_provider_actor(mention)

        assert parsed is not None
        assert parsed.provider is ConnectorProvider.SLACK
        assert parsed.account_id == SLACK_USER

    def test_a_mention_naming_no_real_provider_does_not_parse(self) -> None:
        """The parse decides which table is consulted for a person, so a
        permissive one would send an arbitrary string to the identity lookup."""
        assert mentions.read_provider_actor("provider-actor:linkedin:U1") is None
        assert mentions.read_provider_actor("Ali") is None


class TestResolutionGoesThroughTheExternalIdentityTable:
    """The production resolver, against real rows."""

    @staticmethod
    async def _workspace(platform: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
        tenant = Tenant(name="Acme", slug=f"attr-{uuid.uuid4().hex[:10]}")
        platform.add(tenant)
        await platform.flush()
        person = Person(tenant_id=tenant.id, display_name="Ali Rahman")
        platform.add(person)
        await platform.commit()
        return tenant.id, person.id

    @staticmethod
    async def _link(
        tenant_id: uuid.UUID,
        person_id: uuid.UUID,
        *,
        provider: ConnectorProvider,
        account_id: str,
        state: IdentityLinkState = IdentityLinkState.ACTIVE,
    ) -> None:
        async with tenant_session(tenant_id) as session:
            session.add(
                ExternalIdentity(
                    tenant_id=tenant_id,
                    person_id=person_id,
                    provider=provider,
                    provider_account_id=account_id,
                    provider_email=None,
                    verification=IdentityVerification.SELF_CONFIRMED,
                    state=state,
                    linked_at=datetime.now(UTC),
                    revoked_at=(None if state is IdentityLinkState.ACTIVE else datetime.now(UTC)),
                    revoked_reason=(
                        None if state is IdentityLinkState.ACTIVE else external.REASON_WITHDRAWN
                    ),
                )
            )
            await session.commit()

    async def test_a_confirmed_slack_account_resolves_to_its_person(
        self, platform: AsyncSession
    ) -> None:
        tenant_id, person_id = await self._workspace(platform)
        await self._link(
            tenant_id, person_id, provider=ConnectorProvider.SLACK, account_id=SLACK_USER
        )

        async with tenant_session(tenant_id) as session:
            resolution = await mentions.resolve_mentions(
                session,
                tenant_id=tenant_id,
                names=[
                    mentions.ProviderActor(
                        provider=ConnectorProvider.SLACK, account_id=SLACK_USER
                    ).mention
                ],
            )

        [mention] = resolution.mentions
        assert mention.person_id == person_id

    async def test_an_unconfirmed_account_stays_unresolved(self, platform: AsyncSession) -> None:
        """No nearest match, and no "there is only one person here so it must be
        them". A blank is honest; a plausible wrong name is not."""
        tenant_id, _ = await self._workspace(platform)

        async with tenant_session(tenant_id) as session:
            resolution = await mentions.resolve_mentions(
                session,
                tenant_id=tenant_id,
                names=[
                    mentions.ProviderActor(
                        provider=ConnectorProvider.GOOGLE_CHAT, account_id=CHAT_USER
                    ).mention
                ],
            )

        [mention] = resolution.mentions
        assert mention.person_id is None
        assert mention.unresolved_reason

    async def test_a_revoked_link_stops_resolving(self, platform: AsyncSession) -> None:
        """Revocation that left resolution working would be cosmetic."""
        tenant_id, person_id = await self._workspace(platform)
        await self._link(
            tenant_id,
            person_id,
            provider=ConnectorProvider.SLACK,
            account_id=SLACK_USER,
            state=IdentityLinkState.REVOKED,
        )

        async with tenant_session(tenant_id) as session:
            person = await external.resolve_person(
                session, provider=ConnectorProvider.SLACK, provider_account_id=SLACK_USER
            )

        assert person is None

    async def test_a_link_in_one_workspace_never_resolves_in_another(
        self, platform: AsyncSession
    ) -> None:
        """The same Slack account id in two workspaces is two different questions.

        Row-level security is what enforces it, so this is asserted through a
        scoped session rather than through a `tenant_id` argument somebody could
        forget to pass.
        """
        first_tenant, first_person = await self._workspace(platform)
        second_tenant, _ = await self._workspace(platform)
        await self._link(
            first_tenant, first_person, provider=ConnectorProvider.SLACK, account_id=SLACK_USER
        )

        async with tenant_session(second_tenant) as session:
            person = await external.resolve_person(
                session, provider=ConnectorProvider.SLACK, provider_account_id=SLACK_USER
            )

        assert person is None


class TestANameCannotAttribute:
    """The path that was retired, asserted as retired."""

    async def test_an_exact_display_name_match_does_not_attribute(
        self, platform: AsyncSession
    ) -> None:
        """**This test would have failed before this step, by passing.**

        A single exact `people.display_name` match used to attribute the fact.
        Two colleagues called Sam are one rename away from inheriting each
        other's work, and the single-match rule made that rarer rather than
        safer. The name is still recorded as a mention — a person reading their
        own record is entitled to see and correct it — it simply no longer
        decides ownership.
        """
        tenant = Tenant(name="Acme", slug=f"name-{uuid.uuid4().hex[:10]}")
        platform.add(tenant)
        await platform.flush()
        platform.add(Person(tenant_id=tenant.id, display_name="Ali Rahman"))
        await platform.commit()

        async with tenant_session(tenant.id) as session:
            resolution = await mentions.resolve_mentions(
                session, tenant_id=tenant.id, names=["Ali Rahman"]
            )

        [mention] = resolution.mentions
        assert mention.person_id is None
        assert mention.unresolved_reason == "a name is not evidence of identity"


class TestNothingSensitiveEscapes:
    """An account id identifies a person to anyone who can read a log store."""

    def test_the_evidence_reader_puts_no_actor_in_the_evidence_id(self) -> None:
        """The evidence id is quoted in briefs, logs and the Trust page."""
        [slack] = jobs._read_evidence(_slack_delivery())
        [chat] = jobs._read_evidence(_chat_delivery())

        assert SLACK_USER not in slack.evidence_id
        assert CHAT_USER not in chat.evidence_id

    def test_no_message_text_reaches_the_actor(self) -> None:
        [evidence] = jobs._read_evidence(_slack_delivery())

        assert evidence.actor is not None
        assert "Shipped" not in evidence.actor.mention
