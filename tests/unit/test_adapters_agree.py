"""Both adapters, seen from above, are the same provider.

This is the payoff ADR-012 was bought for: nothing in `agents/` should be able to tell
which one it is holding. Each adapter is fed its own provider's wire format carrying
the same section, and the port-level result has to match.

Where they legitimately differ — Gemini delivers tool arguments whole, Anthropic in
fragments — the test says so explicitly rather than papering over it.
"""

from __future__ import annotations

import json

import httpx

from conftest import Collector, tool_input_of
from garagem.llm import (
    AnthropicAdapter,
    GoogleAdapter,
    LLMProvider,
    Message,
    Request,
    Role,
    StopReason,
    ToolSchema,
    Usage,
)

DSL = "SEC verse 8 132 Em\nDRM |x--x--x-|x--x--x-|\nBAS |E---G---|D---A---|"

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


def a_request(model: str) -> Request:
    return Request(
        model=model,
        system="DSL rules",
        messages=(Message(role=Role.USER, content="a verse in Em"),),
        tool=TOOL,
        max_tokens=800,
        deadline_s=5.8,
    )


def serving(body: bytes) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, content=body))


def anthropic_wire() -> bytes:
    payloads: list[dict[str, object]] = [
        {
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 2000,
                }
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": "toolu_01", "name": "write_section"},
        },
    ]
    # The same JSON, chopped the way the Messages API chops it.
    payload = json.dumps({"dsl": DSL})
    for i in range(0, len(payload), 16):
        payloads.append(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": payload[i : i + 16]},
            }
        )
    payloads += [
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 800},
        },
        {"type": "message_stop"},
    ]
    return "\n".join(f"data: {json.dumps(p)}\n" for p in payloads).encode("utf-8")


def google_wire() -> bytes:
    chunk = {
        "candidates": [
            {
                "content": {
                    "parts": [{"functionCall": {"name": "write_section", "args": {"dsl": DSL}}}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 2500,
            "candidatesTokenCount": 800,
            "cachedContentTokenCount": 2000,
        },
    }
    return f"data: {json.dumps(chunk)}\n".encode()


def both() -> list[tuple[LLMProvider, Request]]:
    return [
        (
            AnthropicAdapter("k", transport=serving(anthropic_wire())),
            a_request("claude-opus-5"),
        ),
        (GoogleAdapter("k", transport=serving(google_wire())), a_request("gemini-3-1-pro")),
    ]


def test_both_adapters_deliver_the_same_section(collect: Collector) -> None:
    for provider, request in both():
        events = collect(provider, request)
        assert tool_input_of(events) == {"dsl": DSL}, provider.name


def test_both_adapters_report_the_same_stop_and_usage(collect: Collector) -> None:
    """The governor charges off this. It must not depend on which provider answered."""
    expected = Usage(input_tokens=500, output_tokens=800, cache_read_tokens=2000)
    for provider, request in both():
        done = collect(provider, request)[-1]
        assert done.type == "done", provider.name
        assert done.stop is StopReason.TOOL_USE, provider.name
        assert done.usage == expected, provider.name


def test_both_name_the_tool_the_same_way(collect: Collector) -> None:
    for provider, request in both():
        starts = [e for e in collect(provider, request) if e.type == "tool_use_start"]
        assert [s.name for s in starts] == ["write_section"], provider.name


def test_only_anthropic_actually_streams_the_tool_arguments(collect: Collector) -> None:
    """The honest difference, asserted rather than hidden. It is an input to E2 and E5."""
    counts = {}
    for provider, request in both():
        events = collect(provider, request)
        counts[provider.name] = len([e for e in events if e.type == "tool_input_delta"])

    assert counts["anthropic"] > 1, "the Messages API streams partial JSON"
    assert counts["google"] == 1, "Gemini delivers the arguments whole"
