"""The four engines and the band that calls them.

The shared contract is the point of this file: whatever an engine does musically, it
must be reproducible from its seed and must produce music the validator accepts without
help. An engine that needed the repairer to be legal would be a floor with a hole in it,
and P2 rests on that floor.
"""

from __future__ import annotations

from itertools import pairwise, product
from random import Random

import pytest

from garagem.domain import (
    BEATS_PER_BAR,
    Feel,
    Instrument,
    Section,
)
from garagem.engines import ENGINES, play_section
from garagem.engines.bass import ROOT_OCTAVE
from garagem.engines.drums import play as play_drums
from garagem.engines.guitar import play as play_guitar
from garagem.engines.keys import KEYS_FLOOR
from garagem.engines.keys import play as play_keys
from garagem.theory import RANGES, parse_chart, repair, validate
from garagem.theory.percussion import CRASH, KICK, SNARE

PROGRESSION = parse_chart("| Em | C | G | D |")


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": PROGRESSION,
    }
    return Section.model_validate(base | extra)


# A spread of briefings wide enough that a rule broken in one corner shows up here.
BRIEFINGS = [
    a_section(feel=feel, dyn=dyn, tension=tension, bars=bars)
    for feel, dyn, tension, bars in product(list(Feel), (1, 3, 5), (0.0, 0.5, 1.0), (1, 4, 8))
]


# ------------------------------------------------------------------- the shared contract


@pytest.mark.parametrize("instrument,play", ENGINES, ids=lambda value: str(value))
def test_the_same_seed_gives_an_identical_part(instrument: Instrument, play: object) -> None:
    section = a_section()
    assert play(section, Random(7)) == play(section, Random(7))  # type: ignore[operator]


@pytest.mark.parametrize("instrument,play", ENGINES, ids=lambda value: str(value))
def test_every_part_is_tagged_with_its_own_instrument(instrument: Instrument, play: object) -> None:
    assert play(a_section(), Random(7)).instrument is instrument  # type: ignore[operator]


@pytest.mark.parametrize(
    "section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}-{s.bars}"
)
def test_the_whole_band_validates_clean_for_any_briefing(section: Section) -> None:
    """No engine calls the validator, and none needs the repairer to be legal."""
    assert validate(play_section(section, 7)) == ()


@pytest.mark.parametrize("section", BRIEFINGS[:12], ids=lambda s: f"{s.feel}-{s.dyn}")
def test_repairing_a_generated_score_changes_nothing(section: Section) -> None:
    score = play_section(section, 3)
    repaired, left = repair(score)
    assert left == ()
    assert repaired == score


# ---------------------------------------------------------------------------------- drums


def test_a_section_opens_with_a_crash_and_ends_with_a_fill() -> None:
    part = play_drums(a_section(bars=4), Random(7))
    crashes = [note for note in part.notes if note.pitch == CRASH]
    assert len(crashes) == 1
    assert crashes[0].start_beats < 0.1

    last_bar = [note for note in part.notes if note.start_beats >= 3 * BEATS_PER_BAR]
    earlier = [note for note in part.notes if BEATS_PER_BAR <= note.start_beats < 2 * BEATS_PER_BAR]
    snares_last = sum(1 for note in last_bar if note.pitch == SNARE)
    snares_earlier = sum(1 for note in earlier if note.pitch == SNARE)
    assert snares_last > snares_earlier


def test_a_one_bar_section_has_no_fill_to_put_anywhere() -> None:
    """A fill that replaces the only bar would be a section made of nothing else."""
    part = play_drums(a_section(bars=1), Random(7))
    assert any(note.pitch == KICK for note in part.notes)


def test_a_quiet_section_is_sparser_than_a_loud_one() -> None:
    quiet = play_drums(a_section(dyn=1), Random(7))
    loud = play_drums(a_section(dyn=5), Random(7))
    assert len(quiet.notes) < len(loud.notes)


