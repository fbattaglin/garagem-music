"""The Google adapter: wire body, chunk translation, and where it differs from Anthropic.

Same approach as the Anthropic tests — a real `httpx.AsyncClient` over a
`MockTransport`, so the SSE path is genuinely exercised without a socket. The chunk
fixtures are what pin the wire format.
"""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import Collector, text_of, tool_input_of
from garagem.llm import (
    DeadlineExceededError,
    Effort,
    GoogleAdapter,
    LLMProvider,
    Message,
    ProviderError,
    ProviderUnavailableError,
    Request,
    Role,
    StopReason,
    ToolSchema,
)
from garagem.llm.google import _StreamState, build_body

TOOL = ToolSchema(
    name="write_section",
    description="Writes one section in the DSL.",
    input_schema={
        "type": "object",
        "properties": {"dsl": {"type": "string"}},
        "required": ["dsl"],
        "additionalProperties": False,
    },
)


def a_request(**extra: object) -> Request:
    base: dict[str, object] = {
        "model": "gemini-3-1-pro",
        "messages": (Message(role=Role.USER, content="a verse in Em"),),
        "max_tokens": 800,
        "deadline_s": 5.8,
    }
    return Request.model_validate(base | extra)


def sse(*chunks: dict[str, object]) -> bytes:
    return "\n".join(f"data: {json.dumps(c)}\n" for c in chunks).encode("utf-8")


USAGE = {
    "promptTokenCount": 2500,
    "candidatesTokenCount": 700,
    "thoughtsTokenCount": 100,
    "cachedContentTokenCount": 2000,
}

TEXT_STREAM = sse(
    {"candidates": [{"content": {"parts": [{"text": "SEC "}], "role": "model"}}]},
    {"candidates": [{"content": {"parts": [{"text": "verse 8"}], "role": "model"}}]},
    {
        "candidates": [{"content": {"parts": []}, "finishReason": "STOP"}],
        "usageMetadata": USAGE,
    },
)

TOOL_STREAM = sse(
    {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"functionCall": {"name": "write_section", "args": {"dsl": "SEC verse"}}}
                    ],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": USAGE,
    },
)


def adapter_serving(
    body: bytes = TEXT_STREAM,
    *,
    status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> GoogleAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=body)

    return GoogleAdapter("test-key", transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------------ wire body


def test_the_body_carries_what_generate_content_needs() -> None:
    body = build_body(a_request(system="DSL rules", effort=Effort.LOW))

    assert body["contents"] == [{"role": "user", "parts": [{"text": "a verse in Em"}]}]
    assert body["systemInstruction"] == {"parts": [{"text": "DSL rules"}]}
    assert body["generationConfig"]["maxOutputTokens"] == 800
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}


def test_an_empty_text_part_is_not_an_event() -> None:
    """Observed on a real recording: a tool call comes padded with an empty text part."""
    state = _StreamState()
    assert state.consume({"candidates": [{"content": {"parts": [{"text": ""}]}}]}) == []


def test_a_model_without_the_effort_knob_gets_no_thinking_config() -> None:
    body = build_body(a_request(effort=None))
    assert body["generationConfig"] == {"maxOutputTokens": 800}


def test_the_assistant_role_is_renamed_to_model() -> None:
    """Gemini says "model" where everyone else says "assistant"."""
    request = a_request(
        messages=(
            Message(role=Role.USER, content="a verse"),
            Message(role=Role.ASSISTANT, content="SEC verse"),
        )
    )
    assert [c["role"] for c in build_body(request)["contents"]] == ["user", "model"]


@pytest.mark.parametrize(
    ("effort", "level"),
    [(Effort.LOW, "low"), (Effort.MEDIUM, "medium"), (Effort.HIGH, "high")],
)
def test_effort_maps_onto_thinking_level(effort: Effort, level: str) -> None:
    body = build_body(a_request(effort=effort))
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == level


@pytest.mark.parametrize("effort", [Effort.XHIGH, Effort.MAX])
def test_the_top_of_our_effort_scale_clamps(effort: Effort) -> None:
    """Gemini's scale stops at high. E2 must not read the two scales as comparable."""
    body = build_body(a_request(effort=effort))
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "high"


def test_the_tool_call_is_forced_and_narrowed() -> None:
    body = build_body(a_request(tool=TOOL))
    assert body["toolConfig"]["functionCallingConfig"] == {
        "mode": "ANY",
        "allowedFunctionNames": ["write_section"],
    }
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "write_section"


def test_schema_vocabulary_gemini_rejects_is_stripped() -> None:
    """Our ToolSchema carries additionalProperties for Anthropic's strict mode."""
    nested = ToolSchema(
        name="write_section",
        description="...",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "section": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"dsl": {"type": "string"}},
                }
            },
            "required": ["section"],
        },
    )
    parameters = build_body(a_request(tool=nested))["tools"][0]["functionDeclarations"][0][
        "parameters"
    ]
    assert "additionalProperties" not in parameters
    assert "additionalProperties" not in parameters["properties"]["section"]
    assert parameters["required"] == ["section"]
    assert parameters["properties"]["section"]["properties"]["dsl"] == {"type": "string"}


def test_no_system_instruction_when_there_is_no_system_prompt() -> None:
    assert "systemInstruction" not in build_body(a_request())


# ------------------------------------------------------------------ chunk translation


def test_text_parts_stream_as_deltas(collect: Collector) -> None:
    events = collect(adapter_serving(TEXT_STREAM), a_request())
    assert text_of(events) == "SEC verse 8"
    done = events[-1]
    assert done.type == "done"
    assert done.stop is StopReason.END_TURN


