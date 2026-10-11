"""The whole band for one section: the deterministic floor, in one call.

This is what P2 rests on. Every later phase adds a model to a system that must already
sound like a band without one, and `play_section` is that system. When an LLM misses its
deadline, is refused, or returns something the validator will not accept, this is the
function the scheduler calls instead — so it can never fail, never wait and never need a
network.

**One `Random`, created here, handed to each engine in the DSL's order.** DRM, BAS, GTR,
KEY is mandated by `.claude/skills/garagem-dsl` for incremental parsing, and following it
offline costs nothing and buys something: it is the same order Phase 3's parser will see,
so an ordering bug shows up in a golden file rather than in a live stream. Because the
engines share one generator, that order is also load-bearing for invariant 7: reordering
the calls changes the music, and the golden tests would say so.

**LED goes behind them, and it is the only engine allowed to return early.** It is last,
so the fact that it draws nothing from the generator when it rests cannot move any other
part (`engines/lead.py`).

**The second guitar is not an engine.** It is made from the finished guitar part by
`with_double`, after every engine has run, and it draws nothing from the generator
(`engines/double.py`, ADR-028).
"""

from __future__ import annotations

from collections.abc import Callable
from random import Random
from typing import Final

from garagem.domain import Instrument, Part, Section, SectionScore
from garagem.engines.bass import play as play_bass
from garagem.engines.double import double
from garagem.engines.drums import play as play_drums
from garagem.engines.guitar import play as play_guitar
from garagem.engines.keys import play as play_keys
from garagem.engines.lead import play as play_lead

# In the DSL's mandated emission order. Iterating this is what guarantees it.
ENGINES: Final[tuple[tuple[Instrument, Callable[[Section, Random], Part]], ...]] = (
    (Instrument.DRUMS, play_drums),
    (Instrument.BASS, play_bass),
    (Instrument.GUITAR, play_guitar),
    (Instrument.KEYS, play_keys),
    (Instrument.LEAD, play_lead),
)


def play_section(section: Section, seed: int) -> SectionScore:
    """Six parts and the seed that produced them. Pure, total, and offline.

    Six parts, not six voices sounding: the lead and the second guitar are each silent below
    their own dynamic (`engines/lead.py`, `engines/double.py`), and a part with no notes is how
    this system says "chose not to play" — the same distinction `dsl/serialize.py` keeps
    between a line of rests and no line at all.
    """
    rng = Random(seed)
    parts = tuple(play(section, rng) for _, play in ENGINES)
    return with_double(SectionScore(section=section, parts=parts, seed=seed))


def completed(score: SectionScore) -> SectionScore:
    """`score` with every instrument it lacks played by the floor, in the DSL's order.

    ADR-000 §4.3: *"if the stream is cut short, write what arrived and complete the rest
    locally."* The scheduler writes only the instruments a score contains, so an incomplete
    score would leave the previous section still sounding underneath this one. The missing
    parts come from `play_section` with the score's own briefing and seed, so they are the
    parts the floor would have played in that place.
    """
    missing = [instrument for instrument, _ in ENGINES if instrument not in score.instruments()]
    if not missing:
        return with_double(score)
    floor = play_section(score.section, score.seed)
    order = [instrument for instrument, _ in ENGINES]
    parts = sorted(
        (*score.parts, *(floor.part(instrument) for instrument in missing)),
        key=lambda part: order.index(part.instrument),
    )
    return with_double(score.model_copy(update={"parts": tuple(parts)}))


def with_double(score: SectionScore) -> SectionScore:
    """`score` with its second guitar, made from whatever guitar part it already has.

    After every other part, from the finished guitar: a model's take is doubled exactly as
    the floor is, and a score that already carries a double is left alone, so this can run
    twice without playing the second guitar twice (ADR-028).
    """
    instruments = score.instruments()
    if Instrument.GUITAR_DOUBLE in instruments or Instrument.GUITAR not in instruments:
        return score
    second = double(score.part(Instrument.GUITAR), score.section)
    return score.model_copy(update={"parts": (*score.parts, second)})
