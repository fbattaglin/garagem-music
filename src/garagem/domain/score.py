"""A section: the briefing, the notes that realise it, and the seed that produced them.

`Note` here is not `daw.MidiNote`, and the duplication is deliberate. `.claude/rules/
domain-purity.md` forbids `domain/` importing `daw/`, and the reason is not tidiness:
`MidiNote` is the Live Object Model's five-tuple in the LOM's field order, a wire
concern that would otherwise get a vote on how music is modelled. `transport/render.py`
is the one place the two meet. The two types validate the same two things for the same
two reasons, and the reasons are restated here rather than cross-referenced, because a
reader of `domain/` should not have to open `daw/port.py` to learn why velocity 0 is
refused.

`SectionScore` carries its `seed`. That is invariant 7 — "every generation is
deterministic given a seed" — made structural: a score that cannot say what produced it
cannot be replayed and cannot go in the event log, so the type refuses to exist without
one.

A `Section` is a *briefing*, not music: eight bars of E minor at 132 with this chart and
this much tension. What an engine does with it is `SectionScore`. Keeping them apart is
what lets the same briefing be realised by the deterministic floor now and by an LLM in
Phase 3, and compared.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from garagem.domain.harmony import PITCH_CLASSES, Chart
from garagem.domain.time import BEATS_PER_BAR, Feel

FROZEN = ConfigDict(frozen=True, extra="forbid")

MAX_BARS = 32
MIN_DYN = 1
MAX_DYN = 5


class Instrument(StrEnum):
    """The four voices of the band, tagged as the DSL tags them.

    The values are the DSL's three-letter line prefixes, so a part and its serialised
    line cannot drift apart (`.claude/skills/garagem-dsl`). Phase 6 adds a fifth voice by
    adding a member here and an engine; nothing else in the system enumerates them.
    """

    DRUMS = "DRM"
    BASS = "BAS"
    GUITAR = "GTR"
    KEYS = "KEY"


class Note(BaseModel):
    """A sounding note: absolute pitch, position and length in beats from the section.

    Beats, not seconds: the section carries the tempo, so a bpm change moves the music
    rather than breaking it. Position is relative to the section's own start, which is
    what makes a `SectionScore` a portable object — the scheduler decides which bar of
    the song it lands in, and the score never knows.
    """

    model_config = FROZEN

    pitch: int = Field(ge=0, le=127)
    start_beats: float = Field(ge=0.0)
    # Strictly positive, as in `daw.MidiNote`: a zero-length note is not a short note,
    # it is silence with a velocity, and Live stores one happily.
    duration_beats: float = Field(gt=0.0)
    # Velocity 0 is a note-off in MIDI, never a quiet note. Refusing it here stops a
    # whole part going silent because a generator scaled a dynamic to zero.
    velocity: int = Field(ge=1, le=127, default=100)


class Part(BaseModel):
    """One instrument's notes for one section."""

    model_config = FROZEN

    instrument: Instrument
    notes: tuple[Note, ...] = ()

    def last_beat(self) -> float:
        """Where the part stops sounding. 0.0 when it plays nothing."""
        return max((note.start_beats + note.duration_beats for note in self.notes), default=0.0)


class Section(BaseModel):
    """A briefing — what to play, not yet the notes. The DSL's `SEC` line, typed."""

    model_config = FROZEN

    name: str = Field(min_length=1)
    bars: int = Field(ge=1, le=MAX_BARS)
    key: int = Field(ge=0, le=PITCH_CLASSES - 1)
    # A name from `theory.scales.SCALES`. Kept as text rather than an enum because
    # `theory/` owns the vocabulary and `domain/` must not import a table to hold a
    # label; `theory.pitch_classes` is what refuses an unknown one, with the list.
    scale: str = Field(min_length=1)
    feel: Feel
    bpm: float = Field(gt=20.0, lt=999.0)
    dyn: int = Field(ge=MIN_DYN, le=MAX_DYN)
    tension: float = Field(ge=0.0, le=1.0)
    chart: Chart

    def total_beats(self) -> float:
        return self.bars * BEATS_PER_BAR

    def total_seconds(self) -> float:
        """How long the section lasts. The one place tempo becomes wall time."""
        return self.total_beats() * 60.0 / self.bpm


class SectionScore(BaseModel):
    """A briefing plus the notes that realise it, and the seed that produced them."""

    model_config = FROZEN

    section: Section
    parts: tuple[Part, ...] = ()
    seed: int

    @model_validator(mode="after")
    def _one_part_per_instrument(self) -> SectionScore:
        """Two parts for one instrument would make `part()` a coin toss."""
        instruments = [part.instrument for part in self.parts]
        if len(set(instruments)) != len(instruments):
            raise ValueError(f"one part per instrument, got {sorted(instruments)}")
        return self

    def part(self, instrument: Instrument) -> Part:
        """The part for `instrument`.

        Raises rather than returning `None`: a missing part is a generator bug, and a
        caller that silently renders nothing turns it into an instrument that stopped
        playing for no stated reason.
        """
        for part in self.parts:
            if part.instrument is instrument:
                return part
        present = ", ".join(sorted(str(name) for name in self.instruments())) or "nothing"
        raise KeyError(f"no {instrument} part in this score; it has {present}")

    def instruments(self) -> frozenset[Instrument]:
        return frozenset(part.instrument for part in self.parts)

    def total_beats(self) -> float:
        return self.section.total_beats()
