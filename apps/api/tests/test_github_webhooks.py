"""GitHub webhook receipt.

Step 11's exit criterion: *a real webhook is delivered, verified, enqueued and
acknowledged under 10s; a duplicate delivery upserts rather than duplicating.*

The signature tests carry the most weight in this file. This is the only
unauthenticated write endpoint in the service, and everything downstream —
tenant resolution, storage, the queue — trusts it. Every forgery below is
constructed the way an attacker would rather than by patching verification out:
a test that disables the control proves the handler works when the control is
absent, which is not a property anyone wants.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest
from cairn_api.api.app import create_app
from cairn_api.config import Settings
from cairn_api.db.github_models import DeliveryStatus, GitHubInstallation, WebhookDelivery
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.github.handlers import GITHUB_DELIVERY_JOB, handle_delivery
from cairn_api.github.signatures import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    SignatureError,
    sign,
    verify,
)
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.jobs.memory import InMemoryJobQueue
from cairn_api.jobs.runner import JobRegistry
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Every secret in this file is a literal by necessity.
# ruff: noqa: S105, S106
SECRET = "webhook-secret-for-tests"
INSTALLATION_ID = 987654321


# --------------------------------------------------------------------------
# Signature verification
# --------------------------------------------------------------------------


class TestSignatureVerification:
    def test_a_correct_signature_verifies(self) -> None:
        payload = b'{"action":"opened"}'

        verify(payload, sign(payload, SECRET), SECRET)  # does not raise

    def test_a_missing_header_is_rejected(self) -> None:
        # The catastrophic implementation is `if signature: verify(...)`, which
        # accepts every request that simply omits the header.
        with pytest.raises(SignatureError, match="Missing signature"):
            verify(b"{}", None, SECRET)

    def test_a_blank_secret_refuses_rather_than_passing(self) -> None:
        # An empty secret makes every signature verifiable. Failing here turns a
        # misconfiguration into an outage instead of an open door.
        with pytest.raises(SignatureError, match="No webhook secret"):
            verify(b"{}", sign(b"{}", ""), "")

    def test_a_sha1_signature_is_not_accepted(self) -> None:
        # GitHub still sends the SHA-1 header for compatibility. Accepting it
        # means the collision-broken one is what an attacker forges.
        import hashlib
        import hmac

        payload = b'{"action":"opened"}'
        sha1 = hmac.new(SECRET.encode(), payload, hashlib.sha1).hexdigest()

        with pytest.raises(SignatureError, match="not sha256"):
            verify(payload, f"sha1={sha1}", SECRET)

    def test_a_signature_for_different_bytes_is_rejected(self) -> None:
        # The realistic attack: capture a legitimate signed delivery, alter the
        # body, replay it.
        original = b'{"action":"opened","number":1}'
        tampered = b'{"action":"opened","number":2}'

        with pytest.raises(SignatureError, match="does not match"):
            verify(tampered, sign(original, SECRET), SECRET)

    def test_a_signature_from_a_different_secret_is_rejected(self) -> None:
        payload = b"{}"

        with pytest.raises(SignatureError, match="does not match"):
            verify(payload, sign(payload, "some-other-secret"), SECRET)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def webhook_app(queue: InMemoryJobQueue) -> FastAPI:
    """An app with a known webhook secret and an inspectable queue."""
    app = create_app(
        Settings(
            environment="test",
            cors_allowed_origins=("http://localhost:3000",),
            github_webhook_secret=SECRET,
        )
    )
    app.state.queue = queue
    return app


@pytest.fixture
async def installation(platform: AsyncSession) -> GitHubInstallation:
    """A workspace with an active GitHub installation."""
    suffix = uuid.uuid4().hex[:10]
    tenant = Tenant(name="Acme", slug=f"acme-{suffix}")
    user = User(email=f"owner-{suffix}@example.com")
    platform.add_all([tenant, user])
    await platform.flush()
    platform.add(Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.OWNER))

    record = GitHubInstallation(
        tenant_id=tenant.id,
        # Unique per test: the column is globally unique, and a shared value
        # would make these pass or fail by execution order.
        installation_id=INSTALLATION_ID + int(suffix[:6], 16) % 100_000,
        account_login="acme-inc",
        account_type="Organization",
    )
    platform.add(record)
    await platform.commit()
    return record


def push_payload(installation_id: int, *, action: str | None = "opened") -> dict[str, Any]:
    return {
        "action": action,
        "installation": {"id": installation_id},
        "repository": {"full_name": "acme-inc/api", "id": 42},
        "sender": {"login": "priya", "id": 7},
    }


async def deliver(
    app: FastAPI,
    payload: dict[str, Any],
    *,
    event: str = "pull_request",
    delivery_id: str | None = None,
    secret: str = SECRET,
    signature: str | None = None,
) -> Any:
    """Send a webhook the way GitHub would.

    The body is serialised once and *that byte string* is both signed and sent.
    Re-serialising between signing and sending would change the bytes and fail
    verification for reasons unrelated to the test.
    """
    body = json.dumps(payload).encode("utf-8")
    headers = {
        EVENT_HEADER: event,
        DELIVERY_HEADER: delivery_id or str(uuid.uuid4()),
        SIGNATURE_HEADER: signature if signature is not None else sign(body, secret),
        "Content-Type": "application/json",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post("/v1/webhooks/github", content=body, headers=headers)


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------


class TestWebhookEndpoint:
    async def test_a_verified_delivery_is_recorded_and_enqueued(
        self,
        webhook_app: FastAPI,
        queue: InMemoryJobQueue,
        installation: GitHubInstallation,
        platform: AsyncSession,
    ) -> None:
        """The exit criterion's happy path."""
        delivery_id = str(uuid.uuid4())

        response = await deliver(
            webhook_app,
            push_payload(installation.installation_id),
            delivery_id=delivery_id,
        )

        assert response.status_code == 202
        assert response.json() == {"status": "accepted"}

        row = await platform.scalar(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        assert row is not None
        assert row.tenant_id == installation.tenant_id
        assert row.status is DeliveryStatus.ACCEPTED

        messages = await queue.receive(max_messages=5)
        assert len(messages) == 1
        assert messages[0].envelope.job_type == GITHUB_DELIVERY_JOB
        # The tenant is on the envelope, which is what makes the worker's
        # session scoped. A job without it cannot be constructed at all.
        assert messages[0].envelope.tenant_id == installation.tenant_id
        assert messages[0].envelope.payload == {"delivery_id": delivery_id}

    async def test_acknowledgement_is_far_inside_githubs_ten_second_budget(
        self, webhook_app: FastAPI, installation: GitHubInstallation
    ) -> None:
        # Miss the 10s budget and GitHub marks the delivery failed and retries,
        # so slow processing becomes duplicate processing — the naive listener's
        # failure mode, where load causes more load.
        started = time.perf_counter()
        response = await deliver(webhook_app, push_payload(installation.installation_id))
        elapsed = time.perf_counter() - started

        assert response.status_code == 202
        assert elapsed < 1.0, f"took {elapsed:.2f}s; GitHub allows 10s"

    async def test_a_forged_signature_is_rejected(
        self, webhook_app: FastAPI, queue: InMemoryJobQueue, installation: GitHubInstallation
    ) -> None:
        response = await deliver(
            webhook_app,
            push_payload(installation.installation_id),
            secret="attacker-guessed-this",
        )

        assert response.status_code == 401
        # Nothing was enqueued: rejection happens before any work.
        assert await queue.receive(max_messages=5) == []

    async def test_an_unsigned_request_is_rejected(
        self, webhook_app: FastAPI, installation: GitHubInstallation
    ) -> None:
        body = json.dumps(push_payload(installation.installation_id)).encode()
        async with AsyncClient(
            transport=ASGITransport(app=webhook_app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/v1/webhooks/github",
                content=body,
                headers={EVENT_HEADER: "push", DELIVERY_HEADER: str(uuid.uuid4())},
            )

        assert response.status_code == 401

    async def test_the_rejection_does_not_say_what_was_wrong(
        self, webhook_app: FastAPI, installation: GitHubInstallation
    ) -> None:
        # Telling a forger which part of their signature failed tells them how
        # to fix it.
        missing = await deliver(
            webhook_app, push_payload(installation.installation_id), signature=""
        )
        wrong = await deliver(
            webhook_app, push_payload(installation.installation_id), secret="wrong"
        )

        assert missing.json()["detail"] == wrong.json()["detail"]

    async def test_an_oversized_payload_is_refused(self, webhook_app: FastAPI) -> None:
        # An unauthenticated endpoint that will hash 25 MB on demand is an
        # amplification vector. Size is checked before the HMAC, so the cost is
        # never paid.
        body = b'{"padding":"' + b"x" * (6 * 1024 * 1024) + b'"}'
        async with AsyncClient(
            transport=ASGITransport(app=webhook_app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/v1/webhooks/github",
                content=body,
                headers={
                    EVENT_HEADER: "push",
                    DELIVERY_HEADER: str(uuid.uuid4()),
                    SIGNATURE_HEADER: sign(body, SECRET),
                },
            )

        assert response.status_code == 413

    async def test_a_ping_is_answered_without_an_installation(self, webhook_app: FastAPI) -> None:
        # Sent once when a webhook is configured, before any installation
        # exists. Treating it as unclaimed would show a failed test delivery in
        # the GitHub UI for a correctly configured app.
        response = await deliver(webhook_app, {"zen": "Design for failure."}, event="ping")

        assert response.status_code == 202
        assert response.json() == {"status": "pong"}


class TestIdempotency:
    async def test_a_redelivery_is_acknowledged_but_not_re_enqueued(
        self,
        webhook_app: FastAPI,
        queue: InMemoryJobQueue,
        installation: GitHubInstallation,
        platform: AsyncSession,
    ) -> None:
        """The other half of the exit criterion.

        GitHub documents that delivery is not exactly-once. Without the unique
        constraint the same activity is counted twice — which, for a product
        whose output is "what happened this week", is a correctness failure a
        customer notices before we do.
        """
        delivery_id = str(uuid.uuid4())
        payload = push_payload(installation.installation_id)

        first = await deliver(webhook_app, payload, delivery_id=delivery_id)
        second = await deliver(webhook_app, payload, delivery_id=delivery_id)

        assert first.status_code == 202
        # 200 rather than 202: acknowledged, but nothing new was accepted.
        assert second.status_code == 200
        assert second.json() == {"status": "duplicate"}

        rows = (
            await platform.scalars(
                select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
            )
        ).all()
        assert len(rows) == 1

        # One job, not two.
        assert len(await queue.receive(max_messages=10)) == 1

    async def test_distinct_deliveries_are_both_processed(
        self, webhook_app: FastAPI, queue: InMemoryJobQueue, installation: GitHubInstallation
    ) -> None:
        # The positive control. Without it, the test above would pass against an
        # endpoint that rejected every delivery after the first.
        payload = push_payload(installation.installation_id)

        await deliver(webhook_app, payload, delivery_id=str(uuid.uuid4()))
        await deliver(webhook_app, payload, delivery_id=str(uuid.uuid4()))

        assert len(await queue.receive(max_messages=10)) == 2


class TestInstallationResolution:
    async def test_an_unknown_installation_is_acknowledged_but_not_queued(
        self, webhook_app: FastAPI, queue: InMemoryJobQueue
    ) -> None:
        # Acknowledged because GitHub retries non-2xx and retrying will not make
        # the installation known. Not queued because there is no tenant to scope
        # the work to.
        response = await deliver(webhook_app, push_payload(999_999_999))

        assert response.status_code == 202
        assert response.json() == {"status": "unclaimed"}
        assert await queue.receive(max_messages=5) == []

    async def test_a_suspended_installation_stops_being_captured(
        self,
        webhook_app: FastAPI,
        queue: InMemoryJobQueue,
        installation: GitHubInstallation,
        platform: AsyncSession,
    ) -> None:
        """Suspension is a consent boundary, not a technical one.

        A suspended installation keeps delivering webhooks. Processing them
        means capturing activity for a customer who switched the integration
        off — which for this product is a consent failure, not a bug.
        """
        from datetime import UTC, datetime

        installation.suspended_at = datetime.now(UTC)
        await platform.commit()

        response = await deliver(webhook_app, push_payload(installation.installation_id))

        assert response.json() == {"status": "unclaimed"}
        assert await queue.receive(max_messages=5) == []

    async def test_a_lifecycle_event_suspends_without_being_queued(
        self,
        webhook_app: FastAPI,
        queue: InMemoryJobQueue,
        installation: GitHubInstallation,
        platform: AsyncSession,
    ) -> None:
        # Applied inline rather than queued: it decides whether *future*
        # deliveries are captured, and deferring it leaves a window in which a
        # suspended installation's activity is still being processed.
        payload = push_payload(installation.installation_id, action="suspend")

        response = await deliver(webhook_app, payload, event="installation")

        assert response.status_code == 202
        await platform.refresh(installation)
        assert installation.suspended_at is not None
        assert await queue.receive(max_messages=5) == []

    async def test_an_installation_created_event_cannot_claim_a_workspace(
        self, webhook_app: FastAPI, queue: InMemoryJobQueue, platform: AsyncSession
    ) -> None:
        """An inbound webhook must not be able to create the tenant mapping.

        If it could, anyone who installed the app would have their activity
        bound to whichever workspace the handler guessed. The link is made by an
        authenticated user completing the connect flow — the only point at which
        we know which workspace asked for it.
        """
        unknown_id = 555_000_111
        payload = {"action": "created", "installation": {"id": unknown_id}}

        response = await deliver(webhook_app, payload, event="installation")

        assert response.status_code == 202
        created = await platform.scalar(
            select(GitHubInstallation).where(GitHubInstallation.installation_id == unknown_id)
        )
        assert created is None


# --------------------------------------------------------------------------
# The worker side
# --------------------------------------------------------------------------


class TestDeliveryHandler:
    async def test_processing_marks_the_delivery_done(
        self,
        webhook_app: FastAPI,
        queue: InMemoryJobQueue,
        installation: GitHubInstallation,
        platform: AsyncSession,
    ) -> None:
        from cairn_api.jobs.worker import Worker, WorkerConfig

        delivery_id = str(uuid.uuid4())
        await deliver(
            webhook_app, push_payload(installation.installation_id), delivery_id=delivery_id
        )

        registry = JobRegistry()
        registry.register(GITHUB_DELIVERY_JOB)(handle_delivery)
        worker = Worker(queue, config=WorkerConfig(), job_registry=registry)

        assert await worker.run_once() == 1
        assert worker.stats.succeeded == 1

        row = await platform.scalar(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        assert row is not None
        await platform.refresh(row)
        assert row.status is DeliveryStatus.PROCESSED
        assert row.processed_at is not None

    async def test_reprocessing_an_already_done_delivery_is_a_no_op(
        self,
        webhook_app: FastAPI,
        queue: InMemoryJobQueue,
        installation: GitHubInstallation,
        platform: AsyncSession,
    ) -> None:
        # At-least-once delivery guarantees this happens eventually. Treating it
        # as an error would fill the dead-letter queue with successful work.
        from cairn_api.db.tenancy import tenant_session

        delivery_id = str(uuid.uuid4())
        await deliver(
            webhook_app, push_payload(installation.installation_id), delivery_id=delivery_id
        )
        envelope = JobEnvelope(
            job_type=GITHUB_DELIVERY_JOB,
            tenant_id=installation.tenant_id,
            payload={"delivery_id": delivery_id},
        )

        async with tenant_session(installation.tenant_id) as session:
            await handle_delivery(session, envelope)
        async with tenant_session(installation.tenant_id) as session:
            await handle_delivery(session, envelope)  # must not raise

        row = await platform.scalar(
            select(WebhookDelivery).where(WebhookDelivery.delivery_id == delivery_id)
        )
        assert row is not None
        await platform.refresh(row)
        assert row.status is DeliveryStatus.PROCESSED

    async def test_a_handler_cannot_reach_another_tenants_delivery(
        self, webhook_app: FastAPI, installation: GitHubInstallation, platform: AsyncSession
    ) -> None:
        """Row-level security, asserted on the webhook path.

        A job naming a real delivery ID but the wrong tenant must find nothing —
        not the row. This is the silent cross-tenant read the whole architecture
        is arranged to prevent, tested where new data enters the system.
        """
        from cairn_api.db.tenancy import tenant_session
        from cairn_api.github.handlers import DeliveryNotFoundError

        delivery_id = str(uuid.uuid4())
        await deliver(
            webhook_app, push_payload(installation.installation_id), delivery_id=delivery_id
        )

        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
        platform.add(other)
        await platform.commit()

        envelope = JobEnvelope(
            job_type=GITHUB_DELIVERY_JOB,
            tenant_id=other.id,
            payload={"delivery_id": delivery_id},
        )

        async with tenant_session(other.id) as session:
            with pytest.raises(DeliveryNotFoundError):
                await handle_delivery(session, envelope)
