"""The port and the FakeProvider: determinism, accounting and failure shapes."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from conftest import Collector, text_of, tool_input_of
from garagem.llm import (
    FakeProvider,
    FakeResponse,
    LLMProvider,
    Message,
    ProviderError,
    ProviderUnavailableError,
    Request,
    Role,
    StopReason,
    ToolSchema,
    Usage,
)

TEXT = "SEC verse 8 132 Em\nDRM |x--x--x-|x--x--x-|\nBAS |E---G---|D---A---|"

TOOL = ToolSchema(
    name="write_section",
    description="Writes one section in the DSL.",
    input_schema={
        "type": "object",
        "properties": {"dsl": {"type": "string"}},
        "required": ["dsl"],
        "additionalProperties": False,
    },
)


def a_request(**extra: object) -> Request:
    base: dict[str, object] = {
        "model": "claude-opus-5",
        "messages": (Message(role=Role.USER, content="a verse in Em"),),
        "deadline_s": 5.8,
    }
    return Request.model_validate(base | extra)


def fake(*responses: FakeResponse, **kwargs: object) -> FakeProvider:
    return FakeProvider(list(responses), **kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------- determinism


def test_same_seed_produces_the_same_events(collect: Collector) -> None:
    req = a_request()
    a = collect(fake(FakeResponse(text=TEXT), seed=42), req)
    b = collect(fake(FakeResponse(text=TEXT), seed=42), req)
    assert a == b


def test_different_seeds_cut_differently_but_the_text_is_the_same(
    collect: Collector,
) -> None:
    req = a_request()
    a = collect(fake(FakeResponse(text=TEXT), seed=1), req)
    b = collect(fake(FakeResponse(text=TEXT), seed=2), req)
    assert a != b, "the delta cutting should vary with the seed"
    assert text_of(a) == text_of(b) == TEXT


def test_successive_calls_do_not_repeat_the_cutting(collect: Collector) -> None:
    """Two identical calls in the same session must not collide by accident."""
    provider = fake(FakeResponse(text=TEXT), FakeResponse(text=TEXT), seed=0)
    req = a_request()
    first = collect(provider, req)
    second = collect(provider, req)
    assert first != second
    assert text_of(first) == text_of(second)


# ------------------------------------------------------------------------ tool use


def test_fragments_reassemble_the_tool_json(collect: Collector) -> None:
    payload = {"dsl": TEXT}
    events = collect(
        fake(
            FakeResponse(
                tool_name="write_section",
                tool_input=json.dumps(payload),
                stop=StopReason.TOOL_USE,
            ),
            seed=3,
        ),
        a_request(tool=TOOL),
    )
    starts = [e for e in events if e.type == "tool_use_start"]
    assert len(starts) == 1
    assert starts[0].name == "write_section"
    assert tool_input_of(events) == payload


def test_a_lone_fragment_is_not_valid_json(collect: Collector) -> None:
    """This is why the ADR-011 parser is incremental, not a json.loads per delta."""
    events = collect(
        fake(
            FakeResponse(tool_name="write_section", tool_input=json.dumps({"dsl": TEXT})),
            seed=3,
        ),
        a_request(tool=TOOL),
    )
    fragments = [e.fragment for e in events if e.type == "tool_input_delta"]
    assert len(fragments) > 1
    with pytest.raises(json.JSONDecodeError):
        json.loads(fragments[0])


# ----------------------------------------------------------------- stop and usage


@pytest.mark.parametrize("stop", list(StopReason))
def test_every_stop_reason_arrives_in_the_final_event(collect: Collector, stop: StopReason) -> None:
    events = collect(fake(FakeResponse(stop=stop)), a_request())
    assert events[-1].type == "done"
    assert events[-1].stop is stop


def test_the_stream_always_ends_with_done(collect: Collector) -> None:
    events = collect(fake(FakeResponse(text=TEXT)), a_request())
    assert [e.type for e in events].count("done") == 1
    assert events[-1].type == "done"


def test_usage_crosses_the_port_intact(collect: Collector) -> None:
    usage = Usage(
        input_tokens=500, output_tokens=800, cache_read_tokens=2000, cache_write_tokens=120
    )
    events = collect(fake(FakeResponse(usage=usage)), a_request())
    assert events[-1].type == "done"
    assert events[-1].usage == usage


def test_billed_input_excludes_what_came_from_cache() -> None:
    usage = Usage(input_tokens=500, cache_read_tokens=2000, cache_write_tokens=120)
    assert usage.billed_input_tokens == 620


# --------------------------------------------------------------------- the request


def test_deadline_is_required() -> None:
    with pytest.raises(ValidationError, match="deadline_s"):
        Request(  # type: ignore[call-arg]
            model="claude-opus-5",
            messages=(Message(role=Role.USER, content="hi"),),
        )


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_deadline_must_be_positive(value: float) -> None:
    with pytest.raises(ValidationError):
        a_request(deadline_s=value)


def test_the_port_rejects_unknown_fields() -> None:
    """A `retries=3` here would be a P7 violation that slips through unnoticed."""
    with pytest.raises(ValidationError):
        a_request(retries=3)


def test_fingerprint_changes_with_the_prompt_and_is_stable_for_the_same_one() -> None:
    a = a_request(system="DSL rules")
    b = a_request(system="DSL rules")
    c = a_request(system="DSL rules, revised")
    assert a.fingerprint() == b.fingerprint()
    assert a.fingerprint() != c.fingerprint()


# -------------------------------------------------------------------------- failure


def test_the_fake_records_the_requests_it_saw(collect: Collector) -> None:
    provider = fake(FakeResponse(), FakeResponse())
    collect(provider, a_request(system="first"))
    collect(provider, a_request(system="second"))
    assert [r.system for r in provider.calls] == ["first", "second"]


def test_an_exhausted_fake_complains_instead_of_repeating(collect: Collector) -> None:
    provider = fake(FakeResponse())
    collect(provider, a_request())
    with pytest.raises(ProviderError, match="exhausted"):
        collect(provider, a_request())


def test_failure_in_the_middle_of_the_stream(collect: Collector) -> None:
    """The breaker needs a provider that breaks after it has already emitted."""
    provider = fake(
        FakeResponse(text=TEXT),
        seed=5,
        fail_with=ProviderUnavailableError("connection dropped"),
        fail_after=3,
    )
    with pytest.raises(ProviderUnavailableError):
        collect(provider, a_request())


def test_the_fake_satisfies_the_port() -> None:
    provider: LLMProvider = fake(FakeResponse())
    assert isinstance(provider, LLMProvider)
    assert provider.name == "fake"
