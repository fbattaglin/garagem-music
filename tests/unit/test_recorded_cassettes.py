"""The real recordings, replayed offline.

Everything else in the suite feeds the adapters fixtures written by hand from the
published wire formats. These three files are different: they are what the Messages
API and the Gemini API actually sent, on 2026-08-30, for the section-shot briefing.
They are the only thing in the default suite that can catch a wire format we
understood wrongly rather than one we transcribed wrongly.

Two Gemini models, not one: `gemini-3.1-pro-preview` (the structural-layer model in
`config/models.toml`) is not served on this key's free tier - it answers 429 with
"limit: 0" on the input-token quota. `gemini-3.6-flash` is the strongest model this key
can actually call, so it stands in for the structural role until billing is enabled
(see the docstring in `scripts/recipes/google_section.py`), and
`gemini-flash-lite-latest` covers the tactical role as before.

They also pin, with evidence rather than with a docstring, the difference that decides
what ADR-011's incremental parser is worth per provider: Anthropic streams the tool
arguments in dozens of fragments, Gemini delivers them in exactly one - on both models.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import Collector
from garagem.llm import CassetteProvider, Request, StopReason

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "recipes"))

from anthropic_section import REQUEST as ANTHROPIC_REQUEST  # noqa: E402 - needs the path
from google_section import REQUEST as GOOGLE_STRUCTURAL_REQUEST  # noqa: E402
from google_section_flash import REQUEST as GOOGLE_TACTICAL_REQUEST  # noqa: E402

ANTHROPIC = ROOT / "cassettes" / "anthropic_section.jsonl"
GOOGLE_STRUCTURAL = ROOT / "cassettes" / "google_section.jsonl"
GOOGLE_TACTICAL = ROOT / "cassettes" / "google_section_flash.jsonl"

# The order is not decoration: it is rhythmic priority (section 4.3), and it is what
# lets drums and bass reach the clip while the guitar is still being generated.
MANDATED_ORDER = ("SEC", "CHD", "DRM", "BAS", "GTR", "KEY")

CASES = [
    pytest.param(ANTHROPIC, ANTHROPIC_REQUEST, id="anthropic"),
    pytest.param(GOOGLE_STRUCTURAL, GOOGLE_STRUCTURAL_REQUEST, id="google-structural"),
    pytest.param(GOOGLE_TACTICAL, GOOGLE_TACTICAL_REQUEST, id="google-tactical"),
]


def dsl_of(path: Path, request: Request, collect: Collector) -> str:
    events = collect(CassetteProvider(path), request)
    fragments = "".join(e.fragment for e in events if e.type == "tool_input_delta")
    parsed = json.loads(fragments)
    assert isinstance(parsed["dsl"], str)
    return parsed["dsl"]


@pytest.mark.parametrize(("path", "request_"), CASES)
def test_the_recording_replays_into_a_complete_section(
    path: Path, request_: Request, collect: Collector
) -> None:
    events = collect(CassetteProvider(path), request_)
    starts = [e for e in events if e.type == "tool_use_start"]
    assert [e.name for e in starts] == ["write_section"]

    done = events[-1]
    assert done.type == "done"
    assert done.stop is StopReason.TOOL_USE
    assert done.usage.output_tokens > 0


@pytest.mark.parametrize(("path", "request_"), CASES)
def test_the_model_emitted_the_parts_in_rhythmic_priority(
    path: Path, request_: Request, collect: Collector
) -> None:
    """P4 layer 1 held on a real call: the DSL came back in the mandated order."""
    dsl = dsl_of(path, request_, collect)
    heads = [line.split()[0] for line in dsl.splitlines() if line.strip()]
    assert tuple(heads) == MANDATED_ORDER


@pytest.mark.parametrize(("path", "request_"), CASES)
def test_a_changed_prompt_makes_the_recording_stop_matching(
    path: Path, request_: Request, collect: Collector
) -> None:
    """The drift alarm, on the real files."""
    from garagem.llm import CassetteMismatchError

    drifted = request_.model_copy(update={"system": request_.system + " Also swing it."})
    with pytest.raises(CassetteMismatchError):
        collect(CassetteProvider(path), drifted)


def test_only_anthropic_actually_streamed_the_tool_arguments(collect: Collector) -> None:
    """The ADR-011 question, answered by the recordings rather than by the docs.

    Anthropic cuts the arguments into `partial_json` fragments, so the parser can start
    on the drums while the keys are still coming. Gemini sends one finished object, so
    on that provider the incremental parser buys nothing for tool use - the section is
    either absent or complete. True on both Gemini models measured.
    """

    def fragments(path: Path, request_: Request) -> int:
        events = collect(CassetteProvider(path), request_)
        return sum(1 for e in events if e.type == "tool_input_delta")

    assert fragments(ANTHROPIC, ANTHROPIC_REQUEST) > 10
    assert fragments(GOOGLE_STRUCTURAL, GOOGLE_STRUCTURAL_REQUEST) == 1
    assert fragments(GOOGLE_TACTICAL, GOOGLE_TACTICAL_REQUEST) == 1


def test_the_cached_prefix_was_actually_read(collect: Collector) -> None:
    """The section 4.4 latency and cost argument rests on this, so measure it once.

    The recording was made after the same system block had already gone out, which is
    what a session looks like: the stable prefix is read from cache, not re-sent.
    """
    events = collect(CassetteProvider(ANTHROPIC), ANTHROPIC_REQUEST)
    done = events[-1]
    assert done.type == "done"
    assert done.usage.cache_read_tokens > 0
    assert done.usage.cache_read_tokens > done.usage.input_tokens