def test_the_stream_ends_with_done_even_without_a_terminal_event(collect: Collector) -> None:
    """Gemini has no message_stop — the body just ends. StreamDone is still emitted."""
    events = collect(adapter_serving(TEXT_STREAM), a_request())
    assert [e.type for e in events].count("done") == 1
    assert events[-1].type == "done"


def test_usage_splits_cached_tokens_out_of_the_prompt_count(collect: Collector) -> None:
    """promptTokenCount includes the cached share; the port wants them apart."""
    events = collect(adapter_serving(TEXT_STREAM), a_request())
    done = events[-1]
    assert done.type == "done"
    assert done.usage.cache_read_tokens == 2000
    assert done.usage.input_tokens == 500  # 2500 - 2000
    assert done.usage.output_tokens == 800  # candidates + thoughts, both billed as output


def test_a_function_call_arrives_complete_in_one_fragment(collect: Collector) -> None:
    """The ADR-011 gain does not exist here. One fragment, whole and already valid."""
    events = collect(adapter_serving(TOOL_STREAM), a_request(tool=TOOL))

    fragments = [e.fragment for e in events if e.type == "tool_input_delta"]
    assert len(fragments) == 1
    assert json.loads(fragments[0]) == {"dsl": "SEC verse"}
    assert tool_input_of(events) == {"dsl": "SEC verse"}


def test_a_tool_call_reports_tool_use_even_when_the_finish_reason_says_stop(
    collect: Collector,
) -> None:
    events = collect(adapter_serving(TOOL_STREAM), a_request(tool=TOOL))
    starts = [e for e in events if e.type == "tool_use_start"]
    assert [s.name for s in starts] == ["write_section"]
    done = events[-1]
    assert done.type == "done"
    assert done.stop is StopReason.TOOL_USE


def test_thought_parts_are_dropped(collect: Collector) -> None:
    body = sse(
        {"candidates": [{"content": {"parts": [{"text": "hmm", "thought": True}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "SEC"}]}, "finishReason": "STOP"}]},
    )
    events = collect(adapter_serving(body), a_request())
    assert text_of(events) == "SEC"


def test_max_tokens_is_reported_as_such(collect: Collector) -> None:
    body = sse({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})
    events = collect(adapter_serving(body), a_request())
    done = events[-1]
    assert done.type == "done"
    assert done.stop is StopReason.MAX_TOKENS


@pytest.mark.parametrize("reason", ["SAFETY", "RECITATION", "BLOCKLIST", "SOMETHING_NEW"])
def test_any_other_finish_reason_is_read_as_a_refusal(collect: Collector, reason: str) -> None:
    """The conservative reading: content cut for policy. Unknown values included."""
    body = sse({"candidates": [{"content": {"parts": []}, "finishReason": reason}]})
    events = collect(adapter_serving(body), a_request())
    done = events[-1]
    assert done.type == "done"
    assert done.stop is StopReason.REFUSAL


# ------------------------------------------------------------- failure classification


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_side_trouble_is_unavailable(collect: Collector, status: int) -> None:
    with pytest.raises(ProviderUnavailableError, match=str(status)):
        collect(adapter_serving(b"busy", status=status), a_request())


@pytest.mark.parametrize("status", [400, 403, 404])
def test_our_own_mistakes_are_not_unavailable(collect: Collector, status: int) -> None:
    with pytest.raises(ProviderError) as caught:
        collect(adapter_serving(b"bad request", status=status), a_request())
    assert not isinstance(caught.value, ProviderUnavailableError)


def test_a_resource_exhausted_payload_mid_stream_is_unavailable(collect: Collector) -> None:
    body = sse({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota"}})
    with pytest.raises(ProviderUnavailableError, match="RESOURCE_EXHAUSTED"):
        collect(adapter_serving(body), a_request())


def test_an_invalid_argument_payload_is_not_unavailable(collect: Collector) -> None:
    body = sse({"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "bad schema"}})
    with pytest.raises(ProviderError) as caught:
        collect(adapter_serving(body), a_request())
    assert not isinstance(caught.value, ProviderUnavailableError)


def test_a_transport_failure_is_unavailable(collect: Collector) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = GoogleAdapter("test-key", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailableError, match="ConnectError"):
        collect(adapter, a_request())


def test_the_deadline_is_enforced_and_is_not_a_provider_failure(collect: Collector) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(10)
        return httpx.Response(200, content=TEXT_STREAM)

    adapter = GoogleAdapter("test-key", transport=httpx.MockTransport(handler))
    with pytest.raises(DeadlineExceededError) as caught:
        collect(adapter, a_request(deadline_s=0.05))
    assert not isinstance(caught.value, ProviderUnavailableError)


# ------------------------------------------------------------------------- plumbing


def test_the_request_hits_the_streaming_endpoint_with_the_key_in_a_header() -> None:
    seen: list[httpx.Request] = []
    import asyncio

    async def drain() -> None:
        adapter = adapter_serving(TEXT_STREAM, seen=seen)
        async for _ in adapter.stream(a_request()):
            pass

    asyncio.run(drain())

    (sent,) = seen
    assert sent.url.path == "/v1beta/models/gemini-3-1-pro:streamGenerateContent"
    assert sent.url.params["alt"] == "sse"
    assert sent.headers["x-goog-api-key"] == "test-key"
    assert "test-key" not in str(sent.url), "the key must not end up in a logged URL"


def test_the_adapter_satisfies_the_port() -> None:
    adapter: LLMProvider = adapter_serving()
    assert isinstance(adapter, LLMProvider)
    assert adapter.name == "google"
