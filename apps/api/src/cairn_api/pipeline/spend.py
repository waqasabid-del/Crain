"""Token accounting, spend ceilings, and the signals they raise.

A ceiling, not a rate limit: decides whether calls happen at all, not just
when. Exceeding it raises rather than degrading silently. Attribution is per
stage (md/10 §7). Two ceilings: the call ceiling backstops a provider that
reports zero tokens. In-process only, not durable across replicas (Stage E).

**A ceiling that is being hit is a signal, not just a control.** Capping spend
silently means the first anyone hears of a runaway is a customer asking why
their briefs stopped. So two things are recorded on the way past: the ceiling
being *approached*, while there is still time to act, and the ceiling actually
*refusing* work, which is what OPERATIONS.md's cost table pages on. Both are
counts and ratios — `SPEND_SIGNALS` holds nothing a prompt or a statement could
reach.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import structlog

from cairn_api import telemetry
from cairn_api.config import Settings, get_settings
from cairn_api.pipeline.provider import ModelProvider, ModelRequest, ModelResponse

if TYPE_CHECKING:
    import uuid

    from cairn_api.pipeline.spend_store import SpendStore as SpendStoreLike

logger = structlog.get_logger(__name__)

#: Stage label for a caller that wraps a provider without naming a stage.
UNATTRIBUTED = "unattributed"

#: The fraction of a ceiling at which an operator is warned.
#:
#: Eight tenths rather than nineteen twentieths: the point of a warning is that
#: somebody can still raise the ceiling or stop the backfill. A signal that
#: arrives at the moment of refusal is a post-mortem with an alert's urgency.
APPROACH_RATIO = 0.8

#: Telemetry outcome for a call the ceiling refused.
#:
#: Recorded on the model-call counter rather than a counter of its own, because
#: `telemetry/` is a fixed allow-list and `outcome` is already on it. A refusal
#: adds one to the call count and zero to the token and cost counters, so the
#: spend dashboards stay truthful while the refusal rate becomes alertable.
REFUSED_OUTCOME = "spend_ceiling_refused"


class SpendCeilingError(RuntimeError):
    """Ceiling reached; the call was not made.

    Deliberately not a `provider.ModelError`: stages retry those, and retrying
    is what ran up the bill.
    """

    def __init__(self, tenant: str, detail: str) -> None:
        self.tenant = tenant
        self.detail = detail
        super().__init__(f"model spend ceiling reached for tenant {tenant!r}: {detail}")


@dataclass(frozen=True, slots=True)
class StageSpend:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class TokenLedger:
    """One tenant's model spend, and the ceilings on it.

    Per tenant rather than global: a global ceiling turns one workspace's
    backfill into an availability incident for every other tenant.
    """

    tenant: str

    #: `None` disables the token ceiling (call ceiling still applies).
    max_tokens: int | None

    #: Backstop for a provider that reports no token usage.
    max_calls: int | None

    _by_stage: dict[str, StageSpend] = field(default_factory=dict)

    #: Whether this ledger has already raised each signal. A ledger is built per
    #: unit of work, so "once" means once per job — the granularity an operator
    #: counting "how often does this happen" actually wants. Without them, a
    #: stage that swallows the refusal and retries writes a line per attempt and
    #: buries the first one.
    _approach_logged: bool = False
    _refusal_logged: bool = False

    @property
    def by_stage(self) -> dict[str, StageSpend]:
        """A copy: a caller reading a cost report can't mutate the ledger."""
        return dict(self._by_stage)

    @property
    def total_tokens(self) -> int:
        return sum(spend.total_tokens for spend in self._by_stage.values())

    @property
    def total_calls(self) -> int:
        return sum(spend.calls for spend in self._by_stage.values())

    @property
    def exceeded(self) -> bool:
        """Lets stages that swallow exceptions tell refusal from outage."""
        return self._breach() is not None

    @property
    def usage_ratio(self) -> float | None:
        """How close this ledger is to whichever ceiling it will hit first.

        `None` means no ceiling is configured, which is deliberately distinct
        from `0.0` — "unbounded" and "bounded and untouched" are different
        things to see on an operations screen, and collapsing them is how an
        unlimited deployment reads as a healthy one.
        """
        ratios = [
            _ratio(self.total_tokens, self.max_tokens),
            _ratio(self.total_calls, self.max_calls),
        ]
        measured = [ratio for ratio in ratios if ratio is not None]
        return max(measured) if measured else None

    @property
    def approaching(self) -> bool:
        """Near the ceiling but not yet refusing.

        Excludes the breached state on purpose: once work is being refused the
        operator needs the refusal signal, and reporting both would double-count
        one incident across two alert rules.
        """
        ratio = self.usage_ratio
        return ratio is not None and ratio >= APPROACH_RATIO and not self.exceeded

    def _breach(self) -> str | None:
        if self.max_tokens is not None and self.total_tokens >= self.max_tokens:
            return f"{self.total_tokens} tokens used of {self.max_tokens} permitted"
        if self.max_calls is not None and self.total_calls >= self.max_calls:
            return f"{self.total_calls} calls made of {self.max_calls} permitted"
        return None

    def check(self) -> None:
        """Checked before the call, recorded after: overshoot is bounded to
        one call since a call's cost is unknowable until it returns."""
        breach = self._breach()
        if breach is not None:
            raise SpendCeilingError(self.tenant, breach)

    def record(self, stage: str, response: ModelResponse) -> None:
        previous = self._by_stage.get(stage, StageSpend())
        self._by_stage[stage] = StageSpend(
            calls=previous.calls + 1,
            input_tokens=previous.input_tokens + response.input_tokens,
            output_tokens=previous.output_tokens + response.output_tokens,
        )

    def claim_approach_log(self) -> bool:
        """True the first time this ledger is asked to log an approach.

        A claim rather than a flag read so the caller cannot forget to set it,
        which is the version of this that logs on every call.
        """
        if self._approach_logged:
            return False
        self._approach_logged = True
        return True

    def claim_refusal_log(self) -> bool:
        """True the first time this ledger is asked to log a refusal."""
        if self._refusal_logged:
            return False
        self._refusal_logged = True
        return True


