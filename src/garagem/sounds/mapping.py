"""Which of an EXS instrument's zones Live plays, and over which keys and velocities (ADR-029).

Logic picks a zone with more than a key and a velocity: the Strat chooses its string by what
the player did last, and its palm mute by a key switch. Live's rack chooses by key and
velocity only, so the choice is made here, once, and written down as `Part`s. The drum kits'
choices are in `kit.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from itertools import groupby
from typing import Final

from garagem.sounds.exs import ExsInstrument, ExsZone

MAX_KEY: Final = 127
MIN_VELOCITY: Final = 1
MAX_VELOCITY: Final = 127
# EXS layers are written over 0..127, and Live's velocity zones over 1..127.
EXS_VELOCITIES: Final = 128

# The lowest note each string takes, the guitar held in the first frets: a note goes to the
# lowest string that can play it there. A power chord on E (40, 47, 52) is then the E, A and D
# strings, as a guitarist would play it, and no note ever sounds on two strings at once.
STRING_FLOORS: Final[dict[int, int]] = {6: 0, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}

# `6 E_Main`, `1 E_Mute `: a string, its open note and the articulation. The Strat's taps, its
# ready-made chords and GarageBand's own one-string groups (`GB_Main`, `Mute_GB`) do not match.
STRING_GROUP: Final = re.compile(r"^([1-6]) [A-G]_(Main|Mute)$")

# A group Logic plays when a key is let go: the bass's `E-BASS PICK NOTE OFF 1`, the sound of a
# string being stopped. Live's rack would play it as a note, so it is left out.
RELEASE_GROUP: Final = re.compile(r"NOTE OFF", re.IGNORECASE)

# GarageBand maps its basses an octave above where they sound: the low E, 41 Hz, is on key 40
# (measured on Picked Rock's and Fingerstyle's samples). The band writes the low E as 28.
BASS_OCTAVE_DOWN: Final = -12

NOTE_NAMES: Final = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


@dataclass(frozen=True)
class Part:
    """One zone as Live plays it: its sample region, over these keys and velocities."""

    name: str
    zone: ExsZone
    # The zone's level and its group's, in dB, as Logic adds them.
    gain_db: int
    key_lo: int
    key_hi: int
    vel_lo: int
    vel_hi: int
    # The key that plays the sample at its own pitch. Logic's root for the guitar; an octave
    # down for a bass; for a drum, the note it answers, less any interval it is moved by.
    root: int


def guitar_parts(instrument: ExsInstrument, palm_mute_below: int) -> tuple[Part, ...]:
    """Each key on one string; a palm mute under `palm_mute_below`, a ringing note at or over.

    The split is the one `engines.guitar.articulated` clamps every guitar note to on its way
    out, so a chug never reaches the ringing samples and a strum never the muted ones.
    """
    if not MIN_VELOCITY < palm_mute_below <= MAX_VELOCITY:
        raise ValueError(f"palm_mute_below must be in 2..127, got {palm_mute_below}")
    bands = {
        "Mute": (MIN_VELOCITY, palm_mute_below - 1),
        "Main": (palm_mute_below, MAX_VELOCITY),
    }
    parts: list[Part] = []
    for zone in instrument.zones:
        if zone.group < 0:
            continue
        match = STRING_GROUP.match(instrument.groups[zone.group].name)
        if match is None:
            continue
        string, articulation = int(match.group(1)), match.group(2)
        floor = STRING_FLOORS[string]
        ceiling = min((f - 1 for f in STRING_FLOORS.values() if f > floor), default=MAX_KEY)
        key_lo, key_hi = max(zone.key_lo, floor), min(zone.key_hi, ceiling)
        if key_lo > key_hi:
            continue
        velocities = group_velocities(instrument, zone)
        if velocities is None:
            continue
        vel_lo, vel_hi = rescale(*velocities, bands[articulation])
        if vel_lo > vel_hi:
            # A soft layer squeezed out of a band one velocity wide.
            continue
        parts.append(
            Part(
                name=f"{note_name(zone.root)} {_STRING_NAMES[string]} {articulation.lower()}"
                + _layer(zone),
                zone=zone,
                gain_db=gain(instrument, zone),
                key_lo=key_lo,
                key_hi=key_hi,
                vel_lo=vel_lo,
                vel_hi=vel_hi,
                root=zone.root,
            )
        )
    return without_overlaps(parts)


def multisample_parts(instrument: ExsInstrument, transpose: int = 0) -> tuple[Part, ...]:
    """Every zone where Logic maps it, `transpose` semitones away, without its release noises.

    Each zone answers the velocities both it and its group do: the basses keep their five
    layers on the group, and every zone in a layer answers 0..127.
    """
    parts: list[Part] = []
    for zone in instrument.zones:
        if zone.group >= 0 and RELEASE_GROUP.search(instrument.groups[zone.group].name):
            continue
        velocities = group_velocities(instrument, zone)
        if velocities is None:
            continue
        vel_lo, vel_hi = rescale(*velocities, (MIN_VELOCITY, MAX_VELOCITY))
        key_lo = max(zone.key_lo + transpose, 0)
        key_hi = min(zone.key_hi + transpose, MAX_KEY)
        root = zone.root + transpose
        if key_lo > key_hi or vel_lo > vel_hi or not 0 <= root <= MAX_KEY:
            continue
        parts.append(
            Part(
                name=f"{note_name(root)} {vel_lo}-{vel_hi}",
                zone=zone,
                gain_db=gain(instrument, zone),
                key_lo=key_lo,
                key_hi=key_hi,
                vel_lo=vel_lo,
                vel_hi=vel_hi,
                root=root,
            )
        )
    return without_overlaps(parts)


def group_velocities(instrument: ExsInstrument, zone: ExsZone) -> tuple[int, int] | None:
    """The velocities, out of 0..127, that the zone and its group both answer, if any."""
    if zone.group < 0:
        return zone.vel_lo, zone.vel_hi
    group = instrument.groups[zone.group]
    low, high = max(zone.vel_lo, group.vel_lo), min(zone.vel_hi, group.vel_hi)
    return (low, high) if low <= high else None


def gain(instrument: ExsInstrument, zone: ExsZone) -> int:
    """The zone's level and its group's, in dB, as Logic adds them."""
    return zone.volume_db + (instrument.groups[zone.group].volume_db if zone.group >= 0 else 0)


def without_overlaps(parts: list[Part]) -> tuple[Part, ...]:
    """Every key and velocity played by one part at most, the most specific one.

    The narrower part wins, and a wider one keeps only the keys and velocities nobody else
    plays. The Strat's high E string has one zone with its velocity range switched off, lying
    over a soft layer at the same keys: in Logic it is the loud layer, and here it keeps the loud
    velocities. Picked Rock's loudest layer runs its B3 zone to the top of the keyboard, under
    its D4 zone: it keeps the B3 and the C4.
    """
    kept: list[Part] = []
    ranked = sorted(
        enumerate(parts),
        key=lambda item: (
            item[1].vel_hi - item[1].vel_lo,
            item[1].key_hi - item[1].key_lo,
            item[0],
        ),
    )
    for _, part in ranked:
        kept += _remainder(part, [other for other in kept if _overlap(part, other)])
    return tuple(sorted(kept, key=lambda p: (p.key_lo, p.vel_lo)))


def _remainder(part: Part, rivals: list[Part]) -> list[Part]:
    """`part` less everything a rival plays: one part per run of keys left the same way."""
    if not rivals:
        return [part]
    left = [
        (
            key,
            _uncovered(
                part.vel_lo, part.vel_hi, [r for r in rivals if r.key_lo <= key <= r.key_hi]
            ),
        )
        for key in range(part.key_lo, part.key_hi + 1)
    ]
    pieces: list[Part] = []
    for runs, keys in groupby(left, key=lambda item: item[1]):
        played = [key for key, _ in keys]
        pieces += [
            replace(part, key_lo=played[0], key_hi=played[-1], vel_lo=lo, vel_hi=hi)
            for lo, hi in runs
        ]
    return pieces


def _uncovered(low: int, high: int, rivals: list[Part]) -> list[tuple[int, int]]:
    """The runs of `low..high` that no rival's velocity range covers."""
    runs: list[tuple[int, int]] = []
    start = low
    for rival in sorted(rivals, key=lambda r: r.vel_lo):
        if rival.vel_lo > start:
            runs.append((start, min(high, rival.vel_lo - 1)))
        start = max(start, rival.vel_hi + 1)
    if start <= high:
        runs.append((start, high))
    return runs


