"""The drummer: a groove from the table, a fill at the end, a crash at the start.

Everything this engine decides comes from three fields of the briefing — `feel` picks
the pattern's shape, `dyn` its density, `tension` how hard the last bar pushes into the
next section. Nothing else, and no randomness beyond the humaniser, so the same briefing
and the same seed produce the same bar for the same reason every time.

**The crash is on bar 1, not after the fill.** A section ends with a fill and the next
one opens with a crash, so from inside a single section the crash belongs at the top.
Writing it the other way round would put a cymbal in a clip that has already been
written and fired (ADR-001), which is the one thing the scheduler cannot do.

The engine does not call the validator. Producing valid music is its job; checking is a
separate concern that has to be able to disagree with it.
"""

from __future__ import annotations

from random import Random

from garagem.domain import (
    SIXTEENTHS_PER_BAR,
    Instrument,
    Note,
    Part,
    Section,
    beats_of,
)
from garagem.engines.groove import fill_for, groove_for
from garagem.engines.humanise import humanise, separate
from garagem.theory.percussion import CLOSED_HAT, CRASH, KICK, SNARE

# A hit lasts long enough to be a hit and no longer: a drum's sound is its decay, not its
# note length, and a long MIDI note on a sampled kit changes nothing but the display.
HIT_BEATS = 0.125

BASE_VELOCITY = 46
DYN_VELOCITY = 13
DOWNBEAT_ACCENT = 12
HAT_DROP = 18


def play(section: Section, rng: Random) -> Part:
    """One drum part for the whole section."""
    notes: list[Note] = []
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn
    groove = groove_for(section.feel, section.dyn, section.bpm)
    last_bar = section.bars - 1

    for bar in range(section.bars):
        offset = bar * SIXTEENTHS_PER_BAR
        filling = bar == last_bar and section.bars > 1

        for slot in range(SIXTEENTHS_PER_BAR):
            at = beats_of(offset + slot, section.feel)
            if groove.kick[slot]:
                notes.append(_hit(KICK, at, velocity, slot))
            if filling:
                if fill_for(section.tension)[slot]:
                    notes.append(_hit(SNARE, at, velocity, slot))
                continue
            if groove.snare[slot]:
                notes.append(_hit(SNARE, at, velocity, slot))
            if groove.hat[slot]:
                notes.append(_hit(CLOSED_HAT, at, velocity - HAT_DROP, slot))

        if bar == 0:
            notes.append(_hit(CRASH, beats_of(offset, section.feel), velocity, 0))

    return Part(
        instrument=Instrument.DRUMS,
        notes=separate(humanise(sorted(notes, key=_when), rng, feel=section.feel)),
    )


def _hit(pitch: int, at: float, velocity: int, slot: int) -> Note:
    """Downbeats are accented. A bar where every hit is equal is a machine."""
    accented = velocity + (DOWNBEAT_ACCENT if slot % 4 == 0 else 0)
    return Note(
        pitch=pitch,
        start_beats=at,
        duration_beats=HIT_BEATS,
        velocity=min(127, max(1, accented)),
    )


def _when(note: Note) -> tuple[float, int]:
    return note.start_beats, note.pitch
