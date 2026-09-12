"""Listens to the MiniLab 3 and reports every control it hears. Sends nothing.

    uv run python scripts/probe_minilab.py --list
    uv run python scripts/probe_minilab.py --seconds 90
    uv run python scripts/probe_minilab.py --port "Minilab3 MIDI" --seconds 60
    uv run python scripts/probe_minilab.py --verbose   # every message, not only new controls

Stage 0 of the MiniLab plan: before a single cue is mapped, find out what the hardware
actually sends. **No MIDI number is guessed.** A pad that sends note 36 on one mode and a
CC on another is a fact about this unit, its firmware and its current mode, and the only
place to learn it is here — the same reason `probe_live.py` exists for AbletonOSC.

Three questions it answers:

1. **Which ports does each control arrive on?** The MiniLab exposes several (`MIDI`,
   `DIN THRU`, `MCU/HUI`, `ALV`). Live's `MiniLab_3` control-surface script talks on one
   of them; the one the band should listen to is the one that carries pads and knobs
   *without* Live acting on them.
2. **What does each control send?** Note or CC, which channel, which number, what range.
3. **Does Python hear it while Live is open?** CoreMIDI lets several clients read one
   source, and this is where that is confirmed rather than assumed.

**It only reads.** It opens input ports and never an output: sending the MiniLab a SysEx
to change its mode would be changing the instrument to suit the probe. Clock and active
sensing are hidden unless `--all`, because a synced unit sends 24 of them a beat and they
bury the one pad press that matters.

By default a control is printed the first time it is heard, not every time: one turn of a
knob is a hundred messages, and a list of every control touched is what the question needs.
At the end it prints each distinct control once, with how often it was heard and the range
of values it sent. That table is what `controller.toml` is written from in Stage 2.
"""

from __future__ import annotations

import argparse
import queue
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Final

import mido

DEFAULT_MATCH: Final = "minilab"
DEFAULT_SECONDS: Final = 60.0
POLL_S: Final = 0.05

# Timing messages a synced controller sends continuously. Noise for this question.
NOISE: Final[frozenset[str]] = frozenset({"clock", "active_sensing"})


@dataclass(frozen=True, slots=True)
class Control:
    """One physical control as the wire names it: where it came from and what it is."""

    port: str
    kind: str
    channel: int | None
    number: int | None

    def label(self) -> str:
        channel = "-" if self.channel is None else str(self.channel + 1)
        number = "-" if self.number is None else str(self.number)
        return f"{self.port:<20} {self.kind:<16} ch={channel:<3} num={number}"


@dataclass(slots=True)
class Seen:
    """How often a control was heard and the values it sent."""

    count: int = 0
    values: list[int] = field(default_factory=list)


def control_of(port: str, message: mido.Message) -> Control:
    """The identity of the control that sent `message`, independent of its value."""
    kind = str(message.type)
    channel = getattr(message, "channel", None)
    number: int | None = None
    if kind in {"note_on", "note_off"}:
        number = int(message.note)
        # A note-off and a note-on at velocity 0 are the same key released. Grouping them
        # under one kind keeps one pad as one row rather than two.
        kind = "note"
    elif kind == "polytouch":
        # Pressure on a held pad. A row of its own: it streams while the pad is held, and
        # counted with the strikes it made one press look like three hundred.
        number = int(message.note)
    elif kind == "control_change":
        number = int(message.control)
    elif kind == "program_change":
        number = int(message.program)
    return Control(port=port, kind=kind, channel=channel, number=number)


def value_of(message: mido.Message) -> int | None:
    """The part of a message that changes when the same control moves."""
    kind = str(message.type)
    if kind == "note_on":
        return int(message.velocity)
    if kind == "note_off":
        return 0
    if kind == "control_change":
        return int(message.value)
    if kind in {"pitchwheel"}:
        return int(message.pitch)
    if kind in {"aftertouch", "polytouch"}:
        return int(message.value)
    return None


