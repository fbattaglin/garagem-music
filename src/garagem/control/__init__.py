"""Controller input — the MiniLab 3 behind a port, with a fake. Infrastructure (ADR-021)."""

from garagem.control.errors import ControlError, ControllerSpecError, ControllerUnavailableError
from garagem.control.fake import FakeController
from garagem.control.mapping import ControllerSpec, KnobSpec, PadSpec, load_controller
from garagem.control.midi import MidoController
from garagem.control.port import ControlHandler, ControllerPort

__all__ = [
    "ControlError",
    "ControlHandler",
    "ControllerPort",
    "ControllerSpec",
    "ControllerSpecError",
    "ControllerUnavailableError",
    "FakeController",
    "KnobSpec",
    "MidoController",
    "PadSpec",
    "load_controller",
]
