"""The breaker state machine, driven by an injected clock instead of sleeping."""

from __future__ import annotations

import pytest

from garagem.llm import (
    BreakerPolicy,
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
)


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


def a_breaker(**policy: object) -> tuple[CircuitBreaker, FakeClock]:
    clock = FakeClock()
    defaults: dict[str, object] = {"failure_threshold": 3, "recovery_s": 10.0}
    return CircuitBreaker(BreakerPolicy.model_validate(defaults | policy), clock=clock), clock


def test_starts_closed_and_lets_calls_through() -> None:
    breaker, _ = a_breaker()
    assert state_of(breaker) is BreakerState.CLOSED
    breaker.check()


def test_opens_only_at_the_threshold() -> None:
    breaker, _ = a_breaker(failure_threshold=3)
    for _ in range(2):
        breaker.record_failure()
    assert state_of(breaker) is BreakerState.CLOSED
    breaker.record_failure()
    assert state_of(breaker) is BreakerState.OPEN


def test_an_open_breaker_refuses_immediately() -> None:
    """The whole point: no waiting. The deterministic path needs its time back."""
    breaker, _ = a_breaker(failure_threshold=1)
    breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        breaker.check()


def test_a_success_resets_the_failure_count() -> None:
    breaker, _ = a_breaker(failure_threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert state_of(breaker) is BreakerState.CLOSED


def test_the_full_cycle_closed_open_half_open_closed() -> None:
    breaker, clock = a_breaker(failure_threshold=1, recovery_s=10.0, success_threshold=1)

    breaker.record_failure()
    assert state_of(breaker) is BreakerState.OPEN

    clock.advance(9.9)
    assert state_of(breaker) is BreakerState.OPEN

    clock.advance(0.1)
    assert state_of(breaker) is BreakerState.HALF_OPEN
    breaker.check()  # the probe is allowed through

    breaker.record_success()
    assert state_of(breaker) is BreakerState.CLOSED


def test_a_failed_probe_goes_straight_back_to_open() -> None:
    """No counting up to the threshold again — the provider is demonstrably still down."""
    breaker, clock = a_breaker(failure_threshold=3, recovery_s=10.0)
    for _ in range(3):
        breaker.record_failure()
    clock.advance(10.0)
    assert state_of(breaker) is BreakerState.HALF_OPEN

    breaker.record_failure()
    assert state_of(breaker) is BreakerState.OPEN


def test_half_open_can_require_more_than_one_success() -> None:
    breaker, clock = a_breaker(failure_threshold=1, recovery_s=1.0, success_threshold=2)
    breaker.record_failure()
    clock.advance(1.0)

    breaker.record_success()
    assert state_of(breaker) is BreakerState.HALF_OPEN
    breaker.record_success()
    assert state_of(breaker) is BreakerState.CLOSED


def test_the_snapshot_reports_the_state_for_the_event_log() -> None:
    breaker, clock = a_breaker(failure_threshold=1)
    breaker.record_failure()
    snapshot = breaker.snapshot()
    assert snapshot.state is BreakerState.OPEN
    assert snapshot.consecutive_failures == 1
    assert snapshot.opened_at == clock.now
