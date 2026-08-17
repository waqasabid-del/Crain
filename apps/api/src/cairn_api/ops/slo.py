"""Service level objectives.

"Slow" is not a number and cannot be alerted on. Each objective below states
four things, and the fourth is the one that makes it real:

1. **Target** — the number somebody agreed to.
2. **Window** — over what period it is judged. A latency target with no window
   is satisfied by one fast request.
3. **Measured from** — the exact column, table or instrument the number comes
   out of. Without this an SLO is aspiration with a decimal point.
4. **Whether it can be measured at all today.** Three of the five below can be,
   from durable tables. Two cannot, and they say so: `measurable=False` with the
   reason. A fabricated number is worse than a missing one, because somebody
   will make a decision with it.

The two unmeasurable objectives are kept here rather than deleted. An objective
nobody wrote down is one nobody notices is unmeasured, and both become
measurable the moment the metrics exporter has a destination — which is the
same Stage E gap OPERATIONS.md records under Alerting.

Nothing here measures a person. Every objective counts machine work: deliveries,
jobs, requests. A "team responsiveness" objective is the shape md/05 §B.2
forbids and is not an oversight to be corrected later.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import timedelta


class Unit(enum.StrEnum):
    """What the target's number means."""

    #: A proportion between 0 and 1. Rendered as a percentage by the reader.
    RATIO = "ratio"
    MINUTES = "minutes"
    MILLISECONDS = "milliseconds"


class Direction(enum.StrEnum):
    """Which side of the target passes.

    Explicit rather than inferred from the unit: an availability ratio wants
    "at least" and an error ratio wants "at most", and both are ratios.
    """

    AT_LEAST = "at_least"
    AT_MOST = "at_most"


@dataclass(frozen=True, slots=True)
class ServiceLevelObjective:
    """One objective, with its target and where the number comes from."""

    #: Stable identifier. Used by the read model and by any future alert rule,
    #: so it outlives rewording of the title.
    key: str

    title: str

    #: What the objective is for, in the terms an operator reading a page at
    #: 3am needs — not a restatement of the number.
    rationale: str

    target: float
    unit: Unit
    direction: Direction

    #: The period the measurement covers. For a live worst-case measurement
    #: (the queue objective) this is the period the *target* is judged over,
    #: not a lookback — noted in `measured_from`.
    window: timedelta

    #: The exact source of the number. A column, a pair of columns, or the
    #: instrument that would carry it. This field is the difference between an
    #: SLO and a slogan.
    measured_from: str

    #: Whether the current infrastructure can produce this number at all.
    measurable: bool

    #: Why not, when it cannot. Required in that case and asserted by the tests:
    #: an objective that reports "not measurable" without saying why is one
    #: nobody can fix.
    unmeasurable_reason: str | None = None

    def met(self, measured: float | None) -> bool | None:
        """Whether a measurement satisfies the target.

        `None` in, `None` out: an unmeasured objective is neither met nor
        breached, and collapsing it to `False` pages somebody for missing
        instrumentation while collapsing it to `True` is how an outage reports
        green.
        """
        if measured is None:
            return None
        if self.direction is Direction.AT_LEAST:
            return measured >= self.target
        return measured <= self.target


#: How long a delivery may take from acknowledgement to processed before it
#: counts against the pipeline objective. Fifteen minutes matches the queue
#: backlog warning in OPERATIONS.md deliberately: two thresholds describing the
#: same latency with different numbers is how an operator learns to trust
#: neither.
PIPELINE_COMPLETION_TARGET = timedelta(minutes=15)


WEBHOOK_ACKNOWLEDGEMENT = ServiceLevelObjective(
    key="webhook_acknowledgement",
    title="Webhook acknowledgement latency",
    rationale=(
        "GitHub retires a webhook that is not acknowledged quickly, and a "
        "retried delivery is one CAIRN has to deduplicate rather than one it "
        "processed. The work happens on the queue; the acknowledgement must not "
        "wait for it."
    ),
    target=500,
    unit=Unit.MILLISECONDS,
    direction=Direction.AT_MOST,
    window=timedelta(hours=1),
    measured_from=(
        "The API process's `cairn.stage.duration` histogram for the webhook "
        "route, at the 95th percentile."
    ),
    measurable=False,
    unmeasurable_reason=(
        "Nothing durable records when the request arrived. "
        "`webhook_deliveries.created_at` is written after the request has "
        "already been accepted and validated, so it cannot be differenced "
        "against an arrival time that was never stored. The histogram exists "
        "and is emitted; it goes nowhere until OTEL_EXPORTER_OTLP_ENDPOINT is "
        "set (OPERATIONS.md, Alerting)."
    ),
)


