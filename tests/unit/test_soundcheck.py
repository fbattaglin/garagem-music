"""The sound check: a verse, a bridge and a chorus, looping, written before Live plays."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from garagem.daw import ClipAddress, FakeDawAdapter, load_session
from garagem.domain import Instrument

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_session(ROOT / "session.toml")


def _load() -> ModuleType:
    path = ROOT / "scripts" / "soundcheck.py"
    spec = importlib.util.spec_from_file_location("soundcheck", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["soundcheck"] = module
    spec.loader.exec_module(module)
    return module


soundcheck = _load()


def a_set(**extra: object) -> FakeDawAdapter:
    base: dict[str, object] = {
        "track_names": [track.name for track in SPEC.tracks],
        "device_names": [(track.instrument,) for track in SPEC.tracks],
        "scenes": len(SPEC.scenes),
        "tempo_bpm": SPEC.tempo_bpm,
        "quantization": SPEC.quantization,
    }
    return FakeDawAdapter(**(base | extra))  # type: ignore[arg-type]


def answers(*typed: str) -> object:
    it: Iterator[str] = iter(typed)

    def ask(prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return ask


def run(
    daw: FakeDawAdapter,
    monkeypatch: pytest.MonkeyPatch,
    *argv: str,
    typed: tuple[str, ...] = ("q",),
) -> int:
    monkeypatch.setattr(soundcheck, "build_adapter", lambda host, timeout_s: daw)
    monkeypatch.setattr(sys, "argv", ["soundcheck.py", *argv])
    return int(soundcheck.main(answers(*typed)))


def test_it_writes_three_looping_sections_then_plays_the_verse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daw = a_set()
    assert run(daw, monkeypatch, typed=("c", "q")) == 0
    assert daw.fired == [0, 2]
    for scene in range(3):
        assert daw.clip_looping(ClipAddress(track=0, scene=scene))
    assert daw.calls.index("start_playing") > max(
        index for index, call in enumerate(daw.calls) if call == "write_notes"
    )
    assert "stop_playing" in daw.calls


def test_the_chorus_has_the_organ_and_the_verse_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    daw = a_set()
    run(daw, monkeypatch)
    keys = SPEC.tracks[[t.role for t in SPEC.tracks].index("keys")].index
    assert daw.read_notes(ClipAddress(track=keys, scene=0)) == ()
    assert daw.read_notes(ClipAddress(track=keys, scene=2)) != ()


def test_only_one_role_leaves_the_rest_of_the_band_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    daw = a_set()
    run(daw, monkeypatch, "--only", "guitar")
    tracks = soundcheck.tracks_of(SPEC)
    assert daw.read_notes(ClipAddress(track=tracks[Instrument.GUITAR], scene=2)) != ()
    assert daw.read_notes(ClipAddress(track=tracks[Instrument.DRUMS], scene=2)) == ()


def test_a_set_that_is_playing_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    daw = a_set()
    daw.start_playing()
    daw.calls.clear()
    assert run(daw, monkeypatch) == 1
    assert "write_notes" not in daw.calls
    assert "stop_playing" not in daw.calls


def test_a_set_without_enough_scenes_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    daw = a_set(scenes=2)
    assert run(daw, monkeypatch) == 1
    assert "write_notes" not in daw.calls


def test_a_wrong_instrument_is_reported_but_does_not_stop_the_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Choosing instruments is what the sound check is for."""
    devices = [(track.instrument,) for track in SPEC.tracks]
    devices[2] = ("Drift",)  # a sound being tried on the guitar
    daw = a_set(device_names=devices)
    assert run(daw, monkeypatch) == 0
    assert "wrong_instrument" in capsys.readouterr().err
