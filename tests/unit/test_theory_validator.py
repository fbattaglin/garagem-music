"""P4 layer two: music that is well-formed and still wrong.

The last test in this file is the one that keeps the others honest. `RULES` is a public
tuple, the event log counts violations by those names, and a rule that is declared and
never implemented would be invisible — so the suite asserts that every name in it is
actually produced by some score.
"""

from __future__ import annotations

import pytest

from garagem.domain import (
    Chart,
    Feel,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
)
from garagem.theory import (
    RULES,
    Violation,
    parse_chart,
    validate,
)
from garagem.theory.percussion import CLOSED_HAT, KICK, OPEN_HAT, SNARE

PROGRESSION: Chart = parse_chart("| Em | C | G | D |")
ROOTS = (40, 36, 43, 38)  # E2, C2, G2, D2 — the four roots, all inside E1-G3


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
    """A root on every downbeat and an eighth-note pulse under it."""
    notes = []
    for bar, pitch in enumerate(pitches):
        for eighth in range(8):
            notes.append(Note(pitch=pitch, start_beats=bar * 4 + eighth * 0.5, duration_beats=0.45))
    return Part(instrument=Instrument.BASS, notes=tuple(notes))


def drum_part(bars: int = 4) -> Part:
    notes = []
    for bar in range(bars):
        for beat in range(4):
            at = bar * 4 + beat
            notes.append(
                Note(pitch=KICK if beat in (0, 2) else SNARE, start_beats=at, duration_beats=0.25)
            )
            notes.append(Note(pitch=CLOSED_HAT, start_beats=at, duration_beats=0.25))
            notes.append(Note(pitch=CLOSED_HAT, start_beats=at + 0.5, duration_beats=0.25))
    return Part(instrument=Instrument.DRUMS, notes=tuple(notes))


def a_score(*parts: Part, **section: object) -> SectionScore:
    return SectionScore(section=a_section(**section), parts=parts, seed=7)


def rules_of(violations: tuple[Violation, ...]) -> list[str]:
    return [violation.rule for violation in violations]


# ---------------------------------------------------------------------------- the clean case


def test_a_clean_section_validates_with_nothing_to_say() -> None:
    assert validate(a_score(drum_part(), bass_part())) == ()


def test_validate_is_repeatable() -> None:
    """Pure: same score, same tuple, every time. The repairer's idempotence needs it."""
    score = a_score(drum_part(), bass_part((40, 36, 43, 20)))
    assert validate(score) == validate(score)


def test_a_score_with_no_parts_has_nothing_to_break() -> None:
    assert validate(a_score()) == ()


# ---------------------------------------------------------------------------------- range


def test_a_bass_note_below_its_lowest_string_is_caught_with_its_index() -> None:
    part = Part(
        instrument=Instrument.BASS,
        notes=(
            Note(pitch=40, start_beats=0.0, duration_beats=1.0),
            Note(pitch=20, start_beats=1.0, duration_beats=1.0),
        ),
    )
    violations = [v for v in validate(a_score(part)) if v.rule == "range"]
    assert len(violations) == 1
    assert violations[0].note_index == 1
    assert violations[0].repairable


def test_drums_are_exempt_from_range_because_their_pitch_is_a_map() -> None:
    part = Part(
        instrument=Instrument.DRUMS, notes=(Note(pitch=36, start_beats=0.0, duration_beats=0.25),)
    )
    assert "range" not in rules_of(validate(a_score(part)))


# ------------------------------------------------------------- bass root on chord change


def test_a_chord_change_with_no_root_under_it_is_caught() -> None:
    """Bar 3 changes to G and the bass stays on C."""
    violations = validate(a_score(bass_part((40, 36, 36, 38))))
    roots = [v for v in violations if v.rule == "bass_root_on_chord_change"]
    assert [v.bar for v in roots] == [2]


def test_high_tension_buys_the_right_to_leave_the_root_out() -> None:
    """The DSL's own exemption: above 0.7 the harmony is allowed to float."""
    broken = bass_part((40, 36, 36, 38))
    assert "bass_root_on_chord_change" in rules_of(validate(a_score(broken)))
    assert "bass_root_on_chord_change" not in rules_of(validate(a_score(broken, tension=0.8)))


def test_a_root_that_arrives_late_is_not_on_the_change() -> None:
    late = Part(
        instrument=Instrument.BASS,
        notes=(Note(pitch=40, start_beats=1.0, duration_beats=1.0),),
    )
    assert "bass_root_on_chord_change" in rules_of(validate(a_score(late)))


# ------------------------------------------------------------------------- hihat conflict


def test_an_open_and_a_closed_hat_in_one_slot_are_caught() -> None:
    """One pedal, one hi-hat."""
    part = Part(
        instrument=Instrument.DRUMS,
        notes=(
            Note(pitch=CLOSED_HAT, start_beats=0.0, duration_beats=0.25),
            Note(pitch=OPEN_HAT, start_beats=0.0, duration_beats=0.25),
        ),
    )
    violations = [v for v in validate(a_score(part)) if v.rule == "hihat_conflict"]
    assert len(violations) == 1
    assert violations[0].note_index == 1


def test_the_same_hat_twice_in_a_slot_is_not_a_conflict() -> None:
    part = Part(
        instrument=Instrument.DRUMS,
        notes=(
            Note(pitch=CLOSED_HAT, start_beats=0.0, duration_beats=0.25),
            Note(pitch=CLOSED_HAT, start_beats=0.0, duration_beats=0.25),
        ),
    )
    assert "hihat_conflict" not in rules_of(validate(a_score(part)))


