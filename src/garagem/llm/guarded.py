"""`GuardedProvider` — the composition that makes the governor and breaker unavoidable.

The project rule is that every model call passes through both. A rule enforced by
convention is a rule that gets skipped in a script at 2 a.m., so it is enforced by
construction instead: wrap the adapter once, and there is no ungoverned path left to
take.

Order matters. The breaker is checked first because it is free: when the provider is
known to be down, refusing costs nothing and the deterministic path gets its time back.
The budget reservation comes second, and is settled against real usage when the stream
ends — or released, costing nothing, when it does not.

What this deliberately does not do is retry (P7). Every error propagates on the first
occurrence; deciding whether there is time to try again is the caller's job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from garagem.llm.breaker import CircuitBreaker
from garagem.llm.errors import ProviderUnavailableError
from garagem.llm.governor import Governor
from garagem.llm.port import LLMProvider, Request, StreamEvent


class GuardedProvider:
    def __init__(
        self,
        inner: LLMProvider,
        *,
        governor: Governor,
        breaker: CircuitBreaker,
    ) -> None:
        self._inner = inner
        self._governor = governor
        self._breaker = breaker

    @property
    def name(self) -> str:
        return f"guarded:{self._inner.name}"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self._breaker.check()
        reservation = self._governor.reserve(request)
        settled = False
        try:
            async for event in self._inner.stream(request):
                if event.type == "done":
                    self._governor.settle(reservation, event.usage)
                    settled = True
                yield event
        except ProviderUnavailableError:
            self._breaker.record_failure()
            raise
        finally:
            if not settled:
                self._governor.release(reservation)
        # Only a stream that ran to completion counts as a success. A consumer that
        # abandons the iterator early leaves the breaker untouched, which is correct:
        # nothing was learned about the provider's health.
        if settled:
            self._breaker.record_success()
