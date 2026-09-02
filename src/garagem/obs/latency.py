"""Latency rig: the arithmetic and the report, with no I/O of its own.

Phase 0 exists to produce one number that calibrates the rest of the roadmap: not the
mean TTFT, but its **tail**. Section 4.2 says the p99 of any call is 2-5x the p50 and
that "this is the enemy, not the p50", and section 7 asks for p50/p95/p99 per model, on
this link, at no fewer than three different times of day.

So this module keeps two things honest:

- **Percentiles are nearest-rank on the raw sample**, never interpolated. With the
  sample sizes a hand-run rig produces, an interpolated p99 invents a number that was
  never observed. `Aggregate` therefore carries `n` and `max_s` alongside, and the
  report says out loud when a percentile is just the maximum wearing a hat.
- **Time of day is part of the datum.** A run is stamped with the local hour and
  bucketed, and the report states whether the three-buckets criterion is actually met
  rather than leaving the reader to count rows.

Measuring lives in `scripts/bench_latency.py`; everything here is pure, which is what
lets the default test suite check it without a network.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

FROZEN = ConfigDict(frozen=True, extra="forbid")

# Local-clock buckets. Coarse on purpose: what moves TTFT is whether the provider is
# busy, and that tracks working hours, not the hour hand.
BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("night", 0, 5),
    ("morning", 5, 12),
    ("afternoon", 12, 18),
    ("evening", 18, 24),
)

REQUIRED_BUCKETS = 3

# The deadline a real section-shot would carry: 40% of the 14.5 s an 8-bar section
# lasts at 132 BPM (section 4.2). The rig itself runs with a generous deadline - we are
# measuring the distribution, not playing - but the report says how much of that
# distribution the player would have thrown away.
SECTION_DEADLINE_S = 5.8


def bucket_of(moment: datetime) -> str:
    hour = moment.hour
    for name, start, end in BUCKETS:
        if start <= hour < end:
            return name
    raise ValueError(f"unbucketable hour: {hour}")


class Sample(BaseModel):
    """One real call. Failures are recorded too - an unavailable provider is a datum."""

    model_config = FROZEN

    at: datetime
    provider: str
    model: str
    effort: str
    # Time to the first content event. This is the number the lookahead is spent
    # against; None when the call never produced one.
    ttft_s: float | None = None
    total_s: float
    output_tokens: int = 0
    cost_usd: float = 0.0
    stop: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def tokens_per_s(self) -> float | None:
        """Decode rate after the first token - the part TTFT does not explain."""
        if self.ttft_s is None or self.output_tokens == 0:
            return None
        decode_s = self.total_s - self.ttft_s
        return self.output_tokens / decode_s if decode_s > 0 else None

    @property
    def bucket(self) -> str:
        return bucket_of(self.at)


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: always a value that was actually observed."""
    if not values:
        raise ValueError("no values")
    if not 0 < q <= 1:
        raise ValueError(f"q out of range: {q}")
    ordered = sorted(values)
    rank = math.ceil(q * len(ordered))
    return ordered[rank - 1]


class Aggregate(BaseModel):
    model_config = FROZEN

    provider: str
    model: str
    n: int
    failures: int
    p50_s: float | None = None
    p95_s: float | None = None
    p99_s: float | None = None
    max_s: float | None = None
    tail_ratio: float | None = None
    median_tokens_per_s: float | None = None
    total_cost_usd: float = 0.0
    buckets: tuple[str, ...] = ()
    deadline_s: float = SECTION_DEADLINE_S
    # Calls that completed, but too late to have been usable for the section they were
    # for. A model can be excellent and still be unusable on the structural layer.
    over_deadline: int = 0

    @property
    def covers_three_times_of_day(self) -> bool:
        return len(self.buckets) >= REQUIRED_BUCKETS

    @property
    def p99_is_just_the_max(self) -> bool:
        """True when n is too small for the 99th percentile to mean anything."""
        return self.n < 100