def _ratio(used: int, ceiling: int | None) -> float | None:
    """Consumption against one ceiling, or `None` when it is not configured.

    A ceiling of zero refuses everything, so it is fully consumed by
    definition — dividing would raise, and reporting `None` would render a
    deployment that refuses all work as one with no limits at all.
    """
    if ceiling is None:
        return None
    if ceiling <= 0:
        return 1.0
    return used / ceiling


@dataclass(frozen=True, slots=True)
class StageSignal:
    """What one stage spent, and how close it came to the ceiling.

    Numbers only. There is nowhere here to put a prompt, a statement or a
    workspace name, which is what makes it safe to put on a dashboard.
    """

    stage: str
    calls: int = 0
    tokens: int = 0

    #: Times the ceiling was approached and times it refused work, since this
    #: process started.
    warnings: int = 0
    refusals: int = 0

    #: The highest fraction of a ceiling any single unit of work reached in this
    #: stage. `None` when no ceiling is configured. This is the "how close" an
    #: operator reads before deciding whether a cap needs raising.
    #:
    #: Not clamped at 1.0. The ceiling permits one call of overshoot by design,
    #: and a value far above 1 says one call costs more than the entire ceiling
    #: — which clamping would render as a tidy "at the limit".
    closest_approach: float | None = None


