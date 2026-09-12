"""Deterministic generators — the musical floor, no LLM."""

from garagem.engines.arranger import (
    SHAPES,
    TRANSITIONS,
    SongBrief,
    arrange,
    diatonic,
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

__all__ = [
    "ENDINGS",
    "ENGINES",
    "FEEL_AMOUNT",
    "FILLS",
    "GROOVES",
    "MAX_TIMING_BEATS",
    "MAX_VELOCITY",
    "RELEASE_BEATS",
    "SHAPES",
    "TRANSITIONS",
    "Ending",
    "Groove",
    "SongBrief",
    "arrange",
    "coherence_of",
    "compose",
    "diatonic",
    "endings_for",
    "fill_for",
    "groove_for",
    "humanise",
    "play_section",
    "reference_attacks",
    "separate",
    "with_climax",
]
