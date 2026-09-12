"""The two things a person can ask for, and which timing each cue has (ADR-022)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from garagem.domain import Cue, CueFamily, CueKind, Macro, MacroKind


def test_every_cue_has_a_family() -> None:
    """A cue with no family would be a cue nobody knows when to play."""
    assert all(isinstance(kind.family, CueFamily) for kind in CueKind)


@pytest.mark.parametrize(
    ("kind", "family"),
    [
        (CueKind.CHORUS_NOW, CueFamily.JUMP),
        (CueKind.STOP, CueFamily.BAR),
        (CueKind.FILL, CueFamily.BAR),
        (CueKind.DRUMS_AND_BASS, CueFamily.BAR),
        (CueKind.NEXT_BRIDGE, CueFamily.BOUNDARY),
        (CueKind.END, CueFamily.BOUNDARY),
    ],
)
def test_each_cue_lands_when_adr_022_says(kind: CueKind, family: CueFamily) -> None:
    assert kind.family is family


def test_a_macro_is_a_position_between_the_two_stops() -> None:
    assert Macro(kind=MacroKind.DENSITY, value=0.0).value == 0.0
    assert Macro(kind=MacroKind.TENSION, value=1.0).value == 1.0
    with pytest.raises(ValidationError):
        Macro(kind=MacroKind.TENSION, value=1.01)


def test_controls_are_frozen() -> None:
    cue = Cue(kind=CueKind.STOP)
    with pytest.raises(ValidationError):
        cue.kind = CueKind.FILL
