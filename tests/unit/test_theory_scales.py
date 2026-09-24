"""Scales, degrees and `nearest_in`.

Two of these tests exist to pin down numbers the rest of the system quietly assumes.
The octave test checks the three instrument ranges the DSL skill states, because if
`pitch_of` were off by twelve every engine would be an octave wrong and every test would
still pass. And `nearest_in`'s tie-breaking is asserted rather than left to chance: the
golden tests depend on it resolving the same way every time.
"""

from __future__ import annotations

import re

import pytest

from garagem.domain import Chord, Quality
from garagem.theory import (
    CHORD_SCALES,
    DEGREES,
    SCALES,
    TheoryError,
    UnknownScaleError,
    degree_to_pitch,
    nearest_in,
    pitch_classes,
    pitch_of,
    scale_pitch,
    steps_of,
)

E = 4
C = 0

EM = Chord(root=E, quality=Quality.MINOR)
C_MAJ = Chord(root=C, quality=Quality.MAJOR)


# -------------------------------------------------------------------------------- scales


def test_e_minor_has_the_pitch_classes_a_guitarist_would_name() -> None:
    """E F# G A B C D — the key the Phase 1 progression is in."""
    assert pitch_classes(E, "minor") == frozenset({4, 6, 7, 9, 11, 0, 2})


@pytest.mark.parametrize("scale", sorted(SCALES))
def test_every_scale_starts_at_zero_and_ascends(scale: str) -> None:
    steps = steps_of(scale)
    assert steps[0] == 0
    assert list(steps) == sorted(steps)
    assert len(set(steps)) == len(steps)
    assert steps[-1] < 12


def test_an_unknown_scale_names_the_ones_that_exist() -> None:
    """The caller is usually a person who guessed a name."""
    with pytest.raises(UnknownScaleError, match="mixolydian"):
        pitch_classes(C, "phrygian")


@pytest.mark.parametrize("quality", list(Quality))
def test_every_chord_quality_has_a_seven_note_degree_scale(quality: Quality) -> None:
    """A degree beyond the fifth has to land somewhere, for every chord we can build."""
    assert len(steps_of(CHORD_SCALES[quality])) == DEGREES


# ------------------------------------------------------------------------------- octaves


@pytest.mark.parametrize(
    ("pitch_class", "octave", "expected"),
    [
        (C, 4, 60),  # middle C
        (E, 1, 28),  # bass low E, the bottom of the DSL's BAS range
        (7, 3, 55),  # G3, the top of it
        (E, 2, 40),  # guitar low E
        (E, 5, 76),  # the top of the GTR range
        (C, 2, 36),  # the bottom of KEY
        (C, 6, 84),  # the top of it
    ],
)
def test_octave_numbering_agrees_with_the_dsl_instrument_ranges(
    pitch_class: int, octave: int, expected: int
) -> None:
    assert pitch_of(pitch_class, octave) == expected


def test_a_pitch_outside_midi_is_refused_rather_than_wrapped() -> None:
    with pytest.raises(TheoryError, match="outside MIDI"):
        pitch_of(C, 10)


# ------------------------------------------------------------------------------- degrees


def test_degree_one_of_e_minor_is_e() -> None:
    assert degree_to_pitch(EM, 1, octave=2) == 40


def test_degree_five_of_c_is_g() -> None:
    assert degree_to_pitch(C_MAJ, 5, octave=4) == 67


def test_degree_three_follows_the_chord_not_the_key() -> None:
    """Degree 3 of Em is G; of E major it is G#. Same root, different chord."""
    assert degree_to_pitch(EM, 3, octave=2) == 43
    assert degree_to_pitch(Chord(root=E, quality=Quality.MAJOR), 3, octave=2) == 44


def test_a_degree_that_is_not_a_chord_tone_comes_from_the_implied_scale() -> None:
    """Degree 7 of a dominant chord is flat — that is what makes it dominant."""
    assert degree_to_pitch(Chord(root=C, quality=Quality.DOM7), 7, octave=4) == 70
    assert degree_to_pitch(Chord(root=C, quality=Quality.MAJ7), 7, octave=4) == 71


@pytest.mark.parametrize("degree", [0, 8, -1])
def test_a_degree_outside_one_to_seven_is_refused(degree: int) -> None:
    with pytest.raises(TheoryError, match=re.escape("a degree is 1..7")):
        degree_to_pitch(EM, degree, octave=2)


# ------------------------------------------------------------------------- scale_pitch


def test_a_step_counts_up_the_key_and_not_up_a_chord() -> None:
    """What the solo needs and `degree_to_pitch` cannot give it: one line through the key,
    whatever chord the bar happens to be on (`engines/lead.py`)."""
    assert scale_pitch(C, "major", 0, 4) == 60
    assert scale_pitch(C, "major", 2, 4) == 64
    assert scale_pitch(C, "minor", 2, 4) == 63


def test_a_step_past_the_scale_takes_the_octave_with_it() -> None:
    """Which is what lets a melodic line be one arithmetic sequence rather than a pile of
    octave cases."""
    assert scale_pitch(C, "major", 7, 4) == 72
    assert scale_pitch(C, "major", 8, 4) == 74
    assert scale_pitch(C, "major", 14, 4) == 84


def test_a_negative_step_goes_down_the_scale() -> None:
    assert scale_pitch(C, "major", -1, 4) == 59
    assert scale_pitch(C, "major", -7, 4) == 48


def test_a_step_counts_entries_so_a_pentatonic_works_too() -> None:
    """Five to the octave, not seven: `degree_to_pitch` refuses these scales and this one
    does not have to, because nothing here asks for a fourth to land on."""
    assert scale_pitch(C, "pentatonic_minor", 5, 4) == 72
    assert scale_pitch(C, "pentatonic_minor", 1, 4) == 63


def test_a_step_is_always_a_note_of_its_scale() -> None:
    for scale in SCALES:
        allowed = pitch_classes(C, scale)
        for step in range(-14, 15):
            assert scale_pitch(C, scale, step, 4) % 12 in allowed, (scale, step)


# ---------------------------------------------------------------------------- nearest_in


def test_a_pitch_already_in_the_scale_comes_back_untouched() -> None:
    """Idempotence, which is what `repair(repair(x)) == repair(x)` rests on."""
    allowed = pitch_classes(E, "minor")
    assert nearest_in(40, allowed) == 40


def test_a_tie_goes_down_by_default_and_up_when_asked() -> None:
    """C# is one semitone from both C and D in a C major scale."""
    allowed = pitch_classes(C, "major")
    assert nearest_in(61, allowed) == 60
    assert nearest_in(61, allowed, prefer_down=False) == 62


def test_the_nearest_pitch_keeps_its_own_octave() -> None:
    allowed = pitch_classes(C, "major")
    assert nearest_in(73, allowed) == 72


def test_nearest_in_stays_inside_midi_at_the_bottom() -> None:
    """Pitch 0 with nothing legal below it must go up rather than off the end."""
    assert nearest_in(0, frozenset({11})) == 11


def test_nearest_in_needs_something_to_aim_at() -> None:
    with pytest.raises(TheoryError, match="at least one allowed"):
        nearest_in(60, frozenset())
