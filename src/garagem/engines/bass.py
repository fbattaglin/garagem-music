"""The bass player: the root on every change, and a pulse under everything else.

The validator has a rule saying a chord change needs a root under it. This engine
satisfies it **by construction** rather than by being repaired afterwards — the first
note of every bar that changes chord is degree 1, before anything else is decided. A
deterministic floor that relied on the repairer to make it legal would be a floor with a
hole in it.

Everything else is a lookup: `feel` picks the pulse, `dyn` the velocity, and `tension`
decides whether the line stays on the root or reaches for the fifth and, higher still,
walks into the next chord.
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
from garagem.theory.scales import degree_to_pitch
from garagem.theory.voicings import RANGES

# Octave 2 puts every root between C2 (36) and B2 (47), comfortably inside E1-G3 whatever
# the key — no chart can push the line off the bottom of the instrument.
ROOT_OCTAVE = 2

# Which sixteenths the line plays, per feel. Sparse enough that `tension` has somewhere
# to add rather than having to take away.
PULSE: dict[Feel, str] = {
    Feel.STRAIGHT8: "x.x.x.x.x.x.x.x.",
    Feel.STRAIGHT16: "x.x.x.x.x.x.x.x.",
    Feel.SHUFFLE: "x.x.x.x.x.x.x.x.",
    Feel.HALFTIME: "x.......x.......",
}

# Above this the line stops sitting on the root and starts moving through the chord.
MOVING_TENSION = 0.35
# Above this it walks: a passing tone on the last eighth, aiming at the next root.
WALKING_TENSION = 0.65

# A walk needs somewhere to walk. One chromatic note in a bar of two is half the bar
# outside the key, which no tension buys; one in a bar of four or more is a passing tone.
# The dissonance budget is a rule the engine satisfies by construction, not by luck.
WALKING_MIN_ATTACKS = 4

BASE_VELOCITY = 52
DYN_VELOCITY = 12
DOWNBEAT_ACCENT = 10
NOTE_BEATS = 0.45


def play(section: Section, rng: Random) -> Part:
    """One bass part for the whole section."""
    low, high = RANGES[Instrument.BASS]
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn
    pulse = PULSE[section.feel]
    notes: list[Note] = []

    for bar in range(section.bars):
        chord = section.chart.at(bar)
        root = degree_to_pitch(chord, 1, ROOT_OCTAVE)
        fifth = degree_to_pitch(chord, 5, ROOT_OCTAVE)
        offset = bar * SIXTEENTHS_PER_BAR
        attacks = [index for index, slot in enumerate(pulse) if slot == "x"]
        last_slot = attacks[-1]
        walking = section.tension > WALKING_TENSION and len(attacks) >= WALKING_MIN_ATTACKS

        for slot, mark in enumerate(pulse):
            if mark != "x":
                continue
            pitch = root
            if section.tension > MOVING_TENSION and slot % 8 == 4:
                pitch = fifth
            if walking and slot == last_slot:
                pitch = _towards(section, bar, root)
            notes.append(
                Note(
                    pitch=_inside(pitch, low, high),
                    start_beats=beats_of(offset + slot, section.feel),
                    duration_beats=NOTE_BEATS,
                    velocity=min(127, velocity + (DOWNBEAT_ACCENT if slot == 0 else 0)),
                )
            )

    return Part(
        instrument=Instrument.BASS,
        notes=separate(humanise(notes, rng, feel=section.feel)),
    )


def _towards(section: Section, bar: int, root: int) -> int:
    """A passing tone aimed at the next bar's root, or the fifth when nothing changes.

    Approaching by a semitone is what a walking line does; it is also, by definition, a
    note outside the key, which is why it only appears above `WALKING_TENSION` — the
    dissonance budget at that tension has room for it and at low tension it does not.
    """
    next_root = degree_to_pitch(section.chart.at(bar + 1), 1, ROOT_OCTAVE)
    if next_root == root:
        return degree_to_pitch(section.chart.at(bar), 5, ROOT_OCTAVE)
    return next_root - 1 if next_root > root else next_root + 1


def _inside(pitch: int, low: int, high: int) -> int:
    while pitch < low:
        pitch += 12
    while pitch > high:
        pitch -= 12
    return pitch
