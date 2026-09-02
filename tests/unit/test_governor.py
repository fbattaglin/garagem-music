"""The budget governor: guards, two-step accounting, and the retry-storm cut-off."""

from __future__ import annotations

from decimal import Decimal

import pytest

from garagem.llm import (
    Budget,
    Governor,
    KillSwitchEngagedError,
    Message,
    ModelPrice,
    RateBudgetExceededError,
    Request,
    Role,
    SessionBudgetExceededError,
    TooManyInFlightError,
    UnpricedModelError,
    Usage,
)
from garagem.llm.governor import input_tokens_of, usage_after_cancellation

# Claude Opus 5, per ADR §4.4: $5 / $25 per million, $0.50 cache read.
OPUS = ModelPrice(
    input_usd=Decimal(5),
    output_usd=Decimal(25),
    cache_read_usd=Decimal("0.5"),
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def a_budget(**extra: object) -> Budget:
    defaults: dict[str, object] = {
        "session_usd": Decimal(1),
        "per_minute_usd": Decimal("0.50"),
        "max_in_flight": 3,
        "prices": {"claude-opus-5": OPUS},
    }
    return Budget.model_validate(defaults | extra)


def a_governor(**extra: object) -> tuple[Governor, FakeClock]:
    clock = FakeClock()
    return Governor(a_budget(**extra), clock=clock), clock


def a_request(**extra: object) -> Request:
    base: dict[str, object] = {
        "model": "claude-opus-5",
        "messages": (Message(role=Role.USER, content="a verse in Em"),),
        "max_tokens": 800,
        "deadline_s": 5.8,
    }
    return Request.model_validate(base | extra)


# ---------------------------------------------------------------------- pricing


def test_cost_follows_the_price_table() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert OPUS.cost_of(usage) == Decimal(30)


def test_cache_reads_cost_a_tenth_of_input() -> None:
    cached = OPUS.cost_of(Usage(cache_read_tokens=1_000_000))
    fresh = OPUS.cost_of(Usage(input_tokens=1_000_000))
    assert cached == fresh / 10


def test_cache_writes_default_to_1_25x_input() -> None:
    assert OPUS.cost_of(Usage(cache_write_tokens=1_000_000)) == Decimal("6.25")


def test_an_unpriced_model_is_refused() -> None:
    """Fail closed: an ungoverned call is exactly the one that burns the account."""
    governor, _ = a_governor()
    with pytest.raises(UnpricedModelError, match="gemini"):
        governor.reserve(a_request(model="gemini-3-1-pro"))


def test_the_estimate_is_pessimistic() -> None:
    """It must assume the full max_tokens, or a burst slips through while cost is unknown."""
    governor, _ = a_governor()
    request = a_request(max_tokens=800)
    estimate = governor.estimate(request)
    actual = OPUS.cost_of(Usage(input_tokens=200, output_tokens=120))
    assert estimate > actual


# ----------------------------------------------------------------------- guards


def test_the_session_cap_holds() -> None:
    governor, _ = a_governor(session_usd=Decimal("0.01"), per_minute_usd=Decimal(100))
    with pytest.raises(SessionBudgetExceededError, match="session cap"):
        governor.reserve(a_request(max_tokens=100_000))


def test_the_per_minute_cap_holds_and_then_frees_up() -> None:
    governor, clock = a_governor(per_minute_usd=Decimal("0.03"), session_usd=Decimal(100))
    first = governor.reserve(a_request())
    governor.settle(first, Usage(input_tokens=200, output_tokens=800))

    with pytest.raises(RateBudgetExceededError, match="per-minute cap"):
        governor.reserve(a_request())

    clock.advance(61.0)
    governor.reserve(a_request())  # the window has rolled past


def test_too_many_in_flight_is_refused() -> None:
    """A concurrency fuse: ten calls for one section is a broken scheduler."""
    governor, _ = a_governor(max_in_flight=2, per_minute_usd=Decimal(100))
    governor.reserve(a_request())
    governor.reserve(a_request())
    with pytest.raises(TooManyInFlightError, match="in flight"):
        governor.reserve(a_request())


def test_settling_frees_the_in_flight_slot() -> None:
    governor, _ = a_governor(max_in_flight=1, per_minute_usd=Decimal(100))
    reservation = governor.reserve(a_request())
    governor.settle(reservation, Usage(input_tokens=200, output_tokens=100))
    governor.reserve(a_request())


# ------------------------------------------------------------ two-step accounting


def test_settling_charges_the_real_cost_not_the_estimate() -> None:
    governor, _ = a_governor(per_minute_usd=Decimal(100))
    reservation = governor.reserve(a_request())
    usage = Usage(input_tokens=2000, output_tokens=800, cache_read_tokens=2000)

    actual = governor.settle(reservation, usage)

    assert actual == OPUS.cost_of(usage)
    snapshot = governor.snapshot()
    assert snapshot.spent_usd == actual
    assert snapshot.reserved_usd == Decimal(0)
    assert snapshot.last_minute_usd == actual


def test_a_released_call_costs_nothing() -> None:
    """A failure with no usage must not leave a phantom charge in the window."""
    governor, _ = a_governor(per_minute_usd=Decimal(100))
    reservation = governor.reserve(a_request())
    governor.release(reservation)

    snapshot = governor.snapshot()
    assert snapshot.spent_usd == Decimal(0)
    assert snapshot.reserved_usd == Decimal(0)
    assert snapshot.last_minute_usd == Decimal(0)
    assert snapshot.in_flight == 0


def test_a_cancelled_call_is_charged_for_the_prompt_and_for_what_arrived() -> None:
    """Phase 3's accounting hole, as a test.

    `Usage` rides on the `done` event, so thirty deadline-cancelled calls were recorded
    at $0.0000 (`phase-3-findings.md` §14). The provider read the whole prompt and emitted
    what it emitted; both are knowable without that event.
    """
    request = a_request()
    usage = usage_after_cancellation(request, output_chars=400)

    assert usage.estimated
    assert usage.input_tokens == input_tokens_of(request)
    assert usage.output_tokens == 100  # 400 chars, four to a token


def test_an_inferred_charge_is_kept_apart_from_a_measured_one() -> None:
    """Both are spent. Only one was counted by the provider, and a report must say which."""
    governor, _ = a_governor(per_minute_usd=Decimal(100))

    measured = governor.settle(
        governor.reserve(a_request()), Usage(input_tokens=2000, output_tokens=800)
    )
    inferred = governor.settle(
        governor.reserve(a_request()), usage_after_cancellation(a_request(), 400)
    )

    snapshot = governor.snapshot()
    assert snapshot.spent_usd == measured + inferred
    assert snapshot.estimated_usd == inferred


def test_a_cancelled_call_never_settles_at_zero() -> None:
    """The one thing the old behaviour did that this exists to stop."""
    governor, _ = a_governor(per_minute_usd=Decimal(100))

    charged = governor.settle(
        governor.reserve(a_request()), usage_after_cancellation(a_request(), output_chars=0)
    )

    assert charged > Decimal(0)


# ------------------------------------------------------------------- kill switch


def test_the_kill_switch_stops_everything_and_does_not_self_clear() -> None:
    governor, _ = a_governor(per_minute_usd=Decimal(100))
    governor.kill("manual stop")

    with pytest.raises(KillSwitchEngagedError, match="manual stop"):
        governor.reserve(a_request())

    governor.reset()
    governor.reserve(a_request())


def test_a_retry_storm_is_cut_off_in_under_two_seconds() -> None:
    """Phase 0 exit criterion.

    Simulated time, driven by the injected clock: a caller looping as fast as it can,
    at 10 ms per attempt. What is being measured is the policy — how much elapsed time
    passes before the switch engages — not the wall clock of this test.
    """
    governor, clock = a_governor(
        # Room for a couple of legitimate calls, so the storm is cut off in traffic
        # rather than from a standing start.
        per_minute_usd=Decimal("0.05"),
        session_usd=Decimal(100),
        refusals_before_kill=5,
    )

    attempts = 0
    while not governor.killed and clock.now < 10.0:
        attempts += 1
        try:
            reservation = governor.reserve(a_request())
        except Exception:
            pass
        else:
            governor.settle(reservation, Usage(input_tokens=2000, output_tokens=800))
        clock.advance(0.01)

    snapshot = governor.snapshot()
    assert governor.killed, f"the storm ran unchecked for {clock.now}s"
    assert clock.now < 2.0, f"took {clock.now}s to cut it off"
    assert snapshot.spent_usd > Decimal(0), "the test should exercise real traffic first"
    assert snapshot.spent_usd < Decimal("0.10"), "too much got through"
    assert attempts < 20


def test_one_success_resets_the_refusal_streak() -> None:
    """Occasional refusals during normal use are not a storm and must not trip the switch."""
    governor, clock = a_governor(
        per_minute_usd=Decimal("0.04"), session_usd=Decimal(100), refusals_before_kill=3
    )

    for _ in range(6):
        with pytest.raises(RateBudgetExceededError):
            governor.reserve(a_request(max_tokens=100_000))
        clock.advance(61.0)
        governor.release(governor.reserve(a_request(max_tokens=10)))

    assert not governor.killed
