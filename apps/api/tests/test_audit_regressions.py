"""Regression tests for the round-four audit findings.

Each of these guards a defect that was present, shipped, and passed every
existing test. They are grouped here rather than scattered so the pattern is
visible: **five of six were things that existed and were never reached** — a job
type with no handler, a status value never set, an endpoint that could not be
created, a gate reading a ratio over zero.

That is the same shape this project has produced in every audit round. The
difference here is that the code was correct and the wiring was absent, which no
unit test can catch — a correct function tested in isolation passes whether or
not anything calls it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cairn_api.api.app import create_app
from cairn_api.config import Settings
from cairn_api.db.github_models import DeliveryStatus
from cairn_api.evaluation.cases import GoldenCase, load_dataset
from cairn_api.evaluation.contract import PipelineOutput
from cairn_api.evaluation.gate import evaluate_gate
from cairn_api.evaluation.reference import ReferencePipeline
from cairn_api.evaluation.runner import run
from cairn_api.github.backfill import BACKFILL_JOB
from cairn_api.github.handlers import GITHUB_DELIVERY_JOB
from cairn_api.jobs.runner import registry as process_registry
from pydantic import SecretStr

TEST_SETTINGS = Settings(
    environment="test",
    github_webhook_secret=SecretStr("audit-secret"),
    cors_allowed_origins=("http://localhost:3000",),
)


class _NullQueue:
    """A queue that accepts registration and nothing else.

    `register_handlers` needs a queue because two handlers publish follow-on
    work, but registration itself never enqueues anything — so a stand-in that
    raises on every operation proves that. If registration ever starts
    publishing, this fails loudly instead of silently sending a message during
    a test run.
    """

    def __getattr__(self, name: str) -> Any:
        def refuse(*args: Any, **kwargs: Any) -> Any:
            msg = f"registration must not call queue.{name}()"
            raise AssertionError(msg)

        return refuse


class TestEveryPublishedJobHasAHandler:
    """Finding 1: `github.backfill` had no handler and no publisher.

    `create_run`, `claim` and `process_batch` were written, tested and correct.
    Nothing registered a handler and nothing published the job, so a run sat in
    PENDING forever — with no dead letter to notice, because nothing was ever
    enqueued.
    """

    def test_the_app_registers_a_handler_for_every_job_type_it_publishes(self) -> None:
        create_app(TEST_SETTINGS)
        registered = process_registry.registered_types()

        # Every constant naming a job type must resolve to a handler. A new job
        # type added without one produces messages that dead-letter as "unknown
        # job type" with the cause three files away.
        for job_type in (GITHUB_DELIVERY_JOB, BACKFILL_JOB):
            assert job_type in registered, f"{job_type} has no registered handler"

    def test_the_worker_registers_a_handler_for_every_job_type(self) -> None:
        """Drift between the API and the worker means the API can publish
        something no worker resolves — which fails silently in the queue rather
        than loudly at startup.

        **This assertion used to read the source of `run_worker` looking for the
        literal text `github_handlers.register()`.** It passed for the right
        reason and then failed for the wrong one, the first time somebody
        legitimately changed the call to pass arguments. A test that greps for a
        call site cannot tell a refactor from a regression, and it does not
        actually check the thing it claims to: source containing the text proves
        nothing about the registry.

        It now builds the worker's real registry and asserts on its contents,
        which is both the property that matters and one a refactor cannot break
        by accident.
        """
        from cairn_api.jobs.main import register_handlers
        from cairn_api.jobs.runner import JobRegistry
        from cairn_api.pipeline.jobs import UNDERSTAND_JOB

        registry = JobRegistry()
        register_handlers(_NullQueue(), registry)
        registered = registry.registered_types()

        for job_type in (GITHUB_DELIVERY_JOB, BACKFILL_JOB, UNDERSTAND_JOB):
            assert job_type in registered, (
                f"the worker has no handler for {job_type} — messages of this "
                "type dead-letter as 'unknown job type'"
            )


class TestClientAddressIsNotTheLoadBalancer:
    """Finding 2: `X-Forwarded-For` was read from the right.

    The rightmost entry is the one the *platform* appended — on Cloud Run,
    Google's front end, identical for effectively all traffic. Every caller in
    the world shared one rate-limit bucket, so the per-address login limit was a
    global limit: fifty failed logins anywhere would lock out every customer,
    and the product would accept five signups an hour.

    The limiter was correct, the store was shared, the tests passed, and the key
    was wrong.
    """

    @staticmethod
    def _request(header: str | None, hops: int) -> Any:
        """A stand-in for a Request.

        Deliberately not a real one: constructing a Starlette Request with an
        app, state and a client peer takes more setup than the thing under test,
        and the function reads exactly three attributes.
        """
        return SimpleNamespace(
            headers={"x-forwarded-for": header} if header else {},
            app=SimpleNamespace(
                state=SimpleNamespace(settings=SimpleNamespace(trusted_proxy_hops=hops))
            ),
            client=SimpleNamespace(host="10.0.0.1"),
        )

    def test_one_proxy_hop_yields_the_client_not_the_front_end(self) -> None:
        from cairn_api.api.dependencies import client_address

        # Cloud Run: "<client>, <google front end>".
        address = client_address(self._request("203.0.113.7, 35.191.0.1", 1))

        assert address == "203.0.113.7"

    def test_two_hops_are_supported_for_a_load_balancer(self) -> None:
        from cairn_api.api.dependencies import client_address

        address = client_address(self._request("203.0.113.7, 130.211.0.1, 35.191.0.1", 2))

        assert address == "203.0.113.7"

    def test_forged_leading_entries_are_ignored(self) -> None:
        # The mirror-image mistake: taking the leftmost entry trusts a value the
        # client supplied, handing an attacker a fresh bucket per request.
        from cairn_api.api.dependencies import client_address

        address = client_address(self._request("1.1.1.1, 2.2.2.2, 203.0.113.7, 35.191.0.1", 1))

        assert address == "203.0.113.7"

    def test_a_short_chain_does_not_select_a_proxy(self) -> None:
        # A chain shorter than the configured hop count means the request did
        # not arrive by the expected path. Clamping to the head is the safest of
        # the bad options — spoofable at worst, where a negative index would
        # silently select a proxy and collapse the buckets again.
        from cairn_api.api.dependencies import client_address

        assert client_address(self._request("203.0.113.7", 2)) == "203.0.113.7"

    def test_no_header_falls_back_to_the_peer(self) -> None:
        from cairn_api.api.dependencies import client_address

        assert client_address(self._request(None, 1)) == "10.0.0.1"


class TestTheEvaluationGateReadsItsDenominators:
    """Finding 3, and the worst of them.

    A pipeline that abstained on every case produced zero claims, and every
    metric is a ratio — so groundedness and attribution accuracy were both
    computed as 1.0 over nothing. It **passed the release gate at 100%** while
    generating a missed-signal finding on all fourteen cases.

    `report.py` already carried a comment saying a "100%" with nothing behind it
    has misled more dashboards than any wrong number. The renderer showed the
    denominator; the gate ignored it.
    """

    async def test_a_pipeline_that_asserts_nothing_is_blocked(self) -> None:
        class SaysNothing:
            async def run(self, case: GoldenCase) -> PipelineOutput:
                return PipelineOutput(abstained=True, narrative="")

        report = await run(load_dataset(), SaysNothing())
        gate = evaluate_gate(report, baseline={})

        # The metrics still read as perfect — that is the trap.
        assert report.groundedness == 1.0
        assert report.attribution_accuracy == 1.0
        assert report.total_claims == 0
        # And the gate now refuses them.
        assert gate.passed is False
        assert any("produced any claim" in reason for reason in gate.blocking)

    async def test_a_working_pipeline_still_passes(self) -> None:
        # The positive control. A coverage check that blocked everything would
        # satisfy the test above and make the gate useless.
        report = await run(load_dataset(), ReferencePipeline())
        gate = evaluate_gate(report, baseline={})

        assert report.case_coverage == 1.0
        assert gate.passed is True

    async def test_coverage_is_reported_next_to_the_metrics(self) -> None:
        # Buried, it would be a number nobody reads. Every other figure on the
        # report is meaningless when this one is low.
        report = await run(load_dataset(), ReferencePipeline())

        assert "case coverage" in report.render()


class TestDeliveryStatusIsActuallySet:
    """Finding 4: two status values were defined and never written.

    `FAILED` was never set, so a delivery that exhausted its retries stayed
    ACCEPTED forever — "queued" and "permanently failed" were the same value,
    and the column could not answer the one question it exists for.

    `UNCLAIMED` was never set either, while its own docstring said deliveries
    were "recorded rather than dropped so 'we are getting nothing from GitHub'
    has an answer". The handler logged and returned.
    """

    def test_every_status_value_is_reachable_from_production_code(self) -> None:
        import inspect

        from cairn_api.github import handlers, webhooks

        source = inspect.getsource(webhooks) + inspect.getsource(handlers)
        for status in DeliveryStatus:
            assert f"DeliveryStatus.{status.name}" in source, (
                f"DeliveryStatus.{status.name} is defined but never set — a column "
                "documenting a capability nothing implements"
            )

    def test_the_final_attempt_threshold_matches_the_retry_policy(self) -> None:
        # The handler must not depend on the worker, so the threshold is stated
        # separately — which means it can drift. This is the test that stops it.
        from cairn_api.github.handlers import FINAL_ATTEMPT_THRESHOLD
        from cairn_api.jobs.retry import DEFAULT_RETRY_POLICY

        assert DEFAULT_RETRY_POLICY.max_attempts == FINAL_ATTEMPT_THRESHOLD


class TestInstallationsCanBeCreated:
    """Finding 5: nothing in production could create a `GitHubInstallation`.

    Only a test fixture did. The webhook resolved installations, backfill needed
    them, and no code path created one — so Steps 11, 12 and 13 were unreachable
    end to end in production. Every test passed because every test built the row
    itself.
    """

    def test_a_connect_endpoint_exists(self) -> None:
        schema = create_app(TEST_SETTINGS).openapi()

        assert any("integrations/github" in path for path in schema["paths"])

    def test_the_webhook_still_cannot_create_one(self) -> None:
        """The fix must not be to let the webhook do it.

        An inbound webhook creating the mapping would mean whoever installed the
        app has their activity bound to a workspace nobody chose. The binding
        belongs behind a session, a membership and a permission check.
        """
        import inspect

        from cairn_api.github import webhooks

        source = inspect.getsource(webhooks)
        assert "GitHubInstallation(" not in source


class TestNoDuplicateJobTypeConstants:
    """Finding 6: `GITHUB_DELIVERY_JOB` was defined in two modules.

    Two sources of truth for a string that must match across a queue boundary.
    They agreed, which is exactly why nobody noticed.
    """

    def test_the_job_type_is_defined_once(self) -> None:
        from pathlib import Path

        source_root = Path(__file__).parents[1] / "src" / "cairn_api"
        definitions = [
            path
            for path in source_root.rglob("*.py")
            if 'GITHUB_DELIVERY_JOB = "' in path.read_text(encoding="utf-8")
        ]

        assert len(definitions) == 1, f"defined in {[p.name for p in definitions]}"


@pytest.mark.parametrize(
    "name",
    ["emulator_host"],
)
def test_dead_code_was_removed(name: str) -> None:
    """Finding 7: helpers with no caller anywhere, not even in tests.

    Small, but they accumulate — and each one is a thing a reader must decide is
    irrelevant. Listed by name so removing the guard requires deleting the
    assertion rather than quietly re-adding the function.
    """
    from cairn_api.jobs import pubsub

    assert not hasattr(pubsub, name), f"{name} has no callers and should be removed"
