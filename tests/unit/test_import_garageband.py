"""The import script, run against a stand-in GarageBand library and a stand-in Live.

`afconvert` is macOS's and CI runs on Linux, so decoding is replaced by a WAV made here. What
is tested is what the script decides on its own: where it reads and writes, what it says when
something is missing, and that a second run changes nothing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from exs_bytes import Sample, Zone, exs
from live_templates import EQ_THREE, RACK, SATURATOR
from test_sounds_audio import ramp

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "session.toml"


def _load() -> ModuleType:
    path = ROOT / "scripts" / "import_garageband.py"
    spec = importlib.util.spec_from_file_location("import_garageband", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["import_garageband"] = module
    spec.loader.exec_module(module)
    return module


importer = _load()


def a_guitar(folder: Path) -> bytes:
    """Two strings, ringing and muted: enough for every part of the script to have work."""
    zones = [
        Zone(root=40, key_lo=36, key_hi=44, vel_lo=0, vel_hi=113, start=0, end=100, group=0),
        Zone(root=40, key_lo=36, key_hi=44, vel_lo=114, vel_hi=127, start=100, end=200, group=0),
        Zone(root=40, key_lo=36, key_hi=44, start=200, end=260, group=1),
        Zone(root=45, key_lo=45, key_hi=49, start=300, end=400, group=2),
        Zone(root=45, key_lo=45, key_hi=49, start=400, end=450, group=3),
    ]
    groups = [("6 E_Main", 0), ("6 E_Mute", 0), ("5 A_Main", 0), ("5 A_Mute", 0)]
    return exs(zones, groups, [Sample("guitar.caf", frames=1000, folder=str(folder))])


@pytest.fixture
def garageband(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    instruments = tmp_path / "Sampler Instruments"
    samples = tmp_path / "EXS Factory Samples"
    for source in importer.GUITARS:
        exs_file = instruments / source.exs
        exs_file.parent.mkdir(parents=True, exist_ok=True)
        exs_file.write_bytes(a_guitar(samples))
    samples.mkdir()
    (samples / "guitar.caf").write_bytes(b"stand-in")
    monkeypatch.setattr(importer, "LOGIC_INSTRUMENTS", instruments)
    monkeypatch.setattr(importer, "SAMPLE_ROOTS", (samples,))
    monkeypatch.setattr(importer, "_decoded", lambda source, bits, scratch: ramp(1000))
    monkeypatch.setattr(
        importer,
        "_templates",
        lambda live: importer.Templates(rack=RACK, saturator=SATURATOR, eq=EQ_THREE),
    )
    return tmp_path / "User Library"


def files_under(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_a_dry_run_shows_the_zones_and_writes_nothing(
    garageband: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert importer.main(["--dry-run", "--user-library", str(garageband)]) == 0

    out = capsys.readouterr().out
    assert "GB Vintage Strat — from Test Guitar, palm mute below velocity 80" in out
    assert "E2 E mute" in out and "A2 A main" in out
    assert not garageband.exists()


def test_each_guitar_becomes_a_crunch_and_a_heavy_preset_over_one_set_of_samples(
    garageband: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert importer.main(["--user-library", str(garageband)]) == 0

    presets = garageband / "Presets/Instruments/Instrument Rack/GARAGEM"
    assert sorted(p.name for p in presets.iterdir()) == [
        "GB Vintage Strat Heavy.adg",
        "GB Vintage Strat.adg",
        "GB Warm Electric Heavy.adg",
        "GB Warm Electric.adg",
    ]
    strat = sorted(p.name for p in (garageband / "Samples/GARAGEM/GB Vintage Strat").iterdir())
    assert strat == ["001 40.wav", "002 40.wav", "003 40.wav", "004 45.wav", "005 45.wav"]
    out = capsys.readouterr().out
    assert "Drag GB Vintage Strat onto the GTR track" in out
    assert "palm_mute_below = 80" in out


def test_a_second_run_writes_the_same_bytes_and_leaves_nothing_stale(garageband: Path) -> None:
    importer.main(["--user-library", str(garageband)])
    first = files_under(garageband)
    stale = garageband / "Samples/GARAGEM/GB Vintage Strat/999 old.wav"
    stale.write_bytes(b"from an earlier mapping")

    importer.main(["--user-library", str(garageband)])

    assert files_under(garageband) == first


def test_the_split_moves_the_palm_mute(
    garageband: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    importer.main(["--dry-run", "--palm-mute-below", "64", "--user-library", str(garageband)])
    out = capsys.readouterr().out
    assert "palm mute below velocity 64" in out
    assert "1-63" in out and "64-" in out


def test_a_missing_instrument_says_what_to_do_in_garageband(
    garageband: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(importer, "LOGIC_INSTRUMENTS", garageband / "nowhere")

    assert importer.main(["--dry-run"]) == 1

    assert "Open GarageBand once" in capsys.readouterr().err


def test_a_missing_sample_says_how_to_download_garagebands_sounds(
    garageband: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(importer, "SAMPLE_ROOTS", (garageband / "nowhere",))
    for source in importer.GUITARS:
        (importer.LOGIC_INSTRUMENTS / source.exs).write_bytes(a_guitar(garageband / "gone"))

    assert importer.main(["--user-library", str(garageband)]) == 1

    assert "Download All Available Sounds" in capsys.readouterr().err


def test_the_split_is_read_from_the_guitar_track(tmp_path: Path) -> None:
    text = SESSION.read_text(encoding="utf-8")
    declared = text.replace("palm_mute_below = 80", "palm_mute_below = 72", 1)
    assert declared != text
    session = tmp_path / "session.toml"
    session.write_text(declared, encoding="utf-8")

    assert importer._split_from(session) == 72


def test_without_a_declared_split_the_default_is_used(tmp_path: Path) -> None:
    text = SESSION.read_text(encoding="utf-8")
    session = tmp_path / "session.toml"
    session.write_text(text.replace("palm_mute_below", "# palm_mute_below"), encoding="utf-8")

    assert importer._split_from(session) == importer.DEFAULT_PALM_MUTE_BELOW
