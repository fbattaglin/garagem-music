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

from garagem.domain import Feel, Quality
from garagem.engines import SHAPES, SongBrief, arrange, diatonic, play_section
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
