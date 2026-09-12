"""How one section hands over to the next: a fill, a build, a stop, or the last chord.

ADR-000 §7 asks Phase 4 for *"a dynamics curve and transitions between sections (fills,
breaks, builds)"*. ADR-017 made that composition rather than generation; ADR-020 says why
it lives here, over a finished score, rather than inside the generators.

**Four endings, and the first is what the band already plays.**

- `FILL` — the last bar is `fill_for(tension)` on the snare. The engines and the realiser
  both do this already and it was approved by ear in Phase 2, so here it is the identity.
- `BUILD` — into a bigger section. The snare rolls over the last bars, quarters to eighths
  to sixteenths, with the hats out; the whole band dips and swells; and everyone but the
  drummer lets go of the final beat, so the roll is alone before the crash.
- `STOP` — the band hits the downbeat of the last bar together and cuts. The drummer alone
  picks up into the next section on the last beat.
- `FINAL` — the song ends: one hit on the downbeat of the last bar, left to ring.

**It takes notes away, moves velocities, lengthens a hit, and adds drums. It never invents
a pitch.** Which chord rings at a stop is the groove's, and the chart is the briefing's. That
is what lets one composition sit over a model's section and over the floor without becoming
a third source of harmony, and it keeps most validator rules true by construction: no pitch
moves, so nothing leaves its range; no kick is added, so no beater is asked to return
faster than it can; a note on a downbeat is never removed, so a root under a chord change
stays under it.

**What is not true by construction is checked by whoever applies it.** Removing notes can
raise a part's share of chromatic notes, and a model's section is only as valid as its
repair left it. The scheduler validates what this returns, and plays the section as it was
generated if composing it broke a rule.

Pure and seeded like every engine: added drum hits are humanised from the score's own seed.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from enum import StrEnum
from random import Random
from typing import Final

from garagem.domain import (
    BEATS_PER_BAR,
    SIXTEENTHS_PER_BAR,
    Grid,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
    beats_of,
    parse_grid,
)
from garagem.engines.arranger import BRIDGE, CHORUS, VERSE
from garagem.engines.groove import fill_for
from garagem.engines.humanise import MIN_DURATION_BEATS, RELEASE_BEATS, humanise, separate
from garagem.theory.percussion import CRASH, GHOST_VELOCITY, HATS, KICK, SNARE
from garagem.theory.validator import grid_slots


class Ending(StrEnum):
    """How a section hands over to the one after it."""

    FILL = "fill"
    BUILD = "build"
    STOP = "stop"
    FINAL = "final"


# Where two kinds of section meet. Anything not listed ends on a fill. Data rather than
# logic, like `arranger.TRANSITIONS`, so it can be argued with by ear.
ENDINGS: Final[dict[tuple[str, str], Ending]] = {
    # The move a rock chorus is announced with.
    (VERSE, CHORUS): Ending.BUILD,
    # A bridge exists to set up a chorus, and a stop is the bluntest way to say it is here.
    (BRIDGE, CHORUS): Ending.STOP,
}

# Two bars of an eight-bar section swell, and one of anything shorter: a two-bar build in a
# four-bar intro would be half of it.
LONG_BUILD_BARS: Final = 2
LONG_BUILD_MIN_BARS: Final = 8

# The snare roll, last bar last. A one-bar build plays only the last row.
ROLL: Final[tuple[Grid, ...]] = (
    parse_grid("x...x...x.x.x.x."),
    parse_grid("x.x.x.x.xxxxxxxx"),
)
# Off the beat a roll is quieter, which is what makes it a roll and not a buzz.
ROLL_OFFBEAT_DROP: Final = 12

# The build starts a little under the groove and ends above it. Starting under is what
# makes the rise heard as a rise rather than as a section that got louder.
SWELL_FROM: Final = 0.8
SWELL_TO: Final = 1.15

# A hit left ringing at a stop: long enough to be a chord, short enough to leave a silence
# before the pickup.
STOP_RING_BEATS: Final = 1.5

# The last beat of a bar, in sixteenths. Where a pickup lives and what a build lets go of.
LAST_BEAT_SLOT: Final = 12

# What a stop keeps of the drums on its downbeat. Hats are the groove, not the hit.
HIT_VOICES: Final[frozenset[int]] = frozenset({KICK, SNARE, CRASH})

HIT_BEATS: Final = 0.125
# Only reached by a part with no notes at all, where the velocity is moot.
DEFAULT_VELOCITY: Final = 100
TOP_VELOCITY: Final = 127


def endings_for(form: Sequence[Section]) -> tuple[Ending, ...]:
    """One ending per section of a song, in play order.

    The last section ends the song. **The step into the last chorus is a stop, whatever the
    table says**, when there is more than one chorus: a song that builds into every chorus
    the same way needs the last one to arrive differently, and saving the stop for it is
    part of what makes it the peak. `arranger.with_climax` lifts that same chorus.
    """
    choruses = [index for index, section in enumerate(form) if section.name == CHORUS]
    last_chorus = choruses[-1] if len(choruses) > 1 else None
    endings: list[Ending] = []
    for index, section in enumerate(form):
        if index == len(form) - 1:
            endings.append(Ending.FINAL)
        elif index + 1 == last_chorus:
            endings.append(Ending.STOP)
        else:
            endings.append(ENDINGS.get((section.name, form[index + 1].name), Ending.FILL))
    return tuple(endings)


def compose(score: SectionScore, ending: Ending, *, into: Section | None = None) -> SectionScore:
    """`score` with `ending` composed over its last bars. A fill returns `score` itself.

    `into` is the section that follows, and only a stop's pickup reads it: the drummer picks
    up with the last beat of the fill the *next* section's tension calls for. A one-bar
    section comes back unchanged, for the engines' reason — its last bar is also its first.
    """
    section = score.section
    if ending is Ending.FILL or section.bars < 2:
        return score
    slots = grid_slots(section)
    rng = Random(score.seed)
    parts = tuple(
        part.model_copy(update={"notes": separate(_ended(part, ending, section, into, slots, rng))})
        for part in score.parts
    )
    return score.model_copy(update={"parts": parts})


def _ended(
    part: Part,
    ending: Ending,
    section: Section,
    into: Section | None,
    slots: tuple[float, ...],
    rng: Random,
) -> list[Note]:
    if ending is Ending.BUILD:
        return _build(part, section, slots, rng)
    final = ending is Ending.FINAL
    return _hit(part, section, slots, rng, final=final, into=None if final else into)


# --------------------------------------------------------------------------------- build


def _build(part: Part, section: Section, slots: tuple[float, ...], rng: Random) -> list[Note]:
    bars = LONG_BUILD_BARS if section.bars >= LONG_BUILD_MIN_BARS else 1
    first = section.bars - bars
    start = first * BEATS_PER_BAR
    end = section.total_beats()

    if part.instrument is Instrument.DRUMS:
        kept = [
            note
            for note in part.notes
            if _bar(slots, note) < first or (note.pitch != SNARE and note.pitch not in HATS)
        ]
        notes = kept + list(humanise(_roll(part, section, first), rng, feel=section.feel))
    else:
        notes = _let_go_of_the_last_beat(part, section, slots)
    return [_swelled(note, start, end) for note in notes]


def _roll(part: Part, section: Section, first: int) -> list[Note]:
    velocity = _reference(part, SNARE)
    rows = ROLL[len(ROLL) - (section.bars - first) :]
    return [
        Note(
            pitch=SNARE,
            start_beats=beats_of(bar * SIXTEENTHS_PER_BAR + slot, section.feel),
            duration_beats=HIT_BEATS,
            velocity=max(1, velocity - (0 if slot % 4 == 0 else ROLL_OFFBEAT_DROP)),
        )
        for bar, row in zip(range(first, section.bars), rows, strict=True)
        for slot, attack in enumerate(row)
        if attack
    ]


def _let_go_of_the_last_beat(part: Part, section: Section, slots: tuple[float, ...]) -> list[Note]:
    """Nothing starts on the final beat, and nothing still sounding reaches into it."""
    last_beat = (section.bars - 1) * SIXTEENTHS_PER_BAR + LAST_BEAT_SLOT
    cut = beats_of(last_beat, section.feel) - RELEASE_BEATS
    notes: list[Note] = []
    for note in part.notes:
        if _slot(slots, note) >= last_beat:
            continue
        notes.append(_ending_by(note, cut))
    return notes


def _swelled(note: Note, start: float, end: float) -> Note:
    """Dip, then rise, across the build. Ghost strokes stay ghosts.

    A ghost lifted past `GHOST_VELOCITY` would become a full stroke the kick-spacing rule
    counts, which is the one way a velocity change could make a legal part illegal.
    """
    if note.start_beats < start or note.velocity < GHOST_VELOCITY:
        return note
    progress = min(1.0, (note.start_beats - start) / (end - start))
    factor = SWELL_FROM + (SWELL_TO - SWELL_FROM) * progress
    velocity = min(TOP_VELOCITY, max(1, round(note.velocity * factor)))
    return note.model_copy(update={"velocity": velocity})


# ----------------------------------------------------------------------------- stop, final


def _hit(
    part: Part,
    section: Section,
    slots: tuple[float, ...],
    rng: Random,
    *,
    final: bool,
    into: Section | None,
) -> list[Note]:
    """The downbeat of the last bar, and nothing after it but a pickup if there is one.

    `final` is the song's last chord: every pitched note on the downbeat rings to the end
    of the section. A stop rings for `STOP_RING_BEATS` and leaves a silence, and picks up
    only when there is a section to pick up into.
    """
    last = section.bars - 1
    downbeat_slot = last * SIXTEENTHS_PER_BAR
    downbeat = last * BEATS_PER_BAR
    before = [note for note in part.notes if _slot(slots, note) < downbeat_slot]
    on = [note for note in part.notes if _slot(slots, note) == downbeat_slot]

    if part.instrument is Instrument.DRUMS:
        hit = [note for note in on if note.pitch in HIT_VOICES]
        added: list[Note] = []
        if not any(note.pitch == CRASH for note in hit):
            added.append(_drum(CRASH, downbeat, _reference(part, CRASH)))
        if into is not None:
            pickup = fill_for(into.tension)
            velocity = _reference(part, SNARE)
            added.extend(
                _drum(SNARE, beats_of(downbeat_slot + slot, section.feel), velocity)
                for slot in range(LAST_BEAT_SLOT, SIXTEENTHS_PER_BAR)
                if pickup[slot]
            )
        return before + hit + list(humanise(added, rng, feel=section.feel))

    end = section.total_beats()
    ringing = [
        note.model_copy(
            update={
                "duration_beats": max(
                    MIN_DURATION_BEATS,
                    end - note.start_beats - RELEASE_BEATS if final else STOP_RING_BEATS,
                )
            }
        )
        for note in on
    ]
    return [_ending_by(note, downbeat - RELEASE_BEATS) for note in before] + ringing


# -------------------------------------------------------------------------------- helpers


def _slot(slots: tuple[float, ...], note: Note) -> int:
    """Which sixteenth of the section a note belongs to, humanisation undone."""
    index = bisect_left(slots, note.start_beats)
    if index == 0:
        return 0
    if index == len(slots):
        return len(slots) - 1
    below, above = slots[index - 1], slots[index]
    return index - 1 if note.start_beats - below <= above - note.start_beats else index


def _bar(slots: tuple[float, ...], note: Note) -> int:
    return _slot(slots, note) // SIXTEENTHS_PER_BAR


def _ending_by(note: Note, cut: float) -> Note:
    """`note`, shortened so it has stopped sounding by `cut`. Untouched if it already has."""
    if note.start_beats + note.duration_beats <= cut:
        return note
    return note.model_copy(
        update={"duration_beats": max(MIN_DURATION_BEATS, cut - note.start_beats)}
    )


def _reference(part: Part, pitch: int) -> int:
    """How hard this drummer already hits `pitch`, or anything, in this section."""
    same = [note.velocity for note in part.notes if note.pitch == pitch]
    if same:
        return max(same)
    return max((note.velocity for note in part.notes), default=DEFAULT_VELOCITY)


def _drum(pitch: int, at: float, velocity: int) -> Note:
    return Note(pitch=pitch, start_beats=at, duration_beats=HIT_BEATS, velocity=velocity)
