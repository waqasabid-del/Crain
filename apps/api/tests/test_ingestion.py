"""The provider-neutral ingestion contract.

Step 31 extracts, from the GitHub webhook path, the shape Slack and Google Chat
will need in Step 32 — and then makes GitHub use it, so the contract has a
production caller rather than being scaffolding nobody runs.

Every test here fails if the property it names is removed, not if it is
reworded. Nothing patches verification out: a test that disables the control
proves the code works when the control is absent, which is not a property
anybody wants. The fake provider below signs and verifies for real, exactly as
GitHub does; what makes it a fake is that it is not GitHub, which is the point —
the contract must hold for a provider that does not exist yet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, get_type_hints

import pytest
from cairn_api import telemetry
from cairn_api.api.app import create_app
from cairn_api.config import Settings
from cairn_api.db.github_models import GitHubInstallation
from cairn_api.db.models import Membership, Tenant, TenantRole, User
from cairn_api.github.signatures import DELIVERY_HEADER, EVENT_HEADER, SIGNATURE_HEADER, sign
from cairn_api.github.webhooks import GitHubInbound
from cairn_api.ingestion import (
    IdempotencyKey,
    InboundRequest,
    Ingestor,
    KeySource,
    PayloadTooLargeError,
    ResolvedTenant,
    SourceMetadata,
    SourceMetadataError,
    UnknownAccountError,
    UnverifiedEventError,
    VerificationError,
    VerifiedEvent,
    enqueue,
    job_payload,
    resolve_tenant,
)
from cairn_api.jobs.memory import InMemoryJobQueue
from cairn_api.telemetry.attributes import ALLOWED
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr

# Every secret in this file is a literal by necessity.
# ruff: noqa: S105, S106
SECRET = "ingestion-secret-for-tests"
PROVIDER = "acme_chat"
SIGNATURE = "x-acme-signature"
EVENT_ID = "x-acme-event-id"
EVENT_TYPE = "x-acme-event-type"
ACCOUNT = "x-acme-team-id"

#: A payload that would be a disaster in an exporter: somebody's words, an
#: address, and a credential. Used wherever a test asserts what does *not*
#: escape.
SENSITIVE = {
    "team": "T-ACME",
    "text": "Priya said the payments migration is blocked on legal",
    "author": "priya@acme.example",
    "token": "stand-in-credential",
}


def acme_sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class AcmeInbound:
    """A provider that does not exist, implementing `InboundProvider`.

    Deliberately not GitHub-shaped in the places that matter: it carries its
    account id in a header, and it supplies no delivery id at all — the two
    variations Slack and Google Chat actually present.
    """

    secret: str = SECRET

    #: Bodies this verifier was asked to hash. The oversize test asserts it
    #: stays empty, which is the only way to prove the cap runs first.
    hashed: list[bytes] = field(default_factory=list)

    def verify(self, request: InboundRequest) -> None:
        self.hashed.append(request.body)
        presented = request.header(SIGNATURE)
        if presented is None:
            raise VerificationError("missing signature")
        if not hmac.compare_digest(presented, acme_sign(request.body)):
            raise VerificationError("signature does not match")

    def read_source(self, request: InboundRequest) -> SourceMetadata:
        event_type = request.header(EVENT_TYPE)
        if not event_type:
            raise SourceMetadataError("no event type")
        return SourceMetadata(
            provider=PROVIDER,
            event_type=event_type,
            external_account_id=request.header(ACCOUNT),
            external_event_id=request.header(EVENT_ID),
        )

    def idempotency_key(self, request: InboundRequest, source: SourceMetadata) -> IdempotencyKey:
        if source.external_event_id:
            return IdempotencyKey.from_provider(source.external_event_id)
        return IdempotencyKey.derive(
            provider=source.provider,
            external_account_id=source.external_account_id,
            event_type=source.event_type,
            body=request.body,
        )


def acme_request(
    payload: dict[str, Any] | None = None,
    *,
    account: str | None = "T-ACME",
    event_id: str | None = None,
    event_type: str = "message",
    secret: str = SECRET,
) -> InboundRequest:
    """A request the way the provider would send it.

    The body is serialised once and *those* bytes are both signed and sent;
    re-serialising in between changes them and fails verification for a reason
    unrelated to the test.
    """
    body = json.dumps(payload if payload is not None else SENSITIVE).encode()
    headers = {
        # Mixed case on purpose: HTTP header names are case-insensitive, and a
        # verifier that matches on the wrong casing is a bypass.
        SIGNATURE.upper(): hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(),
        EVENT_TYPE: event_type,
    }
    if account is not None:
        headers[ACCOUNT] = account
    if event_id is not None:
        headers[EVENT_ID] = event_id
    return InboundRequest(body=body, headers=headers)


@pytest.fixture(autouse=True)
def contained_correlation() -> Any:
    """Keep each test's unit of work inside that test.

    `Ingestor.accept` begins one the way a request handler does, and in
    production that is safe because every request runs in its own task with its
    own copy of the context. A test calling it directly shares this module's
    context, so without this the last id minted here would still be bound when
    an unrelated test asserts that scheduled work starts with none.
    """
    from cairn_api.telemetry import correlation

    with correlation.correlated():
        yield


@pytest.fixture
def provider() -> AcmeInbound:
    return AcmeInbound()


@pytest.fixture
def ingestor(provider: AcmeInbound) -> Ingestor:
    return Ingestor(name=PROVIDER, provider=provider)


@pytest.fixture
def tenant() -> ResolvedTenant:
    return ResolvedTenant(tenant_id=uuid.uuid4(), external_account_id="T-ACME")


class AccountDirectory:
    """A `TenantResolver` over a fixed mapping — the shape of the real one."""

    def __init__(self, mapping: dict[str, uuid.UUID], *, active: bool = True) -> None:
        self._mapping = mapping
        self._active = active
        self.asked: list[str | None] = []

    async def resolve(self, source: SourceMetadata) -> ResolvedTenant | None:
        self.asked.append(source.external_account_id)
        tenant_id = self._mapping.get(source.external_account_id or "")
        if tenant_id is None:
            return None
        return ResolvedTenant(
            tenant_id=tenant_id,
            external_account_id=source.external_account_id or "",
            active=self._active,
        )


class Ledger:
    """An `IdempotencyLedger` with the unique constraint in a set."""

    def __init__(self) -> None:
        self.held: set[str] = set()

    async def claim(self, event: VerifiedEvent, tenant: ResolvedTenant) -> bool:
        key = event.idempotency_key.value
        if key in self.held:
            return False
        self.held.add(key)
        return True


# --------------------------------------------------------------------------
# "Unverified" is not a state anything can be in
# --------------------------------------------------------------------------


class TestUnverifiedIsUnrepresentable:
    """The failure this design removes is a `verified` flag nobody checks.

    There is no flag. The only constructor of `VerifiedEvent` runs the
    provider's verifier first, and every function downstream is typed against
    that class.
    """

    def test_the_event_cannot_be_constructed_without_verification(self) -> None:
        with pytest.raises(UnverifiedEventError, match="verify_and_mint"):
            VerifiedEvent(
                # A type error as well as a runtime one: the parameter is typed
                # against a class this module cannot name, so mypy rejects this
                # line for the same reason the constructor does. The ignore
                # keeps the *runtime* assertion — that the guard fires rather
                # than merely being unreachable in a typed caller.
                object(),  # type: ignore[arg-type]
                source=SourceMetadata(provider=PROVIDER, event_type="message"),
                idempotency_key=IdempotencyKey.from_provider("e-1"),
                body=b"{}",
                correlation_id=uuid.uuid4().hex,
            )

    def test_the_proof_type_is_not_exported(self) -> None:
        """The runtime check is only as good as the proof being unobtainable."""
        import cairn_api.ingestion as ingestion

        assert not any(name.endswith("Proof") for name in dir(ingestion))
        assert "_VerificationProof" not in ingestion.__all__

    def test_a_forged_request_produces_no_event_at_all(self, ingestor: Ingestor) -> None:
        with pytest.raises(VerificationError):
            ingestor.accept(acme_request(secret="attacker-guessed-this"))

    def test_an_unsigned_request_produces_no_event_at_all(self, ingestor: Ingestor) -> None:
        # The catastrophic implementation is `if signature: verify(...)`, which
        # accepts everything that simply omits the header.
        body = json.dumps(SENSITIVE).encode()
        with pytest.raises(VerificationError):
            ingestor.accept(InboundRequest(body=body, headers={EVENT_TYPE: "message"}))

    async def test_nothing_unverified_can_reach_the_queue(
        self, ingestor: Ingestor, tenant: ResolvedTenant
    ) -> None:
        """The type is the guarantee: `enqueue` has nowhere to put a raw body.

        Asserted against the resolved annotation rather than the source text, so
        widening the parameter to `object` fails this test.
        """
        assert get_type_hints(enqueue)["event"] is VerifiedEvent

        queue = InMemoryJobQueue()
        with pytest.raises(VerificationError):
            event = ingestor.accept(acme_request(secret="wrong"))
            await enqueue(queue, event, tenant, job_type="acme.event", payload={})

        assert await queue.receive(max_messages=5) == []

    def test_a_verified_request_does_produce_one(self, ingestor: Ingestor) -> None:
        """The positive control. Without it the tests above would pass against
        an ingestor that refused everything."""
        event = ingestor.accept(acme_request(event_id="e-1"))

        assert event.source.provider == PROVIDER
        assert event.idempotency_key.value == "e-1"


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


class TestIdempotency:
    """No provider offers exactly-once delivery, so the key is what stops one
    event being counted twice — which, for a product whose output is "what
    happened this week", is a correctness failure a customer notices first."""

    async def test_the_same_delivery_id_twice_enqueues_one_job(
        self, ingestor: Ingestor, tenant: ResolvedTenant
    ) -> None:
        queue = InMemoryJobQueue()
        ledger = Ledger()
        request = acme_request(event_id="e-42")

        for _ in range(2):
            event = ingestor.accept(request)
            if await ledger.claim(event, tenant):
                await enqueue(
                    queue, event, tenant, job_type="acme.event", payload=job_payload(event)
                )

        messages = await queue.receive(max_messages=10)
        assert len(messages) == 1
        assert messages[0].envelope.payload == {"delivery_id": "e-42"}

    async def test_two_distinct_events_are_both_enqueued(
        self, ingestor: Ingestor, tenant: ResolvedTenant
    ) -> None:
        # The positive control for the test above.
        queue = InMemoryJobQueue()
        ledger = Ledger()

        for event_id in ("e-1", "e-2"):
            event = ingestor.accept(acme_request(event_id=event_id))
            if await ledger.claim(event, tenant):
                await enqueue(
                    queue, event, tenant, job_type="acme.event", payload=job_payload(event)
                )

        assert len(await queue.receive(max_messages=10)) == 2

    def test_a_providers_own_id_is_used_unchanged(self) -> None:
        """Decorating it would break the one thing it is for: matching what an
        operator reads in the provider's own deliveries UI."""
        key = IdempotencyKey.from_provider("8f4a-delivery")

        assert key.value == "8f4a-delivery"
        assert key.source is KeySource.PROVIDER

    def test_a_derived_key_is_the_same_for_a_byte_identical_redelivery(
        self, ingestor: Ingestor
    ) -> None:
        """Slack and Google Chat resend the same bytes rather than a stable
        delivery id (md/02 §9), so the digest is the key."""
        request = acme_request()

        first = ingestor.accept(request)
        second = ingestor.accept(request)

        assert first.idempotency_key.source is KeySource.DERIVED
        assert first.idempotency_key.value == second.idempotency_key.value

    def test_a_derived_key_differs_for_a_different_event(self, ingestor: Ingestor) -> None:
        one = ingestor.accept(acme_request({"team": "T-ACME", "event_ts": "1"}))
        two = ingestor.accept(acme_request({"team": "T-ACME", "event_ts": "2"}))

        assert one.idempotency_key.value != two.idempotency_key.value

    def test_a_derived_key_is_scoped_to_its_provider_and_account(self) -> None:
        """Two providers sending identical bytes must not collide into one key."""
        # Spelled out rather than splatted from a dict: `**` erases the
        # per-argument types, so a call that had drifted from the signature
        # would still typecheck here.
        body = b'{"text":"ship it"}'

        assert (
            IdempotencyKey.derive(
                provider="slack", external_account_id="T-1", event_type="message", body=body
            ).value
            != IdempotencyKey.derive(
                provider="google_chat", external_account_id="T-1", event_type="message", body=body
            ).value
        )
        assert (
            IdempotencyKey.derive(
                provider="slack", external_account_id="T-2", event_type="message", body=body
            ).value
            != IdempotencyKey.derive(
                provider="slack", external_account_id="T-1", event_type="message", body=body
            ).value
        )

    def test_a_derived_key_carries_none_of_the_message(self) -> None:
        """It is written to a column, logged, and matched on. A key that quoted
        the payload would put a message everywhere an id is allowed."""
        key = IdempotencyKey.derive(
            provider=PROVIDER,
            external_account_id="T-ACME",
            event_type="message",
            body=json.dumps(SENSITIVE).encode(),
        )

        assert "Priya" not in key.value
        assert "xoxb" not in key.value
        assert key.value.startswith("sha256:")

    def test_an_empty_key_is_refused(self) -> None:
        """An empty key deduplicates every event against every other one."""
        with pytest.raises(ValueError, match="cannot be empty"):
            IdempotencyKey.from_provider("")


