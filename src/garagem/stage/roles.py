"""Where `session.toml`'s roles meet the band's instruments.

`session.toml` names roles; the engines name instruments. This is the one place the two
vocabularies meet, and it is a table rather than a convention so a renamed track cannot
quietly send the bass to the drum machine. It moved here from `scripts/jam.py` when a second
script, the sound check, needed it (ADR-028).
"""

from __future__ import annotations

from typing import Final

from garagem.daw import SessionSpec
from garagem.domain import Instrument

ROLE_TO_INSTRUMENT: Final[dict[str, Instrument]] = {
    "drums": Instrument.DRUMS,
    "bass": Instrument.BASS,
    "guitar": Instrument.GUITAR,
    "keys": Instrument.KEYS,
    "lead": Instrument.LEAD,
    "guitar_double": Instrument.GUITAR_DOUBLE,
}

# Roles a Set may leave out and still be played. The second guitar is new in Phase 8 and
# made from the first (ADR-028): a Set without its track plays one guitar, as it always did.
OPTIONAL_ROLES: Final[frozenset[str]] = frozenset({"guitar_double"})


def tracks_of(spec: SessionSpec) -> dict[Instrument, int]:
    """Which Live track each instrument plays on, from the Set spec."""
    return {
        ROLE_TO_INSTRUMENT[track.role]: track.index
        for track in spec.tracks
        if track.role in ROLE_TO_INSTRUMENT
    }


def missing_roles(spec: SessionSpec) -> list[str]:
    """The roles the band cannot play without and the Set does not have."""
    present = {track.role for track in spec.tracks}
    return sorted(set(ROLE_TO_INSTRUMENT) - OPTIONAL_ROLES - present)


def palms_of(spec: SessionSpec) -> dict[Instrument, int]:
    """The velocity each guitar's sampler splits palm mute from sustain at (ADR-028)."""
    return {
        ROLE_TO_INSTRUMENT[track.role]: track.palm_mute_below
        for track in spec.tracks
        if track.role in ROLE_TO_INSTRUMENT and track.palm_mute_below is not None
    }


def pitches_of(spec: SessionSpec) -> dict[Instrument, dict[int, int]]:
    """What each instrument's Live device answers to, from the Set spec (ADR-013)."""
    return {
        ROLE_TO_INSTRUMENT[track.role]: dict(track.pitches)
        for track in spec.tracks
        if track.role in ROLE_TO_INSTRUMENT and track.pitches
    }
