"""A provider account id must never reach anywhere a person can read.

A Slack `U…`, a Google Chat `users/…` and a GitHub numeric id are private
provider identifiers. They are how CAIRN answers "whose work is this?" and they
are not anybody's name — publishing one to a workspace, on the line that credits
a fact, would identify a colleague by an id they never chose to share.

This file exists because the first implementation of provider attribution stored
exactly that, in `fact_people.mention`, and `mention` turned out to be:

- a **required** field of `FactPersonResponse` in the published OpenAPI document;
- rendered directly as `credits` by `apps/web/src/routes/FeedPage.tsx`;
- used as both the id *and* the display label of a person facet in
  `apps/web/src/brief/adapter.ts`;
- exported into evaluation cases by `evaluation/corrections.py`.

None of that was malicious or careless — `mention` had meant "a name" for the
whole life of the product, and the new value simply inherited every path the old
one already had. That is why the guarantee is now structural: the account id
lives in its own column, `FactPersonResponse` has no field it could travel in,
and the tests below fail if either of those facts stops being true.
"""

from __future__ import annotations

import uuid

import pytest
from cairn_api.api.routers import facts as facts_router
from cairn_api.api.schemas import FactPersonResponse
from cairn_api.db.connector_models import ConnectorProvider
from cairn_api.db.fact_models import FactPerson
from cairn_api.pipeline import jobs, mentions, store

pytestmark = pytest.mark.integration

SLACK_USER = "U0SECRET42"
CHAT_USER = "users/9988776655"


class TestTheAccountIdHasNowhereToTravel:
    """The response model, checked field by field."""

    def test_the_published_person_shape_has_no_account_field(self) -> None:
        """An exact set, so a field added later fails here rather than shipping.

        The names are checked as well as the count: a future `providerId` or
        `actorId` would be the same disclosure under a different spelling.
        """
        assert set(FactPersonResponse.model_fields) == {"mention", "person_id"}

    def test_no_field_name_suggests_a_provider_account(self) -> None:
        forbidden = ("provider", "account", "actor", "external", "slack", "chat", "github")
        for name in FactPersonResponse.model_fields:
            assert not any(word in name.lower() for word in forbidden), (
                f"{name!r} looks like a provider identifier on a published model"
            )

    def test_the_serializer_drops_actor_rows_entirely(self) -> None:
        """Not blanked — absent.

        A row with a null mention and a real `personId` would still be a
        published record of "somebody CAIRN cannot name did this", which is
        noise on a credit line rather than information.
        """
        rows = [
            FactPerson(tenant_id=uuid.uuid4(), mention="Ali Rahman", person_id=None),
            FactPerson(
                tenant_id=uuid.uuid4(),
                mention=None,
                provider=ConnectorProvider.SLACK.value,
                provider_account_id=SLACK_USER,
            ),
        ]

        published = [item for item in rows if item.mention is not None]

        assert len(published) == 1
        assert published[0].mention == "Ali Rahman"

    def test_the_response_module_filters_on_mention(self) -> None:
        """Reads the production source rather than trusting the comment above it.

        A future edit that drops the filter reinstates the leak silently, and no
        behavioural test would catch it until a Slack workspace was connected.
        """
        import inspect

        source = inspect.getsource(facts_router._fact_response)

        assert "if link.mention is not None" in source, (
            "the fact serializer no longer excludes actor rows — a provider "
            "account id will be published as a credit"
        )


class TestTheSentinelStopsAtTheDatabase:
    """In-memory encoding, structured storage."""

    def test_a_provider_mention_becomes_columns_and_a_null_mention(self) -> None:
        tenant_id = uuid.uuid4()
        encoded = mentions.ProviderActor(
            provider=ConnectorProvider.SLACK, account_id=SLACK_USER
        ).mention

        row = store._person_row(tenant_id, encoded)

        assert row.mention is None
        assert row.provider == ConnectorProvider.SLACK.value
        assert row.provider_account_id == SLACK_USER

    def test_a_human_name_stays_a_mention_and_gets_no_columns(self) -> None:
        row = store._person_row(uuid.uuid4(), "Ali Rahman")

        assert row.mention == "Ali Rahman"
        assert row.provider is None
        assert row.provider_account_id is None

    def test_the_two_shapes_deduplicate_independently(self) -> None:
        """Reprocessing one delivery must not append a second actor row.

        The stored row has a null mention, so a dedup keyed on incoming strings
        would never match it — and the partial unique index would then refuse
        the insert, turning an ordinary redelivery into a failed job.
        """
        encoded = mentions.ProviderActor(
            provider=ConnectorProvider.GOOGLE_CHAT, account_id=CHAT_USER
        ).mention
        stored = store._person_row(uuid.uuid4(), encoded)

        assert store._person_key(stored) == store._incoming_key(encoded)
        assert store._person_key(stored) != store._incoming_key("Ali Rahman")


class TestNothingRendersAnAccountId:
    """The other paths `mention` already had."""

    def test_the_domain_fact_carries_names_only(self) -> None:
        """`Fact.people` feeds the brief, the feed and every export built on it."""
        import inspect

        source = inspect.getsource(store)

        assert "people=[p.mention for p in row.people if p.mention is not None]" in source, (
            "the row-to-domain mapping no longer filters actor rows — a provider "
            "account id will reach the brief and every export"
        )

    def test_the_evaluation_export_carries_names_only(self) -> None:
        """Evaluation cases are diffed, committed and shared more freely than
        production data, so an account id there travels further than anywhere
        else in the product."""
        import inspect

        from cairn_api.evaluation import corrections

        source = inspect.getsource(corrections)

        assert source.count("if link.mention is not None") >= 2, (
            "an evaluation export no longer filters actor rows"
        )

    def test_the_evidence_id_never_contains_the_actor(self) -> None:
        """Evidence ids are quoted in briefs, logs, the Trust page and errors."""
        delivery_payload = {
            "type": "event_callback",
            "team_id": "T0ACME",
            "event": {
                "type": "message",
                "channel": "C0ENG",
                "ts": "1700000000.000100",
                "text": "Shipped it.",
                "user": SLACK_USER,
            },
        }
        from cairn_api.db.github_models import WebhookDelivery

        [evidence] = jobs._read_evidence(
            WebhookDelivery(delivery_id="d1", event_type="message", payload=delivery_payload)
        )

        assert evidence.actor is not None
        assert evidence.actor.account_id == SLACK_USER
        assert SLACK_USER not in evidence.evidence_id
        assert SLACK_USER not in (evidence.url or "")
        assert SLACK_USER not in evidence.text
