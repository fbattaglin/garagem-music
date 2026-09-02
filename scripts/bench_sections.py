"""Measures Phase 3's exit criteria against the real API, one section-shot at a time.

    uv run python scripts/bench_sections.py                  # estimate only, spends nothing
    uv run python scripts/bench_sections.py --yes --runs 30  # measures, spends real money

Same shape as `scripts/bench_latency.py`, deliberately: estimate first, refuse without
`--yes`, append to a JSONL, render a report. The arithmetic lives in `obs/sections.py`
and is pure, so the default test suite checks it without a network — which is the same
split that let the Phase 0 rig be tested offline.

What each run records is one section-shot end to end: the request, the stream, the
incremental parse, the realise, the validator, and the repairer. Every number the phase
is judged on comes out of that one path, so a number here is a number about the system
rather than about a stage of it.

**Nothing goes out without `--yes`.** The default prints what the run would cost and
stops. The estimate is pessimistic on purpose — it assumes every call fills `max_tokens`,
which no call does — so thirty sections quotes at ~$0.68 and costs about $0.12 in
practice: Phase 0 measured a section at ~340 output tokens against a 2048 ceiling.

**A bad sample is a sample.** A refusal, a timeout, a response in prose — all of them are
rows in the log, because the denominator is every section asked for. Pruning the
inconvenient ones is how a 60% conformance rate becomes a 95% one on paper.

Briefings are drawn from `engines.arranger`, seeded, so the sample covers the space the
system actually generates: intros and choruses, four bars and eight, every feel. A rate
measured on one hand-picked verse is a fact about that verse.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from garagem.agents import request_for, structural
from garagem.agents.section import deadline_for, worth_asking
from garagem.domain import Feel, Section
from garagem.dsl import SectionStream, StringField, realise
from garagem.dsl.errors import DslError
from garagem.engines import SongBrief, arrange
from garagem.llm import (
    AnthropicAdapter,
    BreakerPolicy,
    Budget,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    ProviderError,
    Usage,
    load_catalog,
    prices_of,
    usage_after_cancellation,
)
from garagem.obs import Shot, append_shot, load_shots
from garagem.obs.sections import render_report
from garagem.theory import repair, validate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "config" / "models.toml"
DEFAULT_LOG = ROOT / "bench" / "sections.jsonl"
DEFAULT_REPORT = ROOT / "docs" / "architecture" / "section-report.md"

# Enough form to draw thirty varied briefings from without repeating one twice running.
BRIEF_SECONDS = 600.0

TEMPOS = (110.0, 132.0, 96.0, 150.0)


def briefings(count: int, seed: int) -> list[Section]:
    """A varied sample from the arranger, seeded. Intros and choruses, 4 bars and 8.

    Drawn from what the system actually generates rather than hand-picked: a conformance
    rate measured on one comfortable verse is a fact about that verse.
    """
    out: list[Section] = []
    for index in range(count):
        brief = SongBrief(
            key=(index * 5) % 12,
            scale="minor" if index % 3 else "major",
            # A grid, not two cycles of the same period. The first version stepped both
            # `bpm` and `feel` by `index % 4`, so every 150 BPM sample was also a halftime
            # one — and when four samples failed, the run could not say which variable
            # they belonged to. They were the feel's. Sixteen combinations, covered in the
            # first sixteen samples.
            bpm=TEMPOS[index % len(TEMPOS)],
            feel=list(Feel)[(index // len(TEMPOS)) % len(Feel)],
            minimum_seconds=BRIEF_SECONDS,
        )
        form = arrange(brief, seed + index)
        out.append(form[index % len(form)])
    return [section for section in out if worth_asking(section)][:count]


def estimate_usd(model: ModelSpec, runs: int) -> Decimal:
    """Pessimistic: every run fills `max_tokens`, which no run ever does."""
    prompt_tokens = 700  # the stable block plus a briefing, measured in Phase 0
    return runs * (
        model.price.input_usd * Decimal(prompt_tokens) / Decimal(1_000_000)
        + model.price.output_usd * Decimal(model.max_tokens) / Decimal(1_000_000)
    )


async def one_shot(
    provider: LLMProvider,
    section: Section,
    model: ModelSpec,
    seed: int,
    *,
    arranged: bool = False,
    dense: bool = False,
    positions: bool = True,
) -> Shot:
    """One section-shot, measured end to end. Never raises: a failure is a row."""
    request = request_for(section, model, arranged=arranged, dense=dense, positions=positions)
    started = time.monotonic()
    ttft: float | None = None
    stream = SectionStream(section)
    decoder = StringField()
    usage = Usage()
    # Counted as it goes past: a cancelled stream cannot be asked afterwards what it wrote.
    produced = 0

    base = {
        "at": datetime.now(UTC),
        "model": model.id,
        "section": section.name,
        "bars": section.bars,
        "bpm": section.bpm,
        "deadline_s": deadline_for(section),
    }

    try:
        async for event in provider.stream(request):
            if ttft is None:
                ttft = time.monotonic() - started
            stream.feed(event)
            if event.type == "tool_input_delta":
                decoder.feed(event.fragment)
                produced += len(event.fragment)
            if event.type == "text_delta":
                produced += len(event.text)
            if event.type == "done":
                usage = event.usage
    except (ProviderError, DslError) as error:
        # A stream that reached its first token generated tokens, and generated tokens are
        # billed. `Usage` only rides the `done` event, which a cancelled stream never
        # sends, so the rig reconstructs it from the prompt and from what arrived. The row
        # stays flagged `unpriced`, which now means *inferred* rather than *unknown*: over
        # four rounds this file recorded $0.0000 for calls that cost money (§14).
        spent = usage_after_cancellation(request, produced) if ttft is not None else Usage()
        return Shot(
            **base,
            ok=False,
            error=f"{type(error).__name__}: {error}"[:200],
            ttft_s=ttft,
            total_s=time.monotonic() - started,
            unpriced=ttft is not None,
            input_tokens=spent.input_tokens,
            output_tokens=spent.output_tokens,
            cost_usd=model.price.cost_of(spent),
        )

    total = time.monotonic() - started
    parsed = stream.result()
    # Everything the model actually wrote, before anything interprets it. See `Shot.dsl`.
    dsl = decoder.value()
    score = realise(parsed, seed)
    found = [*parsed.violations, *validate(score)]
    violations = [violation.rule for violation in found]
    repaired, left = repair(score)

    return Shot(
        **base,
        ttft_s=ttft,
        total_s=total,
        violations=tuple(sorted(set(violations))),
        details=tuple(violation.detail[:160] for violation in found),
        dsl=dsl,
        parts=len(score.parts),
        truncated=parsed.truncated,
        repaired=repaired != score,
        left_after_repair=tuple(sorted({violation.rule for violation in left})),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=model.price.cost_of(usage),
    )


async def measure(
    provider: LLMProvider,
    sections: list[Section],
    model: ModelSpec,
    log: Path,
    *,
    gap_s: float,
    seed: int,
    arranged: bool = False,
    dense: bool = False,
    positions: bool = True,
) -> list[Shot]:
    shots: list[Shot] = []
    for index, section in enumerate(sections):
        shot = await one_shot(
            provider,
            section,
            model,
            seed + index,
            arranged=arranged,
            dense=dense,
            positions=positions,
        )
        append_shot(log, shot)
        shots.append(shot)
        mark = "ok" if shot.conformant else ("FAIL" if not shot.ok else "off-spec")
        detail = (
            shot.error
            if not shot.ok
            else f"{shot.total_s:.2f}s ({shot.deadline_fraction:.2f}x) "
            f"{len(shot.violations)} violation(s) ${shot.cost_usd:.4f}"
        )
        sys.stderr.write(
            f"  [{mark}] {index + 1}/{len(sections)} {section.name} "
            f"{section.bars} bars @{section.bpm:g}: {detail}\n"
        )
        if gap_s and index + 1 < len(sections):
            await asyncio.sleep(gap_s)
    return shots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--gap-s",
        type=float,
        default=1.0,
        help="pause between calls, so a burst does not look like a rate limit.",
    )
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("2.00"))
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="re-render the report from what is already logged. Sends nothing.",
    )
    parser.add_argument(
        "--arranged",
        action="store_true",
        help="ask for one bar-level line per bar, arranged — a crash on bar 1, a fill in "
        "the last. Doubles the output; whether it fits the deadline is what this measures.",
    )
    parser.add_argument(
        "--dense",
        action="store_true",
        help="state what dyn is for. The model's density does not move with dyn over 85 "
        "sections; whether saying so moves it is what this measures.",
    )
    parser.add_argument(
        "--grid",
        action="store_true",
        help="write a bar as a 16-character grid instead of the slots that are struck. "
        "The notation every measurement before 2026-09-01 used; kept so the comparison "
        "can be re-run, not because it is better.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="actually make the calls. Without it, the run only estimates the cost.",
    )
    args = parser.parse_args()

    catalog = load_catalog(args.catalog)
    model = structural(catalog)

    if not args.report_only:
        sections = briefings(args.runs, args.seed)
        estimate = estimate_usd(model, len(sections))
        sys.stderr.write(
            f"{len(sections)} section(s) against {model.id} - at most ~${estimate:.2f} "
            "(pessimistic: assumes every call fills max_tokens)\n"
        )
        if not args.yes:
            sys.stderr.write("nothing sent. Re-run with --yes to measure.\n")
            return 0
        if estimate > args.budget_usd:
            sys.stderr.write(
                f"refusing: ~${estimate:.2f} is over the ${args.budget_usd} budget. "
                "Lower --runs or raise --budget-usd deliberately.\n"
            )
            return 1

        provider = GuardedProvider(
            AnthropicAdapter.from_env(),
            governor=Governor(
                Budget(
                    session_usd=args.budget_usd,
                    per_minute_usd=args.budget_usd,
                    prices=prices_of(catalog),
                )
            ),
            breaker=CircuitBreaker(BreakerPolicy()),
        )
        asyncio.run(
            measure(
                provider,
                sections,
                model,
                args.log,
                gap_s=args.gap_s,
                seed=args.seed,
                arranged=args.arranged,
                dense=args.dense,
                positions=not args.grid,
            )
        )

    shots = load_shots(args.log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # `drawn` only means something for a log this invocation filled: an accumulated log
    # spans rounds with different `MIN_DEADLINE_S`, and the report says so rather than
    # quoting a denominator it cannot stand behind.
    args.out.write_text(
        render_report(shots, drawn=None if args.report_only else args.runs), encoding="utf-8"
    )
    sys.stderr.write(f"\n{args.out}: report over {len(shots)} sample(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
