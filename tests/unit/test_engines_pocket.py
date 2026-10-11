"""The pocket: where each player sits against the beat, fixed rather than drawn (ADR-028)."""

from __future__ import annotations

from itertools import pairwise, product

import pytest

from garagem.domain import Feel, Instrument, Note, Part, Section, SectionScore
from garagem.engines import play_section
from garagem.engines.humanise import MAX_TIMING_BEATS
from garagem.engines.pocket import (
    DRUM_LEANS,
    MAX_LEAN_BEATS,
    PART_LEANS,
    STRUM_BEATS,
    lean,
)
from garagem.theory import parse_chart, validate
from garagem.theory.percussion import KICK, SNARE
from garagem.theory.validator import GRID_TOLERANCE_BEATS

PROGRESSION = parse_chart("| Em | C | G | D |")

SECTIONS = [
    Section.model_validate(
        {
            "name": "chorus",
            "bars": 4,
            "key": 4,
            "scale": "minor",
            "feel": feel,
            "bpm": 132.0,
            "dyn": dyn,
            "tension": 0.5,
            "chart": PROGRESSION,
        }
    )
    for feel, dyn in product(list(Feel), (2, 4, 5))
]


def pocketed(score: SectionScore) -> SectionScore:
    parts = tuple(part.model_copy(update={"notes": lean(part)}) for part in score.parts)
    return score.model_copy(update={"parts": parts})


def test_the_room_for_a_lean_is_what_the_grid_leaves_the_humaniser() -> None:
    assert MAX_LEAN_BEATS <= GRID_TOLERANCE_BEATS - MAX_TIMING_BEATS + 1e-9


def test_no_lean_is_wider_than_the_room() -> None:
    widest_strum = 2 * STRUM_BEATS  # three strings: root, fifth, octave
    leans = [*DRUM_LEANS.values(), *PART_LEANS.values(), widest_strum]
    assert all(abs(amount) <= MAX_LEAN_BEATS for amount in leans)


def test_the_backbeat_sits_behind_the_kick() -> None:
    notes = (
        Note(pitch=KICK, start_beats=0.0, duration_beats=0.125, velocity=100),
        Note(pitch=SNARE, start_beats=1.0, duration_beats=0.125, velocity=100),
    )
    moved = lean(Part(instrument=Instrument.DRUMS, notes=notes))
    assert [note.start_beats for note in moved] == [0.0, 1.0 + DRUM_LEANS[SNARE]]


def test_a_downstroke_reaches_the_low_string_first() -> None:
    chord = tuple(
        Note(pitch=pitch, start_beats=at, duration_beats=0.5, velocity=90)
        for pitch, at in ((52, 1.01), (40, 1.012), (47, 1.0))
    )
    moved = lean(Part(instrument=Instrument.GUITAR, notes=chord))
    by_pitch = {note.pitch: note.start_beats for note in moved}
    assert by_pitch[40] < by_pitch[47] < by_pitch[52]
    assert by_pitch[40] == 1.0


@pytest.mark.parametrize("section", SECTIONS, ids=lambda s: f"{s.feel}-{s.dyn}")
def test_a_pocketed_section_is_still_legal(section: Section) -> None:
    """Applied after validation, but it must not take a legal section off the grid."""
    assert validate(pocketed(play_section(section, 7))) == ()


@pytest.mark.parametrize("section", SECTIONS, ids=lambda s: f"{s.feel}-{s.dyn}")
def test_no_pitch_runs_into_itself_after_the_lean(section: Section) -> None:
    for part in pocketed(play_section(section, 7)).parts:
        by_pitch: dict[int, list[Note]] = {}
        for note in part.notes:
            by_pitch.setdefault(note.pitch, []).append(note)
        for notes in by_pitch.values():
            ordered = sorted(notes, key=lambda note: note.start_beats)
            for before, after in pairwise(ordered):
                assert before.start_beats + before.duration_beats <= after.start_beats + 1e-9


def test_the_pocket_draws_nothing_so_it_is_the_same_every_time() -> None:
    score = play_section(SECTIONS[4], 7)
    assert pocketed(score) == pocketed(score)