def _overlap(a: Part, b: Part) -> bool:
    return (
        a.key_lo <= b.key_hi
        and b.key_lo <= a.key_hi
        and a.vel_lo <= b.vel_hi
        and b.vel_lo <= a.vel_hi
    )


def rescale(vel_lo: int, vel_hi: int, band: tuple[int, int]) -> tuple[int, int]:
    """An EXS velocity layer, out of 0..127, moved into `band` with the same proportions.

    Layers that met before still meet: each edge is rounded down the same way, so the top of
    one layer is always one below the bottom of the next.
    """
    low, high = band
    width = high - low + 1
    return (
        low + vel_lo * width // EXS_VELOCITIES,
        low + (vel_hi + 1) * width // EXS_VELOCITIES - 1,
    )


def _layer(zone: ExsZone) -> str:
    """` soft` or ` hard` for a zone that is one of two velocity layers, else nothing."""
    if zone.vel_lo == 0 and zone.vel_hi == MAX_VELOCITY:
        return ""
    return " hard" if zone.vel_hi == MAX_VELOCITY else " soft"


def note_name(pitch: int) -> str:
    """`E2` for 40, the guitar's low string, as this project names pitches (middle C is C4)."""
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


_STRING_NAMES: Final[dict[int, str]] = {6: "E", 5: "A", 4: "D", 3: "G", 2: "B", 1: "e"}
