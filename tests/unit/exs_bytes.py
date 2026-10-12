"""Writes EXS bytes for tests, so no file of Apple's is ever committed (ADR-029).

The layout is the one `garagem.sounds.exs` reads, written from the other side: if the reader's
offsets drift, the round trip in `test_sounds_exs.py` says so.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

ZONE_BODY = 148
GROUP_BODY = 144
SAMPLE_BODY = 600


@dataclass(frozen=True)
class Zone:
    root: int
    key_lo: int
    key_hi: int
    vel_lo: int = 0
    vel_hi: int = 127
    start: int = 0
    end: int = 100
    group: int = 0
    sample: int = 0
    fine: int = 0
    coarse: int = 0
    volume: int = 0
    velocity_on: bool = True
    name: str = "zone"


@dataclass(frozen=True)
class Sample:
    file: str
    frames: int
    folder: str = ""
    rate: int = 44100
    bits: int = 16


def exs(
    zones: list[Zone],
    groups: list[tuple[str, int]],
    samples: list[Sample],
    name: str = "Test Guitar",
) -> bytes:
    """An instrument: its header, then zones, groups and samples, as Logic orders them."""
    out = chunk(0, name, bytes(4))
    out += b"".join(_zone(zone) for zone in zones)
    out += b"".join(_group(group, volume) for group, volume in groups)
    out += b"".join(_sample(sample) for sample in samples)
    return out


def chunk(kind: int, name: str, body: bytes, magic: bytes = b"TBOS") -> bytes:
    signature = 0x00000101 | (kind << 24)
    header = struct.pack("<IIII", signature, len(body), 0, 0) + magic
    return header + _text(name, 64) + body


def _zone(zone: Zone) -> bytes:
    body = bytearray(ZONE_BODY)
    body[0] = 0x08 if zone.velocity_on else 0
    body[1] = zone.root
    struct.pack_into("<b", body, 2, zone.fine)
    struct.pack_into("<b", body, 4, zone.volume)
    body[6], body[7] = zone.key_lo, zone.key_hi
    body[9], body[10] = zone.vel_lo, zone.vel_hi
    struct.pack_into("<ii", body, 12, zone.start, zone.end)
    struct.pack_into("<b", body, 80, zone.coarse)
    struct.pack_into("<ii", body, 88, zone.group, zone.sample)
    return chunk(1, zone.name, bytes(body))


def _group(name: str, volume: int) -> bytes:
    body = bytearray(GROUP_BODY)
    struct.pack_into("<b", body, 0, volume)
    return chunk(2, name, bytes(body))


def _sample(sample: Sample) -> bytes:
    body = bytearray(SAMPLE_BODY)
    struct.pack_into("<III", body, 4, sample.frames, sample.rate, sample.bits)
    body[80:336] = _text(sample.folder, 256)
    body[336:592] = _text(sample.file, 256)
    return chunk(3, sample.file, bytes(body))


def _text(value: str, size: int) -> bytes:
    raw = value.encode("mac_roman")[:size]
    return raw + bytes(size - len(raw))
