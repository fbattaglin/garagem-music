"""The fifth voice: when it speaks, where it speaks, and what it is allowed to say.

ADR-026 gives the band a lead so the songwriter has a track to write a riff on. The floor
plays one in the meantime (invariant 2), and everything worth pinning about it is a
restraint: it is silent most of the time, it answers rather than leads, its notes come out
of the chord, and it sits on the eighths Stage A put the rest of the band on.
"""

from __future__ import annotations

from random import Random

import pytest

from garagem.domain import (
    PITCH_CLASSES,
    SIXTEENTHS_PER_BAR,
    Chart,
    Chord,
    Feel,
    Instrument,
    Quality,
    Section,
)
from garagem.engines import SHAPES, diatonic, play_section
from garagem.engines.arranger import SOLO, SongBrief, arrange
from garagem.engines.lead import (
    BUSY,
    CHORD_STEPS,
    LAND_BEATS,
    LEAD_DYN,
    LEAD_OCTAVE,
    QUIET,
    RUNS,
    TOP_STEP,
    answering_bars,
)
from garagem.engines.lead import play as play_lead
from garagem.theory import (
    DEGREES,
    RANGES,
    SCALES,
    parse_chart,
    pitch_classes,
    pitch_of,
    scale_pitch,
    steps_of,
    validate,
)
from garagem.theory.validator import grid_slots, nearest_slot

PROGRESSION = parse_chart("| Em | C | G | D |")


