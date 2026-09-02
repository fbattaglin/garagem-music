"""The grid: what a bar's worth of sixteenths is, and where each one falls.

Two things are worth stating rather than assuming. A grid that parsed a wrong-length
pattern would silently play a bar nobody wrote, so the refusals are tested as carefully
as the successes. And `beats_of` is the only place `Feel` stops being a label and
becomes time — under shuffle the offbeats move, and if they ever moved past each other
the "feel" would be a wrong note.
"""

from __future__ import annotations

import pytest

from garagem.domain import (
    BEATS_PER_BAR,
    SIXTEENTHS_PER_BAR,
    SWING_POINT,
    Feel,
    beats_of,
    parse_grid,
    render_grid,
)

FOUR_ON_THE_FLOOR = "x...x...x...x..."
SIXTEENTH_HATS = "xxxxxxxxxxxxxxxx"
SILENCE = "." * SIXTEENTHS_PER_BAR


# ------------------------------------------------------------------------ parse / render


@pytest.mark.parametrize("pattern", [FOUR_ON_THE_FLOOR, SIXTEENTH_HATS, SILENCE])
def test_a_grid_round_trips_through_text(pattern: str) -> None:
    assert render_grid(parse_grid(pattern)) == pattern


def test_a_grid_marks_exactly_the_attacks() -> None:
    grid = parse_grid(FOUR_ON_THE_FLOOR)
    assert len(grid) == SIXTEENTHS_PER_BAR
    assert [index for index, slot in enumerate(grid) if slot] == [0, 4, 8, 12]


@pytest.mark.parametrize("pattern", ["x...", "x" * 17, ""])
def test_a_wrong_length_pattern_is_refused(pattern: str) -> None:
    """Padding it would play a bar nobody wrote."""
    with pytest.raises(ValueError, match="16 characters"):
        parse_grid(pattern)


def test_a_stray_character_is_refused_and_named() -> None:
    with pytest.raises(ValueError, match=r"\['o'\]"):
        parse_grid("x..o" + "." * 12)


def test_rendering_a_grid_of_the_wrong_size_is_refused() -> None:
    with pytest.raises(ValueError, match="16 slots"):
        render_grid((True, False))


# ------------------------------------------------------------------------------- placement


@pytest.mark.parametrize("feel", list(Feel))
def test_downbeats_never_move_whatever_the_feel(feel: Feel) -> None:
    """Slot 0, 4, 8 and 12 are the beats. A feel that moved them would be a tempo."""
    assert [beats_of(index, feel) for index in (0, 4, 8, 12)] == [0.0, 1.0, 2.0, 3.0]


@pytest.mark.parametrize("feel", [Feel.STRAIGHT8, Feel.STRAIGHT16, Feel.HALFTIME])
def test_a_straight_feel_puts_every_sixteenth_on_its_arithmetic_place(feel: Feel) -> None:
    assert [beats_of(index, feel) for index in range(4)] == [0.0, 0.25, 0.5, 0.75]


def test_shuffle_moves_the_offbeat_eighth_to_the_triplet() -> None:
    """The whole point of a shuffle: the "and" lands two thirds through the beat."""
    assert beats_of(2, Feel.SHUFFLE) == pytest.approx(SWING_POINT)
    assert beats_of(2, Feel.STRAIGHT8) == 0.5


@pytest.mark.parametrize("feel", list(Feel))
def test_placement_is_strictly_increasing_across_a_bar(feel: Feel) -> None:
    """A feel reorders nothing. If two slots crossed, it would be a wrong note."""
    places = [beats_of(index, feel) for index in range(SIXTEENTHS_PER_BAR)]
    assert places == sorted(places)
    assert len(set(places)) == SIXTEENTHS_PER_BAR
    assert places[0] == 0.0
    assert places[-1] < BEATS_PER_BAR


def test_an_index_past_the_bar_continues_into_the_next_one() -> None:
    """So a caller walking a section does not keep a bar counter of its own."""
    assert beats_of(SIXTEENTHS_PER_BAR, Feel.STRAIGHT8) == BEATS_PER_BAR
    assert beats_of(SIXTEENTHS_PER_BAR + 2, Feel.SHUFFLE) == pytest.approx(
        BEATS_PER_BAR + SWING_POINT
    )


def test_a_negative_index_is_refused() -> None:
    with pytest.raises(ValueError, match="not negative"):
        beats_of(-1, Feel.STRAIGHT8)
