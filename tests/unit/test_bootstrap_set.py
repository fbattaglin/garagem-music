"""The bootstrap script's decisions, exercised with Ableton closed.

The script itself is thin — `session.py` holds the logic — so what is tested here is
exactly what the script decides on its own: when it refuses to run, what it writes, and
what its exit code means. The `importlib` idiom is the one `test_bench_latency.py`
already uses to drive a `scripts/` module.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from garagem.daw import DawUnavailableError, FakeDawAdapter, Quantization

ROOT = Path(__file__).resolve().parents[2]


def _load_bootstrap() -> ModuleType:
    path = ROOT / "scripts" / "bootstrap_set.py"
    spec = importlib.util.spec_from_file_location("bootstrap_set", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap_set"] = module
    spec.loader.exec_module(module)
    return module


bootstrap = _load_bootstrap()


def matching_daw(**extra: object) -> FakeDawAdapter:
    base: dict[str, object] = {
        "track_names": ("DRUMS", "BASS", "GTR", "KEYS"),
        "scenes": 2,
        "tempo_bpm": 132.0,
        "quantization": Quantization.BAR,
    }
    return FakeDawAdapter(**(base | extra))  # type: ignore[arg-type]


def run(daw: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(bootstrap, "build_adapter", lambda host, timeout_s: daw)
    monkeypatch.setattr(sys, "argv", ["bootstrap_set.py", *argv])
    exit_code = bootstrap.main()
    assert isinstance(exit_code, int)
    return exit_code


def test_a_matching_set_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(matching_daw(), monkeypatch) == 0
    assert "matches" in capsys.readouterr().err


def test_a_diverged_set_exits_one_and_says_what_to_do(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    daw = matching_daw(track_names=("DRUMS", "BAIXO", "GTR", "KEYS"))
    assert run(daw, monkeypatch) == 1

    report = capsys.readouterr().err
    assert "fix: [track_name]" in report
    assert "--apply" in report


def test_check_mode_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default has to be safe: a check that repairs is not a check."""
    daw = matching_daw(tempo_bpm=120.0)
    run(daw, monkeypatch)
    assert not [call for call in daw.calls if call.startswith("set_")]


def test_applying_repairs_the_set_and_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    daw = matching_daw(tempo_bpm=120.0, quantization=Quantization.NONE)
    assert run(daw, monkeypatch, "--apply") == 0
    assert (daw.tempo(), daw.quantization()) == (132.0, Quantization.BAR)


def test_it_refuses_to_write_while_live_is_playing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Invariant 6: nothing gets rewritten under a Set that is sounding."""
    daw = matching_daw(tempo_bpm=120.0)
    daw.start_playing()
    assert run(daw, monkeypatch, "--apply") == 1

    assert "invariant 6" in capsys.readouterr().err
    assert "set_tempo" not in daw.calls


def test_force_overrides_the_playing_check(monkeypatch: pytest.MonkeyPatch) -> None:
    daw = matching_daw(tempo_bpm=120.0)
    daw.start_playing()
    assert run(daw, monkeypatch, "--apply", "--force") == 0
    assert daw.tempo() == 132.0


def test_the_script_defaults_to_the_shipped_session_file() -> None:
    """A default that points somewhere else would check a Set nobody described."""
    assert bootstrap.DEFAULT_SESSION == ROOT / "session.toml"
    assert bootstrap.DEFAULT_SESSION.is_file()


def test_a_closed_live_is_reported_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The most common outcome by far, so it must not arrive as a traceback."""
    daw = matching_daw(fail_with=DawUnavailableError("Ableton Live did not answer"), fail_after=0)

    assert run(daw, monkeypatch) == 1
    assert "did not answer" in capsys.readouterr().err
