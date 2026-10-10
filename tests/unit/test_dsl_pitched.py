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
from itertools import pairwise

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
from garagem.theory import RANGES, parse_chart, validate

CHART = "| Em | C | G | D |"
SOLO_CHART = "| Em | D | C | Bm |"


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
        ("LED oct=4 deg:9=0", r"outside 1\.\.14"),
        ("LED oct=4 deg:9=15", r"outside 1\.\.14"),
        ("LED oct=4 deg:9", "is not slot=degree"),
        ("LED oct=4 deg:9=5,9=3", "two degrees"),
        ("LED deg:9=5", "missing oct"),
        ("BAS oct=2 deg:9=99", r"outside 1\.\.14"),
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


# ------------------------------------------------------------------- past the octave


def test_a_degree_may_climb_past_the_octave() -> None:
    """8 is the root an octave up, the way a musician counts. Two paid bakes lost sections
    to `deg:...=8` before the notation allowed it (`phase-6-findings.md` §5, §7)."""
    line = lead("LED oct=4 deg:1=1,5=8,9=13")
    assert line.degrees == ((0, 1), (4, 8), (8, 13))


def test_fifteen_is_still_outside_the_notation() -> None:
    with pytest.raises(LineError, match=r"outside 1\.\.14"):
        parse_bar_line("LED oct=4 deg:1=15")


