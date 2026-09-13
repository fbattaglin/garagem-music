"""Deterministic generators — the musical floor, no LLM."""

from garagem.engines.arranger import (
    SHAPES,
    TRANSITIONS,
    SongBrief,
    arrange,
    candidate_for,
    continue_from,
    density_offset,
    diatonic,
    jump_plan,
    shifted,
    tension_offset,
    with_climax,
)
from garagem.engines.band import ENGINES, play_section
from garagem.engines.coherence import coherence_of, reference_attacks
from garagem.engines.groove import FILLS, GROOVES, Groove, fill_for, groove_for
from garagem.engines.humanise import (
    FEEL_AMOUNT,
    MAX_TIMING_BEATS,
    MAX_VELOCITY,
    RELEASE_BEATS,
    humanise,
    separate,
)
from garagem.engines.transitions import ENDINGS, Ending, compose, endings_for
from garagem.engines.variants import FILL_CUE_TENSION, FillStyle, fill_bars, land_bars, stop_bars

__all__ = [
    "ENDINGS",
    "ENGINES",
    "FEEL_AMOUNT",
    "FILLS",
    "FILL_CUE_TENSION",
    "GROOVES",
    "MAX_TIMING_BEATS",
    "MAX_VELOCITY",
    "RELEASE_BEATS",
    "SHAPES",
    "TRANSITIONS",
    "Ending",
    "FillStyle",
    "Groove",
    "SongBrief",
    "arrange",
    "candidate_for",
    "coherence_of",
    "compose",
    "continue_from",
    "density_offset",
    "diatonic",
    "endings_for",
    "fill_bars",
    "fill_for",
    "groove_for",
    "humanise",
    "jump_plan",
    "land_bars",
    "play_section",
    "reference_attacks",
    "separate",
    "shifted",
    "stop_bars",
    "tension_offset",
    "with_climax",
]
