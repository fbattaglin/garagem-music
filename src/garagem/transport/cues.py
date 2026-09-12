"""`CueQueue`: where a person's cues wait for the scheduler. Invariant 1, for people.

The controller hears a pad on its own thread; the scheduler decides what sounds on its own.
They meet here and nowhere else — the same shape as `ScoreBuffer`, for the same reason
(ADR-022). `offer` takes a lock for a moment and returns, so the controller's thread is never
held up. `drain` hands over everything that arrived, so the scheduler is never waiting on a
person.

**Every control is stamped with the beat Live had reported when it arrived.** That is the
`cue_bar` Phase 4's criterion is measured from, and it has to be the arrival beat rather
than the moment the scheduler got round to it: a cue that waited behind a write is exactly
the latency the log exists to show.

**Macros are coalesced; cues are not.** A knob is absolute, so only its latest position
means anything, and a turn is a hundred messages that would otherwise bury the one pad
strike that matters. Each macro kind keeps its latest value. Cues keep their order and are
bounded: past `CAPACITY` the oldest is dropped and counted, because a person's latest intent
is the one to honour.

The stamp is read outside the lock. It takes the clock's own lock, and two locks taken in
two orders on two threads is how a deadlock gets written.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from typing import Final

from garagem.domain import Control, Cue, Macro, MacroKind

# Far more cues than a person can strike between two drains, which are a bar apart at most.
CAPACITY: Final = 64


@dataclass(frozen=True, slots=True)
class Received:
    """A control, the beat it arrived at, and its place in the order of arrival."""

    control: Control
    beat: int
    order: int


class CueQueue:
    """Controls waiting to be acted on. Bounded, non-blocking, thread-safe."""

    def __init__(self, stamp: Callable[[], int], capacity: int = CAPACITY) -> None:
        self._stamp = stamp
        self._lock = threading.Lock()
        self._cues: deque[Received] = deque()
        self._macros: dict[MacroKind, Received] = {}
        self._capacity = capacity
        self._order = count()
        self.dropped = 0

    def offer(self, control: Control) -> None:
        """Called from the controller's thread. Stores and returns; never blocks for long."""
        beat = self._stamp()
        with self._lock:
            received = Received(control=control, beat=beat, order=next(self._order))
            if isinstance(control, Macro):
                self._macros[control.kind] = received
                return
            if len(self._cues) >= self._capacity:
                self._cues.popleft()
                self.dropped += 1
            self._cues.append(received)

    def drain(self) -> tuple[Received, ...]:
        """Everything that arrived since the last drain, in the order it arrived."""
        with self._lock:
            waiting = [*self._cues, *self._macros.values()]
            self._cues.clear()
            self._macros.clear()
        return tuple(sorted(waiting, key=lambda received: received.order))

    def __len__(self) -> int:
        with self._lock:
            return len(self._cues) + len(self._macros)


def describe(control: Control) -> dict[str, str | float]:
    """How a control appears in the event log: its kind, and a macro's value."""
    if isinstance(control, Cue):
        return {"cue": str(control.kind), "family": str(control.kind.family)}
    return {"macro": str(control.kind), "value": round(control.value, 3)}
