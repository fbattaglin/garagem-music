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
    rendered = render_part(part)
    assert rendered == normalised(rendered)
    assert [note.start_beats for note in rendered] == [0.0, 1.0, 2.0]


def test_rendering_is_pure() -> None:
    part = Part(instrument=Instrument.BASS, notes=(a_note(),))
    assert render_part(part) == render_part(part)
    assert part.notes[0].start_beats == 1.0


def test_a_whole_score_renders_to_one_entry_per_instrument() -> None:
    rendered = render_score(play_section(SECTION, 7))
    assert set(rendered) == set(Instrument)
    assert all(notes for notes in rendered.values())


def test_a_score_with_no_parts_renders_to_an_empty_mapping() -> None:
    empty = SectionScore(section=SECTION, parts=(), seed=7)
    assert render_score(empty) == {}


def test_the_offset_reaches_every_part() -> None:
    score = play_section(SECTION, 7)
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
