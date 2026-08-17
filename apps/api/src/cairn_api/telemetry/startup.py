"""Refuse to run a deployed environment blind.

Instrumentation is a no-op until an SDK exporter is installed into the
OpenTelemetry API. Locally that is exactly right — spans cost nothing and
nobody is collecting. In a deployed environment it is the failure mode Step 29
exists to remove: every span helper still runs, every call site still looks
instrumented, and nothing reaches a backend. The product appears observable and
is not, which is worse than being plainly uninstrumented, because it is only
discovered during the incident it was meant to explain.

So a deployed environment states its intent. Either an exporter endpoint is
configured, or telemetry is explicitly turned off — the same shape as the queue
and email backends, which refuse to start on a local default rather than
degrading quietly.

The endpoint is read from OpenTelemetry's own `OTEL_EXPORTER_OTLP_*` variables
rather than a CAIRN-specific setting. The SDK reads them directly, so a second
name for the same thing could disagree with the one actually in effect.
"""

from __future__ import annotations

import os

import structlog

from cairn_api.config import Settings

logger = structlog.get_logger(__name__)

#: The standard variables an OTLP exporter is configured through. Either the
#: general endpoint or the traces-specific one is enough.
ENDPOINT_VARS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
)

#: Set to "true" to run a deployed environment with no telemetry on purpose.
#: An opt-out that has to be written down is the difference between a decision
#: and an oversight.
OPT_OUT_VAR = "CAIRN_TELEMETRY_OPTIONAL"


class TelemetryConfigurationError(RuntimeError):
    """A deployed environment has no telemetry destination and has not said so."""


def check_telemetry(settings: Settings) -> None:
    """Verify a deployed environment can actually export what it records."""
    if not settings.is_deployed:
        return

    if any(os.environ.get(name) for name in ENDPOINT_VARS):
        return

    if os.environ.get(OPT_OUT_VAR, "").lower() == "true":
        logger.warning(
            "telemetry.disabled_deliberately",
            environment=settings.environment,
            detail=(
                "No OTLP endpoint is configured and "
                f"{OPT_OUT_VAR}=true. Spans and metrics are recorded into a "
                "no-op: an incident in this environment will have no trace."
            ),
        )
        return

    msg = (
        f"CAIRN_ENVIRONMENT is '{settings.environment}' but no OpenTelemetry "
        f"endpoint is set. Instrumentation would run and export nothing, so "
        f"every span and metric would be discarded silently — including the "
        f"ones needed to explain a bad brief. Set "
        f"{ENDPOINT_VARS[0]}, or set {OPT_OUT_VAR}=true to accept running "
        f"without telemetry."
    )
    raise TelemetryConfigurationError(msg)
