"""The song's form, chosen by a seed.

The tests here are about shape rather than about specific songs: which kinds may follow
which, that the clock is met by adding sections rather than by stretching one, and that
tension actually rises into a chorus. A test that pinned an exact sequence would fail
every time somebody argued with the transition table, which is the one thing that table
exists to invite.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from garagem.domain import Feel, Quality, Section
from garagem.engines import (
    SHAPES,
    SongBrief,
    arrange,
    candidate_for,
    continue_from,
    diatonic,
    jump_plan,
    play_section,
    with_climax,
)
from garagem.engines.arranger import CHORUS, INTRO, OUTRO
from garagem.theory import TheoryError, render_chord, validate

THREE_MINUTES = 180.0


def a_brief(**extra: object) -> SongBrief:
    base: dict[str, object] = {
        "key": 4,
        "scale": "minor",
        "bpm": 132.0,
        "feel": Feel.STRAIGHT8,
        "minimum_seconds": THREE_MINUTES,
    }
    return SongBrief.model_validate(base | extra)


def seconds_of(brief: SongBrief, seed: int) -> float:
    return sum(section.total_seconds() for section in arrange(brief, seed))


# --------------------------------------------------------------------------------- form


def test_the_same_seed_gives_the_same_song() -> None:
    assert arrange(a_brief(), 7) == arrange(a_brief(), 7)


def test_different_seeds_give_different_songs() -> None:
    forms = {tuple(section.name for section in arrange(a_brief(), seed)) for seed in range(12)}
    assert len(forms) > 1


def test_an_intro_comes_first_and_an_outro_last() -> None:
    form = arrange(a_brief(), 7)
    assert form[0].name == INTRO
    assert form[-1].name == OUTRO


@pytest.mark.parametrize("seed", range(12))
def test_no_two_adjacent_sections_are_the_same_kind(seed: int) -> None:
    """A repeat is what a longer section is for."""
    names = [section.name for section in arrange(a_brief(), seed)]
    assert all(before != after for before, after in pairwise(names))


@pytest.mark.parametrize("seed", range(12))
def test_the_form_reaches_the_minimum_length(seed: int) -> None:
    assert seconds_of(a_brief(), seed) >= THREE_MINUTES


@pytest.mark.parametrize("seed", range(12))
def test_three_minutes_means_at_least_four_section_changes(seed: int) -> None:
    assert len(arrange(a_brief(), seed)) - 1 >= 4


def test_length_is_met_by_adding_sections_not_by_stretching_one() -> None:
    """A single very long verse would satisfy the clock and prove nothing."""
    form = arrange(a_brief(), 7)
    assert all(section.bars <= 8 for section in form)


def test_a_slower_song_needs_fewer_sections_for_the_same_minutes() -> None:
    fast = len(arrange(a_brief(bpm=180.0), 7))
    slow = len(arrange(a_brief(bpm=90.0), 7))
    assert slow < fast


@pytest.mark.parametrize("seed", range(6))
def test_tension_rises_into_every_chorus(seed: int) -> None:
    form = arrange(a_brief(), seed)
    for before, after in pairwise(form):
        if after.name == CHORUS:
            assert after.tension > before.tension
            assert after.dyn > before.dyn


def test_the_shape_table_gives_a_chorus_more_of_everything_than_a_verse() -> None:
    assert SHAPES[CHORUS].dyn > SHAPES["verse"].dyn
    assert SHAPES[CHORUS].tension > SHAPES["verse"].tension


# ------------------------------------------------------------------------------- charts


@pytest.mark.parametrize("seed", range(12))
def test_every_section_has_a_chart(seed: int) -> None:
    assert all(section.chart.chords for section in arrange(a_brief(), seed))


def test_the_first_degree_of_e_minor_is_e_minor() -> None:
    assert render_chord(diatonic(4, "minor", 1)) == "Em"


@pytest.mark.parametrize(
    ("degree", "symbol"),
    [(1, "Em"), (3, "G"), (4, "Am"), (5, "Bm"), (6, "C"), (7, "D")],
)
def test_the_diatonic_chords_of_e_minor(degree: int, symbol: str) -> None:
    assert render_chord(diatonic(4, "minor", degree)) == symbol


def test_the_second_degree_of_a_minor_key_is_diminished() -> None:
    assert diatonic(4, "minor", 2).quality is Quality.DIM


def test_a_scale_with_no_seventh_degree_cannot_carry_a_song() -> None:
    """Pentatonic has five notes; a chart needs stacked thirds to exist."""
    with pytest.raises(TheoryError, match="seven-note scale"):
        arrange(a_brief(scale="pentatonic_minor"), 7)


@pytest.mark.parametrize("scale", ["minor", "major", "dorian", "mixolydian"])
@pytest.mark.parametrize("key", [0, 4, 7, 11])
def test_a_whole_song_validates_in_any_key_and_mode(scale: str, key: int) -> None:
    """The floor has to hold everywhere, not only in E minor."""
    form = arrange(a_brief(key=key, scale=scale, minimum_seconds=40.0), 7)
    assert all(validate(play_section(section, 7)) == () for section in form)


# ------------------------------------------------------------------------------ climax


@pytest.mark.parametrize("seed", range(12))
def test_the_last_chorus_is_the_biggest_section_of_the_song(seed: int) -> None:
    form = with_climax(arrange(a_brief(), seed))
    choruses = [section for section in form if section.name == CHORUS]
    assert len(choruses) > 1
    peak = choruses[-1]
    assert all(peak.dyn > other.dyn for other in choruses[:-1])
    assert all(peak.tension > other.tension for other in choruses[:-1])
    assert peak.dyn == max(section.dyn for section in form)


@pytest.mark.parametrize("seed", range(12))
def test_the_climax_changes_nothing_but_the_last_chorus(seed: int) -> None:
    plain = arrange(a_brief(), seed)
    lifted = with_climax(plain)
    last = max(index for index, section in enumerate(plain) if section.name == CHORUS)
    assert len(lifted) == len(plain)
    assert [s for i, s in enumerate(lifted) if i != last] == [
        s for i, s in enumerate(plain) if i != last
    ]
    assert lifted[last].chart == plain[last].chart


def test_a_song_with_one_chorus_has_nothing_to_rise_above() -> None:
    form = tuple(
        section for section in arrange(a_brief(minimum_seconds=20.0), 7) if section.name != CHORUS
    )
    one = (*form[:-1], arrange(a_brief(), 7)[2], form[-1])
    assert with_climax(one) == one


def test_the_climax_never_passes_the_top_of_the_scale() -> None:
    form = arrange(a_brief(), 7)
    peaked = {"dyn": 5, "tension": 0.95}
    loud = tuple(
        section.model_copy(update=peaked) if section.name == CHORUS else section for section in form
    )
    peak = [section for section in with_climax(loud) if section.name == CHORUS][-1]
    assert peak.dyn == 5
    assert peak.tension == 1.0


@pytest.mark.parametrize("seed", range(4))
def test_a_lifted_song_still_validates_section_by_section(seed: int) -> None:
    form = with_climax(arrange(a_brief(), seed))
    assert all(validate(play_section(section, seed)) == () for section in form)


# ------------------------------------------------------------------------ jumps (ADR-022)


def a_form(seed: int = 7) -> tuple[Section, ...]:
    return with_climax(arrange(a_brief(), seed))


def test_the_chorus_candidate_is_the_songs_own_chorus_at_its_ordinary_size() -> None:
    form = a_form()
    candidate = candidate_for(form, CHORUS, 1)
    first = next(section for section in form if section.name == CHORUS)
    assert candidate.chart == first.chart
    assert (candidate.dyn, candidate.tension) == (SHAPES[CHORUS].dyn, SHAPES[CHORUS].tension)


def test_a_form_with_no_chorus_still_gets_a_chorus_candidate_in_its_key() -> None:
    form = tuple(section for section in a_form() if section.name != CHORUS)
    candidate = candidate_for(form, CHORUS, 1)
    assert candidate.name == CHORUS
    assert (candidate.key, candidate.scale, candidate.bpm) == (
        form[0].key,
        form[0].scale,
        form[0].bpm,
    )


def test_a_continuation_ends_with_the_outro_and_never_repeats_a_kind() -> None:
    form = a_form()
    tail = continue_from(form[1], CHORUS, 3, 60.0)
    assert tail[-1].name == OUTRO
    names = [CHORUS, *(section.name for section in tail[:-1])]
    assert all(before != after for before, after in pairwise(names))


def test_a_continuation_with_no_time_left_is_only_the_outro() -> None:
    assert [section.name for section in continue_from(a_form()[1], CHORUS, 3, 0.0)] == [OUTRO]


@pytest.mark.parametrize("playing", [0, 1, 4, 9])
def test_a_jump_keeps_what_played_and_puts_the_chorus_next(playing: int) -> None:
    form = a_form()
    candidate = candidate_for(form, CHORUS, 1)
    plan = jump_plan(form, playing, candidate, 5)
    assert plan[: playing + 1] == form[: playing + 1]
    assert plan[playing + 1] == candidate
    assert plan[-1].name == OUTRO


def test_a_jump_reshapes_the_song_rather_than_lengthening_it() -> None:
    form = a_form()
    candidate = candidate_for(form, CHORUS, 1)
    plan = jump_plan(form, 1, candidate, 5)
    planned = sum(section.total_seconds() for section in form)
    jumped = sum(section.total_seconds() for section in plan)
    # The walk stops after it passes the time left, so it can overshoot by a section.
    assert abs(jumped - planned) <= max(section.total_seconds() for section in form) + 1e-6


def test_the_climax_moves_to_the_new_tail_and_never_onto_the_candidate() -> None:
    form = a_form()
    candidate = candidate_for(form, CHORUS, 1)
    plan = jump_plan(form, 1, candidate, 5)
    assert plan[2] == candidate
    tail_choruses = [section for section in plan[3:] if section.name == CHORUS]
    if tail_choruses:
        assert tail_choruses[-1].dyn == SHAPES[CHORUS].dyn + 1


def test_the_same_jump_gives_the_same_song() -> None:
    form = a_form()
    candidate = candidate_for(form, CHORUS, 1)
    assert jump_plan(form, 3, candidate, 5) == jump_plan(form, 3, candidate, 5)


@pytest.mark.parametrize("seed", range(6))
def test_every_section_of_a_jumped_song_validates(seed: int) -> None:
    form = a_form(seed)
    candidate = candidate_for(form, CHORUS, seed)
    plan = jump_plan(form, 2, candidate, seed + 1)
    assert all(validate(play_section(section, seed)) == () for section in plan)
