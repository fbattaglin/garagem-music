"""Reads an EXS instrument, the multisample format GarageBand and Logic ship (ADR-029).

An EXS file is a run of chunks. Each starts with an 84-byte header (a signature whose second
byte from the top is the chunk's kind, the size of the body that follows, an id, the magic
`TBOS` and a 64-byte name) and is followed by `size` bytes of body. Four kinds matter here: the
instrument's header, a zone (one sample over a key and velocity range), a group (a set of zones
Logic switches between, which is how the Strat keeps its strings and its palm mutes apart) and a
sample (the file a zone plays).

The format is not published. The offsets below were read off GarageBand's own Vintage Strat,
Picked Rock Bass and Drum Kit Designer kits, where every zone came out with a root inside its
key range, velocity layers that meet, and sample regions that follow one another through the
file. Anything that does not parse is refused rather than guessed at.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final

HEADER_BYTES: Final = 84
MAGIC: Final = b"TBOS"
MAGIC_AT: Final = 16
NAME_AT: Final = 20
NAME_BYTES: Final = 64

HEADER_KIND: Final = 0
ZONE_KIND: Final = 1
GROUP_KIND: Final = 2
SAMPLE_KIND: Final = 3

# Offsets inside a zone chunk, counted from the chunk's first byte.
ZONE_OPTIONS_AT: Final = 84
ZONE_ROOT_AT: Final = 85
ZONE_FINE_AT: Final = 86
ZONE_VOLUME_AT: Final = 88
ZONE_KEY_LO_AT: Final = 90
ZONE_KEY_HI_AT: Final = 91
ZONE_VEL_LO_AT: Final = 93
ZONE_VEL_HI_AT: Final = 94
ZONE_START_AT: Final = 96
ZONE_END_AT: Final = 100
ZONE_COARSE_AT: Final = 164
ZONE_GROUP_AT: Final = 172
ZONE_SAMPLE_AT: Final = 176
ZONE_BYTES: Final = 180

# Offsets inside a group chunk.
GROUP_VOLUME_AT: Final = 84

# A zone whose velocity range is off answers every velocity, whatever its two bytes say.
VELOCITY_RANGE_ON: Final = 0x08

# Offsets inside a sample chunk.
SAMPLE_FRAMES_AT: Final = 88
SAMPLE_RATE_AT: Final = 92
SAMPLE_BITS_AT: Final = 96
SAMPLE_FOLDER_AT: Final = 164
SAMPLE_FILE_AT: Final = 420
PATH_BYTES: Final = 256

MAX_MIDI: Final = 127


class ExsError(ValueError):
    """The bytes are not an EXS instrument this reader understands."""


@dataclass(frozen=True)
class ExsZone:
    name: str
    root: int
    # Cents, coarse and fine together: Logic tunes a few zones by a handful of cents.
    tune_cents: int
    # Gain in dB. GarageBand normalises every sample and puts the level back here.
    volume_db: int
    key_lo: int
    key_hi: int
    vel_lo: int
    vel_hi: int
    # Frames into the sample file. A consolidated file holds every zone one after another.
    start: int
    end: int
    # -1 when the zone belongs to no group.
    group: int
    sample: int


@dataclass(frozen=True)
class ExsGroup:
    name: str
    volume_db: int


@dataclass(frozen=True)
class ExsSample:
    name: str
    # Where Logic looks for the file, as written in the instrument. May be empty.
    folder: str
    file: str
    frames: int
    rate: int
    bits: int


@dataclass(frozen=True)
class ExsInstrument:
    name: str
    zones: tuple[ExsZone, ...]
    groups: tuple[ExsGroup, ...]
    samples: tuple[ExsSample, ...]


def parse_exs(data: bytes) -> ExsInstrument:
    name = ""
    zones: list[ExsZone] = []
    groups: list[ExsGroup] = []
    samples: list[ExsSample] = []
    at = 0
    while at + HEADER_BYTES <= len(data):
        signature, size = struct.unpack_from("<II", data, at)
        if data[at + MAGIC_AT : at + MAGIC_AT + len(MAGIC)] != MAGIC:
            raise ExsError(f"no {MAGIC.decode()} chunk at byte {at}: not an EXS instrument")
        end = at + HEADER_BYTES + size
        if end > len(data):
            raise ExsError(f"the chunk at byte {at} runs past the end of the file")
        chunk = data[at:end]
        kind = (signature & 0x0F000000) >> 24
        if kind == HEADER_KIND:
            name = _text(chunk, NAME_AT, NAME_BYTES)
        elif kind == ZONE_KIND:
            zones.append(_zone(chunk, at))
        elif kind == GROUP_KIND:
            groups.append(_group(chunk, at))
        elif kind == SAMPLE_KIND:
            samples.append(_sample(chunk, at))
        at = end
    if not zones:
        raise ExsError("an EXS instrument with no zones")
    _check_references(zones, groups, samples)
    return ExsInstrument(
        name=name, zones=tuple(zones), groups=tuple(groups), samples=tuple(samples)
    )


def _zone(chunk: bytes, at: int) -> ExsZone:
    if len(chunk) < ZONE_BYTES:
        raise ExsError(f"the zone at byte {at} is {len(chunk)} bytes, short of {ZONE_BYTES}")
    velocity_on = chunk[ZONE_OPTIONS_AT] & VELOCITY_RANGE_ON
    key_lo, key_hi = chunk[ZONE_KEY_LO_AT], chunk[ZONE_KEY_HI_AT]
    vel_lo, vel_hi = (
        (chunk[ZONE_VEL_LO_AT], chunk[ZONE_VEL_HI_AT]) if velocity_on else (0, MAX_MIDI)
    )
    (fine,) = struct.unpack_from("<b", chunk, ZONE_FINE_AT)
    (volume,) = struct.unpack_from("<b", chunk, ZONE_VOLUME_AT)
    (coarse,) = struct.unpack_from("<b", chunk, ZONE_COARSE_AT)
    start, end = struct.unpack_from("<ii", chunk, ZONE_START_AT)
    (group,) = struct.unpack_from("<i", chunk, ZONE_GROUP_AT)
    (sample,) = struct.unpack_from("<i", chunk, ZONE_SAMPLE_AT)
    zone = ExsZone(
        name=_text(chunk, NAME_AT, NAME_BYTES),
        root=chunk[ZONE_ROOT_AT],
        tune_cents=coarse * 100 + fine,
        volume_db=volume,
        key_lo=key_lo,
        key_hi=key_hi,
        vel_lo=vel_lo,
        vel_hi=vel_hi,
        start=start,
        end=end,
        group=group,
        sample=sample,
    )
    if not (zone.key_lo <= zone.key_hi <= MAX_MIDI and zone.vel_lo <= zone.vel_hi <= MAX_MIDI):
        raise ExsError(f"zone {zone.name!r} has its ranges the wrong way round")
    if not 0 <= zone.start < zone.end:
        raise ExsError(f"zone {zone.name!r} plays frames {zone.start}..{zone.end}")
    return zone


def _group(chunk: bytes, at: int) -> ExsGroup:
    if len(chunk) <= GROUP_VOLUME_AT:
        raise ExsError(f"the group at byte {at} is too short to hold its level")
    (volume,) = struct.unpack_from("<b", chunk, GROUP_VOLUME_AT)
    return ExsGroup(name=_text(chunk, NAME_AT, NAME_BYTES), volume_db=volume)


def _sample(chunk: bytes, at: int) -> ExsSample:
    if len(chunk) < SAMPLE_FILE_AT + PATH_BYTES:
        raise ExsError(f"the sample at byte {at} is too short to name its file")
    frames, rate, bits = struct.unpack_from("<III", chunk, SAMPLE_FRAMES_AT)
    name = _text(chunk, NAME_AT, NAME_BYTES)
    return ExsSample(
        name=name,
        folder=_text(chunk, SAMPLE_FOLDER_AT, PATH_BYTES),
        file=_text(chunk, SAMPLE_FILE_AT, PATH_BYTES) or name,
        frames=frames,
        rate=rate,
        bits=bits,
    )


def _check_references(
    zones: list[ExsZone], groups: list[ExsGroup], samples: list[ExsSample]
) -> None:
    for zone in zones:
        if not 0 <= zone.sample < len(samples):
            raise ExsError(f"zone {zone.name!r} plays sample {zone.sample}, which is not there")
        if not -1 <= zone.group < len(groups):
            raise ExsError(f"zone {zone.name!r} is in group {zone.group}, which is not there")
        if zone.end > samples[zone.sample].frames:
            raise ExsError(f"zone {zone.name!r} ends past the end of its sample")


def _text(chunk: bytes, at: int, size: int) -> str:
    # Logic writes MacRoman; every name in the factory library is plain ASCII.
    return chunk[at : at + size].split(b"\0", 1)[0].decode("mac_roman").strip()
