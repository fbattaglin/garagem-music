"""`ScoreBuffer`: the data structure that *is* P1's boundary.

Invariant 1 says the musical clock and the cognitive one are separated by a data
structure, "never by a function call". This is that data structure. A generator that
takes four seconds and a player that must be punctual meet here and nowhere else; neither
ever calls the other, and neither can block the other.

**`take` returns `None` rather than blocking or raising.** That is the whole design, and
it is P2 in one line: the music degrades, it never stops. A caller that finds nothing
here plays the deterministic engine and logs a fallback — its very next line. A future
reader will want to add `wait=True`; adding it would make the player wait on the
generator, which is exactly the coupling the ScoreBuffer exists to prevent.

**The window is two sections** (ADR-000 §7). Not a queue: a buffer that accepted work
arbitrarily far ahead would let a generator run away from a transport somebody has
stopped, and by the time anyone noticed there would be a minute of music queued for bars
that were never going to arrive.

Thread-safe by a single lock. Everything it holds is a frozen `SectionScore`, so what
comes out of `take` cannot be half-written: the score exists complete before it is
offered, or it does not exist.
"""

from __future__ import annotations

import threading
from typing import Final

from garagem.domain import SectionScore

WINDOW: Final = 2


class ScoreBuffer:
    """Sections waiting to be played. Bounded, non-blocking, and honest about gaps."""

    def __init__(self, window: int = WINDOW) -> None:
        self._window = window
        self._lock = threading.Lock()
        self._scores: dict[int, SectionScore] = {}
        self._floor = 0
        # The last section the scheduler has written into Live. Music generated for it, or
        # for anything before it, can never be heard: the scheduler writes the next section
        # in the first bar of the one playing, and does not write it again.
        self._written = -1
        # Observables. `refused` rising means a generator is working on music nobody will
        # ever hear, which is a scheduling bug rather than a musical one.
        self.refused = 0

    def offer(self, index: int, score: SectionScore) -> bool:
        """Put a generated section in. False when the window has moved past it.

        A refusal is information, not an error: the generator finished after the section
        was needed, and the deterministic floor has already played it.
        """
        with self._lock:
            if index < self._floor or index <= self._written or index > self._floor + self._window:
                self.refused += 1
                return False
            self._scores[index] = score
            return True

    def take(self, index: int) -> SectionScore | None:
        """The section for this index, or `None` — which means *play the fallback*."""
        with self._lock:
            return self._scores.get(index)

    def advance(self, index: int) -> None:
        """The music has reached `index`. Everything before it is history."""
        with self._lock:
            self._floor = max(self._floor, index)
            for stale in [key for key in self._scores if key < self._floor]:
                del self._scores[stale]

    def written(self, index: int) -> None:
        """Section `index` is in Live. A model still asked for it would be playing to nobody.

        Found by rehearsing Stage 6's session offline: conducted from the MiniLab, a third
        to a half of the calls asked for a section the floor had already written, because
        `wanted` began at the section playing (`phase-4-findings.md` §12).
        """
        with self._lock:
            self._written = max(self._written, index)

    def discard_from(self, index: int) -> None:
        """Drop everything generated for `index` and after. What a re-planned form means."""
        with self._lock:
            for stale in [key for key in self._scores if key >= index]:
                del self._scores[stale]

    def clear(self) -> None:
        """Throw everything away. What a rewind means: those bars are not coming."""
        with self._lock:
            self._scores.clear()
            # Only the section playing is still in Live; everything after it is written again.
            self._written = min(self._written, self._floor)

    def pending(self) -> tuple[int, ...]:
        """Which indices are actually ready, ascending."""
        with self._lock:
            return tuple(sorted(self._scores))

    def wanted(self) -> tuple[int, ...]:
        """Indices inside the window with nothing in them yet — what to generate next."""
        with self._lock:
            first = max(self._floor, self._written + 1)
            return tuple(
                index
                for index in range(first, self._floor + self._window + 1)
                if index not in self._scores
            )

    @property
    def floor(self) -> int:
        with self._lock:
            return self._floor

    def __len__(self) -> int:
        with self._lock:
            return len(self._scores)