# --------------------------------------------------------------------------
# Tenancy
# --------------------------------------------------------------------------


class TestTenantIdentity:
    """The tenant comes from the account identifier, resolved against a mapping
    only an authenticated connect flow may write. Everything else is data."""

    async def test_a_body_claiming_another_tenant_does_not_change_the_answer(
        self, ingestor: Ingestor
    ) -> None:
        real = uuid.uuid4()
        attacker = uuid.uuid4()
        directory = AccountDirectory({"T-ACME": real})

        event = ingestor.accept(
            acme_request(
                {"tenant_id": str(attacker), "workspace": str(attacker), "team": "T-VICTIM"},
                account="T-ACME",
            )
        )
        resolved = await resolve_tenant(directory, event.source)

        assert resolved.tenant_id == real
        # It was asked about the *account*, and nothing else was consulted.
        assert directory.asked == ["T-ACME"]

    async def test_an_unknown_account_is_refused_rather_than_guessed(
        self, ingestor: Ingestor
    ) -> None:
        """No default workspace, no first-row fallback. A wrong answer here is a
        cross-tenant leak; no answer is the only safe alternative."""
        directory = AccountDirectory({"T-KNOWN": uuid.uuid4()})

        event = ingestor.accept(acme_request(account="T-STRANGER"))

        with pytest.raises(UnknownAccountError):
            await resolve_tenant(directory, event.source)

    async def test_an_event_naming_no_account_is_refused(self, ingestor: Ingestor) -> None:
        directory = AccountDirectory({"T-ACME": uuid.uuid4()})

        event = ingestor.accept(acme_request(account=None))

        assert event.source.external_account_id is None
        with pytest.raises(UnknownAccountError):
            await resolve_tenant(directory, event.source)

    async def test_a_switched_off_integration_is_distinguishable_from_a_stranger(
        self, ingestor: Ingestor
    ) -> None:
        """Suspension is a consent boundary. Capturing activity for a customer
        who switched the integration off is a consent failure, not a mystery,
        and the caller has to be able to tell the two apart."""
        directory = AccountDirectory({"T-ACME": uuid.uuid4()}, active=False)

        resolved = await resolve_tenant(directory, ingestor.accept(acme_request()).source)

        assert resolved.active is False

    async def test_the_envelope_cannot_be_built_without_a_tenant(self, ingestor: Ingestor) -> None:
        """`JobEnvelope.tenant_id` has no default and refuses the nil UUID, so
        an unattributed event cannot become background work at all."""
        queue = InMemoryJobQueue()
        event = ingestor.accept(acme_request())

        with pytest.raises(ValueError, match="not the nil UUID"):
            await enqueue(
                queue,
                event,
                ResolvedTenant(tenant_id=uuid.UUID(int=0), external_account_id="T-ACME"),
                job_type="acme.event",
                payload=job_payload(event),
            )

        assert await queue.receive(max_messages=5) == []


