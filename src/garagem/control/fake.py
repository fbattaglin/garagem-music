"""`FakeController`: a MiniLab made of method calls, for every test that is not about hardware.

Two ways in, because tests ask two different questions. `press` and `turn` deliver a control
directly — "what does the scheduler do with a stop?". `receive` delivers raw MIDI fields
through the real mapping — "does pad 36 on channel 10 still mean stop?". Both honour the
port's contract: nothing is delivered before `start` or after `stop`, exactly as an
unplugged controller delivers nothing.
"""

from __future__ import annotations

from garagem.control.errors import ControllerUnavailableError
from garagem.control.mapping import ControllerSpec
from garagem.control.port import ControlHandler
from garagem.domain import Control, Cue, CueKind, Macro, MacroKind


class FakeController:
    """Controls on demand. Records what it delivered, in order."""

    def __init__(self, spec: ControllerSpec | None = None, *, available: bool = True) -> None:
        self._spec = spec
        self._available = available
        self._handler: ControlHandler | None = None
        self.delivered: list[Control] = []
        self.started = 0
        self.stopped = 0

    @property
    def name(self) -> str:
        return "fake" if self._spec is None else f"fake {self._spec.port}"

    @property
    def running(self) -> bool:
        return self._handler is not None

    def start(self, handler: ControlHandler) -> None:
        if not self._available:
            raise ControllerUnavailableError("the fake controller was built unplugged")
        self._handler = handler
        self.started += 1

    def stop(self) -> None:
        if self._handler is not None:
            self.stopped += 1
        self._handler = None

    def press(self, cue: CueKind) -> None:
        self._deliver(Cue(kind=cue))

    def turn(self, macro: MacroKind, value: float) -> None:
        self._deliver(Macro(kind=macro, value=value))

    def receive(self, kind: str, channel: int, number: int, value: int) -> None:
        """Raw MIDI fields, wire channel 0-15, through the spec's own `translate`."""
        if self._spec is None:
            raise ValueError("receive needs a ControllerSpec to translate through")
        control = self._spec.translate(kind, channel, number, value)
        if control is not None:
            self._deliver(control)

    def _deliver(self, control: Control) -> None:
        if self._handler is None:
            return
        self.delivered.append(control)
        self._handler(control)
