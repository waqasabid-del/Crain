"""Spend ceilings.

A cost control is only real if it has been watched refuse something. Every test
here is written in the direction that can fail: not "the ledger adds up" — which
would pass on a ledger nobody consults — but "the call did not happen", "the
second stage could not spend the first stage's headroom", "a lying provider
still gets stopped".

The load-bearing one is `test_a_stage_that_swallows_the_error_still_stops_spending`.
`classify` and `extract` catch every exception on purpose, so a budget refusal
reaching them is absorbed. That is fine only if the *ledger* keeps refusing, and
an assertion that it does is the difference between a ceiling and a log line.
"""

from __future__ import annotations

import pytest
from cairn_api.config import Settings
from cairn_api.pipeline.classify import EventClass, classify
from cairn_api.pipeline.provider import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ScriptedProvider,
)
from cairn_api.pipeline.spend import (
    UNATTRIBUTED,
    BudgetedProvider,
    SpendCeilingError,
    TokenLedger,
    ledger_for,
)

pytestmark = pytest.mark.anyio


class CountingProvider:
    """Reports fixed usage and counts how many times it was actually called.

    The count is the assertion that matters. A ceiling that raises *after*
    reaching the model has prevented nothing — the tokens are already spent and
    the bill already exists.
    """

    def __init__(self, input_tokens: int = 10, output_tokens: int = 5) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        return ModelResponse(
            text="{}",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model="counting",
        )


def request() -> ModelRequest:
    return ModelRequest(instruction="do the thing", untrusted_data="content")


