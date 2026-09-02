"""The section-shot: one call, one section, one deadline that is not negotiable.

**The deadline is 40% of the musical time remaining** (ADR-000 §4.2), and the rule is
stated there in full:

> every call has a `timeout` = 40% of the musical time remaining until the point of use.
> If it overruns -> cancel, log, use the deterministic engine, and **do not try again for
> that section**.

For an 8-bar section at 132 BPM that is 5.82 s. Phase 0 measured `claude-sonnet-5` at
p50 4.29 s and max 4.52 s total across sixteen calls — the only model whose *worst* call
fit. The 40% is not a safety margin around a typical call; it is what makes the worst
call survivable, because the other 60% is the write (~1.2 s, `phase-2-findings.md` §3)
and the bars the music still has to play.

**A request built here has no retry in it and cannot acquire one.** `Request.deadline_s`
has no default precisely so that nobody can forget to set it, and `GuardedProvider`
already makes the governor and the breaker unavoidable.

The prompt itself is `dsl/schema.py`'s: the stable block cached, the briefing volatile.
This module only decides *which model*, *how long* and *how many tokens*.
"""

from __future__ import annotations

from typing import Final

from garagem.domain import Section
from garagem.dsl import TOOL, brief, system_for
from garagem.llm import Message, ModelSpec, Request, Role

# ADR-000 §4.2. Not a tuning knob: it is the number the two-section lookahead was sized
# against, and moving it moves what the ScoreBuffer's window means.
DEADLINE_FRACTION: Final = 0.4

# A deadline below this is not a shot, it is a formality. A section this short generates
# deterministically instead, which is P2 and costs nothing.
#
# **5.0 s is measured, not chosen.** Over 57 successful section-shots on `claude-sonnet-5`
# the totals run p50 3.47 s, p95 4.68 s, **max 4.96 s** — so a deadline under five seconds
# does not cover the slowest call this project has actually seen succeed, and asking
# inside one buys a cancelled stream and the fallback we already have for free. The
# previous value, 1.5 s, was a guess made before any of those numbers existed.
#
# **What this does not fix, and must not be credited with fixing:** the two deadline
# failures in the 30-shot static round had budgets of 8.00 s and 5.12 s — the most
# generous in the sample — with normal TTFT. Those are the p99 *tail*, which ADR-000 §9
# lists as a High-probability risk and which no floor addresses. This constant stops one
# wasted call in thirty; it is not the answer to the tail.
MIN_DEADLINE_S: Final = 5.0


def deadline_for(section: Section, *, fraction: float = DEADLINE_FRACTION) -> float:
    """How long the model gets: a fraction of the section's own length, in seconds.

    Computed from the section rather than passed in, so a slow tempo genuinely buys time
    and a fast one genuinely does not. An 8-bar section at 132 BPM lasts 14.55 s and the
    deadline is 5.82 s; the same section at 90 BPM lasts 21.3 s and gets 8.5 s.
    """
    return section.total_seconds() * fraction


def worth_asking(section: Section, *, fraction: float = DEADLINE_FRACTION) -> bool:
    """Whether there is enough musical time to be worth a call at all.

    A four-bar intro at 180 BPM leaves 2.1 s, which no model reliably fills. Asking
    anyway would spend money to produce a cancelled stream and a fallback we could have
    had for free — so the caller checks this first and generates deterministically.
    """
    return deadline_for(section, fraction=fraction) >= MIN_DEADLINE_S


def request_for(
    section: Section,
    model: ModelSpec,
    *,
    deadline_s: float | None = None,
    fraction: float = DEADLINE_FRACTION,
    arranged: bool = False,
    dense: bool = False,
    positions: bool = True,
) -> Request:
    """The whole call: cached system block, one volatile message, one strict tool.

    `arranged` asks for one bar-level line per bar rather than one per instrument. It
    doubles the output and is what the blind A/B found missing — see
    `dsl/schema.SYSTEM_ARRANGED`. Off by default: measured, and the model does not do it
    (`phase-3-findings.md` §11).

    `positions` writes a bar as the slots that are struck (`K:1,4,7,11,14`) instead of a
    fixed-width grid, and is **on by default from 2026-09-01**. After every other defect
    was closed, a grid counted wrong by one character was the entire remaining gap to the
    conformance target (§15); positions removed it — zero schema violations in 29 sections
    against two, and faster (§17). Pass `positions=False` for the notation every earlier
    measurement in this phase was taken against.

    `dense` states what `dyn` is for. The model's drum density does not move with `dyn`
    over 85 sections — 14 attacks per bar at dyn=2, 3 and 4 alike — so a briefing field
    the system sends is one the model ignores. Off by default until measured.
    """
    return Request(
        model=model.id,
        messages=(Message(role=Role.USER, content=brief(section, arranged=arranged)),),
        system=system_for(arranged=arranged, dense=dense, positions=positions),
        tool=TOOL,
        max_tokens=model.max_tokens,
        deadline_s=deadline_s
        if deadline_s is not None
        else deadline_for(section, fraction=fraction),
        effort=model.effort,
        # The stable block is the cache prefix. `dsl/schema.py` says what breaks it.
        cache_system=True,
    )
