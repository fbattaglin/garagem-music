"""The incremental parser, driven by a real recorded stream.

The assertion that carries ADR-011 is `test_drums_are_ready_before_the_stream_ends`: it
names the event index at which the drums became complete and demands it be earlier than
the last. That is §4.3's "halves effective latency" stated as a number instead of a hope.

The other one worth reading feeds the same DSL as 45 fragments and as one, and demands
the same `ParsedSection`. Anthropic sends 45; Gemini 3.6 Flash sends 1; the parser is
never told which.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from garagem.domain import Feel, Instrument, Section
from garagem.dsl import ORDER, SectionStream, parse_section
from garagem.dsl.errors import StreamProtocolError
from garagem.llm import EVENT_ADAPTER, StreamDone, StreamEvent, TextDelta, ToolInputDelta
from garagem.llm import ToolUseStart as Start
from garagem.theory import parse_chart

ROOT = Path(__file__).resolve().parents[2]

DSL = (
    "SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4\n"
    "CHD | Em | Em | C  | D  | Em | Em | C  | B7 |\n"
    "DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x.\n"
    "BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x.\n"
    "GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on\n"
    "KEY voi=sus2 rhy:x.......x....... reg=mid"
)


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": parse_chart("| Em | Em | C | D | Em | Em | C | B7 |"),
    }
    return Section.model_validate(base | extra)


def events_for(dsl: str, *, pieces: int = 1) -> list[StreamEvent]:
    """A synthetic stream carrying `dsl`, cut into `pieces` fragments."""
    body = json.dumps({"dsl": dsl})
    size = max(1, len(body) // pieces + 1)
    fragments = [body[at : at + size] for at in range(0, len(body), size)]
    return [
        Start(id="toolu_test", name="write_section"),
        *[ToolInputDelta(fragment=fragment) for fragment in fragments],
        StreamDone(stop="tool_use"),
    ]


def recorded(name: str) -> list[StreamEvent]:
    lines = (ROOT / "cassettes" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [EVENT_ADAPTER.validate_json(line) for line in lines[1:]]


# --------------------------------------------------------------------- the whole section


def test_a_whole_section_parses_into_four_parts() -> None:
    parsed = parse_section(events_for(DSL), a_section())
    assert parsed.instruments() == frozenset(Instrument)
    assert parsed.violations == ()
    assert not parsed.truncated


def test_one_line_per_instrument_covers_every_bar() -> None:
    """A model writes one DRM line for eight bars and means all eight."""
    parsed = parse_section(events_for(DSL), a_section())
    assert len(parsed.lines[Instrument.DRUMS]) == 1


def test_the_briefing_survives_a_model_that_disagrees_with_it() -> None:
    """The scheduler already sized the clip. The echo is counted, not obeyed."""
    parsed = parse_section(events_for(DSL.replace("bars=8", "bars=16")), a_section())
    assert parsed.section.bars == 8
    assert [v.rule for v in parsed.violations] == ["section_mismatch"]


# ------------------------------------------------------------------------ progressiveness


def test_drums_are_ready_before_the_stream_ends() -> None:
    """ADR-011's whole claim, as an event index rather than an adjective."""
    stream = SectionStream(a_section())
    events = events_for(DSL, pieces=40)
    ready_at = None
    for index, event in enumerate(events):
        if Instrument.DRUMS in stream.feed(event):
            ready_at = index
            break
    assert ready_at is not None
    assert ready_at < len(events) - 1


def test_instruments_become_ready_in_the_mandated_order() -> None:
    stream = SectionStream(a_section())
    order: list[Instrument] = []
    for event in events_for(DSL, pieces=40):
        order.extend(stream.feed(event))
    assert order == list(ORDER)


def fed(lines: int) -> SectionStream:
    """A stream that has seen the first `lines` lines of the DSL and no `done` event."""
    stream = SectionStream(a_section())
    text = "\n".join(DSL.splitlines()[:lines]) + "\n"
    for event in events_for(text, pieces=40):
        if event.type != "done":
            stream.feed(event)
    return stream