# --------------------------------------------------------------------------
# The size cap, and the order it runs in
# --------------------------------------------------------------------------


class TestTheSizeCapRunsFirst:
    async def test_an_oversized_body_is_refused_before_any_hmac_work(
        self, provider: AcmeInbound
    ) -> None:
        """An unauthenticated endpoint that will hash 25 MB on demand is the
        amplification vector this cap exists to prevent. Asserted by the
        verifier recording every body it was asked to hash — a check that fails
        if the two steps are ever reordered."""
        ingestor = Ingestor(name=PROVIDER, provider=provider, max_body_bytes=1024)
        oversized = InboundRequest(body=b"x" * 4096, headers={EVENT_TYPE: "message"})

        with pytest.raises(PayloadTooLargeError):
            ingestor.accept(oversized)

        assert provider.hashed == []

    async def test_a_body_inside_the_cap_is_still_verified(self, provider: AcmeInbound) -> None:
        # The positive control: a cap that refused everything would also pass
        # the test above.
        ingestor = Ingestor(name=PROVIDER, provider=provider, max_body_bytes=1024 * 1024)

        ingestor.accept(acme_request(event_id="e-1"))

        assert provider.hashed


# --------------------------------------------------------------------------
# Correlation and trace
# --------------------------------------------------------------------------


