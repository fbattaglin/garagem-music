"""The section-shot: which model, how long, and the deadline that is not negotiable.

The deadline is computed from the section rather than passed in, and the tests hold it
to ADR-000 §4.2's arithmetic: 40% of the musical time remaining. That single number is
what the ScoreBuffer's two-section window was sized against, so it is asserted against
the tempo and the bar count rather than against a constant somebody could nudge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from garagem.agents import (
    DEADLINE_FRACTION,
    MIN_DEADLINE_S,
    deadline_for,
    request_for,
    structural,
    tactical,
    worth_asking,
)
from garagem.domain import Feel, Section
from garagem.dsl import SYSTEM, TOOL
from garagem.dsl.schema import SYSTEM_POSITIONS
from garagem.llm import load_catalog
from garagem.theory import parse_chart

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "config" / "models.toml")


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": parse_chart("| Em | C | G | D |"),
    }
    return Section.model_validate(base | extra)


# ------------------------------------------------------------------------- the deadline


def test_the_deadline_is_the_number_phase_zero_measured_against() -> None:
    """8 bars at 132 BPM lasts 14.55 s; 40% of that is 5.82 s."""
    assert deadline_for(a_section()) == pytest.approx(5.82, abs=0.01)


def test_a_slower_tempo_genuinely_buys_time() -> None:
    assert deadline_for(a_section(bpm=90.0)) > deadline_for(a_section(bpm=132.0))


def test_a_longer_section_genuinely_buys_time() -> None:
    assert deadline_for(a_section(bars=16)) == pytest.approx(2 * deadline_for(a_section(bars=8)))


def test_the_fraction_is_forty_percent_and_says_so() -> None:
    section = a_section()
    assert deadline_for(section) == pytest.approx(section.total_seconds() * DEADLINE_FRACTION)


def test_sonnets_worst_measured_call_fits_inside_the_deadline() -> None:
    """Phase 0: 16 calls, max total 4.52 s. That is why it is the structural model."""
    assert deadline_for(a_section()) > 4.52


def test_opus_worst_measured_call_does_not() -> None:
    """Same median, 3.08 s over at worst — a cancelled stream, not a better section."""
    assert deadline_for(a_section()) < 8.9


# ---------------------------------------------------------------- when not to ask at all


def test_a_section_with_no_time_in_it_is_not_worth_a_call() -> None:
    """Spending money to produce a cancelled stream and a fallback we had for free."""
    assert not worth_asking(a_section(bars=1, bpm=180.0))


def test_a_normal_section_is_worth_a_call() -> None:
    assert worth_asking(a_section())


def test_the_floor_is_where_the_deadline_stops_being_a_shot() -> None:
    assert deadline_for(a_section()) > MIN_DEADLINE_S


# -------------------------------------------------------------------------- the request


def test_the_request_carries_the_tool_and_the_cached_system_block() -> None:
    request = request_for(a_section(), structural(CATALOG))
    assert request.tool is TOOL
    assert request.system == SYSTEM_POSITIONS
    assert request.cache_system


def test_the_default_notation_is_positions_and_the_grid_is_still_reachable() -> None:
    """Changed on 2026-09-01, and the test is here so it cannot change by accident.

    Measured over 29 sections each: conformance 97% against 93%, **zero schema violations
    against two**, p95 latency 0.69x against 0.84x. The grid miscount the notation removes
    ran at 18 of 149 sections across the phase, so P(0 of 29 | that rate) = 0.024
    (`phase-3-findings.md` §17).

    `SYSTEM` stays reachable because four cassettes and every earlier measurement in this
    phase were taken against it, and a comparison you cannot re-run is not a comparison.
    """
    assert request_for(a_section(), structural(CATALOG)).system == SYSTEM_POSITIONS
    assert request_for(a_section(), structural(CATALOG), positions=False).system == SYSTEM
    assert SYSTEM_POSITIONS != SYSTEM


def test_the_briefing_is_the_only_message() -> None:
    """Everything stable is in `system`; anything per-section there would zero the cache."""
    request = request_for(a_section(), structural(CATALOG))
    assert len(request.messages) == 1
    assert "bars=8" in request.messages[0].content


def test_the_model_and_its_limits_come_from_the_catalogue() -> None:
    spec = structural(CATALOG)
    request = request_for(a_section(), spec)
    assert request.model == spec.id
    assert request.max_tokens == spec.max_tokens
    assert request.effort == spec.effort


def test_a_model_with_no_effort_knob_is_sent_none() -> None:
    """Haiku 4.5 predates the parameter and rejects it with a 400."""
    assert request_for(a_section(), tactical(CATALOG)).effort is None


def test_the_deadline_reaches_the_request() -> None:
    request = request_for(a_section(), structural(CATALOG))
    assert request.deadline_s == pytest.approx(deadline_for(a_section()))


def test_an_explicit_deadline_wins() -> None:
    request = request_for(a_section(), structural(CATALOG), deadline_s=2.0)
    assert request.deadline_s == 2.0


# ------------------------------------------------------------------------ the fingerprint


def test_the_same_section_gives_the_same_request() -> None:
    """The cassette replay matches on this hash; instability breaks every recording."""
    first = request_for(a_section(), structural(CATALOG))
    second = request_for(a_section(), structural(CATALOG))
    assert first.fingerprint() == second.fingerprint()


def test_a_different_briefing_gives_a_different_request() -> None:
    first = request_for(a_section(), structural(CATALOG))
    second = request_for(a_section(tension=0.9), structural(CATALOG))
    assert first.fingerprint() != second.fingerprint()


def test_the_cache_prefix_is_identical_across_two_different_sections() -> None:
    """The whole point of the split: the prefix must not move between calls."""
    first = request_for(a_section(), structural(CATALOG))
    second = request_for(a_section(name="chorus", bars=4, dyn=5), structural(CATALOG))
    assert first.system == second.system
    assert first.messages != second.messages
