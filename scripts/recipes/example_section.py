"""Example recipe: shows the format without depending on the network.

Once `AnthropicAdapter` exists, a real recipe swaps the `FakeProvider` for it and
everything else — including the generated cassette — stays the same.
"""

from __future__ import annotations

import json

from garagem.llm import (
    FakeProvider,
    FakeResponse,
    LLMProvider,
    Message,
    Request,
    Role,
    StopReason,
    ToolSchema,
    Usage,
)

TOOL = ToolSchema(
    name="write_section",
    description="Writes a complete section in the GARAGEM DSL.",
    input_schema={
        "type": "object",
        "properties": {"dsl": {"type": "string"}},
        "required": ["dsl"],
        "additionalProperties": False,
    },
)

# Ordered by rhythmic priority (ADR-011): drums, bass, harmony.
DSL = "\n".join(
    [
        "SEC verse 8 132 Em",
        "DRM |x--x--x-|x--x--x-|",
        "BAS |E---G---|D---A---|",
        "GTR |Em--G---|D---A---|",
    ]
)


def build() -> tuple[LLMProvider, Request]:
    request = Request(
        model="claude-opus-5",
        system="You are the band. Answer only through the write_section tool.",
        messages=(Message(role=Role.USER, content="A rock verse in Em, 8 bars."),),
        tool=TOOL,
        max_tokens=2048,
        deadline_s=5.8,
    )
    provider = FakeProvider(
        [
            FakeResponse(
                tool_name="write_section",
                tool_input=json.dumps({"dsl": DSL}),
                stop=StopReason.TOOL_USE,
                usage=Usage(input_tokens=512, output_tokens=96, cache_read_tokens=2048),
            )
        ],
        seed=7,
    )
    return provider, request
