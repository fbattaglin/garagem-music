"""`controller.toml`: the shipped file, what a message means, and what the loader refuses.

The shipped mapping is tested against the numbers Stage 0 heard from the real MiniLab
(`phase-4-findings.md` §7), so a typo in the file fails here rather than as a pad that
silently does nothing in front of the person pressing it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from garagem.control import ControllerSpecError, load_controller
from garagem.domain import Cue, CueKind, Macro, MacroKind

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "controller.toml"

# What the MiniLab sent on 2026-09-12. Wire channels are 0-based: the pads' channel 10 is 9.
PAD_CHANNEL = 9
KNOB_CHANNEL = 0
PAD_NOTES = range(36, 44)
KNOB_CCS = (74, 71, 76, 77, 93, 18, 19, 16)

MINIMAL = """
schema = 1

[controller]
port = "Minilab3 MIDI"

[[pad]]
channel = 10
note = 36
cue = "stop"

[[knob]]
channel = 1
cc = 74
macro = "density"
"""


def a_spec(tmp_path: Path, body: str = MINIMAL) -> Path:
    path = tmp_path / "controller.toml"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------- the shipped file


def test_the_shipped_mapping_loads_and_listens_to_the_port_that_carries_the_pads() -> None:
    spec = load_controller(SHIPPED)
    assert spec.port == "Minilab3 MIDI"
    assert spec.quantum_bars == 1


def test_every_shipped_pad_is_a_pad_the_minilab_actually_has() -> None:
    spec = load_controller(SHIPPED)
    assert spec.pads
    assert all(pad.channel == PAD_CHANNEL + 1 and pad.note in PAD_NOTES for pad in spec.pads)


def test_every_shipped_knob_is_a_knob_the_minilab_actually_has() -> None:
    spec = load_controller(SHIPPED)
    assert spec.knobs
    assert all(knob.channel == KNOB_CHANNEL + 1 and knob.cc in KNOB_CCS for knob in spec.knobs)


def test_the_shipped_mapping_offers_every_cue_and_every_macro() -> None:
    spec = load_controller(SHIPPED)
    assert {pad.cue for pad in spec.pads} == set(CueKind)
    assert {knob.macro for knob in spec.knobs} == set(MacroKind)


def test_the_legend_names_every_control_for_the_person_pressing_it() -> None:
    legend = load_controller(SHIPPED).legend()
    assert all(str(kind) in legend for kind in CueKind)
    assert "next bar" in legend


# ------------------------------------------------------------------------------ translate


def test_a_pad_strike_is_its_cue() -> None:
    spec = load_controller(SHIPPED)
    assert spec.translate("note_on", PAD_CHANNEL, 36, 100) == Cue(kind=CueKind.STOP)


def test_releasing_a_pad_asks_for_nothing() -> None:
    spec = load_controller(SHIPPED)
    assert spec.translate("note_on", PAD_CHANNEL, 36, 0) is None
    assert spec.translate("note_off", PAD_CHANNEL, 36, 64) is None


def test_pressure_on_a_held_pad_asks_for_nothing() -> None:
    """The MiniLab streams polytouch while a pad is held; only the strike is a cue."""
    assert load_controller(SHIPPED).translate("polytouch", PAD_CHANNEL, 36, 90) is None


def test_a_key_on_the_keyboard_with_a_pads_note_number_is_not_a_pad() -> None:
    """Keys play on channel 1. Note 36 there is a C, not a stop."""
    assert load_controller(SHIPPED).translate("note_on", KNOB_CHANNEL, 36, 100) is None


def test_a_note_no_pad_is_mapped_to_asks_for_nothing() -> None:
    """All eight pads ask for something since keep and veto took pads 4 and 7 (ADR-024)."""
    assert load_controller(SHIPPED).translate("note_on", PAD_CHANNEL, 44, 100) is None


def test_pads_4_and_7_keep_and_veto_what_is_playing() -> None:
    spec = load_controller(SHIPPED)
    assert spec.translate("note_on", PAD_CHANNEL, 39, 100) == Cue(kind=CueKind.KEEP)
    assert spec.translate("note_on", PAD_CHANNEL, 42, 100) == Cue(kind=CueKind.VETO)


def test_a_knob_is_its_macro_scaled_between_the_stops() -> None:
    spec = load_controller(SHIPPED)
    assert spec.translate("control_change", KNOB_CHANNEL, 74, 0) == Macro(
        kind=MacroKind.DENSITY, value=0.0
    )
    assert spec.translate("control_change", KNOB_CHANNEL, 71, 127) == Macro(
        kind=MacroKind.TENSION, value=1.0
    )


# ------------------------------------------------------------------------------- refusals


def test_a_wrong_schema_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ControllerSpecError, match="schema"):
        load_controller(a_spec(tmp_path, MINIMAL.replace("schema = 1", "schema = 2")))


def test_a_missing_port_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ControllerSpecError, match="port"):
        load_controller(a_spec(tmp_path, MINIMAL.replace('port = "Minilab3 MIDI"', "")))


def test_an_unknown_cue_is_refused_and_names_the_entry_and_the_known_ones(tmp_path: Path) -> None:
    body = MINIMAL.replace('cue = "stop"', 'cue = "chrous_now"')
    with pytest.raises(ControllerSpecError, match=r"\[\[pad\]\] #1.*chrous_now.*chorus_now"):
        load_controller(a_spec(tmp_path, body))


def test_a_channel_written_the_wire_way_is_refused(tmp_path: Path) -> None:
    """0 is not a channel anybody labels; the file uses the MiniLab's own 1-16."""
    body = MINIMAL.replace("channel = 10", "channel = 0")
    with pytest.raises(ControllerSpecError, match="channel must be a whole number 1-16"):
        load_controller(a_spec(tmp_path, body))


def test_one_physical_control_asking_for_two_things_is_refused(tmp_path: Path) -> None:
    body = MINIMAL + '\n[[pad]]\nchannel = 10\nnote = 36\ncue = "fill"\n'
    with pytest.raises(ControllerSpecError, match="one physical control"):
        load_controller(a_spec(tmp_path, body))


@pytest.mark.parametrize("quantum", ["0", "1.5", '"1"', "true"])
def test_a_quantum_that_is_not_a_whole_number_of_bars_is_refused(
    tmp_path: Path, quantum: str
) -> None:
    body = MINIMAL.replace(
        'port = "Minilab3 MIDI"', f'port = "Minilab3 MIDI"\nquantum_bars = {quantum}'
    )
    with pytest.raises(ControllerSpecError, match="quantum_bars"):
        load_controller(a_spec(tmp_path, body))


def test_a_mapping_with_nothing_mapped_is_refused(tmp_path: Path) -> None:
    body = 'schema = 1\n[controller]\nport = "Minilab3 MIDI"\n'
    with pytest.raises(ControllerSpecError, match="nothing to listen to"):
        load_controller(a_spec(tmp_path, body))
