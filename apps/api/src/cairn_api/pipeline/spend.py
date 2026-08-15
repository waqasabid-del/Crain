"""Token accounting and spend ceilings.

A ceiling, not a rate limit: decides whether calls happen at all, not just
when. Exceeding it raises rather than degrading silently. Attribution is per
stage (md/10 §7). Two ceilings: the call ceiling backstops a provider that
reports zero tokens. In-process only, not durable across replicas (Stage E).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from cairn_api.config import Settings, get_settings
from cairn_api.pipeline.provider import ModelProvider, ModelRequest, ModelResponse

logger = structlog.get_logger(__name__)

#: Stage label for a caller that wraps a provider without naming a stage.
UNATTRIBUTED = "unattributed"


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
    """

    inner: ModelProvider
    ledger: TokenLedger

    #: Bound at wrap time, not read from the request — a request carries no identity.
    stage: str = UNATTRIBUTED

    def for_stage(self, stage: str) -> BudgetedProvider:
        """Shared, not copied: copying would multiply the ceiling per stage."""
        return BudgetedProvider(inner=self.inner, ledger=self.ledger, stage=stage)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.ledger.check()
        response = await self.inner.complete(request)
        self.ledger.record(self.stage, response)

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
