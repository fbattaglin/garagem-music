"""The Anthropic adapter: wire body, SSE translation, failure classification.

Every test drives a real `httpx.AsyncClient` through a `MockTransport`, so the SSE
parsing, the status handling and the streaming path are all genuinely exercised — with
no socket opened. The SSE fixtures below are copied from the published event shapes;
they are what pins the wire format.
"""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import Collector, text_of, tool_input_of
from garagem.llm import (
    AnthropicAdapter,
    DeadlineExceededError,
    Effort,
    LLMProvider,
    Message,
    ProviderError,
    ProviderUnavailableError,
    Request,
    Role,
    StopReason,
    ToolSchema,
)
from garagem.llm.anthropic import build_body

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
        "model": "claude-opus-5",
        "messages": (Message(role=Role.USER, content="a verse in Em"),),
        "max_tokens": 800,
        "deadline_s": 5.8,
    }
    return Request.model_validate(base | extra)


def sse(*payloads: dict[str, object]) -> bytes:
    lines = []
    for payload in payloads:
        lines.append(f"event: {payload['type']}")
        lines.append(f"data: {json.dumps(payload)}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


TEXT_STREAM = sse(
    {
        "type": "message_start",
        "message": {"id": "msg_1", "usage": {"input_tokens": 472, "output_tokens": 2}},
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "ping"},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "SEC "}},
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "verse 8"},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 89},
    },
    {"type": "message_stop"},
)

TOOL_STREAM = sse(
    {
        "type": "message_start",
        "message": {
            "id": "msg_2",
            "usage": {
                "input_tokens": 2000,
                "output_tokens": 1,
                "cache_read_input_tokens": 2048,
                "cache_creation_input_tokens": 120,
            },
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "write_section",
            "input": {},
        },
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"dsl":'},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": ' "SEC verse"}'},
    },
    {"type": "content_block_stop", "index": 0},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use", "stop_sequence": None},
        "usage": {"output_tokens": 89},
    },
    {"type": "message_stop"},
)


def adapter_serving(
    body: bytes = TEXT_STREAM,
    *,
    status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> AnthropicAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, content=body)

    return AnthropicAdapter("sk-ant-test", transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------------ wire body


def test_the_body_carries_what_the_messages_api_needs() -> None:
    body = build_body(a_request(system="DSL rules", tool=TOOL, effort=Effort.LOW))

    assert body["model"] == "claude-opus-5"
    assert body["max_tokens"] == 800
    assert body["stream"] is True
    assert body["messages"] == [{"role": "user", "content": "a verse in Em"}]
    assert body["output_config"] == {"effort": "low"}


def test_a_model_without_the_effort_knob_gets_no_effort_field() -> None:
    """Haiku 4.5 rejects the parameter with a 400 rather than ignoring it.

    So `effort=None` has to mean the field is absent from the body, not present with
    some default - the tactical layer is exactly the layer that runs on those models.
    """
    body = build_body(a_request(effort=None))
    assert "output_config" not in body


def test_the_system_prefix_is_marked_for_caching() -> None:
    """The whole latency argument in §4.4 rests on this block being cached."""
    body = build_body(a_request(system="DSL rules"))
    assert body["system"] == [
        {"type": "text", "text": "DSL rules", "cache_control": {"type": "ephemeral"}}
    ]


def test_caching_can_be_turned_off_per_request() -> None:
    body = build_body(a_request(system="DSL rules", cache_system=False))
    assert "cache_control" not in body["system"][0]


def test_no_system_block_when_there_is_no_system_prompt() -> None:
    assert "system" not in build_body(a_request())


def test_the_tool_is_strict_and_forced() -> None:
    """Layer 1 of P4: the DSL is the only shape the response can take."""
    body = build_body(a_request(tool=TOOL))
    assert body["tools"][0]["strict"] is True
    assert body["tool_choice"] == {"type": "tool", "name": "write_section"}


def test_a_schema_that_cannot_be_strict_is_refused() -> None:
    """An open schema silently downgrades to non-strict — catch it here, not in the music."""
    loose = ToolSchema(
        name="write_section",
        description="...",
        input_schema={"type": "object", "properties": {}, "required": []},
    )
    with pytest.raises(ValueError, match="strict-ready"):
        build_body(a_request(tool=loose))


# ------------------------------------------------------------------- SSE translation


def test_text_deltas_become_text_events(collect: Collector) -> None:
    events = collect(adapter_serving(TEXT_STREAM), a_request())
    assert text_of(events) == "SEC verse 8"
    assert events[-1].type == "done"
    assert events[-1].stop is StopReason.END_TURN


def test_usage_is_merged_from_message_start_and_message_delta(collect: Collector) -> None:
    events = collect(adapter_serving(TOOL_STREAM), a_request(tool=TOOL))
    done = events[-1]
    assert done.type == "done"
    assert done.usage.input_tokens == 2000
    assert done.usage.output_tokens == 89  # message_delta wins over message_start's 1
    assert done.usage.cache_read_tokens == 2048
    assert done.usage.cache_write_tokens == 120


def test_tool_use_arrives_as_a_start_plus_json_fragments(collect: Collector) -> None:
    events = collect(adapter_serving(TOOL_STREAM), a_request(tool=TOOL))

    starts = [e for e in events if e.type == "tool_use_start"]
    assert [(s.id, s.name) for s in starts] == [("toolu_01", "write_section")]
    assert tool_input_of(events) == {"dsl": "SEC verse"}
    done = events[-1]
    assert done.type == "done"
    assert done.stop is StopReason.TOOL_USE


def test_ping_and_content_block_stop_produce_nothing(collect: Collector) -> None:
    events = collect(adapter_serving(TEXT_STREAM), a_request())
    assert [e.type for e in events] == ["text_delta", "text_delta", "done"]


def test_thinking_deltas_are_dropped(collect: Collector) -> None:
    """Reasoning is not the DSL. It must not reach the incremental parser."""
    body = sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": "let me think"},
        },
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "SEC"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {}},
        {"type": "message_stop"},
    )
    events = collect(adapter_serving(body), a_request())
    assert text_of(events) == "SEC"


