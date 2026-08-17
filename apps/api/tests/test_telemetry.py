"""Telemetry: what it records, and what it must never record.

Step 29's exit criterion is that **a bad output can be traced to its stage,
context, model and cost**. The tests that matter are not "does a span exist" —
they are the ones that keep telemetry from becoming the place customer content
leaks out of a product that is careful with it everywhere else.

Telemetry leaves the building. It goes to an exporter, a vendor, a dashboard and
a retention policy that md/05's promises do not cover. So the allow-list is
tested directly, and every recording helper is tested for what it does *not*
carry.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from cairn_api import telemetry
from cairn_api.jobs.envelope import JobEnvelope
from cairn_api.telemetry.attributes import ALLOWED, UnsafeAttributeError, safe
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture
def spans() -> Any:
    """An in-memory exporter, installed for one test.

    The API is a no-op until an SDK is installed, which is the local default and
    the reason instrumentation costs nothing when nobody is collecting.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    # Only the module's tracer is swapped. Replacing OpenTelemetry's global
    # provider is a one-way door by design and recurses through the proxy when
    # a test tries to put the original back.
    original = telemetry.spans.tracer
    telemetry.spans.tracer = provider.get_tracer("cairn.test")
    try:
        yield exporter
    finally:
        telemetry.spans.tracer = original


class TestTheAllowList:
    """A deny-list fails the first time somebody adds a field nobody banned."""

    def test_an_attribute_nobody_approved_is_refused(self) -> None:
        with pytest.raises(UnsafeAttributeError, match="statement"):
            safe({"statement": "Priya shipped the payments migration."})

    @pytest.mark.parametrize(
        "attribute",
        [
            "prompt",
            "response",
            "statement",
            "narrative",
            "quote",
            "email",
            "payload",
            "token",
            "secret",
            "content",
        ],
    )
    def test_the_obvious_leaks_are_all_refused(self, attribute: str) -> None:
        """Named individually so the list reads as the threat model it is."""
        assert attribute not in ALLOWED
        with pytest.raises(UnsafeAttributeError):
            safe({attribute: "anything at all"})

    def test_identifiers_and_numbers_are_allowed(self) -> None:
        """Every allowed attribute is a shape — an id, a category, a number.

        A tenant id names a customer without describing them; a statement
        describes them.
        """
        assert safe({"tenant_id": "t", "stage": "extract", "tokens_in": 12}) == {
            "tenant_id": "t",
            "stage": "extract",
            "tokens_in": 12,
        }

    def test_none_values_are_dropped_rather_than_exported(self) -> None:
        assert safe({"tenant_id": "t", "priority": None}) == {"tenant_id": "t"}

    def test_an_unsafe_attribute_does_not_break_the_work(self, spans: Any) -> None:
        """Telemetry must never fail the thing it describes.

        The span is emitted without attributes and the refusal is logged, which
        is the only failure mode that does not turn an observability bug into an
        outage.
        """
        with telemetry.stage("extract", **{"quote": "secret words"}):
            pass

        [span] = spans.get_finished_spans()
        assert "quote" not in (span.attributes or {})


class TestStagesAreTraced:
    def test_a_stage_records_its_outcome(self, spans: Any) -> None:
        with telemetry.stage("classify", tenant_id="t"):
            pass

        [span] = spans.get_finished_spans()
        assert span.name == "cairn.classify"
        assert span.attributes["outcome"] == "ok"
        assert span.attributes["tenant_id"] == "t"

    def test_a_failure_is_categorised_without_its_message(self, spans: Any) -> None:
        """An exception message routinely contains the row that broke. The type
        is the part that is safe and the part an operator groups by."""

        class PayloadError(ValueError):
            pass

        with pytest.raises(PayloadError), telemetry.stage("extract"):
            raise PayloadError("statement: Priya shipped the payments migration")

        [span] = spans.get_finished_spans()
        assert span.attributes["error_category"] == "PayloadError"
        assert "Priya" not in str(span.attributes)
        assert "Priya" not in str(span.status.description or "")

    async def test_every_pipeline_stage_opens_a_span(self) -> None:
        """Structural: the criterion is that *any* bad output is traceable, and
        a stage nobody instrumented is the one it will come from."""
        import inspect

        from cairn_api.pipeline import classify, extract, graph, retrieval, store, synthesize

        for module, function in (
            (classify, "classify"),
            (extract, "extract"),
            (store, "apply"),
            (graph, "build"),
            (retrieval, "retrieve"),
            (synthesize, "synthesize"),
        ):
            source = inspect.getsource(getattr(module, function))
            assert "telemetry.stage(" in source, f"{module.__name__}.{function} has no span"


