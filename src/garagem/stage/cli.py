"""`garagem`: the band, run from one command (ADR-028).

    uv run garagem check                 # can the show start? Changes nothing
    uv run garagem check --fix           # and set what Live's API can: tempo, names, arm, mix
    uv run garagem check --setlist setlists/arrangement.json   # against another setlist
    uv run garagem commands              # the words that can be typed during the show
    uv run garagem show --song 1         # a song of the show: the screen, typed words, MiniLab
    uv run garagem show --setlist setlists/arrangement.json --song 2
    uv run garagem studio                # prepare the show: write, hear, approve, order songs
    uv run garagem studio --fake         # the same screen, free: the players write
    uv run garagem studio --concert setlists/friday.toml

Run from the project's folder: `session.toml`, `controller.toml` and `setlists/` are read from
where it is run.
"""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from garagem.control import (
    ControllerPort,
    ControllerSpec,
    ControllerSpecError,
    MidoController,
    input_names,
    load_commands,
    load_controller,
)
from garagem.daw import AbletonOSCAdapter, DawPort, OscSettings
from garagem.daw.live_log import latest_log
from garagem.llm import AnthropicAdapter
from garagem.obs import load_events, marks
from garagem.setlist import load_setlist, save_setlist
from garagem.stage.check import Probes, ready, ready_check, render_check
from garagem.stage.curate import curate
from garagem.stage.show import ShowFiles, Wiring, run_show
from garagem.stage.studio import Studio, StudioFiles, StudioWiring, run_studio
from garagem.stage.terminal import CursesScreen, Screen

DEFAULT_SESSION: Final = Path("session.toml")
DEFAULT_CONTROLLER: Final = Path("controller.toml")
DEFAULT_COMMANDS: Final = Path("commands.toml")
DEFAULT_SHOW: Final = Path("setlists") / "show.json"
DEFAULT_LOG: Final = Path("bench") / "jam.jsonl"
DEFAULT_CATALOG: Final = Path("config") / "models.toml"
DEFAULT_BUDGET: Final = Path("config") / "budget.toml"
DEFAULT_CONCERT: Final = Path("setlists") / "show.toml"
DEFAULT_STYLES: Final = Path("styles")
DEFAULT_STUDIO_LOG: Final = Path("bench") / "studio.jsonl"


def build_adapter(host: str, timeout_s: float) -> DawPort:
    return AbletonOSCAdapter(settings=OscSettings(host=host, timeout_s=timeout_s))


def build_minilab(spec: ControllerSpec) -> ControllerPort:
    return MidoController(spec)


def build_screen() -> Screen:
    return CursesScreen()


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
    check.add_argument("--commands", type=Path, default=DEFAULT_COMMANDS)
    check.add_argument("--setlist", type=Path, default=DEFAULT_SHOW)
    check.add_argument("--host", default="127.0.0.1")
    check.add_argument("--timeout-s", type=float, default=0.5)

    words = commands.add_parser("commands", help="the words that can be typed during the show")
    words.add_argument("--commands", type=Path, default=DEFAULT_COMMANDS)
    words.add_argument("--controller", type=Path, default=DEFAULT_CONTROLLER)

    show = commands.add_parser(
        "show", help="a song of the show, with the screen, typed words and the MiniLab"
    )
    show.add_argument("--setlist", type=Path, default=DEFAULT_SHOW)
    show.add_argument("--song", type=int, default=1, help="which song, counting from 1")
    show.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    show.add_argument("--controller", type=Path, default=DEFAULT_CONTROLLER)
    show.add_argument("--commands", type=Path, default=DEFAULT_COMMANDS)
    show.add_argument("--log", type=Path, default=DEFAULT_LOG)
    show.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    show.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    show.add_argument("--host", default="127.0.0.1")
    show.add_argument("--timeout-s", type=float, default=0.5)

    studio = commands.add_parser(
        "studio", help="prepare the show: what kind of songs, when they are written, which play"
    )
    studio.add_argument("--concert", type=Path, default=DEFAULT_CONCERT)
    studio.add_argument(
        "--fake",
        action="store_true",
        help="the players write in the songwriter's place: free, no key, its own file",
    )
    studio.add_argument("--styles", type=Path, default=DEFAULT_STYLES)
    studio.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    studio.add_argument("--controller", type=Path, default=DEFAULT_CONTROLLER)
    studio.add_argument("--commands", type=Path, default=DEFAULT_COMMANDS)
    studio.add_argument("--log", type=Path, default=DEFAULT_STUDIO_LOG)
    studio.add_argument("--show-log", type=Path, default=DEFAULT_LOG)
    studio.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    studio.add_argument("--budget", type=Path, default=DEFAULT_BUDGET)
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--timeout-s", type=float, default=0.5)

    args = parser.parse_args(argv)
    if args.command == "studio":
        return _studio(args)
    if args.command == "check":
        return _check(args)
    if args.command == "commands":
        return _commands(args)
    if args.command == "show":
        return _show(args)
    parser.error(f"unknown command {args.command!r}")
    return 2


