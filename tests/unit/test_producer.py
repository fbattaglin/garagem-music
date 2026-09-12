"""The producer: the thread where the network lives, driven without one.

Everything here runs against `FakeProvider` and `CassetteProvider`. `produce()` is
separate from the loop precisely so these tests need no thread, no clock and no sleeping
— the same trick that made a three-minute performance a unit test in Phase 2.

Three behaviours carry ADR-016 and each has its own test. The producer never touches a
`DawPort`. It never raises into the scheduler's thread. And a section that missed its
deadline is never asked for again, because §4.2 says so in those words.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from garagem.agents import Producer, structural
from garagem.domain import Feel, Instrument, Section
from garagem.dsl import serialize_section
from garagem.engines import play_section
from garagem.llm import (
    CassetteProvider,
    FakeProvider,
    FakeResponse,
    LLMProvider,
    ProviderUnavailableError,
    Request,
    StopReason,
    StreamEvent,
    Usage,
    load_catalog,
)
from garagem.obs import EventLog
from garagem.theory import parse_chart, validate
from garagem.transport import FormPlan, ScoreBuffer

ROOT = Path(__file__).resolve().parents[2]
MODEL = structural(load_catalog(ROOT / "config" / "models.toml"))


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
        "chart": parse_chart("| Em | Em | C | D | Em | Em | C | B7 |"),
    }
    return Section.model_validate(base | extra)


FORM = (a_section(), a_section(name="chorus", dyn=5, tension=0.8), a_section(name="outro"))


def dsl_for(section: Section, seed: int = 7) -> str:
    """A perfectly conformant response: our own serializer's output."""
    return serialize_section(play_section(section, seed))


def responding(*dsl: str, usage: Usage | None = None, **kwargs: object) -> FakeProvider:
    return FakeProvider(
        [
            FakeResponse(
                tool_name="write_section",
                tool_input=json.dumps({"dsl": text}),
                stop=StopReason.TOOL_USE,
                usage=usage or Usage(input_tokens=1200, output_tokens=340),
            )
            for text in dsl
        ],
        **kwargs,  # type: ignore[arg-type]
    )


class Rig:
    """A producer with everything it needs and nothing it should not have."""

    def __init__(self, provider: LLMProvider, sections: tuple[Section, ...] = FORM) -> None:
        self.buffer = ScoreBuffer()
        self.log = EventLog(None)
        self.producer = Producer(provider, self.buffer, self.log, sections, model=MODEL, seed=7)

    def produce(self, index: int) -> bool:
        return asyncio.run(self.producer.produce(index))

    def kinds(self) -> list[str]:
        return [event.kind for event in self.log]

    def of_kind(self, kind: str) -> list[dict[str, object]]:
        return [dict(event.detail) for event in self.log.of_kind(kind)]


# ------------------------------------------------------------------------ the happy path


def test_a_produced_section_reaches_the_buffer() -> None:
    rig = Rig(responding(dsl_for(FORM[0])))
    assert rig.produce(0)
    assert rig.buffer.take(0) is not None


def test_what_reaches_the_buffer_is_playable() -> None:
    rig = Rig(responding(dsl_for(FORM[0])))
    rig.produce(0)
    score = rig.buffer.take(0)
    assert score is not None
    assert validate(score) == ()


def test_the_score_carries_a_seed_derived_from_the_producers() -> None:
    """Invariant 7: a section nobody can reproduce cannot be replayed from the log."""
    rig = Rig(responding(dsl_for(FORM[0])))
    rig.produce(0)
    score = rig.buffer.take(0)
    assert score is not None
    assert score.seed == 7 + 0
    assert rig.of_kind("section_parsed")[0]["seed"] == 7


def test_the_request_and_the_result_are_both_logged() -> None:
    """The denominator and the numerator. A rate needs both recorded."""
    rig = Rig(responding(dsl_for(FORM[0])))
    rig.produce(0)
    assert "section_requested" in rig.kinds()
    assert "section_parsed" in rig.kinds()


def test_the_log_says_which_model_answered() -> None:
    rig = Rig(responding(dsl_for(FORM[0])))
    rig.produce(0)
    assert rig.of_kind("section_parsed")[0]["model"] == MODEL.id


