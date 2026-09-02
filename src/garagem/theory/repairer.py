"""Making an invalid score legal, deterministically, without losing music.

The DSL skill is explicit: invalid output is repaired, and if it cannot be repaired it
falls back to the deterministic engine and the event is logged — **a bar is never
discarded**. This module holds the first half of that sentence. So every repair here
moves, retunes or quietens a note; none deletes one, and the note count is asserted
never to fall.

**No randomness at all, not even seeded.** A repair is a correction: two identical
inputs must give one output, or the golden tests compare bytes that move on their own.
That is also why every fix reuses a `theory/` primitive — `fit_to_range`, `nearest_in`,
`degree_to_pitch` — instead of reinventing the arithmetic with its own tie-breaking.

**Order matters and is fixed.** Grid first (a note in the wrong place is a note in the
wrong bar), then the drum rules, then dissonance, then the bass root, and range last —
because moving a note into the scale can move it out of the instrument's reach, and
whatever else happens the part must end up playable.
"""

from __future__ import annotations

from garagem.domain import (
    BEATS_PER_BAR,
    PITCH_CLASSES,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
)
from garagem.theory.percussion import GHOST_VELOCITY, HATS, KICK, MIN_KICK_INTERVAL_MS
from garagem.theory.scales import nearest_in, pitch_classes
from garagem.theory.validator import (
    DISSONANCE_FLOOR,
    DISSONANCE_RANGE,
    GRID_TOLERANCE_BEATS,
    ROOT_WINDOW_BEATS,
    ROOTLESS_TENSION,
    Violation,
    grid_slots,
    nearest_slot,
    validate,
)
from garagem.theory.voicings import RANGES


def repair(score: SectionScore) -> tuple[SectionScore, tuple[Violation, ...]]:
    """Fix what is fixable, deterministically. Return the score and what is left.

    The surviving violations are the caller's decision point: anything still here after
    a repair pass is what makes the whole section fall back to the deterministic engine,
    with the rule name in the event log.
    """
    parts = tuple(_repair_part(part, score.section) for part in score.parts)
    repaired = score.model_copy(update={"parts": parts})
    return repaired, validate(repaired)


def _repair_part(part: Part, section: Section) -> Part:
    notes = list(part.notes)
    notes = _snap_to_grid(notes, section)
    if part.instrument is Instrument.DRUMS:
        notes = _resolve_hats(notes)
        notes = _ghost_crowded_kicks(notes, section)
    else:
        notes = _pull_into_key(notes, section)
        if part.instrument is Instrument.BASS:
            notes = _root_on_every_change(notes, section)
        notes = _pull_into_range(notes, part.instrument)
    return part.model_copy(update={"notes": tuple(notes)})


# ----------------------------------------------------------------------------------- grid


def _snap_to_grid(notes: list[Note], section: Section) -> list[Note]:
    """A note off the grid goes to the nearest slot. Its length is left alone."""
    slots = grid_slots(section)
    snapped = []
    for note in notes:
        nearest = nearest_slot(slots, note.start_beats)
        if abs(nearest - note.start_beats) > GRID_TOLERANCE_BEATS:
            note = note.model_copy(update={"start_beats": nearest})
        snapped.append(note)
    return snapped


# ----------------------------------------------------------------------------------- drums


def _resolve_hats(notes: list[Note]) -> list[Note]:
    """Keep the hat that got there first; the other becomes the same hat.

    Retuned rather than removed. Two identical hats in one slot sound like one hat,
    which is what "keep the closed one" means in practice, and nothing is deleted.
    """
    held: dict[float, int] = {}
    resolved = []
    for note in notes:
        if note.pitch in HATS:
            at = round(note.start_beats, 3)
            if at in held and held[at] != note.pitch:
                note = note.model_copy(update={"pitch": held[at]})
            held.setdefault(at, note.pitch)
        resolved.append(note)
    return resolved


