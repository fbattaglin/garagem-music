"""The regression recorder and its replay, against a fake model (phase-4-findings §13).

The real set is recorded by hand and judged in `tests/regression/`. These tests record
from `FakeProvider`, so they can show each way the suite fails without spending anything
and without a recording of the real model.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType

import pytest

from garagem.agents import request_for, structural
from garagem.domain import Section
from garagem.dsl import brief, serialize_section
from garagem.engines import play_section
from garagem.llm import (
    FakeProvider,
    FakeResponse,
    ProviderUnavailableError,
    Request,
    StopReason,
    StreamEvent,
    Usage,
    load_catalog,
    record,
)
from garagem.obs.sections import summarise

ROOT = Path(__file__).resolve().parents[2]
MODEL = structural(load_catalog(ROOT / "config" / "models.toml"))


def _load() -> ModuleType:
    path = ROOT / "scripts" / "record_regression.py"
    spec = importlib.util.spec_from_file_location("record_regression", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_regression"] = module
    spec.loader.exec_module(module)
    return module


recorder = _load()
FULL_SET: list[tuple[str, Section, int]] = recorder.the_set()


class Band:
    """A model that answers every briefing with the floor's own section, in our notation."""

    name = "band"

    def __init__(self, *, failing: str = "", seed_offset: int = 0) -> None:
        self.calls = 0
        self._failing = failing
        self._offset = seed_offset
        self._by_brief = {brief(section): (id_, section, seed) for id_, section, seed in FULL_SET}

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        id_, section, seed = self._by_brief[request.messages[0].content]
        if id_ == self._failing:
            raise ProviderUnavailableError("the network went away")
        dsl = serialize_section(play_section(section, seed + self._offset))
        response = FakeResponse(
            tool_name="write_section",
            tool_input=json.dumps({"dsl": dsl}),
            stop=StopReason.TOOL_USE,
            usage=Usage(input_tokens=300, output_tokens=228),
        )
        async for event in FakeProvider([response]).stream(request):
            yield event


@pytest.fixture
def three(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Section, int]]:
    """Three briefings of the set, so a recording takes milliseconds."""
    chosen = FULL_SET[:3]
    monkeypatch.setattr(recorder, "the_set", lambda: chosen)
    return chosen


def test_the_set_is_phase_3s_closing_population() -> None:
    assert len(FULL_SET) == 29
    assert FULL_SET[0][0] == "00-verse-straight8-132"
    assert len({id_ for id_, _, _ in FULL_SET}) == 29
    assert [seed for _, _, seed in FULL_SET] == list(range(7, 36))


def test_recording_writes_a_cassette_a_briefing_and_the_set_beside_them(
    tmp_path: Path, three: list[tuple[str, Section, int]]
) -> None:
    band = Band()
    recorded = asyncio.run(recorder.record_set(band, MODEL, tmp_path))
    assert band.calls == 3
    assert recorder.load_set(tmp_path) == recorded
    assert all(recorder.cassette_of(tmp_path, entry).exists() for entry in recorded.briefings)


def test_a_failed_call_is_written_down_and_never_asked_again(
    tmp_path: Path, three: list[tuple[str, Section, int]]
) -> None:
    band = Band(failing=three[1][0])
    recorded = asyncio.run(recorder.record_set(band, MODEL, tmp_path))
    assert band.calls == 3
    failed = [entry for entry in recorded.briefings if entry.failed]
    assert [entry.id for entry in failed] == [three[1][0]]
    assert failed[0].failed.startswith("ProviderUnavailableError")
    assert not recorder.cassette_of(tmp_path, failed[0]).exists()


def test_a_faithful_recording_meets_phase_3s_targets(
    tmp_path: Path, three: list[tuple[str, Section, int]]
) -> None:
    recorded = asyncio.run(recorder.record_set(Band(), MODEL, tmp_path))
    shots = recorder.replay(tmp_path, recorded, MODEL)
    assert recorder.missed_targets(summarise(shots, drawn=recorded.drawn)) == []
    assert recorder.mismatched(tmp_path, recorded, MODEL) == []


def test_a_failure_counts_against_the_rates(
    tmp_path: Path, three: list[tuple[str, Section, int]]
) -> None:
    """One call in three lost: a third of the population, and both targets missed."""
    recorded = asyncio.run(recorder.record_set(Band(failing=three[0][0]), MODEL, tmp_path))
    missed = recorder.missed_targets(summarise(recorder.replay(tmp_path, recorded, MODEL)))
    assert missed == ["conformance 0.667", "approval 0.667"]


def test_a_cassette_recorded_for_another_prompt_is_named(
    tmp_path: Path, three: list[tuple[str, Section, int]]
) -> None:
    recorded = asyncio.run(recorder.record_set(Band(), MODEL, tmp_path))
    entry = recorded.briefings[0]
    older = request_for(entry.section, MODEL, positions=False)
    asyncio.run(record(Band(), older, recorder.cassette_of(tmp_path, entry)))
    assert recorder.mismatched(tmp_path, recorded, MODEL) == [entry.id]


def test_a_model_that_plays_differently_changes_the_golden_file(
    tmp_path: Path, three: list[tuple[str, Section, int]]
) -> None:
    """What a new recording's diff shows: the same briefings, other music."""
    before, after = tmp_path / "before", tmp_path / "after"
    first = asyncio.run(recorder.record_set(Band(), MODEL, before))
    second = asyncio.run(recorder.record_set(Band(seed_offset=100), MODEL, after))
    entry = first.briefings[0]
    was = recorder.rendered(recorder.played(before, entry, MODEL))
    now = recorder.rendered(recorder.played(after, second.briefings[0], MODEL))
    assert was != now
    assert was.startswith("# DRM=")
    assert recorder.rendered(recorder.played(before, entry, MODEL)) == was


def test_the_summary_names_the_rates_and_every_briefing(
    tmp_path: Path, three: list[tuple[str, Section, int]]
) -> None:
    recorded = asyncio.run(recorder.record_set(Band(failing=three[2][0]), MODEL, tmp_path))
    shots = recorder.replay(tmp_path, recorded, MODEL)
    scores = [recorder.played(tmp_path, entry, MODEL) for entry in recorded.briefings]
    text = recorder.summary(recorded, shots, scores)
    assert "failures 1" in text
    assert f"{three[0][0]}: conformant, 4 parts; DRM=" in text
    assert f"{three[2][0]}: failed (ProviderUnavailableError)" in text
    assert recorder.rendered(scores[2]) == "unplayable\n"