class TestPropagation:
    """One webhook and the brief it produced must share one greppable name."""

    async def test_the_correlation_id_survives_receipt_to_queue(
        self, ingestor: Ingestor, tenant: ResolvedTenant
    ) -> None:
        queue = InMemoryJobQueue()

        event = ingestor.accept(acme_request(event_id="e-7"))
        await enqueue(queue, event, tenant, job_type="acme.event", payload=job_payload(event))

        [message] = await queue.receive(max_messages=1)
        assert message.envelope.correlation_id == event.correlation_id
        # Opaque by construction — 32 hex characters, derived from nothing.
        assert len(event.correlation_id) == 32
        assert int(event.correlation_id, 16) >= 0

    async def test_a_rejected_delivery_still_has_one(self, ingestor: Ingestor) -> None:
        """Bound *before* verification, so the delivery nobody accepted is still
        greppable. An id minted afterwards only ever names traffic that was
        already fine."""
        from cairn_api.telemetry import correlation

        before = correlation.current_correlation_id()

        with pytest.raises(VerificationError):
            ingestor.accept(acme_request(secret="wrong"))

        after = correlation.current_correlation_id()
        assert after is not None
        # A *fresh* id, minted by this receipt rather than inherited from
        # whatever was ambient: the rejected delivery has a name of its own.
        assert after != before

    async def test_the_active_trace_reaches_the_worker_side(
        self, ingestor: Ingestor, tenant: ResolvedTenant, spans: Any
    ) -> None:
        """`spans` installs a real SDK: the OpenTelemetry API is a no-op until
        one is, which is the local default and the reason the correlation id
        above — not this — is the half that always survives."""
        queue = InMemoryJobQueue()

        with telemetry.stage("request"):
            event = ingestor.accept(acme_request(event_id="e-8"))
            await enqueue(queue, event, tenant, job_type="acme.event", payload=job_payload(event))

        [message] = await queue.receive(max_messages=1)
        assert message.envelope.traceparent is not None
        assert message.envelope.traceparent.startswith("00-")

    async def test_two_deliveries_do_not_share_one_correlation_id(self, ingestor: Ingestor) -> None:
        first = ingestor.accept(acme_request(event_id="e-1"))
        second = ingestor.accept(acme_request(event_id="e-2"))

        assert first.correlation_id != second.correlation_id


