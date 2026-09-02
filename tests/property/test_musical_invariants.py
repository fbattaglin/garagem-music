"""What must be true of every section the deterministic floor can produce.

The example-based tests pick briefings a person thought of. These pick briefings nobody
thought of — every feel, every dynamic, tension anywhere in 0..1, sixteen keys' worth of
charts including chords that have nothing to do with the section's key, which is exactly
what a model will hand us in Phase 3.

The strongest claim in the file is the second one: for any briefing and any seed, the
band's output validates with no violations at all. That is P2 stated as a property — the
floor is not "usually" valid, and it never needs the repairer to become so.
"""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given
from strategies import sections, seeds

from garagem.domain import Instrument, Section, SectionScore
from garagem.dsl import serialize_score, serialize_section
from garagem.engines import coherence_of, play_section
from garagem.theory import RANGES, repair, validate


def notes_in(score: SectionScore) -> int:
    return sum(len(part.notes) for part in score.parts)


@given(section=sections, seed=seeds)
def test_every_note_is_inside_its_instrument(section: Section, seed: int) -> None:
    score = play_section(section, seed)
    for part in score.parts:
        limits = RANGES.get(part.instrument)
        if limits is None:
            continue
        low, high = limits
        assert all(low <= note.pitch <= high for note in part.notes)


@given(section=sections, seed=seeds)
def test_the_band_never_needs_the_repairer(section: Section, seed: int) -> None:
    """P2 as a property: the floor is valid, not usually valid."""
    assert validate(play_section(section, seed)) == ()


@given(section=sections, seed=seeds)
def test_generation_is_reproducible(section: Section, seed: int) -> None:
    assert play_section(section, seed) == play_section(section, seed)


@given(section=sections, seed=seeds)
def test_all_four_instruments_are_always_present(section: Section, seed: int) -> None:
    assert play_section(section, seed).instruments() == frozenset(Instrument)


@given(section=sections, seed=seeds)
def test_repair_is_idempotent(section: Section, seed: int) -> None:
    once, _ = repair(play_section(section, seed))
    twice, _ = repair(once)
    assert twice == once


@given(section=sections, seed=seeds)
def test_repair_never_loses_a_note(section: Section, seed: int) -> None:
    score = play_section(section, seed)
    repaired, _ = repair(score)
    assert notes_in(repaired) >= notes_in(score)


@given(section=sections, seed=seeds)
def test_no_note_overlaps_the_next_attack_of_its_own_pitch(section: Section, seed: int) -> None:
    """Live truncates such a note silently, and the write-then-confirm then fails.

    Found the first time a section reached a real Set (`phase-2-findings.md` §1). Stated
    here so it cannot come back without the offline suite noticing — Live is an expensive
    place to discover it twice.
    """
    for part in play_section(section, seed).parts:
        by_pitch: dict[int, list[tuple[float, float]]] = {}
        for note in part.notes:
            by_pitch.setdefault(note.pitch, []).append((note.start_beats, note.duration_beats))
        for spans in by_pitch.values():
            spans.sort()
            for (start, duration), (next_start, _) in pairwise(spans):
                assert start + duration <= next_start


@given(section=sections, seed=seeds)
def test_no_note_starts_before_the_section_does(section: Section, seed: int) -> None:
    score = play_section(section, seed)
    assert all(note.start_beats >= 0.0 for part in score.parts for note in part.notes)


@given(section=sections, seed=seeds)
def test_no_note_outlasts_the_section_by_more_than_a_bar(section: Section, seed: int) -> None:
    """A clip is the section's length; a note far past the end would be cut mid-sound."""
    score = play_section(section, seed)
    assert all(part.last_beat() <= score.total_beats() + 4.0 for part in score.parts)


@given(section=sections, seed=seeds)
def test_the_dsl_grammar_holds_for_any_section(section: Section, seed: int) -> None:
    """Every line is a tag the skill defines, and every grid is sixteen slots."""
    text = serialize_section(play_section(section, seed))
    lines = text.strip().splitlines()
    assert lines[0].startswith("SEC ")
    assert lines[1].startswith("CHD | ")
    tags = [line.split()[0] for line in lines[2:]]
    assert set(tags) <= {"DRM", "BAS", "GTR", "KEY"}
    assert tags == sorted(tags, key=["DRM", "BAS", "GTR", "KEY"].index)
    for line in lines[2:]:
        for field in line.split():
            if ":" in field:
                assert len(field.split(":", 1)[1]) == 16


@given(section=sections, seed=seeds)
def test_serialisation_is_stable(section: Section, seed: int) -> None:
    first = play_section(section, seed)
    second = play_section(section, seed)
    assert serialize_section(first) == serialize_section(second)
    assert serialize_score(first) == serialize_score(second)


@given(section=sections, seed=seeds)
def test_the_floor_is_never_messy(section: Section, seed: int) -> None:
    """The calibration claim, as a property rather than at four points.

    The engines are the only music this project has approved by ear, so they define the
    clean end of the scale. A coherence metric that can score them as messy is measuring
    something other than mess — which is how the first `bass_kick_alignment` was caught,
    at 0.33 on a halftime bridge.
    """
    coherence = coherence_of(play_section(section, seed))
    assert coherence.messiness < 0.1
    assert coherence.harmonic_conformance > 0.9
    assert coherence.register_spread > 0.8
