"""Scoring a section, with the engine's own answer for how busy it should be.

`theory/coherence.py` holds the musical arithmetic and takes the density reference as an
argument, because `engines/` imports `theory/` and the question cannot be asked back the
other way without a cycle. This module is the one line that closes it: `groove_for` already
knows what a dynamic means for each feel, and it is the same function `dsl/realise.py`
reads its hat floor off, for the same reason — a second definition of "how busy is dyn=4"
would be one too many.
"""

from __future__ import annotations

from garagem.domain import Section, SectionScore
from garagem.engines.groove import groove_for
from garagem.theory.coherence import (
    Coherence,
    bass_kick_alignment,
    density_against_tension,
    harmonic_conformance,
    kit_collision,
    register_spread,
)


def reference_attacks(section: Section) -> float:
    """Drum attacks per bar the deterministic engine would play for this briefing.

    The floor is the only calibrated reference the project owns — Phase 2's engines were
    approved by ear — so "the right density" is defined as what they would have played,
    not as a constant chosen here.
    """
    groove = groove_for(section.feel, section.dyn, section.bpm)
    return float(sum(groove.kick) + sum(groove.snare) + sum(groove.hat))


def coherence_of(score: SectionScore) -> Coherence:
    return Coherence(
        harmonic_conformance=harmonic_conformance(score),
        register_spread=register_spread(score),
        bass_kick_alignment=bass_kick_alignment(score),
        density_against_tension=density_against_tension(score, reference_attacks(score.section)),
        kit_collision=kit_collision(score),
    )
