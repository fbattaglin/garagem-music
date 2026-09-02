"""Serialize, stream, parse, realise — for any section the band can produce.

The strongest statement available in this phase, and it costs nothing: the parser is
tested against thousands of sections nobody wrote by hand, using output that is already
golden-tested and was already approved by ear.

**It is not the identity, and the gap is the DSL's rather than the parser's.** A
sixteen-slot grid cannot carry a nine-millisecond push, and `BAS deg=1` is one degree per
*bar* — so a bass line that moves to the fifth mid-bar comes back on the root. What must
survive is asserted exactly: every attack, every instrument, no violation, and every
pitch class for the three parts whose notation can carry them.

If this fails, the parser is wrong and not the serializer: the serializer's output is
compared byte for byte against committed files in `tests/golden/`, and the music it
describes is what Fabiano listened to on 2026-08-30.
"""

from __future__ import annotations

import json

from hypothesis import given
from strategies import sections, seeds

from garagem.domain import Instrument, Section
from garagem.dsl import parse_section, realise, serialize_section
from garagem.engines import play_section
from garagem.llm import StreamDone, StreamEvent, ToolInputDelta, ToolUseStart
from garagem.theory import validate
from garagem.theory.validator import grid_slots, nearest_slot

# The three whose notation can carry a pitch. `BAS deg=` is one degree per bar.
FULLY_SPELLED = (Instrument.DRUMS, Instrument.GUITAR, Instrument.KEYS)


def as_stream(dsl: str) -> list[StreamEvent]:
    """One fragment, the way Gemini sends it. The 45-fragment path has its own tests."""
    return [
        ToolUseStart(id="round-trip", name="write_section"),
        ToolInputDelta(fragment=json.dumps({"dsl": dsl})),
        StreamDone(stop="tool_use"),
    ]


def attacks(part_notes: tuple[float, ...], section: Section) -> list[float]:
    slots = grid_slots(section)
    return sorted({round(nearest_slot(slots, start), 4) for start in part_notes})


@given(section=sections, seed=seeds)
def test_the_round_trip_keeps_every_attack(section: Section, seed: int) -> None:
    """Where a note falls survives the notation, for every feel and every bar count."""
    original = play_section(section, seed)
    parsed = parse_section(as_stream(serialize_section(original)), section)
    back = realise(parsed, seed)

    for instrument in Instrument:
        before = tuple(n.start_beats for n in original.part(instrument).notes)
        after = tuple(n.start_beats for n in back.part(instrument).notes)
        assert attacks(before, section) == attacks(after, section)


@given(section=sections, seed=seeds)
def test_the_round_trip_produces_no_violation(section: Section, seed: int) -> None:
    """Our own serializer must be perfectly conformant, or the conformance rate is noise."""
    original = play_section(section, seed)
    parsed = parse_section(as_stream(serialize_section(original)), section)
    assert parsed.violations == ()
    assert not parsed.truncated


@given(section=sections, seed=seeds)
def test_what_comes_back_is_playable(section: Section, seed: int) -> None:
    original = play_section(section, seed)
    parsed = parse_section(as_stream(serialize_section(original)), section)
    back = realise(parsed, seed)
    assert back.instruments() == original.instruments()
    assert validate(back) == ()


@given(section=sections, seed=seeds)
def test_pitch_classes_survive_wherever_the_notation_can_carry_them(
    section: Section, seed: int
) -> None:
    """Drums, guitar and keys spell every note. The bass spells one degree per bar."""
    original = play_section(section, seed)
    parsed = parse_section(as_stream(serialize_section(original)), section)
    back = realise(parsed, seed)

    for instrument in FULLY_SPELLED:
        before = {n.pitch % 12 for n in original.part(instrument).notes}
        after = {n.pitch % 12 for n in back.part(instrument).notes}
        assert before == after


@given(section=sections, seed=seeds)
def test_the_bass_comes_back_on_the_roots_it_declared(section: Section, seed: int) -> None:
    """The one lossy part, stated rather than discovered: `deg=` is per bar."""
    original = play_section(section, seed)
    parsed = parse_section(as_stream(serialize_section(original)), section)
    back = realise(parsed, seed)

    before = {n.pitch % 12 for n in original.part(Instrument.BASS).notes}
    after = {n.pitch % 12 for n in back.part(Instrument.BASS).notes}
    assert after <= before


@given(section=sections, seed=seeds)
def test_the_round_trip_is_reproducible(section: Section, seed: int) -> None:
    original = play_section(section, seed)
    dsl = serialize_section(original)
    first = realise(parse_section(as_stream(dsl), section), seed)
    second = realise(parse_section(as_stream(dsl), section), seed)
    assert first == second
