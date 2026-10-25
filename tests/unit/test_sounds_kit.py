"""Drum Kit Designer's kits, each piece on the note the band writes (ADR-029)."""

from __future__ import annotations

from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import pytest
from exs_bytes import Sample, Zone, exs
from hypothesis import given
from hypothesis import strategies as st

from garagem.sounds.exs import ExsInstrument, parse_exs
from garagem.sounds.kit import PIECES, KitError, kit_parts, piece_of
from garagem.sounds.mapping import Part
from garagem.theory.percussion import (
    CLOSED_HAT,
    CRASH,
    HATS,
    KICK,
    OPEN_HAT,
    PEDAL_HAT,
    RIDE,
    SNARE,
    TOM_LOW,
    TOM_MID,
    TOMS,
)

KITS = Path(
    "/Library/Application Support/Logic/Sampler Instruments/03 Drums & Percussion/"
    "04 Drum Kit Designer/Drum Kit Designer/Stereo"
)
BAND_NOTES = (KICK, SNARE, *sorted(HATS), CRASH, RIDE, *TOMS)

# Every hi-hat opening on the same three keys, as Drum Kit Designer lays them out, and a snare
# on a key the band never writes: the import has to choose, not take everything.
DECOYS = [(f"HH:o{n}", key) for n in (1, 2, 3, 4, 5, 6, 7) for key in (42, 44, 46)]
DECOYS += [("Sn1:all", 40)]


def kit_exs(folder: str = "", layers: int = 12, leave_out: str = "") -> bytes:
    """A kit with every piece the import looks for, each in `layers` velocity layers that get
    quieter as they get harder, as the real kick's do."""
    places = [(piece.group, piece.key) for piece in PIECES] + DECOYS
    places = [place for place in dict.fromkeys(places) if place[0] != leave_out]
    groups = sorted({group for group, _ in places})
    zones = [
        Zone(
            root=key,
            key_lo=key,
            key_hi=key,
            vel_lo=layer * 128 // layers,
            vel_hi=(layer + 1) * 128 // layers - 1,
            start=10 * layer,
            end=10 * layer + 100,
            group=groups.index(group),
            volume=-layer,
            name=f"{group} {key} {layer}",
        )
        for group, key in places
        for layer in range(layers)
    ]
    return exs(
        zones,
        [(f"AnKit2:{group}:Pr", 0) for group in groups],
        [Sample("kit.caf", frames=1000, folder=folder)],
        name="Test Kit",
    )


def a_kit(layers: int = 12, kept: int = 8) -> tuple[ExsInstrument, tuple[Part, ...]]:
    instrument = parse_exs(kit_exs(layers=layers))
    return instrument, kit_parts(instrument, kept)


def on(parts: tuple[Part, ...], note: int) -> list[Part]:
    return sorted((p for p in parts if p.key_lo <= note <= p.key_hi), key=lambda p: p.vel_lo)


def test_every_note_the_band_writes_plays_one_sample_at_every_velocity() -> None:
    _, parts = a_kit()
    for note in BAND_NOTES:
        for velocity in range(1, 128):
            playing = [p for p in on(parts, note) if p.vel_lo <= velocity <= p.vel_hi]
            assert len(playing) == 1, (note, velocity)
    assert {p.key_lo for p in parts} == set(BAND_NOTES)


def test_the_hats_are_chosen_by_how_long_they_ring() -> None:
    instrument, parts = a_kit()

    def group(note: int) -> set[str]:
        return {piece_of(instrument, p.zone) for p in on(parts, note)}

    assert group(CLOSED_HAT) == {"HH:o1"}
    assert group(OPEN_HAT) == {"HH:o5"}
    assert group(PEDAL_HAT) == {"HH:foot"}


def test_the_low_tom_is_the_mid_tom_three_semitones_down() -> None:
    _, parts = a_kit()
    low, mid = on(parts, TOM_LOW), on(parts, TOM_MID)
    assert [p.zone for p in low] == [p.zone for p in mid]
    assert {p.root for p in low} == {TOM_LOW + 3}
    assert {p.root for p in mid} == {TOM_MID}


def test_every_other_piece_plays_at_its_own_pitch() -> None:
    _, parts = a_kit()
    assert all(p.root == p.key_lo for p in parts if p.key_lo != TOM_LOW)


@given(layers=st.integers(min_value=1, max_value=16), kept=st.integers(min_value=1, max_value=10))
def test_a_piece_keeps_at_most_the_layers_asked_for_over_every_velocity(
    layers: int, kept: int
) -> None:
    _, parts = a_kit(layers, kept)
    for note in BAND_NOTES:
        spans = [(p.vel_lo, p.vel_hi) for p in on(parts, note)]
        assert len(spans) <= kept
        assert spans[0][0] == 1
        assert spans[-1][1] == 127
        assert all(upper[0] == lower[1] + 1 for lower, upper in pairwise(spans))


def test_each_band_is_played_by_the_layer_logic_plays_in_its_middle() -> None:
    """Sixteen layers of eight velocities into four bands, whose middles are 16, 47, 79, 111."""
    _, parts = a_kit(layers=16, kept=4)
    kick = on(parts, KICK)
    assert [(p.vel_lo, p.vel_hi) for p in kick] == [(1, 31), (32, 63), (64, 95), (96, 127)]
    assert [p.zone.vel_lo for p in kick] == [16, 40, 72, 104]
    assert [p.gain_db for p in kick] == [-2, -5, -9, -13]


def test_a_kit_without_a_piece_the_band_plays_is_refused() -> None:
    with pytest.raises(KitError, match="ride"):
        kit_parts(parse_exs(kit_exs(leave_out="Rd:all")))


def test_layers_that_leave_a_velocity_unplayed_are_refused() -> None:
    instrument = parse_exs(kit_exs(layers=2))
    zones = tuple(
        replace(z, vel_lo=70) if piece_of(instrument, z) == "Bd1:all" and z.vel_lo == 64 else z
        for z in instrument.zones
    )
    with pytest.raises(KitError, match="velocity unplayed"):
        kit_parts(replace(instrument, zones=zones))


@pytest.mark.skipif(not KITS.is_dir(), reason="GarageBand's library is not on this machine")
@pytest.mark.parametrize("kit", ["SoCal Kit", "Heavy Kit"])
def test_garagebands_kits_have_every_piece_the_band_plays(kit: str) -> None:
    parts = kit_parts(parse_exs((KITS / f"{kit}.exs").read_bytes()))
    for note in BAND_NOTES:
        spans = [(p.vel_lo, p.vel_hi) for p in on(parts, note)]
        assert spans[0][0] == 1
        assert spans[-1][1] == 127
        assert all(upper[0] == lower[1] + 1 for lower, upper in pairwise(spans))
