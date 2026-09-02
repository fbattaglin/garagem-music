"""Latency rig: measures TTFT per model, on this link, at this time of day.

Phase 0's exit criterion asks for p50/p95/p99 TTFT per model measured on the real link
at no fewer than three different times of day. Section 4.2 is blunt about why: the p99
is 2-5x the p50 and "this is the enemy, not the p50". Everything downstream - the
two-section lookahead, the 40% deadline, the choice of model per layer - is sized on
numbers this script produces.

    uv run python scripts/bench_latency.py                  # estimate only, spends nothing
    uv run python scripts/bench_latency.py --yes --runs 5   # measures, spends real money
    uv run python scripts/bench_latency.py --report-only    # re-renders from the log

This is the third file in the project that talks to the network on purpose, and the
only one that does it repeatedly. Consequently:

- **Nothing goes out without `--yes`.** The default run prints what it would cost and
  stops.
- **Every call goes through the governor and the breaker**, like any other call in the
  system (`.claude/rules/llm-calls.md`) - a bench script is exactly the 2 a.m. script
  that rule exists for. The session cap is the real fuse here.
- **Calls are serial.** Concurrency would measure our own queueing, not the provider's.
- **The deadline is generous, and deliberately not the section deadline.** We are
  measuring the distribution, not playing over it; the report then says how much of
  that distribution a real 5.8 s section-shot would have thrown away.
- **A failure is a sample.** A 429 at 19:00 is precisely the datum the rig is for, so
  it is recorded rather than raised.

The log is append-only, so running this morning, afternoon and evening accumulates
into one record and the report tells you which buckets are still missing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from garagem.llm import (
    AnthropicAdapter,
    Budget,
    BudgetError,
    CircuitBreaker,
    CircuitOpenError,
    GoogleAdapter,
    Governor,
    GuardedProvider,
    LLMProvider,
    Message,
    ModelSpec,
    ProviderError,
    Request,
    Role,
    Usage,
    load_catalog,
    prices_of,
)
from garagem.obs import Sample, append_sample, load_samples, render_report

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "recipes"))

from section_brief import SYSTEM, TOOL, USER  # noqa: E402 - needs the path above

DEFAULT_CATALOG = ROOT / "config" / "models.toml"
DEFAULT_LOG = ROOT / "bench" / "latency.jsonl"
DEFAULT_REPORT = ROOT / "docs" / "architecture" / "latency-report.md"

# Generous on purpose: see the module docstring. A call cancelled at 5.8 s would be
# recorded as a failure and would hide the tail we came here to measure.
DEFAULT_DEADLINE_S = 60.0


def request_for(model: ModelSpec, deadline_s: float) -> Request:
    """The same briefing for every model - that is what makes the numbers comparable."""
    return Request(
        model=model.id,
        system=SYSTEM,
        messages=(Message(role=Role.USER, content=USER),),
        tool=TOOL,
        max_tokens=model.max_tokens,
        effort=model.effort,
        deadline_s=deadline_s,
    )


def adapter_for(provider: str) -> LLMProvider:
    if provider == "anthropic":
        return AnthropicAdapter.from_env()
    if provider == "google":
        return GoogleAdapter.from_env()
    raise SystemExit(f"unknown provider: {provider}")


async def warm(adapter: LLMProvider) -> None:
    """Open the HTTP/2 pool before the clock starts.

    Section 4.2 budgets zero for the TLS handshake, which only holds for a pool that is
    already up. Measuring the handshake once per model would fatten every p99 with a
    cost the running system does not pay.
    """
    warmer = getattr(adapter, "warm", None)
    if warmer is not None:
        await warmer()


async def measure(
    provider: LLMProvider,
    request: Request,
    model: ModelSpec,
    *,
    now: datetime,
) -> Sample:
    """One call, one sample.

    Nothing here raises. A provider failure is the datum the rig exists to capture, and
    so is one of our own refusals: a breaker that opened or a budget that ran out is a
    fact about this run, not a reason to lose the twenty samples still to come.
    """
    started = time.perf_counter()
    ttft: float | None = None
    usage = Usage()
    stop: str | None = None
    error: str | None = None

    try:
        async for event in provider.stream(request):
            if ttft is None and event.type != "done":
                ttft = time.perf_counter() - started
            if event.type == "done":
                usage = event.usage
                stop = event.stop.value
    except (ProviderError, BudgetError, CircuitOpenError) as exc:
        error = f"{type(exc).__name__}: {exc}"

    return Sample(
        at=now,
        provider=model.provider,
        model=model.id,
        effort=model.effort.value if model.effort is not None else "none",
        ttft_s=ttft,
        total_s=time.perf_counter() - started,
        output_tokens=usage.output_tokens,
        cost_usd=float(model.price.cost_of(usage)),
        stop=stop,
        error=error,
    )


def estimate_usd(models: list[ModelSpec], runs: int) -> Decimal:
    """A pessimistic estimate: every run fills `max_tokens`. It never does."""
    total = Decimal(0)
    for model in models:
        guess = Usage(
            input_tokens=len(SYSTEM + USER) // 4,
            output_tokens=model.max_tokens,
        )
        total += model.price.cost_of(guess) * runs
    return total


async def run(
    models: list[ModelSpec],
    *,
    runs: int,
    gap_s: float,
    deadline_s: float,
    log: Path,
    budget_usd: Decimal,
) -> list[Sample]:
    governor = Governor(
        Budget(
            session_usd=budget_usd,
            # A bench is serial, so a minute cannot legitimately hold much. If this
            # trips, the loop is broken, which is what the governor is for.
            per_minute_usd=budget_usd,
            max_in_flight=1,
            prices=prices_of(models),
        )
    )
    # One breaker per provider, not one for the run: the breaker tracks a provider's
    # health, and Gemini being rate-limited says nothing about Anthropic. A single
    # shared breaker would blank the measurements of a provider that was working fine.
    breakers: dict[str, CircuitBreaker] = {}
    samples: list[Sample] = []

    for model in models:
        adapter = adapter_for(model.provider)
        breaker = breakers.setdefault(model.provider, CircuitBreaker())
        guarded = GuardedProvider(adapter, governor=governor, breaker=breaker)
        request = request_for(model, deadline_s)
        try:
            await warm(adapter)
            for index in range(runs):
                if index:
                    # Back-to-back calls measure the provider's rate limiter as much as
                    # its latency. A gap keeps the samples independent.
                    await asyncio.sleep(gap_s)
                sample = await measure(guarded, request, model, now=datetime.now())
                append_sample(log, sample)
                samples.append(sample)
                mark = "ok" if sample.ok else "FAIL"
                detail = (
                    f"ttft {sample.ttft_s:.2f}s total {sample.total_s:.2f}s "
                    f"{sample.output_tokens} tok ${sample.cost_usd:.4f}"
                    if sample.ok and sample.ttft_s is not None
                    else (sample.error or "no content")
                )
                sys.stderr.write(f"  [{mark}] {model.id} {index + 1}/{runs}: {detail}\n")
        finally:
            closer = getattr(adapter, "aclose", None)
            if closer is not None:
                await closer()

    snapshot = governor.snapshot()
    sys.stderr.write(f"\nspent: ${snapshot.spent_usd:.4f} of ${budget_usd} budgeted\n")
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--gap-s", type=float, default=1.0)
    parser.add_argument("--deadline-s", type=float, default=DEFAULT_DEADLINE_S)
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal("1.00"))
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="measure only this model id; repeatable",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="re-render the report from the existing log, without calling anything",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="actually make the calls. Without it, the run only estimates the cost.",
    )
    args = parser.parse_args()

    models = load_catalog(args.catalog)
    if args.model:
        wanted = set(args.model)
        models = [m for m in models if m.id in wanted]
        if not models:
            raise SystemExit(f"no configured model matches {sorted(wanted)}")

    if not args.report_only:
        estimate = estimate_usd(models, args.runs)
        sys.stderr.write(
            f"{len(models)} model(s) x {args.runs} run(s) - at most ~${estimate:.2f} "
            f"(pessimistic: assumes every call fills max_tokens)\n"
        )
        if not args.yes:
            sys.stderr.write("nothing sent. Re-run with --yes to measure.\n")
            return 0
        if estimate > args.budget_usd:
            raise SystemExit(
                f"estimate ${estimate:.2f} exceeds --budget-usd {args.budget_usd}; "
                "lower --runs or raise the budget deliberately"
            )
        asyncio.run(
            run(
                models,
                runs=args.runs,
                gap_s=args.gap_s,
                deadline_s=args.deadline_s,
                log=args.log,
                budget_usd=args.budget_usd,
            )
        )

    samples = load_samples(args.log)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_report(samples), encoding="utf-8")
    sys.stderr.write(f"{args.out}: report over {len(samples)} sample(s)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
