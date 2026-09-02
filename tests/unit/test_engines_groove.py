"""The groove table and the humaniser.

The humaniser's bound is the assertion that matters: no note may cross a grid line. The
tightest gap the grid has is 1/6 of a beat under a shuffle, so the test checks the
constant against that gap rather than against a number copied from the source — if
either ever moves, this fails rather than the music.
"""

from __future__ import annotations

from random import Random

import pytest

from garagem.domain import (
    SIXTEENTHS_PER_BAR,
    Feel,
    Note,
    beats_of,
    render_grid,
)
from garagem.engines import (
    FILLS,
    GROOVES,
    MAX_TIMING_BEATS,
    MAX_VELOCITY,
    fill_for,
    groove_for,
    humanise,
    separate,
)

DYN_LEVELS = (1, 2, 3, 4, 5)


def some_notes(count: int = 16) -> tuple[Note, ...]:
    return tuple(
        Note(pitch=40, start_beats=index * 0.25, duration_beats=0.2, velocity=90)
        for index in range(count)
    )


# --------------------------------------------------------------------------------- table


@pytest.mark.parametrize("feel", list(Feel))
@pytest.mark.parametrize("dyn", DYN_LEVELS)
def test_every_feel_has_a_groove_at_every_dynamic(feel: Feel, dyn: int) -> None:
    groove = groove_for(feel, dyn)
    for voice in (groove.kick, groove.snare, groove.hat):
        assert len(voice) == SIXTEENTHS_PER_BAR
        assert render_grid(voice)


@pytest.mark.parametrize("feel", list(Feel))
def test_a_higher_dynamic_is_never_sparser(feel: Feel) -> None:
    """`dyn` adds subdivision. Volume is the humaniser's business, not the table's."""
    densities = [
        sum(groove_for(feel, dyn).kick) + sum(groove_for(feel, dyn).hat) for dyn in DYN_LEVELS
    ]
    assert densities == sorted(densities)


@pytest.mark.parametrize("feel", list(Feel))
@pytest.mark.parametrize("dyn", DYN_LEVELS)
def test_every_groove_starts_the_bar_with_a_kick(feel: Feel, dyn: int) -> None:
    assert groove_for(feel, dyn).kick[0]


def test_halftime_has_one_backbeat_and_straight_eight_has_two() -> None:
    """The whole trick of halftime: the same tempo, half the pulse."""
    assert sum(groove_for(Feel.HALFTIME, 3).snare) == 1
    assert sum(groove_for(Feel.STRAIGHT8, 3).snare) == 2


def test_a_dynamic_outside_one_to_five_is_clamped_rather_than_crashing() -> None:
    assert groove_for(Feel.STRAIGHT8, 0) is GROOVES[Feel.STRAIGHT8][0]
    assert groove_for(Feel.STRAIGHT8, 9) is GROOVES[Feel.STRAIGHT8][-1]


