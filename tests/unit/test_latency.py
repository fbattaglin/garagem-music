"""The latency rig's arithmetic, checked without a network.

The rig is the instrument that calibrates the roadmap; an instrument that lies is worse
than no instrument. These tests pin the two claims the report makes about itself: that
a percentile is a value that was really observed, and that the report says out loud
when the sample is too small or the times of day too few for the number to mean
anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from garagem.obs import Sample, bucket_of, percentile, render_report, summarise
from garagem.obs.latency import SECTION_DEADLINE_S

MORNING = datetime(2026, 8, 30, 9, 0)
AFTERNOON = datetime(2026, 8, 30, 14, 0)
EVENING = datetime(2026, 8, 30, 21, 0)


def sample(
    ttft: float | None,
    *,
    at: datetime = MORNING,
    total: float | None = None,
    model: str = "claude-opus-5",
    tokens: int = 800,
    cost: float = 0.02,
    error: str | None = None,
) -> Sample:
    return Sample(
        at=at,
        provider="anthropic",
        model=model,
        effort="high",
        ttft_s=ttft,
        total_s=total if total is not None else (ttft or 0.0) + 4.0,
        output_tokens=tokens,
        cost_usd=cost,
        stop="tool_use" if error is None else None,
        error=error,
    )


class TestPercentile:
    def test_it_returns_a_value_that_was_actually_observed(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0]
        for q in (0.5, 0.95, 0.99):
            assert percentile(values, q) in values

    def test_nearest_rank_does_not_interpolate(self) -> None:
        # The median of an even-sized sample is the lower of the two middles, not
        # their average: 2.5 s was never a real call.
        assert percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.0

    def test_p100_is_the_maximum(self) -> None:
        assert percentile([5.0, 1.0, 9.0], 1.0) == 9.0

    def test_it_refuses_an_empty_sample(self) -> None:
        with pytest.raises(ValueError, match="no values"):
            percentile([], 0.5)

    @pytest.mark.parametrize("q", [0.0, -0.1, 1.5])
    def test_it_refuses_a_quantile_outside_the_range(self, q: float) -> None:
        with pytest.raises(ValueError, match="q out of range"):
            percentile([1.0], q)


class TestBuckets:
    @pytest.mark.parametrize(
        ("hour", "expected"),
        [
            (0, "night"),
            (4, "night"),
            (5, "morning"),
            (11, "morning"),
            (12, "afternoon"),
            (17, "afternoon"),
            (18, "evening"),
            (23, "evening"),
        ],
    )
    def test_every_hour_of_the_day_lands_somewhere(self, hour: int, expected: str) -> None:
        assert bucket_of(datetime(2026, 8, 30, hour)) == expected


class TestSummarise:
    def test_a_failure_is_counted_but_does_not_pollute_the_percentiles(self) -> None:
        samples = [sample(1.0), sample(None, error="ProviderUnavailableError: 503"), sample(3.0)]
        (aggregate,) = summarise(samples)
        assert aggregate.n == 3
        assert aggregate.failures == 1
        # Percentiles are computed over the two served calls only; the failure has
        # no TTFT to contribute and must not be read as a fast one.
        assert aggregate.p50_s == 1.0
        assert aggregate.max_s == 3.0

    def test_the_tail_ratio_is_p99_over_p50(self) -> None:
        (aggregate,) = summarise([sample(1.0), sample(2.0), sample(8.0)])
        assert aggregate.p50_s == 2.0
        assert aggregate.p99_s == 8.0
        assert aggregate.tail_ratio == 4.0

    def test_models_are_aggregated_separately(self) -> None:
        aggregates = summarise([sample(1.0), sample(9.0, model="claude-haiku-4-5-20251001")])
        assert {a.model for a in aggregates} == {"claude-opus-5", "claude-haiku-4-5-20251001"}
        assert all(a.n == 1 for a in aggregates)

    def test_it_collects_the_times_of_day_covered(self) -> None:
        (aggregate,) = summarise(
            [sample(1.0, at=MORNING), sample(1.0, at=AFTERNOON), sample(1.0, at=EVENING)]
        )
        assert aggregate.buckets == ("afternoon", "evening", "morning")
        assert aggregate.covers_three_times_of_day

    def test_two_runs_in_the_same_bucket_are_not_three_times_of_day(self) -> None:
        (aggregate,) = summarise(
            [sample(1.0, at=MORNING), sample(1.0, at=MORNING + timedelta(hours=1))]
        )
        assert aggregate.buckets == ("morning",)
        assert not aggregate.covers_three_times_of_day

    def test_it_counts_the_calls_a_real_section_shot_would_have_cancelled(self) -> None:
        late = SECTION_DEADLINE_S + 1
        (aggregate,) = summarise([sample(0.5, total=1.0), sample(4.0, total=late)])
        assert aggregate.over_deadline == 1

    def test_the_decode_rate_excludes_the_time_spent_waiting(self) -> None:
        # 800 tokens in the 4 s after the first one, not in the 5 s the call took.
        (aggregate,) = summarise([sample(1.0, total=5.0, tokens=800)])
        assert aggregate.median_tokens_per_s == 200.0

    def test_cost_adds_up_across_runs(self) -> None:
        (aggregate,) = summarise([sample(1.0, cost=0.02), sample(2.0, cost=0.03)])
        assert aggregate.total_cost_usd == pytest.approx(0.05)


class TestReport:
    def test_it_says_when_the_sample_is_too_small_for_a_p99(self) -> None:
        report = render_report([sample(1.0), sample(2.0)])
        assert "p99 is the maximum observed" in report

    def test_it_names_the_times_of_day_still_missing(self) -> None:
        report = render_report([sample(1.0, at=MORNING)])
        assert "still missing" in report
        assert "afternoon" in report and "evening" in report
        assert "criterion is not met" in report

    def test_it_stops_complaining_once_three_buckets_are_covered(self) -> None:
        report = render_report(
            [sample(1.0, at=MORNING), sample(1.0, at=AFTERNOON), sample(1.0, at=EVENING)]
        )
        assert "still missing" not in report

    def test_it_flags_a_tail_worse_than_the_baseline_predicted(self) -> None:
        report = render_report([sample(1.0), sample(1.0), sample(20.0)])
        assert "above the 2-5x" in report

    def test_an_empty_log_renders_a_report_rather_than_crashing(self) -> None:
        report = render_report([])
        assert "No samples yet" in report

    def test_the_same_samples_render_the_same_bytes(self) -> None:
        samples = [sample(1.0), sample(2.0, at=EVENING)]
        assert render_report(samples) == render_report(samples)


class TestRoundTrip:
    def test_a_sample_survives_the_log(self, tmp_path: Path) -> None:
        from garagem.obs import append_sample, load_samples

        path = tmp_path / "latency.jsonl"
        append_sample(path, sample(1.5))
        append_sample(path, sample(None, error="boom"))
        loaded = load_samples(path)
        assert [s.ttft_s for s in loaded] == [1.5, None]
        assert loaded[1].error == "boom"

    def test_a_missing_log_is_empty_not_an_error(self, tmp_path: Path) -> None:
        from garagem.obs import load_samples

        assert load_samples(tmp_path / "nothing.jsonl") == []
