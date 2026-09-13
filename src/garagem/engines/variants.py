"""What a bar cue plays instead of the groove: a stop in every bar, or a fill in every bar.

ADR-022. A bar cue may cost a fire and never a write, so what it switches to must be written
ahead. A person can strike the pad in any bar, so a variant is the whole section with
**every** bar turned into that cue. Fired with legato, each track picks the variant up at the
bar the person asked for, plays one bar of it, and goes back to the groove at the same
position.

- `stop_bars` — in every bar the band hits the downbeat and cuts. The chord rings for
  `STOP_RING_BEATS`; the drums hit kick and crash, and the drummer picks up on the last beat.
  Every part changes, so every track is fired.
- `fill_bars` — in every bar the drummer fills. The kick keeps the groove, the snare plays a
  fill at least `FILL_CUE_TENSION` strong, the hats drop out. Only the drums change, and
  only the drums track is fired.

**Built from the section as it was written, ending included**, so the bar a person stops in
carries that bar's chord and that bar's kick. The same rules as `transitions`: no pitch is
invented, no kick is added, and a downbeat is never removed — which keeps a root under a
chord change, and kick spacing, true by construction.

**A fill cue is never a whisper.** The section's own fill follows its tension, and a quiet
verse's is one snare hit on beat four. A person who strikes "fill" is asking for one, so the
cue's fill is at least as strong as a chorus-level one. That floor is a musical choice, made
here so it can be argued with by ear.

**Three ways to fill, because the first one was not clear enough.** Stage 4's gate approved
the stop and the drop and heard the fill as *"não tão clara"* (`phase-4-findings.md` §10).
`FillStyle` keeps the approved `SNARE` fill and adds two candidates for a blind audition:

- `RISING` — the snare comes in on beat two and runs into sixteenths, getting louder.
- `TOMS` — a run down four toms over the second half of the bar.

Both leave the kick only on the downbeat, so the fill has the bar to itself. `land_bars` is
the third idea — a crash on the bar the groove returns in — and it is a variant of its own,
because the fill's bar cannot hold the next bar's downbeat.

The audition chose `TOMS` (§10): the fill cue uses it, and `fill_bars` keeps `SNARE` as its
default because that is still what the section's own ending approval covered.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from random import Random
from typing import Final

from garagem.domain import (
    BEATS_PER_BAR,
    SIXTEENTHS_PER_BAR,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
    beats_of,
)
from garagem.engines.groove import fill_for
from garagem.engines.humanise import humanise, separate
from garagem.engines.transitions import (
    HIT_VOICES,
    LAST_BEAT_SLOT,
    ROLL_OFFBEAT_DROP,
    STOP_RING_BEATS,
    drum_hit,
    reference_velocity,
    slot_of,
)
from garagem.theory.percussion import CRASH, HATS, KICK, SNARE, TOMS
from garagem.theory.validator import grid_slots

# The weakest fill a person gets for striking "fill": FILLS[3], eighths into sixteenths.
FILL_CUE_TENSION: Final = 0.6

# Added hits are humanised from the section's seed, offset so a variant's push and pull are
# not the same numbers the section's own notes were given.
VARIANT_SEED_OFFSET: Final = 7_919


class FillStyle(StrEnum):
    """How the drummer fills a bar when "fill" is struck."""

    # The approved one: the section's fill, at least chorus-strong, over beats three and four.
    SNARE = "snare"
    # From beat two, eighths into sixteenths, from soft to loud.
    RISING = "rising"
    # Down the kit over beats three and four: high, mid, low and floor tom, two hits each.
    TOMS = "toms"


# RISING: the slots it strikes, and how soft it starts and how loud it ends against the
# snare this drummer already plays.
RISING_SLOTS: Final[tuple[int, ...]] = (4, 6, 8, 9, 10, 11, 12, 13, 14, 15)
RISING_FROM: Final = 0.6
RISING_TO: Final = 1.1

# TOMS: a snare on beat two to announce it, then two sixteenths on each tom, going down.
TOM_RUN: Final[tuple[tuple[int, int], ...]] = (
    (4, SNARE),
    (6, SNARE),
    *((8 + 2 * step + offset, tom) for step, tom in enumerate(TOMS) for offset in (0, 1)),
)


def stop_bars(score: SectionScore) -> SectionScore:
    """`score` with every bar a stop: the downbeat, a ringing chord, a pickup on beat four."""
    section = score.section
    slots = grid_slots(section)
    rng = Random(score.seed + VARIANT_SEED_OFFSET)
    parts = tuple(
        part.model_copy(update={"notes": separate(_stopped(part, section, slots, rng))})
        for part in score.parts
    )
    return score.model_copy(update={"parts": parts})


def fill_bars(score: SectionScore, style: FillStyle = FillStyle.SNARE) -> SectionScore:
    """`score` with the drummer filling every bar. Every other part is left as it was."""
    section = score.section
    slots = grid_slots(section)
    rng = Random(score.seed + VARIANT_SEED_OFFSET)
    fill = {FillStyle.SNARE: _filled, FillStyle.RISING: _rising, FillStyle.TOMS: _toms}[style]
    return _drums_only(score, lambda part: fill(part, section, slots, rng))


def land_bars(score: SectionScore) -> SectionScore:
    """`score` with a crash on the downbeat of every bar: the groove, landed on.

    What a fill resolves into. Only the drums change.
    """
    section = score.section
    slots = grid_slots(section)
    rng = Random(score.seed + VARIANT_SEED_OFFSET)

    def landed(part: Part) -> list[Note]:
        crashed = {
            slot_of(slots, note) // SIXTEENTHS_PER_BAR
            for note in part.notes
            if note.pitch == CRASH and slot_of(slots, note) % SIXTEENTHS_PER_BAR == 0
        }
        velocity = reference_velocity(part, CRASH)
        added = [
            drum_hit(CRASH, bar * BEATS_PER_BAR, velocity)
            for bar in range(section.bars)
            if bar not in crashed
        ]
        return list(part.notes) + list(humanise(added, rng, feel=section.feel))

    return _drums_only(score, landed)


def _drums_only(score: SectionScore, change: Callable[[Part], list[Note]]) -> SectionScore:
    parts = tuple(
        part.model_copy(update={"notes": separate(change(part))})
        if part.instrument is Instrument.DRUMS
        else part
        for part in score.parts
    )
    return score.model_copy(update={"parts": parts})


def _stopped(part: Part, section: Section, slots: tuple[float, ...], rng: Random) -> list[Note]:
    downbeats = [note for note in part.notes if slot_of(slots, note) % SIXTEENTHS_PER_BAR == 0]
    if part.instrument is not Instrument.DRUMS:
        return [note.model_copy(update={"duration_beats": STOP_RING_BEATS}) for note in downbeats]

    hits = [note for note in downbeats if note.pitch in HIT_VOICES]
    crashed = {slot_of(slots, note) // SIXTEENTHS_PER_BAR for note in hits if note.pitch == CRASH}
    crash_velocity = reference_velocity(part, CRASH)
    snare_velocity = reference_velocity(part, SNARE)
    pickup = fill_for(section.tension)
    added: list[Note] = []
    for bar in range(section.bars):
        if bar not in crashed:
            added.append(drum_hit(CRASH, bar * BEATS_PER_BAR, crash_velocity))
        added.extend(
            drum_hit(SNARE, beats_of(bar * SIXTEENTHS_PER_BAR + slot, section.feel), snare_velocity)
            for slot in range(LAST_BEAT_SLOT, SIXTEENTHS_PER_BAR)
            if pickup[slot]
        )
    return hits + list(humanise(added, rng, feel=section.feel))


def _filled(part: Part, section: Section, slots: tuple[float, ...], rng: Random) -> list[Note]:
    kept = [note for note in part.notes if note.pitch != SNARE and note.pitch not in HATS]
    fill = fill_for(max(section.tension, FILL_CUE_TENSION))
    velocity = reference_velocity(part, SNARE)
    added = [
        drum_hit(
            SNARE,
            beats_of(bar * SIXTEENTHS_PER_BAR + slot, section.feel),
            max(1, velocity - (0 if slot % 4 == 0 else ROLL_OFFBEAT_DROP)),
        )
        for bar in range(section.bars)
        for slot, attack in enumerate(fill)
        if attack
    ]
    return kept + list(humanise(added, rng, feel=section.feel))


def _downbeat_kicks_and_crashes(part: Part, slots: tuple[float, ...]) -> list[Note]:
    """What a styled fill keeps of the groove: the kick and crash on each downbeat."""
    return [
        note
        for note in part.notes
        if note.pitch in (KICK, CRASH) and slot_of(slots, note) % SIXTEENTHS_PER_BAR == 0
    ]


def _rising(part: Part, section: Section, slots: tuple[float, ...], rng: Random) -> list[Note]:
    reference = reference_velocity(part, SNARE)
    added = [
        drum_hit(
            SNARE,
            beats_of(bar * SIXTEENTHS_PER_BAR + slot, section.feel),
            _rising_velocity(reference, slot),
        )
        for bar in range(section.bars)
        for slot in RISING_SLOTS
    ]
    return _downbeat_kicks_and_crashes(part, slots) + list(humanise(added, rng, feel=section.feel))


def _rising_velocity(reference: int, slot: int) -> int:
    """From `RISING_FROM` of the drummer's snare at the first stroke to `RISING_TO` at the last."""
    progress = (slot - RISING_SLOTS[0]) / (RISING_SLOTS[-1] - RISING_SLOTS[0])
    factor = RISING_FROM + (RISING_TO - RISING_FROM) * progress
    return max(1, min(127, round(reference * factor)))


def _toms(part: Part, section: Section, slots: tuple[float, ...], rng: Random) -> list[Note]:
    velocity = reference_velocity(part, SNARE)
    added = [
        drum_hit(pitch, beats_of(bar * SIXTEENTHS_PER_BAR + slot, section.feel), velocity)
        for bar in range(section.bars)
        for slot, pitch in TOM_RUN
    ]
    return _downbeat_kicks_and_crashes(part, slots) + list(humanise(added, rng, feel=section.feel))
