"""What a bar cue switches to, stated as sound: a stop in every bar, a fill in every bar.

A person can strike the pad in any bar, so every bar of a variant has to be the cue — these
check that, and that only what the cue changes is changed.
"""

from __future__ import annotations

import pytest

from garagem.domain import SIXTEENTHS_PER_BAR, Feel, Instrument, Note, Part, Section
from garagem.engines import (
    FILL_CUE_TENSION,
    FillStyle,
    fill_bars,
    fill_for,
    land_bars,
    play_section,
    stop_bars,
)
from garagem.engines.transitions import LAST_BEAT_SLOT, STOP_RING_BEATS
from garagem.theory import grid_slots, nearest_slot, parse_chart, validate
from garagem.theory.percussion import CRASH, HATS, KICK, SNARE, TOMS

SEED = 7
PITCHED = (Instrument.BASS, Instrument.GUITAR, Instrument.KEYS)


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 2,
        "tension": 0.35,
        "chart": parse_chart("| Em | Em | C | D | Em | Em | C | B7 |"),
    }
    return Section.model_validate(base | extra)


def slot_of(section: Section, note: Note) -> int:
    slots = grid_slots(section)
    return slots.index(nearest_slot(slots, note.start_beats))


def slots_in_bar(section: Section, part: Part, bar: int, pitch: int | None = None) -> set[int]:
    return {
        slot_of(section, note) % SIXTEENTHS_PER_BAR
        for note in part.notes
        if slot_of(section, note) // SIXTEENTHS_PER_BAR == bar
        and (pitch is None or note.pitch == pitch)
    }


# ------------------------------------------------------------------------------- stop


@pytest.mark.parametrize("bar", range(8))
def test_in_every_bar_of_a_stop_the_band_plays_only_the_downbeat(bar: int) -> None:
    section = a_section()
    stopped = stop_bars(play_section(section, SEED))
    for instrument in PITCHED:
        assert slots_in_bar(section, stopped.part(instrument), bar) == {0}


def test_the_stopped_chord_rings_and_then_leaves_a_silence() -> None:
    stopped = stop_bars(play_section(a_section(), SEED))
    for instrument in PITCHED:
        assert all(
            note.duration_beats == STOP_RING_BEATS for note in stopped.part(instrument).notes
        )


@pytest.mark.parametrize("bar", range(8))
def test_in_every_bar_of_a_stop_the_drums_hit_crash_and_pick_up_on_beat_four(bar: int) -> None:
    section = a_section()
    drums = stop_bars(play_section(section, SEED)).part(Instrument.DRUMS)
    assert 0 in slots_in_bar(section, drums, bar, CRASH)
    assert 0 in slots_in_bar(section, drums, bar, KICK)
    pickup = {
        slot for slot, hit in enumerate(fill_for(section.tension)) if hit and slot >= LAST_BEAT_SLOT
    }
    assert slots_in_bar(section, drums, bar, SNARE) - {0} == pickup
    assert slots_in_bar(section, drums, bar) <= {0} | set(range(LAST_BEAT_SLOT, SIXTEENTHS_PER_BAR))
    assert not slots_in_bar(section, drums, bar) & {slot for slot in range(1, LAST_BEAT_SLOT)}
    assert not any(note.pitch in HATS for note in drums.notes)


# ------------------------------------------------------------------------------- fill


@pytest.mark.parametrize("bar", range(8))
def test_in_every_bar_of_a_fill_the_snare_fills_and_the_kick_keeps_the_groove(bar: int) -> None:
    section = a_section()
    score = play_section(section, SEED)
    drums = fill_bars(score).part(Instrument.DRUMS)
    wanted = {slot for slot, hit in enumerate(fill_for(FILL_CUE_TENSION)) if hit}
    assert slots_in_bar(section, drums, bar, SNARE) == wanted
    assert slots_in_bar(section, drums, bar, KICK) == slots_in_bar(
        section, score.part(Instrument.DRUMS), bar, KICK
    )
    assert not any(note.pitch in HATS for note in drums.notes)


def test_a_fill_cue_is_as_strong_as_the_section_asks_when_the_section_asks_for_more() -> None:
    section = a_section(tension=0.95, dyn=4)
    drums = fill_bars(play_section(section, SEED)).part(Instrument.DRUMS)
    wanted = {slot for slot, hit in enumerate(fill_for(0.95)) if hit}
    assert slots_in_bar(section, drums, 3, SNARE) == wanted