def test_every_bar_of_the_section_gets_drums() -> None:
    part = play_drums(a_section(bars=8), Random(7))
    bars = {int(note.start_beats // BEATS_PER_BAR) for note in part.notes}
    assert bars == set(range(8))


# ----------------------------------------------------------------------------------- bass


@pytest.mark.parametrize("section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}")
def test_every_bass_note_is_inside_the_instrument(section: Section) -> None:
    low, high = RANGES[Instrument.BASS]
    part = play_section(section, 7).part(Instrument.BASS)
    assert all(low <= note.pitch <= high for note in part.notes)


def test_every_chord_change_has_its_root_on_the_downbeat() -> None:
    """Satisfied by construction, not by repair — that is the whole point of it."""
    section = a_section(bars=8)
    part = play_section(section, 7).part(Instrument.BASS)
    for bar in range(section.bars):
        if not section.chart.changes_at(bar):
            continue
        downbeat = bar * BEATS_PER_BAR
        on_it = [note for note in part.notes if abs(note.start_beats - downbeat) < 0.25]
        assert any(note.pitch % 12 == section.chart.at(bar).root for note in on_it)


def test_a_still_section_never_leaves_the_root() -> None:
    section = a_section(tension=0.0)
    part = play_section(section, 7).part(Instrument.BASS)
    roots = {section.chart.at(bar).root for bar in range(section.bars)}
    assert {note.pitch % 12 for note in part.notes} == roots


def test_a_tense_section_moves() -> None:
    still = play_section(a_section(tension=0.0), 7).part(Instrument.BASS)
    tense = play_section(a_section(tension=0.9), 7).part(Instrument.BASS)
    assert len({note.pitch for note in tense.notes}) > len({note.pitch for note in still.notes})


def test_the_root_octave_keeps_every_key_inside_the_instrument() -> None:
    low, high = RANGES[Instrument.BASS]
    assert low <= (ROOT_OCTAVE + 1) * 12 <= high
    assert low <= (ROOT_OCTAVE + 1) * 12 + 11 <= high


# --------------------------------------------------------------------------------- guitar


def test_a_verse_plays_power_chords() -> None:
    part = play_guitar(a_section(dyn=2), Random(7))
    at_once = [note for note in part.notes if note.start_beats < 0.1]
    assert len(at_once) == 2


def test_a_chorus_opens_the_chord_up() -> None:
    part = play_guitar(a_section(dyn=5), Random(7))
    at_once = [note for note in part.notes if note.start_beats < 0.1]
    assert len(at_once) == 3


def test_a_palm_mute_is_a_short_note_and_a_quiet_one() -> None:
    """Not a flag: nothing between here and the audio engine has to interpret it."""
    muted = play_guitar(a_section(dyn=1), Random(7))
    ringing = play_guitar(a_section(dyn=5), Random(7))
    assert max(note.duration_beats for note in muted.notes) < min(
        note.duration_beats for note in ringing.notes
    )


@pytest.mark.parametrize("section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}")
def test_every_guitar_note_is_inside_the_instrument(section: Section) -> None:
    low, high = RANGES[Instrument.GUITAR]
    part = play_section(section, 7).part(Instrument.GUITAR)
    assert all(low <= note.pitch <= high for note in part.notes)


def test_the_guitar_moves_less_than_root_position_between_chords() -> None:
    part = play_guitar(a_section(bars=4, dyn=5), Random(7))
    downbeats = [
        sorted(note.pitch for note in part.notes if abs(note.start_beats - bar * 4) < 0.1)
        for bar in range(4)
    ]
    led = sum(
        abs(a - b)
        for before, after in pairwise(downbeats)
        for a, b in zip(before, after, strict=True)
    )
    assert led <= 4 * 12


# ----------------------------------------------------------------------------------- keys


def test_the_keys_never_go_below_the_bass_ceiling() -> None:
    """Two instruments in one octave is mud, not harmony."""
    assert RANGES[Instrument.BASS][1] < KEYS_FLOOR
    for section in BRIEFINGS:
        part = play_keys(section, Random(7))
        assert all(note.pitch >= KEYS_FLOOR for note in part.notes)


def test_a_pad_spans_the_bar_and_a_stab_does_not() -> None:
    pad = play_keys(a_section(dyn=1), Random(7))
    stabs = play_keys(a_section(dyn=5), Random(7))
    assert max(note.duration_beats for note in pad.notes) >= BEATS_PER_BAR - 0.1
    assert max(note.duration_beats for note in stabs.notes) < 1.0


def test_a_chart_that_disagrees_with_its_key_still_validates() -> None:
    """`| Em |` under a C briefing is a legal request, and Phase 3 will make it."""
    section = a_section(key=0, scale="major", chart=parse_chart("| Em |"), dyn=1)
    assert validate(play_section(section, 7)) == ()


# ----------------------------------------------------------------------------------- band


def test_the_band_records_its_seed() -> None:
    assert play_section(a_section(), 42).seed == 42


def test_the_band_is_reproducible() -> None:
    assert play_section(a_section(), 7) == play_section(a_section(), 7)


def test_different_seeds_change_the_notes_but_not_the_harmony() -> None:
    first = play_section(a_section(), 7)
    second = play_section(a_section(), 8)
    assert first != second
    assert first.section.chart == second.section.chart


def test_all_four_instruments_are_present() -> None:
    assert play_section(a_section(), 7).instruments() == frozenset(Instrument)


def test_the_parts_come_out_in_the_dsl_emission_order() -> None:
    """DRM, BAS, GTR, KEY — the order Phase 3's incremental parser will see."""
    parts = play_section(a_section(), 7).parts
    assert [part.instrument for part in parts] == [
        Instrument.DRUMS,
        Instrument.BASS,
        Instrument.GUITAR,
        Instrument.KEYS,
    ]


def test_the_engines_share_one_generator_so_their_order_is_load_bearing() -> None:
    """Reordering the calls changes the music, which is why the order is a constant."""
    section = a_section()
    rng = Random(7)
    drums_first = [play(section, rng) for _, play in ENGINES]
    rng = Random(7)
    reversed_order = [play(section, rng) for _, play in reversed(ENGINES)]
    assert drums_first[0] != reversed_order[-1]
