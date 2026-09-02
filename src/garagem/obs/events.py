"""The session as an event log: what happened, at which beat, from which seed.

P6 says the session *is* an event log. Two decisions make that more than a slogan.

**Time is musical, not wall-clock.** Every event carries `at_beats`. A log stamped with
`time.monotonic()` can tell you a section was late; a log stamped in beats can be
replayed against the music and say *which bar* it was late for. Wall time is the
scheduler's problem and it already has a clock.

**Every event that can name a seed does.** Invariant 7 says a generation is reproducible
from its seed; a log that recorded "fallback" without one records that something went
wrong and throws away the only means of reproducing it.

Split like `obs/latency.py`: the shaping, the validation and the rendering are pure, and
the two functions that touch a disk are the last ten lines. That is what lets the default
suite test the log without writing anywhere except `tmp_path` — and it matters more here,
because `.claude/rules/realtime.md` forbids synchronous disk writes inside the bar loop.
`EventLog` therefore buffers in memory and flushes between sections; the buffering is
here rather than at the call site so the scheduler cannot get it wrong.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

FROZEN = ConfigDict(frozen=True, extra="forbid")

KINDS: Final[tuple[str, ...]] = (
    "section_generated",
    "section_written",
    "scene_fired",
    "fallback",
    "violation_repaired",
    "beat_lost",
    "human_veto",
    # Phase 3. The exit criteria are *rates* — "≥95% schema conformance", "≥80% validator
    # approval" — so the log has to be able to answer "out of how many". A denominator
    # that is not recorded is a rate nobody can compute, which is why `section_requested`
    # exists as its own kind rather than being inferred from what came back.
    #
    # `section_parsed` and `section_generated` are deliberately different kinds and the
    # distinction is load-bearing: the producer *parsed* a section into the buffer, and
    # the scheduler *generated* — or took — the one it then played. They usually differ,
    # and while they shared a name the computed rate ran over 100%.
    "section_requested",
    "section_parsed",
    "deadline_missed",
    "schema_violation",
)

# The kinds a rate can be computed over, and what each one divides by. Written down so
# that `obs/sections.py` and any later report agree on the arithmetic rather than each
# deriving it: a conformance rate measured against "sections we liked" is not a rate.
DENOMINATOR: Final = "section_requested"

Detail = dict[str, str | int | float | bool]


class Event(BaseModel):
    """One thing that happened, at one point in the music."""

    model_config = FROZEN

    at_beats: float = Field(ge=0.0)
    kind: str
    detail: Detail = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, kind: str) -> str:
        """An unknown kind is a typo that would silently never be counted."""
        if kind not in KINDS:
            raise ValueError(f"unknown event kind {kind!r}; known are {', '.join(KINDS)}")
        return kind


class MalformedEventError(ValueError):
    """A line in the log that is not an event, with the line number to look at.

    Raised rather than skipped: a log with an unreadable line is a log that cannot be
    trusted to be complete, and quietly dropping it would make "zero glitches" a claim
    about the lines that happened to parse.
    """


class EventLog:
    """Events in memory, written to disk between sections and never during a bar.

    Not thread-safe by design and not needed to be: everything that logs runs on the
    scheduler's thread. The beat listener runs on the receive thread and does no musical
    work at all (ADR-014), which includes not logging.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._buffered: list[Event] = []
        self._written = 0

    def record(self, kind: str, at_beats: float, **detail: str | int | float | bool) -> Event:
        """Buffer one event. No I/O: this is called from inside the bar loop."""
        event = Event(at_beats=at_beats, kind=kind, detail=dict(detail))
        self._buffered.append(event)
        return event

    def flush(self) -> int:
        """Write everything buffered. Returns how many lines went out."""
        pending = self._buffered[self._written :]
        if self._path is not None and pending:
            append_events(self._path, pending)
        self._written = len(self._buffered)
        return len(pending)

    @property
    def events(self) -> tuple[Event, ...]:
        """Everything recorded this session, flushed or not."""
        return tuple(self._buffered)

    def of_kind(self, kind: str) -> tuple[Event, ...]:
        return tuple(event for event in self._buffered if event.kind == kind)

    def __len__(self) -> int:
        return len(self._buffered)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._buffered)


def rate_of(events: Iterable[Event], kind: str, *, over: str = DENOMINATOR) -> float | None:
    """How often `kind` happened, per `over`. `None` when nothing was asked.

    `None` rather than 0.0 on an empty denominator, and the difference matters: a run
    that made no calls has no conformance rate, and reporting one as 0% would say the
    model failed when it was never asked.
    """
    counted = list(events)
    total = sum(1 for event in counted if event.kind == over)
    if not total:
        return None
    return sum(1 for event in counted if event.kind == kind) / total


def append_events(path: Path, events: Iterable[Event]) -> None:
    """Append-only, one JSON object per line. Two writers interleave lines, never bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(event.model_dump_json() + "\n")


def load_events(path: Path) -> tuple[Event, ...]:
    """Every event in the file, or `MalformedEventError` naming the line that is not one."""
    if not path.exists():
        return ()
    events: list[Event] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(Event.model_validate(json.loads(line)))
        except ValueError as error:
            raise MalformedEventError(f"{path}:{number}: {error}") from error
    return tuple(events)
