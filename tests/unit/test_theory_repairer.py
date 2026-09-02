"""Repair: make it legal, keep the music.

Three properties carry this module and each has its own test. Repair never loses a note.
Repair is idempotent, so running it twice is not a way to get a different answer. And a
clean score comes back untouched, which is what stops the repairer from quietly becoming
a second composer.
"""

from __future__ import annotations

import pytest

from garagem.domain import (
    Feel,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
)
from garagem.theory import (
    GHOST_VELOCITY,
    RANGES,
    parse_chart,
    repair,
    validate,
)
from garagem.theory.percussion import CLOSED_HAT, KICK, OPEN_HAT, SNARE

PROGRESSION = parse_chart("| Em | C | G | D |")
ROOTS = (40, 36, 43, 38)


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 4,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": PROGRESSION,
    }
    return Section.model_validate(base | extra)


def bass_part(pitches: tuple[int, ...] = ROOTS) -> Part:
    notes = [
        Note(pitch=pitch, start_beats=bar * 4 + eighth * 0.5, duration_beats=0.45)
        for bar, pitch in enumerate(pitches)
        for eighth in range(8)
    ]
    return Part(instrument=Instrument.BASS, notes=tuple(notes))


def a_score(*parts: Part, **section: object) -> SectionScore:
    return SectionScore(section=a_section(**section), parts=parts, seed=7)


def note_count(score: SectionScore) -> int:
    return sum(len(part.notes) for part in score.parts)


# ------------------------------------------------------------------------- the clean case


def test_repairing_a_clean_score_changes_nothing() -> None:
    """Not just equal — unchanged. A repairer that rewrites clean music is a composer."""
    score = a_score(bass_part())
    repaired, left = repair(score)
    assert repaired == score
    assert left == ()


# ----------------------------------------------------------------------- each repair type


def test_a_note_out_of_range_is_moved_by_octaves_into_it() -> None:
    low, high = RANGES[Instrument.BASS]
    part = Part(
        instrument=Instrument.BASS, notes=(Note(pitch=16, start_beats=0.0, duration_beats=1.0),)
    )
    repaired, left = repair(a_score(part, tension=0.8))
    pitch = repaired.parts[0].notes[0].pitch
    assert low <= pitch <= high
    assert pitch % 12 == 16 % 12
    assert "range" not in {violation.rule for violation in left}


def test_a_note_off_the_grid_is_snapped_to_the_nearest_slot() -> None:
    part = Part(
        instrument=Instrument.KEYS, notes=(Note(pitch=64, start_beats=0.37, duration_beats=1.0),)
    )
    repaired, left = repair(a_score(part))
    assert repaired.parts[0].notes[0].start_beats == 0.25
    assert left == ()


def test_a_hat_conflict_becomes_the_hat_that_got_there_first() -> None:
    """Retuned, not removed: two identical hats in a slot sound like one hat."""
    part = Part(
        instrument=Instrument.DRUMS,
        notes=(
            Note(pitch=CLOSED_HAT, start_beats=0.0, duration_beats=0.25),
            Note(pitch=OPEN_HAT, start_beats=0.0, duration_beats=0.25),
        ),
    )
    repaired, left = repair(a_score(part))
    assert [note.pitch for note in repaired.parts[0].notes] == [CLOSED_HAT, CLOSED_HAT]
    assert left == ()


def test_a_kick_too_close_to_the_last_one_becomes_a_ghost() -> None:
    part = Part(
        instrument=Instrument.DRUMS,
        notes=(
            Note(pitch=KICK, start_beats=0.0, duration_beats=0.1),
            Note(pitch=KICK, start_beats=0.1, duration_beats=0.1),
        ),
    )
    repaired, left = repair(a_score(part))
    velocities = [note.velocity for note in repaired.parts[0].notes]
    assert velocities[0] == 100
    assert velocities[1] < GHOST_VELOCITY
    assert left == ()


def test_a_chord_change_with_no_root_gets_one() -> None:
    repaired, left = repair(a_score(bass_part((40, 36, 36, 38))))
    bass = repaired.parts[0]
    at_bar_three = [note for note in bass.notes if note.start_beats == 8.0]
    assert [note.pitch % 12 for note in at_bar_three] == [7]  # G
    assert left == ()


