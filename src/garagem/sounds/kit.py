"""Drum Kit Designer's kits as the band plays them: one piece for each note it writes (ADR-029).

A Drum Kit Designer kit keeps its pieces mostly where General MIDI does, which is where
`theory.percussion` writes them, with up to 38 velocity layers each and its hi-hat at seven
openings. Live's rack chooses by key and velocity only, so the choices are made here, once:

- **The hi-hat.** Each opening, `o1` to `o7`, holds the same keys. On SoCal's samples `o1` rings
  for 120 ms and `o7` for 990 ms. The closed hat is `o1`. The open hat is `o5`, at 590 ms, which
  washes over a chorus's eighths without blurring them. The pedal hat is the foot's own group.
- **The toms.** The kits have three and the band writes four, so the low tom is the mid tom
  three semitones down.
- **The layers.** Up to `layers` per piece, spread evenly over the velocities, each the zone
  Logic plays in the middle of its band. Every velocity from 1 to 127 plays exactly one.

A kit without one of these pieces is refused, rather than played with a hole in it.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from garagem.sounds.exs import ExsInstrument, ExsZone
from garagem.sounds.mapping import MAX_VELOCITY, MIN_VELOCITY, Part, gain, group_velocities
from garagem.theory.percussion import (
    CLOSED_HAT,
    CRASH,
    KICK,
    OPEN_HAT,
    PEDAL_HAT,
    RIDE,
    SNARE,
    TOM_FLOOR,
    TOM_HIGH,
    TOM_LOW,
    TOM_MID,
)

# Enough to hear a ghost note, a backbeat and a rimshot-hard hit apart; 38 would be 38 Simplers
# for the kick alone.
DEFAULT_LAYERS: Final = 8


class KitError(ValueError):
    """The kit does not have a piece the band plays."""


@dataclass(frozen=True)
class Piece:
    name: str
    # Where the band writes it.
    note: int
    # Drum Kit Designer's name for it, between the kit's and the mix's: `Bd1:all` in
    # `AnKit8:Bd1:all:Pr`.
    group: str
    # Where the kit keeps it.
    key: int
    # How far it is moved: a tom the kit does not have, borrowed from its neighbour.
    semitones: int = 0


PIECES: Final = (
    Piece("kick", KICK, "Bd1:all", 36),
    Piece("snare", SNARE, "Sn1:all", 38),
    Piece("closed hat", CLOSED_HAT, "HH:o1", 42),
    Piece("pedal hat", PEDAL_HAT, "HH:foot", 33),
    Piece("open hat", OPEN_HAT, "HH:o5", 46),
    Piece("crash", CRASH, "CrL:all", 49),
    Piece("ride", RIDE, "Rd:all", 51),
    Piece("high tom", TOM_HIGH, "TomHi:all", 48),
    Piece("mid tom", TOM_MID, "TomMidHi:all", 47),
    Piece("low tom", TOM_LOW, "TomMidHi:all", 47, semitones=-3),
    Piece("floor tom", TOM_FLOOR, "TomLo:all", 43),
)


def kit_parts(instrument: ExsInstrument, layers: int = DEFAULT_LAYERS) -> tuple[Part, ...]:
    """Each piece on the note the band writes, in at most `layers` velocity layers."""
    if layers < 1:
        raise ValueError(f"a piece needs at least one layer, got {layers}")
    parts: list[Part] = []
    for piece in PIECES:
        zones = [
            zone
            for zone in instrument.zones
            if piece_of(instrument, zone) == piece.group and zone.key_lo <= piece.key <= zone.key_hi
        ]
        if not zones:
            raise KitError(
                f"{instrument.name or 'the kit'} has no {piece.name} ({piece.group} on key "
                f"{piece.key}), and the band plays one"
            )
        for number, (zone, vel_lo, vel_hi) in enumerate(_layers(instrument, zones, layers), 1):
            parts.append(
                Part(
                    name=f"{piece.name} {number}",
                    zone=zone,
                    gain_db=gain(instrument, zone),
                    key_lo=piece.note,
                    key_hi=piece.note,
                    vel_lo=vel_lo,
                    vel_hi=vel_hi,
                    root=piece.note - piece.semitones,
                )
            )
    return tuple(parts)


def piece_of(instrument: ExsInstrument, zone: ExsZone) -> str:
    """`Sn1:all` for a zone in `AnKit2:Sn1:all:Pr`; empty for one in no such group."""
    if zone.group < 0:
        return ""
    fields = instrument.groups[zone.group].name.split(":")
    return ":".join(fields[1:3]) if len(fields) >= 3 else ""


def _layers(
    instrument: ExsInstrument, zones: list[ExsZone], most: int
) -> list[tuple[ExsZone, int, int]]:
    """The zones a piece keeps, each with the velocities it answers, together 1..127."""
    spans: list[tuple[ExsZone, int, int]] = []
    for zone in zones:
        velocities = group_velocities(instrument, zone)
        if velocities is not None:
            spans.append((zone, max(velocities[0], MIN_VELOCITY), velocities[1]))
    spans.sort(key=lambda span: span[1])
    if len(spans) > most:
        spans = _fewer(spans, most)
    edges = [(low, high) for _, low, high in spans]
    meets = all(upper[0] == lower[1] + 1 for lower, upper in pairwise(edges))
    if not (edges and edges[0][0] == MIN_VELOCITY and edges[-1][1] == MAX_VELOCITY and meets):
        raise KitError(f"{instrument.name or 'the kit'}'s layers leave a velocity unplayed")
    return spans


def _fewer(spans: list[tuple[ExsZone, int, int]], most: int) -> list[tuple[ExsZone, int, int]]:
    """`most` even bands over 1..127, each played by the zone Logic plays in its middle."""
    width = MAX_VELOCITY - MIN_VELOCITY + 1
    kept: list[tuple[ExsZone, int, int]] = []
    for band in range(most):
        low = MIN_VELOCITY + band * width // most
        high = MIN_VELOCITY + (band + 1) * width // most - 1
        middle = (low + high) // 2
        zone = min(spans, key=lambda span: _distance(middle, span))[0]
        if kept and kept[-1][0] == zone:
            kept[-1] = (zone, kept[-1][1], high)
        else:
            kept.append((zone, low, high))
    return kept


def _distance(velocity: int, span: tuple[ExsZone, int, int]) -> int:
    """How far `velocity` is from the velocities a zone answers: 0 inside them."""
    _, low, high = span
    return max(low - velocity, 0, velocity - high)
