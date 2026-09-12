"""`FormPlan`: the song as it stands, shared by the scheduler that changes it and the producer.

Before the MiniLab the form was a tuple fixed at the downbeat, and both threads held their
own copy. A jump cue changes it mid-song (ADR-022): the scheduler re-plans everything after
the section it jumped to, and the producer must stop generating for briefings nobody will
play and start on the ones that replaced them.

**One writer, one reader, a lock, and a version.** The scheduler replaces the whole plan at
once; the producer reads a section and, before offering what it generated, checks that the
plan still holds the same briefing at that index. A score for a briefing the plan dropped is
stale, and the scheduler refuses it again on the way out of the buffer, because a check on
one side of a race is a hope.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from garagem.domain import Section
from garagem.engines import Ending


class FormPlan:
    """The sections of the song and how each ends, versioned, safe to read from any thread."""

    def __init__(
        self, sections: Sequence[Section] = (), endings: Sequence[Ending] | None = None
    ) -> None:
        self._lock = threading.Lock()
        self._sections = tuple(sections)
        self._endings = None if endings is None else tuple(endings)
        self._version = 0

    def replace(self, sections: Sequence[Section], endings: Sequence[Ending] | None) -> int:
        """Swap in a new plan. Returns its version."""
        with self._lock:
            self._sections = tuple(sections)
            self._endings = None if endings is None else tuple(endings)
            self._version += 1
            return self._version

    def sections(self) -> tuple[Section, ...]:
        with self._lock:
            return self._sections

    def endings(self) -> tuple[Ending, ...] | None:
        with self._lock:
            return self._endings

    def at(self, index: int) -> Section | None:
        """The briefing at `index`, or `None` past the end of the song."""
        with self._lock:
            return self._sections[index] if 0 <= index < len(self._sections) else None

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._sections)