# ---------------------------------------------------------------------------- kick spacing


def two_kicks(gap_beats: float) -> Part:
    return Part(
        instrument=Instrument.DRUMS,
        notes=(
            Note(pitch=KICK, start_beats=0.0, duration_beats=0.1),
            Note(pitch=KICK, start_beats=gap_beats, duration_beats=0.1),
        ),
    )


def test_kicks_too_close_together_at_132_are_caught() -> None:
    """0.1 beats is 45 ms at 132 BPM — faster than a beater returns."""
    assert "kick_spacing" in rules_of(validate(a_score(two_kicks(0.1))))


def test_the_same_pattern_is_legal_at_60_bpm() -> None:
    """The rule is in milliseconds, not sixteenths. That is the whole point of it."""
    assert "kick_spacing" not in rules_of(validate(a_score(two_kicks(0.1), bpm=60.0)))


def test_sixteenth_note_kicks_at_132_are_fine() -> None:
    assert "kick_spacing" not in rules_of(validate(a_score(two_kicks(0.25))))


# ----------------------------------------------------------------------- dissonance budget


def outside_notes(count: int, total: int = 8) -> Part:
    """`count` notes on D# — outside E natural minor and outside every chord but B7."""
    notes = [
        Note(pitch=39 if index < count else 40, start_beats=index * 0.5, duration_beats=0.45)
        for index in range(total)
    ]
    return Part(instrument=Instrument.BASS, notes=tuple(notes))


def test_a_part_mostly_outside_the_key_is_caught() -> None:
    assert "dissonance_budget" in rules_of(validate(a_score(outside_notes(6))))


def test_one_passing_tone_is_within_budget_even_at_zero_tension() -> None:
    """Chromatic approach notes are normal; the floor exists for them."""
    assert "dissonance_budget" not in rules_of(validate(a_score(outside_notes(0), tension=0.0)))


def test_a_chord_tone_outside_the_scale_is_not_dissonance() -> None:
    """B7's D# is a borrowed dominant in E minor, not a mistake."""
    chart = parse_chart("| Em | Em | C | B7 |")
    part = Part(
        instrument=Instrument.BASS,
        notes=tuple(
            Note(pitch=39, start_beats=index * 0.5, duration_beats=0.45) for index in range(8)
        ),
    )
    assert "dissonance_budget" not in rules_of(validate(a_score(part, chart=chart, tension=0.0)))


# ------------------------------------------------------------------------- grid alignment


def test_a_note_off_the_grid_is_caught() -> None:
    part = Part(
        instrument=Instrument.KEYS,
        notes=(Note(pitch=64, start_beats=0.37, duration_beats=1.0),),
    )
    violations = [v for v in validate(a_score(part)) if v.rule == "grid_alignment"]
    assert len(violations) == 1
    assert violations[0].note_index == 0


def test_humanisation_sized_drift_is_tolerated() -> None:
    """The rule must not flag the system's own humaniser."""
    part = Part(
        instrument=Instrument.KEYS,
        notes=(Note(pitch=64, start_beats=0.02, duration_beats=1.0),),
    )
    assert "grid_alignment" not in rules_of(validate(a_score(part)))


def test_the_grid_follows_the_section_feel() -> None:
    """Beat 0.5 is a slot under straight8 and is not one under shuffle."""
    part = Part(
        instrument=Instrument.KEYS,
        notes=(Note(pitch=64, start_beats=0.5, duration_beats=0.5),),
    )
    assert "grid_alignment" not in rules_of(validate(a_score(part)))
    assert "grid_alignment" in rules_of(validate(a_score(part, feel=Feel.SHUFFLE)))


# ------------------------------------------------------------------------------ every rule


BROKEN_SCORES = [
    a_score(
        Part(
            instrument=Instrument.BASS, notes=(Note(pitch=20, start_beats=0.0, duration_beats=1.0),)
        )
    ),
    a_score(bass_part((40, 36, 36, 38))),
    a_score(
        Part(
            instrument=Instrument.DRUMS,
            notes=(
                Note(pitch=CLOSED_HAT, start_beats=0.0, duration_beats=0.25),
                Note(pitch=OPEN_HAT, start_beats=0.0, duration_beats=0.25),
            ),
        )
    ),
    a_score(two_kicks(0.1)),
    a_score(outside_notes(6)),
    a_score(
        Part(
            instrument=Instrument.KEYS,
            notes=(Note(pitch=64, start_beats=0.37, duration_beats=1.0),),
        )
    ),
]


def test_every_declared_rule_is_actually_implemented() -> None:
    """A rule that is named and never produced would be invisible in the event log."""
    produced = {violation.rule for score in BROKEN_SCORES for violation in validate(score)}
    assert produced == set(RULES)


def test_violations_come_back_in_rule_order() -> None:
    """Stable order, so a repairer and a log read the same list twice."""
    score = a_score(
        Part(
            instrument=Instrument.BASS,
            notes=(Note(pitch=20, start_beats=0.37, duration_beats=1.0),),
        )
    )
    order = rules_of(validate(score))
    assert order == sorted(order, key=RULES.index)


@pytest.mark.parametrize("rule", RULES)
def test_every_rule_name_is_a_plain_identifier(rule: str) -> None:
    """They are counted in the JSONL event log by name."""
    assert rule.isidentifier()