def test_a_fill_leaves_every_other_instrument_exactly_as_it_was() -> None:
    score = play_section(a_section(), SEED)
    filled = fill_bars(score)
    for instrument in PITCHED:
        assert filled.part(instrument) == score.part(instrument)


# ---------------------------------------------------------------------------- both


@pytest.mark.parametrize("variant", [stop_bars, fill_bars])
def test_a_variant_is_the_same_music_every_time(variant: object) -> None:
    score = play_section(a_section(), SEED)
    assert variant(score) == variant(score)  # type: ignore[operator]


@pytest.mark.parametrize("variant", [stop_bars, fill_bars])
def test_a_variant_keeps_the_sections_length_so_legato_positions_line_up(variant: object) -> None:
    score = play_section(a_section(), SEED)
    assert variant(score).section == score.section  # type: ignore[operator]


@pytest.mark.parametrize("variant", [stop_bars, fill_bars])
def test_a_variant_validates(variant: object) -> None:
    assert validate(variant(play_section(a_section(), SEED))) == ()  # type: ignore[operator]


# ------------------------------------------------------------------ fill styles (§10)


def drum_bar(section: Section, part: Part, bar: int) -> list[Note]:
    return sorted(
        (note for note in part.notes if slot_of(section, note) // SIXTEENTHS_PER_BAR == bar),
        key=lambda note: note.start_beats,
    )


def test_the_approved_snare_fill_is_still_the_default() -> None:
    score = play_section(a_section(), SEED)
    assert fill_bars(score) == fill_bars(score, FillStyle.SNARE)


def test_the_three_fill_styles_are_three_different_bars() -> None:
    score = play_section(a_section(), SEED)
    section = score.section
    bars = {
        style: [
            (slot_of(section, n), n.pitch)
            for n in drum_bar(section, fill_bars(score, style).part(Instrument.DRUMS), 3)
        ]
        for style in FillStyle
    }
    assert len({tuple(bar) for bar in bars.values()}) == 3


@pytest.mark.parametrize("bar", range(8))
def test_a_rising_fill_starts_on_beat_two_and_ends_louder_than_it_began(bar: int) -> None:
    section = a_section()
    drums = fill_bars(play_section(section, SEED), FillStyle.RISING).part(Instrument.DRUMS)
    snares = [n for n in drum_bar(section, drums, bar) if n.pitch == SNARE]
    assert slot_of(section, snares[0]) % SIXTEENTHS_PER_BAR == 4
    assert slot_of(section, snares[-1]) % SIXTEENTHS_PER_BAR == 15
    assert snares[-1].velocity > snares[0].velocity


@pytest.mark.parametrize("bar", range(8))
def test_a_tom_fill_runs_down_the_kit(bar: int) -> None:
    section = a_section()
    drums = fill_bars(play_section(section, SEED), FillStyle.TOMS).part(Instrument.DRUMS)
    toms = [n.pitch for n in drum_bar(section, drums, bar) if n.pitch in TOMS]
    assert toms == [pitch for pitch in TOMS for _ in (0, 1)]


@pytest.mark.parametrize("style", [FillStyle.RISING, FillStyle.TOMS])
def test_a_styled_fill_keeps_only_the_downbeat_kick_so_the_bar_is_the_fills(
    style: FillStyle,
) -> None:
    section = a_section()
    drums = fill_bars(play_section(section, SEED), style).part(Instrument.DRUMS)
    kicks = {slot_of(section, n) % SIXTEENTHS_PER_BAR for n in drums.notes if n.pitch == KICK}
    assert kicks <= {0}
    assert not any(n.pitch in HATS for n in drums.notes)


def test_a_landing_puts_a_crash_on_every_downbeat_and_changes_nothing_else() -> None:
    section = a_section()
    score = play_section(section, SEED)
    landed = land_bars(score)
    drums = landed.part(Instrument.DRUMS)
    for bar in range(section.bars):
        assert 0 in slots_in_bar(section, drums, bar, CRASH)
    original = {(n.pitch, n.start_beats) for n in score.part(Instrument.DRUMS).notes}
    assert original <= {(n.pitch, n.start_beats) for n in drums.notes}
    for instrument in PITCHED:
        assert landed.part(instrument) == score.part(instrument)


@pytest.mark.parametrize("style", list(FillStyle))
def test_every_fill_style_validates(style: FillStyle) -> None:
    assert validate(fill_bars(play_section(a_section(), SEED), style)) == ()


def test_a_landing_validates() -> None:
    assert validate(land_bars(play_section(a_section(), SEED))) == ()
