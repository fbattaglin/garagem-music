"""P4, layer two: the deterministic musical validator.

Layer one is the schema — pydantic refuses a velocity of 0 and a pitch of 200. This is
what refuses music that is well-formed and wrong: a bass below its lowest string, a
chord change with no root under it, two hi-hats in one slot, a kick a human foot could
not play.

**Every rule returns violations rather than raising.** The repairer needs to see all of
them at once, and a validator that stopped at the first would make repair an iterative
guess. `validate` is pure, total and repeatable: same score, same tuple, every time.

**Every rule is musical, not arbitrary.** The comment above each one says which fact
about an instrument or a player it encodes. A rule nobody can justify is a rule that
gets relaxed the first time it is inconvenient, and then P4 is decoration.

The invariants themselves are not invented here — they are written down in
`.claude/skills/garagem-dsl` under "Invariants the validator enforces", and this module
implements exactly those and no more. `RULES` names them, and a test asserts every name
in it is produced by some case, which is what stops a rule from being declared and never
written.
"""

from __future__ import annotations

from bisect import bisect_left
from itertools import pairwise
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from garagem.domain import (
    BEATS_PER_BAR,
    PITCH_CLASSES,
    SIXTEENTHS_PER_BEAT,
    Chart,
    Instrument,
    Part,
    Section,
    SectionScore,
    beats_of,
)
from garagem.theory.percussion import GHOST_VELOCITY, HATS, KICK, MIN_KICK_INTERVAL_MS
from garagem.theory.scales import pitch_classes
from garagem.theory.voicings import RANGES

FROZEN = ConfigDict(frozen=True, extra="forbid")

# What `validate` itself can produce. Other layers add their own names — `dsl/lines.py`
# raises `section_mismatch` — and the event log counts the union. Keeping this tuple to
# what this module produces is what lets `test_every_declared_rule_is_actually_implemented`
# stay a real check rather than a list somebody maintains by hand.
RULES: Final[tuple[str, ...]] = (
    "range",
    "bass_root_on_chord_change",
    "hihat_conflict",
    "kick_spacing",
    "dissonance_budget",
    "grid_alignment",
)

# Above this, the section has licence to leave the root out from under a chord change:
# the DSL states the exemption, and it is what lets a bridge float.
ROOTLESS_TENSION: Final = 0.7

# How much of a part may sit outside the section's scale. A little is a passing tone; a
# lot is a different key. The floor exists because chromatic approach notes are normal
# even at tension 0, and the ceiling is what stops a "creative" model writing atonal rock.
DISSONANCE_FLOOR: Final = 0.05
DISSONANCE_RANGE: Final = 0.45

# Humanisation moves notes by up to 0.02 beats on purpose (`engines/humanise.py`), so the
# grid rule has to tolerate at least that much or it would flag its own system's output.
GRID_TOLERANCE_BEATS: Final = 0.03

# How near a chord's downbeat a root has to land to count as being on it. One sixteenth:
# a bass that arrives later than that is not playing the change, it is playing after it.
ROOT_WINDOW_BEATS: Final = 0.25


class Violation(BaseModel):
    """One broken rule, with enough detail for the repairer and for the event log."""

    model_config = FROZEN

    rule: str
    instrument: Instrument
    detail: str
    # Which note, when the rule is about one. `None` for rules about a whole part.
    note_index: int | None = None
    bar: int | None = Field(default=None, ge=0)
    repairable: bool = True


def validate(score: SectionScore) -> tuple[Violation, ...]:
    """Every rule this score breaks, in `RULES` order. Pure and repeatable."""
    violations: list[Violation] = []
    for part in _in_rule_order(score):
        violations.extend(_range(part, score.section))
    for part in _in_rule_order(score):
        violations.extend(_bass_root_on_chord_change(part, score.section))
    for part in _in_rule_order(score):
        violations.extend(_hihat_conflict(part))
    for part in _in_rule_order(score):
        violations.extend(_kick_spacing(part, score.section))
    for part in _in_rule_order(score):
        violations.extend(_dissonance_budget(part, score.section))
    for part in _in_rule_order(score):
        violations.extend(_grid_alignment(part, score.section))
    return tuple(violations)


