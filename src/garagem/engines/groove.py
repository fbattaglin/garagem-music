"""The rhythmic vocabulary, as a table somebody can read and argue with.

Every pattern here is written as the DSL writes it — sixteen characters, `x` and `.` —
so what the engine plays and what a model would be asked to write are the same notation.
That is deliberate: when Phase 3 arrives, the deterministic floor and the generated
material are comparable by eye.

There is no cleverness in this file on purpose. A groove generator that derives patterns
from parameters produces music nobody chose and nobody can fix; a table produces music
someone can point at and say "that snare is wrong". Density comes from `dyn`, placement
from `feel`, and both are lookups.

`dyn` runs 1..5 and indexes straight into each feel's tuple. Rising `dyn` adds
subdivision, not volume: velocity is the humaniser's business and the arrangement's.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from garagem.domain import SIXTEENTHS_PER_BAR, SIXTEENTHS_PER_BEAT, Feel, Grid, parse_grid
from garagem.engines.humanise import MAX_TIMING_BEATS
from garagem.theory.percussion import MIN_KICK_INTERVAL_MS


@dataclass(frozen=True, slots=True)
class Groove:
    """One bar of drums: what each voice plays, and a name to argue with it by."""

    name: str
    kick: Grid
    snare: Grid
    hat: Grid


def _groove(name: str, kick: str, snare: str, hat: str) -> Groove:
    return Groove(name=name, kick=parse_grid(kick), snare=parse_grid(snare), hat=parse_grid(hat))


# Indexed by `dyn` - 1. Read down a column and the arrangement gets busier; read across
# and the feel changes where the same energy lands.
GROOVES: Final[dict[Feel, tuple[Groove, ...]]] = {
    Feel.STRAIGHT8: (
        # Quarter-note hats and a bare backbeat: the verse of a song that has somewhere
        # to go.
        _groove("eighths, held back", "x.......x.......", "....x.......x...", "x...x...x...x..."),
        _groove("eighths", "x.......x.......", "....x.......x...", "x.x.x.x.x.x.x.x."),
        _groove("eighths, pushed", "x.....x.x.......", "....x.......x...", "x.x.x.x.x.x.x.x."),
        _groove("driving", "x.....x.x.....x.", "....x.......x...", "xxxxxxxxxxxxxxxx"),
        _groove("flat out", "x..x..x.x..x..x.", "....x.......x...", "xxxxxxxxxxxxxxxx"),
    ),
    Feel.STRAIGHT16: (
        _groove("sixteenths, sparse", "x.......x.......", "....x.......x...", "x.x.x.x.x.x.x.x."),
        _groove("sixteenths", "x......x........", "....x.......x...", "xxxxxxxxxxxxxxxx"),
        _groove(
            "sixteenths, syncopated", "x......x..x.....", "....x.......x...", "xxxxxxxxxxxxxxxx"
        ),
        _groove("sixteenths, driving", "x..x...x..x...x.", "....x.......x...", "xxxxxxxxxxxxxxxx"),
        _groove("sixteenths, flat out", "x.xx..x.x.xx..x.", "....x...x...x..x", "xxxxxxxxxxxxxxxx"),
    ),
    Feel.SHUFFLE: (
        # Hats on the eighths only: under a shuffle those eighths are already swung, so
        # the feel comes from `beats_of` rather than from a different pattern.
        _groove("shuffle, brushed", "x.......x.......", "....x.......x...", "x...x...x...x..."),
        _groove("shuffle", "x.......x.......", "....x.......x...", "x.x.x.x.x.x.x.x."),
        _groove("shuffle, pushed", "x.....x.x.......", "....x.......x...", "x.x.x.x.x.x.x.x."),
        _groove("shuffle, hard", "x.....x.x.....x.", "....x.......x...", "x.x.x.x.x.x.x.x."),
        _groove("shuffle, flat out", "x..x..x.x..x..x.", "....x.......x...", "x.x.x.x.x.x.x.x."),
    ),
    Feel.HALFTIME: (
        # One backbeat instead of two, on beat 3. Everything sounds half as fast without
        # anything changing tempo — which is the whole trick.
        _groove("halftime, empty", "x...............", "........x.......", "x...x...x...x..."),
        _groove("halftime", "x.....x.........", "........x.......", "x...x...x...x..."),
        _groove("halftime, pushed", "x.....x.....x...", "........x.......", "x.x.x.x.x.x.x.x."),
        _groove("halftime, heavy", "x.....x.x...x...", "........x.......", "x.x.x.x.x.x.x.x."),
        _groove("halftime, flat out", "x..x..x.x...x..x", "........x.......", "xxxxxxxxxxxxxxxx"),
    ),
}

# The last bar of a section. Ordered by density, so `tension` indexes into them: a fill
# is how a band says the next thing is coming, and a quiet section says it quietly.
FILLS: Final[tuple[Grid, ...]] = (
    parse_grid("............x..."),
    parse_grid("............x.x."),
    parse_grid("........x.x.x.x."),
    parse_grid("........x.xxx.xx"),
    parse_grid("....x.xxx.xxx.xx"),
)


def groove_for(feel: Feel, dyn: int, bpm: float | None = None) -> Groove:
    """The pattern for this feel at this dynamic level. `dyn` is the DSL's 1..5.

    With a `bpm`, the busiest pattern a human could actually play at that tempo: a
    drummer at 240 does not play the sixteenth-note kick they play at 120, because the
    beater cannot return in time (`MIN_KICK_INTERVAL_MS`). Choosing a simpler pattern is
    what a player does; writing the busy one and letting the repairer ghost half of it
    would be the engine leaning on a rule it is supposed to satisfy.
    """
    patterns = GROOVES[feel]
    wanted = min(max(dyn, 1), len(patterns))
    if bpm is None:
        return patterns[wanted - 1]
    for level in range(wanted, 0, -1):
        if _playable(patterns[level - 1], bpm):
            return patterns[level - 1]
    return patterns[0]


def _playable(groove: Groove, bpm: float) -> bool:
    """Whether every gap between kicks survives a beater's return *and* the humaniser.

    The bar loops, so the gap from the last kick back round to the first counts too.

    The margin is the part that is easy to miss and was: two adjacent kicks can be pushed
    in opposite directions by up to `MAX_TIMING_BEATS` each, so a pattern that is legal on
    the grid can be illegal once it is played. At 222 BPM a sixteenth is 67 ms and the
    humaniser can close it to 57 — under the limit, from a pattern that looked fine.
    Found by `tests/property/test_musical_invariants.py`, which is what it is for.
    """
    attacks = [index for index, slot in enumerate(groove.kick) if slot]
    if len(attacks) < 2:
        return True
    gaps = [after - before for before, after in pairwise(attacks)]
    gaps.append(SIXTEENTHS_PER_BAR - attacks[-1] + attacks[0])
    ms_per_beat = 60_000.0 / bpm
    ms_per_sixteenth = ms_per_beat / SIXTEENTHS_PER_BEAT
    margin = 2 * MAX_TIMING_BEATS * ms_per_beat
    return min(gaps) * ms_per_sixteenth >= MIN_KICK_INTERVAL_MS + margin


def fill_for(tension: float) -> Grid:
    """The fill a section with this much tension ends on."""
    index = min(int(tension * len(FILLS)), len(FILLS) - 1)
    return FILLS[index]
