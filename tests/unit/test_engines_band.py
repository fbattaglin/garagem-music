"""The four engines and the band that calls them.

The shared contract is the point of this file: whatever an engine does musically, it
must be reproducible from its seed and must produce music the validator accepts without
help. An engine that needed the repairer to be legal would be a floor with a hole in it,
and P2 rests on that floor.
"""

from __future__ import annotations

from itertools import product
from random import Random

import pytest

from garagem.domain import (
    BEATS_PER_BAR,
    Feel,
    Instrument,
    Section,
)
from garagem.engines import ENGINES, play_section
from garagem.engines.bass import ROOT_WINDOW
from garagem.engines.bass import play as play_bass
from garagem.engines.drums import play as play_drums
from garagem.engines.guitar import play as play_guitar
from garagem.engines.keys import KEYS_FLOOR, ORGAN_DYN, ORGAN_FLOOR
from garagem.engines.keys import play as play_keys
from garagem.theory import POWER_ROOTS, RANGES, parse_chart, repair, validate
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


def test_the_root_window_is_inside_the_instrument() -> None:
    low, high = RANGES[Instrument.BASS]
    assert low <= ROOT_WINDOW[0] < ROOT_WINDOW[1] <= high
    assert ROOT_WINDOW[1] - ROOT_WINDOW[0] == 11


@pytest.mark.parametrize("section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}")
def test_every_bar_starts_on_a_root_on_the_low_strings(section: Section) -> None:
    """Every key, every bar: the downbeat is between E1 and D#2 (ADR-028)."""
    part = play_bass(section, Random(7))
    for bar in range(section.bars):
        downbeat = min(
            (note for note in part.notes if abs(note.start_beats - bar * BEATS_PER_BAR) < 0.1),
            key=lambda note: note.start_beats,
        )
        assert ROOT_WINDOW[0] <= downbeat.pitch <= ROOT_WINDOW[1]
        assert downbeat.pitch % 12 == section.chart.at(bar).root


# --------------------------------------------------------------------------------- guitar


def test_a_verse_plays_power_chords() -> None:
    part = play_guitar(a_section(dyn=2), Random(7))
    at_once = sorted(note.pitch for note in part.notes if note.start_beats < 0.1)
    root = at_once[0]
    assert at_once == [root, root + 7, root + 12]


@pytest.mark.parametrize("section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}")
def test_the_guitar_never_plays_a_triad(section: Section) -> None:
    """A chorus gets bigger by ringing and by a second guitar, not by a third (ADR-028)."""
    part = play_guitar(section, Random(7))
    for bar in range(section.bars):
        chord = section.chart.at(bar)
        classes = {
            note.pitch % 12
            for note in part.notes
            if bar * BEATS_PER_BAR - 0.1 <= note.start_beats < (bar + 1) * BEATS_PER_BAR - 0.1
        }
        assert classes <= {chord.root, (chord.root + 7) % 12, (chord.root + 6) % 12}


@pytest.mark.parametrize("section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}")
def test_every_power_chord_has_its_root_on_the_low_strings(section: Section) -> None:
    low, high = POWER_ROOTS
    part = play_guitar(section, Random(7))
    assert all(low <= note.pitch <= high + 19 for note in part.notes)
    assert min(note.pitch for note in part.notes) <= high


def test_a_palm_mute_is_a_short_note_and_a_quiet_one() -> None:
    """Not a flag: nothing between here and the audio engine has to interpret it."""
    muted = play_guitar(a_section(dyn=1), Random(7))
    ringing = play_guitar(a_section(dyn=5), Random(7))
    assert max(note.duration_beats for note in muted.notes) < min(
        note.duration_beats for note in ringing.notes
    )


def test_a_half_time_chorus_rings_until_the_next_strum() -> None:
    part = play_guitar(a_section(dyn=5, feel=Feel.HALFTIME), Random(7))
    assert min(note.duration_beats for note in part.notes) > 1.5


@pytest.mark.parametrize("section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}")
def test_every_guitar_note_is_inside_the_instrument(section: Section) -> None:
    low, high = RANGES[Instrument.GUITAR]
    part = play_section(section, 7).part(Instrument.GUITAR)
    assert all(low <= note.pitch <= high for note in part.notes)


