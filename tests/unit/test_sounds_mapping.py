"""Which zones of a guitar Live plays, over which keys and velocities (ADR-029)."""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st

from garagem.sounds.exs import ExsGroup, ExsInstrument, ExsSample, ExsZone
from garagem.sounds.mapping import (
    STRING_FLOORS,
    Part,
    guitar_parts,
    note_name,
    rescale,
    without_overlaps,
)

OPEN_STRINGS = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}


def a_strat() -> ExsInstrument:
    """Six strings, each sampled every two frets up to the 15th, ringing at two strengths and
    palm-muted at one, plus the groups the import must leave out."""
    groups = [
        ExsGroup(f"{s} {'EADGBE'[6 - s]}_{a}", 0) for a in ("Main", "Mute") for s in OPEN_STRINGS
    ]
    groups += [ExsGroup("GB_Main", 0), ExsGroup("6 E_Tap", -2), ExsGroup("Open Chords", 0)]
    index = {group.name: n for n, group in enumerate(groups)}
    zones: list[ExsZone] = []

    def zone(group: str, root: int, lo: int, hi: int, vel: tuple[int, int]) -> None:
        start = len(zones) * 1000
        zones.append(
            ExsZone("z", root, 0, 0, lo, hi, vel[0], vel[1], start, start + 900, index[group], 0)
        )

    for string, open_note in OPEN_STRINGS.items():
        letter = "EADGBE"[6 - string]
        for fret in range(0, 16, 2):
            root = open_note + fret
            lo = open_note - 4 if fret == 0 else root
            for layer in ((0, 113), (114, 127)):
                zone(f"{string} {letter}_Main", root, lo, root + 1, layer)
            zone(f"{string} {letter}_Mute", root, lo, root + 1, (0, 127))
    zone("GB_Main", 52, 38, 127, (0, 127))
    zone("6 E_Tap", 41, 40, 63, (0, 127))
    zone("Open Chords", 16, 0, 29, (0, 127))
    return ExsInstrument(
        "Strat", tuple(zones), tuple(groups), (ExsSample("s", "", "s.caf", 10**6, 44100, 16),)
    )


def playing(parts: tuple[Part, ...], key: int, velocity: int) -> list[Part]:
    return [p for p in parts if p.key_lo <= key <= p.key_hi and p.vel_lo <= velocity <= p.vel_hi]


@given(split=st.integers(min_value=2, max_value=127))
def test_every_key_and_velocity_plays_exactly_one_sample(split: int) -> None:
    parts = guitar_parts(a_strat(), split)
    for key in range(36, 80):
        for velocity in range(1, 128):
            assert len(playing(parts, key, velocity)) == 1, (key, velocity)


@given(split=st.integers(min_value=2, max_value=127))
def test_the_palm_mute_is_below_the_split_and_the_ringing_note_at_or_above(split: int) -> None:
    for part in guitar_parts(a_strat(), split):
        if part.name.split()[2] == "mute":
            assert part.vel_hi < split
        else:
            assert part.vel_lo >= split


def test_a_note_sounds_on_the_lowest_string_that_reaches_it_in_the_first_frets() -> None:
    parts = guitar_parts(a_strat(), 80)
    string_of = {"E": 6, "A": 5, "D": 4, "G": 3, "B": 2, "e": 1}
    # A power chord on E: root, fifth and octave on the E, A and D strings.
    assert [string_of[playing(parts, k, 100)[0].name.split()[1]] for k in (40, 47, 52)] == [6, 5, 4]
    for part in parts:
        string = string_of[part.name.split()[1]]
        floors = sorted(STRING_FLOORS.values())
        floor = STRING_FLOORS[string]
        above = [f for f in floors if f > floor]
        assert part.key_lo >= floor
        assert not above or part.key_hi < above[0]


def test_taps_chords_and_garagebands_own_groups_are_left_out() -> None:
    instrument = a_strat()
    kept = {instrument.groups[p.zone.group].name for p in guitar_parts(instrument, 80)}
    assert kept.isdisjoint({"GB_Main", "6 E_Tap", "Open Chords"})


def test_a_part_carries_its_zones_level_and_its_groups() -> None:
    strat = a_strat()
    groups = tuple(ExsGroup(g.name, 3 if g.name == "6 E_Main" else 0) for g in strat.groups)
    zones = tuple(
        ExsZone(
            z.name,
            z.root,
            z.tune_cents,
            -2,
            z.key_lo,
            z.key_hi,
            z.vel_lo,
            z.vel_hi,
            z.start,
            z.end,
            z.group,
            z.sample,
        )
        for z in strat.zones
    )
    parts = guitar_parts(ExsInstrument("Strat", zones, groups, strat.samples), 80)
    assert playing(parts, 40, 100)[0].gain_db == 1
    assert playing(parts, 40, 50)[0].gain_db == -2


def test_a_zone_with_every_velocity_fills_the_layer_its_neighbours_leave() -> None:
    """The real Strat's high E at A4: a soft layer and, over it, a zone with its velocity
    range off. Logic plays that zone as the loud layer, and so does Live."""
    soft = ExsZone("soft", 69, 0, 0, 69, 70, 0, 113, 0, 10, 0, 0)
    every = ExsZone("every", 69, 0, 0, 69, 70, 0, 127, 10, 20, 0, 0)
    parts = without_overlaps(
        [Part("soft", soft, 0, 69, 70, 80, 121), Part("every", every, 0, 69, 70, 80, 127)]
    )
    assert [(p.name, p.vel_lo, p.vel_hi) for p in parts] == [("soft", 80, 121), ("every", 122, 127)]


def test_a_wider_part_over_other_keys_gives_way() -> None:
    narrow = ExsZone("narrow", 50, 0, 0, 50, 51, 0, 127, 0, 10, 0, 0)
    wide = ExsZone("wide", 52, 0, 0, 48, 60, 0, 127, 10, 20, 0, 0)
    parts = without_overlaps(
        [Part("wide", wide, 0, 48, 60, 1, 127), Part("narrow", narrow, 0, 50, 51, 1, 127)]
    )
    assert [p.name for p in parts] == ["narrow"]


layers = st.lists(st.integers(min_value=1, max_value=127), unique=True, max_size=6).map(
    lambda cuts: [0, *sorted(cuts), 128]
)


@given(edges=layers, low=st.integers(1, 127), width=st.integers(1, 127))
def test_layers_that_met_still_meet_once_rescaled(edges: list[int], low: int, width: int) -> None:
    high = min(127, low + width - 1)
    spans = [rescale(a, b - 1, (low, high)) for a, b in pairwise(edges)]
    kept = [span for span in spans if span[0] <= span[1]]
    assert kept[0][0] == low
    assert kept[-1][1] == high
    for (_, top), (bottom, _) in pairwise(kept):
        assert bottom == top + 1


def test_pitches_are_named_with_middle_c_as_c4() -> None:
    assert [note_name(p) for p in (28, 40, 60, 69)] == ["E1", "E2", "C4", "A4"]
