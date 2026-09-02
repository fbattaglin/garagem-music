"""Parsed DSL to notes, against the same `theory/` the engines use.

The point of this module is that it needed no new musical knowledge: `degree_to_pitch`,
`voice`, `fit_to_range` and `voice_lead` were already there because the engines needed
them, and a model's part needs exactly the same ones. These tests check that the reuse is
real — the pitches, the ranges and the release gap all come out the way they do for a
generated part.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest

from garagem.domain import (
    SIXTEENTHS_PER_BAR,
    Feel,
    Grid,
    Instrument,
    Part,
    Section,
    beats_of,
    render_grid,
)
from garagem.dsl import ParsedSection, parse_section, realise
from garagem.engines import MAX_TIMING_BEATS
from garagem.engines.groove import fill_for, groove_for
from garagem.llm import EVENT_ADAPTER, StreamEvent
from garagem.theory import RANGES, parse_chart, validate
from garagem.theory.percussion import CLOSED_HAT, CRASH, GHOST_VELOCITY, KICK, SNARE

ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ("anthropic_section", "google_section", "google_section_flash")


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
        "chart": parse_chart("| Em | Em | C | D | Em | Em | C | B7 |"),
    }
    return Section.model_validate(base | extra)


def parsed_from(dsl: str, section: Section | None = None) -> ParsedSection:
    section = section or a_section()
    body = json.dumps({"dsl": dsl})
    from garagem.llm import StreamDone, ToolInputDelta, ToolUseStart

    events: list[StreamEvent] = [
        ToolUseStart(id="t", name="write_section"),
        ToolInputDelta(fragment=body),
        StreamDone(stop="tool_use"),
    ]
    return parse_section(events, section)


def recorded(name: str) -> list[StreamEvent]:
    lines = (ROOT / "cassettes" / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [EVENT_ADAPTER.validate_json(line) for line in lines[1:]]


def slots(
    part: Part, bar: int, pitch: int | None = None, feel: Feel = Feel.STRAIGHT8
) -> tuple[int, ...]:
    """Which sixteenths of `bar` the part attacks, read back through humanisation.

    Inverted through `beats_of` rather than by dividing, because **a swung feel is not
    linear in time**: under shuffle, slot 2 sounds at beat 0.667, and `round(0.667 * 4)`
    calls it slot 3. A first version divided, and every shuffle assertion here was quietly
    measuring the wrong slot. Pass the section's own feel.

    The humaniser moves a note by at most `MAX_TIMING_BEATS` — 0.02 beats — so the nearest
    grid position is unambiguous. Deduplicated, because a chord is several notes on one
    slot.
    """
    grid = [beats_of(bar * SIXTEENTHS_PER_BAR + slot, feel) for slot in range(SIXTEENTHS_PER_BAR)]
    limit = beats_of((bar + 1) * SIXTEENTHS_PER_BAR, feel)
    found: set[int] = set()
    for note in part.notes:
        if pitch is not None and note.pitch != pitch:
            continue
        if not grid[0] - 0.1 <= note.start_beats < limit - 0.1:
            continue
        at = note.start_beats
        nearest = min(range(SIXTEENTHS_PER_BAR), key=lambda slot: abs(grid[slot] - at))
        found.add(nearest)
    return tuple(sorted(found))


def attacks_of(grid: Grid) -> tuple[int, ...]:
    return tuple(index for index, attack in enumerate(grid) if attack)


# --------------------------------------------------------------------------------- drums


def test_a_drum_line_becomes_notes_on_the_general_midi_map() -> None:
    parsed = parsed_from("DRM K:x...............\nS:....x...........\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    # The crash is the arrangement's, not the line's. See `test_the_section_opens_…`.
    assert {note.pitch for note in part.notes} == {KICK, CRASH}


def test_every_drum_voice_reaches_its_own_pitch() -> None:
    parsed = parsed_from(
        "DRM K:x............... S:....x........... H:x.x.x.x.x.x.x.x.\n", a_section(bars=1)
    )
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert {note.pitch for note in part.notes} == {KICK, SNARE, CLOSED_HAT, CRASH}


def test_one_line_fills_every_bar_of_the_section() -> None:
    parsed = parsed_from("DRM K:x...............\n", a_section(bars=4))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert [slots(part, bar, KICK) for bar in range(4)] == [(0,), (0,), (0,), (0,)]


# ----------------------------------------------------------------------- drums: the form
#
# The model writes the groove and the arrangement decides where the bars differ. Measured
# over 85 sections (`phase-3-findings.md` §11), the model writes one bar-level line
# whatever the prompt asks, so without this the realised section is a static loop — which
# is what the blind A/B was actually measuring when it lost nine of eleven.


def test_the_section_opens_with_a_crash_the_model_never_wrote() -> None:
    parsed = parsed_from("DRM K:x...............\n", a_section(bars=4))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert [slots(part, bar, CRASH) for bar in range(4)] == [(0,), (), (), ()]


def test_a_crash_the_model_wrote_does_not_repeat_through_the_section() -> None:
    """`_for_bar` repeats one line across every bar; a crash must not repeat with it."""
    parsed = parsed_from("DRM K:x............... C:x...............\n", a_section(bars=4))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert sum(note.pitch == CRASH for note in part.notes) == 1


def test_the_last_bar_is_a_fill_and_not_the_models_snare() -> None:
    parsed = parsed_from(
        "DRM K:x............... S:....x...........\n", a_section(bars=4, tension=0.4)
    )
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert slots(part, 0, SNARE) == (4,)
    assert slots(part, 3, SNARE) == attacks_of(fill_for(0.4))


def test_the_fill_keeps_the_models_kick_and_silences_the_hat() -> None:
    """What `engines/drums.py` does, and what a drummer does: the kick plays through."""
    parsed = parsed_from("DRM K:x.......x....... H:x.x.x.x.x.x.x.x.\n", a_section(bars=2))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert slots(part, 1, KICK) == (0, 8)
    assert slots(part, 1, CLOSED_HAT) == ()
    assert slots(part, 0, CLOSED_HAT) != ()


def test_a_one_bar_section_has_no_last_bar_to_fill() -> None:
    """It *is* the section — a fill would be the whole of it. The engine's own guard."""
    parsed = parsed_from("DRM S:....x...........\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert slots(part, 0, SNARE) == (4,)


def test_more_tension_gives_a_denser_fill() -> None:
    dsl = "DRM K:x...............\n"
    calm = realise(parsed_from(dsl, a_section(bars=4, tension=0.1)), 7).part(Instrument.DRUMS)
    pushed = realise(parsed_from(dsl, a_section(bars=4, tension=0.9)), 7).part(Instrument.DRUMS)
    assert len(slots(pushed, 3, SNARE)) > len(slots(calm, 3, SNARE))


def test_the_arrangement_touches_the_drums_and_nothing_else() -> None:
    """Bass varies with `tension` but not with bar position; guitar and keys do neither."""
    parsed = parsed_from(
        "BAS deg=1 oct=2 rhy:x.......x.......\nGTR voi=pow rhy:x...............\n",
        a_section(bars=4),
    )
    score = realise(parsed, 7)
    assert [slots(score.part(Instrument.BASS), bar) for bar in range(4)] == [(0, 8)] * 4
    assert [slots(score.part(Instrument.GUITAR), bar) for bar in range(4)] == [(0,)] * 4


# ---------------------------------------------------------------------------------- bass


def test_degree_one_in_octave_two_under_em_is_e2() -> None:
    parsed = parsed_from("BAS deg=1 oct=2 rhy:x...............\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.BASS)
    assert part.notes[0].pitch == 40


def test_the_degree_follows_the_chart_bar_by_bar() -> None:
    """Bar 3 of the briefing is C, so degree 1 there is C and not E."""
    parsed = parsed_from("BAS deg=1 oct=2 rhy:x...............\n", a_section(bars=4))
    part = realise(parsed, 7).part(Instrument.BASS)
    assert [note.pitch % 12 for note in part.notes] == [4, 4, 0, 2]


def test_ghost_positions_become_ghost_velocities() -> None:
    parsed = parsed_from("BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x. ghost=3\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.BASS)
    ghosts = [note for note in part.notes if note.velocity < GHOST_VELOCITY]
    assert len(ghosts) == 1


@pytest.mark.parametrize("octave", [0, 1, 2, 5, 8])
def test_every_bass_note_is_pulled_inside_the_instrument(octave: int) -> None:
    """A model asking for octave 8 gets the nearest one the bass can actually play."""
    low, high = RANGES[Instrument.BASS]
    parsed = parsed_from(f"BAS deg=1 oct={octave} rhy:x...............\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.BASS)
    assert all(low <= note.pitch <= high for note in part.notes)


# ------------------------------------------------------------------------ guitar and keys


def test_a_power_chord_has_two_notes_in_the_guitars_range() -> None:
    low, high = RANGES[Instrument.GUITAR]
    parsed = parsed_from("GTR voi=pow rhy:x...............\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.GUITAR)
    assert len(part.notes) == 2
    assert all(low <= note.pitch <= high for note in part.notes)


def test_a_palm_mute_is_a_short_note() -> None:
    ringing = parsed_from("GTR voi=pow rhy:x............... palm=off\n", a_section(bars=1))
    muted = parsed_from("GTR voi=pow rhy:x............... palm=on\n", a_section(bars=1))
    long = realise(ringing, 7).part(Instrument.GUITAR).notes[0].duration_beats
    short = realise(muted, 7).part(Instrument.GUITAR).notes[0].duration_beats
    assert short < long


def test_an_accent_is_louder() -> None:
    plain = parsed_from("GTR voi=pow rhy:x.x.............\n", a_section(bars=1))
    accented = parsed_from("GTR voi=pow rhy:x.x............. acc=3\n", a_section(bars=1))
    quiet = max(n.velocity for n in realise(plain, 7).part(Instrument.GUITAR).notes)
    loud = max(n.velocity for n in realise(accented, 7).part(Instrument.GUITAR).notes)
    assert loud > quiet


def test_the_keys_never_go_below_the_bass_ceiling() -> None:
    """Two instruments in one octave is mud, exactly as in `engines/keys.py`."""
    parsed = parsed_from("KEY voi=triad rhy:x............... reg=low\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.KEYS)
    assert all(note.pitch > RANGES[Instrument.BASS][1] for note in part.notes)


def test_voice_leading_runs_across_chord_changes() -> None:
    """Otherwise four chords sound like four chords."""
    parsed = parsed_from("GTR voi=triad rhy:x...............\n", a_section(bars=4))
    part = realise(parsed, 7).part(Instrument.GUITAR)
    downbeats = [
        sorted(n.pitch for n in part.notes if abs(n.start_beats - bar * 4) < 0.1)
        for bar in range(4)
    ]
    moved = sum(
        abs(a - b)
        for before, after in pairwise(downbeats)
        for a, b in zip(before, after, strict=True)
    )
    assert moved <= 3 * 12


# ------------------------------------------------------------------------------ the whole


def test_only_the_instruments_that_arrived_are_present() -> None:
    """The caller fills the rest from the deterministic engine. That is P2."""
    parsed = parsed_from("DRM K:x...............\n", a_section(bars=1))
    score = realise(parsed, 7)
    assert score.instruments() == {Instrument.DRUMS}


def test_the_score_carries_the_seed_it_was_given() -> None:
    parsed = parsed_from("DRM K:x...............\n", a_section(bars=1))
    assert realise(parsed, 1234).seed == 1234


def test_the_same_parse_and_seed_give_an_identical_score() -> None:
    parsed = parsed_from("DRM K:x..x..x...x..x..\nBAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x.\n")
    assert realise(parsed, 7) == realise(parsed, 7)


def test_different_seeds_differ() -> None:
    parsed = parsed_from("DRM K:x..x..x...x..x..\n")
    assert realise(parsed, 7) != realise(parsed, 8)


def test_the_release_gap_is_applied_to_a_models_part_too() -> None:
    """Live truncates an overlapping note and the write-then-confirm then fails."""
    parsed = parsed_from("KEY voi=triad rhy:x.......x.......\n", a_section(bars=2))
    part = realise(parsed, 7).part(Instrument.KEYS)
    by_pitch: dict[int, list[tuple[float, float]]] = {}
    for note in part.notes:
        by_pitch.setdefault(note.pitch, []).append((note.start_beats, note.duration_beats))
    for spans in by_pitch.values():
        spans.sort()
        for (start, length), (next_start, _) in pairwise(spans):
            assert start + length <= next_start


def test_humanisation_moved_the_notes_but_not_far() -> None:
    parsed = parsed_from("DRM K:x...x...x...x...\n", a_section(bars=1))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    starts = [note.start_beats for note in part.notes]
    assert starts != [0.0, 1.0, 2.0, 3.0]
    assert all(abs(start - round(start)) <= MAX_TIMING_BEATS for start in starts)


# --------------------------------------------------------------------- the real cassettes


@pytest.mark.parametrize("name", CASSETTES)
def test_every_recorded_response_realises_into_a_valid_score(name: str) -> None:
    """Three real models, replayed with no network, straight through to notes."""
    parsed = parse_section(recorded(name), a_section())
    score = realise(parsed, 7)
    assert validate(score) == ()


def test_the_anthropic_cassette_realises_all_four_parts() -> None:
    parsed = parse_section(recorded("anthropic_section"), a_section())
    score = realise(parsed, 7)
    assert score.instruments() == frozenset(Instrument)
    assert all(part.notes for part in score.parts)


# ------------------------------------------------- drums: the density the briefing asked


def test_a_sparse_hat_is_lifted_where_the_engine_would_play_sixteenths() -> None:
    """straight8 at dyn=4: `groove_for` plays 16 hat hits and the model writes 8."""
    parsed = parsed_from("DRM H:x.x.x.x.x.x.x.x.\n", a_section(bars=1, dyn=4, feel=Feel.STRAIGHT8))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert len(slots(part, 0, CLOSED_HAT)) == 16


def test_a_swung_hat_is_left_alone_however_loud_the_section() -> None:
    """shuffle stays at eighths even at dyn=5 — sixteenths there end the shuffle.

    The rule that broke on this: `dyn >= 4` is right for straight8 and wrong for every
    other feel. The threshold belongs to `groove_for`, which already knows it.
    """
    parsed = parsed_from("DRM H:x.x.x.x.x.x.x.x.\n", a_section(bars=1, dyn=5, feel=Feel.SHUFFLE))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert slots(part, 0, CLOSED_HAT, Feel.SHUFFLE) == (0, 2, 4, 6, 8, 10, 12, 14)


def test_a_quiet_section_keeps_the_hat_the_model_wrote() -> None:
    parsed = parsed_from("DRM H:x.x.x.x.x.x.x.x.\n", a_section(bars=1, dyn=2, feel=Feel.STRAIGHT8))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert len(slots(part, 0, CLOSED_HAT)) == 8


def test_the_lift_never_goes_denser_than_the_engine_itself_would() -> None:
    """One doubling at a time. A quarter-note hat under a sixteenth floor becomes eighths."""
    parsed = parsed_from("DRM H:x...x...x...x...\n", a_section(bars=1, dyn=4))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert slots(part, 0, CLOSED_HAT) == (0, 2, 4, 6, 8, 10, 12, 14)


def test_the_lift_keeps_the_attacks_the_model_wrote() -> None:
    """Doubling, not overwriting: every original hit survives, the midpoints are added."""
    parsed = parsed_from("DRM H:x.x.x.x.x.x.x.x.\n", a_section(bars=1, dyn=4))
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert set(range(0, 16, 2)) <= set(slots(part, 0, CLOSED_HAT))


def test_the_lift_touches_neither_kick_nor_snare() -> None:
    """The groove is the model's. Only the subdivision is the arrangement's."""
    parsed = parsed_from(
        "DRM K:x...x...x...x... S:....x.......x... H:x.x.x.x.x.x.x.x.\n",
        a_section(bars=1, dyn=5),
    )
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert slots(part, 0, KICK) == (0, 4, 8, 12)
    assert slots(part, 0, SNARE) == (4, 12)


@pytest.mark.parametrize("feel", list(Feel))
@pytest.mark.parametrize("dyn", [1, 2, 3, 4, 5])
def test_an_engine_section_is_never_lifted(feel: Feel, dyn: int) -> None:
    """The fixed point, stated directly rather than only through the round trip.

    The engine's own hat *is* `groove_for`'s hat, so there is nothing finer to lift it to
    — in every feel and at every dynamic. If this ever fails, the composition has started
    disagreeing with the music a human approved by ear in Phase 2.
    """
    section = a_section(bars=1, dyn=dyn, feel=feel)
    engine_hat = groove_for(feel, dyn, section.bpm)
    parsed = parsed_from(f"DRM H:{render_grid(engine_hat.hat)}\n", section)
    part = realise(parsed, 7).part(Instrument.DRUMS)
    assert slots(part, 0, CLOSED_HAT, feel) == attacks_of(engine_hat.hat)
