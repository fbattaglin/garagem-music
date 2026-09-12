"""How a section hands over to the next, stated as what a listener would hear.

Each test names a sound — the snare rolls, the band lets go of the last beat, the chord
rings to the end — and checks it in the notes. None of them says whether it sounds good:
that is Fabiano's call at the gate (ADR-019), and these only make sure the thing he is
asked about is the thing that was built.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from garagem.domain import (
    SIXTEENTHS_PER_BAR,
    Feel,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
    beats_of,
)
from garagem.dsl import parse_section, realise
from garagem.engines import SongBrief, arrange, play_section, with_climax
from garagem.engines.arranger import BRIDGE, CHORUS, INTRO, OUTRO, VERSE
from garagem.engines.groove import fill_for
from garagem.engines.transitions import (
    LAST_BEAT_SLOT,
    ROLL,
    STOP_RING_BEATS,
    Ending,
    compose,
    endings_for,
)
from garagem.llm import EVENT_ADAPTER, StreamEvent
from garagem.theory import grid_slots, nearest_slot, parse_chart, validate
from garagem.theory.percussion import CRASH, HATS, KICK, SNARE

ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ("anthropic_section", "google_section", "google_section_flash")
SEED = 7
PITCHED = (Instrument.BASS, Instrument.GUITAR, Instrument.KEYS)


def a_section(name: str = VERSE, **extra: object) -> Section:
    base: dict[str, object] = {
        "name": name,
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


CHORUS_AFTER = a_section(CHORUS, dyn=4, tension=0.7)


def form_of(*names: str) -> tuple[Section, ...]:
    return tuple(a_section(name) for name in names)


def slot_of(section: Section, note: Note) -> int:
    """The sixteenth of the section a note was placed on, humanisation undone."""
    slots = grid_slots(section)
    return slots.index(nearest_slot(slots, note.start_beats))


def in_bar(section: Section, part: Part, bar: int, pitch: int | None = None) -> list[Note]:
    return [
        note
        for note in part.notes
        if slot_of(section, note) // SIXTEENTHS_PER_BAR == bar
        and (pitch is None or note.pitch == pitch)
    ]


def slots_in_bar(section: Section, part: Part, bar: int, pitch: int) -> set[int]:
    return {
        slot_of(section, note) % SIXTEENTHS_PER_BAR for note in in_bar(section, part, bar, pitch)
    }


def attacks(grid: tuple[bool, ...]) -> set[int]:
    return {slot for slot, hit in enumerate(grid) if hit}


def recorded(name: str) -> list[StreamEvent]:
    lines = (ROOT / "cassettes" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [EVENT_ADAPTER.validate_json(line) for line in lines[1:]]


# ------------------------------------------------------------------------ which ending


def test_the_last_section_ends_the_song() -> None:
    assert endings_for(form_of(INTRO, VERSE, OUTRO))[-1] is Ending.FINAL


def test_a_verse_builds_into_a_chorus() -> None:
    endings = endings_for(form_of(INTRO, VERSE, CHORUS, VERSE, CHORUS, OUTRO))
    assert endings[1] is Ending.BUILD


def test_a_bridge_stops_before_a_chorus() -> None:
    endings = endings_for(form_of(INTRO, VERSE, CHORUS, BRIDGE, CHORUS, VERSE, CHORUS, OUTRO))
    assert endings[3] is Ending.STOP


def test_the_step_into_the_last_chorus_is_a_stop_even_from_a_verse() -> None:
    """Saved for the peak: every other verse builds, this one stops."""
    endings = endings_for(form_of(INTRO, VERSE, CHORUS, VERSE, CHORUS, OUTRO))
    assert endings[3] is Ending.STOP


def test_a_song_with_one_chorus_builds_into_it() -> None:
    """There is no last chorus to save the stop for when there is only one."""
    endings = endings_for(form_of(INTRO, VERSE, CHORUS, OUTRO))
    assert endings[1] is Ending.BUILD


def test_everything_else_ends_on_the_fill_the_band_already_plays() -> None:
    endings = endings_for(form_of(INTRO, VERSE, CHORUS, VERSE, BRIDGE, CHORUS, OUTRO))
    assert endings[0] is Ending.FILL  # intro -> verse
    assert endings[2] is Ending.FILL  # chorus -> verse
    assert endings[3] is Ending.FILL  # verse -> bridge
    assert endings[5] is Ending.FILL  # chorus -> outro


@pytest.mark.parametrize("seed", range(12))
def test_every_arranged_song_gets_one_ending_per_section(seed: int) -> None:
    brief = SongBrief(key=4, scale="minor", bpm=132.0, feel=Feel.STRAIGHT8, minimum_seconds=180)
    form = with_climax(arrange(brief, seed))
    endings = endings_for(form)
    assert len(endings) == len(form)
    assert endings[-1] is Ending.FINAL
    assert Ending.FINAL not in endings[:-1]


def test_an_empty_song_has_no_endings() -> None:
    assert endings_for(()) == ()


# ------------------------------------------------------------------------------ identity


def test_a_fill_is_the_section_exactly_as_generated() -> None:
    score = play_section(a_section(), SEED)
    assert compose(score, Ending.FILL, into=CHORUS_AFTER) is score


@pytest.mark.parametrize("ending", list(Ending))
def test_a_one_bar_section_has_no_last_bar_to_change(ending: Ending) -> None:
    score = play_section(a_section(bars=1), SEED)
    assert compose(score, ending, into=CHORUS_AFTER) is score


@pytest.mark.parametrize("ending", list(Ending))
def test_the_same_score_and_ending_give_the_same_music(ending: Ending) -> None:
    score = play_section(a_section(), SEED)
    assert compose(score, ending, into=CHORUS_AFTER) == compose(score, ending, into=CHORUS_AFTER)


@pytest.mark.parametrize("ending", [Ending.BUILD, Ending.STOP, Ending.FINAL])
def test_the_bars_before_the_ending_are_untouched(ending: Ending) -> None:
    section = a_section()
    score = play_section(section, SEED)
    composed = compose(score, ending, into=CHORUS_AFTER)
    for before, after in zip(score.parts, composed.parts, strict=True):
        assert in_bar(section, before, 0) == in_bar(section, after, 0)
        assert in_bar(section, before, 5) == in_bar(section, after, 5)


# --------------------------------------------------------------------------------- build


def build_of(section: Section) -> tuple[SectionScore, SectionScore]:
    score = play_section(section, SEED)
    return score, compose(score, Ending.BUILD, into=CHORUS_AFTER)


def test_the_snare_rolls_over_the_last_two_bars_of_an_eight_bar_section() -> None:
    section = a_section()
    _, built = build_of(section)
    drums = built.part(Instrument.DRUMS)
    assert slots_in_bar(section, drums, 6, SNARE) == attacks(ROLL[0])
    assert slots_in_bar(section, drums, 7, SNARE) == attacks(ROLL[1])


def test_a_short_section_rolls_only_over_its_last_bar() -> None:
    section = a_section(bars=4, chart=parse_chart("| Em | C | G | D |"))
    score, built = build_of(section)
    assert in_bar(section, built.part(Instrument.DRUMS), 2) == in_bar(
        section, score.part(Instrument.DRUMS), 2
    )
    assert slots_in_bar(section, built.part(Instrument.DRUMS), 3, SNARE) == attacks(ROLL[1])


def test_the_hats_drop_out_while_the_snare_rolls() -> None:
    section = a_section()
    _, built = build_of(section)
    drums = built.part(Instrument.DRUMS)
    assert not any(note.pitch in HATS for bar in (6, 7) for note in in_bar(section, drums, bar))


def test_the_kick_keeps_the_groove_through_the_build() -> None:
    section = a_section()
    score, built = build_of(section)
    before = score.part(Instrument.DRUMS)
    after = built.part(Instrument.DRUMS)
    for bar in (6, 7):
        assert slots_in_bar(section, after, bar, KICK) == slots_in_bar(section, before, bar, KICK)


def test_the_band_lets_go_of_the_final_beat_so_the_roll_is_alone() -> None:
    section = a_section()
    _, built = build_of(section)
    last_beat = beats_of(7 * SIXTEENTHS_PER_BAR + LAST_BEAT_SLOT, section.feel)
    for instrument in PITCHED:
        part = built.part(instrument)
        assert part.notes
        assert all(note.start_beats + note.duration_beats <= last_beat for note in part.notes)


def test_the_build_dips_under_the_groove_and_rises_above_it() -> None:
    """Heard as a rise only if it starts lower than what came before it."""
    section = a_section()
    score, built = build_of(section)
    groove = score.part(Instrument.GUITAR)
    guitar = built.part(Instrument.GUITAR)

    def loudness(part: Part, bar: int) -> float:
        notes = in_bar(section, part, bar)
        return sum(note.velocity for note in notes) / len(notes)

    assert loudness(guitar, 6) < loudness(groove, 5)
    assert loudness(guitar, 7) > loudness(guitar, 6)


# ---------------------------------------------------------------------------------- stop


def stop_of(section: Section, into: Section | None = CHORUS_AFTER) -> SectionScore:
    return compose(play_section(section, SEED), Ending.STOP, into=into)


def test_at_a_stop_the_band_plays_only_the_downbeat_of_the_last_bar() -> None:
    section = a_section(dyn=3, tension=0.55)
    stopped = stop_of(section)
    for instrument in PITCHED:
        notes = in_bar(section, stopped.part(instrument), 7)
        assert notes
        assert {slot_of(section, note) % SIXTEENTHS_PER_BAR for note in notes} == {0}


def test_the_stop_hit_rings_and_then_leaves_a_silence() -> None:
    section = a_section(dyn=3, tension=0.55)
    stopped = stop_of(section)
    for instrument in PITCHED:
        for note in in_bar(section, stopped.part(instrument), 7):
            assert note.duration_beats == STOP_RING_BEATS


def test_the_drums_hit_the_stop_with_a_crash() -> None:
    section = a_section(dyn=3, tension=0.55)
    drums = stop_of(section).part(Instrument.DRUMS)
    assert 0 in slots_in_bar(section, drums, 7, CRASH)
    assert not any(note.pitch in HATS for note in in_bar(section, drums, 7))


def test_the_drummer_picks_up_with_the_last_beat_of_the_fill_the_next_section_wants() -> None:
    section = a_section(dyn=3, tension=0.55)
    drums = stop_of(section).part(Instrument.DRUMS)
    wanted = {slot for slot in attacks(fill_for(CHORUS_AFTER.tension)) if slot >= LAST_BEAT_SLOT}
    assert wanted
    assert slots_in_bar(section, drums, 7, SNARE) - {0} == wanted


def test_between_the_hit_and_the_pickup_nothing_plays() -> None:
    section = a_section(dyn=3, tension=0.55)
    stopped = stop_of(section)
    for part in stopped.parts:
        for note in in_bar(section, part, 7):
            assert slot_of(section, note) % SIXTEENTHS_PER_BAR in {0} | set(
                range(LAST_BEAT_SLOT, SIXTEENTHS_PER_BAR)
            )


def test_a_stop_with_nothing_after_it_has_no_pickup() -> None:
    section = a_section(dyn=3, tension=0.55)
    drums = stop_of(section, into=None).part(Instrument.DRUMS)
    assert slots_in_bar(section, drums, 7, SNARE) <= {0}


# --------------------------------------------------------------------------------- final


def final_of(section: Section) -> SectionScore:
    return compose(play_section(section, SEED), Ending.FINAL)


def test_the_last_chord_rings_to_the_end_of_the_song() -> None:
    section = a_section(OUTRO, bars=4, chart=parse_chart("| Em | C | Em | Em |"))
    ended = final_of(section)
    end = section.total_beats()
    for instrument in PITCHED:
        notes = in_bar(section, ended.part(instrument), 3)
        assert notes
        assert all(end - 0.05 < note.start_beats + note.duration_beats <= end for note in notes)


def test_the_song_ends_on_a_kick_and_a_crash_and_nothing_after() -> None:
    section = a_section(OUTRO, bars=4, chart=parse_chart("| Em | C | Em | Em |"))
    drums = final_of(section).part(Instrument.DRUMS)
    last = in_bar(section, drums, 3)
    assert {note.pitch for note in last} <= {KICK, SNARE, CRASH}
    assert {slot_of(section, note) % SIXTEENTHS_PER_BAR for note in last} == {0}
    assert CRASH in {note.pitch for note in last}


# ------------------------------------------------------------------------ any source


@pytest.mark.parametrize("ending", list(Ending))
@pytest.mark.parametrize("name", CASSETTES)
def test_every_ending_composes_validly_over_a_real_models_section(
    name: str, ending: Ending
) -> None:
    """The point of composing over a finished score: the model's groove gets the same form."""
    section = a_section(dyn=3, tension=0.4)
    score = realise(parse_section(recorded(name), section), SEED)
    assert validate(compose(score, ending, into=CHORUS_AFTER)) == ()


@pytest.mark.parametrize("ending", [Ending.BUILD, Ending.STOP, Ending.FINAL])
def test_an_ending_never_invents_a_pitch(ending: Ending) -> None:
    score = play_section(a_section(), SEED)
    composed = compose(score, ending, into=CHORUS_AFTER)
    for instrument in PITCHED:
        before = {note.pitch for note in score.part(instrument).notes}
        after = {note.pitch for note in composed.part(instrument).notes}
        assert after <= before
