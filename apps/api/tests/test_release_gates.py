"""Release gates must never overstate what is proven.

The failure this file exists to prevent is a release signed off on the strength
of a `.env` file: a GitHub App id in an environment variable proves somebody set
a variable, not that an app is installed, that the webhook secret matches, or
that a signed delivery has ever arrived.

So the assertions here are mostly about the *absence* of a claim — that
configuration alone never reports `passed` for anything requiring an external
round-trip, and that a blocking gate always names the action that would close
it.
"""

from __future__ import annotations

import pytest
from cairn_api.config import Settings
from cairn_api.jobs.factory import QueueConfigurationError, build_queue
from cairn_api.ops.release_gates import (
    Gate,
    GateStatus,
    blocking_gates,
    evaluate_release_gates,
)

DEPLOYED: dict[str, object] = {
    "environment": "production",
    "database_url": "postgresql+asyncpg://cairn_app:s@10.0.0.4:5432/cairn",
    "platform_database_url": "postgresql+asyncpg://cairn:s@10.0.0.4:5432/cairn",
    "cors_allowed_origins": ("https://app.example.com",),
    "github_webhook_secret": "a-real-secret",
    "email_backend": "smtp",
    "smtp_host": "relay.example.com",
}


#: Slack credentials present and nothing proven — the state the connector gate
#: exists to refuse to call `passed`.
#:
#: `slack_redirect_uri` is https because a deployed `Settings` refuses anything
#: else: the install code arrives on that URL and is exchangeable for a
#: workspace's bot token by whoever sees it first.
SLACK_CONFIGURED: dict[str, object] = {
    "slack_client_id": "A0000000000",
    "slack_client_secret": "not-a-real-secret",
    "slack_signing_secret": "not-a-real-secret",
    "slack_redirect_uri": "https://app.example.com/v1/integrations/slack/callback",
}


def deployed(**overrides: object) -> Settings:
    return Settings.model_validate({**DEPLOYED, **overrides})


def gate_named(name: str, settings: Settings) -> Gate:
    return next(gate for gate in evaluate_release_gates(settings) if gate.name == name)


