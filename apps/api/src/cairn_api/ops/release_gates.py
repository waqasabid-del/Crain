"""What must be true of the outside world before CAIRN serves a customer.

Every other startup check in this codebase verifies something about *this*
process: that the database role cannot bypass row-level security, that the queue
is durable, that telemetry has somewhere to go. This module verifies the
opposite — the things CAIRN cannot check by itself, because they depend on an
account somebody has to create, a key somebody has to issue, or an app somebody
has to install.

**These are gates, not health checks.** A gate reports one of three states, and
the third is the reason the module exists:

- `PASSED` — configured, and verified as far as configuration can verify it.
- `BLOCKED` — not configured. The environment cannot do this thing.
- `UNVERIFIED` — configured, but proving it works needs a real request to a real
  external service, which no unit test may make.

The distinction between `PASSED` and `UNVERIFIED` is the whole point. A GitHub
App id in an environment variable proves somebody set a variable. It does not
prove the app is installed, that the webhook secret matches, or that a signed
delivery has ever arrived. Reporting that as "passed" is how a release gets
signed off on the strength of a `.env` file, so `verify` never claims more than
the evidence supports and names the manual command that would close the gap.

Nothing here calls out to a network. A release gate that made a live API call
would fail in CI for reasons unrelated to the code under test, and would need
production credentials to be present wherever it ran.
"""

from __future__ import annotations

import enum
import os
from collections.abc import Sequence
from dataclasses import dataclass

from cairn_api.config import Settings


class GateStatus(enum.StrEnum):
    """How far a release gate can be trusted."""

    #: Configured, and everything checkable from inside the process checks out.
    PASSED = "passed"

    #: Not configured. This environment cannot perform the capability at all.
    BLOCKED = "blocked"

    #: Configured, but the proof needs a real external round-trip.
    UNVERIFIED = "unverified"


@dataclass(frozen=True, slots=True)
class Gate:
    """One external dependency, and what is actually known about it."""

    name: str

    status: GateStatus

    #: What is true right now, in an operator's terms.
    detail: str

    #: The command or action that would move this gate forward. Empty only when
    #: the gate has genuinely passed.
    next_step: str = ""

    @property
    def blocks_release(self) -> bool:
        """Whether a live release may proceed.

        `UNVERIFIED` blocks as firmly as `BLOCKED`. The difference is what to do
        about it, not whether it is finished.
        """
        return self.status is not GateStatus.PASSED


def _email_gate(settings: Settings) -> Gate:
    """Transactional email.

    Nobody can be invited to a workspace without it, so "a team can be
    onboarded" is false until this passes — the difference between onboarding a
    team and onboarding a team *by the person who bought it*.
    """
    if settings.email_backend == "console":
        return Gate(
            name="email",
            status=GateStatus.BLOCKED if settings.is_deployed else GateStatus.UNVERIFIED,
            detail=(
                "Email is written to the log. Invitations and verification links reach nobody."
            ),
            next_step=(
                "Set CAIRN_EMAIL_BACKEND=smtp with CAIRN_SMTP_HOST, CAIRN_SMTP_USERNAME "
                "and CAIRN_SMTP_PASSWORD, then send one real invitation and confirm it "
                "arrives: uv run python -m cairn_api.email.probe --to you@example.com"
            ),
        )

    if not settings.smtp_host:
        return Gate(
            name="email",
            status=GateStatus.BLOCKED,
            detail="CAIRN_EMAIL_BACKEND=smtp but no relay host is configured.",
            next_step="Set CAIRN_SMTP_HOST.",
        )

    return Gate(
        name="email",
        status=GateStatus.UNVERIFIED,
        detail=f"An SMTP relay is configured at {settings.smtp_host}.",
        next_step=(
            "Send one real invitation to an address you control and confirm delivery, "
            "including that it did not land in spam. Configuration proves a relay was "
            "named, never that mail arrives."
        ),
    )


def _telemetry_gate(settings: Settings) -> Gate:
    """Spans and metrics reaching a collector.

    Instrumentation is a no-op until an SDK exporter is installed, so a deployed
    environment with no endpoint records everything and exports nothing.
    """
    from cairn_api.telemetry.startup import ENDPOINT_VARS, OPT_OUT_VAR

    endpoint = next((os.environ[name] for name in ENDPOINT_VARS if os.environ.get(name)), None)

    if endpoint is None:
        opted_out = os.environ.get(OPT_OUT_VAR, "").lower() == "true"
        return Gate(
            name="telemetry",
            status=GateStatus.BLOCKED,
            detail=(
                "No OTLP endpoint. Spans and metrics are built and discarded"
                + (f", accepted deliberately via {OPT_OUT_VAR}." if opted_out else ".")
            ),
            next_step=(
                f"Set {ENDPOINT_VARS[0]} to a collector, restart, and confirm a span "
                "for one webhook arrives in the backend."
            ),
        )

    return Gate(
        name="telemetry",
        status=GateStatus.UNVERIFIED,
        detail=f"An OTLP endpoint is configured at {endpoint}.",
        next_step=(
            "Send one webhook and find its trace in the collector. An endpoint that "
            "refuses connections looks identical to one nobody has sent to."
        ),
    )


