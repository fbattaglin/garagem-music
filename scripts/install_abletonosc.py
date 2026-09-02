"""Installs AbletonOSC into Live's Remote Scripts folder.

    uv run python scripts/install_abletonosc.py                  # download and install
    uv run python scripts/install_abletonosc.py --dry-run        # say what it would do
    uv run python scripts/install_abletonosc.py --from-zip a.zip # install a local archive

What it **cannot** do, and does not try:

- **Enable the Control Surface.** That lives in Live's own preferences, in a binary
  format nobody should be editing from a script. It is step 1 of the manual follow-up
  printed at the end.
- **Restart Live.** The first time a remote script is installed, `/live/api/reload` is
  not enough — Live has to be quit completely and reopened. Step 2.

Running it twice produces the same tree: the existing install is removed first, so a
half-updated mixture of two versions cannot happen.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Final

# AbletonOSC publishes no releases and its default branch is `master`, so the branch
# archive is the only artefact there is. Pinned here rather than assembled at runtime.
DEFAULT_URL: Final = "https://github.com/ideoforms/AbletonOSC/archive/refs/heads/master.zip"
# GitHub wraps a branch archive in one top-level folder, which gets stripped.
ARCHIVE_PREFIX: Final = "AbletonOSC-master/"
INSTALL_NAME: Final = "AbletonOSC"

FOLLOW_UP: Final = """
Installed. Three things left, and none of them can be scripted:

  1. Live -> Settings -> Link/Tempo/MIDI -> Control Surface -> AbletonOSC, in the
     first FREE slot. Do not overwrite an existing surface — on this machine slot 1
     is the MiniLab 3, which Phase 5 needs, so AbletonOSC goes in slot 2.
  2. Quit Live completely and reopen it. `/live/api/reload` is not enough the first
     time the script is installed.
  3. Verify:  uv run python scripts/probe_live.py

If it does not answer, the log says why — it only appears once the script has loaded
inside Live:

  {log}
"""


def user_library(home: Path | None = None) -> Path:
    """Live's Remote Scripts folder on macOS."""
    return (home or Path.home()) / "Music" / "Ableton" / "User Library" / "Remote Scripts"


def install_from_zip(archive: Path, remote_scripts: Path) -> Path:
    """Extract the archive into `<remote_scripts>/AbletonOSC`, replacing any existing one.

    Members are checked against the target before anything is written: a zip is a file
    format that can name `../../anywhere`, and this one is downloaded from the network.
    """
    target = remote_scripts / INSTALL_NAME
    with zipfile.ZipFile(archive) as zipped:
        members = [
            name
            for name in zipped.namelist()
            if name.startswith(ARCHIVE_PREFIX) and not name.endswith("/")
        ]
        if not members:
            raise SystemExit(f"{archive}: no {ARCHIVE_PREFIX} folder inside — is this AbletonOSC?")

        planned = {name: _safe_destination(name, target) for name in members}
        # Only now that every destination is known to be inside the target.
        if target.exists():
            shutil.rmtree(target)
        for name, destination in planned.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(name) as source, destination.open("wb") as sink:
                shutil.copyfileobj(source, sink)
    return target


def _safe_destination(name: str, target: Path) -> Path:
    """Where this member lands, or a refusal if it lands outside the target."""
    relative = name[len(ARCHIVE_PREFIX) :]
    destination = (target / relative).resolve()
    if not destination.is_relative_to(target.resolve()):
        raise SystemExit(f"refusing to extract {name!r}: it escapes {target}")
    return destination


def download(url: str, into: Path) -> Path:
    """Fetch the archive. Thin on purpose — the interesting logic is in the unzip."""
    archive = into / "abletonosc.zip"
    with urllib.request.urlopen(url) as response, archive.open("wb") as sink:
        shutil.copyfileobj(response, sink)
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--from-zip", type=Path, help="install this archive instead of downloading")
    parser.add_argument("--remote-scripts", type=Path, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would happen, write nothing"
    )
    args = parser.parse_args()

    remote_scripts = args.remote_scripts or user_library()
    target = remote_scripts / INSTALL_NAME

    if args.dry_run:
        source = args.from_zip or args.url
        sys.stderr.write(f"would install {source} into {target}\n")
        if target.exists():
            sys.stderr.write(f"would first remove the existing {target}\n")
        return 0

    remote_scripts.mkdir(parents=True, exist_ok=True)
    if args.from_zip:
        installed = install_from_zip(args.from_zip, remote_scripts)
    else:
        with tempfile.TemporaryDirectory() as scratch:
            sys.stderr.write(f"downloading {args.url}\n")
            installed = install_from_zip(download(args.url, Path(scratch)), remote_scripts)

    sys.stderr.write(f"{installed}\n")
    sys.stderr.write(FOLLOW_UP.format(log=installed / "logs" / "abletonosc.log"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