class TestNothingExternalIsEverClaimedProven:
    """Configuration cannot verify another company's service."""

    @pytest.mark.parametrize("name", ["github", "model", "email", "telemetry"])
    def test_a_configured_external_service_is_unverified_not_passed(
        self, name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example.com")

        settings = deployed(
            github_app_id="12345",
            # Deliberately not PEM-shaped. The gate only checks that a key is
            # configured, and a realistic-looking header here would train the
            # secret scanner's readers to wave one through.
            github_private_key="not-a-real-key",
            model_backend="vertex",
            gcp_project_id="cairn-prod",
        )

        assert gate_named(name, settings).status is GateStatus.UNVERIFIED

    def test_an_unverified_gate_still_blocks_the_release(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "Configured" is not "working". Both stop a release; only the remedy
        differs."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.example.com")

        gate = gate_named("telemetry", deployed())

        assert gate.status is GateStatus.UNVERIFIED
        assert gate.blocks_release

    @pytest.mark.parametrize(
        "name", ["github", "model", "email", "telemetry", "queue", "connectors"]
    )
    def test_every_blocking_gate_names_its_next_step(
        self, name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A gate that says "blocked" and nothing else is an observation, not a
        runbook.

        Measured against a bare local environment, because that is the one where
        every gate is genuinely unconfigured — a deployed `Settings` refuses to
        validate with the console email backend, so the unconfigured case cannot
        be built there at all.
        """
        for variable in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
            monkeypatch.delenv(variable, raising=False)

        gate = gate_named(name, Settings(model_backend="scripted"))

        assert gate.blocks_release
        assert gate.next_step != ""


class TestTheQueueGateIsTheOneThatCanPass:
    def test_the_postgres_scheduler_passes_on_its_own(self) -> None:
        """No external account is involved: the fairness guarantee is enforced by
        a query this repository owns and tests."""
        assert gate_named("queue", deployed(queue_backend="postgres")).status is GateStatus.PASSED

    @pytest.mark.parametrize("backend", ["memory", "pubsub"])
    def test_every_other_backend_blocks(self, backend: str) -> None:
        gate = gate_named("queue", deployed(queue_backend=backend, gcp_project_id="cairn-prod"))

        assert gate.status is GateStatus.BLOCKED
        assert "postgres" in gate.next_step


class TestProductionCannotSilentlyLoseFairness:
    """A log warning was not enough.

    An operator following an older runbook deploys Pub/Sub, the warning scrolls
    past, and the first person to notice is the customer whose live events are
    stuck behind somebody else's import.
    """

    @pytest.mark.parametrize("environment", ["staging", "production"])
    def test_a_deployed_environment_refuses_pubsub(self, environment: str) -> None:
        with pytest.raises(QueueConfigurationError, match="per-tenant fairness"):
            build_queue(
                deployed(
                    environment=environment,
                    queue_backend="pubsub",
                    gcp_project_id="cairn-prod",
                )
            )

    def test_the_refusal_names_both_losses(self) -> None:
        """Fairness is the famous one; the missing retry and dead-letter metrics
        are what leave the DLQ alert with nothing to fire on."""
        with pytest.raises(QueueConfigurationError) as raised:
            build_queue(deployed(queue_backend="pubsub", gcp_project_id="cairn-prod"))

        message = str(raised.value)
        assert "fairness" in message
        assert "dead-letter" in message

    def test_the_trade_can_be_accepted_deliberately(self) -> None:
        """Refusing outright would strand anyone with a real reason to run
        Pub/Sub. An opt-out that has to be written down is the difference between
        a decision and an oversight."""
        queue = build_queue(
            deployed(
                queue_backend="pubsub",
                gcp_project_id="cairn-prod",
                queue_fairness_optional=True,
            )
        )

        assert type(queue).__name__ == "PubSubJobQueue"

    def test_local_development_is_unaffected(self) -> None:
        assert type(build_queue(Settings(queue_backend="memory"))).__name__ == "InMemoryJobQueue"


class TestTheAuditSinkStaysHonest:
    """The chain resists the application, not the database owner.

    Tracked as a gate rather than a paragraph, so that "we should do that
    eventually" cannot quietly become "we did that".
    """

    def test_it_is_blocked_regardless_of_configuration(self) -> None:
        for settings in (Settings(), deployed(queue_backend="postgres")):
            assert gate_named("audit-sink", settings).status is GateStatus.BLOCKED

    def test_it_says_what_the_chain_does_not_survive(self) -> None:
        gate = gate_named("audit-sink", Settings())

        assert "database-owner" in gate.detail
        assert "append-only" in gate.next_step

    def test_it_forbids_the_external_claim_rather_than_implying_it(self) -> None:
        """The wording an audit already flagged: "customer-verifiable" and
        "immutable" are both false while one database holds the only copy."""
        gate = gate_named("audit-sink", Settings())

        assert "immutable" in gate.next_step
        assert "customer-verifiable" in gate.next_step


class TestTheConnectorGateCannotPass:
    """Slack and Google Chat arrive in Step 32; this gate arrives first.

    Written before the connectors so that the first thing anybody can say about
    them is bounded by evidence. Every input the gate has is configuration — a
    client id, a signing secret, a service account — and none of them is a
    delivery, so `PASSED` is unreachable by construction rather than by accident.
    The detailed assertions live in `test_connector_ops.py`; these two pin the
    gate's place in the release list.
    """

    def test_it_is_evaluated_with_the_others(self) -> None:
        assert "connectors" in {gate.name for gate in evaluate_release_gates(Settings())}

    def test_no_configuration_makes_it_pass(self) -> None:
        for settings in (Settings(), deployed(queue_backend="postgres")):
            assert gate_named("connectors", settings).status is not GateStatus.PASSED

    def test_configured_slack_is_manual_and_still_blocks(self) -> None:
        """The Step 32 case, stated where the release list is assembled.

        Three Slack environment variables can all be correct while the app is
        not installed, while the Events API Request URL was never verified, or —
        most often — while the bot has never been invited to a channel. Every
        configuration check passes in that state and no event has ever arrived,
        so `MANUAL` is the strongest honest answer and it blocks exactly as
        firmly as `BLOCK`.
        """
        gate = gate_named("connectors", deployed(**SLACK_CONFIGURED))

        assert gate.status is GateStatus.UNVERIFIED
        assert gate.blocks_release
        assert "slack" in gate.detail
        assert "invite" in gate.next_step


class TestTheHonestSummary:
    def test_a_local_environment_reports_the_work_that_remains(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The state this repository is actually in. If this ever reports zero
        blocking gates without the external work being done, the gates have
        stopped being honest."""
        for variable in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
            monkeypatch.delenv(variable, raising=False)

        blocking = {gate.name for gate in blocking_gates(Settings())}

        assert {"github", "model", "email", "telemetry"} <= blocking

    def test_the_cli_exits_non_zero_while_anything_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """So a deployment pipeline can call it as a step rather than a person
        reading a table and deciding."""
        from cairn_api.ops.gates_cli import main

        for variable in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
            monkeypatch.delenv(variable, raising=False)

        assert main() == 1
