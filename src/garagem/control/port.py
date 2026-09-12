"""`ControllerPort`: everything the system asks of a controller, which is very little.

A controller is started with somewhere to put what it hears, and stopped. That is the whole
contract, and it is deliberately one-way: the band never talks back to the MiniLab (no
lights, no SysEx), so nothing here can be slow, fail on a write, or leave the instrument in
a state the person did not choose.

**The handler runs on the controller's own thread** and must only hand the control over —
in practice `CueQueue.offer`, which takes a lock for a moment and returns. The ADR-014 idiom
applied to people: receive, store, wake, nothing else. `transport/` never imports this
package; `scripts/jam.py` wires the two together (ADR-022).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from garagem.domain import Control

ControlHandler = Callable[[Control], object]


@runtime_checkable
class ControllerPort(Protocol):
    """A source of cues and macros."""

    @property
    def name(self) -> str: ...

    def start(self, handler: ControlHandler) -> None:
        """Begin delivering controls to `handler`. Raises `ControllerUnavailableError`."""
        ...

    def stop(self) -> None:
        """Stop delivering. Safe to call twice, and without `start`."""
        ...
