"""Fragments in, parts out as soon as they are whole. ADR-011 in code.

**Progressive parsing, atomic publication.** This module reports an instrument the
moment its lines are complete, so the producer can start realising drums while keys is
still arriving. It does not touch a `ScoreBuffer` and does not know one exists: a score
that grows after publication is a score the scheduler can read half-written, which is
exactly what invariant 1's data structure is there to prevent.

**The mandated order is what makes completeness decidable.** `SEC → CHD → DRM → BAS →
GTR → KEY` is rhythmic priority, and because it is fixed, a `BAS` line is proof that the
drums are finished. Without it there is no moment at which anything is known to be
complete except the end of the stream — which is the same as not parsing incrementally
at all.

**Violations accumulate; they do not raise.** A malformed line costs that line and
nothing else: the section still has most of its notes, and the exit criterion is a *rate*
that needs a count rather than a first failure. Only a broken *envelope* raises — a
wrong field, an impossible escape — because there is no partial section to salvage from
a tool input that is not the object the schema promised.

A stream that stops early is a `truncated` result, not an error. `engines.band` supplies
the rest, which is P2 and was already the scheduler's behaviour for a section that never
arrived at all.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

from garagem.domain import Chart, Instrument, Section
from garagem.dsl.errors import LineError, StreamProtocolError
from garagem.dsl.fragments import StringField
from garagem.dsl.lines import (
    BarLine,
    BassLine,
    DrumLine,
    check_chd,
    check_sec,
    parse_bar_line,
    parse_chd,
    parse_sec,
    tag_of,
)
from garagem.dsl.schema import TOOL
from garagem.llm import StreamEvent
from garagem.theory import Violation

FROZEN = ConfigDict(frozen=True, extra="forbid")

# Rhythmic priority. A line for a later instrument closes every earlier one.
ORDER: Final[tuple[Instrument, ...]] = (
    Instrument.DRUMS,
    Instrument.BASS,
    Instrument.GUITAR,
    Instrument.KEYS,
)

# The rule name a line that would not parse is counted under. It is the name the exit
# criterion is stated in — "≥95% schema conformance on the first pass".
SCHEMA_RULE: Final = "schema"


class ParsedSection(BaseModel):
    """What arrived, per instrument, plus everything wrong with it.

    The `Section` is the briefing and is ours (ADR-011): the model's `SEC` line is an
    echo, checked and counted, never obeyed.
    """

    model_config = FROZEN

    section: Section
    chart: Chart | None = None
    lines: dict[Instrument, tuple[BarLine, ...]] = {}
    violations: tuple[Violation, ...] = ()
    truncated: bool = False

    def instruments(self) -> frozenset[Instrument]:
        return frozenset(instrument for instrument, lines in self.lines.items() if lines)


class SectionStream:
    """One section's worth of stream, assembled as it arrives."""

    def __init__(self, asked: Section) -> None:
        self._asked = asked
        self._decoder = StringField()
        self._buffer = ""
        self._lines: dict[Instrument, list[BarLine]] = {instrument: [] for instrument in ORDER}
        self._chart: Chart | None = None
        self._violations: list[Violation] = []
        self._ready: set[Instrument] = set()
        self._latest = -1
        self._done = False
        self._saw_tool = False

    # ---------------------------------------------------------------------------- feeding

    def feed(self, event: StreamEvent) -> tuple[Instrument, ...]:
        """Consume one stream event. Returns the instruments that just became complete.

        Usually empty. On the event that carries the first `BAS` line it returns
        `(DRUMS,)`, which is the moment §4.3's halved latency becomes available.
        """
        if event.type == "tool_use_start":
            if event.name != TOOL.name:
                raise StreamProtocolError(
                    f"the model called {event.name!r}; the only tool is {TOOL.name!r}"
                )
            self._saw_tool = True
            return ()
        if event.type == "tool_input_delta":
            return self._text(self._decoder.feed(event.fragment))
        if event.type == "done":
            return self._finish()
        # A `text_delta` is the model talking outside the tool. ADR-009 says the answer
        # comes through the schema, so there is nothing here to parse — and nothing worth
        # failing over either, because the tool input may still be perfect.
        return ()

    def _text(self, decoded: str) -> tuple[Instrument, ...]:
        if not decoded:
            return ()
        self._buffer += decoded
        completed: list[Instrument] = []
        while "\n" in self._buffer:
            line, _, self._buffer = self._buffer.partition("\n")
            completed.extend(self._line(line))
        return tuple(completed)

    def _finish(self) -> tuple[Instrument, ...]:
        """End of stream: the last line may have no newline, and everything closes."""
        completed: list[Instrument] = []
        if self._buffer.strip():
            completed.extend(self._line(self._buffer))
        self._buffer = ""
        self._done = True
        for instrument in ORDER:
            if self._lines[instrument] and instrument not in self._ready:
                self._ready.add(instrument)
                completed.append(instrument)
        return tuple(completed)

    # ----------------------------------------------------------------------- one line

    def _line(self, text: str) -> list[Instrument]:
        tag = tag_of(text)
        if not tag:
            return []
        try:
            if tag == "SEC":
                self._violations.extend(check_sec(parse_sec(text), self._asked))
                return []
            if tag == "CHD":
                self._chart = parse_chd(text)
                self._violations.extend(check_chd(self._chart, self._asked))
                return []
            return self._bar_line(text, tag)
        except LineError as error:
            self._violations.append(self._schema_violation(tag, str(error)))
            return []

    def _bar_line(self, text: str, tag: str) -> list[Instrument]:
        parsed = parse_bar_line(text)
        instrument = _instrument_of(parsed)
        position = ORDER.index(instrument)

        # A line for a later instrument is proof that every earlier one is finished.
        closed = self._close_before(position)
        self._latest = max(self._latest, position)

        if len(self._lines[instrument]) >= self._asked.bars:
            self._violations.append(
                self._schema_violation(
                    tag,
                    f"more than {self._asked.bars} lines for {instrument}; "
                    "a bar-level line is one bar, or one line covers them all",
                )
            )
            return closed

        self._lines[instrument].append(parsed)
        if len(self._lines[instrument]) == self._asked.bars:
            self._ready.add(instrument)
            closed.append(instrument)
        return closed

    def _close_before(self, position: int) -> list[Instrument]:
        closed = []
        for earlier in ORDER[:position]:
            if self._lines[earlier] and earlier not in self._ready:
                self._ready.add(earlier)
                closed.append(earlier)
        return closed

    def _schema_violation(self, tag: str, detail: str) -> Violation:
        return Violation(
            rule=SCHEMA_RULE,
            instrument=_instrument_for_tag(tag),
            detail=detail,
            repairable=False,
        )

    # ---------------------------------------------------------------------------- reading

    @property
    def ready(self) -> frozenset[Instrument]:
        """Instruments whose lines are complete and can be realised now."""
        return frozenset(self._ready)

    def violations(self) -> tuple[Violation, ...]:
        return tuple(self._violations)

    def result(self) -> ParsedSection:
        """Everything that arrived. `truncated` when the stream ended mid-section."""
        expected = len(ORDER)
        arrived = sum(1 for instrument in ORDER if self._lines[instrument])
        return ParsedSection(
            section=self._asked,
            chart=self._chart,
            lines={instrument: tuple(lines) for instrument, lines in self._lines.items() if lines},
            violations=tuple(self._violations),
            truncated=not self._saw_tool or arrived < expected,
        )


def _instrument_of(line: BarLine) -> Instrument:
    if isinstance(line, DrumLine):
        return Instrument.DRUMS
    if isinstance(line, BassLine):
        return Instrument.BASS
    return line.instrument


def _instrument_for_tag(tag: str) -> Instrument:
    """Which instrument a violation belongs to. `SEC` and `CHD` belong to nobody."""
    try:
        return Instrument(tag)
    except ValueError:
        return Instrument.DRUMS


def parse_section(events: list[StreamEvent], asked: Section) -> ParsedSection:
    """Whole stream to whole result. Convenience for tests and for a non-streaming path."""
    stream = SectionStream(asked)
    for event in events:
        stream.feed(event)
    return stream.result()
