"""Google Gemini adapter (ADR-012), over the same raw-HTTP approach as the Anthropic one.

Same shape, same rules: no retries (P7), the deadline is the only clock, failures are
classified so the breaker can tell a sick provider from a malformed request.

**Three differences from the Messages API that are not cosmetic**, and that E2 (model
routing) has to weigh alongside price and quality:

1. **Tool arguments do not stream.** Gemini delivers a `functionCall` complete, with
   `args` as a finished JSON object. There is no partial-JSON equivalent, so the
   incremental parser (ADR-011) buys *nothing* here for tool use: the whole section
   lands at once. Text does stream, so the gain survives only for text-shaped output.
   We emit the arguments as a single `ToolInputDelta` rather than chopping them up —
   pretending they trickled in would be a lie about when the data was usable.
2. **There is no `strict` flag.** The nearest thing is forcing the call with
   `functionCallingConfig.mode = "ANY"`, which constrains *whether* a tool is used, not
   whether its arguments validate. Layer 1 of P4 is therefore weaker here, which makes
   the deterministic validator (layer 2) load-bearing rather than a safety net.
3. **Effort has a lower ceiling.** Gemini's `thinkingLevel` tops out at `high`, so our
   `XHIGH` and `MAX` clamp to it. The two scales are not comparable — do not read an
   E2 result as if they were.

Prompt caching also differs: Anthropic marks a prefix inline, Gemini uses implicit
caching or a separate CachedContent resource. `Request.cache_system` therefore has no
direct translation here; the system instruction is sent as-is.
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
    Effort,
    Request,
    Role,
    StopReason,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolInputDelta,
    ToolSchema,
    ToolUseStart,
    Usage,
)

DEFAULT_BASE_URL: Final = "https://generativelanguage.googleapis.com"
API_VERSION: Final = "v1beta"

UNAVAILABLE_STATUSES: Final = frozenset({408, 409, 429, 500, 502, 503, 504})

# Gemini speaks "model" where the rest of the world says "assistant".
ROLES: Final[dict[Role, str]] = {Role.USER: "user", Role.ASSISTANT: "model"}

THINKING_LEVELS: Final[dict[Effort, str]] = {
    Effort.LOW: "low",
    Effort.MEDIUM: "medium",
    Effort.HIGH: "high",
    Effort.XHIGH: "high",
    Effort.MAX: "high",
}

# Only the two we can read unambiguously. Everything else — safety, recitation,
# blocklist, whatever gets added next — is treated as a refusal, which is the
# conservative reading: every documented non-STOP reason means the content was cut
# short for a policy reason, and the caller should reach for the deterministic part.
FINISH_REASONS: Final[dict[str, StopReason]] = {
    "STOP": StopReason.END_TURN,
    "MAX_TOKENS": StopReason.MAX_TOKENS,
    "FUNCTION_CALL": StopReason.TOOL_USE,
}

# Keys from the JSON Schema vocabulary that Gemini's OpenAPI subset does not accept.
# `additionalProperties` is the one that matters: our ToolSchema carries it because
# Anthropic's strict mode requires it.
UNSUPPORTED_SCHEMA_KEYS: Final = frozenset({"additionalProperties", "$schema"})


class GoogleSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = DEFAULT_BASE_URL
    connect_timeout_s: float = 5.0


def build_body(request: Request) -> dict[str, Any]:
    """Translate a `Request` into a generateContent wire body."""
    body: dict[str, Any] = {
        "contents": [
            {"role": ROLES[m.role], "parts": [{"text": m.content}]} for m in request.messages
        ],
        "generationConfig": {"maxOutputTokens": request.max_tokens},
    }

    if request.effort is not None:
        body["generationConfig"]["thinkingConfig"] = {
            "thinkingLevel": THINKING_LEVELS[request.effort]
        }

    if request.system:
        body["systemInstruction"] = {"parts": [{"text": request.system}]}

    if request.tool is not None:
        body["tools"] = [{"functionDeclarations": [_declaration(request.tool)]}]
        # ANY forces a tool call; allowedFunctionNames narrows it to ours. It is the
        # closest thing to Anthropic's forced tool_choice.
        body["toolConfig"] = {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": [request.tool.name],
            }
        }

    return body


def _declaration(tool: ToolSchema) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": _prune_schema(tool.input_schema),
    }


def _prune_schema(schema: Any) -> Any:  # noqa: ANN401 — arbitrary JSON Schema
    """Strip vocabulary Gemini rejects, recursively, leaving the shape intact."""
    if isinstance(schema, dict):
        return {
            key: _prune_schema(value)
            for key, value in schema.items()
            if key not in UNSUPPORTED_SCHEMA_KEYS
        }
    if isinstance(schema, list):
        return [_prune_schema(item) for item in schema]
    return schema


class GoogleAdapter:
    name = "google"

    def __init__(
        self,
        api_key: str,
        *,
        settings: GoogleSettings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or GoogleSettings()
        self._client = httpx.AsyncClient(
            base_url=self._settings.base_url,
            http2=True,
            transport=transport,
            # The key goes in a header, not the query string: URLs end up in logs.
            headers={"x-goog-api-key": api_key, "content-type": "application/json"},
            timeout=httpx.Timeout(
                None,
                connect=self._settings.connect_timeout_s,
                pool=self._settings.connect_timeout_s,
            ),
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> GoogleAdapter:  # noqa: ANN401 — passthrough
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError("neither GEMINI_API_KEY nor GOOGLE_API_KEY is set")
        return cls(key, **kwargs)

    async def warm(self) -> None:
        """Open and authenticate the connection before it is needed (§4.2). No tokens."""
        try:
            response = await self._client.get(f"/{API_VERSION}/models", params={"pageSize": 1})
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
        path = f"/{API_VERSION}/models/{request.model}:streamGenerateContent"
        state = _StreamState()
        try:
            async with self._client.stream(
                "POST", path, params={"alt": "sse"}, json=build_body(request)
            ) as response:
                if response.status_code != httpx.codes.OK:
                    await response.aread()
                    raise _status_error(response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    for event in state.consume(json.loads(line[5:].strip())):
                        yield event
                yield state.done()
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"{type(exc).__name__}: {exc}") from exc


class _StreamState:
    """Accumulates chunks into port events.

    Unlike the Messages API, there is no terminal `message_stop` event: the stream just
    ends. `done()` is therefore called by the caller once the body is exhausted, and it
    is the only place a `StreamDone` comes from.
    """

    def __init__(self) -> None:
        self._usage = Usage()
        self._stop: StopReason | None = None
        self._saw_tool_call = False
        self._calls = 0

    def consume(self, payload: dict[str, Any]) -> list[StreamEvent]:
        if "error" in payload:
            raise _payload_error(payload["error"])

        if (usage := payload.get("usageMetadata")) is not None:
            self._usage = _usage_of(usage)

        events: list[StreamEvent] = []
        for candidate in payload.get("candidates", []):
            events += self._candidate(candidate)
        return events

    def done(self) -> StreamDone:
        # A tool call outranks whatever finishReason came with it: the caller cares
        # that there is structured output to parse, not how generation terminated.
        stop = StopReason.TOOL_USE if self._saw_tool_call else (self._stop or StopReason.END_TURN)
        return StreamDone(stop=stop, usage=self._usage)

    def _candidate(self, candidate: dict[str, Any]) -> list[StreamEvent]:
        events: list[StreamEvent] = []
        for part in candidate.get("content", {}).get("parts", []):
            events += self._part(part)

        if (reason := candidate.get("finishReason")) is not None:
            self._stop = FINISH_REASONS.get(reason, StopReason.REFUSAL)
        return events

    def _part(self, part: dict[str, Any]) -> list[StreamEvent]:
        if part.get("thought"):
            return []  # reasoning, not the DSL
        if (text := part.get("text")) is not None:
            # Gemini pads a tool-call response with an empty text part. Forwarding it
            # would wake the incremental parser for nothing, and a real recording would
            # carry an event that means nothing.
            return [TextDelta(text=text)] if text else []
        if (call := part.get("functionCall")) is not None:
            self._saw_tool_call = True
            self._calls += 1
            # No id on the wire; synthesise a stable one so the port's contract holds.
            return [
                ToolUseStart(id=f"gemini_call_{self._calls}", name=call["name"]),
                # One fragment, complete. See the module docstring: this is the whole
                # argument object, not the first slice of a stream.
                ToolInputDelta(fragment=json.dumps(call.get("args", {}))),
            ]
        return []


def _usage_of(usage: dict[str, Any]) -> Usage:
    def count(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) else 0

    cached = count("cachedContentTokenCount")
    return Usage(
        # promptTokenCount is the total prompt, cached content included; the port wants
        # them separate, so the cached share is subtracted out.
        input_tokens=max(count("promptTokenCount") - cached, 0),
        # Thinking tokens are billed as output, so they belong in the output count.
        output_tokens=count("candidatesTokenCount") + count("thoughtsTokenCount"),
        cache_read_tokens=cached,
    )


def _status_error(response: httpx.Response) -> ProviderError:
    message = f"HTTP {response.status_code} from the Gemini API: {response.text[:500]}"
    if response.status_code in UNAVAILABLE_STATUSES:
        return ProviderUnavailableError(message)
    return ProviderError(message)


def _payload_error(error: dict[str, Any]) -> ProviderError:
    status = error.get("status", "UNKNOWN")
    message = f"{status}: {error.get('message', '')}"
    if error.get("code") in UNAVAILABLE_STATUSES or status in {
        "RESOURCE_EXHAUSTED",
        "UNAVAILABLE",
        "INTERNAL",
        "DEADLINE_EXCEEDED",
    }:
        return ProviderUnavailableError(message)
    return ProviderError(message)
