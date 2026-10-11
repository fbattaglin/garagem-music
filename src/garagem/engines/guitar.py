"""The guitarist: power chords on the low strings, palm-muted when the section holds back.

Power chords at every dynamic, because that is what rock is: no third, so the same shape sits
over a major and a minor bar, and the harmony comes from the bass and the organ. A chorus gets
bigger by ringing, and by a second guitar joining it (`engines/double.py`), not by adding a
third to the chord. Close triads in a chorus were a keyboard player's idea of "opening up", and
they sat in the same octave as the keys (ADR-028).

**The shape moves along the neck, not between inversions.** `theory.power_chord` puts each root
on the low E or A string, and the hand slides the whole shape from chord to chord. Voice leading
is what a pianist does, and on a power chord it produced fourths.

**A palm mute is a short note and a soft one, not a flag.** Nothing downstream has to interpret
it: the renderer writes a duration and a velocity, Live plays exactly that, and a muted chug is
audibly a muted chug. A boolean would have to be understood by every layer between here and the
audio engine.
"""

from __future__ import annotations

from random import Random

from garagem.domain import (
    SIXTEENTHS_PER_BAR,
    Feel,
    Instrument,
    Note,
    Part,
    Section,
    beats_of,
)
from garagem.engines.humanise import humanise, separate
from garagem.theory.voicings import power_chord

# Which sixteenths get a strum, per feel. The DSL's own `rhy:` line, chosen rather than
# generated.
RHYTHMS: dict[Feel, str] = {
    Feel.STRAIGHT8: "x.x.x.x.x.x.x.x.",
    Feel.STRAIGHT16: "xx.xxx.xxx.xx.x.",
    # The swung offbeats, and only those: the chop that makes a shuffle swing. The bass has
    # the beats and the hats have both, so the three interlock instead of doubling each other
    # (ADR-026). Under `beats_of` these four attacks are the late half of each beat.
    Feel.SHUFFLE: "..x...x...x...x.",
    Feel.HALFTIME: "x.......x.......",
}

# Below this the section is holding back and the right hand stays on the strings.
MUTED_DYN = 3
MUTED_BEATS = 0.12
RING_BEATS = 0.5
MUTED_DROP = 14

# From here the chord rings into the next strum instead of stopping on the eighth. That
# sustain is the arena half of the sound in a chorus (ADR-028), and in a half-time chorus it
# is the difference between two stabs a bar and two chords a bar.
SUSTAIN_DYN = 4

BASE_VELOCITY = 48
DYN_VELOCITY = 13
DOWNBEAT_ACCENT = 10


def play(section: Section, rng: Random) -> Part:
    """One guitar part for the whole section."""
    muted = section.dyn < MUTED_DYN
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn - (MUTED_DROP if muted else 0)
    rhythm = RHYTHMS[section.feel]
    attacks = [slot for slot, mark in enumerate(rhythm) if mark == "x"]

    notes: list[Note] = []
    for bar in range(section.bars):
        shape = power_chord(section.chart.at(bar))
        offset = bar * SIXTEENTHS_PER_BAR

        for slot in attacks:
            at = beats_of(offset + slot, section.feel)
            accent = DOWNBEAT_ACCENT if slot % 4 == 0 else 0
            length = _length(section, attacks, slot, muted=muted)
            for pitch in shape:
                notes.append(
                    Note(
                        pitch=pitch,
                        start_beats=at,
                        duration_beats=length,
                        velocity=min(127, max(1, velocity + accent)),
                    )
                )

    return Part(
        instrument=Instrument.GUITAR, notes=separate(humanise(notes, rng, feel=section.feel))
    )


def _length(section: Section, attacks: list[int], slot: int, *, muted: bool) -> float:
    """Muted, ringing for an eighth, or sustained until the next strum."""
    if muted:
        return MUTED_BEATS
    if section.dyn < SUSTAIN_DYN:
        return RING_BEATS
    later = [other for other in attacks if other > slot]
    following = later[0] if later else attacks[0] + SIXTEENTHS_PER_BAR
    return beats_of(following, section.feel) - beats_of(slot, section.feel)
