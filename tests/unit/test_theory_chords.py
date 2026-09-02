"""Chord symbols in and out.

The round trip is not the identity, and the test that says so is the important one:
`Gb` comes back as `F#`. One spelling per chord is what makes a serialised section
comparable byte for byte, which is what the golden tests rest on.
"""

from __future__ import annotations

import pytest

from garagem.domain import Chart, Chord, Quality
from garagem.theory import (
    TheoryError,
    parse_chart,
    parse_chord,
    render_chart,
    render_chord,
)

CANONICAL = ["Em", "B7", "Csus2", "F#m7", "A5", "C", "Gmaj7", "Ddim", "G#sus4"]


# -------------------------------------------------------------------------------- chords


@pytest.mark.parametrize("symbol", CANONICAL)
def test_a_canonical_symbol_round_trips(symbol: str) -> None:
    assert render_chord(parse_chord(symbol)) == symbol


@pytest.mark.parametrize(
    ("symbol", "root", "quality"),
    [
        ("Em", 4, Quality.MINOR),
        ("B7", 11, Quality.DOM7),
        ("Csus2", 0, Quality.SUS2),
        ("F#m7", 6, Quality.MIN7),
        ("A5", 9, Quality.POWER),
    ],
)
def test_the_dsl_examples_parse_to_what_they_mean(symbol: str, root: int, quality: Quality) -> None:
    assert parse_chord(symbol) == Chord(root=root, quality=quality)


@pytest.mark.parametrize(("flat", "sharp"), [("Gb", "F#"), ("Ebm7", "D#m7"), ("Bb", "A#")])
def test_flats_parse_and_render_as_sharps(flat: str, sharp: str) -> None:
    """Canonical form, stated: one spelling per chord, so sections compare byte for byte."""
    assert render_chord(parse_chord(flat)) == sharp


def test_an_accidental_that_crosses_the_octave_still_lands() -> None:
    """`Cb` is B and `B#` is C — arithmetic, not a table of special cases."""
    assert parse_chord("Cb") == Chord(root=11, quality=Quality.MAJOR)
    assert parse_chord("B#") == Chord(root=0, quality=Quality.MAJOR)


def test_an_unknown_quality_names_the_symbol_and_the_known_suffixes() -> None:
    with pytest.raises(TheoryError, match="'Cm9'"):
        parse_chord("Cm9")


def test_a_note_name_outside_a_to_g_is_refused() -> None:
    with pytest.raises(TheoryError, match="not a note name"):
        parse_chord("Hm")


def test_an_empty_symbol_is_refused() -> None:
    with pytest.raises(TheoryError, match="empty chord symbol"):
        parse_chord("  ")


# -------------------------------------------------------------------------------- charts


def test_the_dsl_chd_line_parses() -> None:
    chart = parse_chart("| Em | Em | C  | D  | Em | Em | C  | B7 |")
    assert [render_chord(chord) for chord in chart.chords] == [
        "Em",
        "Em",
        "C",
        "D",
        "Em",
        "Em",
        "C",
        "B7",
    ]


def test_the_outer_pipes_are_optional() -> None:
    assert parse_chart("Em | C | G | D") == parse_chart("| Em | C | G | D |")


def test_whitespace_is_free() -> None:
    assert parse_chart("|Em|C|") == parse_chart("  |  Em  |  C  |  ")


def test_an_empty_bar_is_refused_rather_than_filled() -> None:
    """A hole in a chart would play a bar nobody chose."""
    with pytest.raises(TheoryError, match="bar 2"):
        parse_chart("| Em |  | C |")


def test_an_empty_chart_line_is_refused() -> None:
    with pytest.raises(TheoryError, match="at least one chord"):
        parse_chart("|  |")


def test_a_chart_round_trips_through_the_chd_line() -> None:
    line = "| Em | C | G | D |"
    assert render_chart(parse_chart(line)) == line


def test_rendering_a_chart_uses_the_pipes_the_dsl_writes() -> None:
    chart = Chart(chords=(Chord(root=4, quality=Quality.MINOR),))
    assert render_chart(chart) == "| Em |"