class TestTraceContextSurvivesTheQueue:
    def test_an_envelope_carries_the_active_trace(self, spans: Any) -> None:
        """Captured at construction rather than passed by callers: a worker span
        that does not link back to the request is the one nobody can follow."""
        with telemetry.stage("webhook"):
            envelope = JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4())

        assert envelope.traceparent is not None
        assert envelope.traceparent.startswith("00-")

    def test_the_worker_joins_the_trace_it_was_given(self, spans: Any) -> None:
        with telemetry.stage("webhook") as origin:
            envelope = JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4())
            expected = origin.get_span_context().trace_id

        with (
            telemetry.linked_to({"traceparent": envelope.traceparent or ""}),
            telemetry.stage("job") as worker,
        ):
            assert worker.get_span_context().trace_id == expected

    def test_a_job_with_no_trace_still_runs(self, spans: Any) -> None:
        """Scheduled work has no originating request, and must not fail for it."""
        with telemetry.linked_to(None), telemetry.stage("job"):
            pass

        assert spans.get_finished_spans()


class TestTheQueueReportsEveryOutcome:
    """A metric that only counts the happy path hides the failures.

    Retry and dead-letter are the two an operator alerts on, so they are tested
    through the broker rather than by calling the recorder directly.
    """

    @pytest.fixture
    def recorded(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        """Capture what reaches the counter, attributes and all."""
        captured: list[dict[str, Any]] = []

        class Recorder:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append(dict(attributes or {}))

        monkeypatch.setattr(telemetry.spans, "queue_depth", Recorder())
        return captured

    async def test_publish_receive_and_ack_are_each_counted(
        self, recorded: list[dict[str, Any]]
    ) -> None:
        from cairn_api.jobs.memory import InMemoryJobQueue

        queue = InMemoryJobQueue()
        await queue.publish(JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4()))
        [message] = await queue.receive(max_messages=1)
        await queue.ack(message)

        assert [entry["outcome"] for entry in recorded] == ["published", "claimed", "acked"]

    async def test_a_retry_is_counted(self, recorded: list[dict[str, Any]]) -> None:
        from cairn_api.jobs.memory import InMemoryJobQueue

        queue = InMemoryJobQueue()
        await queue.publish(JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4()))
        [message] = await queue.receive(max_messages=1)
        await queue.retry(message, delay_seconds=0)

        assert "retried" in [entry["outcome"] for entry in recorded]

    async def test_a_dead_letter_is_counted(self, recorded: list[dict[str, Any]]) -> None:
        from cairn_api.jobs.memory import InMemoryJobQueue

        queue = InMemoryJobQueue()
        await queue.publish(JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4()))
        [message] = await queue.receive(max_messages=1)
        await queue.dead_letter(message, reason="UnknownJobTypeError")

        assert "dead_lettered" in [entry["outcome"] for entry in recorded]

    async def test_no_outcome_carries_a_payload_or_a_tenant_s_words(
        self, recorded: list[dict[str, Any]]
    ) -> None:
        """The queue sees the envelope, which holds the payload. None of it may
        reach a counter that leaves the building."""
        from cairn_api.jobs.memory import InMemoryJobQueue

        queue = InMemoryJobQueue()
        await queue.publish(
            JobEnvelope(
                job_type="pipeline.understand",
                tenant_id=uuid.uuid4(),
                payload={"statement": "Priya shipped the payments migration."},
            )
        )
        [message] = await queue.receive(max_messages=1)
        await queue.dead_letter(message, reason="a failure mentioning Priya")

        assert recorded
        assert "Priya" not in str(recorded)
        for entry in recorded:
            assert set(entry) <= {"job_type", "outcome", "priority"}