def _in_rule_order(score: SectionScore) -> tuple[Part, ...]:
    """Parts in the DSL's emission order, so the violation list is stable."""
    order = list(Instrument)
    return tuple(sorted(score.parts, key=lambda part: order.index(part.instrument)))


# ---------------------------------------------------------------------------------- range


def _range(part: Part, section: Section) -> list[Violation]:
    """An instrument cannot play below its lowest string or above its top fret.

    Drums are exempt: their "pitch" is a map entry, not a register (`percussion.py`).
    """
    limits = RANGES.get(part.instrument)
    if limits is None:
        return []
    low, high = limits
    return [
        Violation(
            rule="range",
            instrument=part.instrument,
            detail=f"pitch {note.pitch} is outside {low}-{high}",
            note_index=index,
            bar=_bar_of(note.start_beats),
            repairable=True,
        )
        for index, note in enumerate(part.notes)
        if not low <= note.pitch <= high
    ]


# ------------------------------------------------------------- bass root on chord change


def _bass_root_on_chord_change(part: Part, section: Section) -> list[Violation]:
    """A chord change with no root under it does not sound like that chord.

    The exemption above `ROOTLESS_TENSION` is the DSL's own: at high tension the bass is
    allowed to sit on a third or a fifth and let the harmony float.
    """
    if part.instrument is not Instrument.BASS or section.tension > ROOTLESS_TENSION:
        return []

    violations: list[Violation] = []
    for bar in range(section.bars):
        if not section.chart.changes_at(bar):
            continue
        downbeat = bar * BEATS_PER_BAR
        root = section.chart.at(bar).root
        landed = any(
            note.pitch % PITCH_CLASSES == root
            and abs(note.start_beats - downbeat) <= ROOT_WINDOW_BEATS
            for note in part.notes
        )
        if not landed:
            violations.append(
                Violation(
                    rule="bass_root_on_chord_change",
                    instrument=part.instrument,
                    detail=f"no root under the chord change in bar {bar + 1}",
                    bar=bar,
                    repairable=True,
                )
            )
    return violations


# ------------------------------------------------------------------------- hihat conflict


def _hihat_conflict(part: Part) -> list[Violation]:
    """One pedal, one hi-hat: open and closed in the same slot cannot happen."""
    if part.instrument is not Instrument.DRUMS:
        return []

    seen: dict[float, int] = {}
    violations: list[Violation] = []
    for index, note in enumerate(part.notes):
        if note.pitch not in HATS:
            continue
        at = round(note.start_beats, 3)
        if at in seen and seen[at] != note.pitch:
            violations.append(
                Violation(
                    rule="hihat_conflict",
                    instrument=part.instrument,
                    detail=f"hats {seen[at]} and {note.pitch} both at beat {at}",
                    note_index=index,
                    bar=_bar_of(note.start_beats),
                    repairable=True,
                )
            )
        seen.setdefault(at, note.pitch)
    return violations


# ---------------------------------------------------------------------------- kick spacing


