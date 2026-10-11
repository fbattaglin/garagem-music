"""Domain notes to Live notes, and the bar offset that makes a score portable.

The output goes through `daw.normalised` on purpose, and the test says why: a rendered
part and a part read back out of Live must compare equal without a tolerance argument,
which is how the Phase 1 idempotence criterion is stated.
"""

from __future__ import annotations

import pytest

from garagem.daw import MidiNote, normalised
from garagem.domain import (
    BEATS_PER_BAR,
    Feel,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
)
from garagem.engines import play_section
from garagem.engines.pocket import PART_LEANS
from garagem.theory import parse_chart
from garagem.transport import render_note, render_part, render_score

SECTION = Section(
    name="verse",
    bars=4,
    key=4,
    scale="minor",
    feel=Feel.STRAIGHT8,
    bpm=132.0,
    dyn=3,
    tension=0.4,
    chart=parse_chart("| Em | C | G | D |"),
)

# The lead rests below `dyn` 4 (`engines/lead.py`), so a verse is the wrong briefing for
# any test whose point is that every voice sounds. A chorus is one where all five do.
CHORUS = SECTION.model_copy(update={"name": "chorus", "dyn": 4, "tension": 0.7})


def a_note(**extra: object) -> Note:
    base: dict[str, object] = {"pitch": 40, "start_beats": 1.0, "duration_beats": 0.5}
    return Note.model_validate(base | extra)


def test_a_note_keeps_its_pitch_its_place_and_its_velocity() -> None:
    rendered = render_note(a_note(velocity=93))
    assert rendered == MidiNote(pitch=40, start_beats=1.0, duration_beats=0.5, velocity=93)


def test_a_bar_offset_shifts_by_four_beats_a_bar() -> None:
    assert render_note(a_note(), bar_offset=2).start_beats == 1.0 + 2 * BEATS_PER_BAR


def test_an_empty_part_renders_to_nothing_rather_than_to_one_note() -> None:
    assert render_part(Part(instrument=Instrument.KEYS)) == ()


def test_a_rendered_part_is_normalised() -> None:
    """So it compares equal to what Live gives back, with no tolerance argument."""
    part = Part(
        instrument=Instrument.BASS,
        notes=(a_note(start_beats=2.0), a_note(start_beats=0.0), a_note(start_beats=1.0)),
    )
    rendered = render_part(part, pocket=False)
    assert rendered == normalised(rendered)
    assert [note.start_beats for note in rendered] == [0.0, 1.0, 2.0]


def test_the_pocket_is_applied_on_the_way_out_and_can_be_switched_off() -> None:
    """The bass sits just behind the beat in Live; the score never knows (ADR-028)."""
    part = Part(instrument=Instrument.BASS, notes=(a_note(start_beats=1.0),))
    assert render_part(part)[0].start_beats == 1.0 + PART_LEANS[Instrument.BASS]
    assert render_part(part, pocket=False)[0].start_beats == 1.0


def test_rendering_is_pure() -> None:
    part = Part(instrument=Instrument.BASS, notes=(a_note(),))
    assert render_part(part) == render_part(part)
    assert part.notes[0].start_beats == 1.0


def test_a_whole_score_renders_to_one_entry_per_instrument() -> None:
    rendered = render_score(play_section(CHORUS, 7))
    assert set(rendered) == set(Instrument)
    assert all(notes for notes in rendered.values())


def test_a_score_with_no_parts_renders_to_an_empty_mapping() -> None:
    empty = SectionScore(section=SECTION, parts=(), seed=7)
    assert render_score(empty) == {}


def test_the_offset_reaches_every_part() -> None:
    score = play_section(CHORUS, 7)
    at_zero = render_score(score)
    shifted = render_score(score, bar_offset=1)
    for instrument, notes in at_zero.items():
        assert shifted[instrument][0].start_beats == pytest.approx(
            notes[0].start_beats + BEATS_PER_BAR
        )


def test_every_rendered_note_is_a_legal_midi_note() -> None:
    """Both types refuse a zero-length note and a velocity of 0, for the same reasons."""
    rendered = render_score(play_section(SECTION, 7))
    for notes in rendered.values():
        assert all(1 <= note.velocity <= 127 for note in notes)
        assert all(note.duration_beats > 0.0 for note in notes)


# -------------------------------------------------------- what this Set answers to (ADR-025)


def test_a_pitch_this_set_keeps_elsewhere_is_sent_where_the_kit_keeps_it() -> None:
    """`session.toml`'s `pitches`: the band writes its own vocabulary, the Set gets the kit's."""
    assert render_note(a_note(pitch=50), pitches={50: 47}).pitch == 47
    assert render_note(a_note(pitch=38), pitches={50: 47}).pitch == 38


def test_a_pitch_moves_once_and_never_down_a_chain() -> None:
    """The Dry Session Kit's toms move 50 to 47 and 47 to 45. A 50 must not land on 45."""
    moved = {50: 47, 47: 45, 45: 43, 43: 41}
    part = Part(
        instrument=Instrument.DRUMS,
        notes=tuple(
            a_note(pitch=pitch, start_beats=index * 0.25)
            for index, pitch in enumerate((50, 47, 45, 43))
        ),
    )
    assert [note.pitch for note in render_part(part, pitches=moved)] == [47, 45, 43, 41]


def test_only_the_instrument_it_is_declared_for_is_moved() -> None:
    score = play_section(SECTION, seed=7)
    rendered = render_score(score, pitches={Instrument.DRUMS: {50: 47}})
    plain = render_score(score)
    assert rendered[Instrument.BASS] == plain[Instrument.BASS]
    assert all(note.pitch != 50 for note in rendered[Instrument.DRUMS])


def test_a_palm_mute_stays_under_the_split_and_a_ringing_chord_over_it() -> None:
    """A sampler that picks its articulation by velocity must never get the other one."""
    loud_chug = Note(pitch=40, start_beats=0.0, duration_beats=0.12, velocity=90)
    quiet_strum = Note(pitch=40, start_beats=1.0, duration_beats=0.5, velocity=50)
    part = Part(instrument=Instrument.GUITAR, notes=(loud_chug, quiet_strum))
    rendered = render_part(part, pocket=False, palm_below=72)
    assert [note.velocity for note in rendered] == [71, 72]


def test_without_a_split_the_velocities_are_the_band_s_own() -> None:
    note = Note(pitch=40, start_beats=0.0, duration_beats=0.12, velocity=90)
    part = Part(instrument=Instrument.GUITAR, notes=(note,))
    assert render_part(part, pocket=False)[0].velocity == 90
