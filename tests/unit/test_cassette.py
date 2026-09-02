"""Cassettes: recording, replaying and — above all — noticing when they have aged."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from conftest import Collector, tool_input_of
from garagem.llm import (
    CassetteMismatchError,
    CassetteMissingError,
    CassetteProvider,
    FakeProvider,
    FakeResponse,
    LLMProvider,
    Message,
    Request,
    Role,
    StopReason,
    Usage,
    record,
)

CASSETTES = Path(__file__).resolve().parents[2] / "cassettes"
EXAMPLE = CASSETTES / "example_section.jsonl"

DSL = "\n".join(
    [
        "SEC verse 8 132 Em",
        "DRM |x--x--x-|x--x--x-|",
        "BAS |E---G---|D---A---|",
        "GTR |Em--G---|D---A---|",
    ]
)


def a_request(**extra: object) -> Request:
    base: dict[str, object] = {
        "model": "claude-opus-5",
        "messages": (Message(role=Role.USER, content="a verse in Em"),),
        "deadline_s": 5.8,
    }
    return Request.model_validate(base | extra)


def record_to(provider: LLMProvider, request: Request, target: Path) -> list[object]:
    return list(asyncio.run(record(provider, request, target)))


# ------------------------------------------------------------------------ roundtrip


def test_records_and_replays_event_for_event(tmp_path: Path, collect: Collector) -> None:
    req = a_request()
    source = FakeProvider([FakeResponse(text=DSL, usage=Usage(output_tokens=42))], seed=11)
    recorded = record_to(source, req, tmp_path / "c.jsonl")

    replayed = collect(CassetteProvider(tmp_path / "c.jsonl"), req)
    assert replayed == recorded


def test_re_recording_produces_the_same_file_byte_for_byte(tmp_path: Path) -> None:
    """A cassette that changes on its own pollutes every diff — and hides real drift."""
    req = a_request()
    for name in ("a.jsonl", "b.jsonl"):
        record_to(FakeProvider([FakeResponse(text=DSL)], seed=11), req, tmp_path / name)
    assert (tmp_path / "a.jsonl").read_bytes() == (tmp_path / "b.jsonl").read_bytes()


def test_the_cassette_committed_to_the_repo_still_replays(collect: Collector) -> None:
    """Pins the format: if it changes, this test says so before CI breaks."""
    provider = CassetteProvider(EXAMPLE)
    _, req = _example_recipe()
    events = collect(provider, req)

    assert provider.name == "cassette:fake"
    assert provider.header.model == "claude-opus-5"
    assert events[-1].type == "done"
    assert events[-1].stop is StopReason.TOOL_USE
    assert events[-1].usage.cache_read_tokens == 2048
    assert tool_input_of(events) == {"dsl": DSL}


# ------------------------------------------------------------------------ vigilance


def test_a_different_prompt_invalidates_the_cassette(tmp_path: Path, collect: Collector) -> None:
    record_to(
        FakeProvider([FakeResponse(text=DSL)]), a_request(system="rules v1"), tmp_path / "c.jsonl"
    )

    with pytest.raises(CassetteMismatchError, match="re-record"):
        collect(CassetteProvider(tmp_path / "c.jsonl"), a_request(system="rules v2"))


def test_a_missing_cassette_says_which_one(tmp_path: Path) -> None:
    with pytest.raises(CassetteMissingError, match=r"does_not_exist\.jsonl"):
        CassetteProvider(tmp_path / "does_not_exist.jsonl")


def test_a_future_format_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "c.jsonl"
    record_to(FakeProvider([FakeResponse(text=DSL)]), a_request(), target)

    lines = target.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0]) | {"cassette": 99}
    target.write_text("\n".join([json.dumps(header), *lines[1:]]) + "\n", encoding="utf-8")

    with pytest.raises(CassetteMismatchError, match="format 99"):
        CassetteProvider(target)


def _example_recipe() -> tuple[LLMProvider, Request]:
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "recipes" / "example_section.py"
    spec = importlib.util.spec_from_file_location("example_section", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build: object = module.build
    assert callable(build)
    result = build()
    assert isinstance(result, tuple)
    return result
