"""`controller.toml`: which physical control asks for what — "Controller as Code".

The same idiom as `session.toml` (ADR-013): a file a person can read and argue with, a
loader that refuses anything unplayable and names the entry, and no numbers in code. Every
number in the shipped file was *heard* from the real MiniLab by `scripts/probe_minilab.py`
(`phase-4-findings.md` §7) rather than read from a manual.

**Channels are written 1 to 16, as the MiniLab's own editor labels them**, and compared against
the wire's 0 to 15 in exactly one place, `ControllerSpec.translate`. The pads arrive on what
the wire calls channel 9 and every human calls channel 10; a file written in wire numbers
would be wrong in the way nobody spots.

**A cue is a strike.** `translate` answers a `note_on` with velocity above zero and nothing
else — not the release, and not the polytouch pressure a held pad streams, or one press
would cue again every few milliseconds.

`translate` takes the message's fields rather than a `mido.Message`, so this module needs no
MIDI library and the mapping is testable with four integers.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from garagem.control.errors import ControllerSpecError
from garagem.domain import Control, Cue, CueKind, Macro, MacroKind

SCHEMA: Final = 1
CHANNELS: Final[tuple[int, int]] = (1, 16)
DATA_RANGE: Final[tuple[int, int]] = (0, 127)
DATA_MAX: Final = 127
NOTE_ON: Final = "note_on"
CONTROL_CHANGE: Final = "control_change"


@dataclass(frozen=True, slots=True)
class PadSpec:
    """A pad: the note it sends on a channel, and the cue it asks for."""

    channel: int
    note: int
    cue: CueKind


@dataclass(frozen=True, slots=True)
class KnobSpec:
    """A knob or fader: the CC it sends on a channel, and the macro it sets."""

    channel: int
    cc: int
    macro: MacroKind


@dataclass(frozen=True, slots=True)
class ControllerSpec:
    """The controller the band listens to, and what each of its controls means."""

    port: str
    quantum_bars: int
    pads: tuple[PadSpec, ...]
    knobs: tuple[KnobSpec, ...]

    def translate(self, kind: str, channel: int, number: int, value: int) -> Control | None:
        """The control a MIDI message asks for, or `None` for everything else.

        `channel` is the wire's 0 to 15. `number` is the note or the CC, `value` the velocity
        or the CC value. Linear over a handful of entries, which is cheaper than a lookup
        table would be to keep in step with the file.
        """
        human = channel + 1
        if kind == NOTE_ON and value > 0:
            for pad in self.pads:
                if pad.channel == human and pad.note == number:
                    return Cue(kind=pad.cue)
            return None
        if kind == CONTROL_CHANGE:
            for knob in self.knobs:
                if knob.channel == human and knob.cc == number:
                    return Macro(kind=knob.macro, value=min(max(value, 0), DATA_MAX) / DATA_MAX)
        return None

    def legend(self) -> str:
        """What each control does, for the person about to press them."""
        lines = [f"{self.port}, cues land {self._quantum()}:"]
        lines += [f"  pad  ch{pad.channel:<2} note {pad.note:<3} -> {pad.cue}" for pad in self.pads]
        lines += [
            f"  knob ch{knob.channel:<2} cc   {knob.cc:<3} -> {knob.macro}" for knob in self.knobs
        ]
        return "\n".join(lines) + "\n"

    def _quantum(self) -> str:
        return "on the next bar" if self.quantum_bars == 1 else f"within {self.quantum_bars} bars"


def load_controller(path: Path) -> ControllerSpec:
    """Read and validate `controller.toml`. Every refusal names the file and the entry."""
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA:
        raise ControllerSpecError(f"{path}: schema must be {SCHEMA}, got {raw.get('schema')!r}")

    controller = raw.get("controller", {})
    port = controller.get("port", "")
    if not isinstance(port, str) or not port.strip():
        raise ControllerSpecError(f"{path}: [controller] port must name a MIDI input")
    quantum = controller.get("quantum_bars", 1)
    if not isinstance(quantum, int) or isinstance(quantum, bool) or quantum < 1:
        raise ControllerSpecError(
            f"{path}: [controller] quantum_bars must be a whole number of bars, got {quantum!r}"
        )

    pads = tuple(_pad(path, number, entry) for number, entry in _numbered(raw, "pad"))
    knobs = tuple(_knob(path, number, entry) for number, entry in _numbered(raw, "knob"))
    if not pads and not knobs:
        raise ControllerSpecError(f"{path}: maps no [[pad]] and no [[knob]]; nothing to listen to")

    _unique(path, "pad", [(pad.channel, pad.note) for pad in pads], "note")
    _unique(path, "knob", [(knob.channel, knob.cc) for knob in knobs], "cc")
    return ControllerSpec(port=port, quantum_bars=quantum, pads=pads, knobs=knobs)


def _numbered(raw: dict[str, Any], table: str) -> list[tuple[int, dict[str, Any]]]:
    entries: Sequence[dict[str, Any]] = raw.get(table, [])
    return [(number, entry) for number, entry in enumerate(entries, start=1)]


def _pad(path: Path, number: int, entry: dict[str, Any]) -> PadSpec:
    where = f"{path}: [[pad]] #{number}"
    return PadSpec(
        channel=_ranged(where, entry, "channel", CHANNELS),
        note=_ranged(where, entry, "note", DATA_RANGE),
        cue=_member(where, entry, "cue", CueKind),
    )


def _knob(path: Path, number: int, entry: dict[str, Any]) -> KnobSpec:
    where = f"{path}: [[knob]] #{number}"
    return KnobSpec(
        channel=_ranged(where, entry, "channel", CHANNELS),
        cc=_ranged(where, entry, "cc", DATA_RANGE),
        macro=_member(where, entry, "macro", MacroKind),
    )


def _ranged(where: str, entry: dict[str, Any], key: str, bounds: tuple[int, int]) -> int:
    value = entry.get(key)
    low, high = bounds
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ControllerSpecError(
            f"{where}: {key} must be a whole number {low}-{high}, got {value!r}"
        )
    return value


def _member[E: (CueKind, MacroKind)](
    where: str, entry: dict[str, Any], key: str, enum: type[E]
) -> E:
    value = entry.get(key)
    try:
        return enum(str(value))
    except ValueError as exc:
        known = ", ".join(member.value for member in enum)
        raise ControllerSpecError(f"{where}: unknown {key} {value!r}. Known: {known}") from exc


def _unique(path: Path, table: str, keys: list[tuple[int, int]], number: str) -> None:
    seen: set[tuple[int, int]] = set()
    for channel, value in keys:
        if (channel, value) in seen:
            raise ControllerSpecError(
                f"{path}: two [[{table}]] entries listen to channel {channel} {number} {value}; "
                "one physical control can ask for one thing"
            )
        seen.add((channel, value))