def _ghost_crowded_kicks(notes: list[Note], section: Section) -> list[Note]:
    """The second of two kicks too close together becomes a ghost stroke.

    A heel-toe ghost is how a drummer actually plays a double faster than the beater
    returns, so this is the repair a player would make — not a way of hiding the note.
    """
    ms_per_beat = 60_000.0 / section.bpm
    order = sorted(
        (index for index, note in enumerate(notes) if note.pitch == KICK),
        key=lambda index: (notes[index].start_beats, index),
    )
    ghosted = list(notes)
    previous: float | None = None
    for index in order:
        note = ghosted[index]
        if note.velocity < GHOST_VELOCITY:
            continue
        if (
            previous is not None
            and (note.start_beats - previous) * ms_per_beat < MIN_KICK_INTERVAL_MS
        ):
            ghosted[index] = note.model_copy(update={"velocity": GHOST_VELOCITY - 1})
            continue
        previous = note.start_beats
    return ghosted


# -------------------------------------------------------------------------------- pitched


def _pull_into_key(notes: list[Note], section: Section) -> list[Note]:
    """Only when the part is over its dissonance budget, and then all the way.

    A part under budget is left untouched: the floor exists so that a passing tone
    survives repair, and a repairer that flattened every chromatic note would make the
    budget pointless.
    """
    if not notes:
        return notes
    allowed = pitch_classes(section.key, section.scale) | frozenset().union(
        *(chord.pitch_classes() for chord in section.chart.chords)
    )
    outside = [
        index for index, note in enumerate(notes) if note.pitch % PITCH_CLASSES not in allowed
    ]
    budget = DISSONANCE_FLOOR + DISSONANCE_RANGE * section.tension
    if len(outside) / len(notes) <= budget:
        return notes

    pulled = list(notes)
    for index in outside:
        note = pulled[index]
        pulled[index] = note.model_copy(update={"pitch": nearest_in(note.pitch, allowed)})
    return pulled


def _root_on_every_change(notes: list[Note], section: Section) -> list[Note]:
    """Put a root under every chord change: retune the nearest note, or add one.

    Adding is a repair too. The alternative — leaving the change unsupported — is the
    thing the rule exists to stop, and a bass line with one extra root note is closer to
    the briefing than one that skips the change.
    """
    if section.tension > ROOTLESS_TENSION:
        return notes

    repaired = list(notes)
    for bar in range(section.bars):
        if not section.chart.changes_at(bar):
            continue
        downbeat = bar * BEATS_PER_BAR
        root = section.chart.at(bar).root
        window = [
            index
            for index, note in enumerate(repaired)
            if abs(note.start_beats - downbeat) <= ROOT_WINDOW_BEATS
        ]
        if any(repaired[index].pitch % PITCH_CLASSES == root for index in window):
            continue
        if window:
            index = min(window, key=lambda i: (abs(repaired[i].start_beats - downbeat), i))
            note = repaired[index]
            repaired[index] = note.model_copy(
                update={
                    "pitch": nearest_in(note.pitch, frozenset({root})),
                    "start_beats": downbeat,
                }
            )
        else:
            repaired.append(
                Note(
                    pitch=nearest_in(_centre(repaired, Instrument.BASS), frozenset({root})),
                    start_beats=downbeat,
                    duration_beats=0.5,
                )
            )
    return repaired


def _centre(notes: list[Note], instrument: Instrument) -> int:
    """Where to put an added note: near what the part is already doing."""
    low, high = RANGES[instrument]
    if not notes:
        return (low + high) // 2
    return sorted(note.pitch for note in notes)[len(notes) // 2]


def _pull_into_range(notes: list[Note], instrument: Instrument) -> list[Note]:
    """Octave-shift each out-of-range note until it fits. Never clipped, never dropped."""
    limits = RANGES.get(instrument)
    if limits is None:
        return notes
    low, high = limits
    fitted = []
    for note in notes:
        pitch = note.pitch
        while pitch < low:
            pitch += PITCH_CLASSES
        while pitch > high:
            pitch -= PITCH_CLASSES
        fitted.append(note if pitch == note.pitch else note.model_copy(update={"pitch": pitch}))
    return fitted
