"""Scales, degrees and the one primitive the repairer moves notes with.

Everything here is arithmetic on pitch classes and MIDI numbers. No note names: those
are `theory/chords.py`'s problem, and keeping the split means this module never has to
decide between F# and Gb.

**Octave numbering.** MIDI middle C is 60 and is C4, so `pitch_of(c, octave)` is
`(octave + 1) * 12 + c`. That is not a convention this file invented — it is the one the
DSL skill's own instrument ranges are written in, and all three of them agree with it:
bass E1-G3 is 28-55, guitar E2-E5 is 40-76, keys C2-C6 is 36-84. Three independent
pairs landing exactly on those numbers is what makes it a fact rather than a guess.

**A degree is relative to the chord, not to the key.** The DSL says so outright: `deg`
is "a scale degree (1-7) relative to the current chord, not an absolute note". So degree
1 of C is C and degree 1 of Em is E. Degrees 3, 5 and 7 land on the chord's own tones;
2, 4 and 6 are not in any triad, so they come from the scale the chord implies —
mixolydian under a dominant seventh, dorian under a minor seventh, and so on. That table
is `CHORD_SCALES`, and it is the whole reason `degree_to_pitch` needs no scale argument.
"""

from __future__ import annotations

from typing import Final

from garagem.domain import PITCH_CLASSES, Chord, Quality
from garagem.theory.errors import TheoryError, UnknownScaleError

SEMITONES_PER_OCTAVE: Final = PITCH_CLASSES
MIDI_MIN: Final = 0
MIDI_MAX: Final = 127
DEGREES: Final = 7

SCALES: Final[dict[str, tuple[int, ...]]] = {
    "major": (0, 2, 4, 5, 7, 9, 11),
    "minor": (0, 2, 3, 5, 7, 8, 10),  # natural minor
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),  # rock's other home
    # Locrian is here for one reason: every `Quality` needs a scale its degrees can come
    # from, and the diminished chord has no other. Rock does not play in it.
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "pentatonic_minor": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
}

# Which scale a chord's degrees are counted in. Seven-note scales only: a degree beyond
# the fifth has to land somewhere, and a pentatonic has no fourth to land on.
CHORD_SCALES: Final[dict[Quality, str]] = {
    Quality.MAJOR: "major",
    Quality.MAJ7: "major",
    Quality.SUS2: "major",
    Quality.MINOR: "minor",
    Quality.MIN7: "dorian",
    Quality.DOM7: "mixolydian",
    Quality.SUS4: "mixolydian",
    Quality.DIM: "locrian",
    # No third, so nothing to contradict: mixolydian is the safe reading of a power
    # chord, and the flat seventh is what a rock riff reaches for anyway.
    Quality.POWER: "mixolydian",
}


def steps_of(scale: str) -> tuple[int, ...]:
    """The scale's semitone steps above its root."""
    try:
        return SCALES[scale]
    except KeyError:
        known = ", ".join(sorted(SCALES))
        raise UnknownScaleError(f"unknown scale {scale!r}; known scales are {known}") from None


def pitch_classes(key: int, scale: str) -> frozenset[int]:
    """The pitch classes of `scale` rooted on `key`. What "in the scale" means."""
    return frozenset((key + step) % SEMITONES_PER_OCTAVE for step in steps_of(scale))


def pitch_of(pitch_class: int, octave: int) -> int:
    """The MIDI pitch for a pitch class in an octave. C4 is 60."""
    pitch = (octave + 1) * SEMITONES_PER_OCTAVE + pitch_class
    if not MIDI_MIN <= pitch <= MIDI_MAX:
        raise TheoryError(f"pitch class {pitch_class} in octave {octave} is {pitch}, outside MIDI")
    return pitch


def degree_to_pitch(chord: Chord, degree: int, octave: int) -> int:
    """Degree `1..DEGREES` of `chord`, as an absolute MIDI pitch in `octave`.

    Relative to the chord: degree 1 of Em is E, degree 3 is G, degree 5 is B. Degrees
    that are not chord tones come from the chord's implied scale (`CHORD_SCALES`).

    The octave is the octave of the *root*, and a degree that rises past B stays in the
    same octave number rather than jumping — degree 7 of C2 is B2, one semitone below
    C3, which is what a musician counting degrees means.
    """
    if not 1 <= degree <= DEGREES:
        raise TheoryError(f"a degree is 1..{DEGREES}, got {degree}")
    step = steps_of(CHORD_SCALES[chord.quality])[degree - 1]
    return pitch_of(chord.root, octave) + step


def nearest_in(pitch: int, allowed: frozenset[int], *, prefer_down: bool = True) -> int:
    """The closest MIDI pitch to `pitch` whose pitch class is in `allowed`.

    The repairer's primitive: an off-scale note is moved, never deleted. Ties go down by
    default because a note pulled downwards keeps the melodic line under its ceiling,
    and a repairer that resolved ties by coin toss would break the golden tests.

    Idempotent: a pitch already legal comes back untouched, which is what makes
    `repair(repair(x)) == repair(x)` provable rather than hoped for.
    """
    if not allowed:
        raise TheoryError("nearest_in needs at least one allowed pitch class")

    first, second = (-1, 1) if prefer_down else (1, -1)
    for distance in range(SEMITONES_PER_OCTAVE + 1):
        for direction in (0,) if distance == 0 else (first, second):
            candidate = pitch + direction * distance
            if MIDI_MIN <= candidate <= MIDI_MAX and candidate % SEMITONES_PER_OCTAVE in allowed:
                return candidate
    raise TheoryError(f"no pitch class of {sorted(allowed)} is reachable from {pitch}")
