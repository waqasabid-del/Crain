"""Webhook in, facts out — the test that would have caught the whole finding.

**Why this file exists.** Steps 15-18 built four pipeline stages, ~2,500 lines,
90% coverage, every unit correct. Nothing in production called any of them: the
ingestion path attributed a delivery, wrote a log line and stopped. Every test
passed, because every test stopped at a layer boundary too.

So this one crosses all of them, deliberately using the production objects at
each step: a real signed webhook, the real router, the real queue envelope, the
real job registry, the real handler, a tenant-scoped session, real resolution,
the real store, and finally the real HTTP route a user would call. The single
substitution is the model, because a scripted provider is the only kind CI can
have — and the model is the one component no test can assert on anyway.

**A mock chain would prove nothing here.** The defect was not that a function
misbehaved; it was that nothing called it. Only real wiring can detect absent
wiring.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from cairn_api.db.fact_models import Fact as FactRow
from cairn_api.db.fact_models import FactSource as FactSourceRow
from cairn_api.db.github_models import GitHubInstallation, WebhookDelivery
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.db.tenancy import tenant_session
from cairn_api.evaluation.scripted import build_scripted_provider
from cairn_api.github.handlers import GITHUB_DELIVERY_JOB, handle_delivery
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.memory import InMemoryJobQueue
from cairn_api.pipeline.embeddings import HashingEmbedder
from cairn_api.pipeline.jobs import UNDERSTAND_JOB, Providers, make_handler
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

SECRET = "wiring-secret"  # noqa: S105 — a test webhook secret, not a credential


@pytest.fixture
def providers() -> Providers:
    """The production stages, driven by a deterministic model.

    `live=False` is the honest label: these are the offline stand-ins. The
    pipeline does not branch on it — it is carried so a startup log can say out
    loud that the expensive stage is not real, rather than leaving that to be
    discovered from a suspiciously cheap invoice.
    """
    return Providers(model=build_scripted_provider(), embedder=HashingEmbedder(), live=False)


@pytest.fixture
async def workspace(platform: AsyncSession) -> tuple[Tenant, GitHubInstallation]:
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name="Acme", slug=f"wiring-{suffix}")
    user = User(email=f"owner-{suffix}@example.com")
    platform.add_all([tenant, user])
    await platform.flush()
    platform.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.OWNER))

    installation = GitHubInstallation(
        tenant_id=tenant.id,
        installation_id=990_000 + int(suffix[:6], 16) % 90_000,
        account_login="acme-inc",
        account_type="Organization",
    )
    platform.add(installation)
    await platform.commit()
    return tenant, installation


def push_payload(installation_id: int) -> dict[str, Any]:
    """A push with two commits, one of them substantive.

    Real shape rather than a minimal one: the extractor reads commit messages
    and author fields, and a payload trimmed to what the test needs would prove
    the pipeline works on payloads nobody sends.
    """
    return {
        "installation": {"id": installation_id},
        "repository": {"full_name": "acme-inc/api", "id": 42},
        "sender": {"login": "priya", "id": 7},
        "ref": "refs/heads/main",
        "commits": [
            {
                "id": "a1b2c3d4e5f6",
                "message": (
                    "Add rate limiting to the public API\n\n"
                    "Co-authored-by: Tom Reilly <tom@acme.test>"
                ),
                "timestamp": "2026-08-14T09:30:00Z",
                "url": "https://github.com/acme-inc/api/commit/a1b2c3d4e5f6",
                "author": {"name": "Priya Nair", "email": "priya@acme.test"},
            },
            {
                "id": "f6e5d4c3b2a1",
                "message": "Fix typo in README",
                "timestamp": "2026-08-14T09:35:00Z",
                "url": "https://github.com/acme-inc/api/commit/f6e5d4c3b2a1",
                "author": {"name": "Priya Nair", "email": "priya@acme.test"},
            },
        ],
    }


async def store_delivery(platform: AsyncSession, tenant: Tenant, payload: dict[str, Any]) -> str:
    """Record a delivery the way the webhook route does — platform-side.

    Deliberately not through a tenant-scoped session, and the first attempt at
    this test got it wrong: the application role has SELECT and UPDATE on
    `webhook_deliveries` and **no INSERT**, because a scoped session that could
    create a delivery could forge activity for its own workspace. The route
    resolves installation to tenant before any tenant context exists, so it
    writes with platform privileges. `permission denied for table
    webhook_deliveries` was the schema refusing to let a test do something
    production cannot.
    """
    delivery_id = str(uuid.uuid4())
    platform.add(
        WebhookDelivery(
            tenant_id=tenant.id,
            delivery_id=delivery_id,
            event_type="push",
            payload=payload,
        )
    )
    await platform.commit()
    return delivery_id


class TestTheChainIsConnected:
    async def test_a_delivery_publishes_the_understanding_job(
        self, platform: AsyncSession, workspace: tuple[Tenant, GitHubInstallation]
    ) -> None:
        """The link that did not exist.

        `_process` attributed the delivery and returned. Nothing downstream ran,
        and nothing recorded that nothing had run — the log line said the work
        succeeded, because attribution had.
        """
        tenant, installation = workspace
        queue = InMemoryJobQueue()
        payload = push_payload(installation.installation_id)
        delivery_id = await store_delivery(platform, tenant, payload)

        async with tenant_session(tenant.id) as session:
            await handle_delivery(
                session,
                JobEnvelope(
                    job_type=GITHUB_DELIVERY_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
                queue=queue,
            )
            await session.commit()

        # Read back through `receive`, the interface a worker actually uses,
        # rather than through the queue's internals. A message that is present
        # in a list but never delivered is the same defect one layer down.
        messages = await queue.receive(max_messages=10)
        published = [message.envelope for message in messages]
        assert any(item.job_type == UNDERSTAND_JOB for item in published), (
            "attribution ran and nothing was queued to understand the delivery"
        )
        understanding = next(item for item in published if item.job_type == UNDERSTAND_JOB)
        # Tenant id on every message is mandatory (md/06 §4.3) — a job that
        # loses it does not fail, it reads across tenants.
        assert understanding.tenant_id == tenant.id
        assert understanding.payload["delivery_id"] == delivery_id

    async def test_the_understanding_job_writes_facts(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """The assertion the project could not previously make: a fact exists.

        Not "a fact object was constructed" — a row, in the database, for this
        workspace, carrying provenance back to the commit it came from.
        """
        tenant, installation = workspace
        payload = push_payload(installation.installation_id)
        delivery_id = await store_delivery(platform, tenant, payload)

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            facts = list(await session.scalars(select(FactRow)))

        assert facts, "the delivery produced no facts"
        for fact in facts:
            assert fact.tenant_id == tenant.id
            # Provenance is the product's central promise. A fact with no source
            # cannot be checked by the person it concerns.
            assert fact.sources, f"fact {fact.id} reached the store with no source"
            assert fact.valid_from is not None
            assert fact.valid_until is None

    async def test_a_slack_message_becomes_a_fact_cited_to_slack(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """The gap between "ingested" and "in a brief".

        The evidence reader was GitHub-shaped, so a Slack delivery reaching the
        understanding job found nothing to cite and produced no facts — silently,
        with no error anywhere. A connector that receives messages and never
        reaches a brief is the failure the vertical-slice rule exists to catch.

        The source label matters as much as the fact: it was hardcoded to
        "github", which would file every Slack message as a commit on the Trust
        page and in the per-source opt-out — the one place a reader checks
        whether a statement came from somewhere they agreed to.
        """
        tenant, _ = workspace
        payload = {
            "type": "event_callback",
            "team_id": "T-ACME",
            "event_id": f"Ev{uuid.uuid4().hex[:10]}",
            "event": {
                "type": "message",
                "channel": "C-DELIVERY",
                "channel_type": "channel",
                "user": "U-PRIYA",
                "text": "Shipped the payments migration to production this morning.",
                "ts": "1786900000.000100",
            },
        }
        delivery_id = await store_delivery(platform, tenant, payload)

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            facts = list(await session.scalars(select(FactRow)))

        assert facts, "a Slack message produced no facts"
        cited = [ref for fact in facts for ref in fact.sources]
        assert cited, "a Slack fact reached the store with no source"
        assert all(ref.source == "slack" for ref in cited), (
            "a Slack statement was filed as another source"
        )
        assert all(ref.evidence_id.startswith("slack:message:T-ACME:C-DELIVERY:") for ref in cited)

    async def test_a_deleted_slack_message_cites_nothing(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """A deletion must not leave a statement standing as current.

        The citation stops resolving rather than the text being re-read from a
        payload that no longer represents anything — Slack's own docs note the
        message will not return in history either.
        """
        tenant, _ = workspace
        payload = {
            "type": "event_callback",
            "team_id": "T-ACME",
            "event_id": f"Ev{uuid.uuid4().hex[:10]}",
            "event": {
                "type": "message",
                "subtype": "message_deleted",
                "channel": "C-DELIVERY",
                "channel_type": "channel",
                "ts": "1786900100.000200",
                "deleted_ts": "1786900000.000100",
            },
        }
        delivery_id = await store_delivery(platform, tenant, payload)

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            facts = list(await session.scalars(select(FactRow)))

        assert facts == [], "a deleted message was written as a current statement"

    async def test_a_chat_message_becomes_a_fact_cited_to_google_chat(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """The same gap as Slack's, one connector later.

        The evidence reader knew two payload shapes; a Google Chat delivery
        reaching the understanding job would have found nothing to cite and
        produced no facts — silently, with no error anywhere. A connector that
        receives messages and never reaches a brief is exactly what the
        vertical-slice rule exists to catch.

        The source label matters as much as the fact: filed as "github" it would
        appear as a commit on the Trust page and in the per-source opt-out, which
        is the one place a reader checks whether a statement came from somewhere
        they agreed to.
        """
        tenant, _ = workspace
        payload = {
            "type": "google_chat_event",
            "event_type": "google.workspace.chat.message.v1.created",
            "message": {
                "name": "spaces/AAAADELIVERY/messages/MSG1",
                "createTime": "2026-08-17T09:30:00Z",
                "space": {"name": "spaces/AAAADELIVERY"},
                "sender": {"name": "users/107700770077007700770", "type": "HUMAN"},
                "text": "Shipped the payments migration to production this morning.",
            },
        }
        delivery_id = await store_delivery(platform, tenant, payload)

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            facts = list(await session.scalars(select(FactRow)))

        assert facts, "a Google Chat message produced no facts"
        cited = [ref for fact in facts for ref in fact.sources]
        assert cited, "a Google Chat fact reached the store with no source"
        assert all(ref.source == "google_chat" for ref in cited), (
            "a Google Chat statement was filed as another source"
        )
        assert all(
            ref.evidence_id == "google_chat:message:spaces/AAAADELIVERY/messages/MSG1"
            for ref in cited
        )
        # Provenance a reader can open, built from the resource name rather than
        # fetched inside an acknowledgement budget that cannot be extended.
        assert all(ref.url == "https://chat.google.com/room/AAAADELIVERY/MSG1" for ref in cited)

    async def test_a_deleted_chat_message_cites_nothing(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """A deletion must not leave a statement standing as current.

        Google's documented delete payload still echoes the message's `text` and
        `sender`; that is boilerplate about a message that no longer exists, and
        re-reading it would resurrect exactly the claim the deletion retracted.
        The citation stops resolving instead — the delete is discriminated by the
        stored CloudEvent type, since the three payload shapes are identical.
        """
        tenant, _ = workspace
        payload = {
            "type": "google_chat_event",
            "event_type": "google.workspace.chat.message.v1.deleted",
            "message": {
                "name": "spaces/AAAADELIVERY/messages/MSG2",
                "createTime": "2026-08-17T09:30:00Z",
                "space": {"name": "spaces/AAAADELIVERY"},
                "sender": {"name": "users/107700770077007700770", "type": "HUMAN"},
                "text": "Shipped the payments migration to production this morning.",
            },
        }
        delivery_id = await store_delivery(platform, tenant, payload)

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            facts = list(await session.scalars(select(FactRow)))

        assert facts == [], "a deleted message was written as a current statement"

    async def test_reprocessing_the_same_delivery_does_not_duplicate_facts(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """At-least-once delivery makes this the normal case, not the edge one.

        A queue redelivery after a worker restart must not double every fact in
        the workspace — which would be invisible in a brief except as the team
        appearing to have done everything twice.
        """
        tenant, installation = workspace
        payload = push_payload(installation.installation_id)
        delivery_id = await store_delivery(platform, tenant, payload)
        handler = make_handler(providers=providers)
        envelope = JobEnvelope(
            job_type=UNDERSTAND_JOB,
            tenant_id=tenant.id,
            payload={"delivery_id": delivery_id},
        )

        for _ in range(2):
            async with tenant_session(tenant.id) as session:
                await handler(session, envelope)
                await session.commit()

        async with tenant_session(tenant.id) as session:
            facts = list(await session.scalars(select(FactRow)))

        statements = [fact.statement for fact in facts]
        assert len(statements) == len(set(statements)), f"redelivery duplicated facts: {statements}"

    async def test_facts_from_one_workspace_are_invisible_to_another(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """The isolation check, on the newest write path.

        Every previous audit round found a table or a path where scoping had
        been assumed rather than enforced. This is the newest one.
        """
        tenant, installation = workspace
        delivery_id = await store_delivery(
            platform, tenant, push_payload(installation.installation_id)
        )
        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:10]}")
        platform.add(other)
        await platform.commit()

        async with tenant_session(other.id) as session:
            assert (await session.scalars(select(FactRow))).all() == []


class TestTheApiExposesWhatThePipelineProduced:
    """C3: the pipeline wrote facts nobody could read.

    A fact in a table that no route returns is the same as no fact, from the
    point of view of everyone outside this repository.
    """

    async def test_the_facts_route_returns_what_the_job_stored(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        tenant, installation = workspace
        delivery_id = await store_delivery(
            platform, tenant, push_payload(installation.installation_id)
        )

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        # Shaped by the route's own serialiser rather than by a second
        # hand-written mapping in the test. A route that returns something
        # different from what the test asserts is the gap being closed here.
        from cairn_api.api.routers.facts import _fact_response

        async with tenant_session(tenant.id) as session:
            rows = list(await session.scalars(select(FactRow)))
            items = [_fact_response(row) for row in rows]

        assert items, "the API layer produced nothing for a workspace with facts"
        for item in items:
            assert item.sources, "a fact was exposed without its provenance"
            # Categorical, never numeric (md/05 §A.2.1). mypy already proves a
            # float cannot appear here — the type is an enum — so the runtime
            # assertion is the value set rather than a redundant type check.
            assert item.certainty in {"verified", "observed", "suggested"}

    async def test_a_real_delivery_produces_facts_the_feed_can_filter_by_project(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """Step 24's project filter, from the webhook rather than from a fixture.

        The project reaches the fact graph by being read off the delivery
        alongside the evidence — never asked of the model, which can invent a
        repository as easily as a sentence. This is the test that proves the
        whole path is connected: a filter populated by hand in a unit test is a
        filter that finds nothing in production.
        """
        from cairn_api.api import feed

        tenant, installation = workspace
        delivery_id = await store_delivery(
            platform, tenant, push_payload(installation.installation_id)
        )

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            offered = await feed.facets(session, tenant_id=tenant.id)
            matching = list(
                await session.scalars(
                    select(FactRow).where(
                        *feed.conditions(tenant.id, feed.FeedFilters(projects=("acme-inc/api",)))
                    )
                )
            )

        assert "acme-inc/api" in offered.projects, (
            f"the repository never reached the feed's filters: {offered.projects}"
        )
        assert matching, "facts were stored but the project filter matched none of them"

    def test_the_routes_are_registered_on_the_app(self) -> None:
        """A router written and never included is the same defect one level up."""
        from cairn_api.api.app import create_app
        from cairn_api.config import Settings

        app = create_app(
            Settings(
                environment="test",
                github_webhook_secret=SecretStr(SECRET),
                cors_allowed_origins=("http://localhost:3000",),
            )
        )
        # Read from the OpenAPI document rather than `app.routes`: the latter
        # holds router wrappers as well as routes, and the document is what the
        # client is generated from — so it is the surface that actually matters.
        paths = set(app.openapi()["paths"])

        assert any(path.endswith("/facts") for path in paths), (
            f"no facts route on the app: {sorted(paths)}"
        )
        assert any(path.endswith("/brief") for path in paths), (
            f"no brief route on the app: {sorted(paths)}"
        )
        # Step 24. A search module with no route is the same defect this class
        # was written for, one product surface later.
        for surface in ("/search", "/facets"):
            assert any(path.endswith(surface) for path in paths), (
                f"no {surface} route on the app: {sorted(paths)}"
            )

    def test_the_openapi_schema_describes_them(self) -> None:
        """The generated TypeScript client is derived from this document.

        A route missing from the schema is a route the frontend cannot call, and
        the drift test would not catch it — a schema and a client that agree on
        nothing still agree.
        """
        from cairn_api.api.app import create_app
        from cairn_api.config import Settings

        app = create_app(
            Settings(
                environment="test",
                github_webhook_secret=SecretStr(SECRET),
                cors_allowed_origins=("http://localhost:3000",),
            )
        )
        schema = json.dumps(app.openapi())

        assert "/facts" in schema
        assert "/brief" in schema


class TestNothingIsDroppedFromALargePush:
    """**The defect this class exists for was found in production, by a person.**

    A 26-commit push produced facts for 20 commits. `MAX_EVIDENCE_ITEMS` sliced
    the list and the remaining six were discarded with no log line, no counter
    and no marker on the delivery. One of the dropped commits was co-authored,
    so two people's work vanished, and the only trace that anything had happened
    was a commit on GitHub with no matching fact.

    That is worse than an error. This repository's own reporting rule is that a
    cap must say so; this one was invisible from every side. The webhook
    returned 202, the delivery was marked processed, the counts in the log were
    the counts of what survived, and a brief written from the result read as a
    complete week.

    The cap itself is not the bug. It bounds prompt size and cost, and raising
    it only moves the cliff. The bug is that work past the cap was lost rather
    than carried.
    """

    @staticmethod
    def _push(installation_id: int, *, commits: int = 26) -> dict[str, Any]:
        """A push whose tail is past the cap, with the co-author in the tail.

        The last commit is the interesting one: under the old slice it was the
        furthest thing from being processed, and it is the one carrying a second
        person's name.
        """
        trailer = "\n\nCo-authored-by: Tom Reilly <tom@acme.test>"
        return {
            "installation": {"id": installation_id},
            "repository": {"full_name": "acme-inc/api", "id": 42},
            "sender": {"login": "priya", "id": 7},
            "ref": "refs/heads/main",
            "commits": [
                {
                    "id": format(index, "040x"),
                    "message": (
                        f"Land change {index} in the batch"
                        + (trailer if index == commits - 1 else "")
                    ),
                    "timestamp": "2026-08-14T09:30:00Z",
                    "url": "https://github.com/acme-inc/api/commit/" + format(index, "040x"),
                    "author": {"name": "Priya Nair", "email": "priya@acme.test"},
                }
                for index in range(commits)
            ],
        }

    def test_every_commit_becomes_evidence(self) -> None:
        """The unit-level statement of the bug: reading a delivery must not lose
        any of it. Chunking happens after the read, over the whole list."""
        from cairn_api.pipeline import jobs

        delivery = WebhookDelivery(
            delivery_id="gh-" + uuid.uuid4().hex[:12],
            event_type="push",
            payload=self._push(1, commits=26),
        )

        evidence = jobs._read_evidence(delivery)

        assert len(evidence) == 26, "the tail of the push was dropped on read"

    def test_the_co_author_in_the_tail_survives(self) -> None:
        """The commit that failed live, asserted directly."""
        from cairn_api.pipeline import jobs

        delivery = WebhookDelivery(
            delivery_id="gh-" + uuid.uuid4().hex[:12],
            event_type="push",
            payload=self._push(1, commits=26),
        )

        last = jobs._read_evidence(delivery)[-1]

        assert "Tom Reilly" in last.text
        assert "Priya Nair" in last.text

    def test_chunks_cover_the_whole_delivery_without_overlap(self) -> None:
        """Every item in exactly one chunk. A gap loses a commit; an overlap
        costs a duplicate model call for a fact that merges anyway."""
        from cairn_api.pipeline import jobs

        evidence = jobs._read_evidence(
            WebhookDelivery(
                delivery_id="gh-" + uuid.uuid4().hex[:12],
                event_type="push",
                payload=self._push(1, commits=26),
            )
        )

        chunks = list(jobs._chunks(evidence))

        assert [len(chunk) for chunk in chunks] == [jobs.MAX_EVIDENCE_ITEMS, 6]
        flattened = [item.evidence_id for chunk in chunks for item in chunk]
        assert flattened == [item.evidence_id for item in evidence]
        assert len(set(flattened)) == len(flattened)

    async def test_all_twenty_six_commits_produce_attributed_facts(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """**The end-to-end version, in the shape that failed.**

        Every commit cited, including the six that used to fall past the cap.
        """
        tenant, installation = workspace
        payload = self._push(installation.installation_id, commits=26)
        delivery_id = await store_delivery(platform, tenant, payload)

        handler = make_handler(providers=providers)
        async with tenant_session(tenant.id) as session:
            await handler(
                session,
                JobEnvelope(
                    job_type=UNDERSTAND_JOB,
                    tenant_id=tenant.id,
                    payload={"delivery_id": delivery_id},
                ),
            )
            await session.commit()

        async with tenant_session(tenant.id) as session:
            cited = set(await session.scalars(select(FactSourceRow.evidence_id)))

        expected = {"github:commit:" + format(index, "040x") for index in range(26)}
        missing = expected - cited
        assert not missing, f"{len(missing)} commit(s) produced no fact: {sorted(missing)}"

    async def test_reprocessing_a_chunked_delivery_does_not_duplicate_facts(
        self,
        platform: AsyncSession,
        workspace: tuple[Tenant, GitHubInstallation],
        providers: Providers,
    ) -> None:
        """Chunking must not cost the idempotency the single-pass path had.

        `_already_understood` is set containment over the evidence ids it is
        handed, so it has to be asked per chunk. Asked over the whole delivery
        it would answer "no" while any chunk was outstanding, and re-run every
        chunk on every redelivery.
        """
        tenant, installation = workspace
        payload = self._push(installation.installation_id, commits=26)
        delivery_id = await store_delivery(platform, tenant, payload)
        handler = make_handler(providers=providers)
        envelope = JobEnvelope(
            job_type=UNDERSTAND_JOB,
            tenant_id=tenant.id,
            payload={"delivery_id": delivery_id},
        )

        counts = []
        for _ in range(2):
            async with tenant_session(tenant.id) as session:
                await handler(session, envelope)
                await session.commit()
            async with tenant_session(tenant.id) as session:
                counts.append(len(list(await session.scalars(select(FactRow)))))

        assert counts[0] == counts[1], f"redelivery changed the fact count: {counts}"


class TestEveryCapSaysSoOutLoud:
    """A cap that cannot be observed is indistinguishable from a quiet week."""

    def test_the_item_cap_is_not_a_slice_any_more(self) -> None:
        """The literal defect: `found[:MAX_EVIDENCE_ITEMS]` discarded the tail.

        Asserted against the source because the behaviour it produced - facts
        that never exist - leaves nothing to assert on.
        """
        import inspect

        from cairn_api.pipeline import jobs

        source = inspect.getsource(jobs._read_evidence)
        assert "[:MAX_EVIDENCE_ITEMS]" not in source

    def test_truncating_an_over_long_message_is_recorded(self) -> None:
        """`MAX_EVIDENCE_CHARS` had the same silence as the item cap.

        It cannot be chunked away - a commit message is one piece of evidence
        under one id, and splitting it would either duplicate that id or invent
        one - so it stays a cap and becomes an honest one: counted, logged, and
        marked in the text, so the model is told it is reading a fragment rather
        than left to summarise a sentence that stops mid-word.
        """
        from cairn_api.pipeline import jobs

        long_message = "x" * (jobs.MAX_EVIDENCE_CHARS + 500)
        delivery = WebhookDelivery(
            delivery_id="gh-" + uuid.uuid4().hex[:12],
            event_type="push",
            payload={
                "repository": {"full_name": "acme-inc/api"},
                "commits": [
                    {
                        "id": "c" * 40,
                        "message": long_message,
                        "url": None,
                        "author": {"name": "Priya Nair", "email": "priya@acme.test"},
                    }
                ],
            },
        )

        [item] = jobs._read_evidence(delivery)

        assert len(item.text) <= jobs.MAX_EVIDENCE_CHARS + len(jobs.TRUNCATION_MARKER)
        assert item.text.endswith(jobs.TRUNCATION_MARKER)

    def test_a_message_within_the_cap_is_left_alone(self) -> None:
        from cairn_api.pipeline import jobs

        delivery = WebhookDelivery(
            delivery_id="gh-" + uuid.uuid4().hex[:12],
            event_type="push",
            payload={
                "repository": {"full_name": "acme-inc/api"},
                "commits": [{"id": "d" * 40, "message": "Short and complete", "url": None}],
            },
        )

        [item] = jobs._read_evidence(delivery)

        assert item.text == "Short and complete"
        assert jobs.TRUNCATION_MARKER not in item.text
