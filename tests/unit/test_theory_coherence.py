"""Coherence metrics: what each one says, and what it deliberately does not say.

The load-bearing test in this file is `test_the_floor_is_clean_by_this_measure`. The
deterministic engines are the only musical reference this project has approved by ear
(Phase 2), so a metric that scores them as messy is measuring something else — which is
how the first version of `bass_kick_alignment` was caught and rewritten.
"""

from __future__ import annotations

import pytest

from garagem.domain import Feel, Instrument, Note, Part, Section, SectionScore
from garagem.engines import SongBrief, arrange, coherence_of, play_section, reference_attacks
from garagem.theory import (
    MESSINESS_PARTS,
    bass_kick_alignment,
    density_against_tension,
    harmonic_conformance,
    kit_collision,
    parse_chart,
    register_spread,
)

SECTION = Section(
    name="verse",
    bars=2,
    key=4,
    scale="minor",
    feel=Feel.STRAIGHT8,
    bpm=132.0,
    dyn=3,
    tension=0.4,
    chart=parse_chart("| Em | C |"),
)


def scored(**parts: tuple[Note, ...]) -> SectionScore:
    named = {
        "drums": Instrument.DRUMS,
        "bass": Instrument.BASS,
        "guitar": Instrument.GUITAR,
        "keys": Instrument.KEYS,
    }
    return SectionScore(
        section=SECTION,
        seed=7,
        parts=tuple(
            Part(instrument=named[name], notes=notes)
            for name, notes in parts.items()
            if notes
        ),
    )


def at(*beats: float, pitch: int) -> tuple[Note, ...]:
    return tuple(Note(pitch=pitch, start_beats=b, duration_beats=0.25) for b in beats)


# ------------------------------------------------------------------ harmonic conformance


def test_notes_in_the_key_all_conform() -> None:
    # E minor: E G A B D.
    assert harmonic_conformance(scored(bass=at(0.0, 1.0, pitch=40))) == 1.0


def test_a_note_outside_key_and_chart_is_counted() -> None:
    inside = at(0.0, 1.0, 2.0, pitch=40)  # E
    outside = at(3.0, pitch=41)  # F, in neither E minor nor Em/C
    assert harmonic_conformance(scored(bass=inside + outside)) == 0.75


def test_a_chord_tone_outside_the_scale_still_conforms() -> None:
    """A borrowed dominant is a decision, not mess — `chart_pitch_classes` exists for it."""
    section = SECTION.model_copy(update={"chart": parse_chart("| Em | B7 |")})
    score = SectionScore(
        section=section,
        seed=7,
        # D# is B7's third and is not in E natural minor.
        parts=(Part(instrument=Instrument.GUITAR, notes=at(0.0, pitch=51)),),
    )
    assert harmonic_conformance(score) == 1.0


def test_parts_are_pooled_so_a_short_pad_cannot_outvote_a_long_bass_line() -> None:
    bass = at(*[float(i) for i in range(8)], pitch=40)  # eight notes, all in key
    keys = at(0.0, pitch=41)  # one note, outside
    assert harmonic_conformance(scored(bass=bass, keys=keys)) == pytest.approx(8 / 9)


def test_drums_are_not_asked_to_be_in_key() -> None:
    """Their pitch is a map entry, not a register (`percussion.py`)."""
    assert harmonic_conformance(scored(drums=at(0.0, 1.0, pitch=36))) == 1.0


# ----------------------------------------------------------------------- register spread


def test_instruments_piled_into_one_octave_score_low() -> None:
    piled = scored(
        bass=at(0.0, pitch=60), guitar=at(0.0, pitch=61), keys=at(0.0, pitch=62)
    )
    assert register_spread(piled) < 0.2


def test_a_band_spread_over_its_nominal_ranges_scores_full() -> None:
    spread = scored(bass=at(0.0, pitch=33), guitar=at(0.0, pitch=57), keys=at(0.0, pitch=72))
    assert register_spread(spread) == 1.0


def test_one_pitched_part_cannot_be_piled_against_anything() -> None:
    assert register_spread(scored(bass=at(0.0, pitch=40))) == 1.0


# ------------------------------------------------------------------- bass/kick alignment


def test_every_kick_supported_by_a_bass_note_scores_full() -> None:
    assert (
        bass_kick_alignment(
            scored(drums=at(0.0, 2.0, pitch=36), bass=at(0.0, 2.0, pitch=40))
        )
        == 1.0
    )


