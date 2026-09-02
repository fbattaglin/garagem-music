"""Four recorded responses from three real models, replayed with no network.

This is the phase's exit criterion measured on a sample far too small to *be* the
criterion — `scripts/bench_sections.py` does that with n=30 against the live API. What
it is instead is a regression suite made of real model output, which is the only kind
that catches a parser quietly learning to accept something it should refuse.

The pinned failure matters as much as the passes. `google_section_flash` wrote
`GTR … rhy:xx.xx.xx.xx.xx.xx.xx.` — 21 characters where the grid is sixteen. If a change
ever makes that parse, this file fails in the offline suite rather than in the music.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from garagem.domain import Feel, Instrument, Section
from garagem.dsl import parse_section, realise
from garagem.llm import EVENT_ADAPTER, StreamEvent
from garagem.theory import parse_chart, repair, validate

ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ROOT / "cassettes"

# The briefing the four cassettes were recorded against
# (`scripts/recipes/section_brief.py`).
BRIEFING = Section(
    name="verse",
    bars=8,
    key=4,
    scale="minor",
    feel=Feel.STRAIGHT8,
    bpm=132.0,
    dyn=3,
    tension=0.4,
    chart=parse_chart("| Em | Em | C | D | Em | Em | C | B7 |"),
)

# `example_section` predates the DSL settling — its recipe writes `SEC verse 8 132 Em` and
# `DRM |x--x--x-|`, a format from before the skill was written. It is a *format* example
# produced by `FakeProvider`, not a recording of a model, and it is excluded here rather
# than deleted: it still documents how a recipe is built with no network.
FROM_MODELS = ("anthropic_section", "google_section", "google_section_flash")


def recorded(name: str) -> list[StreamEvent]:
    lines = (CASSETTES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [EVENT_ADAPTER.validate_json(line) for line in lines[1:]]


def header(name: str) -> dict[str, str]:
    first = (CASSETTES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()[0]
    return dict(json.loads(first))


# ---------------------------------------------------------------------------- conformance


@pytest.mark.parametrize("name", FROM_MODELS)
def test_every_recorded_response_reaches_the_parser(name: str) -> None:
    """Whatever else is wrong with it, the envelope is the object the schema promised."""
    parsed = parse_section(recorded(name), BRIEFING)
    assert not parsed.truncated or parsed.instruments()


@pytest.mark.parametrize("name", FROM_MODELS)
def test_every_recorded_response_is_perfectly_conformant(name: str) -> None:
    """Three models, three clean sections, under prompt v2.

    Under v1 this was one of three. The two failures were `voi=min` and `voi=clean` — a
    chord quality where a voicing was asked for — and the prompt showed `voi=pow` and
    `voi=sus2` as examples while never saying those were two of six. Enumerating them
    fixed both. The measurement is in `phase-3-findings.md`; this is the regression.
    """
    parsed = parse_section(recorded(name), BRIEFING)
    assert parsed.violations == ()
    assert parsed.instruments() == frozenset(Instrument)


def test_a_voicing_the_dsl_does_not_have_is_still_refused() -> None:
    """The prompt got clearer; the parser did not get looser.

    `voi=min` was a real response from Gemini 3.1 Pro under prompt v1. It must still be
    a violation — the fix was to stop provoking it, not to start accepting it.
    """
    from garagem.dsl.errors import LineError
    from garagem.dsl.lines import parse_bar_line

    with pytest.raises(LineError, match="not a voicing"):
        parse_bar_line("KEY voi=min reg=mid rhy:x...............")


def test_a_grid_of_the_wrong_length_is_still_refused() -> None:
    """`rhy:xx.xx.xx.xx.xx.xx.xx.` — 21 characters, a real response from Flash under v1."""
    from garagem.dsl.errors import LineError
    from garagem.dsl.lines import parse_bar_line

    with pytest.raises(LineError, match="21"):
        parse_bar_line("GTR voi=pow rhy:xx.xx.xx.xx.xx.xx.xx. palm=on")


@pytest.mark.parametrize("name", FROM_MODELS)
def test_what_parsed_realises_into_music_the_validator_accepts(name: str) -> None:
    parsed = parse_section(recorded(name), BRIEFING)
    score = realise(parsed, 7)
    repaired, left = repair(score)
    assert left == ()
    assert validate(repaired) == ()


# ------------------------------------------------------------------------------ the rate


def test_the_conformance_rate_over_the_recorded_sample() -> None:
    """Three of three, under prompt v2. It was one of three under v1.

    Three is not a sample — the real measurement is `scripts/bench_sections.py` at n=30,
    and it is what the exit criterion is read from. This is a sanity check with a number
    attached, and the number is here so that a change moving it is visible rather than
    buried. When it moves, move it deliberately and say in the commit what changed in the
    prompt — the same rule the golden files follow.
    """
    clean = [name for name in FROM_MODELS if not parse_section(recorded(name), BRIEFING).violations]
    assert len(clean) == len(FROM_MODELS), (
        f"{len(clean)}/{len(FROM_MODELS)} recorded responses are clean: {clean}. "
        "The real measurement is scripts/bench_sections.py with n=30."
    )


def test_the_prompt_now_states_what_it_used_to_leave_to_inference() -> None:
    """The two v1 failures were both a field whose legal set was shown by example only.

    Enumerating the six voicings and writing the chart out one chord per bar took the
    recorded sample from one clean response to three. The measurement at n=30 is in
    `phase-3-findings.md`; this test is what stops the prompt from quietly losing them.
    """
    from garagem.dsl.lines import VOICINGS
    from garagem.dsl.schema import SYSTEM

    named = [voicing for voicing in VOICINGS if f"    {voicing}" in SYSTEM]
    assert sorted(named) == sorted(VOICINGS)
    assert "exactly 16 characters" in SYSTEM
    assert "not a voicing" in SYSTEM


def test_the_sample_covers_more_than_one_provider() -> None:
    """A conformance rate measured on one model is a fact about that model."""
    providers = {header(name)["provider"] for name in FROM_MODELS}
    assert len(providers) > 1


def test_anthropic_streamed_in_pieces_and_flash_did_not() -> None:
    """ADR-011's premise, from the recordings: incremental parsing pays on one path."""
    fragments = {
        name: sum(1 for event in recorded(name) if event.type == "tool_input_delta")
        for name in ("anthropic_section", "google_section_flash")
    }
    assert fragments["anthropic_section"] > 40
    assert fragments["google_section_flash"] == 1
