"""`GuardedProvider` — the composition that makes the governor and breaker unavoidable.

The project rule is that every model call passes through both. A rule enforced by
convention is a rule that gets skipped in a script at 2 a.m., so it is enforced by
construction instead: wrap the adapter once, and there is no ungoverned path left to
take.

Order matters. The breaker is checked first because it is free: when the provider is
known to be down, refusing costs nothing and the deterministic path gets its time back.
The budget reservation comes second, and is settled against real usage when the stream
ends. When it does not end, the distinction that matters is whether the provider ever
started: a call refused before it left costs nothing and is released, while a call
cancelled at its deadline generated tokens that were billed, and is settled against a
reconstruction of them. Releasing that one is how Phase 3 recorded thirty billed calls
at $0.0000 (`phase-3-findings.md` §14).

What this deliberately does not do is retry (P7). Every error propagates on the first
occurrence; deciding whether there is time to try again is the caller's job.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from garagem.llm.breaker import CircuitBreaker
from garagem.llm.errors import ProviderUnavailableError
from garagem.llm.governor import Governor, usage_after_cancellation
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
        # Counted on the way past, because a cancelled stream cannot be asked afterwards
        # what it produced. `answered` is the tell that the prompt itself was billed.
        answered = False
        produced = 0
        try:
            async for event in self._inner.stream(request):
                answered = True
                if event.type == "text_delta":
                    produced += len(event.text)
                elif event.type == "tool_input_delta":
                    produced += len(event.fragment)
                elif event.type == "done":
                    self._governor.settle(reservation, event.usage)
                    settled = True
                yield event
        except ProviderUnavailableError:
            self._breaker.record_failure()
            raise
        finally:
            if not settled:
                if answered:
                    self._governor.settle(
                        reservation, usage_after_cancellation(request, produced)
                    )
                else:
                    self._governor.release(reservation)
        # Only a stream that ran to completion counts as a success. A consumer that
        # abandons the iterator early leaves the breaker untouched, which is correct:
        # nothing was learned about the provider's health.
        if settled:
            self._breaker.record_success()
