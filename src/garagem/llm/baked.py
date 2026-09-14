"""`BakedProvider`: answers from takes baked before the performance. Never touches the network.

Setlist Mode (ADR-000 §7, ADR-024) is connected pre-production and disconnected
performance: the model writes a song's sections online, ahead of time, and the performance
plays them from disk. This is the second half behind the same port as every other provider,
so the producer, the parser, the realise, the repairer and the stale-score checks run
unchanged, and nothing above this layer knows the model is not on the line.

**Keyed by the briefing, not by the request's fingerprint.** A cassette matches the whole
request, so a changed prompt makes it refuse, which is its job: it is a drift alarm. A baked
take is material, and the text the model saw is the only key that must match. `answers` maps
that text, the request's last user message, to the DSL the model wrote for it. The caller
builds it with today's `dsl.brief`, so a reworded prompt does not strand a curated setlist.

**It bills nothing.** The take was paid for when it was baked. Every answer ends with an empty
`Usage`, so the governor settles each call at $0.

**A briefing with no take is refused**, and it is never a network failure: the breaker must
not open because a knob moved the song somewhere the bake did not go. The producer's route
(`agents/routing.py`) keeps it from being asked at all. This refusal is the backstop.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping

from garagem.llm.errors import ProviderRefusedError
from garagem.llm.port import (
    Request,
    Role,
    StopReason,
    StreamDone,
    StreamEvent,
    ToolInputDelta,
    ToolUseStart,
    Usage,
)


class BakedProvider:
    """Streams the take baked for a request's briefing, in one fragment, for free."""

    def __init__(self, answers: Mapping[str, str], *, name: str = "setlist") -> None:
        self._answers = dict(answers)
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return f"baked:{self._name}"

    def holds(self, briefing: str) -> bool:
        return briefing in self._answers

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        asked = [message.content for message in request.messages if message.role is Role.USER]
        dsl = self._answers.get(asked[-1]) if asked else None
        if dsl is None or request.tool is None:
            raise ProviderRefusedError(f"{self.name} holds no take for this briefing")
        yield ToolUseStart(id=f"{self._name}-take", name=request.tool.name)
        yield ToolInputDelta(fragment=json.dumps({"dsl": dsl}))
        yield StreamDone(stop=StopReason.TOOL_USE, usage=Usage())