@dataclass
class SpendSignals:
    """Process-wide spend counters, for the operations read model.

    Separate from `TokenLedger` because a ledger belongs to one unit of work and
    is discarded with it. Reading a freshly built ledger — which is what
    `/operations/spend` did — reports zero however much the process has spent,
    so the screen was structurally incapable of showing a cost incident.

    Per replica, exactly like the ledger, and for the same reason: no durable
    spend store exists yet. The read model states that rather than implying a
    platform-wide figure.
    """

    #: Guarded because a read-modify-write of a frozen `StageSignal` is not
    #: atomic, and the API serves handlers from a threadpool. A lost increment
    #: on a refusal counter is a missed page.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    _by_stage: dict[str, StageSignal] = field(default_factory=dict)

    #: Distinct tenants that have had work refused. Reported as a count only:
    #: "one workspace" and "every workspace" need completely different first
    #: actions, and neither answer requires naming anybody.
    _tenants_refused: set[str] = field(default_factory=set, repr=False)

    def spent(self, *, stage: str, tokens: int, ratio: float | None) -> None:
        """One completed model call."""
        with self._lock:
            current = self._by_stage.get(stage, StageSignal(stage=stage))
            self._by_stage[stage] = replace(
                current,
                calls=current.calls + 1,
                tokens=current.tokens + tokens,
                closest_approach=_higher(current.closest_approach, ratio),
            )

    def approached(self, *, stage: str) -> None:
        """One unit of work came within `APPROACH_RATIO` of its ceiling."""
        with self._lock:
            current = self._by_stage.get(stage, StageSignal(stage=stage))
            self._by_stage[stage] = replace(current, warnings=current.warnings + 1)

    def refused(self, *, stage: str, tenant: str) -> None:
        """One call the ceiling did not allow to happen."""
        with self._lock:
            current = self._by_stage.get(stage, StageSignal(stage=stage))
            self._by_stage[stage] = replace(
                current,
                refusals=current.refusals + 1,
                # A refusal means the ceiling was reached, whatever the last
                # completed call measured.
                closest_approach=_higher(current.closest_approach, 1.0),
            )
            self._tenants_refused.add(tenant)

    def snapshot(self) -> tuple[StageSignal, ...]:
        """Every stage seen so far, in a stable order."""
        with self._lock:
            return tuple(signal for _, signal in sorted(self._by_stage.items()))

    @property
    def warnings(self) -> int:
        return sum(signal.warnings for signal in self.snapshot())

    @property
    def refusals(self) -> int:
        return sum(signal.refusals for signal in self.snapshot())

    @property
    def workspaces_refused(self) -> int:
        with self._lock:
            return len(self._tenants_refused)

    @property
    def total_calls(self) -> int:
        return sum(signal.calls for signal in self.snapshot())

    @property
    def total_tokens(self) -> int:
        return sum(signal.tokens for signal in self.snapshot())

    def reset(self) -> None:
        """Empty the counters. For tests, which must not inherit each other's
        spend, and for nothing else — an operator clearing a refusal count is
        clearing the evidence."""
        with self._lock:
            self._by_stage.clear()
            self._tenants_refused.clear()


def _higher(current: float | None, candidate: float | None) -> float | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate)


#: The process's spend signals. Module-level for the same reason the ledger is
#: in-process: there is nowhere durable to put it yet, and a screen reading
#: nothing is worse than a screen reading one replica and saying so.
SPEND_SIGNALS = SpendSignals()


def ledger_for(tenant: str, settings: Settings | None = None) -> TokenLedger:
    """A ledger with this deployment's configured ceilings."""
    resolved = settings or get_settings()
    return TokenLedger(
        tenant=tenant,
        max_tokens=resolved.model_max_tokens_per_tenant,
        max_calls=resolved.model_max_calls_per_tenant,
    )