class TestDeadLettersAreAlertable:
    """A job that fails permanently must not disappear quietly.

    `docs/OPERATIONS.md` alerts on "any dead letter" and pages above five in an
    hour. That needs a series of its own — a dead letter buried among publishes
    and acks in the general queue counter is one an alert has to filter for, and
    a filter is what silently stops matching when an outcome string is renamed.

    Every test here fails if the alerting is removed rather than if it is
    reworded: they go through a real broker and a real worker.
    """

    @pytest.fixture
    def dead_letters(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        """Capture what reaches the dedicated dead-letter counter."""
        captured: list[dict[str, Any]] = []

        class Recorder:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                captured.append(dict(attributes or {}))

        monkeypatch.setattr(telemetry.spans, "dead_letters", Recorder())
        return captured

    def test_the_dlq_counter_is_not_the_general_queue_counter(self) -> None:
        """Separate instruments, so the alert is a series and not a filter."""
        assert telemetry.spans.dead_letters is not telemetry.spans.queue_depth

    async def test_a_dead_letter_increments_the_dedicated_counter(
        self, dead_letters: list[dict[str, Any]]
    ) -> None:
        from cairn_api.jobs.memory import InMemoryJobQueue

        queue = InMemoryJobQueue()
        await queue.publish(JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4()))
        [message] = await queue.receive(max_messages=1)
        await queue.dead_letter(message, reason="DeliveryNotFoundError: no such delivery")

        assert dead_letters == [
            {
                "job_type": "pipeline.understand",
                "error_category": "DeliveryNotFoundError",
                "priority": "standard",
            }
        ]

    async def test_a_reason_quoting_a_customer_is_not_exported(
        self, dead_letters: list[dict[str, Any]]
    ) -> None:
        """The reason is a free string, and an exception message routinely
        quotes the row that broke. The durable row and the log keep it; the
        counter must not."""
        from cairn_api.jobs.memory import InMemoryJobQueue

        queue = InMemoryJobQueue()
        await queue.publish(JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4()))
        [message] = await queue.receive(max_messages=1)
        reason = "ValueError: could not parse 'Priya shipped the payments migration'"

        await queue.dead_letter(message, reason=reason)

        assert dead_letters
        assert "Priya" not in str(dead_letters)
        assert "payments" not in str(dead_letters)
        # The full text survives where it is allowed to: the durable record.
        assert queue.dead_letters()[0].reason == reason

    def test_the_counter_takes_a_reason_and_reduces_it_itself(self) -> None:
        """`error_category` is an allow-listed *name*, so a caller allowed to
        choose the value could put the whole reason behind it and the allow-list
        would pass it. Reduction happens at the one place that writes."""
        import inspect

        assert set(inspect.signature(telemetry.record_dead_letter).parameters) == {
            "job_type",
            "reason",
            "priority",
        }

    @pytest.mark.parametrize(
        ("reason", "expected"),
        [
            ("UnknownJobTypeError: no handler for 'x'", "UnknownJobTypeError"),
            ("TimeoutError: upstream took too long", "TimeoutError"),
            ("SomeVendorException: 503", "SomeVendorException"),
            ("undecodable", "undecodable"),
            ("", "unknown"),
            (None, "unknown"),
            # Not exception-shaped: filed as `other` rather than risking a
            # metric label reading `Priya`.
            ("Priya: shipped the payments migration", "other"),
            ("the pipeline gave up on Priya's commit", "other"),
        ],
    )
    def test_a_reason_becomes_a_bounded_category(self, reason: str | None, expected: str) -> None:
        assert telemetry.dead_letter_category(reason) == expected

    def test_the_category_is_stable_across_messages_of_the_same_type(self) -> None:
        """Stability is the whole value: two failures of one type must group,
        however different the sentences after the colon."""
        first = telemetry.dead_letter_category("DeliveryNotFoundError: delivery 12 for tenant a")
        second = telemetry.dead_letter_category("DeliveryNotFoundError: delivery 99 for tenant b")

        assert first == second == "DeliveryNotFoundError"

    def test_the_dead_letter_path_logs_at_error(self) -> None:
        """A permanent failure below ERROR is one filtered out of the console
        somebody is watching during an incident."""
        import inspect

        from cairn_api.jobs import memory, postgres

        for module, function in ((memory, "dead_letter"), (postgres, "dead_letter")):
            queue_class = memory.InMemoryJobQueue if module is memory else postgres.PostgresJobQueue
            source = inspect.getsource(getattr(queue_class, function))
            assert "aerror(" in source, f"{queue_class.__name__}.{function} does not log at ERROR"
            assert "record_dead_letter(" in source


