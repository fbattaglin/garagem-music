"""`garagem show`: a song of the show, with the screen, typed commands and the MiniLab.

ADR-028. **It starts only from a clean `garagem check`**, and prints the check either way, so
a show that refuses says why in the same words the check uses.

Then it plays a baked song from disk as `scripts/jam.py --setlist` does (ADR-024), by the same
pieces (`stage.band`), with three differences:

- **the screen** draws from a tap on the event log while the band plays on a thread of its
  own; the screen has the main thread, because `curses` wants it;
- **the keyboard** is a controller beside the MiniLab, into the same `CueQueue`, and `quit`
  asks the scheduler to stop at its next wake;
- **no MiniLab is not a refusal**: the check warned, and the words still reach the band.

The whole setlist in one run, a tempo per song and the count-in are Stage E's.
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from garagem.agents import Producer, by_id, only
from garagem.control import (
    ConsoleController,
    ControllerPort,
    ControllerSpec,
    ControllerUnavailableError,
    StageAction,
    load_commands,
    load_controller,
)
from garagem.daw import DawError, DawUnavailableError, load_session
from garagem.llm import load_budget, load_catalog
from garagem.obs import Event, EventLog, model_share, render_checks, setlist_checks
from garagem.setlist import Song, briefings, load_setlist
from garagem.stage.band import build_setlist_provider, candidate_scenes, prime, variant_scenes
from garagem.stage.check import Probes, ready, ready_check, render_check
from garagem.stage.roles import palms_of, pitches_of, tracks_of
from garagem.stage.screen import Planned, ShowView
from garagem.stage.terminal import Screen
from garagem.transport import BarClock, CueQueue, FormPlan, Scheduler, ScoreBuffer

# How long teardown waits for the band's thread once it has been asked to stop.
JOIN_S: Final = 5.0


@dataclass(frozen=True, slots=True)
class ShowFiles:
    session: Path
    controller: Path
    commands: Path
    setlist: Path
    log: Path
    catalog: Path
    budget: Path


@dataclass(frozen=True, slots=True)
class Wiring:
    """How the show reaches Live and the MiniLab. Swapped for fakes in tests."""

    probes: Probes
    build_minilab: Callable[[ControllerSpec], ControllerPort]


def run_show(files: ShowFiles, number: int, wiring: Wiring, screen: Screen, out: TextIO) -> int:
    findings = ready_check(
        files.session, files.controller, files.commands, files.setlist, wiring.probes
    )
    out.write(render_check(findings))
    if not ready(findings):
        out.write("garagem show starts once garagem check has nothing to fix.\n")
        return 1

    setlist = load_setlist(files.setlist)
    if not 1 <= number <= len(setlist.songs):
        out.write(f"--song {number}: {setlist.name} has songs 1 to {len(setlist.songs)}\n")
        return 1
    song = setlist.songs[number - 1]
    spec = load_session(files.session)
    commands = load_commands(files.commands)
    pads = load_controller(files.controller)
    catalog = load_catalog(files.catalog)
    budget = load_budget(files.budget)
    provider = build_setlist_provider(setlist, song, catalog, budget)

    tapped: deque[Event] = deque()
    log = EventLog(files.log, tap=tapped.append)
    daw = wiring.probes.connect()
    clock = BarClock(daw)
    buffer = ScoreBuffer()
    plan = FormPlan(song.form, song.endings)
    cues = CueQueue(stamp=lambda: clock.beat)
    view = ShowView(
        title=song.title,
        song=number,
        songs=len(setlist.songs),
        bpm=setlist.bpm,
        form=[Planned(section.name, section.bars) for section in song.form],
        words={command.cue: command.word for command in commands.commands if command.cue},
        cheat_sheet=commands.cheat_sheet(pads.pad_numbers()),
    )
    keyboard = ConsoleController(commands)
    minilab = wiring.build_minilab(pads) if pads.port in wiring.probes.midi_inputs() else None
    producer: Producer | None = None
    scheduler: Scheduler | None = None
    band: threading.Thread | None = None
    try:
        try:
            daw.warm()
        except DawUnavailableError as exc:
            out.write(f"{exc}\n")
            return 1
        log.record(
            "setlist_loaded",
            0.0,
            setlist=setlist.name,
            provider=setlist.provider,
            model=setlist.model,
            song=number,
            title=song.title,
            takes=len(song.playable()),
            serving="baked",
        )
        producer = Producer(
            provider,
            buffer,
            log,
            plan,
            model=by_id(catalog, setlist.model),
            seed=song.seed,
            route=only(briefings(song)),
        )
        producer.start()
        prime(buffer, song.form[0])
        keyboard.start(cues.offer)
        if minilab is not None:
            try:
                minilab.start(cues.offer)
            except ControllerUnavailableError as exc:
                view.said(f"the MiniLab could not be opened, typed words only: {exc}")
                minilab = None
        scheduler = Scheduler(
            daw,
            clock,
            buffer,
            tracks_of(spec),
            log,
            seed=song.seed,
            cues=cues,
            candidates=candidate_scenes(spec),
            plan=plan,
            variants=variant_scenes(spec),
            pitches=pitches_of(spec),
            palms=palms_of(spec),
        )
        clock.start()
        daw.start_playing()
        band = threading.Thread(target=_perform, args=(scheduler, song), name="band", daemon=True)
        band.start()
        playing = band
        on_line = _typing(keyboard, view, scheduler.stop)
        try:
            screen.run(view, tapped, lambda: clock.beat, on_line, lambda: not playing.is_alive())
        except KeyboardInterrupt:
            scheduler.stop()
        band.join(JOIN_S)
    finally:
        if scheduler is not None and band is not None and band.is_alive():
            scheduler.stop()
            band.join(JOIN_S)
        keyboard.stop()
        if minilab is not None:
            minilab.stop()
        if producer is not None:
            producer.stop()
        if scheduler is not None:
            log.record(
                "session_ended",
                float(max(clock.beat, 0)),
                finished=scheduler.finished,
                bpm=setlist.bpm,
            )
        teardown = (("stop listening", clock.stop), ("stop the transport", daw.stop_playing))
        for step, action in teardown:
            try:
                action()
            except DawError as exc:
                out.write(f"could not {step}: {exc}\n")
        log.flush()
        daw.close()

    assert scheduler is not None  # every path that leaves it unset has returned
    out.write(end_card(song, scheduler, log, files))
    if scheduler.finished or scheduler.stopped_because == "stopped_by_hand":
        return 0
    return 1


def end_card(song: Song, scheduler: Scheduler, log: EventLog, files: ShowFiles) -> str:
    """How the song went, what was marked, and the criteria read back from the log."""
    if scheduler.finished:
        lines = [f"{song.title}: played to its end."]
    elif scheduler.stopped_because == "stopped_by_hand":
        lines = [f"{song.title}: stopped by hand."]
    else:
        lines = [f"{song.title}: stopped early, Live sent no beat ({scheduler.stopped_because})."]
    marks = Counter(str(event.detail["mark"]) for event in log.of_kind("take_marked"))
    if marks:
        lines.append(
            "marked: "
            + ", ".join(f"{mark} x{count}" for mark, count in sorted(marks.items()))
            + f". To keep them: uv run python scripts/curate_setlist.py {files.setlist}"
        )
    checks = render_checks(
        setlist_checks(log.events, share_floor=None),
        model_share(log.events),
        phase="The show",
        wrote="from the setlist:",
    )
    return "\n".join(lines) + "\n" + checks + f"{len(log)} events -> {files.log}\n"


def _perform(scheduler: Scheduler, song: Song) -> None:
    scheduler.run(song.form, seed=song.seed, endings=song.endings)


def _typing(
    keyboard: ConsoleController, view: ShowView, stop: Callable[[], None]
) -> Callable[[str], None]:
    """A typed line: a cue for the band, a word for the show, or one nobody knows."""

    def heard(text: str) -> None:
        if not text.strip():
            return
        command = keyboard.hear(text)
        if command is None:
            view.said(f"{text.strip()!r}: no such word, type help")
        elif command.stage is StageAction.QUIT:
            stop()
            view.said("quit: stopping the show")
        elif command.stage is StageAction.HELP:
            view.said("help: every word is listed below")

    return heard
