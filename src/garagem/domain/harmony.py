"""Chords and charts: the harmonic spine of a section, in pitch classes.

**Pitch classes, never note names.** A `Chord` here is `root=4, quality=MINOR`, not
`"Em"`. Text is a boundary concern and belongs in `theory/chords.py`, which is the one
place that has to decide whether the fifth of B is F# or Gb. Keeping names out means
every engine does arithmetic on integers, and no engine has to know about enharmonics.

**One chord per bar.** The DSL's `CHD` line is exactly that — `| Em | Em | C | D |` —
and it is a deliberate limit rather than a missing feature: mid-bar changes would double
the grammar and rock spends most of its time on the bar line. When a section needs one,
the section gets shorter bars, not a richer chart.

`Chart.at` wraps, which is the other half of the same decision: a four-chord loop under
an eight-bar section is how the music actually works, and putting the modulo here means
no engine has to remember it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

FROZEN = ConfigDict(frozen=True, extra="forbid")

PITCH_CLASSES: Final = 12


class Quality(StrEnum):
    """The chord vocabulary the deterministic engines can build and the DSL can name.

    Deliberately short. Every quality here earns its place in rock; anything richer is a
    voicing decision (`theory/voicings.py`) or a note the engines add on top, not a new
    kind of chord. A vocabulary the validator cannot check is a vocabulary that lets
    model output through unexamined.
    """

    MAJOR = "maj"
    MINOR = "min"
    DOM7 = "7"
    MIN7 = "min7"
    MAJ7 = "maj7"
    SUS2 = "sus2"
    SUS4 = "sus4"
    DIM = "dim"
    POWER = "5"


# Semitones above the root. The power chord has two notes on purpose: it has no third,
# which is why it sits equally well over a major and a minor bar and why distorted
# guitar uses it at all.
INTERVALS: Final[dict[Quality, tuple[int, ...]]] = {
    Quality.MAJOR: (0, 4, 7),
    Quality.MINOR: (0, 3, 7),
    Quality.DOM7: (0, 4, 7, 10),
    Quality.MIN7: (0, 3, 7, 10),
    Quality.MAJ7: (0, 4, 7, 11),
    Quality.SUS2: (0, 2, 7),
    Quality.SUS4: (0, 5, 7),
    Quality.DIM: (0, 3, 6),
    Quality.POWER: (0, 7),
}


class Chord(BaseModel):
    """A root pitch class and a quality. C is 0, C# is 1, B is 11."""

    model_config = FROZEN

    root: int = Field(ge=0, le=PITCH_CLASSES - 1)
    quality: Quality

    def intervals(self) -> tuple[int, ...]:
        """Semitones above the root, ascending, starting at 0."""
        return INTERVALS[self.quality]

    def pitch_classes(self) -> frozenset[int]:
        """The chord's own tones, as pitch classes. What "in the chord" means."""
        return frozenset((self.root + step) % PITCH_CLASSES for step in self.intervals())


class Chart(BaseModel):
    """One chord per bar. The section's harmonic spine.

    Shorter than the section it covers, as a rule: `at` wraps, so four chords carry
    eight bars and the loop is the arrangement rather than a special case.
    """

    model_config = FROZEN

    chords: tuple[Chord, ...] = Field(min_length=1)

    def at(self, bar: int) -> Chord:
        """The chord for `bar`, wrapping. Bar 0 is the first bar of the section."""
        if bar < 0:
            raise ValueError(f"a bar index is not negative, got {bar}")
        return self.chords[bar % len(self.chords)]

    def changes_at(self, bar: int) -> bool:
        """True when `bar` starts a different chord from the bar before it.

        The bass engine puts a root on every one of these, and the validator checks it.
        Both ask the chart rather than deriving it, so there is one definition of a
        chord change and bar 0 counts as one.
        """
        return bar == 0 or self.at(bar) != self.at(bar - 1)
