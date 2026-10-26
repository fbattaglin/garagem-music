"""Where the show screen is drawn: a terminal through `curses`, or nowhere, for the tests.

ADR-028: stdlib `curses`, no new dependency. Both screens do the same three things until the
song is over: hand every tapped event to the view, hand every typed line to the show, and
draw the view's lines. Only the curses one reads a keyboard and paints.
"""

from __future__ import annotations

import curses
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Final, Protocol

from garagem.obs import Event
from garagem.stage.screen import ShowView

LineHandler = Callable[[str], None]
# How long the screen waits for a key before it redraws: the bar counter's resolution.
REDRAW_MS: Final = 100
MAX_TYPED: Final = 40
ENTER: Final = frozenset({"\n", "\r", curses.KEY_ENTER})
BACKSPACE: Final = frozenset({"\x7f", "\b", curses.KEY_BACKSPACE})
CLOSING: Final = "the song is over: press Enter to close the screen"


class Screen(Protocol):
    def run(
        self,
        view: ShowView,
        events: deque[Event],
        beat: Callable[[], int],
        on_line: LineHandler,
        done: Callable[[], bool],
    ) -> None:
        """Until `done`, and then until the person has read the end."""
        ...


def drain(events: deque[Event], view: ShowView) -> None:
    while events:
        view.see(events.popleft())


class HeadlessScreen:
    """No terminal: the lines it was given are typed at once, and the last screen is kept."""

    def __init__(self, typed: Sequence[str] = (), *, poll_s: float = 0.01) -> None:
        self._typed = tuple(typed)
        self._poll_s = poll_s
        self.last: list[str] = []

    def run(
        self,
        view: ShowView,
        events: deque[Event],
        beat: Callable[[], int],
        on_line: LineHandler,
        done: Callable[[], bool],
    ) -> None:
        for text in self._typed:
            on_line(text)
        while True:
            finished = done()
            drain(events, view)
            if finished:
                break
            time.sleep(self._poll_s)
        self.last = view.lines(beat())


class CursesScreen:
    """The terminal, redrawn every `REDRAW_MS`, with a line to type into at the bottom."""

    def run(
        self,
        view: ShowView,
        events: deque[Event],
        beat: Callable[[], int],
        on_line: LineHandler,
        done: Callable[[], bool],
    ) -> None:
        curses.wrapper(self._loop, view, events, beat, on_line, done)

    def _loop(
        self,
        window: curses.window,
        view: ShowView,
        events: deque[Event],
        beat: Callable[[], int],
        on_line: LineHandler,
        done: Callable[[], bool],
    ) -> None:
        window.timeout(REDRAW_MS)
        typed = ""
        closing = False
        while True:
            drain(events, view)
            if not closing and done():
                closing = True
                drain(events, view)
                view.said(CLOSING)
            _paint(window, view.lines(beat()), typed)
            try:
                key = window.get_wch()
            except curses.error:
                continue
            if key in ENTER:
                if closing:
                    return
                on_line(typed)
                typed = ""
            elif key in BACKSPACE:
                typed = typed[:-1]
            elif isinstance(key, str) and key.isprintable() and len(typed) < MAX_TYPED:
                typed += key


def _paint(window: curses.window, lines: list[str], typed: str) -> None:
    window.erase()
    height, width = window.getmaxyx()
    try:
        for row, line in enumerate(lines[: max(height - 2, 0)]):
            bold = curses.A_BOLD if line.startswith(("GARAGEM", "NOW")) else curses.A_NORMAL
            window.addnstr(row, 0, line, width - 1, bold)
        window.addnstr(height - 1, 0, f"> {typed}", width - 1)
    except curses.error:
        # A terminal too small to hold the screen still plays the song.
        pass
    window.refresh()
