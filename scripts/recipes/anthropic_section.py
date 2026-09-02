"""Records a real section-shot call against the Messages API.

This is one of the two files in the project that talk to the network on purpose. It
needs `ANTHROPIC_API_KEY` and it spends real money — a few cents (§4.4).

    uv run python scripts/record_cassette.py scripts/recipes/anthropic_section.py \
        --out cassettes/anthropic_section.jsonl --note "rock verse in Em, 8 bars"

The system block is the stable, cacheable prefix. Changing it changes the request
fingerprint, which is exactly what makes the recorded cassette stop matching — that is
the drift alarm, not a nuisance to work around.
"""

from __future__ import annotations

from section_brief import SYSTEM, TOOL, USER

from garagem.llm import AnthropicAdapter, Effort, LLMProvider, Message, Request, Role

REQUEST = Request(
    model="claude-opus-5",
    system=SYSTEM,
    messages=(Message(role=Role.USER, content=USER),),
    tool=TOOL,
    max_tokens=2048,
    # Structural layer: this is the call that can afford to think (§4.2).
    effort=Effort.HIGH,
    # 40% of the 14.5 s an 8-bar section lasts at 132 BPM.
    deadline_s=5.8,
)


def build() -> tuple[LLMProvider, Request]:
    return AnthropicAdapter.from_env(), REQUEST
