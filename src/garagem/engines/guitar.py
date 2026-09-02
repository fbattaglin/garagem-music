"""The guitarist: power chords, voice-led, palm-muted when the section is holding back.

Power chords by default because that is what rock is: no third, so the same shape sits
over a major and a minor bar and the harmony comes from the bass and the keys. Richer
voicings arrive with `dyn`, not with cleverness.

**A palm mute is a short note and a soft one, not a flag.** Nothing downstream has to
interpret it: the renderer writes a duration and a velocity, Live plays exactly that, and
a muted chug is audibly a muted chug. A boolean would have to be understood by every
layer between here and the audio engine.

`voice_lead` runs across every chord change, which is what stops four chords sounding
like four chords.
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
from garagem.theory.voicings import Register, fit_to_range, voice, voice_lead

# Which sixteenths get a strum, per feel. The DSL's own `rhy:` line, chosen rather than
# generated.
RHYTHMS: dict[Feel, str] = {
    Feel.STRAIGHT8: "x.x.x.x.x.x.x.x.",
    Feel.STRAIGHT16: "xx.xxx.xxx.xx.x.",
    Feel.SHUFFLE: "x.x.x.x.x.x.x.x.",
    Feel.HALFTIME: "x.......x.......",
}

# Below this the section is holding back and the right hand stays on the strings.
MUTED_DYN = 3
MUTED_BEATS = 0.12
RING_BEATS = 0.5
MUTED_DROP = 14

# A triad instead of a power chord once the section opens up: more information in the
# chord, which is what a chorus wants and a verse does not.
TRIAD_DYN = 4

BASE_VELOCITY = 48
DYN_VELOCITY = 13
DOWNBEAT_ACCENT = 10


def play(section: Section, rng: Random) -> Part:
    """One guitar part for the whole section."""
    style = "triad" if section.dyn >= TRIAD_DYN else "pow"
    muted = section.dyn < MUTED_DYN
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn - (MUTED_DROP if muted else 0)
    rhythm = RHYTHMS[section.feel]

    notes: list[Note] = []
    previous: tuple[int, ...] = ()
    for bar in range(section.bars):
        chord = section.chart.at(bar)
        shape = fit_to_range(voice(chord, style, Register.MID), Instrument.GUITAR)
        shape = fit_to_range(voice_lead(previous, shape), Instrument.GUITAR)
        previous = shape
        offset = bar * SIXTEENTHS_PER_BAR

        for slot, mark in enumerate(rhythm):
            if mark != "x":
                continue
            at = beats_of(offset + slot, section.feel)
            accent = DOWNBEAT_ACCENT if slot % 4 == 0 else 0
            for pitch in shape:
                notes.append(
                    Note(
                        pitch=pitch,
                        start_beats=at,
                        duration_beats=MUTED_BEATS if muted else RING_BEATS,
                        velocity=min(127, max(1, velocity + accent)),
                    )
                )

    return Part(
        instrument=Instrument.GUITAR, notes=separate(humanise(notes, rng, feel=section.feel))
    )
