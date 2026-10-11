"""The second guitar: the rhythm part played again, mirrored around the grid (ADR-028)."""

from __future__ import annotations

from itertools import product

import pytest

from garagem.domain import Feel, Instrument, Section
from garagem.engines import DOUBLE_DYN, completed, double, play_section, with_double
from garagem.theory import parse_chart, validate
from garagem.theory.validator import GRID_TOLERANCE_BEATS, grid_slots, nearest_slot
from garagem.transport.bar_cues import DROPPED, STOP, TRACKS

PROGRESSION = parse_chart("| Em | C | G | D |")


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
        "chart": PROGRESSION,
    }
    return Section.model_validate(base | extra)


CHORUSES = [
    a_section(feel=feel, dyn=dyn, tension=tension)
    for feel, dyn, tension in product(list(Feel), (4, 5), (0.0, 1.0))
]


@pytest.mark.parametrize("dyn", range(1, DOUBLE_DYN))
def test_below_a_chorus_the_second_guitar_is_an_empty_part_not_a_missing_one(dyn: int) -> None:
    """Empty, so the scheduler writes an empty clip over the last chorus's double."""
    score = play_section(a_section(dyn=dyn), 7)
    assert Instrument.GUITAR_DOUBLE in score.instruments()
    assert score.part(Instrument.GUITAR_DOUBLE).notes == ()


@pytest.mark.parametrize("section", CHORUSES, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}")
def test_the_second_guitar_plays_the_first_ones_chords(section: Section) -> None:
    score = play_section(section, 7)
    first = score.part(Instrument.GUITAR).notes
    second = score.part(Instrument.GUITAR_DOUBLE).notes
    assert sorted(note.pitch for note in first) == sorted(note.pitch for note in second)


@pytest.mark.parametrize("section", CHORUSES, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}")
def test_the_second_guitar_is_not_quite_together_with_the_first(section: Section) -> None:
    """Identical MIDI on two tracks is one guitar in the middle, not two guitars apart."""
    score = play_section(section, 7)
    first = {(n.pitch, n.start_beats) for n in score.part(Instrument.GUITAR).notes}
    second = {(n.pitch, n.start_beats) for n in score.part(Instrument.GUITAR_DOUBLE).notes}
    assert first != second


@pytest.mark.parametrize("section", CHORUSES, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}")
def test_every_note_of_the_second_guitar_stays_on_the_grid(section: Section) -> None:
    slots = grid_slots(section)
    notes = play_section(section, 7).part(Instrument.GUITAR_DOUBLE).notes
    assert all(
        abs(note.start_beats - nearest_slot(slots, note.start_beats)) <= GRID_TOLERANCE_BEATS
        for note in notes
    )


@pytest.mark.parametrize("section", CHORUSES, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}")
def test_a_doubled_chorus_is_still_legal(section: Section) -> None:
    assert validate(play_section(section, 7)) == ()


def test_the_double_draws_nothing_so_the_same_guitar_gives_the_same_double() -> None:
    score = play_section(a_section(), 7)
    guitar = score.part(Instrument.GUITAR)
    assert double(guitar, score.section) == double(guitar, score.section)


def test_a_score_is_doubled_once_however_often_it_is_asked() -> None:
    score = play_section(a_section(), 7)
    assert with_double(with_double(score)) == score


def test_a_take_without_a_double_gets_one_made_from_its_own_guitar() -> None:
    """A model's take is doubled exactly as the floor is: from the guitar it has."""
    floor = play_section(a_section(), 7)
    take = floor.model_copy(
        update={
            "parts": tuple(
                part for part in floor.parts if part.instrument is not Instrument.GUITAR_DOUBLE
            )
        }
    )
    assert completed(take).part(Instrument.GUITAR_DOUBLE) == floor.part(Instrument.GUITAR_DOUBLE)


def test_the_second_guitar_stops_and_drops_out_with_the_first() -> None:
    assert Instrument.GUITAR_DOUBLE in TRACKS[STOP]
    assert Instrument.GUITAR_DOUBLE in DROPPED
