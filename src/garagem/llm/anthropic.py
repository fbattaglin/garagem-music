"""Anthropic Messages API adapter (ADR-012), over raw HTTP with a warm HTTP/2 pool.

Raw `httpx` rather than the official SDK, for three project-specific reasons:

1. **The pool is a latency decision.** §4.2 budgets zero for the TLS handshake, which
   only holds with a persistent, pre-warmed HTTP/2 connection under our control.
2. **P7 forbids retries.** The SDK retries twice by default; a client configured to
   never retry is a footgun one keyword argument away from being re-armed.
3. **The port already owns the vocabulary.** Everything above translates to our own
   event types anyway, so the SDK's models would be built only to be discarded.

The cost of that choice is that the wire format is now ours to track. It is pinned by
cassettes and by the SSE fixtures in the tests; when Anthropic changes an event shape,
those fail loudly rather than silently dropping half a section.

Nothing here retries, and nothing here decides. It translates, enforces the deadline,
and classifies failures so the breaker upstream can tell "the network is down" from
"this request was malformed".
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict

from garagem.llm.errors import (
    DeadlineExceededError,
    ProviderError,
    ProviderUnavailableError,
)
from garagem.llm.port import (
    Request,
    StopReason,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolInputDelta,
    ToolSchema,
    ToolUseStart,
    Usage,
)

API_VERSION: Final = "2023-06-01"
DEFAULT_BASE_URL: Final = "https://api.anthropic.com"

# 429 and 5xx are the provider being unwell; everything else is us being wrong, and
# failing over to another provider would not fix it.
UNAVAILABLE_STATUSES: Final = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

STOP_REASONS: Final[dict[str, StopReason]] = {
    "end_turn": StopReason.END_TURN,
    "max_tokens": StopReason.MAX_TOKENS,
    "tool_use": StopReason.TOOL_USE,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "refusal": StopReason.REFUSAL,
    "pause_turn": StopReason.PAUSE_TURN,
}


class AnthropicSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = DEFAULT_BASE_URL
    connect_timeout_s: float = 5.0


def build_body(request: Request) -> dict[str, Any]:
    """Translate a `Request` into the Messages API wire body.

    Public because the cassette recorder and the tests both need to see exactly what
    would go over the wire, without a client or a key.
    """
    body: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "stream": True,
        "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
    }

    # Older models reject the parameter outright ("This model does not support the
    # effort parameter"), so `effort=None` has to mean absent, not defaulted.
    if request.effort is not None:
        body["output_config"] = {"effort": request.effort.value}

    if request.system:
        # A list of blocks, not a bare string, so the stable prefix can be marked for
        # caching. Anything volatile belongs in the messages, after this breakpoint.
        block: dict[str, Any] = {"type": "text", "text": request.system}
        if request.cache_system:
            block["cache_control"] = {"type": "ephemeral"}
        body["system"] = [block]

    if request.tool is not None:
        body["tools"] = [_tool_payload(request.tool)]
        # Forcing the tool is what makes the DSL the only possible output shape.
        body["tool_choice"] = {"type": "tool", "name": request.tool.name}

    return body


def _tool_payload(tool: ToolSchema) -> dict[str, Any]:
    schema = tool.input_schema
    # `strict` is layer 1 of P4, and the API only honours it on a closed schema. A tool
    # that quietly falls back to non-strict is the failure this check exists to prevent.
    if schema.get("additionalProperties") is not False or "required" not in schema:
        raise ValueError(
            f"tool {tool.name!r} is not strict-ready: its input_schema needs "
            '"additionalProperties": false and a "required" list'
        )
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": schema,
        "strict": True,
    }


class AnthropicAdapter:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        *,
        settings: AnthropicSettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or AnthropicSettings()
        self._client = httpx.AsyncClient(
            base_url=self._settings.base_url,
            http2=True,
            transport=transport,
            headers={
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            # No read timeout on purpose: the deadline (§4.2) is the single authority on
            # how long a call may take, and two competing clocks would only disagree.
            timeout=httpx.Timeout(
                None,
                connect=self._settings.connect_timeout_s,
                pool=self._settings.connect_timeout_s,
            ),
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> AnthropicAdapter:  # noqa: ANN401 — passthrough
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        return cls(key, **kwargs)

    async def warm(self) -> None:
        """Open and authenticate the connection before it is needed.

        §4.2 budgets zero for the handshake. That is only true if someone paid for it
        earlier — call this at session start, off the critical path. Costs no tokens.
        """
        try:
            response = await self._client.get("/v1/models", params={"limit": 1})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"could not warm the pool: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        try:
            async with asyncio.timeout(request.deadline_s):
                async for event in self._stream(request):
                    yield event
        except TimeoutError as exc:
            raise DeadlineExceededError(
                f"exceeded the {request.deadline_s}s deadline; "
                "play the deterministic part and do not retry this section"
            ) from exc

    async def _stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        state = _StreamState()
        try:
            async with self._client.stream(
                "POST", "/v1/messages", json=build_body(request)
            ) as response:
                if response.status_code != httpx.codes.OK:
                    await response.aread()
                    raise _status_error(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue  # `event:` lines are redundant — the JSON carries the type
                    for event in state.consume(json.loads(line[5:].strip())):
                        yield event
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{type(exc).__name__}: {exc}") from exc


class _StreamState:
    """Turns the SSE event sequence into port events, carrying usage across it.

    Usage arrives in two places: `message_start` has the input side, `message_delta` the
    output side (and sometimes restates the cache fields). Both are merged, and the
    total is emitted once, at the end, with `StreamDone`.
    """

    def __init__(self) -> None:
        self._usage: dict[str, int] = {}
        self._stop: StopReason | None = None

    def consume(self, payload: dict[str, Any]) -> list[StreamEvent]:
        kind = payload.get("type")

        if kind == "error":
            raise _sse_error(payload)

        if kind == "message_start":
            self._merge_usage(payload.get("message", {}).get("usage"))
            return []

        if kind == "content_block_start":
            block = payload.get("content_block", {})
            if block.get("type") == "tool_use":
                return [ToolUseStart(id=block["id"], name=block["name"])]
            return []

        if kind == "content_block_delta":
            return self._delta(payload.get("delta", {}))

        if kind == "message_delta":
            self._merge_usage(payload.get("usage"))
            reason = payload.get("delta", {}).get("stop_reason")
            if reason is not None:
                self._stop = STOP_REASONS.get(reason, StopReason.END_TURN)
            return []

        if kind == "message_stop":
            return [StreamDone(stop=self._stop or StopReason.END_TURN, usage=self._built_usage())]

        # ping, content_block_stop, and anything added after this was written.
        return []

    def _delta(self, delta: dict[str, Any]) -> list[StreamEvent]:
        kind = delta.get("type")
        if kind == "text_delta":
            return [TextDelta(text=delta["text"])]
        if kind == "input_json_delta":
            if "partial_json" not in delta:
                # Loud rather than silent: dropping these would lose half a section and
                # look like the model simply produced less.
                raise ProviderError(f"input_json_delta without partial_json: {delta!r}")
            return [ToolInputDelta(fragment=delta["partial_json"])]
        # thinking_delta and signature_delta are reasoning, not the DSL. Dropped.
        return []

    def _merge_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value = usage.get(key)
            if isinstance(value, int):
                self._usage[key] = value

    def _built_usage(self) -> Usage:
        return Usage(
            input_tokens=self._usage.get("input_tokens", 0),
            output_tokens=self._usage.get("output_tokens", 0),
            cache_read_tokens=self._usage.get("cache_read_input_tokens", 0),
            cache_write_tokens=self._usage.get("cache_creation_input_tokens", 0),
        )


def _status_error(response: httpx.Response) -> ProviderError:
    detail = response.text[:500]
    message = f"HTTP {response.status_code} from the Messages API: {detail}"
    if response.status_code in UNAVAILABLE_STATUSES:
        return ProviderUnavailableError(message)
    return ProviderError(message)


def _sse_error(payload: dict[str, Any]) -> ProviderError:
    error = payload.get("error", {})
    kind = error.get("type", "unknown")
    message = f"{kind}: {error.get('message', '')}"
    if kind in {"overloaded_error", "api_error", "rate_limit_error"}:
        return ProviderUnavailableError(message)
    return ProviderError(message)