def ledger(**overrides: object) -> TokenLedger:
    fields: dict[str, object] = {"tenant": "acme", "max_tokens": 100, "max_calls": None}
    fields.update(overrides)
    return TokenLedger(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The ceiling refuses
# --------------------------------------------------------------------------


async def test_the_call_is_not_made_once_the_ceiling_is_reached() -> None:
    """The point of the whole module, asserted against the provider's call count.

    A budget that raises after the model has answered has recorded an overspend
    rather than prevented one.
    """
    inner = CountingProvider(input_tokens=60, output_tokens=0)
    provider = BudgetedProvider(inner=inner, ledger=ledger(max_tokens=100), stage="extract")

    await provider.complete(request())  # 60 of 100
    await provider.complete(request())  # 120 of 100 — the permitted overshoot

    with pytest.raises(SpendCeilingError) as caught:
        await provider.complete(request())

    assert inner.calls == 2, "the refused call reached the model anyway"
    assert caught.value.tenant == "acme"
    assert "120 tokens used of 100" in str(caught.value)


async def test_the_overshoot_is_at_most_one_call() -> None:
    """The documented imprecision, pinned so it cannot quietly grow.

    A call's cost is unknowable until it returns, so the ceiling is checked
    before and recorded after. That admits exactly one call of overshoot. If
    someone later moves the check, or batches several calls between checks, the
    overshoot becomes unbounded and this fails.
    """
    inner = CountingProvider(input_tokens=1000, output_tokens=0)
    provider = BudgetedProvider(inner=inner, ledger=ledger(max_tokens=10))

    await provider.complete(request())
    with pytest.raises(SpendCeilingError):
        await provider.complete(request())

    assert inner.calls == 1


async def test_a_provider_reporting_no_tokens_is_still_bounded() -> None:
    """The hole a token-only ceiling has.

    `ScriptedProvider` genuinely reports zero tokens, and so would a real
    adapter whose SDK response had no usage block, or one that was simply
    broken. Under a token-only ceiling every one of those spends without limit
    while the accounting reports zero — the ceiling would be most permissive
    exactly when the instrumentation is least trustworthy.
    """
    inner = ScriptedProvider(default="{}")
    budget = ledger(max_tokens=1_000_000, max_calls=3)
    provider = BudgetedProvider(inner=inner, ledger=budget)

    for _ in range(3):
        await provider.complete(request())
    with pytest.raises(SpendCeilingError, match="3 calls made of 3 permitted"):
        await provider.complete(request())

    assert budget.total_tokens == 0, "the provider reported usage it does not have"
    assert len(inner.calls) == 3


async def test_a_ledger_with_no_ceilings_never_refuses() -> None:
    """Both ceilings off is a supported configuration and must not half-work."""
    provider = BudgetedProvider(
        inner=CountingProvider(), ledger=ledger(max_tokens=None, max_calls=None)
    )
    for _ in range(50):
        await provider.complete(request())
    assert provider.ledger.total_calls == 50


# --------------------------------------------------------------------------
# Per-stage attribution (md/10 §7)
# --------------------------------------------------------------------------


async def test_spend_is_itemised_by_stage() -> None:
    """ "Which stage costs the money" is the question md/10 §7 requires answering.

    A total alone answers "are we spending too much" and never "on what" — and
    the fix differs entirely: classification is a cheap model over every raw
    event, synthesis is a premium model over a few dozen facts.
    """
    base = BudgetedProvider(
        inner=CountingProvider(input_tokens=10, output_tokens=5), ledger=ledger(max_tokens=None)
    )

    await base.for_stage("classify").complete(request())
    await base.for_stage("classify").complete(request())
    await base.for_stage("synthesize").complete(request())

    by_stage = base.ledger.by_stage
    assert by_stage["classify"].calls == 2
    assert by_stage["classify"].total_tokens == 30
    assert by_stage["synthesize"].calls == 1
    assert by_stage["synthesize"].total_tokens == 15


async def test_stages_share_one_ceiling_rather_than_each_getting_their_own() -> None:
    """`for_stage` is a view, not a fresh budget.

    A copy per stage would multiply the configured ceiling by the number of
    stages — a four-stage pipeline silently permitted four times the spend the
    operator set, which is worse than having no ceiling because it looks like
    one.
    """
    base = BudgetedProvider(
        inner=CountingProvider(input_tokens=40, output_tokens=0), ledger=ledger(max_tokens=100)
    )

    await base.for_stage("classify").complete(request())
    await base.for_stage("extract").complete(request())
    await base.for_stage("synthesize").complete(request())

    with pytest.raises(SpendCeilingError):
        await base.for_stage("resolve").complete(request())


async def test_unattributed_spend_is_labelled_as_such() -> None:
    """Wrapping without naming a stage is allowed — the budget must apply even
    when nobody bothered to attribute it — but it is not reported as a stage.

    A default of "unknown" would read, in a cost report, as an attribution that
    failed rather than one nobody made.
    """
    provider = BudgetedProvider(inner=CountingProvider(), ledger=ledger(max_tokens=None))
    await provider.complete(request())
    assert set(provider.ledger.by_stage) == {UNATTRIBUTED}


async def test_a_cost_report_cannot_mutate_the_ledger_it_came_from() -> None:
    provider = BudgetedProvider(inner=CountingProvider(), ledger=ledger(max_tokens=None))
    await provider.complete(request())

    provider.ledger.by_stage.clear()
    assert provider.ledger.total_calls == 1


# --------------------------------------------------------------------------
# Behaviour under the stages that swallow exceptions
# --------------------------------------------------------------------------


async def test_a_stage_that_swallows_the_error_still_stops_spending() -> None:
    """The honest limitation, tested rather than asserted in a docstring.

    `classify` degrades on any exception so that a model outage cannot stop
    ingestion, which means it absorbs a budget refusal too. That is acceptable
    only because the ledger keeps refusing: the cost of a swallowed refusal is a
    diagnostic, not another model call. If the ledger ever reset or the wrapper
    ever fell through on error, this test is what notices.
    """
    inner = CountingProvider(input_tokens=1000, output_tokens=0)
    budget = ledger(max_tokens=10)
    provider = BudgetedProvider(inner=inner, ledger=budget, stage="classify")

    first = await classify(provider, content="anything")
    assert first.event_class is EventClass.UNKNOWN  # scripted "{}" is unusable

    for _ in range(5):
        result = await classify(provider, content="anything")
        assert result.event_class is EventClass.UNKNOWN

    assert inner.calls == 1, "the ceiling stopped applying once a stage swallowed it"
    assert budget.exceeded, "the caller has no way to tell a ceiling from an outage"


async def test_the_ceiling_error_is_not_a_model_error() -> None:
    """Retry handlers catch `ModelError` because a model failure is often
    transient. A ceiling is the opposite: retrying is the behaviour that spent
    the money. Sharing a base class would put the refusal directly into a retry
    loop.
    """
    from cairn_api.pipeline.provider import ModelError

    assert not issubclass(SpendCeilingError, ModelError)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def test_ledger_for_takes_its_ceilings_from_settings() -> None:
    settings = Settings(
        environment="local",
        model_max_tokens_per_tenant=17,
        model_max_calls_per_tenant=3,
    )
    budget = ledger_for("acme", settings)
    assert budget.tenant == "acme"
    assert budget.max_tokens == 17
    assert budget.max_calls == 3


def test_the_default_configuration_has_both_ceilings_on() -> None:
    """A shipped default of "unlimited" is a control that exists in code and not
    in production — which is the state this finding was raised about.
    """
    defaults = Settings(environment="local")
    assert defaults.model_max_tokens_per_tenant is not None
    assert defaults.model_max_calls_per_tenant is not None


def test_the_wrapper_satisfies_the_provider_protocol() -> None:
    """Structural, because the whole design rests on it.

    If `BudgetedProvider` stopped being a `ModelProvider`, every stage would
    have to be changed to accept it — and the change someone would actually
    make under time pressure is to unwrap it.
    """
    provider: ModelProvider = BudgetedProvider(inner=CountingProvider(), ledger=ledger())
    assert provider is not None
