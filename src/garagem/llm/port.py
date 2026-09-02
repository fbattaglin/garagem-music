"""The `LLMProvider` port — the only boundary between the system and a model provider.

ADR-012: the provider sits behind a port, with adapters behind it. Nothing above this
layer knows whether the text came from Anthropic, from Google, from a cassette or from
a deterministic fake.

Three invariants live here, which is why some things are deliberately absent:

- **P7 — no retries.** There is no retry, backoff or attempt parameter. Repeating a
  call is a planning decision taken above; down here a failure is a failure.
- **A deadline, not a library timeout.** `Request.deadline_s` is the budget in seconds
  (§4.2: 40% of the remaining musical time). The adapter cancels when it runs out; it
  does not extend it and does not try again.
- **Streaming is the normal mode.** The port only exposes `stream()`. The incremental
  parser (ADR-011) needs the DSL arriving line by line, and TTFT is only observable
  this way. Callers wanting the whole response aggregate the events themselves.

The event vocabulary is the lowest common denominator between the Messages API and
Gemini: text in deltas, tool use with the JSON input arriving in fragments, and a
final event carrying the stop reason and the token accounting.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

FROZEN = ConfigDict(frozen=True, extra="forbid")


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Effort(StrEnum):
    """How much thinking the provider should spend. Neutral across providers.

    This is the one knob that trades quality against TTFT, and §4.2 shows the trade is
    steep: a strong model with deep reasoning has a 2-10 s TTFT with high variance,
    against 0.6-1.5 s shallow. So the structural layer runs high and the tactical layer
    runs low. Note that thinking is never switched off — lowering effort is the cheaper
    and better-behaved way to buy latency back.

    Not every model has the knob. `Request.effort = None` means "send no preference,
    take the provider's default" — which is the only thing that can be said about a
    model from before the parameter existed, such as Haiku 4.5.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class Message(BaseModel):
    model_config = FROZEN

    role: Role
    content: str


class ToolSchema(BaseModel):
    """A single strict tool (ADR-009) — this is how a section arrives structured."""

    model_config = FROZEN

    name: str
    description: str
    # JSON Schema. A `dict` rather than a `Mapping` so it serialises without
    # gymnastics; the model is frozen, so nobody swaps the object — but do not hash it.
    input_schema: dict[str, object]


class Request(BaseModel):
    model_config = FROZEN

    model: str
    messages: tuple[Message, ...]
    system: str = ""
    tool: ToolSchema | None = None
    max_tokens: int = 4096
    # Required, no default: §4.2 mandates 40% of the musical time remaining before the
    # point of use. A generous default here would become the deadline nobody chose.
    deadline_s: float = Field(gt=0)
    # None: this model has no effort knob, so do not send one. See `Effort`.
    effort: Effort | None = Effort.HIGH
    # The stable block (DSL rules + personas + session context) is marked for caching.
    # Keep it in `system` and leave volatile content in the messages, or the prefix is
    # invalidated and the cache hit rate drops to zero.
    cache_system: bool = True

    def fingerprint(self) -> str:
        """Request identity, used to match against a recorded cassette."""
        return hashlib.sha256(self.model_dump_json().encode("utf-8")).hexdigest()[:16]


class StopReason(StrEnum):
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    TOOL_USE = "tool_use"
    STOP_SEQUENCE = "stop_sequence"
    REFUSAL = "refusal"
    PAUSE_TURN = "pause_turn"


class Usage(BaseModel):
    """Token accounting. The governor (ADR-010) turns this into money."""

    model_config = FROZEN

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # A stream cancelled at its deadline never sends the `done` event that carries this,
    # so its usage is reconstructed from the request and from the deltas that arrived
    # (`phase-3-findings.md` §14). Those tokens were generated and billed; recording them
    # as zero is what made every deadline round under-report its own cost. Charged like
    # any other usage, and flagged so a report can separate measured spend from inferred.
    estimated: bool = False

    @property
    def billed_input_tokens(self) -> int:
        """Input tokens that did not come from cache — what the governor charges."""
        return self.input_tokens + self.cache_write_tokens


class TextDelta(BaseModel):
    model_config = FROZEN

    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolUseStart(BaseModel):
    model_config = FROZEN

    type: Literal["tool_use_start"] = "tool_use_start"
    id: str
    name: str


class ToolInputDelta(BaseModel):
    """A fragment of the tool's JSON input. On its own it is not valid JSON.

    This is what lets the incremental parser write drums and bass into the ScoreBuffer
    while guitar and keys are still being generated.
    """

    model_config = FROZEN

    type: Literal["tool_input_delta"] = "tool_input_delta"
    fragment: str


class StreamDone(BaseModel):
    model_config = FROZEN

    type: Literal["done"] = "done"
    stop: StopReason
    usage: Usage = Usage()


StreamEvent = Annotated[
    TextDelta | ToolUseStart | ToolInputDelta | StreamDone,
    Field(discriminator="type"),
]

EVENT_ADAPTER: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)


@runtime_checkable
class LLMProvider(Protocol):
    """Every provider: a name for the event log and a stream of events.

    `stream` is an async generator function — do not await it, iterate over it.
    It must raise `ProviderUnavailableError` for infrastructure failures, and
    `ProviderRefusedError` only when a request is rejected outright, before any stream.
    A model that declines mid-generation is a normal completion: it arrives as
    `StreamDone` with `StopReason.REFUSAL`, and the caller decides what to play.
    Any other exception is a bug.
    """

    @property
    def name(self) -> str: ...

    def stream(self, request: Request) -> AsyncIterator[StreamEvent]: ...
