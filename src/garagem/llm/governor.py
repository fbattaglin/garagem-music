"""Budget governor (ADR-010): the fuse between a bug and the credit card.

Normal use is not the cost risk — §4.4 puts a two-hour jam between $2 and $8. The risk
is the retry storm: an orchestrator bug that resends in a loop burns a week of sessions
in minutes. So this is not an optimisation, it is a fuse, and it exists from Phase 0.

Four independent guards, checked before anything is spent:

- **Session cap** — the hard ceiling for the whole session.
- **Per-minute cap** — a rolling 60 s window. This is what actually catches a storm:
  a loop hits the rate ceiling long before the session ceiling.
- **In-flight count** — a concurrency fuse. Ten calls in flight for one section means
  the scheduler is broken, whatever they cost.
- **Kill switch** — manual, and automatic after a burst of consecutive refusals. Once
  engaged, nothing else goes out until a human resets it.

Money moves in two steps. `reserve()` charges a deliberately pessimistic estimate
before the call, so a burst cannot slip through while its true cost is unknown;
`settle()` then replaces the estimate with the real `Usage` once the stream ends.
A call that fails without usage is `release()`d and costs nothing.

The clock is injected so that window behaviour is testable without sleeping.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from itertools import count

from pydantic import BaseModel, ConfigDict, Field

from garagem.llm.errors import (
    KillSwitchEngagedError,
    RateBudgetExceededError,
    SessionBudgetExceededError,
    TooManyInFlightError,
    UnpricedModelError,
)
from garagem.llm.port import Request, Usage

MILLION = Decimal(1_000_000)
WINDOW_S = 60.0

# Crude, and deliberately so: it only has to be conservative enough to hold the line
# until `settle()` replaces it with the real number. A tokeniser here would mean a
# network call or a new dependency, to refine a figure that lives for a few seconds.
CHARS_PER_TOKEN = 4


class ModelPrice(BaseModel):
    """USD per million tokens, per §4.4. Prices come from configuration, never a alias."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_usd: Decimal
    output_usd: Decimal
    cache_read_usd: Decimal
    # Anthropic charges cache writes at 1.25x base input; leave unset for that default.
    cache_write_usd: Decimal | None = None

    def cost_of(self, usage: Usage) -> Decimal:
        write = (
            self.cache_write_usd
            if self.cache_write_usd is not None
            else self.input_usd * Decimal("1.25")
        )
        return (
            usage.input_tokens * self.input_usd
            + usage.output_tokens * self.output_usd
            + usage.cache_read_tokens * self.cache_read_usd
            + usage.cache_write_tokens * write
        ) / MILLION


class Budget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_usd: Decimal = Field(gt=0)
    per_minute_usd: Decimal = Field(gt=0)
    max_in_flight: int = Field(default=3, gt=0)
    # A storm shows up as refusals in a burst, not as one expensive call. Once this
    # many land back to back, stop asking and pull the switch.
    refusals_before_kill: int = Field(default=5, gt=0)
    prices: dict[str, ModelPrice]


@dataclass(frozen=True, slots=True)
class Reservation:
    id: int
    model: str
    estimate_usd: Decimal
    at: float