def test_a_later_instrument_is_what_closes_an_earlier_one() -> None:
    """One DRM line does not reach eight bars, so only the BAS line proves it is done."""
    assert Instrument.DRUMS not in fed(3).ready  # SEC, CHD, DRM

    through_bass = fed(4).ready  # + BAS
    assert Instrument.DRUMS in through_bass
    assert Instrument.BASS not in through_bass


# ----------------------------------------------------------------------------- truncation


def test_a_stream_cut_after_the_bass_keeps_what_arrived() -> None:
    """P2: the rest is the deterministic engine's, and that costs nothing extra."""
    partial = "\n".join(DSL.splitlines()[:4])
    parsed = parse_section(events_for(partial), a_section())
    assert parsed.instruments() == {Instrument.DRUMS, Instrument.BASS}
    assert parsed.truncated


def test_a_stream_that_never_called_the_tool_yields_nothing_and_says_so() -> None:
    events: list[StreamEvent] = [TextDelta(text="I'd rather chat"), StreamDone(stop="end_turn")]
    parsed = parse_section(events, a_section())
    assert parsed.instruments() == frozenset()
    assert parsed.truncated


def test_a_last_line_with_no_newline_is_still_read() -> None:
    parsed = parse_section(events_for(DSL), a_section())
    assert Instrument.KEYS in parsed.instruments()


# ------------------------------------------------------------------------------ violations


def test_a_malformed_line_is_a_violation_and_does_not_stop_the_parse() -> None:
    broken = DSL.replace("rhy:xx.xxx.xxx.xx.x.", "rhy:xx.xx.xx.xx.xx.xx.xx.")
    parsed = parse_section(events_for(broken), a_section())
    assert [v.rule for v in parsed.violations] == ["schema"]
    assert Instrument.KEYS in parsed.instruments()


def test_violations_accumulate_rather_than_raising() -> None:
    broken = DSL.replace("voi=pow", "voi=quartal").replace("deg=1", "deg=one")
    parsed = parse_section(events_for(broken), a_section())
    assert len(parsed.violations) == 2


def test_more_lines_than_bars_is_a_violation() -> None:
    """One line means every bar; N lines mean N bars; N+1 means somebody miscounted."""
    two_bars = a_section(bars=2)
    extra = "\n".join(["DRM K:x..............."] * 3)
    parsed = parse_section(events_for(extra + "\n"), two_bars)
    assert len(parsed.lines[Instrument.DRUMS]) == 2
    assert any("more than 2 lines" in v.detail for v in parsed.violations)


def test_a_tool_by_another_name_is_a_protocol_error() -> None:
    """Not a violation: there is no partial section to salvage."""
    stream = SectionStream(a_section())
    with pytest.raises(StreamProtocolError, match="write_section"):
        stream.feed(Start(id="x", name="improvise"))


# --------------------------------------------------------------------- the real cassettes


def test_the_recorded_anthropic_stream_parses_clean() -> None:
    """45 fragments from a real model, replayed with no network."""
    parsed = parse_section(recorded("anthropic_section"), a_section())
    assert parsed.instruments() == frozenset(Instrument)
    assert parsed.violations == ()


def test_the_recorded_flash_stream_parses_clean_too() -> None:
    """It wrote a 21-character guitar grid under prompt v1 and stopped under v2.

    A single fragment rather than 45, which is why it is worth having: the parser is
    never told which provider it is reading.
    """
    parsed = parse_section(recorded("google_section_flash"), a_section())
    assert parsed.violations == ()
    assert parsed.instruments() == frozenset(Instrument)


def test_one_fragment_and_forty_five_give_the_same_section() -> None:
    """The parser is never told which provider it is reading."""
    many = parse_section(events_for(DSL, pieces=45), a_section())
    once = parse_section(events_for(DSL, pieces=1), a_section())
    assert many == once
