"""Provider failures, classified by what the caller should do about them."""

from __future__ import annotations


class ProviderError(Exception):
    """Base for everything that can go wrong behind the port."""


class ProviderUnavailableError(ProviderError):
    """Network, 5xx, 429, connection timeout.

    The only family the circuit breaker counts as a provider failure. Never turned
    into a retry in here (P7) — replanning is the caller's decision.
    """


class ProviderRefusedError(ProviderError):
    """The model declined on policy grounds. Not an infrastructure failure.

    Does not open the breaker: trying another provider would not help, and the
    correct defence is the deterministic path.
    """


class CassetteError(ProviderError):
    """Something is wrong with a recorded cassette."""


class CassetteMissingError(CassetteError):
    """The cassette file does not exist. Record it before running the test."""


class CassetteMismatchError(CassetteError):
    """The request does not match the one that was recorded.

    The cassette aged together with the prompt: re-record it instead of relaxing
    the check.
    """


class BudgetError(Exception):
    """The governor refused a call. Not a provider failure — do not open the breaker."""


class SessionBudgetExceededError(BudgetError):
    """The session cap would be exceeded by this call."""


class RateBudgetExceededError(BudgetError):
    """The per-minute cap would be exceeded by this call."""


class TooManyInFlightError(BudgetError):
    """Too many calls already in flight. A concurrency fuse, not a queue."""


class UnpricedModelError(BudgetError):
    """No price is configured for this model, so its spend cannot be bounded.

    Fail closed: an ungoverned call is exactly the one that burns the account.
    """


class KillSwitchEngagedError(BudgetError):
    """The kill switch is engaged. Nothing else goes out until it is reset by hand."""


class CircuitOpenError(Exception):
    """The breaker is open. Go to the deterministic path — do not wait, do not retry."""


class DeadlineExceededError(ProviderError):
    """The call outran its deadline (§4.2) and was cancelled.

    Deliberately *not* a `ProviderUnavailableError`: our deadlines are aggressive by
    design (40% of the remaining musical time), so a normal p95 can overrun one on a
    perfectly healthy link. Counting that as provider failure would open the breaker
    against a provider that is fine. Fall back to the deterministic engine, log it, and
    do not retry this section.
    """
