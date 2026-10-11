"""The pocket: where each player sits against the beat, the same way every time.

`humanise` makes every note a little early or late at random, the same for every player.
A band is not like that. A rock drummer lays the backbeat back, the bass sits just behind the
kick, and a guitarist's downstroke reaches the low string before the high one. Those leans
are not noise, they are each player's habit, so here they are fixed rather than drawn
(ADR-028). That is why the pocket draws nothing from any `Random`, and why it can be switched
off for a comparison without moving a single other note.

**It is applied on the way out, by `transport/render.py`, and nowhere else.** Every note that
reaches Live passes through there, including the endings and the cue variants composed over a
score. The validator, the golden files and the round trip all see the grid without the pocket,
which keeps them exact.

**Every lean is smaller than the grid tolerance less the humaniser's widest push**
(`MAX_LEAN_BEATS`), so a pocketed note is still on the grid it was written on. At 132 BPM a
hundredth of a beat is 4.5 ms.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from garagem.domain import Instrument, Note, Part
from garagem.engines.humanise import separate
from garagem.theory.percussion import CLOSED_HAT, OPEN_HAT, SNARE

# The room the grid leaves: `validator.GRID_TOLERANCE_BEATS` (0.03) less the humaniser's
# `MAX_TIMING_BEATS` (0.02). A test pins it against both.
MAX_LEAN_BEATS: Final = 0.01

# The drummer: the backbeat laid back, the hats a hair ahead. The kick is the reference
# every other lean is measured from, so it does not move.
DRUM_LEANS: Final[dict[int, float]] = {
    SNARE: 0.008,
    CLOSED_HAT: -0.003,
    OPEN_HAT: -0.003,
}

# Whole parts that sit behind the beat.
PART_LEANS: Final[dict[Instrument, float]] = {
    Instrument.BASS: 0.005,
    Instrument.LEAD: 0.004,
}

# A downstroke reaches the low string first: this much later per string, upwards.
STRUM_BEATS: Final = 0.003
# Notes this close are one chord: twice the humaniser's widest push, and far under the
# smallest gap between two strums (a sixteenth, a quarter of a beat).
CHORD_WINDOW_BEATS: Final = 0.05
STRUMMED: Final[frozenset[Instrument]] = frozenset({Instrument.GUITAR, Instrument.GUITAR_DOUBLE})


def lean(part: Part) -> tuple[Note, ...]:
    """`part`'s notes, each moved to where its player sits against the beat.

    Separated again afterwards: a pitch that is the top string of one chord and the bottom
    string of the next leans by two different amounts, and could otherwise run into itself.
    """
    if part.instrument is Instrument.DRUMS:
        moved = tuple(_moved(note, DRUM_LEANS.get(note.pitch, 0.0)) for note in part.notes)
    elif part.instrument in STRUMMED:
        moved = _strummed(part.notes)
    else:
        behind = PART_LEANS.get(part.instrument, 0.0)
        moved = tuple(_moved(note, behind) for note in part.notes)
    return separate(moved)


def _strummed(notes: Iterable[Note]) -> tuple[Note, ...]:
    """Notes struck together are spread low to high, the way a pick crosses the strings.

    "Together" is a cluster rather than an equal start: the humaniser has already moved
    every note of a chord on its own, so a chord arrives as notes a few hundredths of a beat
    apart. The strum starts from the earliest of them, which keeps the chord's lateness
    inside what the humaniser drew.
    """
    spread: list[Note] = []
    for chord in _clusters(sorted(notes, key=lambda note: note.start_beats)):
        anchor = chord[0].start_beats
        for string, note in enumerate(sorted(chord, key=lambda note: note.pitch)):
            spread.append(note.model_copy(update={"start_beats": anchor + string * STRUM_BEATS}))
    return tuple(sorted(spread, key=lambda note: (note.start_beats, note.pitch)))


def _clusters(ordered: list[Note]) -> list[list[Note]]:
    clusters: list[list[Note]] = []
    for note in ordered:
        if clusters and note.start_beats - clusters[-1][0].start_beats <= CHORD_WINDOW_BEATS:
            clusters[-1].append(note)
        else:
            clusters.append([note])
    return clusters


def _moved(note: Note, by: float) -> Note:
    if by == 0.0:
        return note
    start = max(0.0, round(note.start_beats + by, 6))
    return note.model_copy(update={"start_beats": start})
