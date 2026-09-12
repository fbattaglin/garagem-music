"""`MidoController`: the MiniLab 3, heard through CoreMIDI by `mido` and `python-rtmidi`.

The only module in `src/` that imports a MIDI library. Its job is to open one input port,
turn each message into four integers, ask the spec what they mean, and hand the answer to
the handler — on rtmidi's callback thread, so nothing here may block.

**It opens the port the spec names and no other**, and refuses rather than guessing when
that port is not there: the MiniLab exposes four (`phase-4-findings.md` §7), and listening
to the wrong one is a controller that silently does nothing. The error lists the ports that
do exist.

**It never sends.** No output port is opened, so no LED, mode change or SysEx can leave
this process.

The backend is injectable, so the whole adapter is tested with `mido.Message` objects and no
hardware; `mido.Message` is plain data and constructing one opens nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import mido

from garagem.control.errors import ControllerUnavailableError
from garagem.control.mapping import ControllerSpec
from garagem.control.port import ControlHandler


class InputPort(Protocol):
    def close(self) -> None: ...


class Backend(Protocol):
    """The two things this adapter needs from `mido`."""

    def get_input_names(self) -> list[str]: ...

    def open_input(self, name: str, *, callback: Callable[[Any], None]) -> InputPort: ...


class _Mido:
    def get_input_names(self) -> list[str]:
        return list(mido.get_input_names())

    def open_input(self, name: str, *, callback: Callable[[Any], None]) -> InputPort:
        port: InputPort = mido.open_input(name, callback=callback)
        return port


class MidoController:
    """Pads and knobs from a real controller, as cues and macros."""

    def __init__(self, spec: ControllerSpec, *, backend: Backend | None = None) -> None:
        self._spec = spec
        self._backend: Backend = backend if backend is not None else _Mido()
        self._port: InputPort | None = None
        self._handler: ControlHandler | None = None

    @property
    def name(self) -> str:
        return self._spec.port

    def start(self, handler: ControlHandler) -> None:
        if self._port is not None:
            return
        names = self._backend.get_input_names()
        if self._spec.port not in names:
            raise ControllerUnavailableError(
                f"no MIDI input called {self._spec.port!r}; found {names or 'none'}. "
                "Is the MiniLab plugged in, and does controller.toml name the port "
                "`scripts/probe_minilab.py --list` shows?"
            )
        self._handler = handler
        self._port = self._backend.open_input(self._spec.port, callback=self._on_message)

    def stop(self) -> None:
        port, self._port, self._handler = self._port, None, None
        if port is not None:
            port.close()

    def _on_message(self, message: Any) -> None:  # noqa: ANN401 - mido ships no types
        """rtmidi's thread. Translate and hand over; never block, never raise."""
        handler = self._handler
        channel = getattr(message, "channel", None)
        if handler is None or channel is None:
            return
        kind = str(message.type)
        if kind == "note_on":
            number, value = int(message.note), int(message.velocity)
        elif kind == "control_change":
            number, value = int(message.control), int(message.value)
        else:
            return
        control = self._spec.translate(kind, int(channel), number, value)
        if control is not None:
            handler(control)
