"""`garagem check`: whether the show can start, in one look (ADR-028).

Every check runs whatever failed before it, and every failure carries the step that fixes it,
in the words of Live's own menus. A check that stopped at its first failure would move each
discovery one run later, and the last one would be found on stage.

Three levels. **ok** says what was checked, so a clean run is a list of reasons to trust it.
**warn** is something missing that the show plays without: no MiniLab still leaves typed
commands. **fail** stops the show until it is fixed.

Nothing here writes to the Set unless `fix` is asked for, and then only what the bootstrap
writes (ADR-013), never while Live plays (invariant 6). The outside world is reached through
`Probes`, so every failure kind is tested with fakes.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from garagem.control import ControllerSpecError, load_commands, load_controller
from garagem.daw import (
    DawError,
    DawPort,
    DawTimeoutError,
    DawUnavailableError,
    Divergence,
    SessionSpec,
    apply_session,
    diff_session,
    fix_step,
    load_session,
    observe,
)
from garagem.daw.errors import SessionSpecError
from garagem.daw.live_log import control_surfaces, listening_to
from garagem.domain import CueKind
from garagem.setlist import SetlistError, load_setlist
from garagem.stage.roles import missing_roles


class Level(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Finding:
    level: Level
    area: str
    what: str
    fix: str = ""
    # A stable name for the failure, for tests. `what` is for a person and free to change.
    kind: str = ""


@dataclass(frozen=True, slots=True)
class Probes:
    """How the check reaches the outside world."""

    connect: Callable[[], DawPort]
    midi_inputs: Callable[[], list[str]]
    # Live's `Log.txt`, or `None` when it cannot be found or read.
    live_log: Callable[[], str | None]


SESSION: Final = "session.toml"
LIVE: Final = "Live"
SET: Final = "the Set"
MINILAB: Final = "MiniLab"
KEYBOARD: Final = "keyboard"
SHOW: Final = "the show"

OPEN_LIVE: Final = (
    "open Ableton Live with the band's Set. If it is open: Live -> Settings -> Link, Tempo & "
    "MIDI -> Control Surface, pick AbletonOSC in a free row, then quit Live and open it again"
)
FROM_THE_PROJECT: Final = "run garagem from the project's folder, where that file lives"
FIX_IT: Final = "run garagem check --fix, which sets it in Live"


def ready_check(
    session: Path,
    controller: Path,
    commands: Path,
    setlist: Path,
    probes: Probes,
    *,
    fix: bool = False,
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    spec = _session(session, findings)
    _live(spec, probes, findings, fix=fix)
    _controller(controller, probes, findings)
    _keyboard(commands, findings)
    _setlist(setlist, spec, findings)
    return tuple(findings)


def ready(findings: Sequence[Finding]) -> bool:
    return not any(finding.level is Level.FAIL for finding in findings)


def render_check(findings: Sequence[Finding]) -> str:
    marks = {Level.OK: "  ok", Level.WARN: "WARN", Level.FAIL: "FAIL"}
    lines: list[str] = []
    for finding in findings:
        lines.append(f"{marks[finding.level]}  {finding.area}: {finding.what}")
        if finding.fix:
            lines.append(f"      -> {finding.fix}")
    failed = sum(finding.level is Level.FAIL for finding in findings)
    warned = sum(finding.level is Level.WARN for finding in findings)
    if failed:
        lines.append(f"Not ready: {failed} thing{'s' if failed != 1 else ''} to fix first.")
    elif warned:
        lines.append(f"Ready, with {warned} warning{'s' if warned != 1 else ''}.")
    else:
        lines.append("Ready for the show.")
    return "\n".join(lines) + "\n"


def _session(path: Path, findings: list[Finding]) -> SessionSpec | None:
    try:
        spec = load_session(path)
    except OSError:
        findings.append(
            Finding(Level.FAIL, SESSION, f"{path} not found", FROM_THE_PROJECT, "session_missing")
        )
        return None
    except (tomllib.TOMLDecodeError, SessionSpecError) as exc:
        findings.append(
            Finding(
                Level.FAIL,
                SESSION,
                f"cannot be used: {exc}",
                "correct the line the message names",
                "session_unreadable",
            )
        )
        return None
    missing = missing_roles(spec)
    if missing:
        findings.append(
            Finding(
                Level.FAIL,
                SESSION,
                f"no track plays {', '.join(missing)}",
                "add a [[track]] with that role to session.toml, and the track in Live",
                "missing_role",
            )
        )
    else:
        findings.append(Finding(Level.OK, SESSION, f"{len(spec.tracks)} tracks for the band"))
    return spec


def _live(spec: SessionSpec | None, probes: Probes, findings: list[Finding], *, fix: bool) -> None:
    daw = probes.connect()
    try:
        try:
            daw.warm()
        except DawTimeoutError:
            findings.append(
                Finding(
                    Level.FAIL,
                    LIVE,
                    "does not answer, so nothing in the Set was checked",
                    OPEN_LIVE,
                    "live_silent",
                )
            )
            return
        except DawUnavailableError as exc:
            findings.append(
                Finding(
                    Level.FAIL,
                    LIVE,
                    f"cannot be reached: {exc}",
                    "close the other GARAGEM command talking to Live (a jam, a sound check), "
                    "then run this again",
                    "live_busy",
                )
            )
            return
        findings.append(Finding(Level.OK, LIVE, "answers"))
        try:
            divergences = _the_set(daw, spec, findings, fix=fix)
        except DawError as exc:
            findings.append(
                Finding(
                    Level.FAIL,
                    LIVE,
                    f"stopped answering during the check: {exc}",
                    OPEN_LIVE,
                    "live_silent",
                )
            )
            return
        if divergences is None:
            return
        findings.extend(_divergence(divergence) for divergence in divergences)
        if not divergences and spec is not None:
            findings.append(
                Finding(
                    Level.OK,
                    SET,
                    f"tracks, instruments, tempo {spec.tempo_bpm:g} and mix as {SESSION} says",
                )
            )
    finally:
        daw.close()


def _the_set(
    daw: DawPort, spec: SessionSpec | None, findings: list[Finding], *, fix: bool
) -> tuple[Divergence, ...] | None:
    """What differs from `session.toml`, after fixing what may be fixed; `None`: not checked."""
    if daw.is_playing():
        findings.append(
            Finding(
                Level.FAIL,
                LIVE,
                "is playing",
                "press the space bar in Live to stop it: the show starts the band itself"
                + (", and nothing is set in a Set that plays" if fix else ""),
                "live_playing",
            )
        )
        fix = False
    if spec is None:
        return None
    if fix:
        return apply_session(daw, spec)
    return diff_session(spec, observe(daw, spec))


def _divergence(divergence: Divergence) -> Finding:
    step = FIX_IT if divergence.fixable else fix_step(divergence)
    return Finding(Level.FAIL, SET, divergence.detail, step, f"set_{divergence.kind}")


def _controller(path: Path, probes: Probes, findings: list[Finding]) -> None:
    try:
        spec = load_controller(path)
    except OSError:
        findings.append(
            Finding(
                Level.FAIL, MINILAB, f"{path} not found", FROM_THE_PROJECT, "controller_missing"
            )
        )
        return
    except (tomllib.TOMLDecodeError, ControllerSpecError) as exc:
        findings.append(
            Finding(
                Level.FAIL,
                MINILAB,
                f"controller.toml cannot be used: {exc}",
                "correct the entry the message names; scripts/probe_minilab.py shows what each "
                "pad and knob sends",
                "controller_unreadable",
            )
        )
        return

    if spec.port in probes.midi_inputs():
        findings.append(Finding(Level.OK, MINILAB, f"plugged in, as {spec.port}"))
    else:
        findings.append(
            Finding(
                Level.WARN,
                MINILAB,
                "not plugged in: the show will take typed commands only",
                "plug it in by USB, then run garagem check again",
                "minilab_missing",
            )
        )

    text = probes.live_log()
    if text is None:
        findings.append(
            Finding(
                Level.WARN,
                MINILAB,
                "Live's log could not be read, so its control surfaces were not checked",
                "open Live once, then run garagem check again",
                "live_log_unreadable",
            )
        )
        return
    clashing = listening_to(control_surfaces(text), spec.port)
    if clashing:
        rows = ", ".join(f"row {surface.slot} ({surface.name})" for surface in clashing)
        findings.append(
            Finding(
                Level.FAIL,
                MINILAB,
                f"Live's control surface {rows} also listens to it, and can move the transport "
                "or switch the loop on from a pad",
                "Live -> Settings -> Link, Tempo & MIDI -> Control Surface: set that row's Input "
                "and Output to None",
                "surface_clash",
            )
        )


def _keyboard(path: Path, findings: list[Finding]) -> None:
    try:
        spec = load_commands(path)
    except OSError:
        findings.append(
            Finding(Level.FAIL, KEYBOARD, f"{path} not found", FROM_THE_PROJECT, "commands_missing")
        )
        return
    except (tomllib.TOMLDecodeError, ControllerSpecError) as exc:
        findings.append(
            Finding(
                Level.FAIL,
                KEYBOARD,
                f"commands.toml cannot be used: {exc}",
                "correct the entry the message names",
                "commands_unreadable",
            )
        )
        return
    typed = {command.cue for command in spec.commands if command.cue is not None}
    missing = [str(kind) for kind in CueKind if kind not in typed]
    if missing:
        findings.append(
            Finding(
                Level.WARN,
                KEYBOARD,
                f"no word for {', '.join(missing)}",
                "add a [[command]] for it to commands.toml",
                "commands_incomplete",
            )
        )
    else:
        findings.append(
            Finding(Level.OK, KEYBOARD, f"a word for every cue, {len(spec.commands)} in all")
        )


def _setlist(path: Path, spec: SessionSpec | None, findings: list[Finding]) -> None:
    if not path.exists():
        findings.append(
            Finding(
                Level.FAIL,
                SHOW,
                f"not baked yet ({path} does not exist)",
                f"uv run python scripts/bake_setlist.py {path.with_suffix('.toml')} says what the "
                "bake costs and stops; add --yes to bake it",
                "setlist_missing",
            )
        )
        return
    try:
        setlist = load_setlist(path)
    except SetlistError as exc:
        findings.append(
            Finding(
                Level.FAIL,
                SHOW,
                f"cannot be read: {exc}",
                "bake it again",
                "setlist_unreadable",
            )
        )
        return
    if spec is not None and setlist.bpm != spec.tempo_bpm:
        findings.append(
            Finding(
                Level.FAIL,
                SHOW,
                f"{path.name} was baked at {setlist.bpm:g} BPM and the Set is at "
                f"{spec.tempo_bpm:g}",
                f"bake it again, or set {SESSION}'s tempo back",
                "setlist_tempo",
            )
        )
        return
    songs = len(setlist.songs)
    findings.append(
        Finding(Level.OK, SHOW, f"{path.name}: {songs} song{'s' if songs != 1 else ''}, from disk")
    )
