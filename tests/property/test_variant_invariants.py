"""What must stay true of a bar cue's variant, for any briefing and any seed (ADR-022)."""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st
from strategies import sections, seeds

from garagem.domain import Instrument, Section
from garagem.engines import FillStyle, fill_bars, land_bars, play_section, stop_bars
from garagem.theory import validate

variants = st.sampled_from(
    [
        stop_bars,
        land_bars,
        *(lambda score, style=style: fill_bars(score, style) for style in FillStyle),
    ]
)


@given(section=sections, seed=seeds, variant=variants)
def test_a_variant_never_needs_the_repairer(section: Section, seed: int, variant: object) -> None:
    assert validate(variant(play_section(section, seed))) == ()  # type: ignore[operator]


@given(section=sections, seed=seeds, variant=variants)
def test_a_variant_never_invents_a_pitch(section: Section, seed: int, variant: object) -> None:
    score = play_section(section, seed)
    changed = variant(score)  # type: ignore[operator]
    for instrument in (Instrument.BASS, Instrument.GUITAR, Instrument.KEYS):
        before = {note.pitch for note in score.part(instrument).notes}
        assert {note.pitch for note in changed.part(instrument).notes} <= before


@given(section=sections, seed=seeds, variant=variants)
def test_no_variant_note_overlaps_the_next_attack_of_its_own_pitch(
    section: Section, seed: int, variant: object
) -> None:
    for part in variant(play_section(section, seed)).parts:  # type: ignore[operator]
        by_pitch: dict[int, list[tuple[float, float]]] = {}
        for note in part.notes:
            by_pitch.setdefault(note.pitch, []).append((note.start_beats, note.duration_beats))
        for spans in by_pitch.values():
            spans.sort()
            for (start, duration), (next_start, _) in pairwise(spans):
                assert start + duration <= next_start


@given(section=sections, seed=seeds, variant=variants)
def test_a_variant_stays_inside_its_section(section: Section, seed: int, variant: object) -> None:
    changed = variant(play_section(section, seed))  # type: ignore[operator]
    assert all(part.last_beat() <= section.total_beats() + 4.0 for part in changed.parts)
