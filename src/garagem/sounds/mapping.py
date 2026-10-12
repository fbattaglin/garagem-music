"""Which of an EXS instrument's zones Live plays, and over which keys and velocities (ADR-029).

Logic picks a zone with more than a key and a velocity: the Strat chooses its string by what
the player did last, and its palm mute by a key switch. Live's rack chooses by key and
velocity only, so the choice is made here, once, and written down as `Part`s.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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
        vel_lo, vel_hi = rescale(zone.vel_lo, zone.vel_hi, bands[articulation])
        if vel_lo > vel_hi:
            # A soft layer squeezed out of a band one velocity wide.
            continue
        parts.append(
            Part(
                name=f"{note_name(zone.root)} {_STRING_NAMES[string]} {articulation.lower()}"
                + _layer(zone),
                zone=zone,
                gain_db=zone.volume_db + instrument.groups[zone.group].volume_db,
                key_lo=key_lo,
                key_hi=key_hi,
                vel_lo=vel_lo,
                vel_hi=vel_hi,
            )
        )
    return without_overlaps(parts)


def without_overlaps(parts: list[Part]) -> tuple[Part, ...]:
    """Every key and velocity played by one part at most, the most specific one.

    The Strat's high E string has one zone with its velocity range switched off, lying over
    a soft layer at the same keys, and no loud layer beside it: in Logic it is the loud layer.
    So the narrower part wins, and a wider one over exactly the same keys keeps the velocities
    nobody else plays. A wider one over other keys gives way altogether.
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
        rivals = [other for other in kept if _overlap(part, other)]
        if not rivals:
            kept.append(part)
        elif all((r.key_lo, r.key_hi) == (part.key_lo, part.key_hi) for r in rivals):
            kept += [
                Part(part.name, part.zone, part.gain_db, part.key_lo, part.key_hi, lo, hi)
                for lo, hi in _uncovered(part.vel_lo, part.vel_hi, rivals)
            ]
    return tuple(sorted(kept, key=lambda p: (p.key_lo, p.vel_lo)))


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