def a_section(**extra: object) -> Section:
    """A bridge: the hook's section since ADR-028 gave verses and choruses a melody."""
    base: dict[str, object] = {
        "name": "bridge",
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
def test_it_says_nothing_under_a_quiet_bridge(dyn: int) -> None:
    assert play_lead(a_section(dyn=dyn), Random(7)).notes == ()


@pytest.mark.parametrize("dyn", [4, 5])
def test_the_hook_speaks_once_a_bridge_is_pushed_to_a_chorus_s_dynamic(dyn: int) -> None:
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


def test_the_knob_can_bring_the_hook_into_a_bridge() -> None:
    """The density knob moves `dyn` by up to two (ADR-021). That is the knob working."""
    quiet = a_section(dyn=2, tension=0.35)
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
        assert note.pitch % 12 in chord.pitch_classes()


@pytest.mark.parametrize("quality", list(Quality))
def test_a_chord_with_no_third_never_gets_one(quality: Quality) -> None:
    """A power chord has no third and a sus chord has none either, and `degree_to_pitch`
    answers for them out of the chord's implied scale — a note that can be in neither the
    chord nor the key. Found by the bake notation's round trip: 50% of one section's lead
    notes outside the key against a 5% budget.
    """
    chart = Chart(chords=(Chord(root=0, quality=quality),))
    section = a_section(key=0, scale="dorian", chart=chart, tension=0.0, dyn=5)
    allowed = chart.chords[0].pitch_classes()
    for seed in range(20):
        for note in play_lead(section, Random(seed)).notes:
            assert note.pitch % PITCH_CLASSES in allowed, quality


@pytest.mark.parametrize("quality", list(Quality))
def test_the_whole_band_stays_legal_under_a_chart_that_fights_its_key(quality: Quality) -> None:
    chart = Chart(chords=(Chord(root=0, quality=quality),))
    section = a_section(key=0, scale="dorian", chart=chart, tension=0.0, dyn=5)
    assert validate(play_section(section, 7)) == ()


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


# ------------------------------------------------------------------------------- the solo

SOLO_CHART = parse_chart("| Em | D | C | Bm |")


def a_solo(**extra: object) -> Section:
    """A solo section as the arranger writes one, over its own first chart."""
    return a_section(
        **{
            "name": SOLO,
            "dyn": SHAPES[SOLO].dyn,
            "tension": SHAPES[SOLO].tension,
            "chart": SOLO_CHART,
            **extra,
        }
    )


def bar_slots(section: Section, seed: int = 7) -> dict[int, list[int]]:
    """Which sixteenth of its own bar each note was written on, bar by bar.

    Off the grid rather than off the beat: humanisation moves an attack by a few milliseconds
    either way, and a note pulled that far before a bar line is still in the bar it was
    written in. `bars_played` divides by four and is fine for the hook, which never goes
    near a bar line — the solo lands exactly on one.
    """
    slots = grid_slots(section)
    played: dict[int, list[int]] = {}
    for note in play_lead(section, Random(seed)).notes:
        index = slots.index(nearest_slot(slots, note.start_beats))
        played.setdefault(index // SIXTEENTHS_PER_BAR, []).append(index % SIXTEENTHS_PER_BAR)
    return played


@pytest.mark.parametrize("feel", list(Feel))
def test_a_solo_plays_in_every_bar(feel: Feel) -> None:
    """The one thing that makes the section a solo rather than a bridge with a hook over it.

    ADR-027 gave the solo a section of its own so it would have the stage; a solo that rested
    every other bar would be the hook with a new name.
    """
    for seed in range(8):
        assert set(bar_slots(a_solo(feel=feel), seed)) == set(range(8)), (feel, seed)


def test_the_knobs_cannot_silence_a_solo() -> None:
    """The density knob may take the hook away — that is what it is for (ADR-021) — but a solo
    section with nothing in it is not a quieter section, it is an empty one. Invariant 2 says
    it has to sound with the network off, and that is not conditional on a knob."""
    for dyn in range(1, LEAD_DYN + 1):
        assert set(bar_slots(a_solo(dyn=dyn))) == set(range(8)), dyn


def test_a_solo_lands_on_the_downbeat_of_the_fill_bar_and_holds() -> None:
    """The last bar is the drummer's. The solo resolves into it and gets out of the way."""
    section = a_solo()
    assert bar_slots(section)[section.bars - 1] == [0]
    held = max(play_lead(section, Random(7)).notes, key=lambda note: note.start_beats)
    assert held.duration_beats == LAND_BEATS


def test_a_solo_says_something_and_says_it_again() -> None:
    """A call and an answer, alternating: bars 1 and 3 are the same phrase, and bar 2 is not.

    One run eight times is a riff; eight different runs are eight beginnings. The rhythm is
    what is compared, because the pitches cannot repeat — each bar re-roots on its own chord,
    which is what makes the repeat worth hearing.
    """
    played = bar_slots(a_solo())
    assert played[0] == played[2] == played[4]
    assert played[1] == played[3] == played[5]
    assert played[0] != played[1]


def test_every_attack_in_a_solo_is_on_an_eighth() -> None:
    """The rule Stage A of Phase 6 put the whole band under, and the solo is not exempt."""
    for feel in Feel:
        for slots in bar_slots(a_solo(feel=feel)).values():
            assert all(slot % 2 == 0 for slot in slots), feel


def test_a_solo_lands_on_a_chord_tone_at_every_bar_line() -> None:
    """Which is the whole legality argument, and it is by construction (ADR-027).

    A run opens and closes on 0, 2 or 4 steps above the bar's anchor, and the anchor is the
    chord's root as a step of the key — so over the diatonic chart the arranger writes, those
    are the root, the third and the fifth.
    """
    section = a_solo()
    slots = grid_slots(section)
    for note in play_lead(section, Random(7)).notes:
        index = slots.index(nearest_slot(slots, note.start_beats))
        if index % SIXTEENTHS_PER_BAR:
            continue
        chord = section.chart.at(index // SIXTEENTHS_PER_BAR)
        assert note.pitch % PITCH_CLASSES in chord.pitch_classes(), (index, note.pitch)


def test_every_run_opens_and_closes_on_a_chord_step() -> None:
    """The table is where the legality lives, so the table is what is held to it.

    Also: the last attack is no later than the third beat, so the note that holds through the
    end of the bar stops at the bar line instead of spilling over the next chord.
    """
    for run in RUNS:
        slots = [slot for slot, _ in run]
        assert run[0][1] in CHORD_STEPS
        assert run[-1][1] in CHORD_STEPS
        assert slots == sorted(set(slots))
        assert all(slot % 2 == 0 for slot in slots)
        assert slots[-1] <= SIXTEENTHS_PER_BAR - 4
        assert all(0 <= step <= TOP_STEP for _, step in run)


@pytest.mark.parametrize("scale", sorted(SCALES))
def test_a_solo_fits_the_lead_s_range_in_every_key_and_every_scale(scale: str) -> None:
    """The width argument `TOP_STEP` exists for, held to every scale this project knows.

    A solo is as wide as one bar's run plus the spread of the anchors across the key, and it
    is placed by whole octaves — so where an octave of the key's root falls inside the range
    decides whether it fits at all. At `TOP_STEP` 5 it did not, in some keys, and the floor
    raised `UnvoiceableError` instead of playing (`phase-7-findings.md` §2).
    """
    low, high = RANGES[Instrument.LEAD]
    for key in range(PITCH_CLASSES):
        chart = Chart(chords=(Chord(root=key, quality=Quality.MINOR),))
        for seed in range(6):
            section = a_solo(key=key, scale=scale, chart=chart)
            for note in play_lead(section, Random(seed)).notes:
                assert low <= note.pitch <= high, (scale, key, seed, note.pitch)


def test_the_widest_line_a_seven_note_scale_can_draw_leaves_an_octave_of_room() -> None:
    """`TOP_STEP` as arithmetic rather than as a sample, which is the only way it is honest.

    The solo is placed by whole octaves, so it fits only when *some* octave of the key's root
    leaves room both below the line and above it. That window is the range less the line's
    width, and a window narrower than twelve semitones can fall between two octaves — which is
    what happened at `TOP_STEP` 5: nineteen semitones wide, an eleven-semitone window, and no
    octave at all in a few keys. Twelve or more and no key can miss, whatever the seed.
    """
    low, high = RANGES[Instrument.LEAD]
    for scale in sorted(SCALES):
        steps = steps_of(scale)
        if len(steps) != DEGREES:
            continue
        widest = max(
            scale_pitch(0, scale, anchor + step, LEAD_OCTAVE)
            for anchor in range(len(steps))
            for step in range(TOP_STEP + 1)
        ) - pitch_of(0, LEAD_OCTAVE)
        assert (high - low) - widest + 1 >= PITCH_CLASSES, (scale, widest)


@pytest.mark.parametrize("scale", ["minor", "major", "dorian", "mixolydian"])
@pytest.mark.parametrize("key", [0, 5, 7, 11])
def test_a_solo_stays_in_its_key_in_every_key_and_mode(scale: str, key: int) -> None:
    """Not a chord tone everywhere — a solo that only played chord tones would be an
    arpeggio — but every note in the section's scale, which is what the dissonance budget
    actually counts (`theory/validator._dissonance_budget`)."""
    section = a_solo(key=key, scale=scale, chart=Chart(chords=(diatonic(key, scale, 1),)))
    allowed = pitch_classes(key, scale)
    for note in play_lead(section, Random(7)).notes:
        assert note.pitch % PITCH_CLASSES in allowed, (key, scale, note.pitch)


@pytest.mark.parametrize("quality", [Quality.POWER, Quality.SUS2, Quality.SUS4, Quality.DOM7])
def test_a_solo_over_a_chart_that_fights_its_key_stays_in_the_key(quality: Quality) -> None:
    """The trap `_in_the_chord` was written for, one level up: the chord's implied scale is
    not consulted at all, so it cannot drag the line out of the key."""
    section = a_solo(chart=Chart(chords=(Chord(root=4, quality=quality),)))
    allowed = pitch_classes(section.key, section.scale)
    for note in play_lead(section, Random(7)).notes:
        assert note.pitch % PITCH_CLASSES in allowed, (quality, note.pitch)


def test_a_solo_stays_inside_the_lead_s_range() -> None:
    low, high = RANGES[Instrument.LEAD]
    for feel in Feel:
        for seed in range(8):
            for note in play_lead(a_solo(feel=feel), Random(seed)).notes:
                assert low <= note.pitch <= high


@pytest.mark.parametrize("feel", list(Feel))
@pytest.mark.parametrize("scale", ["minor", "major"])
def test_the_band_needs_no_repairer_in_a_solo_section(feel: Feel, scale: str) -> None:
    """Invariant 2 for a whole section kind: it plays, and it plays legally, with no network."""
    chart = Chart(chords=tuple(diatonic(4, scale, degree) for degree in (1, 7, 6, 5)))
    assert validate(play_section(a_solo(feel=feel, scale=scale, chart=chart), 7)) == ()


def test_a_solo_is_reproducible_from_its_seed() -> None:
    section = a_solo()
    assert play_lead(section, Random(7)) == play_lead(section, Random(7))


def test_two_seeds_pick_different_pairs_of_runs() -> None:
    """Otherwise the table has four entries and the section only ever hears one."""
    rhythms = {
        tuple(tuple(slots) for slots in bar_slots(a_solo(), seed).values()) for seed in range(12)
    }
    assert len(rhythms) > 1


# ----------------------------------------------------------------------- the melody (ADR-028)

# Charts in their own key, as the arranger writes them: a chart that argues with its key gets
# the key's nearest note on a strong beat instead, as the solo does (`lead._anchor`).
SUNG_SECTIONS = [
    a_section(
        name=name,
        dyn=dyn,
        feel=feel,
        key=key,
        scale=scale,
        tune=tune,
        chart=Chart(chords=tuple(diatonic(key, scale, degree) for degree in (0, 5, 3, 4))),
    )
    for name, dyn in (("verse", 2), ("chorus", 4))
    for feel in Feel
    for key, scale in ((4, "minor"), (0, "major"), (9, "dorian"))
    for tune in (7, 23)
]


def strong_notes(section: Section, part_notes: tuple[object, ...]) -> list[tuple[int, int]]:
    """(bar, pitch) of every note on beat 1 or 3, read back through the grid."""
    slots = grid_slots(section)
    found: list[tuple[int, int]] = []
    for note in part_notes:
        slot = slots.index(nearest_slot(slots, note.start_beats))  # type: ignore[attr-defined]
        if slot % 8 == 0:
            found.append((slot // SIXTEENTHS_PER_BAR, note.pitch))  # type: ignore[attr-defined]
    return found


@pytest.mark.parametrize("dyn", [1, 2, 3, 4])
def test_a_verse_sings_whatever_its_dynamic(dyn: int) -> None:
    """The density knob can thin the band; it cannot take the tune out of the verse."""
    assert play_lead(a_section(name="verse", dyn=dyn, tune=7), Random(7)).notes


@pytest.mark.parametrize("section", SUNG_SECTIONS, ids=lambda s: f"{s.name}-{s.feel}-{s.scale}")
def test_a_sung_section_is_legal_by_construction(section: Section) -> None:
    score = play_section(section, 7)
    assert validate(score) == ()


@pytest.mark.parametrize("section", SUNG_SECTIONS, ids=lambda s: f"{s.name}-{s.feel}-{s.scale}")
def test_every_note_on_beat_one_or_three_is_a_tone_of_its_chord(section: Section) -> None:
    for bar, pitch in strong_notes(section, play_lead(section, Random(7)).notes):
        assert pitch % PITCH_CLASSES in section.chart.at(bar).pitch_classes()


@pytest.mark.parametrize("section", SUNG_SECTIONS, ids=lambda s: f"{s.name}-{s.feel}-{s.scale}")
def test_the_melody_lands_on_the_root_and_leaves_the_last_bar_to_the_fill(
    section: Section,
) -> None:
    notes = play_lead(section, Random(7)).notes
    last = section.bars - 1
    in_last = [note for note in notes if note.start_beats >= last * 4 - 0.05]
    assert len(in_last) == 1
    assert in_last[0].duration_beats == LAND_BEATS
    assert in_last[0].pitch % PITCH_CLASSES == section.chart.at(last).root


def test_every_verse_of_a_song_sings_the_same_rhythm_on_its_own_chords() -> None:
    first = a_section(name="verse", dyn=2, tune=7, chart=parse_chart("| Em | C | G | D |"))
    second = first.model_copy(update={"chart": parse_chart("| Am | F | C | G |")})
    one = play_lead(first, Random(1)).notes
    two = play_lead(second, Random(1)).notes
    assert [round(n.start_beats * 4) for n in one] == [round(n.start_beats * 4) for n in two]
    assert [n.pitch for n in one] != [n.pitch for n in two]


def test_two_songs_sing_two_tunes() -> None:
    one = play_lead(a_section(name="verse", dyn=2, tune=7), Random(1)).notes
    other = play_lead(a_section(name="verse", dyn=2, tune=8), Random(1)).notes
    assert [n.pitch for n in one] != [n.pitch for n in other]


def test_a_section_from_no_arranged_song_still_has_a_tune_of_its_own() -> None:
    """A briefing written by hand, or baked before ADR-028, carries no tune."""
    untuned = a_section(name="verse", dyn=2)
    assert play_lead(untuned, Random(1)) == play_lead(untuned, Random(1))
    assert play_lead(untuned, Random(1)).notes


def test_a_verse_is_sung_softer_than_a_chorus() -> None:
    verse = play_lead(a_section(name="verse", dyn=2, tune=7), Random(1)).notes
    chorus = play_lead(a_section(name="chorus", dyn=4, tune=7), Random(1)).notes
    assert max(n.velocity for n in verse) < min(n.velocity for n in chorus)


def test_the_arranger_gives_every_section_of_a_song_its_seed_as_the_tune() -> None:
    form = arrange(
        SongBrief(key=4, scale="minor", bpm=132.0, feel=Feel.STRAIGHT8, minimum_seconds=120),
        11,
    )
    assert {section.tune for section in form} == {11}