def test_token_usage_reaches_the_log() -> None:
    rig = Rig(responding(dsl_for(FORM[0]), usage=Usage(input_tokens=900, output_tokens=210)))
    rig.produce(0)
    detail = rig.of_kind("section_parsed")[0]
    assert detail["input_tokens"] == 900
    assert detail["output_tokens"] == 210


# ---------------------------------------------------------------------- partial sections


def test_a_truncated_stream_is_completed_from_the_deterministic_engine() -> None:
    """§4.3: write what arrived and complete the rest locally.

    Offered as-is, a two-part score would leave the previous section's guitar and keys
    still sounding underneath this one — the scheduler writes only what a score contains.
    """
    partial = "\n".join(dsl_for(FORM[0]).splitlines()[:10])
    rig = Rig(responding(partial))
    assert rig.produce(0)
    score = rig.buffer.take(0)
    assert score is not None
    assert score.instruments() == frozenset(Instrument)


def test_the_log_says_which_parts_were_the_models() -> None:
    partial = "\n".join(dsl_for(FORM[0]).splitlines()[:10])
    rig = Rig(responding(partial))
    rig.produce(0)
    parts = str(rig.of_kind("section_parsed")[0]["parts"])
    assert "DRM" in parts
    assert "KEY" not in parts


def test_a_stream_with_no_tool_call_at_all_falls_back() -> None:
    rig = Rig(FakeProvider([FakeResponse(text="I would rather not.")]))
    assert not rig.produce(0)
    assert rig.buffer.take(0) is None
    assert "fallback" in rig.kinds()


# ------------------------------------------------------------------------ schema failures


def test_a_malformed_line_is_logged_as_a_schema_violation() -> None:
    """The numerator of the conformance rate, recorded per violation."""
    broken = dsl_for(FORM[0]).replace("rhy:", "rhy:x", 1)
    rig = Rig(responding(broken))
    rig.produce(0)
    assert rig.of_kind("schema_violation")


def test_a_section_with_one_bad_line_still_reaches_the_buffer() -> None:
    """A violation costs that line, not the section. Most of the notes are still good."""
    broken = dsl_for(FORM[0]).replace("rhy:", "rhy:x", 1)
    rig = Rig(responding(broken))
    assert rig.produce(0)
    assert rig.buffer.take(0) is not None


# ------------------------------------------------------------------------- the deadline


# Long enough that `worth_asking` says yes: the overrun under test has to be the provider
# being slow, not the producer declining to ask. Eight bars at 132 BPM give a 5.82 s
# deadline, over the 5.0 s floor.
#
# **This is the only test here that costs real time, and it costs 5.82 s of it** — the
# thing being proven is that a *wall-clock* deadline actually cancels a stream, and a fake
# clock would prove something else. Two bars at 120 BPM used to serve, at 1.6 s, and
# stopped when `MIN_DEADLINE_S` went from a guessed 1.5 s to a measured 5.0 s: the test
# then passed for the wrong reason, logging `no_time` instead of a cancellation.
SLOW = a_section(bars=8, bpm=132.0)


def test_a_deadline_overrun_cancels_the_stream_and_is_logged() -> None:
    """§4.2: cancel, log, use the deterministic engine. Not a timeout noticed later."""
    rig = Rig(responding(dsl_for(SLOW), ttft_s=30.0), sections=(SLOW,))

    assert not rig.produce(0)
    assert rig.buffer.take(0) is None
    missed = rig.of_kind("deadline_missed")
    assert len(missed) == 1
    assert missed[0]["deadline_s"] == pytest.approx(5.82, abs=0.01)


def test_a_section_that_missed_its_deadline_is_never_asked_again() -> None:
    """ "...and do not try again for that section" — §4.2, in those words.

    The second provider response exists precisely so that a retry would *succeed*: if
    anything ever asks again, this fails by producing a section rather than by erroring.
    """
    rig = Rig(
        FakeProvider(
            [
                FakeResponse(text="too slow"),
                FakeResponse(
                    tool_name="write_section",
                    tool_input=json.dumps({"dsl": dsl_for(SLOW)}),
                    stop=StopReason.TOOL_USE,
                ),
            ],
            ttft_s=30.0,
        ),
        sections=(SLOW,),
    )

    assert not rig.produce(0)
    assert 0 in rig.producer.attempted
    assert rig.producer._next_wanted() is None
    assert rig.buffer.take(0) is None


