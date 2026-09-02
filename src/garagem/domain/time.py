"""The rhythmic grid: sixteen slots to a bar, and where each one actually falls.

Three decisions live here, and everything else in `domain/` inherits them.

**Sixteenths.** The DSL's bar level is a 16-character grid (`.claude/skills/garagem-dsl`)
because that is the resolution a model can hold in its head and still count. Finer would
buy detail no rock arrangement asks for and cost tokens; coarser would lose the
sixteenth-note hi-hat that defines half the vocabulary. Sixteen is the whole reason the
DSL is compact.

**A tuple of bools, not a bitmask.** The skill's anti-patterns say it outright: a hex
encoding is cheap in tokens and the model reasons poorly about bits. The same is true of
the code that reads it. `grid[4]` is a slot; `mask & (1 << 4)` is a puzzle. Sixteen
booleans cost nothing at this scale and every engine indexes them directly.

**Positions are 0-indexed here and 1-indexed in the DSL.** The skill writes `acc=1,9`
because it is written for a model to read; this module is written for a machine to
index. The conversion happens once, at the parser boundary in `dsl/`, and never leaks
inwards — a module that has to remember which convention it is in has already lost.

Beats, never seconds: tempo belongs to the section, not to the grid. `beats_of` answers
"where in the bar", and what that means in milliseconds is Live's business.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

SIXTEENTHS_PER_BAR: Final = 16
BEATS_PER_BAR: Final = 4.0
SIXTEENTHS_PER_BEAT: Final = 4

ATTACK: Final = "x"
REST: Final = "."

# A shuffle is a 2:1 triplet division of the beat: the "and" lands two thirds of the way
# through instead of halfway, which is what a swung eighth-note pair means. Everything
# else in the bar is warped to follow it, so nothing crosses a neighbour (see `beats_of`).
SWING_POINT: Final = 2.0 / 3.0


class Feel(StrEnum):
    """The section's rhythmic character. The DSL's `feel=` field, verbatim.

    Only `SHUFFLE` changes *where* a slot falls. `STRAIGHT8`, `STRAIGHT16` and `HALFTIME`
    differ in which slots the engines fill and where the backbeat sits, not in the
    placement of the grid itself — so `beats_of` gives the same answer for all three, and
    that is a statement about music rather than an omission.
    """

    STRAIGHT8 = "straight8"
    STRAIGHT16 = "straight16"
    SHUFFLE = "shuffle"
    HALFTIME = "halftime"


# Sixteen slots, one bar. Always exactly SIXTEENTHS_PER_BAR long — `parse_grid` is the
# only supported way to build one, and it refuses anything else.
Grid = tuple[bool, ...]


def parse_grid(pattern: str) -> Grid:
    """`x..x..x...x..x..` -> attacks.

    Raises `ValueError` on a wrong length or a stray character, naming both. A grid that
    is quietly padded or truncated is a bar that plays something nobody wrote; the DSL's
    whole claim is that the model can see the grid, and a forgiving parser would make
    that claim untestable.
    """
    if len(pattern) != SIXTEENTHS_PER_BAR:
        raise ValueError(
            f"a grid is {SIXTEENTHS_PER_BAR} characters, got {len(pattern)}: {pattern!r}"
        )
    stray = sorted(set(pattern) - {ATTACK, REST})
    if stray:
        raise ValueError(f"a grid holds only {ATTACK!r} and {REST!r}, got {stray} in {pattern!r}")
    return tuple(character == ATTACK for character in pattern)


def render_grid(grid: Grid) -> str:
    """The inverse of `parse_grid`, exactly `SIXTEENTHS_PER_BAR` characters."""
    if len(grid) != SIXTEENTHS_PER_BAR:
        raise ValueError(f"a grid is {SIXTEENTHS_PER_BAR} slots, got {len(grid)}")
    return "".join(ATTACK if slot else REST for slot in grid)


def parse_positions(pattern: str) -> Grid:
    """`1,4,7,11,14` -> the same attacks `x..x..x...x..x..` describes.

    The second accepted spelling of a bar, and the reason is measured. After the alias and
    the deadline floor closed every other defect, **the entire remaining gap between the
    conformance rate and its target was a grid counted wrong by one character** — 15 or 17
    where 16 is required (`phase-3-findings.md` §15). No prompt moved it in four rounds,
    which is unsurprising: counting sixteen characters of `x` and `.` is close to the
    worst thing a tokeniser can be asked to do.

    Positions cannot be miscounted. There is no length to get right, an out-of-range slot
    is *detectable* rather than silently shifting the bar, and a dropped item costs one
    note instead of the whole line.

    **1-indexed, like `ghost=` and `acc=` already are.** Slot 1 is the downbeat. Two
    position conventions in one DSL would be a trap, and the wire convention was fixed
    before this notation existed.

    Out of order and repeated are both accepted and normalised: `7,1,1,4` and `1,4,7` name
    the same bar and neither is ambiguous. An empty value is refused rather than read as
    silence — a voice nobody wants is a voice left out, and `""` is as likely to be a
    dropped field as an intended rest.
    """
    if not pattern.strip():
        raise ValueError("a position list is empty; leave the voice out to mean silence")
    slots: set[int] = set()
    for item in pattern.split(","):
        text = item.strip()
        if not text.isdigit():
            raise ValueError(f"{text!r} is not a position, in {pattern!r}")
        position = int(text)
        if not 1 <= position <= SIXTEENTHS_PER_BAR:
            raise ValueError(
                f"position {position} is outside 1..{SIXTEENTHS_PER_BAR}, in {pattern!r}"
            )
        slots.add(position - 1)
    return tuple(slot in slots for slot in range(SIXTEENTHS_PER_BAR))


def render_positions(grid: Grid) -> str:
    """The inverse of `parse_positions`. `-` for a bar with nothing in it."""
    if len(grid) != SIXTEENTHS_PER_BAR:
        raise ValueError(f"a grid is {SIXTEENTHS_PER_BAR} slots, got {len(grid)}")
    attacks = [str(slot + 1) for slot, hit in enumerate(grid) if hit]
    return ",".join(attacks) if attacks else "-"


def beats_of(index: int, feel: Feel) -> float:
    """Where sixteenth `index` falls, in beats from the start of bar 0.

    Indices past the end of a bar continue into the next one, so a caller walking a
    section does not have to keep a bar counter of its own.

    Under `SHUFFLE` the beat is warped piecewise-linearly: the halfway point moves to
    `SWING_POINT` and everything is stretched or squeezed to follow. Three properties
    make that the right warp rather than a nudge — downbeats never move, the order of
    slots never changes, and the two sixteenths inside each swung half stay evenly
    spread inside it. A shuffle that could reorder two slots would not be a feel, it
    would be a wrong note.
    """
    if index < 0:
        raise ValueError(f"a grid index is not negative, got {index}")

    bar, slot = divmod(index, SIXTEENTHS_PER_BAR)
    beat, sub = divmod(slot, SIXTEENTHS_PER_BEAT)
    within_beat = sub / SIXTEENTHS_PER_BEAT

    if feel is Feel.SHUFFLE:
        within_beat = _swung(within_beat)

    return bar * BEATS_PER_BAR + beat + within_beat


def _swung(within_beat: float) -> float:
    """Map a straight position inside one beat onto the 2:1 triplet division.

    `0 -> 0`, `1/2 -> SWING_POINT`, `1 -> 1`, linear in between. The first half of the
    beat is stretched, the second squeezed, and the endpoints are fixed — which is why
    a downbeat under shuffle is still a downbeat.
    """
    if within_beat <= 0.5:
        return within_beat * (SWING_POINT / 0.5)
    return SWING_POINT + (within_beat - 0.5) * ((1.0 - SWING_POINT) / 0.5)