class TestTheCorrelationIdIsSafeToExport:
    def test_it_is_allow_listed(self) -> None:
        """An opaque identifier, not content: 32 hex characters from `uuid4`,
        derived from nothing anyone said."""
        assert "correlation_id" in ALLOWED
        assert safe({"correlation_id": "0" * 32}) == {"correlation_id": "0" * 32}

    def test_an_id_from_storage_that_is_not_one_of_ours_is_discarded(self) -> None:
        """The field is allow-listed by *name*, so the shape is what stops a
        queue row's `correlation_id` from carrying a sentence onto a span."""
        from cairn_api.telemetry import correlation

        assert correlation.coerce("Priya shipped the payments migration") is None
        assert correlation.coerce(uuid.uuid4().hex) is not None

    def test_a_job_span_carries_both_the_trace_and_the_correlation_id(
        self, spans: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """They coexist. `traceparent` joins the trace; the correlation id is
        what remains when there is no tracer to join."""
        envelope = JobEnvelope(job_type="pipeline.understand", tenant_id=uuid.uuid4())

        with telemetry.stage(
            "job", job_type=envelope.job_type, correlation_id=envelope.correlation_id
        ):
            pass

        [span] = spans.get_finished_spans()
        assert span.attributes["correlation_id"] == envelope.correlation_id


class TestADeployedEnvironmentCannotRunBlind:
    """Instrumentation that exports nowhere is the worst of both states.

    Every call site looks instrumented, every span is built and discarded, and
    it is discovered during the incident it was supposed to explain.
    """

    def _settings(self, environment: str) -> Any:
        from cairn_api.config import Settings

        return Settings.model_validate(
            {
                "environment": environment,
                "database_url": "postgresql+asyncpg://c:s@10.0.0.4:5432/c",
                "platform_database_url": "postgresql+asyncpg://c:s@10.0.0.4:5432/c",
                "cors_allowed_origins": ("https://app.example.com",),
                "github_webhook_secret": "a-real-secret",
                "email_backend": "smtp",
                "smtp_host": "relay.example.com",
            }
        )

    def test_local_development_needs_no_exporter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cairn_api.telemetry.startup import ENDPOINT_VARS, check_telemetry

        for name in ENDPOINT_VARS:
            monkeypatch.delenv(name, raising=False)

        check_telemetry(self._settings("local"))

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_a_deployed_environment_refuses_to_start_with_no_destination(
        self, environment: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cairn_api.telemetry.startup import (
            ENDPOINT_VARS,
            OPT_OUT_VAR,
            TelemetryConfigurationError,
            check_telemetry,
        )

        for name in (*ENDPOINT_VARS, OPT_OUT_VAR):
            monkeypatch.delenv(name, raising=False)

        with pytest.raises(TelemetryConfigurationError, match="discarded silently"):
            check_telemetry(self._settings(environment))

    def test_an_endpoint_satisfies_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from cairn_api.telemetry.startup import ENDPOINT_VARS, check_telemetry

        monkeypatch.setenv(ENDPOINT_VARS[0], "https://collector.example.com")

        check_telemetry(self._settings("production"))

    def test_running_without_telemetry_must_be_written_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An opt-out that has to be stated is the difference between a decision
        and an oversight."""
        from cairn_api.telemetry.startup import ENDPOINT_VARS, OPT_OUT_VAR, check_telemetry

        for name in ENDPOINT_VARS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(OPT_OUT_VAR, "true")

        check_telemetry(self._settings("production"))


class TestModelAndCostMetrics:
    def test_the_reported_tokens_are_the_ledger_s_own(self) -> None:
        """A dashboard that disagrees with the bill is worse than no dashboard.

        `BudgetedProvider` records to the ledger and reports the same numbers to
        telemetry — asserted by reading the ledger after a call rather than by
        trusting that two counters agree.
        """
        import asyncio

        from cairn_api.pipeline.provider import ModelRequest, ScriptedProvider
        from cairn_api.pipeline.spend import BudgetedProvider, TokenLedger

        ledger = TokenLedger(tenant="acme", max_tokens=None, max_calls=None)
        provider = BudgetedProvider(
            inner=ScriptedProvider(default="{}"), ledger=ledger, stage="extract"
        )

        asyncio.run(provider.complete(ModelRequest(instruction="i", untrusted_data="c")))

        assert ledger.total_tokens == ledger.by_stage["extract"].total_tokens
        assert ledger.by_stage["extract"].calls == 1

    def test_a_failed_model_call_is_still_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A timeout or a quota refusal is the call an operator alerts on.

        It used to be counted as nothing: `record_model_call` ran only after a
        successful response, so the failure rate was structurally zero while the
        `outcome` field sat unused on the recorder.
        """
        import asyncio

        from cairn_api.pipeline.provider import ModelProvider, ModelRequest, ModelResponse
        from cairn_api.pipeline.spend import BudgetedProvider, TokenLedger

        recorded: list[dict[str, Any]] = []

        class Recorder:
            def add(self, amount: int, attributes: dict[str, Any] | None = None) -> None:
                recorded.append(dict(attributes or {}))

        monkeypatch.setattr(telemetry.spans, "model_calls", Recorder())

        class Failing(ModelProvider):
            async def complete(self, request: ModelRequest) -> ModelResponse:
                raise TimeoutError("upstream took too long reading Priya's commit")

        provider = BudgetedProvider(
            inner=Failing(),
            ledger=TokenLedger(tenant="acme", max_tokens=None, max_calls=None),
            stage="extract",
        )

        with pytest.raises(TimeoutError):
            asyncio.run(provider.complete(ModelRequest(instruction="i", untrusted_data="c")))

        assert [entry["outcome"] for entry in recorded] == ["TimeoutError"]
        assert "Priya" not in str(recorded)

    def test_recording_a_call_carries_no_prompt_or_response(self, spans: Any) -> None:
        """The signature has nowhere to put one, which is the point."""
        import inspect

        signature = inspect.signature(telemetry.record_model_call)
        assert set(signature.parameters) <= {
            "model",
            "provider",
            "live",
            "tokens_in",
            "tokens_out",
            "cost_micros",
            "outcome",
        }

    def test_queue_and_evaluation_helpers_take_only_categories(self) -> None:
        import inspect

        assert set(inspect.signature(telemetry.record_queue_event).parameters) == {
            "job_type",
            "outcome",
            "priority",
        }
        assert set(inspect.signature(telemetry.record_evaluation).parameters) == {
            "result",
            "failure_mode",
        }
