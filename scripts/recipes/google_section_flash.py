"""Records the section-shot against Gemini Flash-Lite instead of Pro.

Same briefing as `google_section.py` - the point of a Google cassette is to pin the
Gemini *wire format*, which is identical across models, and Flash-Lite is the one this
key can actually call: Gemini 3.1 Pro answers 429 with
"limit: 0, generate_content_free_tier_input_token_count", i.e. the model needs a paid
tier. Re-record against `google_section.py` once billing is enabled; until then this is
the cassette that keeps the adapter honest.

    uv run python scripts/record_cassette.py scripts/recipes/google_section_flash.py \
        --out cassettes/google_section_flash.jsonl --note "rock verse in Em, 8 bars"
"""

from __future__ import annotations

from section_brief import SYSTEM, TOOL, USER

from garagem.llm import Effort, GoogleAdapter, LLMProvider, Message, Request, Role

REQUEST = Request(
    model="gemini-flash-lite-latest",
    system=SYSTEM,
    messages=(Message(role=Role.USER, content=USER),),
    tool=TOOL,
    max_tokens=2048,
    effort=Effort.LOW,
    deadline_s=5.8,
)


def build() -> tuple[LLMProvider, Request]:
    return GoogleAdapter.from_env(), REQUEST
