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

The second half of the file is about the *signals*, and is written the same way.
A cap that refuses work silently is a cost incident nobody hears about until a
customer asks why their briefs stopped, so the tests that matter there are the
ones that fail if the alerting is removed: the warning is emitted, it is emitted
once rather than per call, the refusal is counted every time, and none of it
carries a line of the request that triggered it.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

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
    APPROACH_RATIO,
    REFUSED_OUTCOME,
    SPEND_SIGNALS,
    UNATTRIBUTED,
    BudgetedProvider,
    SpendCeilingError,
    TokenLedger,
    ledger_for,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _clean_signals() -> Iterator[None]:
    """The signal counters live for the life of the process.

    That is right in production and wrong in a suite: without this, a test
    asserting "one refusal" passes or fails depending on which tests ran before
    it, which is the flakiness that gets an assertion loosened until it proves
    nothing.
    """
    SPEND_SIGNALS.reset()
    yield
    SPEND_SIGNALS.reset()


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


# --------------------------------------------------------------------------
# Alerting: a ceiling being hit is a signal, not only a control
# --------------------------------------------------------------------------


class RecordingLogger:
    """Stands in for the module's logger and keeps what it was told.

    `structlog.testing.capture_logs` cannot be used here. `configure_logging`
    sets `cache_logger_on_first_use=True` — correct in production, fatal for a
    test — so the first call anywhere freezes the processor chain onto this
    module's logger and a later `capture_logs` never gets inside it. The file
    passed alone and failed after any test that built an app: an order-dependent
    test, which is the kind that gets re-run until green rather than believed.

    Substituting the logger sidesteps the whole question. It asserts what the
    code *called*, which is the thing under test, rather than what a processor
    chain happened to render.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def _record(self, event: str, **fields: Any) -> None:
        self.records.append({"event": event, **fields})

    warning = _record
    error = _record
    info = _record


@pytest.fixture(autouse=True)
def signals(monkeypatch: pytest.MonkeyPatch) -> RecordingLogger:
    recorder = RecordingLogger()
    monkeypatch.setattr("cairn_api.pipeline.spend.logger", recorder)
    return recorder


def logged(records: list[dict[str, Any]], event: str) -> list[dict[str, Any]]:
    return [record for record in records if record.get("event") == event]


async def test_approaching_the_ceiling_warns_while_there_is_still_time(
    signals: RecordingLogger,
) -> None:
    """The warning half of OPERATIONS.md's cost row.

    Eighty per cent, not the moment of refusal: a signal that arrives when work
    is already being refused is a post-mortem. The point is that somebody can
    still raise the ceiling or stop the backfill.
    """
    inner = CountingProvider(input_tokens=85, output_tokens=0)
    provider = BudgetedProvider(inner=inner, ledger=ledger(max_tokens=100), stage="synthesize")

    await provider.complete(request())

    warnings = logged(signals.records, "spend.ceiling_approaching")
    assert len(warnings) == 1
    assert warnings[0]["stage"] == "synthesize"
    assert warnings[0]["usage_ratio"] == 0.85
    assert warnings[0]["max_tokens"] == 100


async def test_the_warning_is_emitted_once_and_not_on_every_call(signals: RecordingLogger) -> None:
    """The property that decides whether anybody reads the signal.

    A workspace sitting at ninety per cent of its ceiling makes a call a second.
    One line per call is not an alert, it is a denial of service against the log,
    and the first occurrence — the one that says when it started — is the line it
    buries.
    """
    inner = CountingProvider(input_tokens=85, output_tokens=0)
    ledger_under_test = ledger(max_tokens=1_000, max_calls=None)
    provider = BudgetedProvider(inner=inner, ledger=ledger_under_test, stage="extract")

    for _ in range(11):  # 935 of 1000 — well past the warning fraction
        await provider.complete(request())

    assert ledger_under_test.usage_ratio is not None
    assert ledger_under_test.usage_ratio >= APPROACH_RATIO
    assert len(logged(signals.records, "spend.ceiling_approaching")) == 1, "one line per call"

    # Counted every time, though: a rate is what an alert rule needs, and the
    # count is what the operations screen shows.
    stage_signal = next(item for item in SPEND_SIGNALS.snapshot() if item.stage == "extract")
    assert stage_signal.warnings > 1


async def test_a_refusal_is_recorded_every_time_it_happens() -> None:
    """The page half of the same row.

    Counted per refusal rather than once: "the ceiling refused something at some
    point" and "the ceiling is refusing everything right now" are different
    incidents, and only a count distinguishes them.
    """
    inner = CountingProvider(input_tokens=1000, output_tokens=0)
    provider = BudgetedProvider(inner=inner, ledger=ledger(max_tokens=10), stage="classify")

    await provider.complete(request())
    for _ in range(4):
        with pytest.raises(SpendCeilingError):
            await provider.complete(request())

    assert SPEND_SIGNALS.refusals == 4
    assert SPEND_SIGNALS.workspaces_refused == 1

    # Above 1.0, and deliberately not clamped: one call of overshoot is the
    # documented imprecision of checking before and recording after, and a
    # ceiling of ten that a single call took to a thousand is exactly the
    # configuration error an operator needs to see. Clamping to 1.0 would show
    # "at the ceiling" and hide that the ceiling is two orders of magnitude
    # below what one call costs.
    stage_signal = next(item for item in SPEND_SIGNALS.snapshot() if item.stage == "classify")
    assert stage_signal.refusals == 4
    assert stage_signal.closest_approach == 100.0


async def test_a_refusal_is_logged_once_however_many_times_a_stage_retries(
    signals: RecordingLogger,
) -> None:
    """`classify` and `extract` swallow every exception and are called again.

    Without this, one exhausted budget writes a line per event for the rest of
    the backfill.
    """
    inner = CountingProvider(input_tokens=1000, output_tokens=0)
    provider = BudgetedProvider(inner=inner, ledger=ledger(max_tokens=10), stage="classify")

    await provider.complete(request())
    for _ in range(6):
        with pytest.raises(SpendCeilingError):
            await provider.complete(request())

    refusals = logged(signals.records, "spend.ceiling_refused")
    assert len(refusals) == 1
    assert refusals[0]["stage"] == "classify"
    assert refusals[0]["detail"] == "1000 tokens used of 10 permitted"


async def test_a_refusal_is_counted_on_the_model_call_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal has to reach telemetry, not only the log.

    `outcome` is on the allow-list and a bespoke counter is not — `telemetry/`
    is closed by design — so the refusal rides the model-call counter with zero
    tokens and zero cost. That keeps the spend dashboards truthful while making
    the refusal rate alertable.
    """
    calls: list[dict[str, Any]] = []
    # Patched by path rather than through `spend.telemetry`: re-exporting an
    # import is not part of a module's interface, and mypy is right to say so.
    monkeypatch.setattr(
        "cairn_api.pipeline.spend.telemetry.record_model_call",
        lambda **kwargs: calls.append(kwargs),
    )

    provider = BudgetedProvider(
        inner=CountingProvider(input_tokens=1000), ledger=ledger(max_tokens=10), stage="extract"
    )
    await provider.complete(request())
    with pytest.raises(SpendCeilingError):
        await provider.complete(request())

    refused = [call for call in calls if call.get("outcome") == REFUSED_OUTCOME]
    assert len(refused) == 1
    # A refused call spent nothing, so it must add nothing to the token counter.
    assert refused[0].get("tokens_in", 0) == 0
    assert refused[0].get("tokens_out", 0) == 0


