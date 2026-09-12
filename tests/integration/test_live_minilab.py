"""The MiniLab 3, through the real adapter and the real CoreMIDI.

    uv run pytest -m live -q tests/integration/test_live_minilab.py

The offline suite proves every step from a MIDI message to the event log against a fake
backend. What only the hardware can answer is whether `controller.toml`'s port is the one
this machine actually exposes, and whether opening and closing it through `mido` and
`python-rtmidi` is clean. Pressing the pads is the Stage 2 gate, done in a jam by a person,
because a test that waits for a hand is not a test.

Skipped, not failed, when no MiniLab is connected: the rest of `-m live` is about Live.
"""

from __future__ import annotations

from pathlib import Path

import mido
import pytest

from garagem.control import ControllerPort, MidoController, load_controller
from garagem.domain import Control

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_controller(ROOT / "controller.toml")


@pytest.fixture
def connected() -> None:
    if SPEC.port not in mido.get_input_names():
        pytest.skip(f"{SPEC.port!r} is not connected")


def test_the_port_controller_toml_names_is_one_this_machine_exposes(connected: None) -> None:
    assert SPEC.port in mido.get_input_names()


def test_the_minilab_opens_and_closes_cleanly_through_the_adapter(connected: None) -> None:
    heard: list[Control] = []
    controller = MidoController(SPEC)
    assert isinstance(controller, ControllerPort)
    controller.start(heard.append)
    controller.stop()
    controller.stop()
