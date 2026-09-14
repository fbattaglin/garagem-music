"""`BakedProvider`: a take from disk behind the port, free, and never a network failure."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from garagem.agents import request_for, structural
from garagem.domain import Feel, Section
from garagem.dsl import SectionStream, brief, serialize_section
from garagem.engines import play_section
from garagem.llm import (
    BakedProvider,
    BreakerPolicy,
    BreakerState,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    ProviderRefusedError,
    load_budget,
    load_catalog,
    prices_of,
)
from garagem.theory import parse_chart

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "config" / "models.toml")
MODEL = structural(CATALOG)


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 2,
        "tension": 0.35,
        "chart": parse_chart("| Em | Em | C | D |"),
    }
    return Section.model_validate(base | extra)


VERSE = a_section()
DSL = serialize_section(play_section(VERSE, 7))


def guarded(provider: BakedProvider) -> GuardedProvider:
    budget = load_budget(ROOT / "config" / "budget.toml")
    return GuardedProvider(
        provider,
        governor=Governor(budget.fuse(prices_of(CATALOG))),
        breaker=CircuitBreaker(BreakerPolicy()),
    )


def drain(provider: GuardedProvider | BakedProvider, section: Section) -> SectionStream:
    stream = SectionStream(section)

    async def run() -> None:
        async for event in provider.stream(request_for(section, MODEL)):
            stream.feed(event)

    asyncio.run(run())
    return stream


def test_a_baked_briefing_streams_its_take_through_the_parser() -> None:
    stream = drain(BakedProvider({brief(VERSE): DSL}), VERSE)
    assert stream.text == DSL
    result = stream.result()
    assert result.violations == ()
    assert not result.truncated


def test_a_take_bills_nothing_through_the_governor() -> None:
    provider = guarded(BakedProvider({brief(VERSE): DSL}))
    drain(provider, VERSE)
    assert provider.governor.snapshot().spent_usd == Decimal(0)


def test_a_briefing_with_no_take_is_refused() -> None:
    chorus = a_section(name="chorus", dyn=4, tension=0.7)
    with pytest.raises(ProviderRefusedError, match="no take"):
        drain(BakedProvider({brief(VERSE): DSL}), chorus)


def test_refusals_never_open_the_breaker() -> None:
    """A knob moving the song off the bake is not the network failing."""
    breaker = CircuitBreaker(BreakerPolicy())
    budget = load_budget(ROOT / "config" / "budget.toml")
    provider = GuardedProvider(
        BakedProvider({brief(VERSE): DSL}),
        governor=Governor(budget.fuse(prices_of(CATALOG))),
        breaker=breaker,
    )
    chorus = a_section(name="chorus", dyn=4, tension=0.7)
    for _ in range(5):
        with pytest.raises(ProviderRefusedError):
            drain(provider, chorus)
    assert breaker.snapshot().state is BreakerState.CLOSED


def test_it_names_itself_as_baked() -> None:
    provider = BakedProvider({brief(VERSE): DSL}, name="first")
    assert provider.name == "baked:first"
    assert provider.holds(brief(VERSE))
    assert not provider.holds("anything else")
