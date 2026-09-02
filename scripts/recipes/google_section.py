"""Records a real section-shot call against the Gemini API.

Needs `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) and spends real money — a few cents.

    uv run python scripts/record_cassette.py scripts/recipes/google_section.py \
        --out cassettes/google_section.jsonl --note "rock verse in Em, 8 bars"

Same briefing as `anthropic_section.py`, imported rather than copied — see
`section_brief.py`. Note that unlike the Messages API, the system block is not marked
for caching here: Gemini caches implicitly or through a separate CachedContent
resource, so `cache_system` has no effect on this request.

Model: Gemini 3.6 Flash, not 3.1 Pro. Pro answers 429 ("limit: 0") on this key's free
tier — billing required. 3.6 Flash is the strongest model this key can actually call,
and its price is in section 4.4 of ADR-000.

The deadline here is 15 s, not the 5.8 s a real 8-bar section-shot would carry. Four
attempts at 5.8 s all failed — two on the deadline itself, two on a 503 from the free
tier being busy — so 5.8 s is not a recording quirk, it is a real finding: on the free
tier, this model does not reliably fit the structural-layer deadline. A production call
under real constraints would degrade to the deterministic engine most of the time. The
generous deadline here exists only to get a recording at all; it does not claim this
model is fit for the structural role as configured. Point this recipe at
`gemini-3.1-pro-preview` with `deadline_s=5.8` once billing is enabled, and re-record.
"""

from __future__ import annotations

from section_brief import SYSTEM, TOOL, USER

from garagem.llm import Effort, GoogleAdapter, LLMProvider, Message, Request, Role

REQUEST = Request(
    model="gemini-3.6-flash",
    system=SYSTEM,
    messages=(Message(role=Role.USER, content=USER),),
    tool=TOOL,
    max_tokens=2048,
    effort=Effort.HIGH,
    # 60 s, and it is not §4.2's deadline. That one lives in `agents/section.py` and is
    # 40% of the musical time; this one only stops a recording from hanging. Phase 0
    # measured this model at p50 12.31 s TTFT with 6 of 15 calls failing, so 15 s here
    # was a coin toss that lost twice — and what the cassette is *for* is comparing
    # content for experiment E2. Its latency is already recorded in latency-report.md,
    # where a reader will not mistake it for a section-shot budget.
    deadline_s=60.0,
)


def build() -> tuple[LLMProvider, Request]:
    return GoogleAdapter.from_env(), REQUEST