# --------------------------------------------------------------------------
# Telemetry
# --------------------------------------------------------------------------


@pytest.fixture
def spans() -> Any:
    """An in-memory exporter, installed for one test.

    Only the module's tracer is swapped: replacing OpenTelemetry's global
    provider is a one-way door and recurses through the proxy on the way back.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    original = telemetry.spans.tracer
    telemetry.spans.tracer = provider.get_tracer("cairn.test")
    try:
        yield exporter
    finally:
        telemetry.spans.tracer = original


class TestNothingLeavesOnASpan:
    """Telemetry leaves the product — to an exporter, a vendor, a dashboard and
    a retention policy none of md/05's promises cover. Ingestion is where the
    rawest customer content in the system arrives, so it is the likeliest place
    for a leak to start.

    Asserted against the *recorded* attributes rather than by reading the
    source, so an attribute added later is caught by this test rather than by a
    reviewer.
    """

    def _recorded(self, spans: Any) -> list[dict[str, Any]]:
        return [dict(span.attributes or {}) for span in spans.get_finished_spans()]

    def test_receipt_records_only_allow_listed_attributes(
        self, ingestor: Ingestor, spans: Any
    ) -> None:
        ingestor.accept(acme_request(event_id="e-9"))

        recorded = self._recorded(spans)
        assert recorded, "receipt opened no span at all"
        for attributes in recorded:
            assert set(attributes) <= ALLOWED

    def test_no_message_address_or_token_reaches_a_span(
        self, ingestor: Ingestor, spans: Any
    ) -> None:
        ingestor.accept(acme_request(event_id="e-10"))

        exported = str(self._recorded(spans))
        for leak in ("Priya", "payments migration", "priya@acme.example", "xoxb"):
            assert leak not in exported

    def test_a_rejected_delivery_does_not_export_the_body_either(
        self, ingestor: Ingestor, spans: Any
    ) -> None:
        """The failure path is the one that carries an exception message, and an
        exception message routinely quotes what broke."""
        with pytest.raises(VerificationError):
            ingestor.accept(acme_request(secret="wrong"))

        exported = str(self._recorded(spans))
        assert "Priya" not in exported
        assert "xoxb" not in exported
        for attributes in self._recorded(spans):
            assert set(attributes) <= ALLOWED

    async def test_the_queue_hand_off_exports_no_payload(
        self, ingestor: Ingestor, tenant: ResolvedTenant, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The envelope holds the key, and the queue counts the publish. Neither
        may put anything from the event on a metric."""
        captured: list[dict[str, Any]] = []

        class Recorder:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append(dict(attributes or {}))

        monkeypatch.setattr(telemetry.spans, "queue_depth", Recorder())

        event = ingestor.accept(acme_request(event_id="e-11"))
        await enqueue(
            InMemoryJobQueue(), event, tenant, job_type="acme.event", payload=job_payload(event)
        )

        assert captured
        for attributes in captured:
            assert set(attributes) <= ALLOWED
        assert "Priya" not in str(captured)