@dataclass(frozen=True, slots=True)
class BudgetedProvider:
    """A `ModelProvider` that spends against a ledger — a decorator so no
    stage has to know a budget exists, and it can't be bypassed by accident.

    With a `store`, the ceiling gains a memory: the durable period counters in
    `spend_store` are consulted — and the call atomically reserved — before the
    in-process check, so restarts forget nothing and replicas share one
    ceiling. Without one, behaviour is exactly what it was: per-unit-of-work,
    in-process, the configuration unit tests run against.
    """

    inner: ModelProvider
    ledger: TokenLedger

    #: Bound at wrap time, not read from the request — a request carries no identity.
    stage: str = UNATTRIBUTED

    #: The durable counters, when the deployment has them. `None` preserves the
    #: historical in-process behaviour byte for byte.
    store: SpendStoreLike | None = None

    #: The tenant as a UUID for the store's tenant-scoped rows. The ledger's
    #: `tenant` string stays what it was because log lines and tests read it.
    tenant_id: uuid.UUID | None = None

    def for_stage(self, stage: str) -> BudgetedProvider:
        """Shared, not copied: copying would multiply the ceiling per stage."""
        return BudgetedProvider(
            inner=self.inner,
            ledger=self.ledger,
            stage=stage,
            store=self.store,
            tenant_id=self.tenant_id,
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            self.ledger.check()
            if self.store is not None and self.tenant_id is not None:
                # Pre-dispatch and atomic: the call is counted in the same
                # operation that checks the period ceiling, which is what makes
                # two replicas provably unable to jointly exceed it. Raises the
                # same SpendCeilingError, so every refusal path downstream —
                # the signal counters, the once-per-job log claim, the stages
                # that swallow and degrade — behaves identically.
                await self.store.reserve_call(
                    self.tenant_id,
                    stage=self.stage,
                    max_tokens=self.ledger.max_tokens,
                    max_calls=self.ledger.max_calls,
                )
        except SpendCeilingError as refusal:
            # Recorded here rather than inside `check()` because the ledger does
            # not know which stage is asking, and "which stage is being refused"
            # is the first thing an operator needs — synthesis stopping and
            # extraction stopping are different incidents.
            self._record_refusal(refusal)
            raise

        try:
            with telemetry.stage(f"model.{self.stage}", stage=self.stage):
                response = await self.inner.complete(request)
        except Exception as error:
            # A call that failed is still a call, and the one an operator alerts
            # on. Recorded only on the counter — a provider's exception message
            # routinely quotes the request that produced it, so the category is
            # the part that is safe to keep.
            telemetry.record_model_call(
                model="unknown",
                provider=type(self.inner).__name__,
                live=False,
                outcome=telemetry.error_category(error),
            )
            raise

        self.ledger.record(self.stage, response)
        if self.store is not None and self.tenant_id is not None:
            await self.store.record_tokens(
                self.tenant_id,
                stage=self.stage,
                tokens=response.input_tokens + response.output_tokens,
            )
        SPEND_SIGNALS.spent(
            stage=self.stage,
            tokens=response.input_tokens + response.output_tokens,
            ratio=self.ledger.usage_ratio,
        )

        # The same numbers the ledger recorded, never a second count: a
        # dashboard that disagrees with the bill is worse than no dashboard.
        telemetry.record_model_call(
            model=response.model,
            provider=type(self.inner).__name__,
            live=not response.model.startswith("offline"),
            tokens_in=response.input_tokens,
            tokens_out=response.output_tokens,
        )

        if self.ledger.approaching:
            self._record_approach()

        if self.ledger.exceeded:
            # Logged when crossed, not when refused: the refusal may be swallowed
            # by a stage that degrades on any exception.
            logger.warning(
                "spend.ceiling_reached",
                tenant=self.ledger.tenant,
                stage=self.stage,
                total_tokens=self.ledger.total_tokens,
                total_calls=self.ledger.total_calls,
            )
        return response

    def _record_approach(self) -> None:
        """The warning half of OPERATIONS.md's cost row.

        Counted every time so a rate is available, logged once per ledger so the
        line is readable. There is no metric for it: `telemetry/` is a closed
        allow-list of instruments, and inventing a model call that did not happen
        to carry the signal would corrupt the spend counters it shares.
        """
        SPEND_SIGNALS.approached(stage=self.stage)
        if not self.ledger.claim_approach_log():
            return

        ratio = self.ledger.usage_ratio
        logger.warning(
            "spend.ceiling_approaching",
            tenant=self.ledger.tenant,
            stage=self.stage,
            # Two decimals: the useful distinction is 0.81 from 0.95, not the
            # sixteenth digit of a float in a log aggregator.
            usage_ratio=round(ratio, 2) if ratio is not None else None,
            total_tokens=self.ledger.total_tokens,
            max_tokens=self.ledger.max_tokens,
            total_calls=self.ledger.total_calls,
            max_calls=self.ledger.max_calls,
        )

    def _record_refusal(self, refusal: SpendCeilingError) -> None:
        """The page half of OPERATIONS.md's cost row.

        `detail` is the ledger's own breach sentence — two integers and the word
        between them. It is the only string here, and it cannot carry a request.
        """
        SPEND_SIGNALS.refused(stage=self.stage, tenant=self.ledger.tenant)
        telemetry.record_model_call(
            model="unknown",
            provider=type(self.inner).__name__,
            live=False,
            outcome=REFUSED_OUTCOME,
        )
        if not self.ledger.claim_refusal_log():
            return

        logger.error(
            "spend.ceiling_refused",
            tenant=self.ledger.tenant,
            stage=self.stage,
            detail=refusal.detail,
        )