def test_a_section_too_short_to_be_worth_asking_is_not_asked() -> None:
    """Spending a call to buy a cancelled stream and a fallback we had for free."""
    rig = Rig(responding(dsl_for(FORM[0])), sections=(a_section(bars=1, bpm=200.0),))
    assert not rig.produce(0)
    assert "section_requested" not in rig.kinds()
    assert rig.of_kind("fallback")[0]["reason"] == "no_time"


# -------------------------------------------------------------------- provider failures


def test_a_provider_that_raises_logs_a_fallback_and_leaves_the_buffer_empty() -> None:
    """Nothing escapes into the scheduler's thread. That is the whole contract."""
    rig = Rig(responding(dsl_for(FORM[0]), fail_with=ProviderUnavailableError("503"), fail_after=0))
    assert not rig.produce(0)
    assert rig.buffer.take(0) is None
    assert rig.of_kind("fallback")[0]["reason"] == "ProviderUnavailableError"


def test_a_stream_cut_midway_keeps_what_arrived() -> None:
    rig = Rig(responding(dsl_for(FORM[0]), fail_with=ProviderUnavailableError("cut"), fail_after=8))
    assert not rig.produce(0)
    assert "fallback" in rig.kinds()


# -------------------------------------------------------------------------- the window


def test_a_section_offered_after_the_window_moved_is_refused_and_counted() -> None:
    """`ScoreBuffer.refused` becomes meaningful for the first time in this phase."""
    rig = Rig(responding(dsl_for(FORM[0])))
    rig.buffer.advance(2)
    assert not rig.produce(0)
    assert rig.buffer.refused == 1
    assert rig.of_kind("fallback")[0]["reason"] == "too_late"


def test_an_index_past_the_form_produces_nothing() -> None:
    rig = Rig(responding(dsl_for(FORM[0])))
    assert not rig.produce(99)


def test_the_producer_asks_for_the_gaps_in_play_order() -> None:
    rig = Rig(responding(dsl_for(FORM[0])))
    assert rig.producer._next_wanted() == 0
    rig.produce(0)
    assert rig.producer._next_wanted() == 1


def test_a_producer_with_nothing_wanted_does_no_work() -> None:
    rig = Rig(responding(dsl_for(FORM[0])), sections=())
    assert rig.producer._next_wanted() is None


# ------------------------------------------------------------------------- the lifecycle


def test_stopping_without_starting_is_safe() -> None:
    Rig(responding(dsl_for(FORM[0]))).producer.stop()


def test_the_thread_starts_and_joins() -> None:
    rig = Rig(responding(*[dsl_for(section) for section in FORM]))
    rig.producer.start()
    assert rig.producer.running
    rig.producer.stop()
    assert not rig.producer.running


def test_starting_twice_makes_one_thread() -> None:
    rig = Rig(responding(*[dsl_for(section) for section in FORM]))
    rig.producer.start()
    rig.producer.start()
    rig.producer.stop()


# --------------------------------------------------------------------- against a cassette


def test_a_cassette_recorded_for_another_prompt_is_swallowed_not_raised() -> None:
    """`CassetteMismatchError` is a `ProviderError`, and the producer eats every one.

    The four cassettes were recorded against the recipe's probe string, not against
    `brief(section)`, so replaying one here is a fingerprint mismatch — which is exactly
    the check `CassetteProvider` exists to make. What matters is what the producer does
    with it: logs a fallback, leaves the buffer empty, and lets the scheduler carry on
    playing the deterministic floor. Nothing reaches the other thread.
    """
    rig = Rig(CassetteProvider(ROOT / "cassettes" / "anthropic_section.jsonl"))
    assert not rig.produce(0)
    assert rig.buffer.take(0) is None
    assert rig.of_kind("fallback")[0]["reason"] == "CassetteMismatchError"


def test_the_whole_path_runs_against_a_real_cassette_provider(tmp_path: Path) -> None:
    """End to end through `CassetteProvider`, with a recording made offline.

    `llm.cassette.record` against a `FakeProvider` produces a real cassette file with a
    real fingerprint — the same shape `scripts/record_cassette.py` writes against a real
    model. So the replay path is exercised for real, with no network and no key.
    """
    from garagem.agents.section import request_for
    from garagem.llm import record

    section = FORM[0]
    request = request_for(section, MODEL)
    path = tmp_path / "section.jsonl"
    asyncio.run(record(responding(dsl_for(section)), request, path, note="offline fixture"))

    rig = Rig(CassetteProvider(path))
    assert rig.produce(0)
    score = rig.buffer.take(0)
    assert score is not None
    assert score.instruments() == frozenset(Instrument)
    assert validate(score) == ()