# --------------------------------------------------------------------------
# GitHub, the contract's production caller
# --------------------------------------------------------------------------

GITHUB_SECRET = "webhook-secret-for-tests"


class TestGitHubImplementsTheContract:
    """The provider-specific half, on its own.

    These are the only GitHub-shaped assertions in this file; everything above
    holds for a provider that does not exist yet, which is the property Step 32
    depends on.
    """

    def _request(
        self, *, body: bytes, secret: str = GITHUB_SECRET, **headers: str
    ) -> InboundRequest:
        return InboundRequest(
            body=body,
            headers={
                SIGNATURE_HEADER: sign(body, secret),
                EVENT_HEADER: "pull_request",
                DELIVERY_HEADER: "8f4a-delivery",
                **headers,
            },
        )

    def test_a_correct_signature_verifies(self) -> None:
        GitHubInbound(secret=GITHUB_SECRET).verify(self._request(body=b'{"action":"opened"}'))

    def test_a_signature_for_different_bytes_is_refused(self) -> None:
        request = self._request(body=b'{"action":"opened","number":1}')
        tampered = InboundRequest(
            body=b'{"action":"opened","number":2}', headers=dict(request.headers)
        )

        with pytest.raises(VerificationError):
            GitHubInbound(secret=GITHUB_SECRET).verify(tampered)

    def test_a_blank_secret_refuses_rather_than_passing(self) -> None:
        # An empty secret makes every signature verifiable. Failing here turns a
        # misconfiguration into an outage instead of an open door.
        with pytest.raises(VerificationError):
            GitHubInbound(secret="").verify(self._request(body=b"{}", secret=""))

    def test_the_delivery_header_becomes_the_key(self) -> None:
        provider = GitHubInbound(secret=GITHUB_SECRET)
        request = self._request(body=b"{}")

        source = provider.read_source(request)

        assert provider.idempotency_key(request, source) == IdempotencyKey.from_provider(
            "8f4a-delivery"
        )

    def test_a_delivery_that_cannot_name_itself_is_refused(self) -> None:
        provider = GitHubInbound(secret=GITHUB_SECRET)
        request = InboundRequest(body=b"{}", headers={EVENT_HEADER: "push"})

        with pytest.raises(SourceMetadataError):
            provider.read_source(request)