def test_a_refusal_is_a_stop_reason_not_an_exception(collect: Collector) -> None:
    """The API answers 200. The caller decides what to play; the breaker stays shut."""
    body = sse(
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "message_delta", "delta": {"stop_reason": "refusal"}, "usage": {}},
        {"type": "message_stop"},
    )
    events = collect(adapter_serving(body), a_request())
    done = events[-1]
    assert done.type == "done"
    assert done.stop is StopReason.REFUSAL


def test_an_input_json_delta_without_partial_json_fails_loudly(collect: Collector) -> None:
    """Silently dropping these would look like the model just wrote less music."""
    body = sse(
        {"type": "message_start", "message": {"usage": {}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta"}},
    )
    with pytest.raises(ProviderError, match="partial_json"):
        collect(adapter_serving(body), a_request())


# ------------------------------------------------------------- failure classification


@pytest.mark.parametrize("status", [429, 500, 503, 529])
def test_server_side_trouble_is_unavailable(collect: Collector, status: int) -> None:
    """These are the ones the breaker should count."""
    with pytest.raises(ProviderUnavailableError, match=str(status)):
        collect(adapter_serving(b"overloaded", status=status), a_request())


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_our_own_mistakes_are_not_unavailable(collect: Collector, status: int) -> None:
    """A malformed request is not a sick provider — failing over would not fix it."""
    with pytest.raises(ProviderError) as caught:
        collect(adapter_serving(b"bad request", status=status), a_request())
    assert not isinstance(caught.value, ProviderUnavailableError)


def test_an_overloaded_error_mid_stream_is_unavailable(collect: Collector) -> None:
    body = sse(
        {"type": "message_start", "message": {"usage": {}}},
        {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
    )
    with pytest.raises(ProviderUnavailableError, match="overloaded"):
        collect(adapter_serving(body), a_request())


def test_a_transport_failure_is_unavailable(collect: Collector) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = AnthropicAdapter("sk-ant-test", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailableError, match="ConnectError"):
        collect(adapter, a_request())


def test_the_deadline_is_enforced_and_is_not_a_provider_failure(collect: Collector) -> None:
    """§4.2: cancel, log, play the deterministic part. Not the breaker's business."""

    async def handler(request: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(10)
        return httpx.Response(200, content=TEXT_STREAM)

    adapter = AnthropicAdapter("sk-ant-test", transport=httpx.MockTransport(handler))
    with pytest.raises(DeadlineExceededError) as caught:
        collect(adapter, a_request(deadline_s=0.05))
    assert not isinstance(caught.value, ProviderUnavailableError)


# ------------------------------------------------------------------------- plumbing


def test_the_request_reaches_the_right_endpoint_with_auth() -> None:
    seen: list[httpx.Request] = []
    import asyncio

    async def drain() -> None:
        adapter = adapter_serving(TEXT_STREAM, seen=seen)
        async for _ in adapter.stream(a_request()):
            pass

    asyncio.run(drain())

    (sent,) = seen
    assert sent.url.path == "/v1/messages"
    assert sent.headers["x-api-key"] == "sk-ant-test"
    assert sent.headers["anthropic-version"] == "2023-06-01"


def test_the_adapter_satisfies_the_port() -> None:
    adapter: LLMProvider = adapter_serving()
    assert isinstance(adapter, LLMProvider)
    assert adapter.name == "anthropic"
