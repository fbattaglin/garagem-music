"""The section, the parts and the seed.

Two of these tests are about things the type refuses to be. A `SectionScore` without a
seed cannot exist, because invariant 7 says every generation is reproducible and a score
that cannot name its seed cannot be replayed. A score with two parts for one instrument
cannot exist either, because `part()` would then be a coin toss.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from garagem.domain import (
    BEATS_PER_BAR,
    Chart,
    Chord,
    Feel,
    Instrument,
    Note,
    Part,
    Quality,
    Section,
    SectionScore,
)

E_MINOR = Chart(chords=(Chord(root=4, quality=Quality.MINOR),))


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
        "chart": E_MINOR,
    }
    return Section.model_validate(base | extra)


def a_note(**extra: object) -> Note:
    base: dict[str, object] = {"pitch": 40, "start_beats": 0.0, "duration_beats": 1.0}
    return Note.model_validate(base | extra)


# --------------------------------------------------------------------------------- notes


def test_a_zero_length_note_is_refused() -> None:
    """Not a short note: silence with a velocity, exactly as in `daw.MidiNote`."""
    with pytest.raises(ValidationError):
        a_note(duration_beats=0.0)


def test_velocity_zero_is_refused_because_it_is_a_note_off() -> None:
    with pytest.raises(ValidationError):
        a_note(velocity=0)


@pytest.mark.parametrize("pitch", [-1, 128])
def test_a_pitch_outside_midi_range_is_refused(pitch: int) -> None:
    with pytest.raises(ValidationError):
        a_note(pitch=pitch)


def test_a_note_is_frozen() -> None:
    with pytest.raises(ValidationError):
        a_note().pitch = 41


# --------------------------------------------------------------------------------- parts


def test_a_part_that_plays_nothing_ends_at_zero() -> None:
    assert Part(instrument=Instrument.KEYS).last_beat() == 0.0


def test_last_beat_is_where_the_sound_stops_not_where_it_starts() -> None:
    part = Part(
        instrument=Instrument.BASS,
        notes=(a_note(start_beats=0.0, duration_beats=4.0), a_note(start_beats=3.0)),
    )
    assert part.last_beat() == 4.0


# ------------------------------------------------------------------------------ sections


@pytest.mark.parametrize(("field", "value"), [("bars", 0), ("bars", 33), ("tension", 1.5)])
def test_a_section_outside_its_limits_is_refused(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        a_section(**{field: value})


def test_a_section_lasts_four_beats_a_bar() -> None:
    assert a_section(bars=8).total_beats() == 8 * BEATS_PER_BAR


def test_tempo_becomes_wall_time_only_here() -> None:
    """8 bars at 132 BPM is 14.55 s — the number the deadline rule is computed from."""
    assert a_section(bars=8, bpm=132.0).total_seconds() == pytest.approx(14.5454, abs=1e-4)


# --------------------------------------------------------------------------------- scores


def test_a_score_cannot_exist_without_its_seed() -> None:
    """Invariant 7, made structural: an unreproducible score is not a score."""
    with pytest.raises(ValidationError):
        SectionScore.model_validate({"section": a_section(), "parts": ()})


def test_two_parts_for_one_instrument_are_refused() -> None:
    with pytest.raises(ValidationError, match="one part per instrument"):
        SectionScore(
            section=a_section(),
            parts=(Part(instrument=Instrument.BASS), Part(instrument=Instrument.BASS)),
            seed=7,
        )


def test_a_missing_part_raises_rather_than_returning_none() -> None:
    """A caller that silently renders nothing is an instrument that stopped playing."""
    score = SectionScore(section=a_section(), parts=(Part(instrument=Instrument.BASS),), seed=7)
    with pytest.raises(KeyError, match="no KEY part in this score; it has BAS"):
        score.part(Instrument.KEYS)


def test_a_present_part_comes_back() -> None:
    bass = Part(instrument=Instrument.BASS, notes=(a_note(),))
    score = SectionScore(section=a_section(), parts=(bass,), seed=7)
    assert score.part(Instrument.BASS) is bass
    assert score.instruments() == frozenset({Instrument.BASS})


def test_a_score_is_frozen() -> None:
    score = SectionScore(section=a_section(), parts=(), seed=7)
    with pytest.raises(ValidationError):
        score.seed = 8
