"""GuardedProvider: the governor and the breaker actually sitting in the call path."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest

from conftest import Collector
from garagem.llm import (
    BreakerPolicy,
    BreakerState,
    Budget,
    CircuitBreaker,
    CircuitOpenError,
    FakeProvider,
    FakeResponse,
    Governor,
    GuardedProvider,
    KillSwitchEngagedError,
    LLMProvider,
    Message,
    ModelPrice,
    ProviderRefusedError,
    ProviderUnavailableError,
    Request,
    Role,
    StopReason,
    StreamDone,
    StreamEvent,
    TextDelta,
    Usage,
)

OPUS = ModelPrice(input_usd=Decimal(5), output_usd=Decimal(25), cache_read_usd=Decimal("0.5"))


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def state_of(breaker: CircuitBreaker) -> BreakerState:
    """Read the state through a call, so mypy does not narrow a clock-dependent property."""
    return breaker.state


def a_request(**extra: object) -> Request:
    base: dict[str, object] = {
        "model": "claude-opus-5",
        "messages": (Message(role=Role.USER, content="a verse in Em"),),
        "max_tokens": 800,
        "deadline_s": 5.8,
    }
    return Request.model_validate(base | extra)


def guarded(
    inner: LLMProvider, **budget: object
) -> tuple[GuardedProvider, Governor, CircuitBreaker, FakeClock]:
    clock = FakeClock()
    defaults: dict[str, object] = {
        "session_usd": Decimal(10),
        "per_minute_usd": Decimal(10),
        "max_in_flight": 3,
        "prices": {"claude-opus-5": OPUS},
    }
    governor = Governor(Budget.model_validate(defaults | budget), clock=clock)
    breaker = CircuitBreaker(BreakerPolicy(failure_threshold=2, recovery_s=10.0), clock=clock)
    return GuardedProvider(inner, governor=governor, breaker=breaker), governor, breaker, clock


USAGE = Usage(input_tokens=2000, output_tokens=800, cache_read_tokens=2000)


def test_a_successful_call_is_settled_at_its_real_cost(collect: Collector) -> None:
    inner = FakeProvider([FakeResponse(text="SEC verse", usage=USAGE)])
    provider, governor, _, _ = guarded(inner)

    events = collect(provider, a_request())

    assert events[-1].type == "done"
    snapshot = governor.snapshot()
    assert snapshot.spent_usd == OPUS.cost_of(USAGE)
    assert snapshot.in_flight == 0
    assert snapshot.reserved_usd == Decimal(0)


def test_the_events_pass_through_untouched(collect: Collector) -> None:
    inner = FakeProvider([FakeResponse(text="SEC verse 8 132 Em", usage=USAGE)], seed=4)
    provider, _, _, _ = guarded(inner)
    bare = FakeProvider([FakeResponse(text="SEC verse 8 132 Em", usage=USAGE)], seed=4)

    assert collect(provider, a_request()) == collect(bare, a_request())


def test_a_provider_failure_charges_nothing_and_counts_against_the_breaker(
    collect: Collector,
) -> None:
    inner = FakeProvider(
        [FakeResponse(text="SEC verse")],
        fail_with=ProviderUnavailableError("connection dropped"),
        fail_after=1,
    )
    provider, governor, breaker, _ = guarded(inner)

    with pytest.raises(ProviderUnavailableError):
        collect(provider, a_request())

    assert governor.snapshot().spent_usd == Decimal(0)
    assert governor.snapshot().in_flight == 0
    assert breaker.snapshot().consecutive_failures == 1


def test_a_policy_refusal_does_not_open_the_breaker(collect: Collector) -> None:
    """Trying another provider would not help; the defence is the deterministic path."""
    inner = FakeProvider(
        [FakeResponse(text="x")], fail_with=ProviderRefusedError("declined"), fail_after=0
    )
    provider, governor, breaker, _ = guarded(inner)

    with pytest.raises(ProviderRefusedError):
        collect(provider, a_request())

    assert breaker.snapshot().consecutive_failures == 0
    assert governor.snapshot().spent_usd == Decimal(0)


def test_an_open_breaker_refuses_before_spending_anything(collect: Collector) -> None:
    inner = FakeProvider(
        [FakeResponse(text="x"), FakeResponse(text="x"), FakeResponse(text="x")],
        fail_with=ProviderUnavailableError("down"),
        fail_after=0,
    )
    provider, governor, breaker, _ = guarded(inner)

    for _ in range(2):
        with pytest.raises(ProviderUnavailableError):
            collect(provider, a_request())
    assert state_of(breaker) is BreakerState.OPEN

    with pytest.raises(CircuitOpenError):
        collect(provider, a_request())

    # The third attempt never reached the provider, and never reserved budget.
    assert len(inner.calls) == 2
    assert governor.snapshot().reserved_usd == Decimal(0)


class FlakyProvider:
    """Fails the first `failures` calls, then serves normally."""

    name = "flaky"

    def __init__(self, failures: int) -> None:
        self._left = failures
        self.calls = 0

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        if self._left > 0:
            self._left -= 1
            raise ProviderUnavailableError("down")
        yield TextDelta(text="SEC verse")
        yield StreamDone(stop=StopReason.END_TURN, usage=USAGE)


def test_recovery_lets_a_probe_through_and_closes_the_breaker(collect: Collector) -> None:
    inner = FlakyProvider(failures=2)
    provider, _, breaker, clock = guarded(inner)

    for _ in range(2):
        with pytest.raises(ProviderUnavailableError):
            collect(provider, a_request())
    assert state_of(breaker) is BreakerState.OPEN

    with pytest.raises(CircuitOpenError):
        collect(provider, a_request())
    assert inner.calls == 2, "the open breaker must not reach the provider"

    clock.advance(10.0)
    assert state_of(breaker) is BreakerState.HALF_OPEN

    collect(provider, a_request())  # the probe succeeds
    assert state_of(breaker) is BreakerState.CLOSED
    assert inner.calls == 3


def test_the_kill_switch_stops_the_guarded_provider(collect: Collector) -> None:
    inner = FakeProvider([FakeResponse(text="x", usage=USAGE)])
    provider, governor, _, _ = guarded(inner)
    governor.kill("test")

    with pytest.raises(KillSwitchEngagedError):
        collect(provider, a_request())
    assert inner.calls == []


def test_the_guarded_provider_is_still_a_provider() -> None:
    inner = FakeProvider([FakeResponse()])
    provider, _, _, _ = guarded(inner)
    assert isinstance(provider, LLMProvider)
    assert provider.name == "guarded:fake"
