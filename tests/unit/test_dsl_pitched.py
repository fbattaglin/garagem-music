"""The bake's notation: a degree per struck slot, and the `LED` line (ADR-026).

GARAGEM/0.1 lets a model name no pitch — the bass gets one degree for a whole bar and
there is no line for a lead at all. That is what a 5.8 s live deadline bought, and offline
it buys nothing. This is the superset, and the test that matters most in the file is the
last one: **the live notation does not move.**

Every refusal here is the exit criterion's denominator, exactly as in `dsl/lines.py`: a
degree map that is not understood must be refused by name, never softened.
"""

from __future__ import annotations

import json

import pytest

from garagem.domain import Feel, Instrument, Section, render_positions
from garagem.dsl import (
    BassLine,
    LeadLine,
    ParsedSection,
    parse_bar_line,
    parse_section,
    realise,
    serialize_section,
)
from garagem.dsl.errors import LineError
from garagem.dsl.realise import straightened
from garagem.engines import play_section
from garagem.llm import StreamDone, StreamEvent, ToolInputDelta, ToolUseStart
from garagem.theory import parse_chart, validate

CHART = "| Em | C | G | D |"


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "chorus",
        "bars": 4,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 4,
        "tension": 0.5,
        "chart": parse_chart(CHART),
    }
    return Section.model_validate(base | extra)


def bass(line: str) -> BassLine:
    parsed = parse_bar_line(line)
    assert isinstance(parsed, BassLine)
    return parsed


def lead(line: str) -> LeadLine:
    parsed = parse_bar_line(line)
    assert isinstance(parsed, LeadLine)
    return parsed


def parsed_from(dsl: str, section: Section) -> ParsedSection:
    events: list[StreamEvent] = [
        ToolUseStart(id="t", name="write_section"),
        ToolInputDelta(fragment=json.dumps({"dsl": dsl})),
        StreamDone(stop="tool_use"),
    ]
    return parse_section(events, section)


# ------------------------------------------------------------------- the bass, both forms


def test_a_degree_per_slot_carries_the_rhythm_with_it() -> None:
    line = bass("BAS oct=2 deg:1=1,5=5,9=7,13=1")
    assert line.degrees == ((0, 1), (4, 5), (8, 7), (12, 1))
    assert render_positions(line.rhythm) == "1,5,9,13"
    assert line.octave == 2


def test_the_bar_level_form_is_untouched_and_carries_no_map() -> None:
    line = bass("BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x.")
    assert line.degrees == ()
    assert line.degree == 1
    assert render_positions(line.rhythm) == "1,3,5,7,9,11,13,15"


def test_the_map_answers_what_degree_the_bar_is_on() -> None:
    """So anything written against GARAGEM/0.1 still gets an answer from `degree`."""
    assert bass("BAS oct=2 deg:5=5,9=3").degree == 5


def test_saying_where_the_notes_are_twice_is_refused() -> None:
    with pytest.raises(LineError, match="drop rhy:"):
        parse_bar_line("BAS oct=2 deg:1=1,5=5 rhy:x.x.x.x.x.x.x.x.")


# --------------------------------------------------------------------------- the lead line


def test_a_lead_names_a_degree_a_slot_and_what_rings() -> None:
    line = lead("LED oct=4 deg:9=5,11=3,13=1 hold=13")
    assert line.degrees == ((8, 5), (10, 3), (12, 1))
    assert line.holds == (12,)
    assert render_positions(line.rhythm) == "9,11,13"


def test_a_bar_the_lead_sits_out_is_spellable() -> None:
    """Most bars are, and a line left out would shift every bar after it."""
    line = lead("LED oct=4 deg:")
    assert line.degrees == ()
    assert not any(line.rhythm)


def test_a_lead_written_the_bass_s_way_is_refused_by_name() -> None:
    with pytest.raises(LineError, match="deg:1=5 not deg=5"):
        parse_bar_line("LED oct=4 deg=5")


# ------------------------------------------------------------------------- the refusals


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("LED oct=4 deg:0=5", "outside 1..16"),
        ("LED oct=4 deg:17=5", "outside 1..16"),
        ("LED oct=4 deg:9=0", "outside 1..7"),
        ("LED oct=4 deg:9=8", "outside 1..7"),
        ("LED oct=4 deg:9", "is not slot=degree"),
        ("LED oct=4 deg:9=5,9=3", "two degrees"),
        ("LED deg:9=5", "missing oct"),
        ("BAS oct=2 deg:9=9", "outside 1..7"),
    ],
)
def test_what_the_notation_will_not_read(line: str, why: str) -> None:
    with pytest.raises(LineError, match=why):
        parse_bar_line(line)