@pytest.mark.parametrize("tension", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_a_fill_exists_for_every_tension(tension: float) -> None:
    assert len(fill_for(tension)) == SIXTEENTHS_PER_BAR


def test_more_tension_is_never_a_quieter_fill() -> None:
    assert [sum(fill) for fill in FILLS] == sorted(sum(fill) for fill in FILLS)


# ----------------------------------------------------------------------------- humanising


def test_the_same_seed_gives_byte_identical_output() -> None:
    """Invariant 7. The golden tests compare exactly this."""
    first = humanise(some_notes(), Random(7), feel=Feel.STRAIGHT8)
    second = humanise(some_notes(), Random(7), feel=Feel.STRAIGHT8)
    assert first == second


def test_different_seeds_differ() -> None:
    first = humanise(some_notes(), Random(7), feel=Feel.STRAIGHT8)
    second = humanise(some_notes(), Random(8), feel=Feel.STRAIGHT8)
    assert first != second


def test_no_note_moves_further_than_the_bound() -> None:
    before = some_notes()
    after = humanise(before, Random(7), feel=Feel.STRAIGHT8)
    for original, moved in zip(before, after, strict=True):
        assert abs(moved.start_beats - original.start_beats) <= MAX_TIMING_BEATS


def test_the_bound_cannot_reach_halfway_to_a_neighbouring_slot() -> None:
    """The tightest gap in any grid is 1/6 of a beat, under a shuffle."""
    gaps = [
        beats_of(index + 1, feel) - beats_of(index, feel)
        for feel in Feel
        for index in range(SIXTEENTHS_PER_BAR - 1)
    ]
    assert min(gaps) / 2 > MAX_TIMING_BEATS


def test_no_note_crosses_a_grid_line() -> None:
    before = some_notes()
    after = humanise(before, Random(11), feel=Feel.SHUFFLE)
    for original, moved in zip(before, after, strict=True):
        assert abs(moved.start_beats - original.start_beats) < 0.5 * (1 / 6)


def test_a_note_on_the_downbeat_can_only_be_late() -> None:
    """Nothing sounds before the section starts."""
    on_one = (Note(pitch=36, start_beats=0.0, duration_beats=0.25),)
    for seed in range(20):
        assert humanise(on_one, Random(seed), feel=Feel.STRAIGHT8)[0].start_beats >= 0.0


def test_velocities_stay_inside_midi_after_the_hardest_push() -> None:
    loud = (Note(pitch=38, start_beats=0.0, duration_beats=0.25, velocity=127),)
    quiet = (Note(pitch=38, start_beats=0.0, duration_beats=0.25, velocity=1),)
    for seed in range(20):
        assert 1 <= humanise(loud, Random(seed), feel=Feel.STRAIGHT8)[0].velocity <= 127
        assert 1 <= humanise(quiet, Random(seed), feel=Feel.STRAIGHT8)[0].velocity <= 127


def test_no_velocity_moves_further_than_the_bound() -> None:
    before = some_notes()
    after = humanise(before, Random(3), feel=Feel.STRAIGHT8)
    for original, moved in zip(before, after, strict=True):
        assert abs(moved.velocity - original.velocity) <= MAX_VELOCITY


def test_amount_zero_is_the_identity_and_consumes_no_randomness() -> None:
    """A caller that turns humanisation off must not shift the rest of its section."""
    notes = some_notes()
    rng = Random(7)
    assert humanise(notes, rng, feel=Feel.STRAIGHT8, amount=0.0) == notes
    assert rng.random() == Random(7).random()


# ------------------------------------------------------------------------- separating


def test_a_note_that_would_run_into_the_next_of_its_pitch_is_shortened() -> None:
    """Live truncates such a note silently and then fails the write-then-confirm."""
    pad = (
        Note(pitch=64, start_beats=0.0, duration_beats=4.0),
        Note(pitch=64, start_beats=3.99, duration_beats=4.0),
    )
    first, second = separate(pad)
    assert first.start_beats + first.duration_beats <= second.start_beats
    assert second.duration_beats == 4.0


def test_a_different_pitch_at_the_same_moment_is_left_alone() -> None:
    """A chord is notes at the same time. Only the same pitch is a retrigger."""
    chord = (
        Note(pitch=64, start_beats=0.0, duration_beats=4.0),
        Note(pitch=67, start_beats=0.0, duration_beats=4.0),
    )
    assert separate(chord) == tuple(sorted(chord, key=lambda n: (n.start_beats, n.pitch)))


def test_separating_never_loses_a_note_or_makes_one_silent() -> None:
    crowded = tuple(
        Note(pitch=40, start_beats=index * 0.05, duration_beats=2.0) for index in range(10)
    )
    separated = separate(crowded)
    assert len(separated) == len(crowded)
    assert all(note.duration_beats > 0.0 for note in separated)


def test_separating_is_idempotent() -> None:
    pad = (
        Note(pitch=64, start_beats=0.0, duration_beats=4.0),
        Note(pitch=64, start_beats=3.99, duration_beats=4.0),
    )
    once = separate(pad)
    assert separate(once) == once


def test_separating_leaves_a_clean_part_untouched() -> None:
    clean = (
        Note(pitch=64, start_beats=0.0, duration_beats=0.5),
        Note(pitch=64, start_beats=1.0, duration_beats=0.5),
    )
    assert separate(clean) == clean


def test_output_is_in_time_order() -> None:
    """So a golden file reads like music rather than like a hash table."""
    scattered = (
        Note(pitch=40, start_beats=2.0, duration_beats=0.2),
        Note(pitch=64, start_beats=0.0, duration_beats=0.2),
        Note(pitch=40, start_beats=1.0, duration_beats=0.2),
    )
    starts = [note.start_beats for note in separate(scattered)]
    assert starts == sorted(starts)
