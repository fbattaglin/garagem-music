"""The fake controller and the `mido` adapter, both with no hardware.

The adapter's backend is replaced by one that hands `mido.Message` objects to the callback,
which is what rtmidi's thread does. Constructing a `mido.Message` opens nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import mido
import pytest

from garagem.control import (
    ControllerPort,
    ControllerUnavailableError,
    FakeController,
    MidoController,
    load_controller,
)
from garagem.domain import Control, Cue, CueKind, Macro, MacroKind

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_controller(ROOT / "controller.toml")


class Port:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class Backend:
    """What `mido` would be, with a hand on the callback."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.callback: Callable[[Any], None] | None = None
        self.opened: list[str] = []
        self.port = Port()

    def get_input_names(self) -> list[str]:
        return self.names

    def open_input(self, name: str, *, callback: Callable[[Any], None]) -> Port:
        self.opened.append(name)
        self.callback = callback
        return self.port

    def send(self, message: mido.Message) -> None:
        assert self.callback is not None
        self.callback(message)


def collected() -> tuple[list[Control], Callable[[Control], None]]:
    got: list[Control] = []
    return got, got.append


# -------------------------------------------------------------------------------- fake


def test_both_controllers_satisfy_the_port() -> None:
    assert isinstance(FakeController(), ControllerPort)
    assert isinstance(MidoController(SPEC, backend=Backend([SPEC.port])), ControllerPort)


def test_a_fake_that_was_never_started_delivers_nothing() -> None:
    controller = FakeController()
    controller.press(CueKind.STOP)
    assert controller.delivered == []


def test_a_started_fake_delivers_presses_and_turns_in_order() -> None:
    got, handler = collected()
    controller = FakeController()
    controller.start(handler)
    controller.press(CueKind.STOP)
    controller.turn(MacroKind.DENSITY, 0.25)
    assert got == [Cue(kind=CueKind.STOP), Macro(kind=MacroKind.DENSITY, value=0.25)]


def test_raw_midi_into_the_fake_goes_through_the_real_mapping() -> None:
    got, handler = collected()
    controller = FakeController(SPEC)
    controller.start(handler)
    controller.receive("note_on", 9, 40, 90)
    controller.receive("polytouch", 9, 40, 90)
    assert got == [Cue(kind=CueKind.CHORUS_NOW)]


def test_a_stopped_fake_delivers_nothing_and_stopping_twice_is_safe() -> None:
    got, handler = collected()
    controller = FakeController()
    controller.start(handler)
    controller.stop()
    controller.stop()
    controller.press(CueKind.END)
    assert got == []
    assert controller.stopped == 1


def test_an_unplugged_fake_refuses_to_start() -> None:
    with pytest.raises(ControllerUnavailableError):
        FakeController(available=False).start(lambda control: None)


# -------------------------------------------------------------------------------- mido


def test_the_adapter_opens_exactly_the_port_the_spec_names() -> None:
    backend = Backend(["Minilab3 MIDI", "Minilab3 DIN THRU", "Minilab3 MCU/HUI", "Minilab3 ALV"])
    MidoController(SPEC, backend=backend).start(lambda control: None)
    assert backend.opened == ["Minilab3 MIDI"]


def test_a_missing_port_is_refused_and_the_error_lists_what_is_there() -> None:
    backend = Backend(["IAC Driver Bus 1"])
    with pytest.raises(ControllerUnavailableError, match="IAC Driver Bus 1"):
        MidoController(SPEC, backend=backend).start(lambda control: None)
    assert backend.opened == []


def test_a_pad_strike_arrives_as_its_cue() -> None:
    backend = Backend([SPEC.port])
    got, handler = collected()
    MidoController(SPEC, backend=backend).start(handler)
    backend.send(mido.Message("note_on", channel=9, note=36, velocity=110))
    assert got == [Cue(kind=CueKind.STOP)]


def test_releases_pressure_and_keys_arrive_as_nothing() -> None:
    backend = Backend([SPEC.port])
    got, handler = collected()
    MidoController(SPEC, backend=backend).start(handler)
    backend.send(mido.Message("note_off", channel=9, note=36, velocity=0))
    backend.send(mido.Message("polytouch", channel=9, note=36, value=80))
    backend.send(mido.Message("note_on", channel=0, note=36, velocity=100))
    backend.send(mido.Message("clock"))
    assert got == []


def test_a_knob_arrives_as_its_macro() -> None:
    backend = Backend([SPEC.port])
    got, handler = collected()
    MidoController(SPEC, backend=backend).start(handler)
    backend.send(mido.Message("control_change", channel=0, control=71, value=127))
    assert got == [Macro(kind=MacroKind.TENSION, value=1.0)]


def test_stopping_closes_the_port_and_later_messages_are_ignored() -> None:
    backend = Backend([SPEC.port])
    got, handler = collected()
    controller = MidoController(SPEC, backend=backend)
    controller.start(handler)
    callback = backend.callback
    controller.stop()
    controller.stop()
    assert backend.port.closed
    assert callback is not None
    callback(mido.Message("note_on", channel=9, note=36, velocity=110))
    assert got == []
