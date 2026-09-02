"""Seeded, bounded deviation: the difference between a drum machine and a drummer.

Two bounds, and the first one is the interesting one.

**A humanised note never crosses a grid line.** `MAX_TIMING_BEATS` is 0.02 beats — about
9 ms at 132 BPM, felt rather than heard as late. The tightest gap the grid ever has is
under a shuffle, where two slots can sit 1/6 of a beat apart; half of that is 0.083, so
0.02 cannot reach the halfway point to a neighbour. That is not a coincidence to be
grateful for, it is a constraint with a test on it: humanisation that can cross a grid
line is not humanisation, it is a wrong note, and the validator would rightly reject it.

**Every deviation comes from a `Random` passed in.** Never `random.random()`, never a
second generator. The same seed gives byte-identical output, which is invariant 7 and
what the golden tests compare. The call order below is therefore part of the contract:
timing then velocity, note by note, in the order the notes arrive.
"""

from __future__ import annotations

from collections.abc import Iterable
from random import Random
from typing import Final

from garagem.domain import Feel, Note

# About 9 ms at 132 BPM. Below the threshold where a listener hears "late" and above the
# one where they hear nothing at all.
MAX_TIMING_BEATS: Final = 0.02
MAX_VELOCITY: Final = 12

# The gap left between one note and the next attack of the *same pitch*. Small enough to
# be inaudible (~4.5 ms at 132 BPM) and far larger than any rounding this survives: six
# decimal places in `normalised`, and 32-bit floats on the OSC wire.
RELEASE_BEATS: Final = 0.01

# A note shortened by `separate` never becomes silence with a velocity.
MIN_DURATION_BEATS: Final = 0.02

MIN_VELOCITY: Final = 1
TOP_VELOCITY: Final = 127

# A shuffle already pushes the offbeats a long way; pushing them further blurs the feel
# rather than deepening it. Straight sixteenths have the least room of all.
FEEL_AMOUNT: Final[dict[Feel, float]] = {
    Feel.STRAIGHT8: 1.0,
    Feel.STRAIGHT16: 0.6,
    Feel.SHUFFLE: 0.7,
    Feel.HALFTIME: 1.0,
}


def humanise(
    notes: Iterable[Note], rng: Random, *, feel: Feel, amount: float = 1.0
) -> tuple[Note, ...]:
    """Push and pull, seeded. `amount=0.0` is the identity, exactly.

    The identity is exact rather than approximate, and it consumes no randomness: a
    caller that turns humanisation off must get the engine's output back unchanged, and
    must not find the rest of its section altered because the generator moved on.
    """
    if amount == 0.0:
        return tuple(notes)

    scale = amount * FEEL_AMOUNT[feel]
    humanised = []
    for note in notes:
        shift = rng.uniform(-MAX_TIMING_BEATS, MAX_TIMING_BEATS) * scale
        push = round(rng.uniform(-MAX_VELOCITY, MAX_VELOCITY) * scale)
        humanised.append(
            note.model_copy(
                update={
                    # Never before the section starts: a note at beat 0 can only be late.
                    "start_beats": max(0.0, note.start_beats + shift),
                    "velocity": min(TOP_VELOCITY, max(MIN_VELOCITY, note.velocity + push)),
                }
            )
        )
    return tuple(humanised)


def separate(notes: Iterable[Note], *, gap_beats: float = RELEASE_BEATS) -> tuple[Note, ...]:
    """Shorten any note that would run into the next attack of the same pitch.

    Live truncates an overlapping note silently and then reports the shortened one back,
    which fails the adapter's write-then-confirm — a write that "did not take" for a
    reason nobody can see. Found the first time a section was written into a real Set
    (`phase-2-findings.md`): a keyboard pad lasting exactly one bar overlapped the next
    bar's chord as soon as humanisation moved it a few milliseconds earlier.

    It is also the musically right answer. A player lifts their hand before striking the
    same key again; a MIDI part that does not is asking the sampler to retrigger a voice
    that is still sounding, which is a different sound from the one that was written.

    Runs *after* humanising, because humanising is what creates the overlap.
    """
    ordered = sorted(notes, key=lambda note: (note.pitch, note.start_beats))
    separated: list[Note] = []
    for index, note in enumerate(ordered):
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        if following is None or following.pitch != note.pitch:
            separated.append(note)
            continue
        latest_end = following.start_beats - gap_beats
        if note.start_beats + note.duration_beats <= latest_end:
            separated.append(note)
            continue
        duration = max(MIN_DURATION_BEATS, latest_end - note.start_beats)
        separated.append(note.model_copy(update={"duration_beats": duration}))
    return tuple(sorted(separated, key=lambda note: (note.start_beats, note.pitch)))
