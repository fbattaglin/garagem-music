"""The keyboard player: pads when the section breathes, stabs when it pushes.

**Keys never play below the bass's ceiling.** The DSL's ranges overlap — bass reaches
G3 (55) and keys start at C2 (36) — and two instruments in the same octave turn into
mud rather than into harmony. So this engine fits its voicings into a narrowed window
that starts one semitone above the top of the bass's range. The rule holds without the
engine ever seeing the bass part, which matters: `play` takes a briefing, not the rest
of the band, and an engine that needed its neighbours' output could not be generated in
parallel or replaced by a model in Phase 3.

Duration is the whole difference between a pad and a stab, and it comes from `dyn`: a
low-dynamic section gets chords that span the bar, a high-dynamic one gets chords that
punch and stop.
"""

from __future__ import annotations

from random import Random

from garagem.domain import (
    BEATS_PER_BAR,
    PITCH_CLASSES,
    SIXTEENTHS_PER_BAR,
    Chord,
    Feel,
    Instrument,
    Note,
    Part,
    Quality,
    Section,
    beats_of,
)
from garagem.engines.humanise import humanise, separate
from garagem.theory.scales import pitch_classes
from garagem.theory.voicings import RANGES, Register, fit_to_range, voice, voice_lead

# Above the bass's top note, so the two never share an octave.
KEYS_FLOOR = RANGES[Instrument.BASS][1] + 1
KEYS_CEILING = RANGES[Instrument.KEYS][1]

# At or above this the part stops sustaining and starts punctuating.
STAB_DYN = 4
STAB_BEATS = 0.4

STAB_RHYTHMS: dict[Feel, str] = {
    Feel.STRAIGHT8: "x...x...x...x...",
    Feel.STRAIGHT16: "x..x..x...x..x..",
    Feel.SHUFFLE: "x...x...x...x...",
    Feel.HALFTIME: "x.......x.......",
}

BASE_VELOCITY = 44
DYN_VELOCITY = 11


def play(section: Section, rng: Random) -> Part:
    """One keys part for the whole section."""
    stabbing = section.dyn >= STAB_DYN
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn
    rhythm = STAB_RHYTHMS[section.feel] if stabbing else "x" + "." * (SIXTEENTHS_PER_BAR - 1)

    notes: list[Note] = []
    previous: tuple[int, ...] = ()
    consonant = _consonant_pitch_classes(section)
    for bar in range(section.bars):
        chord = section.chart.at(bar)
        style = _style_for(chord, stabbing=stabbing, consonant=consonant)
        shape = _above_the_bass(voice(chord, style, Register.HIGH))
        shape = _above_the_bass(voice_lead(previous, shape))
        previous = shape
        offset = bar * SIXTEENTHS_PER_BAR

        for slot, mark in enumerate(rhythm):
            if mark != "x":
                continue
            at = beats_of(offset + slot, section.feel)
            # A pad holds until the next bar; a stab does not.
            length = STAB_BEATS if stabbing else BEATS_PER_BAR - (at - bar * BEATS_PER_BAR)
            for pitch in shape:
                notes.append(
                    Note(
                        pitch=pitch,
                        start_beats=at,
                        duration_beats=max(0.1, length),
                        velocity=min(127, max(1, velocity)),
                    )
                )

    return Part(instrument=Instrument.KEYS, notes=separate(humanise(notes, rng, feel=section.feel)))


def _consonant_pitch_classes(section: Section) -> frozenset[int]:
    """The section's scale plus every chord tone in its chart."""
    return pitch_classes(section.key, section.scale).union(
        *(chord.pitch_classes() for chord in section.chart.chords)
    )


def _style_for(chord: Chord, *, stabbing: bool, consonant: frozenset[int]) -> str:
    """A sus2 pad, unless its added second falls outside the section.

    A chart is allowed to disagree with its key — `| Em |` under a C briefing is a legal
    request and something Phase 3 will certainly be asked to play. The added second of a
    sus2 is not a chord tone, so under such a chart it can land outside both the key and
    the chart, and a pad that breaks the dissonance budget on its own would make the
    deterministic floor depend on the repairer. A triad is always inside the chord.
    """
    if stabbing:
        return "triad"
    added = {
        (chord.root + step) % PITCH_CLASSES
        for step in Chord(root=0, quality=Quality.SUS2).intervals()
    }
    return "sus2" if added <= consonant else "triad"


def _above_the_bass(pitches: tuple[int, ...]) -> tuple[int, ...]:
    """Octave-shift the whole voicing until it clears the bass's range."""
    fitted = fit_to_range(pitches, Instrument.KEYS)
    while fitted and fitted[0] < KEYS_FLOOR and fitted[-1] + 12 <= KEYS_CEILING:
        fitted = tuple(pitch + 12 for pitch in fitted)
    return fitted
