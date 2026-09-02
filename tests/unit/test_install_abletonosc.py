"""The installer's unzip, tested with archives built in `tmp_path`. Nothing downloads.

The one genuinely dangerous thing here is that a zip fetched over the network can name
a path outside the folder it is being extracted into. That is what the escape test is
for; the rest checks that a second run leaves the same tree rather than a mixture of
two versions.
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_installer() -> ModuleType:
    path = ROOT / "scripts" / "install_abletonosc.py"
    spec = importlib.util.spec_from_file_location("install_abletonosc", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["install_abletonosc"] = module
    spec.loader.exec_module(module)
    return module


installer = _load_installer()

FILES = {
    "AbletonOSC-master/__init__.py": b"from .manager import Manager\n",
    "AbletonOSC-master/manager.py": b"class Manager: pass\n",
    "AbletonOSC-master/abletonosc/song.py": b"# song handlers\n",
}


def an_archive(tmp_path: Path, files: dict[str, bytes] = FILES) -> Path:
    archive = tmp_path / "abletonosc.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, body in files.items():
            zipped.writestr(name, body)
    return archive


def tree(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_the_top_level_folder_is_stripped(tmp_path: Path) -> None:
    installed = installer.install_from_zip(an_archive(tmp_path), tmp_path / "Remote Scripts")

    assert installed.name == "AbletonOSC"
    assert (installed / "manager.py").is_file()
    assert (installed / "abletonosc" / "song.py").is_file()
    assert not (installed / "AbletonOSC-master").exists()


def test_installing_twice_leaves_the_same_tree(tmp_path: Path) -> None:
    """A second run must not leave a mixture of two versions behind."""
    remote_scripts = tmp_path / "Remote Scripts"
    first = tree(installer.install_from_zip(an_archive(tmp_path), remote_scripts))

    stale = remote_scripts / "AbletonOSC" / "removed_upstream.py"
    stale.write_text("# from an older version\n", encoding="utf-8")
    assert tree(installer.install_from_zip(an_archive(tmp_path), remote_scripts)) == first


def test_a_member_that_escapes_the_target_is_refused(tmp_path: Path) -> None:
    """A zip can name `../../anywhere`, and this one comes off the network."""
    archive = an_archive(tmp_path, FILES | {"AbletonOSC-master/../../evil.py": b"boom\n"})
    with pytest.raises(SystemExit, match="escapes"):
        installer.install_from_zip(archive, tmp_path / "Remote Scripts")
    assert not (tmp_path.parent / "evil.py").exists()


def test_an_archive_that_is_not_abletonosc_is_refused(tmp_path: Path) -> None:
    archive = an_archive(tmp_path, {"something-else/main.py": b"pass\n"})
    with pytest.raises(SystemExit, match="AbletonOSC"):
        installer.install_from_zip(archive, tmp_path / "Remote Scripts")


def test_the_target_is_lives_remote_scripts_folder(tmp_path: Path) -> None:
    assert installer.user_library(tmp_path) == (
        tmp_path / "Music" / "Ableton" / "User Library" / "Remote Scripts"
    )


def test_a_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    remote_scripts = tmp_path / "Remote Scripts"
    monkeypatch.setattr(
        sys, "argv", ["install_abletonosc.py", "--dry-run", "--remote-scripts", str(remote_scripts)]
    )

    assert installer.main() == 0
    assert "would install" in capsys.readouterr().err
    assert not remote_scripts.exists()
