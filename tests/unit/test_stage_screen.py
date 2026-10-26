"""The show screen, headless: what it shows is what the log records, never who wrote it."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from garagem.control import load_commands
from garagem.daw import FakeDawAdapter
from garagem.domain import Cue, CueKind, Feel, Instrument, Section
from garagem.obs import Event, EventLog
from garagem.stage.screen import Planned, ShowView
from garagem.theory import parse_chart
from garagem.transport import BarClock, CueQueue, Scheduler, ScoreBuffer

ROOT = Path(__file__).resolve().parents[2]
COMMANDS = load_commands(ROOT / "commands.toml")
WORDS = {command.cue: command.word for command in COMMANDS.commands if command.cue is not None}
TRACKS = {
    Instrument.DRUMS: 0,
    Instrument.BASS: 1,
    Instrument.GUITAR: 2,
    Instrument.KEYS: 3,
    Instrument.LEAD: 4,
}
VARIANTS = {"stop": {0: 4, 1: 5}, "fill": {0: 6, 1: 7}}
# Who wrote a section is never on the screen (ADR-024), in any of the words that would say so.
AUTHORSHIP = ("model", "floor", "fallback", "author", "baked", "generated", "take")


def a_section(name: str, bars: int) -> Section:
    return Section(
        name=name,
        bars=bars,
        key=4,
        scale="minor",
        feel=Feel.STRAIGHT8,
        bpm=132.0,
        dyn=3,
        tension=0.4,
        chart=parse_chart("| Em | C | G | D |"),
    )


# Intro bars 0-3, verse 4-11, chorus 12-19, outro 20-23.
LONG = (a_section("intro", 4), a_section("verse", 8), a_section("chorus", 8), a_section("outro", 4))


def view_of(form: tuple[Section, ...] = LONG) -> ShowView:
    return ShowView(
        title="Seven",
        song=1,
        songs=3,
        bpm=132.0,
        form=[Planned(section.name, section.bars) for section in form],
        words=WORDS,
        cheat_sheet=COMMANDS.cheat_sheet(),
    )


class Stage:
    """A real scheduler on a fake Live, its log tapped into a view as the show would."""

    def __init__(self) -> None:
        self.daw = FakeDawAdapter(scenes=8)
        self.clock = BarClock(self.daw)
        self.clock.start()
        self.tapped: deque[Event] = deque()
        self.log = EventLog(None, tap=self.tapped.append)
        self.queue = CueQueue(stamp=lambda: self.clock.beat)
        self.scheduler = Scheduler(
            self.daw,
            self.clock,
            ScoreBuffer(),
            TRACKS,
            self.log,
            seed=7,
            cues=self.queue,
            candidates={"chorus": 2},
            variants=VARIANTS,
        )
        self.view = view_of()
        self.screens: dict[int, list[str]] = {}

    def play(self, strikes: dict[int, CueKind] | None = None) -> Stage:
        strikes = strikes or {}
        self.scheduler.begin(LONG)
        beat = 0
        while not self.scheduler.finished and beat < 400:
            self.daw.push_beat(beat)
            if beat in strikes:
                self.queue.offer(Cue(kind=strikes[beat]))
            self.scheduler.tick()
            while self.tapped:
                self.view.see(self.tapped.popleft())
            self.screens[beat] = self.view.lines(beat)
            beat += 1
        return self

    def line(self, beat: int, label: str) -> str:
        return next(line for line in self.screens[beat] if line.startswith(label))


# ------------------------------------------------------------------- driven by the band


def test_it_shows_the_section_the_bar_and_what_comes_next() -> None:
    stage = Stage().play()

    assert stage.line(0, "NOW").startswith("NOW    intro    bar 1 of 4   (song bar 1)")
    assert "verse" in stage.line(1, "NEXT")
    assert stage.line(22, "NOW").startswith("NOW    verse    bar 2 of 8")
    assert stage.line(22, "NEXT").startswith("NEXT   chorus")
    # Once the chorus is fired, a bar ahead of its downbeat, the screen counts down to it.
    assert "chorus (in 1 bar)" in stage.line(44, "NEXT")
    assert stage.line(48, "NOW").startswith("NOW    chorus   bar 1 of 8")


def test_every_cue_is_acknowledged_with_where_it_lands() -> None:
    stage = Stage().play({22: CueKind.FILL, 25: CueKind.NEXT_BRIDGE})
    said = "\n".join(stage.screens[30])

    assert "fill -> bar 7, the next one" in said
    assert "bridge -> bridge, after this section" in said
    # And the plan the screen shows is the plan the scheduler re-made.
    assert stage.line(30, "NEXT").startswith("NEXT   bridge")


def test_every_decline_says_why_in_plain_words() -> None:
    stage = Stage().play({22: CueKind.NEXT_BRIDGE, 26: CueKind.NEXT_BRIDGE})
    said = "\n".join(stage.screens[30])
    assert "bridge: not now, that is already what comes next" in said


def test_a_jump_moves_the_screen_to_the_chorus_on_the_bar_it_lands() -> None:
    stage = Stage().play({21: CueKind.CHORUS_NOW})
    said = "\n".join(stage.screens[24])
    assert "chorus -> bar 7, the next one" in said
    assert stage.line(24, "NOW").startswith("NOW    chorus   bar 1 of 8")


def test_the_song_ends_on_the_screen() -> None:
    stage = Stage().play()
    stage.view.see(Event(at_beats=96.0, kind="session_ended", detail={"finished": True}))
    assert stage.view.lines(96)[2] == "NOW    the song is over"


def test_nothing_on_the_screen_ever_says_who_wrote_a_section() -> None:
    strikes = {22: CueKind.FILL, 30: CueKind.KEEP, 34: CueKind.VETO, 40: CueKind.NEXT_SOLO}
    stage = Stage().play(strikes)
    marked = [event for event in stage.log if event.kind == "take_marked"]
    assert marked and all("author" in event.detail for event in marked)

    for screen in stage.screens.values():
        for line in screen[: screen.index("Type a word, then Enter:")]:
            assert not any(word in line.lower() for word in AUTHORSHIP), line


# ------------------------------------------------------------------------- one event each


def test_a_word_nobody_knows_is_said_back() -> None:
    view = view_of()
    view.said("sollo: no such word, type help")
    assert "  sollo: no such word, type help" in view.lines(-1)


def test_before_the_downbeat_it_waits() -> None:
    lines = view_of().lines(-1)
    assert lines[2] == "NOW    waiting for the downbeat"
    assert "(nothing asked yet)" in "\n".join(lines)


def test_the_knobs_show_how_far_they_moved_the_plan() -> None:
    view = view_of()
    view.see(
        Event(
            at_beats=20.0,
            kind="macro_changed",
            detail={
                "density": 1.0,
                "tension": 0.8,
                "dyn_offset": 2,
                "tension_offset": 0.15,
                "from_section": 2,
            },
        )
    )
    assert "KNOBS  density +2   tension +0.15" in view.lines(20)


def test_a_hand_stop_and_a_lost_beat_end_the_song_differently() -> None:
    stopped = view_of()
    stopped.see(Event(at_beats=20.0, kind="stopped_by_hand", detail={"bar": 5, "section": 1}))
    assert stopped.lines(20)[2] == "NOW    stopped"

    lost = view_of()
    lost.see(Event(at_beats=20.0, kind="beat_lost", detail={"reason": "position_went_back"}))
    assert "arrangement loop" in lost.lines(20)[2]


def test_the_cheat_sheet_is_on_the_screen() -> None:
    lines = view_of().lines(-1)
    assert "Type a word, then Enter:" in lines
    assert any(line.strip().startswith("solo") for line in lines)
