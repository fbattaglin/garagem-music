"""`FormPlan` and the buffer's side of a re-plan: versions, lookups, stale scores dropped."""

from __future__ import annotations

from garagem.domain import Feel
from garagem.engines import SongBrief, arrange, endings_for, play_section
from garagem.transport import FormPlan, ScoreBuffer

FORM = arrange(
    SongBrief(key=4, scale="minor", bpm=132.0, feel=Feel.STRAIGHT8, minimum_seconds=60), 7
)


def test_a_plan_answers_by_index_and_says_nothing_past_the_end() -> None:
    plan = FormPlan(FORM)
    assert plan.at(0) == FORM[0]
    assert plan.at(len(FORM)) is None
    assert plan.at(-1) is None
    assert len(plan) == len(FORM)


def test_replacing_a_plan_bumps_its_version_and_swaps_everything_at_once() -> None:
    plan = FormPlan(FORM)
    before = plan.version
    shorter = FORM[:3]
    version = plan.replace(shorter, endings_for(shorter))
    assert version == before + 1 == plan.version
    assert plan.sections() == shorter
    assert plan.endings() == endings_for(shorter)


def test_discarding_from_an_index_keeps_what_comes_before_it() -> None:
    buffer = ScoreBuffer()
    for index in range(3):
        buffer.offer(index, play_section(FORM[index], index))
    buffer.discard_from(1)
    assert buffer.pending() == (0,)
