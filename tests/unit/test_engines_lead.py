"""The fifth voice: when it speaks, where it speaks, and what it is allowed to say.

ADR-026 gives the band a lead so the songwriter has a track to write a riff on. The floor
plays one in the meantime (invariant 2), and everything worth pinning about it is a
restraint: it is silent most of the time, it answers rather than leads, its notes come out
of the chord, and it sits on the eighths Stage A put the rest of the band on.
"""

from __future__ import annotations

from random import Random

import pytest

from garagem.domain import SIXTEENTHS_PER_BAR, Feel, Instrument, Section
from garagem.engines import play_section
from garagem.engines.lead import BUSY, LEAD_DYN, QUIET, answering_bars
from garagem.engines.lead import play as play_lead
from garagem.theory import RANGES, parse_chart, validate
from garagem.theory.scales import degree_to_pitch
from garagem.theory.validator import grid_slots, nearest_slot

PROGRESSION = parse_chart("| Em | C | G | D |")


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "chorus",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 4,
        "tension": 0.7,
        "chart": PROGRESSION,
    }
    return Section.model_validate(base | extra)


def bars_played(section: Section, seed: int = 7) -> set[int]:
    part = play_lead(section, Random(seed))
    return {int(note.start_beats // 4) for note in part.notes}


# ------------------------------------------------------------------------ when it speaks


@pytest.mark.parametrize("dyn", [1, 2, 3])
def test_it_says_nothing_under_a_verse(dyn: int) -> None:
    assert play_lead(a_section(dyn=dyn), Random(7)).notes == ()


@pytest.mark.parametrize("dyn", [4, 5])
def test_it_speaks_in_a_chorus(dyn: int) -> None:
    assert play_lead(a_section(dyn=dyn), Random(7)).notes


def test_being_silent_costs_no_randomness() -> None:
    """Which is what lets the silent case be an early return.

    The band hands one `Random` to each engine in turn (`engines/band.py`), so an engine
    that drew from it and threw the result away would move every engine after it. There is
    none after this one — but the claim is cheap to make true and expensive to rediscover.
    """
    rng = Random(7)
    before = rng.getstate()
    play_lead(a_section(dyn=LEAD_DYN - 1), rng)
    assert rng.getstate() == before


def test_the_knob_can_bring_it_into_a_verse() -> None:
    """The density knob moves `dyn` by up to two (ADR-021). That is the knob working."""
    quiet = a_section(name="verse", dyn=2, tension=0.35)
    assert play_lead(quiet, Random(7)).notes == ()
    assert play_lead(quiet.model_copy(update={"dyn": 4}), Random(7)).notes


# ----------------------------------------------------------------------- where it speaks


def test_it_answers_on_alternate_bars_and_leaves_the_last_one_alone() -> None:
    assert bars_played(a_section(bars=8)) == {1, 3, 5}


def test_a_section_too_short_to_answer_in_says_nothing() -> None:
    assert bars_played(a_section(bars=2)) == set()


@pytest.mark.parametrize("bars", [1, 2, 3, 4, 8, 16, 32])
def test_it_never_plays_in_the_bar_the_fill_is_composed_into(bars: int) -> None:
    assert bars - 1 not in answering_bars(bars)


def test_every_attack_is_on_an_eighth() -> None:
    """Stage A took the band off the sixteenths between a shuffle's eighths; the lead
    arrived after that and was never on them (`phase-6-findings.md` §1)."""
    for feel in Feel:
        section = a_section(feel=feel)
        slots = grid_slots(section)
        eighths = set(slots[::2])
        for note in play_lead(section, Random(7)).notes:
            assert nearest_slot(slots, note.start_beats) in eighths, feel


def test_it_plays_the_second_half_of_the_bar_and_not_the_downbeat() -> None:
    """A hook that lands on one is a hook nobody left room for.

    Read off the grid rather than off the beat, because humanisation moves an attack by
    up to a few milliseconds either way and a slot is what was written.
    """
    section = a_section()
    slots = grid_slots(section)
    for note in play_lead(section, Random(7)).notes:
        slot = slots.index(nearest_slot(slots, note.start_beats)) % SIXTEENTHS_PER_BAR
        assert slot >= SIXTEENTHS_PER_BAR // 2


# ------------------------------------------------------------------------ what it says


def test_every_note_is_a_tone_of_the_bar_it_is_in() -> None:
    """Which is how the dissonance budget is satisfied by construction, not by repair."""
    section = a_section()
    for note in play_lead(section, Random(7)).notes:
        chord = section.chart.at(int(note.start_beats // 4))
        tones = {degree_to_pitch(chord, degree, 0) % 12 for degree in (1, 3, 5)}
        assert note.pitch % 12 in tones


def test_it_stays_inside_the_lead_s_range() -> None:
    low, high = RANGES[Instrument.LEAD]
    for seed in range(20):
        for note in play_lead(a_section(), Random(seed)).notes:
            assert low <= note.pitch <= high


def test_it_sits_above_the_bass() -> None:
    assert RANGES[Instrument.LEAD][0] > RANGES[Instrument.BASS][1] - 1


def test_the_hook_comes_back() -> None:
    """One motif a section, played again on each answering bar. That is what makes it a
    hook rather than three phrases that never return."""
    section = a_section()
    part = play_lead(section, Random(7))
    by_bar: dict[int, list[float]] = {}
    for note in part.notes:
        bar = int(note.start_beats // 4)
        by_bar.setdefault(bar, []).append(round(note.start_beats % 4, 1))
    shapes = {tuple(sorted(starts)) for starts in by_bar.values()}
    assert len(by_bar) == 3
    assert len(shapes) == 1


def test_tension_buys_the_third_note() -> None:
    calm = play_lead(a_section(tension=0.2), Random(7))
    tense = play_lead(a_section(tension=0.7), Random(7))
    assert len(calm.notes) // 3 == len(QUIET[0])
    assert len(tense.notes) // 3 == len(BUSY[0])


def test_the_figure_lands_on_its_last_note() -> None:
    """It holds twice as long as the others, so the phrase resolves instead of stopping."""
    part = play_lead(a_section(), Random(7))
    first_bar = [note for note in part.notes if int(note.start_beats // 4) == 1]
    ordered = sorted(first_bar, key=lambda note: note.start_beats)
    assert ordered[-1].duration_beats > ordered[0].duration_beats


# --------------------------------------------------------------------- the shared contract


def test_it_is_reproducible_from_its_seed() -> None:
    section = a_section()
    assert play_lead(section, Random(7)) == play_lead(section, Random(7))


@pytest.mark.parametrize("feel", list(Feel))
@pytest.mark.parametrize("dyn", [4, 5])
def test_the_band_with_a_lead_needs_no_repairer(feel: Feel, dyn: int) -> None:
    assert validate(play_section(a_section(feel=feel, dyn=dyn), 7)) == ()
