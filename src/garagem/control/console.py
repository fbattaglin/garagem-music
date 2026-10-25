"""`ConsoleController`: typed words as cues, the keyboard beside the MiniLab (ADR-028).

A `ControllerPort` like the MiniLab's: started with somewhere to put what it hears, stopped,
and one-way. A word that names a cue becomes the same `Cue` a pad strike becomes, so it goes
into the same `CueQueue`, is stamped the same way and lands on the same bar.

**Two ways in.** The show screen reads the keyboard itself and hands each line to `hear`.
Without a screen, `lines` is read on a thread of its own, and `on_heard` is told what each
line was: a command, or nothing it knows. Blocked in a read, that thread cannot be woken by
`stop`; it is a daemon, and after `stop` it delivers nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from garagem.control.commands import Command, CommandSpec
from garagem.control.port import ControlHandler
from garagem.domain import Cue

HeardHandler = Callable[[str, Command | None], object]


class ConsoleController:
    """Words, as cues."""

    name = "keyboard"

    def __init__(
        self,
        spec: CommandSpec,
        *,
        lines: Callable[[], str] | None = None,
        on_heard: HeardHandler | None = None,
    ) -> None:
        self._spec = spec
        self._lines = lines
        self._on_heard = on_heard
        self._handler: ControlHandler | None = None
        self._reader: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._handler is not None

    def start(self, handler: ControlHandler) -> None:
        self._handler = handler
        if self._lines is not None and self._reader is None:
            self._reader = threading.Thread(target=self._read, name="keyboard", daemon=True)
            self._reader.start()

    def stop(self) -> None:
        self._handler = None

    def hear(self, text: str) -> Command | None:
        """What `text` asks for, delivered if it is a cue. `None`: no word it knows."""
        command = self._spec.lookup(text)
        handler = self._handler
        if command is not None and command.cue is not None and handler is not None:
            handler(Cue(kind=command.cue))
        return command

    def _read(self) -> None:
        assert self._lines is not None
        while self._handler is not None:
            try:
                line = self._lines()
            except EOFError:
                return
            if self._handler is None:
                return
            command = self.hear(line)
            if self._on_heard is not None:
                self._on_heard(line, command)