def _kick_spacing(part: Part, section: Section) -> list[Violation]:
    """A beater and a spring cannot return faster than `MIN_KICK_INTERVAL_MS`.

    In milliseconds, not sixteenths, which is the whole point: the same pattern is
    playable at 132 BPM and not at 240. The DSL's `double_kick=on` exemption has no
    field on `Section` to hang from, so it is not implemented rather than half-honoured.

    Ghost strokes do not count: below `GHOST_VELOCITY` the beater never returns to full
    extension, which is what makes fast doubles physically possible in the first place.
    """
    if part.instrument is not Instrument.DRUMS:
        return []

    ms_per_beat = 60_000.0 / section.bpm
    kicks = sorted(
        (note.start_beats, index)
        for index, note in enumerate(part.notes)
        if note.pitch == KICK and note.velocity >= GHOST_VELOCITY
    )
    violations: list[Violation] = []
    for (earlier, _), (later, index) in pairwise(kicks):
        gap_ms = (later - earlier) * ms_per_beat
        if gap_ms < MIN_KICK_INTERVAL_MS:
            violations.append(
                Violation(
                    rule="kick_spacing",
                    instrument=part.instrument,
                    detail=f"{gap_ms:.0f} ms between kicks, under {MIN_KICK_INTERVAL_MS:.0f}",
                    note_index=index,
                    bar=_bar_of(later),
                    repairable=True,
                )
            )
    return violations


# ------------------------------------------------------------------------ dissonance budget


def _dissonance_budget(part: Part, section: Section) -> list[Violation]:
    """Notes outside the key, as a fraction of the part. Tension buys more of them."""
    if part.instrument is Instrument.DRUMS or not part.notes:
        return []

    allowed = pitch_classes(section.key, section.scale) | chart_pitch_classes(section.chart)
    outside = sum(1 for note in part.notes if note.pitch % PITCH_CLASSES not in allowed)
    budget = DISSONANCE_FLOOR + DISSONANCE_RANGE * section.tension
    share = outside / len(part.notes)
    if share <= budget:
        return []
    return [
        Violation(
            rule="dissonance_budget",
            instrument=part.instrument,
            detail=f"{share:.0%} of notes outside the key, budget is {budget:.0%}",
            repairable=True,
        )
    ]


def chart_pitch_classes(chart: Chart) -> frozenset[int]:
    """Chord tones count as consonant even when the scale does not contain them.

    A B7 in E minor has a D#, which natural minor does not: that is a borrowed dominant,
    not a mistake, and a budget that flagged it would push every engine towards blandness.
    """
    return frozenset().union(*(chord.pitch_classes() for chord in chart.chords))


# ------------------------------------------------------------------------- grid alignment


def _grid_alignment(part: Part, section: Section) -> list[Violation]:
    """Every attack belongs to a slot of the section's grid, give or take humanisation.

    The tolerance is deliberately just above `humanise`'s maximum push. A note further
    off than that did not get there by feel.
    """
    slots = grid_slots(section)
    violations: list[Violation] = []
    for index, note in enumerate(part.notes):
        drift = abs(nearest_slot(slots, note.start_beats) - note.start_beats)
        if drift > GRID_TOLERANCE_BEATS:
            violations.append(
                Violation(
                    rule="grid_alignment",
                    instrument=part.instrument,
                    detail=f"beat {note.start_beats:.3f} is {drift:.3f} off the grid",
                    note_index=index,
                    bar=_bar_of(note.start_beats),
                    repairable=True,
                )
            )
    return violations


def grid_slots(section: Section) -> tuple[float, ...]:
    """Every legal attack position in the section, ascending.

    Public because the repairer snaps to exactly these, and two definitions of "the grid"
    would be one too many.
    """
    count = section.bars * int(BEATS_PER_BAR) * SIXTEENTHS_PER_BEAT
    return tuple(beats_of(index, section.feel) for index in range(count))


def nearest_slot(slots: tuple[float, ...], at: float) -> float:
    """The closest slot to `at`. Binary search: this runs once per note, per rule.

    A linear scan is the obvious version and was the first one; over a three-minute run
    it is tens of millions of comparisons, and the property tests in `tests/property/`
    generate sections by the thousand.
    """
    index = bisect_left(slots, at)
    if index == 0:
        return slots[0]
    if index == len(slots):
        return slots[-1]
    below, above = slots[index - 1], slots[index]
    return below if at - below <= above - at else above


def _bar_of(start_beats: float) -> int:
    return max(0, int(start_beats // BEATS_PER_BAR))
