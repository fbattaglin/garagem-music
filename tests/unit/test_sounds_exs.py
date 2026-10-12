"""The EXS reader: GarageBand's instruments, read field by field (ADR-029)."""

from __future__ import annotations

from pathlib import Path

import pytest
from exs_bytes import Sample, Zone, chunk, exs

from garagem.sounds.exs import ExsError, parse_exs

STRAT = Path("/Library/Application Support/Logic/Sampler Instruments/08 Guitars/Vintage Strat.exs")


def one_zone(**fields: object) -> bytes:
    zone = Zone(**{"root": 40, "key_lo": 36, "key_hi": 44, **fields})  # type: ignore[arg-type]
    return exs([zone], [("6 E_Main", 0)], [Sample("strat.caf", frames=1000)])


def test_every_field_comes_back_as_written() -> None:
    data = exs(
        [
            Zone(
                root=45,
                key_lo=45,
                key_hi=46,
                vel_lo=114,
                vel_hi=127,
                start=1095,
                end=276130,
                group=1,
                sample=0,
                fine=-5,
                coarse=1,
                volume=-3,
                name="Zone #956",
            )
        ],
        [("6 E_Main", 0), ("5 A_Main", 4)],
        [Sample("Strat_consolidated.caf", frames=300_000, folder="/Library/x", bits=24)],
        name="Vintage Strat",
    )

    instrument = parse_exs(data)

    assert instrument.name == "Vintage Strat"
    (zone,) = instrument.zones
    assert (zone.name, zone.root, zone.key_lo, zone.key_hi) == ("Zone #956", 45, 45, 46)
    assert (zone.vel_lo, zone.vel_hi, zone.start, zone.end) == (114, 127, 1095, 276130)
    assert (zone.group, zone.sample, zone.volume_db) == (1, 0, -3)
    assert zone.tune_cents == 95
    assert [(g.name, g.volume_db) for g in instrument.groups] == [("6 E_Main", 0), ("5 A_Main", 4)]
    (sample,) = instrument.samples
    assert (sample.folder, sample.file) == ("/Library/x", "Strat_consolidated.caf")
    assert (sample.frames, sample.rate, sample.bits) == (300_000, 44100, 24)


def test_a_zone_with_its_velocity_range_off_answers_every_velocity() -> None:
    instrument = parse_exs(one_zone(vel_lo=20, vel_hi=40, velocity_on=False))
    assert (instrument.zones[0].vel_lo, instrument.zones[0].vel_hi) == (0, 127)


def test_a_zone_in_no_group_is_kept_with_group_minus_one() -> None:
    assert parse_exs(one_zone(group=-1)).zones[0].group == -1


@pytest.mark.parametrize(
    ("fields", "complaint"),
    [
        ({"sample": 3}, "sample 3"),
        ({"group": 5}, "group 5"),
        ({"end": 2000}, "past the end"),
        ({"key_lo": 50, "key_hi": 40}, "wrong way round"),
        ({"start": 100, "end": 100}, "plays frames"),
    ],
)
def test_a_zone_that_points_nowhere_is_refused(fields: dict[str, object], complaint: str) -> None:
    with pytest.raises(ExsError, match=complaint):
        parse_exs(one_zone(**fields))


def test_bytes_that_are_not_an_exs_instrument_are_refused() -> None:
    with pytest.raises(ExsError, match="not an EXS"):
        parse_exs(chunk(0, "Grand Piano", bytes(4), magic=b"JBOS"))


def test_a_truncated_file_is_refused() -> None:
    with pytest.raises(ExsError, match="runs past the end"):
        parse_exs(one_zone()[:-10])


def test_an_instrument_with_no_zones_is_refused() -> None:
    with pytest.raises(ExsError, match="no zones"):
        parse_exs(exs([], [], [Sample("a.caf", frames=10)]))


@pytest.mark.skipif(not STRAT.is_file(), reason="GarageBand's library is not on this machine")
def test_garagebands_vintage_strat_reads_as_six_strings_ringing_and_muted() -> None:
    instrument = parse_exs(STRAT.read_bytes())
    names = {group.name for group in instrument.groups}
    assert {"6 E_Main", "5 A_Main", "6 E_Mute", "1 E_Mute"} <= names
    assert len(instrument.zones) == 239
    low_e = [
        (z.vel_lo, z.vel_hi)
        for z in instrument.zones
        if instrument.groups[z.group].name == "6 E_Main" and z.root == 40
    ]
    assert sorted(low_e) == [(0, 113), (114, 127)]