def test_a_bass_denser_than_the_kick_is_not_penalised() -> None:
    """The correction that this metric exists in its current form because of.

    The floor's bass plays eighths against two kicks in a bar. Scoring that as
    misalignment made the approved reference look messy; see the function's docstring.
    """
    busy = scored(drums=at(0.0, 2.0, pitch=36), bass=at(0.0, 1.0, 2.0, 3.0, pitch=40))
    assert bass_kick_alignment(busy) == 1.0


def test_a_bass_that_misses_every_kick_scores_zero() -> None:
    assert bass_kick_alignment(scored(drums=at(0.0, pitch=36), bass=at(1.0, pitch=40))) == 0.0


def test_a_section_with_no_bass_has_nothing_to_misalign() -> None:
    assert bass_kick_alignment(scored(drums=at(0.0, pitch=36))) == 1.0


# --------------------------------------------------------------- density against tension


def test_hitting_the_reference_density_scores_full() -> None:
    # Two bars, eight attacks: four per bar.
    eight = at(0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, pitch=36)
    assert density_against_tension(scored(drums=eight), 4.0) == 1.0


def test_too_busy_and_too_sparse_are_wrong_by_the_same_amount() -> None:
    """`dyn` is a target, not a floor."""
    half = density_against_tension(scored(drums=at(0.0, 1.0, pitch=36)), 2.0)
    double = density_against_tension(
        scored(drums=at(0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, pitch=36)), 2.0
    )
    assert half == double


def test_a_wildly_overbusy_section_stays_inside_the_scale() -> None:
    """A ratio has no cliff: it tends to zero instead of clamping at it."""
    crowded = at(*[i * 0.25 for i in range(64)], pitch=36)
    score = density_against_tension(scored(drums=crowded), 1.0)
    assert 0.0 < score < 0.05


def test_a_section_with_no_drums_has_no_density_to_judge() -> None:
    assert density_against_tension(scored(bass=at(0.0, pitch=40)), 4.0) == 1.0


# ---------------------------------------------------------------------------- the composite


def test_messiness_reads_only_the_measure_that_separated_model_from_floor() -> None:
    """The other four are reported and compose into nothing. See `MESSINESS_PARTS`."""
    assert MESSINESS_PARTS == ("kit_collision",)


def test_a_kit_fighting_itself_is_messy_and_the_floor_is_not() -> None:
    fighting = scored(
        drums=at(0.0, 1.0, 2.0, 3.0, pitch=36) + at(0.0, 1.0, 2.0, 3.0, pitch=38),
    )
    assert coherence_of(fighting).messiness == 1.0
    assert coherence_of(play_section(SECTION, 7)).messiness < 0.3


# ------------------------------------------------------------------------ kit collision


def test_a_kick_and_a_snare_in_one_slot_is_the_collision() -> None:
    both = scored(drums=at(0.0, pitch=36) + at(0.0, pitch=38))
    assert kit_collision(both) == 0.0


def test_a_kick_and_a_snare_that_take_turns_do_not_collide() -> None:
    apart = scored(drums=at(0.0, 2.0, pitch=36) + at(1.0, 3.0, pitch=38))
    assert kit_collision(apart) == 1.0


def test_the_hat_is_not_counted_because_it_sounds_with_everything() -> None:
    """Folding it in would bury the signal under the simultaneity that is never mess."""
    with_hat = scored(drums=at(0.0, 2.0, pitch=36) + at(1.0, 3.0, pitch=38) + at(
        0.0, 1.0, 2.0, 3.0, pitch=42
    ))
    assert kit_collision(with_hat) == 1.0


def test_the_floor_is_clean_by_this_measure() -> None:
    """The reference approved by ear, over every feel and three seeds.

    A metric that scores the engines as messy is not measuring mess. Measured over these
    168 sections the worst is 0.250 and the mean is 0.041 — the curated grooves *do* put a
    kick and a snare together sometimes, deliberately, which is why the bound is where it
    is rather than near zero. A smoke alarm for a future change, not a tuned figure.
    """
    worst = 0.0
    for seed in (7, 11, 1729):
        for feel in Feel:
            brief = SongBrief(
                bpm=132.0, key=4, scale="minor", feel=feel, minimum_seconds=180.0
            )
            for section in arrange(brief, seed):
                worst = max(worst, coherence_of(play_section(section, seed)).messiness)
    assert worst < 0.3


# ------------------------------------------------------------------------ the reference


def test_the_reference_density_is_the_engine_s_own_answer() -> None:
    """Not a constant chosen here: shuffle is not straight8 played louder."""
    quiet = SECTION.model_copy(update={"dyn": 1})
    loud = SECTION.model_copy(update={"dyn": 5})
    assert reference_attacks(loud) > reference_attacks(quiet)
