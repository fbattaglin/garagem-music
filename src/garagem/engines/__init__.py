"""Deterministic generators — the musical floor, no LLM."""

from garagem.engines.arranger import SHAPES, TRANSITIONS, SongBrief, arrange, diatonic
from garagem.engines.band import ENGINES, play_section
from garagem.engines.groove import FILLS, GROOVES, Groove, fill_for, groove_for
from garagem.engines.humanise import (
    FEEL_AMOUNT,
    MAX_TIMING_BEATS,
    MAX_VELOCITY,
    RELEASE_BEATS,
    humanise,
    separate,
)

__all__ = [
    "ENGINES",
    "FEEL_AMOUNT",
    "FILLS",
    "GROOVES",
    "MAX_TIMING_BEATS",
    "MAX_VELOCITY",
    "RELEASE_BEATS",
    "SHAPES",
    "TRANSITIONS",
    "Groove",
    "SongBrief",
    "arrange",
    "diatonic",
    "fill_for",
    "groove_for",
    "humanise",
    "play_section",
    "separate",
]