def test_the_guitar_slides_the_shape_rather_than_inverting_it() -> None:
    """Every chord is root, fifth and octave from the bottom: never a fourth below the root."""
    part = play_guitar(a_section(bars=4, dyn=5), Random(7))
    for bar in range(4):
        chord = sorted(note.pitch for note in part.notes if abs(note.start_beats - bar * 4) < 0.1)
        assert chord[0] % 12 == PROGRESSION.at(bar).root
        assert chord[1] - chord[0] == 7


# ----------------------------------------------------------------------------------- keys


def test_the_keys_never_go_below_the_bass_ceiling() -> None:
    """Two instruments in one octave is mud, not harmony."""
    assert RANGES[Instrument.BASS][1] < KEYS_FLOOR
    for section in BRIEFINGS:
        part = play_keys(section, Random(7))
        assert all(note.pitch >= KEYS_FLOOR for note in part.notes)


@pytest.mark.parametrize("dyn", range(1, ORGAN_DYN))
def test_the_organ_rests_in_a_verse(dyn: int) -> None:
    """An indie verse is guitar, bass and drums (ADR-028). Empty, not missing."""
    assert play_keys(a_section(dyn=dyn), Random(7)).notes == ()


@pytest.mark.parametrize("dyn", range(ORGAN_DYN, 6))
def test_the_organ_holds_every_chord_across_its_bar(dyn: int) -> None:
    """No stabs: an organ holds the chord underneath the guitars."""
    part = play_keys(a_section(dyn=dyn), Random(7))
    assert part.notes
    assert min(note.duration_beats for note in part.notes) >= BEATS_PER_BAR - 0.1


@pytest.mark.parametrize("section", BRIEFINGS, ids=lambda s: f"{s.feel}-{s.dyn}-{s.tension}")
def test_the_organ_sits_above_the_guitar(section: Section) -> None:
    organ = play_keys(section, Random(7))
    guitar = play_guitar(section, Random(7))
    if organ.notes:
        assert min(note.pitch for note in organ.notes) >= ORGAN_FLOOR
        assert max(note.pitch for note in guitar.notes) < ORGAN_FLOOR


def test_a_chorus_gets_the_whole_chord_and_a_bridge_an_open_one() -> None:
    chorus = play_keys(a_section(dyn=4, chart=parse_chart("| Em |"), bars=1), Random(7))
    bridge = play_keys(a_section(dyn=3, chart=parse_chart("| Em |"), bars=1), Random(7))
    assert {note.pitch % 12 for note in chorus.notes} == {4, 7, 11}
    assert {note.pitch % 12 for note in bridge.notes} == {4, 6, 11}


def test_a_chart_that_disagrees_with_its_key_still_validates() -> None:
    """`| Em |` under a C briefing is a legal request, and Phase 3 will make it."""
    section = a_section(key=0, scale="major", chart=parse_chart("| Em |"), dyn=3)
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


def test_all_five_instruments_are_present() -> None:
    assert play_section(a_section(), 7).instruments() == frozenset(Instrument)


def test_the_parts_come_out_in_the_dsl_emission_order() -> None:
    """DRM, BAS, GTR, KEY — the order Phase 3's incremental parser will see — then LED,
    which it never sees, behind them (ADR-026), and the second guitar, which no notation
    carries, last of all (ADR-028)."""
    parts = play_section(a_section(), 7).parts
    assert [part.instrument for part in parts] == [
        Instrument.DRUMS,
        Instrument.BASS,
        Instrument.GUITAR,
        Instrument.KEYS,
        Instrument.LEAD,
        Instrument.GUITAR_DOUBLE,
    ]


def test_the_engines_share_one_generator_so_their_order_is_load_bearing() -> None:
    """Reordering the calls changes the music, which is why the order is a constant."""
    section = a_section()
    rng = Random(7)
    drums_first = [play(section, rng) for _, play in ENGINES]
    rng = Random(7)
    reversed_order = [play(section, rng) for _, play in reversed(ENGINES)]
    assert drums_first[0] != reversed_order[-1]
