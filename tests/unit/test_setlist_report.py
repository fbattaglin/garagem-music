"""The Wi-Fi-off session read back from the log (`scripts/setlist_report.py`, ADR-025).

The phase gate is a command rather than a reading by eye, so what it exits with is part of
the evidence: 0 when every criterion is met, 1 when one is not.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from garagem.obs import EventLog

ROOT = Path(__file__).resolve().parents[2]
BPM = 132.0


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


report = _load("setlist_report")


def a_session(path: Path, songs: int = 3, *, beats: float = 230 * BPM / 60) -> Path:
    """Three songs from a setlist, one run each, as `jam.py --setlist` logs them."""
    log = EventLog(path)
    for song in range(1, songs + 1):
        log.record("setlist_loaded", 0.0, setlist="first", song=song, title="t", serving="baked")
        for section in range(4):
            log.record("section_generated", float(section), section=section, source="buffer")
            log.record("section_written", float(section), section=section, seed=section)
            log.record("scene_fired", float(section) * 32.0, section=section, slack_bars=1)
        log.record("session_ended", beats, finished=True, bpm=BPM, spent_usd="0.0000")
    log.flush()
    return path


def run(*args: str) -> int:
    return int(report.main())


def test_a_session_that_meets_every_line_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = a_session(tmp_path / "jam.jsonl")
    monkeypatch.setattr(sys, "argv", ["setlist_report.py", "--log", str(path), "--share", "12"])
    assert run() == 0
    printed = capsys.readouterr().err
    assert "3 songs" in printed
    assert "12 of 12 sections played came from a take" in printed


def test_a_session_short_of_its_share_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = a_session(tmp_path / "jam.jsonl")
    monkeypatch.setattr(sys, "argv", ["setlist_report.py", "--log", str(path), "--share", "20"])
    assert run() == 1
    assert "at least 20 sections" in capsys.readouterr().err


def test_two_songs_are_short_of_ten_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = a_session(tmp_path / "jam.jsonl", songs=2)
    monkeypatch.setattr(sys, "argv", ["setlist_report.py", "--log", str(path)])
    assert run() == 1
    assert "2 songs" in capsys.readouterr().err


def test_a_log_that_is_not_there_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["setlist_report.py", "--log", str(tmp_path / "nothing.jsonl")]
    )
    assert run() == 1
    assert "does not exist" in capsys.readouterr().err