def test_the_octave_sounds_an_octave_above_the_root() -> None:
    section = a_section(bars=1, chart=parse_chart("| Em |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | Em |\n"
        "LED oct=4 deg:1=1,5=8,9=10\n"
    )
    notes = realise(parsed_from(dsl, section), 7, straighten=False).part(Instrument.LEAD).notes
    root, octave, tenth = (note.pitch for note in notes)
    assert octave == root + 12
    # Degree 10 is degree 3 an octave up: a third above the octave.
    assert tenth > octave
    assert (tenth - root) % 12 == (tenth - octave) % 12


def test_a_bass_riff_may_reach_the_octave_too() -> None:
    section = a_section(bars=1, chart=parse_chart("| Em |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | Em |\n"
        "BAS oct=2 deg:1=1,9=8\n"
    )
    notes = realise(parsed_from(dsl, section), 7, straighten=False).part(Instrument.BASS).notes
    assert notes[1].pitch % 12 == notes[0].pitch % 12


# ------------------------------------------------- a bar that does not fit the instrument


def test_a_bar_that_runs_past_the_ceiling_moves_whole_and_keeps_its_shape() -> None:
    """Found by the first paid solo probe, and it cost one note (`phase-7-findings.md` §4).

    The model wrote `… 8, 9, 8 …` over a `Bm`, whose ninth is MIDI 85 — **one semitone** above
    the lead's ceiling of 84. The realiser folded that note alone, an octave down, and left a
    ten-semitone hole in a run of sixteenths. Nothing refused it: the pitch class is still the
    one that was written, so no rule was broken.

    A bodily octave keeps every interval in the bar; folding one note destroys two. Same call
    `engines/lead._in_range` makes for the floor.
    """
    section = a_section(bars=1, chart=parse_chart("| Bm |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | Bm |\n"
        "LED oct=4 deg:1=1,3=3,5=5,7=8,9=9,11=8,13=5,15=1\n"
    )
    notes = realise(parsed_from(dsl, section), 7, straighten=False).part(Instrument.LEAD).notes
    pitches = [note.pitch for note in notes]

    wanted = [71, 74, 78, 83, 85, 83, 78, 71]
    steps = [b - a for a, b in pairwise(wanted)]
    assert [b - a for a, b in pairwise(pitches)] == steps
    low, high = RANGES[Instrument.LEAD]
    assert all(low <= pitch <= high for pitch in pitches)
    assert pitches == [pitch - 12 for pitch in wanted]


def test_a_bar_wider_than_the_instrument_still_folds_note_by_note() -> None:
    """No octave holds a line wider than the range, so the contour has to give — but only
    there, and the notes that fit are left where they were written."""
    section = a_section(bars=1, chart=parse_chart("| Em |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | Em |\n"
        "LED oct=2 deg:1=1,9=14\n"
    )
    notes = realise(parsed_from(dsl, section), 7, straighten=False).part(Instrument.LEAD).notes
    low, high = RANGES[Instrument.LEAD]
    assert all(low <= note.pitch <= high for note in notes)


def test_a_bar_already_inside_the_range_is_left_exactly_where_it_was() -> None:
    """The fix must not move anything that fitted: every golden file depends on it."""
    section = a_section(bars=1, chart=parse_chart("| Em |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | Em |\n"
        "LED oct=4 deg:1=1,5=3,9=5\n"
    )
    notes = realise(parsed_from(dsl, section), 7, straighten=False).part(Instrument.LEAD).notes
    assert [note.pitch for note in notes] == [64, 67, 71]


# ----------------------------------------------------------------- rel=key, the solo's spelling


def test_rel_defaults_to_the_chord_and_every_take_on_disk_keeps_its_meaning() -> None:
    """The one property that matters most about an additive spelling."""
    assert lead("LED oct=4 deg:1=1,5=3").relative == "chord"
    assert lead("LED oct=4 rel=chord deg:1=1,5=3").relative == "chord"
    assert lead("LED oct=4 rel=key deg:1=1,5=3").relative == "key"


@pytest.mark.parametrize("spelling", ["scale", "Key", "", "bar"])
def test_what_rel_will_not_read(spelling: str) -> None:
    with pytest.raises(LineError, match="rel is chord, key"):
        parse_bar_line(f"LED oct=4 rel={spelling} deg:1=1")


def test_a_degree_of_the_key_does_not_move_when_the_chord_does() -> None:
    """**Why `rel=key` exists** (ADR-027, `phase-7-findings.md` §4). Under `rel=chord` degree 1
    of `Em` and degree 1 of `C` are a seventh apart at the same `oct=`, which is right for a
    figure inside a bar and wrong for a line crossing one. Under `rel=key` the same degree is
    the same note in every bar, whatever is underneath it."""
    section = a_section(bars=2, chart=parse_chart("| Em | C |"))
    head = "SEC chorus bars=2 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\nCHD | Em | C |\n"

    chordal = realise(
        parsed_from(head + "LED oct=4 deg:1=1\nLED oct=4 deg:1=1\n", section), 7, straighten=False
    )
    keyed = realise(
        parsed_from(head + "LED oct=4 rel=key deg:1=1\nLED oct=4 rel=key deg:1=1\n", section),
        7,
        straighten=False,
    )
    first, second = (note.pitch for note in chordal.part(Instrument.LEAD).notes)
    assert second - first == -4, "degree 1 of C sits a third below degree 1 of Em"
    same = [note.pitch for note in keyed.part(Instrument.LEAD).notes]
    assert same[0] == same[1], "a degree of the key is one note"


def test_a_degree_of_the_key_climbs_the_scale_and_not_the_chord() -> None:
    """E minor from E: E F# G A B C D. Degree 3 is G whatever chord is sounding, where degree 3
    of a `C` chord is E — the chord's third, from the chord's own scale."""
    section = a_section(bars=1, chart=parse_chart("| C |"))
    dsl = (
        "SEC chorus bars=1 key=Em feel=straight8 bpm=132 dyn=4 tension=0.5\n"
        "CHD | C |\n"
        "LED oct=4 rel=key deg:1=1,5=3,9=8\n"
    )
    notes = realise(parsed_from(dsl, section), 7, straighten=False).part(Instrument.LEAD).notes
    tonic, third, octave = (note.pitch for note in notes)
    assert tonic % 12 == 4, "E"
    assert third % 12 == 7, "G, the key's third — not the chord's"
    assert octave == tonic + 12


def test_the_pitched_round_trip_keeps_every_lead_pitch_of_a_solo() -> None:
    """The measurement `scripts/probe_solo.py` reports, as a test: **0 of 43 notes move.**

    Before `rel=key` this was 5 of 43, four of them out of the key, and the validator let it
    through because a solo's dissonance budget is far wider than that.
    """
    section = a_section(name="solo", bars=8, dyn=3, tension=0.65, chart=parse_chart(SOLO_CHART))
    floor = play_section(section, 7)
    again = realise(parsed_from(serialize_section(floor, pitched=True), section), 7)
    before = [note.pitch for note in floor.part(Instrument.LEAD).notes]
    after = [note.pitch for note in again.part(Instrument.LEAD).notes]
    assert after == before
    assert validate(again) == ()
