"""The measuring loop of the latency rig, exercised against the fake provider.

The rig spends real money the moment it runs, so its logic is checked here, offline,
where a mistake costs nothing. Two things matter: that a provider failure becomes a
recorded sample rather than an exception that ends the run, and that the money gate in
front of the whole thing cannot be walked past by accident.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from garagem.llm import (
    Effort,
    FakeProvider,
    FakeResponse,
    LLMProvider,
    ModelPrice,
    ModelSpec,
    ProviderUnavailableError,
    StopReason,
    Usage,
)
from garagem.obs import Sample

ROOT = Path(__file__).resolve().parents[2]


def _load_bench() -> ModuleType:
    path = ROOT / "scripts" / "bench_latency.py"
    spec = importlib.util.spec_from_file_location("bench_latency", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_latency"] = module
    spec.loader.exec_module(module)
    return module


bench = _load_bench()

PRICE = ModelPrice(input_usd=Decimal("5"), output_usd=Decimal("25"), cache_read_usd=Decimal("0.5"))
MODEL = ModelSpec(
    provider="anthropic",
    id="claude-opus-5",
    effort=Effort.HIGH,
    max_tokens=2048,
    price=PRICE,
)

RESPONSE = FakeResponse(
    tool_name="write_section",
    tool_input='{"dsl": "SEC verse bars=8 key=Em"}',
    stop=StopReason.TOOL_USE,
    usage=Usage(input_tokens=500, output_tokens=800),
)


def measure(provider: LLMProvider, model: Any = MODEL) -> Sample:
    request = bench.request_for(model, 30.0)
    sample = asyncio.run(bench.measure(provider, request, model, now=datetime(2026, 8, 30, 9)))
    assert isinstance(sample, Sample)
    return sample


class TestMeasure:
    def test_it_records_the_time_to_the_first_content_event(self) -> None:
        sample = measure(FakeProvider([RESPONSE], ttft_s=0.02))
        assert sample.ok
        assert sample.ttft_s is not None
        # TTFT is when content appeared, not when the call ended.
        assert 0.02 <= sample.ttft_s <= sample.total_s

    def test_it_reads_the_usage_and_prices_it(self) -> None:
        sample = measure(FakeProvider([RESPONSE]))
        assert sample.output_tokens == 800
        # 500 in at $5/MTok + 800 out at $25/MTok
        assert sample.cost_usd == pytest.approx(0.0225)
        assert sample.stop == "tool_use"

    def test_a_provider_failure_becomes_a_sample_not_an_exception(self) -> None:
        sample = measure(
            FakeProvider([RESPONSE], fail_with=ProviderUnavailableError("503 from upstream"))
        )
        assert not sample.ok
        assert sample.error is not None and "503" in sample.error
        assert sample.ttft_s is None
        # A failed call still took time, and that time is part of the picture.
        assert sample.total_s >= 0

    def test_a_local_refusal_is_recorded_instead_of_ending_the_run(self) -> None:
        """An open breaker or an exhausted budget is a fact about the run, not a crash.

        Losing the twenty samples still queued because the previous provider was rate
        limited is exactly the failure that made this a test.
        """
        from garagem.llm import Budget, CircuitBreaker, Governor, GuardedProvider

        governor = Governor(
            Budget(
                session_usd=Decimal("0.000001"),
                per_minute_usd=Decimal("1"),
                prices={MODEL.id: PRICE},
            )
        )
        guarded = GuardedProvider(
            FakeProvider([RESPONSE]), governor=governor, breaker=CircuitBreaker()
        )
        sample = measure(guarded)
        assert not sample.ok
        assert sample.error is not None and "Budget" in sample.error

    def test_the_briefing_is_the_same_for_every_model(self) -> None:
        other = ModelSpec(
            provider="google",
            id="gemini-3-pro-preview",
            effort=Effort.HIGH,
            max_tokens=2048,
            price=PRICE,
        )
        one, two = bench.request_for(MODEL, 30.0), bench.request_for(other, 30.0)
        assert one.system == two.system
        assert one.messages == two.messages
        assert one.tool == two.tool

    def test_the_bench_deadline_is_not_the_section_deadline(self) -> None:
        # Measuring under the playing deadline would cancel exactly the slow calls the
        # rig exists to observe.
        from garagem.obs.latency import SECTION_DEADLINE_S

        assert bench.DEFAULT_DEADLINE_S > SECTION_DEADLINE_S


class TestCostGate:
    def test_the_estimate_assumes_every_call_fills_max_tokens(self) -> None:
        one = bench.estimate_usd([MODEL], 1)
        assert one > Decimal("0.05")  # 2048 output tokens at $25/MTok
        assert bench.estimate_usd([MODEL], 4) == one * 4

    def test_a_dry_run_sends_nothing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log = tmp_path / "latency.jsonl"
        monkeypatch.setattr(
            sys,
            "argv",
            ["bench_latency.py", "--log", str(log), "--out", str(tmp_path / "r.md")],
        )
        monkeypatch.setattr(
            bench,
            "run",
            lambda *a, **k: pytest.fail("a run without --yes must not call anything"),
        )
        assert bench.main() == 0
        assert "nothing sent" in capsys.readouterr().err
        assert not log.exists()