def describe(port: str, message: mido.Message, elapsed_s: float) -> str:
    """One line per message, aligned so a column of pad presses reads at a glance."""
    control = control_of(port, message)
    value = value_of(message)
    shown = "" if value is None else f" value={value}"
    if str(message.type) == "sysex":
        shown = f" bytes={len(message.data)}"
    return f"{elapsed_s:8.2f}s  {control.label()}{shown}  ({message.type})"


def summarise(seen: dict[Control, Seen]) -> str:
    """Each distinct control once: the table `controller.toml` will be written from."""
    if not seen:
        return "nothing was heard. Is the MiniLab on, and is --port right? Try --list.\n"
    lines = [f"{len(seen)} distinct controls:"]
    for control in sorted(seen, key=_order):
        entry = seen[control]
        values = [value for value in entry.values if value is not None]
        span = f"values {min(values)}..{max(values)}" if values else "no values"
        lines.append(f"  {control.label()}  x{entry.count:<4} {span}")
    return "\n".join(lines) + "\n"


def _order(control: Control) -> tuple[str, str, int, int]:
    return (
        control.port,
        control.kind,
        -1 if control.channel is None else control.channel,
        -1 if control.number is None else control.number,
    )


def matching(names: Iterable[str], match: str) -> list[str]:
    """Input ports whose name contains `match`, case-insensitively."""
    wanted = match.lower()
    return [name for name in names if wanted in name.lower()]


def listen(
    ports: list[str],
    seconds: float,
    *,
    include_noise: bool,
    verbose: bool = False,
    write: Callable[[str], object] = sys.stderr.write,
) -> dict[Control, Seen]:
    """Open every port, print what arrives, and return what was seen.

    The rtmidi callback runs on its own thread and only enqueues (the ADR-014 idiom): all
    formatting and printing happens here, on the caller's thread.
    """
    arrived: queue.Queue[tuple[str, mido.Message, float]] = queue.Queue()
    started = time.monotonic()
    opened = []
    seen: dict[Control, Seen] = {}

    def callback_for(port: str) -> Callable[[mido.Message], None]:
        def on_message(message: mido.Message) -> None:
            arrived.put((port, message, time.monotonic() - started))

        return on_message

    try:
        for port in ports:
            opened.append(mido.open_input(port, callback=callback_for(port)))
        write(f"listening on {', '.join(ports)} for {seconds:g}s — touch every control\n")
        while time.monotonic() - started < seconds:
            try:
                port, message, at = arrived.get(timeout=POLL_S)
            except queue.Empty:
                continue
            if str(message.type) in NOISE and not include_noise:
                continue
            control = control_of(port, message)
            new = control not in seen
            entry = seen.setdefault(control, Seen())
            entry.count += 1
            value = value_of(message)
            if value is not None:
                entry.values.append(value)
            if new or verbose:
                write(describe(port, message, at) + "\n")
    except KeyboardInterrupt:
        write("stopped\n")
    finally:
        for port in opened:
            port.close()
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list MIDI ports and exit")
    parser.add_argument(
        "--port",
        default=DEFAULT_MATCH,
        help="listen to input ports whose name contains this (default: every MiniLab port)",
    )
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--all", action="store_true", help="include clock and active sensing")
    parser.add_argument("--verbose", action="store_true", help="print every message")
    args = parser.parse_args()

    inputs = list(mido.get_input_names())
    if args.list:
        sys.stderr.write("inputs:\n" + "".join(f"  {name}\n" for name in inputs))
        sys.stderr.write("outputs:\n" + "".join(f"  {name}\n" for name in mido.get_output_names()))
        return 0

    ports = matching(inputs, args.port)
    if not ports:
        sys.stderr.write(
            f"no input port matches {args.port!r}; found {inputs or 'none'}. "
            "Is the MiniLab connected?\n"
        )
        return 1

    seen = listen(ports, args.seconds, include_noise=args.all, verbose=args.verbose)
    sys.stderr.write(summarise(seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