def test_a_chord_change_with_no_note_at_all_gets_a_note_added() -> None:
    """Adding is a repair. Leaving the change unsupported is the thing the rule stops."""
    sparse = Part(
        instrument=Instrument.BASS,
        notes=(Note(pitch=40, start_beats=0.0, duration_beats=1.0),),
    )
    repaired, left = repair(a_score(sparse))
    assert len(repaired.parts[0].notes) == 4
    assert left == ()


def test_a_part_over_its_dissonance_budget_is_pulled_into_the_key() -> None:
    outside = Part(
        instrument=Instrument.BASS,
        notes=tuple(
            Note(pitch=41, start_beats=index * 0.5, duration_beats=0.45) for index in range(8)
        ),
    )
    repaired, left = repair(a_score(outside, tension=0.0))
    assert left == ()
    assert all(note.pitch % 12 in {4, 6, 7, 9, 11, 0, 2} for note in repaired.parts[0].notes)


def test_a_part_under_budget_keeps_its_passing_tone() -> None:
    """The floor exists so a chromatic approach note survives repair."""
    notes = [Note(pitch=40, start_beats=index * 0.5, duration_beats=0.45) for index in range(16)]
    notes[7] = notes[7].model_copy(update={"pitch": 41})
    part = Part(instrument=Instrument.BASS, notes=tuple(notes))
    repaired, _ = repair(a_score(part, tension=0.5))
    assert repaired.parts[0].notes[7].pitch == 41


# ----------------------------------------------------------------------------- properties


BROKEN = [
    Part(instrument=Instrument.BASS, notes=(Note(pitch=16, start_beats=0.37, duration_beats=1.0),)),
    bass_part((40, 36, 36, 38)),
    Part(
        instrument=Instrument.DRUMS,
        notes=(
            Note(pitch=CLOSED_HAT, start_beats=0.0, duration_beats=0.25),
            Note(pitch=OPEN_HAT, start_beats=0.0, duration_beats=0.25),
            Note(pitch=KICK, start_beats=1.0, duration_beats=0.1),
            Note(pitch=KICK, start_beats=1.1, duration_beats=0.1),
            Note(pitch=SNARE, start_beats=2.03, duration_beats=0.1),
        ),
    ),
    Part(
        instrument=Instrument.KEYS,
        notes=tuple(
            Note(pitch=97, start_beats=index * 0.5, duration_beats=0.5) for index in range(8)
        ),
    ),
]


@pytest.mark.parametrize("part", BROKEN, ids=lambda part: str(part.instrument))
def test_repair_never_loses_a_note(part: Part) -> None:
    score = a_score(part)
    repaired, _ = repair(score)
    assert note_count(repaired) >= note_count(score)


@pytest.mark.parametrize("part", BROKEN, ids=lambda part: str(part.instrument))
def test_repair_is_idempotent(part: Part) -> None:
    """`repair(repair(x)) == repair(x)`. Two passes are not a second opinion."""
    once, _ = repair(a_score(part))
    twice, _ = repair(once)
    assert twice == once


@pytest.mark.parametrize("part", BROKEN, ids=lambda part: str(part.instrument))
def test_repair_is_deterministic(part: Part) -> None:
    assert repair(a_score(part)) == repair(a_score(part))


def test_a_whole_broken_band_comes_out_clean() -> None:
    score = a_score(*BROKEN[1:])
    repaired, left = repair(score)
    assert left == ()
    assert validate(repaired) == ()


def test_every_rule_the_validator_can_raise_is_currently_repairable() -> None:
    """Stated as a fact rather than assumed: nothing survives a repair pass today.

    Every violation the validator produces has a fix here, so `repair` always returns an
    empty tail. `Violation.repairable` and the fallback path are not dead weight — they
    are what Phase 3 needs when a model writes something no primitive can move — but
    pretending this suite exercises them would be a test that proves nothing.
    """
    impossible = Part(
        instrument=Instrument.KEYS,
        notes=(Note(pitch=64, start_beats=0.0, duration_beats=1.0),),
    )
    score = SectionScore(
        section=a_section(bars=1, chart=parse_chart("| Em |")),
        parts=(impossible,),
        seed=7,
    )
    repaired, left = repair(score)
    assert left == ()
    assert repaired.parts[0].notes[0].pitch == 64
