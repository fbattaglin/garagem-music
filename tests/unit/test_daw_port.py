"""The DAW port's value objects: what a note may be, and what equality means.

`MidiNote` is the last place a nonsensical note can be stopped before it reaches Live,
where it becomes silence rather than an error. `normalised` is what makes the Phase 1
idempotence criterion statable: written notes and read-back notes compare equal without
a tolerance argument at every call site.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from garagem.daw import (
    QUANTIZATION_BY_CODE,
    QUANTIZATION_CODES,
    ClipAddress,
    MidiNote,
    Quantization,
    normalised,
)


def a_note(**extra: object) -> MidiNote:
    base: dict[str, object] = {"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0}
    return MidiNote.model_validate(base | extra)


# ------------------------------------------------------------------- what a note may be


@pytest.mark.parametrize("pitch", [-1, 128])
def test_a_pitch_outside_midi_range_is_refused(pitch: int) -> None:
    with pytest.raises(ValidationError):
        a_note(pitch=pitch)


def test_a_zero_length_note_is_refused() -> None:
    """Not a short note: silence with a velocity, which Live would store happily."""
    with pytest.raises(ValidationError):
        a_note(duration_beats=0.0)


def test_velocity_zero_is_refused_because_it_is_a_note_off() -> None:
    with pytest.raises(ValidationError):
        a_note(velocity=0)


def test_a_note_is_frozen_and_hashable() -> None:
    note = a_note()
    with pytest.raises(ValidationError):
        note.pitch = 61
    assert {note, a_note()} == {note}


def test_a_clip_address_refuses_a_negative_index() -> None:
    with pytest.raises(ValidationError):
        ClipAddress(track=-1, scene=0)


# ------------------------------------------------------------------------- normalised


def test_normalising_sorts_by_start_then_pitch() -> None:
    scrambled = [
        a_note(pitch=67, start_beats=4.0),
        a_note(pitch=64, start_beats=0.0),
        a_note(pitch=60, start_beats=0.0),
    ]
    assert [n.pitch for n in normalised(scrambled)] == [60, 64, 67]


def test_normalising_rounds_away_the_float_noise_live_returns() -> None:
    written = a_note(start_beats=1.0, duration_beats=2.0)
    read_back = a_note(start_beats=0.9999999999, duration_beats=2.0000000001)
    assert normalised([read_back]) == normalised([written])


def test_normalising_twice_changes_nothing() -> None:
    once = normalised([a_note(pitch=64, start_beats=1.5), a_note(start_beats=0.25)])
    assert normalised(once) == once


# --------------------------------------------------------------------------- the wire


@pytest.mark.parametrize("quantization", list(Quantization))
def test_every_quantisation_round_trips_through_its_wire_code(
    quantization: Quantization,
) -> None:
    code = QUANTIZATION_CODES[quantization]
    assert QUANTIZATION_BY_CODE[code] is quantization
