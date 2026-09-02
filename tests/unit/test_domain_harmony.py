"""Chords as integers, and a chart that loops.

The interesting assertions are the ones about absence: a power chord has no third, and
an empty chart cannot be constructed. Both are places where a permissive type would let
a whole section be silently wrong.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from garagem.domain import PITCH_CLASSES, Chart, Chord, Quality

E = 4
C = 0
G = 7
D = 2

EM = Chord(root=E, quality=Quality.MINOR)
C_MAJ = Chord(root=C, quality=Quality.MAJOR)
G_MAJ = Chord(root=G, quality=Quality.MAJOR)
D_MAJ = Chord(root=D, quality=Quality.MAJOR)

PROGRESSION = Chart(chords=(EM, C_MAJ, G_MAJ, D_MAJ))


# ------------------------------------------------------------------------------- chords


@pytest.mark.parametrize(
    ("quality", "expected"),
    [
        (Quality.MAJOR, (0, 4, 7)),
        (Quality.MINOR, (0, 3, 7)),
        (Quality.DOM7, (0, 4, 7, 10)),
        (Quality.MIN7, (0, 3, 7, 10)),
        (Quality.MAJ7, (0, 4, 7, 11)),
        (Quality.SUS2, (0, 2, 7)),
        (Quality.SUS4, (0, 5, 7)),
        (Quality.DIM, (0, 3, 6)),
        (Quality.POWER, (0, 7)),
    ],
)
def test_each_quality_has_its_intervals(quality: Quality, expected: tuple[int, ...]) -> None:
    assert Chord(root=C, quality=quality).intervals() == expected


def test_a_power_chord_has_two_notes_and_no_third() -> None:
    """No third is why it sits over a major and a minor bar alike."""
    power = Chord(root=E, quality=Quality.POWER)
    assert len(power.intervals()) == 2
    assert power.pitch_classes() == frozenset({E, (E + 7) % PITCH_CLASSES})


def test_pitch_classes_wrap_around_b() -> None:
    b_major = Chord(root=11, quality=Quality.MAJOR)
    assert b_major.pitch_classes() == frozenset({11, 3, 6})


@pytest.mark.parametrize("root", [-1, 12])
def test_a_root_outside_the_twelve_pitch_classes_is_refused(root: int) -> None:
    with pytest.raises(ValidationError):
        Chord(root=root, quality=Quality.MAJOR)


def test_a_chord_is_frozen_and_hashable() -> None:
    """Engines put chords in sets and use them as dict keys; both need this."""
    with pytest.raises(ValidationError):
        EM.root = 5
    assert len({EM, Chord(root=E, quality=Quality.MINOR)}) == 1


# -------------------------------------------------------------------------------- charts


def test_a_chart_wraps_so_four_chords_cover_eight_bars() -> None:
    assert [PROGRESSION.at(bar) for bar in range(4)] == [EM, C_MAJ, G_MAJ, D_MAJ]
    assert [PROGRESSION.at(bar) for bar in range(4, 8)] == [EM, C_MAJ, G_MAJ, D_MAJ]


def test_an_empty_chart_cannot_be_constructed() -> None:
    """`at` would have nothing to return, and every engine would have to check."""
    with pytest.raises(ValidationError):
        Chart(chords=())


def test_a_negative_bar_is_refused_rather_than_wrapped_backwards() -> None:
    with pytest.raises(ValueError, match="not negative"):
        PROGRESSION.at(-1)


def test_bar_zero_counts_as_a_chord_change() -> None:
    """The first chord of a section needs its root as much as any later one."""
    assert PROGRESSION.changes_at(0)


def test_a_repeated_chord_is_not_a_change() -> None:
    held = Chart(chords=(EM, EM, C_MAJ))
    assert not held.changes_at(1)
    assert held.changes_at(2)


def test_changes_at_sees_the_wrap() -> None:
    """Bar 4 restarts the loop on Em after a D — a change, not a continuation."""
    assert PROGRESSION.changes_at(4)
