"""The show screen: what the band plays, what comes next, and what became of each cue.

ADR-028. **It draws from a tap on the event log**, so what it shows is what the log records,
and it never calls into the scheduler. The only thing it reads besides events is the beat
Live last reported, so the bar counter moves between events.

**It never shows who wrote a section** (ADR-024). The events that say so (`fallback`,
`section_generated`, a mark's `author`) are not read at all.

`ShowView` is the state and its text. `lines` is the whole screen as strings, so the headless
mode the tests use and the curses painter draw exactly the same thing.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from garagem.domain import CueFamily, CueKind
from garagem.obs import Event

BEATS_PER_BAR: Final = 4
NO_BEAT: Final = -1
HISTORY: Final = 6
AHEAD: Final = 4

# Why a cue was declined, in the words of someone on stage rather than the scheduler's.
REASONS: Final[dict[str, str]] = {
    "before_the_downbeat": "the song has not started yet",
    "song_over": "the song is over",
    "already_ending": "the song is already ending",
    "no_section_left": "no section is left to change",
    "already_next": "that is already what comes next",
    "section_change": "a new section starts on the next bar; ask again once it has",
    "no_candidate": "nothing was written ahead for it in this song",
    "no_variant": "nothing was written ahead for it in this section",
    "unavailable": "it is not ready yet in this section",
}

STOPS: Final[dict[str, str]] = {
    "transport_stopped": "Live stopped sending beats: the transport was stopped outside GARAGEM",
    "position_went_back": "Live's song position went back: the arrangement loop is on",
}


@dataclass(frozen=True, slots=True)
class Planned:
    name: str
    bars: int


class ShowView:
    """One song's screen."""

    def __init__(
        self,
        *,
        title: str,
        song: int,
        songs: int,
        bpm: float,
        form: Sequence[Planned],
        words: Mapping[CueKind, str],
        cheat_sheet: str = "",
    ) -> None:
        self._title = title
        self._song = song
        self._songs = songs
        self._bpm = bpm
        self._plan = list(form)
        self._words = dict(words)
        self._cheat_sheet = cheat_sheet
        self._starts: dict[int, int] = {}
        self._knobs = (0, 0.0)
        self._said: deque[str] = deque(maxlen=HISTORY)
        self._over: str | None = None

    @property
    def over(self) -> str | None:
        """How the song ended, once it has: `None` while it plays."""
        return self._over

    def said(self, message: str) -> None:
        """A line from the stage itself, such as a word nobody knows."""
        self._said.append(message)

    def see(self, event: Event) -> None:
        detail = event.detail
        bar = _bar_of(event.at_beats)
        match event.kind:
            case "scene_fired":
                section = int(detail["section"])
                self._starts[section] = max(bar, 0) + int(detail["slack_bars"])
            case "form_replanned":
                self._replanned(
                    int(detail["from_section"]), str(detail["names"]), str(detail.get("bars", ""))
                )
            case "cue_applied":
                if _is_jump(detail["cue"]):
                    # A jump fires its own scene and logs no `scene_fired`: it starts here.
                    self._starts[int(detail["section"])] = int(detail["fired_bar"])
                self._said.append(self._applied(detail, bar))
            case "cue_declined":
                reason = str(detail["reason"])
                self._said.append(
                    f"{self._word(detail['cue'])}: not now, {REASONS.get(reason, reason)}"
                )
            case "take_marked":
                kept = detail["mark"] == str(CueKind.KEEP)
                self._said.append(
                    f"{self._word(detail['mark'])}: "
                    + ("kept, the setlist pins this section" if kept else "it will not come back")
                )
            case "macro_changed":
                self._knobs = (int(detail["dyn_offset"]), float(detail["tension_offset"]))
            case "session_ended":
                if self._over is None:
                    self._over = "the song is over" if detail.get("finished") else "stopped"
            case "stopped_by_hand":
                self._over = "stopped"
            case "beat_lost":
                reason = str(detail.get("reason", ""))
                self._over = STOPS.get(reason, "Live stopped sending beats")
            case _:
                pass

    def lines(self, beat: int) -> list[str]:
        bar = _bar_of(beat)
        now = self._now(bar)
        lines = [
            f"GARAGEM   {self._title}   song {self._song} of {self._songs}   {self._bpm:g} BPM",
            "",
            self._now_line(now, bar),
            self._next_line(now, bar),
            self._knob_line(),
            "",
        ]
        lines += [f"  {message}" for message in self._said] or ["  (nothing asked yet)"]
        if self._cheat_sheet:
            lines += ["", *self._cheat_sheet.rstrip("\n").splitlines()]
        return lines

    # ----------------------------------------------------------------------------- state

    def _replanned(self, at: int, names: str, bars: str) -> None:
        counts = [int(count) for count in bars.split(",") if count]
        kept = self._plan[:at]
        new = names.split(",") if names else []
        self._plan = [
            *kept,
            *(
                Planned(name, counts[index] if index < len(counts) else 0)
                for index, name in enumerate(new)
            ),
        ]
        # Nothing after `at` has been fired yet; a start there belonged to a section now gone.
        for section in [index for index in self._starts if index > at]:
            del self._starts[section]

    def _now(self, bar: int) -> int | None:
        if bar == NO_BEAT:
            return None
        started = [index for index, start in self._starts.items() if start <= bar]
        return max(started) if started else None

    def _applied(self, detail: Mapping[str, object], bar: int) -> str:
        word = self._word(detail["cue"])
        if "fired_bar" in detail:
            fired = int(str(detail["fired_bar"]))
            cued = int(str(detail["cue_bar"]))
            when = "the next one" if fired == cued + 1 else f"{fired - cued} bars on"
            return f"{word} -> bar {fired + 1}, {when}"
        if "section" in detail:
            section = int(str(detail["section"]))
            first = str(detail.get("names", "")).split(",")[0]
            now = self._now(bar)
            if now is not None and section == now + 1:
                when = "after this section"
            elif now is not None and section == now + 2:
                when = "after the next section"
            else:
                when = f"from section {section + 1}"
            return f"{word} -> {first}, {when}"
        return f"{word}: done"

    def _word(self, cue: object) -> str:
        try:
            return self._words.get(CueKind(str(cue)), str(cue))
        except ValueError:
            return str(cue)

    # ------------------------------------------------------------------------------ text

    def _now_line(self, now: int | None, bar: int) -> str:
        if self._over is not None:
            return f"NOW    {self._over}"
        if now is None or now >= len(self._plan):
            return "NOW    waiting for the downbeat"
        planned = self._plan[now]
        into = bar - self._starts[now] + 1
        of = f" of {planned.bars}" if planned.bars else ""
        return f"NOW    {planned.name:<8} bar {into}{of}   (song bar {bar + 1})"

    def _next_line(self, now: int | None, bar: int) -> str:
        following = 0 if now is None else now + 1
        ahead = self._plan[following : following + AHEAD]
        if not ahead or self._over is not None:
            return "NEXT   -"
        first = ahead[0].name
        start = self._starts.get(following)
        if start is not None and start > bar:
            first += f" (in {start - bar} bar{'s' if start - bar != 1 else ''})"
        rest = [planned.name for planned in ahead[1:]]
        more = " ..." if following + AHEAD < len(self._plan) else ""
        return "NEXT   " + "  >  ".join([first, *rest]) + more

    def _knob_line(self) -> str:
        dyn, tension = self._knobs
        return f"KNOBS  density {dyn:+d}   tension {tension:+.2f}"


def _is_jump(cue: object) -> bool:
    try:
        return CueKind(str(cue)).family is CueFamily.JUMP
    except ValueError:
        return False


def _bar_of(beat: float) -> int:
    return NO_BEAT if beat < 0 else int(beat // BEATS_PER_BAR)