class GovernorSnapshot(BaseModel):
    """What the TUI shows and the event log records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spent_usd: Decimal
    reserved_usd: Decimal
    last_minute_usd: Decimal
    in_flight: int
    consecutive_refusals: int
    killed: bool
    kill_reason: str | None


class Governor:
    def __init__(self, budget: Budget, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._budget = budget
        self._clock = clock
        self._spent = Decimal(0)
        self._open: dict[int, Reservation] = {}
        # (timestamp, cost, reservation id) — the id lets settle() find its own entry.
        self._window: deque[tuple[float, Decimal, int]] = deque()
        self._ids = count(1)
        self._refusals = 0
        self._kill_reason: str | None = None

    # ------------------------------------------------------------------ estimating

    def estimate(self, request: Request) -> Decimal:
        """Pessimistic pre-flight cost: counted input plus `max_tokens` of output."""
        price = self._budget.prices.get(request.model)
        if price is None:
            raise UnpricedModelError(
                f"no price configured for {request.model!r}; "
                "an ungoverned call is exactly the one that burns the account"
            )
        chars = len(request.system) + sum(len(m.content) for m in request.messages)
        if request.tool is not None:
            chars += len(request.tool.model_dump_json())
        worst_case = Usage(
            input_tokens=chars // CHARS_PER_TOKEN,
            output_tokens=request.max_tokens,
        )
        return price.cost_of(worst_case)

    # -------------------------------------------------------------------- spending

    def reserve(self, request: Request) -> Reservation:
        """Check every guard and hold the estimated cost. Raises `BudgetError`."""
        if self._kill_reason is not None:
            raise KillSwitchEngagedError(f"kill switch engaged: {self._kill_reason}")

        estimate = self.estimate(request)
        now = self._clock()
        self._prune(now)

        if len(self._open) >= self._budget.max_in_flight:
            self._refuse(
                TooManyInFlightError(
                    f"{len(self._open)} calls already in flight (max {self._budget.max_in_flight})"
                )
            )
        if self._spent + self._reserved() + estimate > self._budget.session_usd:
            self._refuse(
                SessionBudgetExceededError(
                    f"session cap ${self._budget.session_usd} would be exceeded "
                    f"(spent ${self._spent}, reserved ${self._reserved()}, "
                    f"this call ~${estimate})"
                )
            )
        if self._window_total() + estimate > self._budget.per_minute_usd:
            self._refuse(
                RateBudgetExceededError(
                    f"per-minute cap ${self._budget.per_minute_usd} would be exceeded "
                    f"(${self._window_total()} in the last {WINDOW_S:.0f}s)"
                )
            )

        reservation = Reservation(
            id=next(self._ids), model=request.model, estimate_usd=estimate, at=now
        )
        self._open[reservation.id] = reservation
        self._window.append((now, estimate, reservation.id))
        self._refusals = 0
        return reservation

    def settle(self, reservation: Reservation, usage: Usage) -> Decimal:
        """Replace the estimate with the real cost. Returns what the call actually cost."""
        self._open.pop(reservation.id, None)
        price = self._budget.prices[reservation.model]
        actual = price.cost_of(usage)
        self._spent += actual
        self._replace_in_window(reservation, actual)
        return actual

    def release(self, reservation: Reservation) -> None:
        """The call produced no usage (failure, refusal, cancellation). Charge nothing."""
        self._open.pop(reservation.id, None)
        self._replace_in_window(reservation, Decimal(0))

    # ----------------------------------------------------------------- kill switch

    def kill(self, reason: str) -> None:
        self._kill_reason = reason

    def reset(self) -> None:
        """Disengage the kill switch. Deliberately manual — a storm must not self-clear."""
        self._kill_reason = None
        self._refusals = 0

    @property
    def killed(self) -> bool:
        return self._kill_reason is not None

    def snapshot(self) -> GovernorSnapshot:
        self._prune(self._clock())
        return GovernorSnapshot(
            spent_usd=self._spent,
            reserved_usd=self._reserved(),
            last_minute_usd=self._window_total(),
            in_flight=len(self._open),
            consecutive_refusals=self._refusals,
            killed=self.killed,
            kill_reason=self._kill_reason,
        )

    # ---------------------------------------------------------------------- internals

    def _refuse(self, error: Exception) -> None:
        self._refusals += 1
        if self._refusals >= self._budget.refusals_before_kill:
            self.kill(f"{self._refusals} consecutive refusals: {error}")
            raise KillSwitchEngagedError(f"kill switch engaged: {self._kill_reason}")
        raise error

    def _reserved(self) -> Decimal:
        return sum((r.estimate_usd for r in self._open.values()), Decimal(0))

    def _window_total(self) -> Decimal:
        return sum((usd for _, usd, _ in self._window), Decimal(0))

    def _prune(self, now: float) -> None:
        while self._window and now - self._window[0][0] > WINDOW_S:
            self._window.popleft()

    def _replace_in_window(self, reservation: Reservation, actual: Decimal) -> None:
        """Swap a reservation's estimate for its real cost, keeping its position."""
        for i, (at, _, rid) in enumerate(self._window):
            if rid == reservation.id:
                self._window[i] = (at, actual, rid)
                return