def test_two_runs_with_one_seed_produce_the_same_music() -> None:
    first = Rig(responding(dsl_for(FORM[0])))
    second = Rig(responding(dsl_for(FORM[0])))
    first.produce(0)
    second.produce(0)
    assert first.buffer.take(0) == second.buffer.take(0)


# ------------------------------------------------------------------------------ warming


class WarmingProvider:
    """A provider that counts its warmings, and can refuse one."""

    def __init__(self, inner: LLMProvider, *, fail: bool = False) -> None:
        self._inner = inner
        self._fail = fail
        self.warmed = 0

    @property
    def name(self) -> str:
        return self._inner.name

    async def warm(self) -> None:
        self.warmed += 1
        if self._fail:
            raise ProviderUnavailableError("no route to host")

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        async for event in self._inner.stream(request):
            yield event


def test_the_pool_is_warmed_on_the_producers_own_loop() -> None:
    """§4.2 budgets zero for the handshake, which is only true if someone paid earlier.

    It has to be this loop: the pool belongs to the loop that created it (§9).
    """
    provider = WarmingProvider(responding(dsl_for(FORM[0])))
    rig = Rig(provider)
    asyncio.run(rig.producer._warm())
    assert provider.warmed == 1


def test_a_provider_that_cannot_be_warmed_still_produces() -> None:
    """A warm failure is not a stop. The first section fails and *that* is logged."""
    provider = WarmingProvider(responding(dsl_for(FORM[0])), fail=True)
    rig = Rig(provider)
    asyncio.run(rig.producer._warm())
    assert rig.produce(0)
    assert rig.buffer.take(0) is not None


def test_a_provider_with_no_pool_to_open_is_not_an_error() -> None:
    """A cassette has nothing to warm and is not deficient for it."""
    rig = Rig(responding(dsl_for(FORM[0])))
    asyncio.run(rig.producer._warm())
    assert rig.produce(0)


# ------------------------------------------------------------- a form that changes (ADR-022)


class Replanning:
    """A provider that re-plans the form while it is answering, as a jump cue would."""

    def __init__(self, inner: FakeProvider, plan: FormPlan, replacement: tuple[Section, ...]):
        self.inner = inner
        self.plan = plan
        self.replacement = replacement

    @property
    def name(self) -> str:
        return "replanning"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.plan.replace(self.replacement, None)
        async for event in self.inner.stream(request):
            yield event


def test_a_re_planned_index_is_a_new_question_for_the_model() -> None:
    plan = FormPlan(FORM)
    provider = responding(dsl_for(FORM[0]), dsl_for(FORM[1]), dsl_for(FORM[0]))
    buffer = ScoreBuffer()
    producer = Producer(provider, buffer, EventLog(None), plan, model=MODEL, seed=7)
    assert asyncio.run(producer.produce(0))
    assert asyncio.run(producer.produce(1))

    replanned = (FORM[0], FORM[0], FORM[2])
    plan.replace(replanned, None)
    buffer.discard_from(1)
    assert producer._next_wanted() == 1
    assert asyncio.run(producer.produce(1))
    assert "verse" in provider.calls[-1].messages[0].content
    assert buffer.take(1) is not None
    assert buffer.take(1).section == FORM[0]  # type: ignore[union-attr]


def test_music_for_a_briefing_replaced_mid_answer_is_never_offered() -> None:
    plan = FormPlan(FORM)
    replanned = (FORM[0], FORM[0], FORM[2])
    provider = Replanning(responding(dsl_for(FORM[1])), plan, replanned)
    buffer = ScoreBuffer()
    log = EventLog(None)
    producer = Producer(provider, buffer, log, plan, model=MODEL, seed=7)

    assert not asyncio.run(producer.produce(1))
    assert buffer.take(1) is None
    assert [event.detail.get("reason") for event in log.of_kind("fallback")] == ["stale"]
    assert log.of_kind("section_parsed") == ()