def summarise(
    samples: Iterable[Sample], *, deadline_s: float = SECTION_DEADLINE_S
) -> list[Aggregate]:
    """One aggregate per (provider, model), in the order each model first appears."""
    grouped: dict[tuple[str, str], list[Sample]] = {}
    for sample in samples:
        grouped.setdefault((sample.provider, sample.model), []).append(sample)

    out: list[Aggregate] = []
    for (provider, model), group in grouped.items():
        served = [s for s in group if s.ok and s.ttft_s is not None]
        ttfts = [s.ttft_s for s in served if s.ttft_s is not None]
        rates = [r for s in served if (r := s.tokens_per_s) is not None]
        p50 = percentile(ttfts, 0.50) if ttfts else None
        p99 = percentile(ttfts, 0.99) if ttfts else None
        out.append(
            Aggregate(
                provider=provider,
                model=model,
                n=len(group),
                failures=sum(1 for s in group if not s.ok),
                p50_s=p50,
                p95_s=percentile(ttfts, 0.95) if ttfts else None,
                p99_s=p99,
                max_s=max(ttfts) if ttfts else None,
                # The ratio section 4.2 predicts at 2-5x. It is the point of the rig.
                tail_ratio=(p99 / p50) if p50 and p99 else None,
                median_tokens_per_s=percentile(rates, 0.50) if rates else None,
                total_cost_usd=sum(s.cost_usd for s in group),
                deadline_s=deadline_s,
                over_deadline=sum(1 for s in served if s.total_s > deadline_s),
                buckets=tuple(sorted({s.bucket for s in group})),
            )
        )
    return out


def _seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def render_report(samples: Sequence[Sample], *, deadline_s: float = SECTION_DEADLINE_S) -> str:
    """A markdown report. Reproducible: the same samples in, the same bytes out."""
    aggregates = summarise(samples, deadline_s=deadline_s)
    window = ""
    if samples:
        first = min(s.at for s in samples).isoformat(timespec="seconds")
        last = max(s.at for s in samples).isoformat(timespec="seconds")
        window = f" - window: {first} to {last}"
    lines = [
        "# Latency report - TTFT per model",
        "",
        f"Samples: **{len(samples)}**{window}",
        "",
        "TTFT in seconds, nearest-rank percentiles over successful calls.",
        "",
        "| provider | model | n | fail | p50 | p95 | p99 | max | p99/p50 "
        f"| tok/s | late@{deadline_s:g}s | $ | times of day |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in aggregates:
        coverage = f"{len(a.buckets)}/3 {'yes' if a.covers_three_times_of_day else 'no'}"
        rate = "-" if a.median_tokens_per_s is None else f"{a.median_tokens_per_s:.0f}"
        ratio = "-" if a.tail_ratio is None else f"{a.tail_ratio:.1f}x"
        lines.append(
            f"| {a.provider} | `{a.model}` | {a.n} | {a.failures} | {_seconds(a.p50_s)} "
            f"| {_seconds(a.p95_s)} | {_seconds(a.p99_s)} | {_seconds(a.max_s)} | {ratio} "
            f"| {rate} | {a.over_deadline}/{a.n - a.failures} "
            f"| {a.total_cost_usd:.4f} | {coverage} |"
        )

    lines += ["", "## Reading this", ""]
    if not aggregates:
        lines.append("- No samples yet. Run `scripts/bench_latency.py` at least three times.")
    for a in aggregates:
        if a.p99_is_just_the_max:
            lines.append(
                f"- `{a.model}`: n={a.n} < 100, so p99 is the maximum observed, not an "
                "estimate of the tail. Read `max`, and treat p95 as the honest tail."
            )
        if not a.covers_three_times_of_day:
            missing = [b for b, _, _ in BUCKETS if b not in a.buckets]
            lines.append(
                f"- `{a.model}`: covered {', '.join(a.buckets) or 'nothing'} - still missing "
                f"{', '.join(missing)}. The Phase 0 criterion is not met for this model yet."
            )
        served = a.n - a.failures
        if served and a.over_deadline:
            share = 100 * a.over_deadline / served
            lines.append(
                f"- `{a.model}`: {a.over_deadline}/{served} calls ({share:.0f}%) came back "
                f"after {a.deadline_s:g} s. A real section-shot would have cancelled those "
                "and played the deterministic part instead."
            )
        if a.tail_ratio is not None and a.tail_ratio > 5:
            lines.append(
                f"- `{a.model}`: tail ratio {a.tail_ratio:.1f}x is above the 2-5x that "
                "section 4.2 predicts. The 2-section lookahead was sized on that assumption."
            )
    lines.append("")
    return "\n".join(lines)


def append_sample(path: Path, sample: Sample) -> None:
    """Append-only: runs from different times of day accumulate into one record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(sample.model_dump_json() + "\n")


def load_samples(path: Path) -> list[Sample]:
    if not path.exists():
        return []
    return [
        Sample.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
