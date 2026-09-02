"""Circuit breaker (ADR-010): stops calling a provider that is already down.

The point is not to protect the provider — it is to stop the musical loop from
spending its deadline discovering, call after call, that the network is gone. An open
breaker turns a 5-second timeout into an immediate, cheap answer, which is exactly
what the deterministic path needs in order to take over in time (P2).

    CLOSED ──(failure_threshold consecutive failures)──> OPEN
      ▲                                                   │
      │                                          (recovery_s elapsed)
      │                                                   ▼
      └──(success_threshold successes)────────────── HALF_OPEN
                                                          │
                            (any failure) ────────────────┘ back to OPEN

Only `ProviderUnavailableError` counts as a failure. A policy refusal is not an
infrastructure fault: trying another provider would not help, so it must not open the
breaker.

The clock is injected so that the state machine is testable without sleeping.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from garagem.llm.errors import CircuitOpenError


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class BreakerPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    failure_threshold: int = Field(default=3, gt=0)
    # How long to stay open before letting a single probe through. Deliberately short:
    # the cost of a failed probe is one refused call, and the cost of staying open too
    # long is a whole section played deterministically for no reason.
    recovery_s: float = Field(default=10.0, gt=0)
    success_threshold: int = Field(default=1, gt=0)


class BreakerSnapshot(BaseModel):
    """What the event log and the TUI read. Never mutated in place."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: BreakerState
    consecutive_failures: int
    consecutive_successes: int
    opened_at: float | None


class CircuitBreaker:
    def __init__(
        self,
        policy: BreakerPolicy | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy or BreakerPolicy()
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._successes = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> BreakerState:
        """The state as of now, accounting for elapsed recovery time."""
        self._maybe_half_open()
        return self._state

    def check(self) -> None:
        """Raise `CircuitOpenError` if the call must not go out.

        Call this before spending anything on the request — it is the cheapest gate.
        """
        if self.state is BreakerState.OPEN:
            raise CircuitOpenError(
                f"breaker open since {self._opened_at}; "
                f"reopens for a probe after {self._policy.recovery_s}s"
            )

    def record_success(self) -> None:
        self._maybe_half_open()
        self._failures = 0
        if self._state is BreakerState.HALF_OPEN:
            self._successes += 1
            if self._successes >= self._policy.success_threshold:
                self._close()
        else:
            self._successes = 0

    def record_failure(self) -> None:
        self._maybe_half_open()
        self._successes = 0
        # A failed probe sends it straight back to open: the provider is still down,
        # and there is no point counting up to the threshold again.
        if self._state is BreakerState.HALF_OPEN:
            self._open()
            return
        self._failures += 1
        if self._failures >= self._policy.failure_threshold:
            self._open()

    def snapshot(self) -> BreakerSnapshot:
        return BreakerSnapshot(
            state=self.state,
            consecutive_failures=self._failures,
            consecutive_successes=self._successes,
            opened_at=self._opened_at,
        )

    def _maybe_half_open(self) -> None:
        if self._state is not BreakerState.OPEN or self._opened_at is None:
            return
        if self._clock() - self._opened_at >= self._policy.recovery_s:
            self._state = BreakerState.HALF_OPEN
            self._successes = 0

    def _open(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._successes = 0

    def _close(self) -> None:
        self._state = BreakerState.CLOSED
        self._opened_at = None
        self._failures = 0
        self._successes = 0
