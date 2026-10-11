"""The organist: out of the verse, a pad under the bridge, chords held under the chorus.

ADR-028 made the keys an organ, and an organ in a rock band does one thing: it holds the
chord underneath the guitars, where it thickens the band without competing with it. So this
engine has no stabs any more. The piano's quarter-note triads in a chorus sat in the same
octave as the guitar's and turned both into mud.

**The organ follows the arrangement in and out.** Below `ORGAN_DYN` it rests: an indie verse
is guitar, bass and drums. A bridge or a solo gets an open sus2 pad, and a chorus gets the full
chord, held across the bar. The density knob moves `dyn`, so it brings the organ in and out too.

**It sits above the guitar, not merely above the bass.** `ORGAN_FLOOR` is one semitone over the
highest note of the guitar's power chords (`theory.POWER_ROOTS`), so the two never share an
octave, and the voicing is led from chord to chord inside that window. Voice leading is right
for an organ, whose hand stays in one place, and wrong for a guitar, whose hand slides.
"""

from __future__ import annotations

from random import Random
from typing import Final

from garagem.domain import (
    BEATS_PER_BAR,
    PITCH_CLASSES,
    SIXTEENTHS_PER_BAR,
    Chord,
    Instrument,
    Note,
    Part,
    Quality,
    Section,
    beats_of,
)
from garagem.engines.humanise import humanise, separate
from garagem.theory.scales import SEMITONES_PER_OCTAVE, pitch_classes
from garagem.theory.voicings import (
    POWER_ROOTS,
    RANGES,
    Register,
    fit_to_range,
    voice,
    voice_lead,
)

# Above the bass's top note, so the two never share an octave. The organ's own floor is
# higher still; this is the rule every keys part keeps, the floor's and a model's alike.
KEYS_FLOOR = RANGES[Instrument.BASS][1] + 1
KEYS_CEILING = RANGES[Instrument.KEYS][1]

# Above the guitar's highest power-chord note: root on D#3, its octave on D#4 (ADR-028).
ORGAN_FLOOR: Final = POWER_ROOTS[1] + SEMITONES_PER_OCTAVE + 1

# Below this the organ rests. At this the section breathes and gets a pad; from
# `FULL_DYN` it is a chorus and gets the whole chord.
ORGAN_DYN: Final = 3
FULL_DYN: Final = 4

BASE_VELOCITY = 44
DYN_VELOCITY = 11


def play(section: Section, rng: Random) -> Part:
    """One organ part for the whole section."""
    if section.dyn < ORGAN_DYN:
        return Part(instrument=Instrument.KEYS, notes=())
    full = section.dyn >= FULL_DYN
    velocity = min(127, max(1, BASE_VELOCITY + DYN_VELOCITY * section.dyn))

    notes: list[Note] = []
    previous: tuple[int, ...] = ()
    consonant = _consonant_pitch_classes(section)
    for bar in range(section.bars):
        chord = section.chart.at(bar)
        style = _style_for(chord, full=full, consonant=consonant)
        shape = _in_the_window(voice(chord, style, Register.HIGH))
        shape = _in_the_window(voice_lead(previous, shape))
        previous = shape
        at = beats_of(bar * SIXTEENTHS_PER_BAR, section.feel)
        notes.extend(
            Note(pitch=pitch, start_beats=at, duration_beats=BEATS_PER_BAR, velocity=velocity)
            for pitch in shape
        )

    return Part(instrument=Instrument.KEYS, notes=separate(humanise(notes, rng, feel=section.feel)))


def _consonant_pitch_classes(section: Section) -> frozenset[int]:
    """The section's scale plus every chord tone in its chart."""
    return pitch_classes(section.key, section.scale).union(
        *(chord.pitch_classes() for chord in section.chart.chords)
    )


def _style_for(chord: Chord, *, full: bool, consonant: frozenset[int]) -> str:
    """A sus2 pad, unless its added second falls outside the section; a chorus's triad.

    A chart is allowed to disagree with its key — `| Em |` under a C briefing is a legal
    request. The added second of a sus2 is not a chord tone, so under such a chart it can
    land outside both the key and the chart, and a pad that breaks the dissonance budget on
    its own would make the deterministic floor depend on the repairer. A triad is always
    inside the chord.
    """
    if full:
        return "triad"
    added = {
        (chord.root + step) % PITCH_CLASSES
        for step in Chord(root=0, quality=Quality.SUS2).intervals()
    }
    return "sus2" if added <= consonant else "triad"


def _in_the_window(pitches: tuple[int, ...]) -> tuple[int, ...]:
    """Octave-shift the whole voicing until it clears the guitar, inside the keys' range."""
    fitted = fit_to_range(pitches, Instrument.KEYS)
    while fitted and fitted[0] < ORGAN_FLOOR and fitted[-1] + SEMITONES_PER_OCTAVE <= KEYS_CEILING:
        fitted = tuple(pitch + SEMITONES_PER_OCTAVE for pitch in fitted)
    return fitted