QUEUE_FIRST_ATTEMPT = ServiceLevelObjective(
    key="queue_first_attempt",
    title="Queue latency: longest wait for a first attempt",
    rationale=(
        "Queue depth hides one stuck job behind a thousand fast ones. The "
        "oldest waiting job is the honest measure, and it is the one "
        "OPERATIONS.md's backlog row already alerts on."
    ),
    target=15,
    unit=Unit.MINUTES,
    direction=Direction.AT_MOST,
    window=timedelta(minutes=15),
    measured_from=(
        "`max(now() - scheduled_jobs.enqueued_at)` over rows still in state "
        "'queued'. A live worst case, not a lookback: `ack` deletes the row, so "
        "no history of completed waits survives."
    ),
    measurable=True,
    unmeasurable_reason=None,
)


PIPELINE_COMPLETION = ServiceLevelObjective(
    key="pipeline_completion",
    title="Pipeline completion within fifteen minutes",
    rationale=(
        "The end-to-end promise: a push that has been accepted turns into "
        "recorded facts while the work is still fresh. This is the objective a "
        "customer would notice being missed."
    ),
    target=0.95,
    unit=Unit.RATIO,
    direction=Direction.AT_LEAST,
    window=timedelta(hours=24),
    measured_from=(
        "`webhook_deliveries`: the share of rows created in the window whose "
        "`processed_at - created_at` is at most fifteen minutes. Rows still "
        "unprocessed count as missed, so a stuck pipeline cannot report a "
        "perfect score by having completed nothing."
    ),
    measurable=True,
    unmeasurable_reason=None,
)


DELIVERY_ERROR_RATE = ServiceLevelObjective(
    key="delivery_error_rate",
    title="Delivery error rate",
    rationale=(
        "Distinguishes 'slow' from 'broken'. A delivery that failed is one a "
        "customer's activity never became a fact from, and no amount of "
        "throughput compensates for it."
    ),
    target=0.01,
    unit=Unit.RATIO,
    direction=Direction.AT_MOST,
    window=timedelta(hours=24),
    measured_from=(
        "`webhook_deliveries`: the share of rows created in the window whose "
        "`status` is 'failed'. Deliberately excludes 'unclaimed', which is an "
        "unknown or suspended installation rather than a fault in CAIRN."
    ),
    measurable=True,
    unmeasurable_reason=None,
)


AVAILABILITY = ServiceLevelObjective(
    key="availability",
    title="API availability",
    rationale=(
        "The objective every other one is conditional on. An API returning 503 "
        "has no latency worth measuring."
    ),
    target=0.995,
    unit=Unit.RATIO,
    direction=Direction.AT_LEAST,
    window=timedelta(days=30),
    measured_from=(
        "The share of `/readyz` probes and `/v1/*` requests that did not return "
        "5xx, from the load balancer or an external prober."
    ),
    measurable=False,
    unmeasurable_reason=(
        "CAIRN stores no request log and no probe history — deliberately, since "
        "a durable per-request record inside the product is a second copy of "
        "who did what. Availability has to be measured from outside the "
        "process: the load balancer, or a prober against /healthz and /readyz. "
        "Neither is deployed (OPERATIONS.md, Dashboards)."
    ),
)


#: Every objective, in the order an operator reads them: can it be reached, is
#: it working, is it fast, is it right.
OBJECTIVES: tuple[ServiceLevelObjective, ...] = (
    AVAILABILITY,
    WEBHOOK_ACKNOWLEDGEMENT,
    QUEUE_FIRST_ATTEMPT,
    PIPELINE_COMPLETION,
    DELIVERY_ERROR_RATE,
)


def objective(key: str) -> ServiceLevelObjective:
    """Look one up, or fail loudly.

    A missing objective is a typo in a caller, not a runtime condition to
    degrade around.
    """
    for candidate in OBJECTIVES:
        if candidate.key == key:
            return candidate
    msg = f"no service level objective named {key!r}"
    raise KeyError(msg)
