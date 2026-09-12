"""Reading Live's Control Surface table out of its own log (`phase-4-findings.md` §8)."""

from __future__ import annotations

from pathlib import Path

from garagem.daw.live_log import (
    ControlSurface,
    control_surfaces,
    latest_log,
    listening_to,
    same_port,
)

# Two tables, as Live writes them: at startup with the MiniLab unplugged, then again when
# it was plugged in. Only the second one is the Set's current state.
LOG = """2026-09-12T13:49:32.914214: info: AMidiIO: Midi Remote Scripts:
  MidiRemoteScript 1 [Control Surface="MiniLab_3" Input="None" Output="None"]
  MidiRemoteScript 2 [Control Surface="AbletonOSC" Input="None" Output="None"]
  MidiRemoteScript 3 [Control Surface="None" Input="None" Output="None"]
2026-09-12T13:49:32.914238: info: AMidiIO: Takeover Mode: None
2026-09-12T13:50:23.532354: info: AMidiIO: Midi Remote Scripts:
  MidiRemoteScript 1 [Control Surface="MiniLab_3" Input="Minilab3 (MIDI)" Output="Minilab3 (MIDI)"]
  MidiRemoteScript 2 [Control Surface="AbletonOSC" Input="None" Output="None"]
  MidiRemoteScript 3 [Control Surface="None" Input="None" Output="None"]
2026-09-12T13:50:23.532381: info: AMidiIO: Takeover Mode: None
2026-09-12T16:22:31.415907: info: Python: INFO:abletonosc:415 - Calling method for scene: fire
"""


def test_the_last_table_in_the_log_is_the_one_that_counts() -> None:
    surfaces = control_surfaces(LOG)
    assert surfaces[0] == ControlSurface(1, "MiniLab_3", "Minilab3 (MIDI)", "Minilab3 (MIDI)")
    assert [surface.slot for surface in surfaces] == [1, 2, 3]


def test_a_log_with_no_table_has_no_surfaces() -> None:
    assert control_surfaces("2026-09-12: info: nothing about MIDI here\n") == ()


def test_live_and_coremidi_spell_the_same_port_differently() -> None:
    assert same_port("Minilab3 (MIDI)", "Minilab3 MIDI")
    assert not same_port("Minilab3 (ALV)", "Minilab3 MIDI")


def test_a_surface_listening_to_the_cue_port_is_found() -> None:
    (clash,) = listening_to(control_surfaces(LOG), "Minilab3 MIDI")
    assert clash.name == "MiniLab_3"


def test_a_surface_with_its_input_set_to_none_is_not_in_the_way() -> None:
    cleared = LOG.replace('Input="Minilab3 (MIDI)"', 'Input="None"')
    assert listening_to(control_surfaces(cleared), "Minilab3 MIDI") == ()


def test_an_empty_slot_is_never_in_the_way() -> None:
    empty = (ControlSurface(3, "None", "Minilab3 (MIDI)", "None"),)
    assert listening_to(empty, "Minilab3 MIDI") == ()


def test_the_most_recently_written_live_log_is_the_one_read(tmp_path: Path) -> None:
    import os

    older = tmp_path / "Live 12.3.1" / "Log.txt"
    newer = tmp_path / "Live 12.4.5" / "Log.txt"
    for path, stamp in ((older, 1_000), (newer, 2_000)):
        path.parent.mkdir()
        path.write_text("", encoding="utf-8")
        os.utime(path, (stamp, stamp))
    assert latest_log(tmp_path) == newer
    assert latest_log(tmp_path / "nowhere") is None