async def test_nothing_emitted_carries_a_line_of_the_request(signals: RecordingLogger) -> None:
    """The constraint every signal in this codebase is under.

    A spend alert is the most tempting place to attach "what was it doing" —
    and the answer is a prompt, which is a customer's statement, which leaves
    the product the moment a log ships anywhere. Asserted against the whole
    emitted record rather than against named fields, so a helpful new field
    fails here.
    """
    statement = "Priya shipped the payments migration"
    provider = BudgetedProvider(
        inner=CountingProvider(input_tokens=1000), ledger=ledger(max_tokens=900), stage="synthesize"
    )

    await provider.complete(
        ModelRequest(instruction="summarise the week", untrusted_data=statement)
    )
    with pytest.raises(SpendCeilingError):
        await provider.complete(
            ModelRequest(instruction="summarise the week", untrusted_data=statement)
        )

    assert logged(signals.records, "spend.ceiling_refused"), "the test asserted against nothing"
    for record in signals.records:
        rendered = str(record)
        assert statement not in rendered
        assert "summarise the week" not in rendered


async def test_the_signals_say_which_stage_and_how_close() -> None:
    """What an operator reads on `/operations/spend`.

    "Spend is high" is not actionable. "Synthesis reached 90% of its ceiling and
    extraction is at 30%" names the stage to look at, and OPERATIONS.md's first
    action for a cost spike depends on exactly that distinction.
    """
    base = BudgetedProvider(
        inner=CountingProvider(input_tokens=30, output_tokens=0), ledger=ledger(max_tokens=100)
    )

    await base.for_stage("classify").complete(request())
    await base.for_stage("synthesize").complete(request())
    await base.for_stage("synthesize").complete(request())

    by_stage = {signal.stage: signal for signal in SPEND_SIGNALS.snapshot()}
    assert by_stage["classify"].closest_approach == pytest.approx(0.3)
    assert by_stage["synthesize"].closest_approach == pytest.approx(0.9)
    assert by_stage["synthesize"].tokens == 60


async def test_a_stage_that_never_approaches_reports_no_warning(signals: RecordingLogger) -> None:
    """The signal has to be able to stay quiet.

    An alert that fires on ordinary operation is one an operator mutes, and a
    muted alert is worse than none because everybody believes it is on.
    """
    provider = BudgetedProvider(
        inner=CountingProvider(input_tokens=1, output_tokens=0),
        ledger=ledger(max_tokens=1_000),
        stage="retrieve",
    )

    for _ in range(20):
        await provider.complete(request())

    assert logged(signals.records, "spend.ceiling_approaching") == []
    assert SPEND_SIGNALS.warnings == 0
    assert SPEND_SIGNALS.refusals == 0


def test_an_unbounded_ledger_reports_no_ratio_rather_than_zero() -> None:
    """ "Unlimited" and "bounded and untouched" must not read the same.

    Both would render as an empty bar. One of them is a deployment with the cost
    control switched off, which is the finding the ceilings were added for.
    """
    assert ledger(max_tokens=None, max_calls=None).usage_ratio is None
    assert ledger(max_tokens=100, max_calls=None).usage_ratio == 0.0


def test_a_ceiling_of_zero_reports_as_fully_consumed() -> None:
    """A ceiling nothing can be spent under is not an absent ceiling.

    Dividing by it raises; reporting `None` would render a deployment refusing
    all work as one with no limits at all.
    """
    assert ledger(max_tokens=0, max_calls=None).usage_ratio == 1.0


def test_the_wrapper_satisfies_the_provider_protocol() -> None:
    """Structural, because the whole design rests on it.

    If `BudgetedProvider` stopped being a `ModelProvider`, every stage would
    have to be changed to accept it — and the change someone would actually
    make under time pressure is to unwrap it.
    """
    provider: ModelProvider = BudgetedProvider(inner=CountingProvider(), ledger=ledger())
    assert provider is not None
