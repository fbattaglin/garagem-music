"""The MiniLab probe's bookkeeping, with messages built in memory and no port opened.

What matters is that one physical control is one row: a pad pressed and released is one
control, whatever its value, so the summary it prints is the list `controller.toml` gets
written from. Listening itself needs the hardware and is run by hand.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import mido

ROOT = Path(__file__).resolve().parents[2]
PORT = "Minilab3 MIDI"


def _load() -> ModuleType:
    path = ROOT / "scripts" / "probe_minilab.py"
    spec = importlib.util.spec_from_file_location("probe_minilab", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["probe_minilab"] = module
    spec.loader.exec_module(module)
    return module


probe = _load()


def test_a_pad_pressed_and_released_is_one_control() -> None:
    press = mido.Message("note_on", channel=9, note=36, velocity=100)
    release = mido.Message("note_off", channel=9, note=36, velocity=0)
    assert probe.control_of(PORT, press) == probe.control_of(PORT, release)


def test_the_same_knob_at_two_values_is_one_control() -> None:
    low = mido.Message("control_change", channel=0, control=74, value=3)
    high = mido.Message("control_change", channel=0, control=74, value=120)
    assert probe.control_of(PORT, low) == probe.control_of(PORT, high)


def test_the_same_number_on_another_port_is_another_control() -> None:
    """The ports are the question: which one carries the pads without Live acting on them."""
    message = mido.Message("note_on", note=36, velocity=100)
    assert probe.control_of(PORT, message) != probe.control_of("Minilab3 ALV", message)


def test_a_note_and_a_cc_with_the_same_number_are_different_controls() -> None:
    note = mido.Message("note_on", note=36, velocity=100)
    cc = mido.Message("control_change", control=36, value=100)
    assert probe.control_of(PORT, note) != probe.control_of(PORT, cc)


def test_values_are_read_from_the_field_that_moves() -> None:
    assert probe.value_of(mido.Message("note_on", note=36, velocity=87)) == 87
    assert probe.value_of(mido.Message("note_off", note=36, velocity=64)) == 0
    assert probe.value_of(mido.Message("control_change", control=1, value=42)) == 42
    assert probe.value_of(mido.Message("sysex", data=[1, 2, 3])) is None


def test_channels_are_printed_the_way_the_hardware_labels_them() -> None:
    """mido counts channels from 0; the MiniLab's own editor counts from 1."""
    line = probe.describe(PORT, mido.Message("note_on", channel=9, note=36, velocity=1), 1.0)
    assert "ch=10" in line
    assert "num=36" in line


def test_the_summary_lists_each_control_once_with_its_range() -> None:
    seen = {
        probe.Control(PORT, "control_change", 0, 74): probe.Seen(count=3, values=[0, 64, 127]),
        probe.Control(PORT, "note", 9, 36): probe.Seen(count=2, values=[100, 0]),
    }
    text = probe.summarise(seen)
    assert "2 distinct controls" in text
    assert "values 0..127" in text
    assert text.index("control_change") < text.index("note")


def test_an_empty_summary_says_what_to_check() -> None:
    assert "--list" in probe.summarise({})


def test_ports_are_matched_by_name_without_case() -> None:
    names = ["Minilab3 MIDI", "Minilab3 ALV", "IAC Driver Bus 1"]
    assert probe.matching(names, "minilab") == ["Minilab3 MIDI", "Minilab3 ALV"]
    assert probe.matching(names, "ALV") == ["Minilab3 ALV"]


def test_pressure_on_a_held_pad_is_not_counted_as_a_strike() -> None:
    """The MiniLab's pads stream polytouch while held; a cue is the strike, not the pressure."""
    strike = mido.Message("note_on", channel=9, note=38, velocity=110)
    pressure = mido.Message("polytouch", channel=9, note=38, value=60)
    assert probe.control_of(PORT, strike) != probe.control_of(PORT, pressure)
    assert probe.control_of(PORT, pressure).number == 38
