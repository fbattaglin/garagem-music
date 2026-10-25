"""`garagem`: the band, run from one command (ADR-028).

    uv run garagem check                 # can the show start? Changes nothing
    uv run garagem check --fix           # and set what Live's API can: tempo, names, arm, mix
    uv run garagem check --setlist setlists/arrangement.json   # against another setlist

Run from the project's folder: `session.toml`, `controller.toml` and `setlists/` are read from
where it is run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from garagem.control import input_names
from garagem.daw import AbletonOSCAdapter, DawPort, OscSettings
from garagem.daw.live_log import latest_log
from garagem.stage.check import Probes, ready, ready_check, render_check

DEFAULT_SESSION: Final = Path("session.toml")
DEFAULT_CONTROLLER: Final = Path("controller.toml")
DEFAULT_SHOW: Final = Path("setlists") / "show.json"


def build_adapter(host: str, timeout_s: float) -> DawPort:
    return AbletonOSCAdapter(settings=OscSettings(host=host, timeout_s=timeout_s))


def read_live_log() -> str | None:
    log = latest_log()
    if log is None:
        return None
    try:
        return log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="garagem", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    check = commands.add_parser("check", help="whether the show can start, in one look")
    check.add_argument(
        "--fix",
        action="store_true",
        help="set what Live's API can set: tempo, launch quantisation, track names, arm, mix",
    )
    check.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    check.add_argument("--controller", type=Path, default=DEFAULT_CONTROLLER)
    check.add_argument("--setlist", type=Path, default=DEFAULT_SHOW)
    check.add_argument("--host", default="127.0.0.1")
    check.add_argument("--timeout-s", type=float, default=0.5)

    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


def _check(args: argparse.Namespace) -> int:
    probes = Probes(
        connect=lambda: build_adapter(args.host, args.timeout_s),
        midi_inputs=input_names,
        live_log=read_live_log,
    )
    findings = ready_check(args.session, args.controller, args.setlist, probes, fix=args.fix)
    sys.stderr.write(render_check(findings))
    return 0 if ready(findings) else 1
