"""The grid, for every feel and every index.

`.claude/rules/realtime.md` names `uv run pytest tests/property/ -k timing` as the
command to run when anything on the real-time path changes. This is that file: it is
about where a slot falls, never about when a note sounds, which is Live's business
(ADR-015).
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
from strategies import feels

from garagem.domain import (
    BEATS_PER_BAR,
    SIXTEENTHS_PER_BAR,
    Feel,
    beats_of,
    parse_grid,
    render_grid,
)
from garagem.engines import MAX_TIMING_BEATS

indices = st.integers(min_value=0, max_value=SIXTEENTHS_PER_BAR * 32 - 1)


@given(feel=feels, index=indices)
def test_placement_is_strictly_increasing(feel: Feel, index: int) -> None:
    """No feel ever reorders two slots. A feel that could would be a wrong note."""
    assert beats_of(index, feel) < beats_of(index + 1, feel)


@given(feel=feels, index=indices)
def test_a_slot_never_leaves_its_own_bar(feel: Feel, index: int) -> None:
    bar = index // SIXTEENTHS_PER_BAR
    at = beats_of(index, feel)
    assert bar * BEATS_PER_BAR <= at < (bar + 1) * BEATS_PER_BAR


@given(feel=feels, index=indices)
def test_downbeats_land_exactly_on_their_beat(feel: Feel, index: int) -> None:
    beat = index - index % 4
    assert beats_of(beat, feel) == beat / 4.0


@given(feel=feels, index=indices)
def test_humanisation_can_never_reach_the_next_slot(feel: Feel, index: int) -> None:
    """The bound in `humanise` is a fact about the grid, not a hopeful constant."""
    gap = beats_of(index + 1, feel) - beats_of(index, feel)
    assert gap / 2 > MAX_TIMING_BEATS


@given(pattern=st.lists(st.sampled_from("x."), min_size=16, max_size=16).map("".join))
def test_a_grid_round_trips_for_any_pattern(pattern: str) -> None:
    assert render_grid(parse_grid(pattern)) == pattern
