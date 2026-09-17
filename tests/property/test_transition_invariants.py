"""What must stay true of the floor once a section hands over to the next.

`test_musical_invariants.py` says the band never needs the repairer. Composing an ending
over it takes notes away, moves velocities, lengthens hits and adds drums, and every one of
those could in principle break that. These say it does not — for any briefing, any seed,
any ending and anything that could follow — which is what lets the scheduler treat a
declined ending as an event worth logging rather than a path it expects to take.
"""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given
from hypothesis import strategies as st
from strategies import sections, seeds

from garagem.domain import BEATS_PER_BAR, Instrument, Section
from garagem.engines import Ending, compose, play_section, tail_bars
from garagem.theory import validate

endings = st.sampled_from(Ending)
followers = st.none() | sections


@given(section=sections, seed=seeds, ending=endings, into=followers)
def test_an_ending_never_needs_the_repairer(
    section: Section, seed: int, ending: Ending, into: Section | None
) -> None:
    assert validate(compose(play_section(section, seed), ending, into=into)) == ()


@given(section=sections, seed=seeds, ending=endings, into=followers)
def test_an_ending_never_invents_a_pitch(
    section: Section, seed: int, ending: Ending, into: Section | None
) -> None:
    """Harmony stays the groove's and the briefing's."""
    score = play_section(section, seed)
    composed = compose(score, ending, into=into)
    for instrument in (Instrument.BASS, Instrument.GUITAR, Instrument.KEYS):
        before = {note.pitch for note in score.part(instrument).notes}
        assert {note.pitch for note in composed.part(instrument).notes} <= before


@given(section=sections, seed=seeds, ending=endings, into=followers)
def test_an_ending_keeps_the_whole_band(
    section: Section, seed: int, ending: Ending, into: Section | None
) -> None:
    composed = compose(play_section(section, seed), ending, into=into)
    assert composed.instruments() == frozenset(Instrument)


@given(section=sections, seed=seeds, ending=endings, into=followers)
def test_an_ending_is_reproducible(
    section: Section, seed: int, ending: Ending, into: Section | None
) -> None:
    score = play_section(section, seed)
    assert compose(score, ending, into=into) == compose(score, ending, into=into)


@given(section=sections, seed=seeds, ending=endings, into=followers)
def test_no_ended_note_overlaps_the_next_attack_of_its_own_pitch(
    section: Section, seed: int, ending: Ending, into: Section | None
) -> None:
    """A lengthened hit is exactly how Live's silent truncation would come back."""
    for part in compose(play_section(section, seed), ending, into=into).parts:
        by_pitch: dict[int, list[tuple[float, float]]] = {}
        for note in part.notes:
            by_pitch.setdefault(note.pitch, []).append((note.start_beats, note.duration_beats))
        for spans in by_pitch.values():
            spans.sort()
            for (start, duration), (next_start, _) in pairwise(spans):
                assert start + duration <= next_start


@given(section=sections, seed=seeds, ending=endings, into=followers)
def test_an_ending_stays_inside_the_section(
    section: Section, seed: int, ending: Ending, into: Section | None
) -> None:
    """The next section's clip is a different clip. Nothing rung here may reach into it.

    The one exception is the song's last chord, which has no next section and rings into the
    tail its clip carries (`engines.tail_bars`, `phase-5-findings.md` §10).
    """
    score = play_section(section, seed)
    composed = compose(score, ending, into=into)
    room = tail_bars(ending) * BEATS_PER_BAR
    for before, after in zip(score.parts, composed.parts, strict=True):
        assert all(note.start_beats >= 0.0 for note in after.notes)
        assert all(note.start_beats < score.total_beats() for note in after.notes)
        assert after.last_beat() <= max(before.last_beat(), score.total_beats()) + room
