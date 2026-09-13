"""The offline rehearsal of Stage 6's session: what it replays, and that it plays."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from garagem.domain import Cue, CueKind, Macro, MacroKind
from garagem.obs import Event

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "rehearse_session.py"
    spec = importlib.util.spec_from_file_location("rehearse_session", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rehearse_session"] = module
    spec.loader.exec_module(module)
    return module


rehearsal = _load()


def a_run(*controls: tuple[float, dict[str, str | float]]) -> list[Event]:
    return [
        Event(at_beats=0.0, kind="scene_fired", detail={"first": True, "section": 0}),
        *(Event(at_beats=at, kind="cue_received", detail=detail) for at, detail in controls),
        Event(at_beats=40.0, kind="scene_fired", detail={"first": False, "section": 1}),
    ]


def test_only_performances_that_were_conducted_are_replayed() -> None:
    silent = a_run()
    first = a_run((8.0, {"cue": "stop"}))
    second = a_run((12.0, {"cue": "fill"}))
    runs = rehearsal.conducted_runs([*first, *silent, *second], runs=2)
    assert [len(run) for run in runs] == [3, 3]
    assert runs[1][1].detail["cue"] == "fill"


def test_end_is_left_out_and_the_runs_repeat_until_the_song_is_over() -> None:
    run = a_run(
        (8.0, {"cue": "end"}),
        (9.0, {"cue": "stop"}),
        (10.0, {"macro": "density", "value": 1.0}),
    )
    strikes = rehearsal.conducting([run], "all", until_beat=80)
    assert strikes[9] == [Cue(kind=CueKind.STOP)]
    assert strikes[10] == [Macro(kind=MacroKind.DENSITY, value=1.0)]
    assert strikes[9 + 44] == [Cue(kind=CueKind.STOP)]
    assert all(Cue(kind=CueKind.END) not in controls for controls in strikes.values())


def test_pads_and_knobs_can_be_rehearsed_apart() -> None:
    run = a_run((9.0, {"cue": "stop"}), (10.0, {"macro": "tension", "value": 0.0}))
    assert set(rehearsal.conducting([run], "pads", until_beat=40)) == {9}
    assert set(rehearsal.conducting([run], "knobs", until_beat=40)) == {10}
    assert rehearsal.conducting([run], "none", until_beat=40) == {}


def test_a_short_conducted_rehearsal_plays_to_its_end_and_says_what_it_spent() -> None:
    strikes = {41: [Cue(kind=CueKind.CHORUS_NOW)], 70: [Macro(kind=MacroKind.DENSITY, value=1.0)]}
    log, calls = rehearsal.rehearse(90.0, 7, strikes)
    (ended,) = log.of_kind("session_ended")
    assert ended.detail["finished"] is True
    assert calls > 0
    assert float(str(ended.detail["spent_usd"])) > 0
    assert log.of_kind("cue_applied") and log.of_kind("macro_changed")


def test_a_rehearsal_can_lose_the_network_and_play_on() -> None:
    """The chaos test offline: the network gone from 30 s to 60 s of a 90-second song."""
    log, _ = rehearsal.rehearse(90.0, 7, {}, offline=(30.0, 60.0))
    lost = [
        event
        for event in log.of_kind("fallback")
        if event.detail.get("reason") in ("ProviderUnavailableError", "CircuitOpenError")
    ]
    (ended,) = log.of_kind("session_ended")
    assert lost
    assert ended.detail["finished"] is True
    assert not log.of_kind("beat_lost")