@pytest.fixture
def queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


@pytest.fixture
def webhook_app(queue: InMemoryJobQueue) -> FastAPI:
    app = create_app(
        Settings(
            environment="test",
            cors_allowed_origins=("http://localhost:3000",),
            github_webhook_secret=SecretStr(GITHUB_SECRET),
        )
    )
    app.state.queue = queue
    return app


@pytest.fixture
async def installation(platform: Any) -> GitHubInstallation:
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
        installation_id=770_000_000 + int(suffix[:6], 16) % 100_000,
        account_login="acme-inc",
        account_type="Organization",
    )
    platform.add(record)
    await platform.commit()
    return record


async def deliver(app: FastAPI, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(
            "/v1/webhooks/github",
            content=body,
            headers={
                EVENT_HEADER: "pull_request",
                DELIVERY_HEADER: str(uuid.uuid4()),
                SIGNATURE_HEADER: sign(body, GITHUB_SECRET),
                "Content-Type": "application/json",
            },
        )


class TestTheGitHubEndpointGoesThroughTheContract:
    """The contract is only worth having if production runs it.

    These assert the two properties that cannot be checked from the unit side:
    that the live endpoint attributes by installation rather than by anything
    the body says, and that what it publishes is a correlated `JobEnvelope`.
    """

    async def test_a_body_claiming_another_workspace_is_ignored(
        self, webhook_app: FastAPI, queue: InMemoryJobQueue, installation: GitHubInstallation
    ) -> None:
        stranger = uuid.uuid4()

        response = await deliver(
            webhook_app,
            {
                "action": "opened",
                "installation": {"id": installation.installation_id},
                # Everything an attacker would try, all at once.
                "tenant_id": str(stranger),
                "workspace_id": str(stranger),
                "organization": {"id": 1, "login": "someone-else"},
            },
        )

        assert response.status_code == 202
        [message] = await queue.receive(max_messages=5)
        assert message.envelope.tenant_id == installation.tenant_id
        assert message.envelope.tenant_id != stranger

    async def test_the_published_envelope_is_correlated(
        self, webhook_app: FastAPI, queue: InMemoryJobQueue, installation: GitHubInstallation
    ) -> None:
        await deliver(
            webhook_app, {"action": "opened", "installation": {"id": installation.installation_id}}
        )

        [message] = await queue.receive(max_messages=5)
        # The durable half of "follow this webhook to its brief": always
        # present, whether or not a tracer is installed.
        assert len(message.envelope.correlation_id) == 32

    async def test_acknowledgement_is_far_inside_githubs_ten_second_budget(
        self, webhook_app: FastAPI, installation: GitHubInstallation
    ) -> None:
        # Routing through the shared contract must not cost the budget: miss the
        # 10s and GitHub retries, so slow processing becomes duplicate
        # processing.
        started = time.perf_counter()
        response = await deliver(
            webhook_app, {"action": "opened", "installation": {"id": installation.installation_id}}
        )
        elapsed = time.perf_counter() - started

        assert response.status_code == 202
        assert elapsed < 1.0, f"took {elapsed:.2f}s; GitHub allows 10s"
