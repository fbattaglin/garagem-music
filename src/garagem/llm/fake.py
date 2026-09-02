"""`FakeProvider` — a deterministic, network-free provider for the default suite.

It serves three distinct purposes, which is why it has the parameters it has:

1. **Standing in for the cloud in tests.** Same seed, same events, byte for byte —
   including how the deltas are cut, which is where incremental parsers break.
2. **Simulating latency** without spending it: `ttft_s` and `gap_s` shift the events in
   time to exercise deadlines and lookahead. Zero by default, to keep the suite fast.
3. **Injecting failure** (`fail_with` / `fail_after`) to exercise the governor and the
   breaker, both of which need a provider that breaks on demand.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence
from random import Random

from pydantic import BaseModel, ConfigDict

from garagem.llm.errors import ProviderError
from garagem.llm.port import (
    Request,
    StopReason,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolInputDelta,
    ToolUseStart,
    Usage,
)

MIN_CHUNK = 3
MAX_CHUNK = 12


class FakeResponse(BaseModel):
    """What the fake will emit on one call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = ""
    tool_name: str | None = None
    # The tool input, already serialised as JSON; the fake cuts it into fragments.
    tool_input: str = ""
    stop: StopReason = StopReason.END_TURN
    usage: Usage = Usage()


def _chunks(text: str, rng: Random) -> Iterator[str]:
    """Deterministic cutting, imitating the irregular size of real deltas."""
    i = 0
    while i < len(text):
        n = rng.randint(MIN_CHUNK, MAX_CHUNK)
        yield text[i : i + n]
        i += n


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        responses: Sequence[FakeResponse],
        *,
        seed: int = 0,
        ttft_s: float = 0.0,
        gap_s: float = 0.0,
        fail_with: Exception | None = None,
        fail_after: int = 0,
    ) -> None:
        if not responses:
            raise ValueError("FakeProvider needs at least one response")
        self._responses = tuple(responses)
        self._seed = seed
        self._ttft_s = ttft_s
        self._gap_s = gap_s
        self._fail_with = fail_with
        self._fail_after = fail_after
        # Requests seen, in order — so tests can assert on the prompt.
        self.calls: list[Request] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        index = len(self.calls)
        self.calls.append(request)
        if index >= len(self._responses):
            raise ProviderError(
                f"FakeProvider exhausted: {len(self._responses)} response(s), call #{index + 1}"
            )
        response = self._responses[index]
        # The seed varies per call: two identical calls must not produce the same
        # cutting by accident, while the session as a whole stays reproducible.
        rng = Random(self._seed + index)

        if self._ttft_s:
            await asyncio.sleep(self._ttft_s)

        for emitted, event in enumerate(self._events(response, rng)):
            if self._fail_with is not None and emitted >= self._fail_after:
                raise self._fail_with
            if emitted and self._gap_s:
                await asyncio.sleep(self._gap_s)
            yield event

    def _events(self, response: FakeResponse, rng: Random) -> Iterator[StreamEvent]:
        for chunk in _chunks(response.text, rng):
            yield TextDelta(text=chunk)
        if response.tool_name is not None:
            yield ToolUseStart(id=f"toolu_fake_{rng.randrange(16**8):08x}", name=response.tool_name)
            for chunk in _chunks(response.tool_input, rng):
                yield ToolInputDelta(fragment=chunk)
        yield StreamDone(stop=response.stop, usage=response.usage)
