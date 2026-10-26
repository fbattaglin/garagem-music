"""What playing a song needs besides the scheduler: its scenes, its takes, its first section.

Moved here from `scripts/jam.py` when `garagem show` needed the same pieces (ADR-028). The
script imports them back, so the two play a baked song by one set of rules.
"""

from __future__ import annotations

import time
from typing import Final

from garagem.agents import deadline_for, worth_asking
from garagem.daw import SessionSpec
from garagem.daw.errors import SessionSpecError
from garagem.domain import Section
from garagem.engines.arranger import CHORUS
from garagem.llm import (
    BakedProvider,
    BreakerPolicy,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    SessionBudget,
    prices_of,
)
from garagem.setlist import Setlist, Song, answers
from garagem.transport import ScoreBuffer

CHORUS_SCENE: Final = "CHORUS"
# ADR-022's variant scenes, by the names session.toml gives them, paired with main scenes A, B.
MAIN_SCENES: Final = ("A", "B")
VARIANT_SCENES: Final[dict[str, tuple[str, str]]] = {
    "stop": ("STOP A", "STOP B"),
    "fill": ("FILL A", "FILL B"),
}

# How long to let the producer fill the buffer before the transport rolls. Without this
# the first section is always a fallback — `Scheduler.begin` writes and fires before any
# generation can finish, which is a race the music always wins. A band does not hit play
# before it knows the first song.
#
# The wait is the section's own deadline plus a margin, not a number somebody picked: a
# model that has not answered by its deadline is not going to (§4.2), and the margin
# covers the parse, the realise and the repair. Bounded, and falling through is not a
# failure — the deterministic engine plays section one, which is P2 working as designed.
PRIME_MARGIN_S: Final = 1.0
PRIME_POLL_S: Final = 0.05


def candidate_scenes(spec: SessionSpec) -> dict[str, int]:
    """Which scene each jump's candidate is written into, found by name in `session.toml`."""
    named = {scene.name: scene.index for scene in spec.scenes}
    if CHORUS_SCENE not in named:
        raise SessionSpecError(
            f"session.toml names no {CHORUS_SCENE!r} scene; ADR-022 writes the chorus candidate "
            "there"
        )
    return {CHORUS: named[CHORUS_SCENE]}


def variant_scenes(spec: SessionSpec) -> dict[str, dict[int, int]]:
    """Variant kind -> main scene -> the scene its variants are written into, by name."""
    named = {scene.name: scene.index for scene in spec.scenes}
    wanted = [*MAIN_SCENES, *(name for pair in VARIANT_SCENES.values() for name in pair)]
    missing = [name for name in wanted if name not in named]
    if missing:
        raise SessionSpecError(
            f"session.toml names no scene {missing}; ADR-022 writes bar-cue variants there"
        )
    return {
        kind: {named[main]: named[variant] for main, variant in zip(MAIN_SCENES, pair, strict=True)}
        for kind, pair in VARIANT_SCENES.items()
    }


def build_setlist_provider(
    setlist: Setlist, song: Song, catalog: list[ModelSpec], budget: SessionBudget
) -> LLMProvider:
    """The song's takes behind the same guards as a model: nothing here reaches a network."""
    return GuardedProvider(
        BakedProvider(answers(song), name=setlist.name),
        governor=Governor(budget.fuse(prices_of(catalog))),
        breaker=CircuitBreaker(BreakerPolicy()),
    )


def prime(buffer: ScoreBuffer, first: Section, *, margin_s: float = PRIME_MARGIN_S) -> float:
    """Wait for the first section, or give up. Returns how long it took, in seconds.

    The one place that sleeps, and it is before the music starts rather than during it —
    nothing here runs on the bar loop.

    **Returns immediately when the first section was never going to be asked for.** A
    4-bar intro at 132 BPM has a 2.91 s deadline, under `MIN_DEADLINE_S`, so the producer
    declines it and plays the floor — and waiting 3.9 s for an answer nobody requested
    delayed the downbeat of every performance for nothing. Found in `bench/jam-phase3.jsonl`
    on 2026-09-01, one run after the floor was raised from 1.5 s to a measured 5.0 s.
    """
    if not worth_asking(first):
        return 0.0
    timeout_s = deadline_for(first) + margin_s
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if buffer.take(0) is not None:
            break
        time.sleep(PRIME_POLL_S)
    return time.monotonic() - started