def _probes(args: argparse.Namespace) -> Probes:
    return Probes(
        connect=lambda: build_adapter(args.host, args.timeout_s),
        midi_inputs=input_names,
        live_log=read_live_log,
    )


def _check(args: argparse.Namespace) -> int:
    probes = _probes(args)
    findings = ready_check(
        args.session, args.controller, args.commands, args.setlist, probes, fix=args.fix
    )
    sys.stderr.write(render_check(findings))
    return 0 if ready(findings) else 1


def _commands(args: argparse.Namespace) -> int:
    try:
        spec = load_commands(args.commands)
    except (OSError, ControllerSpecError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    try:
        pads = load_controller(args.controller).pad_numbers()
    except (OSError, ControllerSpecError):
        pads = {}
    sys.stdout.write(spec.cheat_sheet(pads))
    return 0


def _show(args: argparse.Namespace) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write("garagem show draws a screen: run it in a terminal\n")
        return 1
    files = ShowFiles(
        session=args.session,
        controller=args.controller,
        commands=args.commands,
        setlist=args.setlist,
        log=args.log,
        catalog=args.catalog,
        budget=args.budget,
    )
    wiring = Wiring(probes=_probes(args), build_minilab=build_minilab)
    return run_show(files, args.song, wiring, build_screen(), sys.stderr)


def _studio(args: argparse.Namespace) -> int:
    probes = _probes(args)

    def listen(bake: Path, title: str) -> str:
        """One song on the stage, and its keeps and vetoes written into the bake after."""
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return "listening draws the show's screen: run the studio in a terminal\n"
        files = ShowFiles(
            session=args.session,
            controller=args.controller,
            commands=args.commands,
            setlist=bake,
            log=args.show_log,
            catalog=args.catalog,
            budget=args.budget,
        )
        said = io.StringIO()
        wiring = Wiring(probes=probes, build_minilab=build_minilab)
        run_show(files, 1, wiring, build_screen(), said, title=title)
        return said.getvalue() + save_marks(bake, args.show_log)

    def check(bake: Path) -> str:
        return render_check(ready_check(args.session, args.controller, args.commands, bake, probes))

    files = StudioFiles(
        concert=args.concert,
        styles=args.styles,
        session=args.session,
        catalog=args.catalog,
        budget=args.budget,
        log=args.log,
    )
    wiring = StudioWiring(connect=AnthropicAdapter.from_env, listen=listen, check=check)
    try:
        studio = Studio(files, wiring, fake=args.fake)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return run_studio(studio, sys.stdin, sys.stdout)


def save_marks(bake: Path, log: Path) -> str:
    """Write the keeps and vetoes the log holds into the bake, and say what changed.

    What `scripts/curate_setlist.py` does as a second command, done when the song ends: a mark
    struck and never saved was the commonest way to lose one.
    """
    if not log.exists():
        return ""
    setlist = load_setlist(bake)
    curated, tally = curate(setlist, marks(load_events(log)))
    if curated == setlist:
        return ""
    save_setlist(curated, bake)
    return f"saved to the setlist: {tally['keep']} keep, {tally['veto']} veto so far\n"