# ----------------------------------------------------------------------- what it realises


def test_the_bass_moves_inside_the_bar() -> None:
    """The thing GARAGEM/0.1 could not say. `deg=` is one degree for eight attacks."""
    section = a_section(bars=1, chart=parse_chart("| Em |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | Em |\n"
        "DRM K:x.......x.......\n"
        "BAS oct=2 deg:1=1,5=5,9=3,13=5\n"
        "GTR voi=pow rhy:x.......x.......\n"
        "KEY voi=triad rhy:x............... reg=mid\n"
    )
    score = realise(parsed_from(dsl, section), 7, straighten=False)
    pitches = [note.pitch for note in score.part(Instrument.BASS).notes]
    # E, B, G, B in octave 2: root, fifth, third, fifth.
    assert [pitch % 12 for pitch in pitches] == [4, 11, 7, 11]


def test_the_lead_plays_the_degrees_it_names() -> None:
    section = a_section(bars=1, chart=parse_chart("| Em |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | Em |\n"
        "LED oct=4 deg:9=5,11=3,13=1\n"
    )
    score = realise(parsed_from(dsl, section), 7, straighten=False)
    notes = score.part(Instrument.LEAD).notes
    assert [note.pitch % 12 for note in notes] == [11, 7, 4]
    assert validate(score) == ()


def test_a_held_note_rings_to_the_next_attack_and_a_plain_one_does_not() -> None:
    section = a_section(bars=1, chart=parse_chart("| Em |"))
    head = "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\nCHD | Em |\n"
    plain = realise(parsed_from(head + "LED oct=4 deg:1=1,13=5\n", section), 7, straighten=False)
    held = realise(
        parsed_from(head + "LED oct=4 deg:1=1,13=5 hold=1\n", section), 7, straighten=False
    )
    assert plain.part(Instrument.LEAD).notes[0].duration_beats == pytest.approx(0.5)
    assert held.part(Instrument.LEAD).notes[0].duration_beats == pytest.approx(3.0)


# ------------------------------------------------------------------------- straightening


def test_a_shuffle_moves_the_map_onto_the_eighths_and_the_earlier_degree_wins() -> None:
    section = a_section(bars=1, feel=Feel.SHUFFLE, chart=parse_chart("| Em |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=shuffle bpm=132 dyn=4 tension=0.5\n"
        "CHD | Em |\n"
        "BAS oct=2 deg:1=1,4=5,7=3\n"
        "LED oct=4 deg:1=5,2=1,7=3\n"
    )
    straight = straightened(parsed_from(dsl, section))
    bass_line = straight.lines[Instrument.BASS][0]
    lead_line = straight.lines[Instrument.LEAD][0]
    assert isinstance(bass_line, BassLine) and isinstance(lead_line, LeadLine)
    # Nothing merges in the bass: slot 4 is the "a" of beat 1 and moves back onto the
    # "and" before it, slot 3, which was empty. Its degree travels with it.
    assert bass_line.degrees == ((0, 1), (2, 5), (6, 3))
    assert render_positions(bass_line.rhythm) == "1,3,7"
    # The lead does merge: slots 1 and 2 are both the first eighth once straightened, and
    # two attacks that land together are one. The earlier degree is the one that sounds.
    assert lead_line.degrees == ((0, 5), (6, 3))
    assert render_positions(lead_line.rhythm) == "1,7"


# ---------------------------------------------------------------- the live notation stands


def test_the_serializer_writes_garagem_0_1_unless_it_is_asked_for_more() -> None:
    """The one that would break the cassettes, the goldens and the prompt at once."""
    written = serialize_section(play_section(a_section(), 7))
    assert "LED" not in written
    assert "deg:" not in written
    assert "BAS deg=" in written


def test_asked_for_more_it_writes_the_lead_and_a_moving_bass() -> None:
    written = serialize_section(play_section(a_section(), 7), pitched=True)
    assert "LED oct=" in written
    assert "BAS oct=2 deg:" in written


def test_the_pitched_round_trip_keeps_every_pitch_the_bass_played() -> None:
    """Which the bar-level form cannot do, and is the whole reason for the superset."""
    section = a_section(bars=8)
    original = play_section(section, 7)
    back = realise(
        parsed_from(serialize_section(original, pitched=True), section),
        7,
        straighten=False,
    )
    for instrument in (Instrument.BASS, Instrument.LEAD):
        before = {note.pitch % 12 for note in original.part(instrument).notes}
        after = {note.pitch % 12 for note in back.part(instrument).notes}
        assert before == after, instrument