def _queue_gate(settings: Settings) -> Gate:
    """The durable, fair queue.

    Passing needs no external service, which is why this is the one gate that
    can genuinely reach `PASSED` from configuration alone: PostgreSQL is already
    a hard dependency, and the fairness guarantee is enforced in a query this
    repository owns and tests.
    """
    if settings.queue_backend == "postgres":
        return Gate(
            name="queue",
            status=GateStatus.PASSED,
            detail=(
                "The PostgreSQL scheduler is selected: durable, priority-ordered, "
                "per-tenant fair, and reporting retry and dead-letter outcomes."
            ),
        )

    if settings.queue_backend == "memory":
        return Gate(
            name="queue",
            status=GateStatus.BLOCKED,
            detail="The in-memory broker loses every job on restart.",
            next_step="Set CAIRN_QUEUE_BACKEND=postgres.",
        )

    return Gate(
        name="queue",
        status=GateStatus.BLOCKED,
        detail=(
            "Pub/Sub is durable but cannot enforce per-tenant fairness and emits "
            "no retry or dead-letter metrics."
        ),
        next_step=(
            "Set CAIRN_QUEUE_BACKEND=postgres. Deployed environments refuse to start "
            "on Pub/Sub unless CAIRN_QUEUE_FAIRNESS_OPTIONAL=true accepts both losses."
        ),
    )


def _github_gate(settings: Settings) -> Gate:
    """A real GitHub App processing real activity.

    Stage B of the roadmap. Until a signed delivery from a real installation has
    been attributed correctly, the product's central claim is untested rather
    than unproven — the pipeline has only ever seen fixtures.
    """
    missing = [
        name
        for name, value in (
            ("CAIRN_GITHUB_APP_ID", settings.github_app_id),
            ("CAIRN_GITHUB_WEBHOOK_SECRET", settings.github_webhook_secret),
            ("CAIRN_GITHUB_PRIVATE_KEY", settings.github_private_key),
        )
        if not value
    ]

    if missing:
        return Gate(
            name="github",
            status=GateStatus.BLOCKED,
            detail=f"No GitHub App is configured: {', '.join(missing)} unset.",
            next_step=(
                "Create a GitHub App, install it on one repository, set the three "
                "variables, then push a commit and confirm a fact appears attributed "
                "to the right person."
            ),
        )

    return Gate(
        name="github",
        status=GateStatus.UNVERIFIED,
        detail="A GitHub App is configured.",
        next_step=(
            "Push one real commit to an installed repository and confirm the delivery "
            "verifies its signature and produces a correctly attributed fact. "
            "Credentials being present proves nothing about the installation."
        ),
    )


def _model_gate(settings: Settings) -> Gate:
    """A real model producing grounded, cited briefs.

    Stage C. The committed evaluation baseline was produced by a deterministic
    scripted provider because CI has no model credentials, and it says so — so
    every quality number in this repository measures the machinery, not the
    model.
    """
    if settings.model_backend == "scripted":
        return Gate(
            name="model",
            status=GateStatus.BLOCKED,
            detail=(
                "The scripted provider is selected. It is deterministic and real "
                "enough to exercise the pipeline, and it is not a model."
            ),
            next_step="Set CAIRN_MODEL_BACKEND=vertex with CAIRN_GCP_PROJECT_ID.",
        )

    if not settings.gcp_project_id:
        return Gate(
            name="model",
            status=GateStatus.BLOCKED,
            detail=(
                "No GCP project, so the pipeline runs without a model: nothing is "
                "extracted and every brief is empty."
            ),
            next_step="Set CAIRN_GCP_PROJECT_ID and grant the service account Vertex access.",
        )

    return Gate(
        name="model",
        status=GateStatus.UNVERIFIED,
        detail=f"Vertex is configured against project {settings.gcp_project_id}.",
        next_step=(
            "Run the evaluation against the live model and record a baseline: "
            "uv run python -m cairn_api.evaluation.runner --pipeline real. "
            "Groundedness and citation accuracy must be measured against a model, "
            "not against the scripted stand-in."
        ),
    )


def _audit_sink_gate(settings: Settings) -> Gate:
    """A record that survives a compromise of the database that holds it.

    The internal audit log is hash-chained, so an attacker inside the
    *application* can append but cannot rewrite history undetected — the
    application role holds INSERT and SELECT and neither UPDATE nor DELETE.

    What the chain cannot survive is the database *owner*. A compromise at that
    level can drop the table outright, and a chain nobody can read proves
    nothing. So this gate stays blocked until the record is replicated somewhere
    CAIRN's own operators cannot reach, and it exists in code rather than in a
    document so that "we should do that eventually" cannot quietly become
    "we did that".

    Tracked here, not fixed here: a second sink is a separate piece of
    infrastructure with its own retention, access model and failure modes.
    Until it exists, the honest external claim is "tamper-evident", never
    "immutable" or "customer-verifiable".
    """
    _ = settings
    return Gate(
        name="audit-sink",
        status=GateStatus.BLOCKED,
        detail=(
            "The internal audit log lives only in the application database. It is "
            "tamper-evident, not tamper-proof: a database-owner compromise can "
            "delete the whole record."
        ),
        next_step=(
            "Replicate the audit chain to an append-only sink outside this database "
            "and outside CAIRN operators' write access. Until then, do not describe "
            "the audit log externally as immutable or customer-verifiable — see "
            "md/16 Step 28, 'Still deferred from Step 27'."
        ),
    )


def evaluate_release_gates(settings: Settings | None = None) -> Sequence[Gate]:
    """Every dependency a live release turns on, in the order to close them."""
    from cairn_api.config import get_settings

    resolved = settings or get_settings()
    return (
        _queue_gate(resolved),
        _telemetry_gate(resolved),
        _email_gate(resolved),
        _github_gate(resolved),
        _model_gate(resolved),
        _audit_sink_gate(resolved),
    )


def blocking_gates(settings: Settings | None = None) -> Sequence[Gate]:
    """The gates standing between this configuration and a live release."""
    return tuple(gate for gate in evaluate_release_gates(settings) if gate.blocks_release)
