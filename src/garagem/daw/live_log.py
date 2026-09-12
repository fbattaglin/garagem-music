"""What Live's own log says about its control surfaces — the only place they can be read.

Found at Stage 2's gate (`phase-4-findings.md` §8). Live's `MiniLab_3` control-surface script
listens to `Minilab3 (MIDI)`, the same port the band's cues come from, so every pad, knob and
button reaches both, and Live's surface acts on some of them. It was first blamed for a song
that stopped at bar 5; the arrangement loop was the cause. But a surface that can switch the
loop on from a pad has no business on the port a person conducts the band from.

AbletonOSC exposes no list of control surfaces (`application.py` answers only the version
and the CPU load). But Live writes the whole table to `Log.txt` each time it opens its MIDI
devices — at startup, when a controller is plugged in, when a setting changes:

    AMidiIO: Midi Remote Scripts:
      MidiRemoteScript 1 [Control Surface="MiniLab_3" Input="Minilab3 (MIDI)" Output=...]
      MidiRemoteScript 2 [Control Surface="AbletonOSC" Input="None" Output="None"]

So **the last table in the log is the current one**. Reading it is a heuristic with a known
edge — a log Live has not flushed yet — and that is why a missing table is a warning and
not a refusal.

**Live and CoreMIDI spell a port differently**: Live writes `Minilab3 (MIDI)` for what `mido`
calls `Minilab3 MIDI`. `same_port` is the one place that difference is absorbed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

HEADER: Final = "Midi Remote Scripts:"
NONE: Final = "None"
REMOTE_SCRIPT: Final = re.compile(
    r'MidiRemoteScript (\d+) \[Control Surface="([^"]*)" Input="([^"]*)" Output="([^"]*)"\]'
)
DEFAULT_PREFERENCES: Final = Path.home() / "Library" / "Preferences" / "Ableton"


@dataclass(frozen=True, slots=True)
class ControlSurface:
    """One row of Live's Control Surface table."""

    slot: int
    name: str
    input: str
    output: str

    @property
    def active(self) -> bool:
        return self.name != NONE


def control_surfaces(log_text: str) -> tuple[ControlSurface, ...]:
    """The last Control Surface table Live logged, or `()` if it never logged one."""
    last = log_text.rfind(HEADER)
    if last < 0:
        return ()
    surfaces: list[ControlSurface] = []
    for line in log_text[last:].splitlines()[1:]:
        match = REMOTE_SCRIPT.search(line)
        if match is None:
            break
        slot, name, port_in, port_out = match.groups()
        surfaces.append(ControlSurface(slot=int(slot), name=name, input=port_in, output=port_out))
    return tuple(surfaces)


def same_port(live_name: str, midi_name: str) -> bool:
    """`Minilab3 (MIDI)` as Live writes it and `Minilab3 MIDI` as CoreMIDI does are one port."""
    return _normal(live_name) == _normal(midi_name)


def listening_to(surfaces: tuple[ControlSurface, ...], port: str) -> tuple[ControlSurface, ...]:
    """The active control surfaces whose input is `port`."""
    return tuple(
        surface for surface in surfaces if surface.active and same_port(surface.input, port)
    )


def latest_log(preferences: Path = DEFAULT_PREFERENCES) -> Path | None:
    """The `Log.txt` of the Live version that ran most recently, if there is one."""
    logs = [path for path in preferences.glob("Live */Log.txt") if path.is_file()]
    return max(logs, key=lambda path: path.stat().st_mtime) if logs else None


def _normal(name: str) -> str:
    return " ".join(re.sub(r"[()]", " ", name).split()).lower()
