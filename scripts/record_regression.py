"""Records the musical regression set, or replays it. Recording is paid and run by hand.

    uv run python scripts/record_regression.py            # estimate only, spends nothing
    uv run python scripts/record_regression.py --yes      # records, spends real money
    uv run python scripts/record_regression.py --replay   # the report, from the cassettes

ADR-000 names the risk: a provider changes a pinned model's behaviour, and nothing says so.
The answer it gave is a musical regression suite in CI, against cassettes. CI holds no key and
may not spend, so it cannot ask the model anything. What it can do is judge a recording
(`phase-4-findings.md` §13):

- **The set.** Phase 3's last measured population, `bench_sections.briefings(30, 7)`: 29
  eight-bar sections across four tempos and every feel. It is the population the conformance
  and approval criteria were met on, so the two can be compared.
- **Recording.** One cassette a section, made with the request the producer sends
  (`request_for`), into `cassettes/regression/`. `set.json` beside them names each
  briefing, its seed, and any call that failed. A failure is a sample (P7): it is not
  recorded again, and it counts against the rates.
- **Replaying.** Each cassette goes through the path Phase 3 was judged on (`one_shot`):
  the incremental parse, the realise, the validator and the repairer. The result is scored
  with the arithmetic of `obs/sections.py`.
- **`tests/regression/`** runs in CI on every push, and fails three ways:
  - the prompt no longer matches the recording;
  - conformance or approval falls under Phase 3's targets;
  - what the system makes of a recording changes. Each section's realised score and the
    set's summary are golden files.

**Drift is detected when someone records again.** Re-record with `--yes`, run
`tests/regression/`, and read what failed:

- a target missed is drift past the bar the phase was closed on;
- a golden diff is what the model now plays differently.

Nothing continuous is claimed. Watching the model between recordings would need a key in CI,
and the CI design refuses one.

**Nothing goes out without `--yes`.** The estimate is pessimistic: it assumes every call
fills `max_tokens`. 29 sections quote about $0.66 and cost about $0.10.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import sys
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Final

from pydantic import BaseModel, ConfigDict

from garagem.agents import deadline_for, request_for, structural
from garagem.domain import Section, SectionScore
from garagem.dsl import parse_section, realise, serialize_score, serialize_section
from garagem.engines import coherence_of
from garagem.llm import (
    AnthropicAdapter,
    Budget,
    CassetteProvider,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    LLMProvider,
    ModelSpec,
    ProviderError,
    Request,
    StreamEvent,
    load_catalog,
    prices_of,
    record,
)
from garagem.obs import Shot
from garagem.obs.sections import Report, summarise
from garagem.theory import repair

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "models.toml"
DEFAULT_DIR = ROOT / "cassettes" / "regression"
SET_FILE = "set.json"

# Phase 3's closing population, drawn exactly as `bench_sections.py` drew it.
DRAWN: Final = 30
SEED: Final = 7
BUDGET_USD: Final = Decimal("0.50")
METRIC_DECIMALS: Final = 3

OneShot = Callable[[LLMProvider, Section, ModelSpec, int], Coroutine[object, object, Shot]]


class Recorded(BaseModel):
    """One briefing of the set: what was asked, and what came of asking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    section: Section
    seed: int
    # Why the call produced no cassette. Empty when it did.
    failed: str = ""


class RegressionSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    recorded_on: date
    drawn: int
    briefings: tuple[Recorded, ...]


# ------------------------------------------------------------------------------ the set


@cache
def _bench() -> ModuleType:
    """`scripts/bench_sections.py`, loaded by path: one draw and one shot, not copies."""
    spec = importlib.util.spec_from_file_location(
        "bench_sections", ROOT / "scripts" / "bench_sections.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("bench_sections", module)
    spec.loader.exec_module(module)
    return module


def the_set() -> list[tuple[str, Section, int]]:
    """Every briefing with its id and its seed, in the order it is recorded."""
    briefings: Callable[[int, int], list[Section]] = _bench().briefings
    return [
        (f"{index:02d}-{section.name}-{section.feel}-{section.bpm:g}", section, SEED + index)
        for index, section in enumerate(briefings(DRAWN, SEED))
    ]


def cassette_of(folder: Path, entry: Recorded) -> Path:
    return folder / f"{entry.id}.jsonl"


def load_set(folder: Path) -> RegressionSet:
    return RegressionSet.model_validate_json((folder / SET_FILE).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- recording


async def record_set(provider: LLMProvider, model: ModelSpec, folder: Path) -> RegressionSet:
    """One call a briefing, in order, never repeated. A failure is written down, not retried."""
    briefings: list[Recorded] = []
    for id_, section, seed in the_set():
        entry = Recorded(id=id_, section=section, seed=seed)
        try:
            await record(
                provider,
                request_for(section, model),
                cassette_of(folder, entry),
                note=id_,
                name="anthropic",
            )
        except ProviderError as error:
            entry = entry.model_copy(update={"failed": f"{type(error).__name__}: {error}"[:200]})
        briefings.append(entry)
        sys.stderr.write(f"  {id_}: {entry.failed or 'recorded'}\n")
    recorded = RegressionSet(
        model=model.id,
        recorded_on=datetime.now(UTC).date(),
        drawn=DRAWN,
        briefings=tuple(briefings),
    )
    folder.mkdir(parents=True, exist_ok=True)
    (folder / SET_FILE).write_text(recorded.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return recorded


# ----------------------------------------------------------------------------- replaying


def mismatched(folder: Path, recorded: RegressionSet, model: ModelSpec) -> list[str]:
    """Briefings whose cassette was recorded for a request the producer no longer sends."""
    return [
        entry.id
        for entry in recorded.briefings
        if not entry.failed
        and CassetteProvider(cassette_of(folder, entry)).header.fingerprint
        != request_for(entry.section, model).fingerprint()
    ]


def replay(folder: Path, recorded: RegressionSet, model: ModelSpec) -> list[Shot]:
    """Every briefing as a Phase 3 shot, from its cassette. Offline, and free."""
    one_shot: OneShot = _bench().one_shot
    shots: list[Shot] = []
    # One loop for the whole replay, as `tests/unit/test_ab_section.py` asks of every script.
    with asyncio.Runner() as runner:
        for entry in recorded.briefings:
            if entry.failed:
                shots.append(_failed(entry, model, recorded.recorded_on))
                continue
            provider = CassetteProvider(cassette_of(folder, entry))
            shots.append(runner.run(one_shot(provider, entry.section, model, entry.seed)))
    return shots


def played(folder: Path, entry: Recorded, model: ModelSpec) -> SectionScore | None:
    """What the system makes of one recording: realised, then repaired. `None` if unplayable."""
    if entry.failed:
        return None
    provider = CassetteProvider(cassette_of(folder, entry))
    events = asyncio.run(_drain(provider, request_for(entry.section, model)))
    repaired, left = repair(realise(parse_section(events, entry.section), entry.seed))
    return None if left or not repaired.parts else repaired


def rendered(score: SectionScore | None) -> str:
    """One section's golden file: the notation of what plays, and a digest of every note.

    The notation is what a diff can be read in. The digest catches the change it cannot
    show, a velocity or a humanised onset, without committing every note of 29 sections.
    """
    if score is None:
        return "unplayable\n"
    every_note = serialize_score(score).encode("utf-8")
    counts = " ".join(f"{part.instrument}={len(part.notes)}" for part in score.parts)
    return f"# {counts}; notes sha256 {hashlib.sha256(every_note).hexdigest()[:16]}\n" + (
        serialize_section(score)
    )


def summary(
    recorded: RegressionSet, shots: Sequence[Shot], scores: Sequence[SectionScore | None]
) -> str:
    """The set on one page: the rates, then a line a section. A golden file, so a diff."""
    report = summarise(shots, drawn=recorded.drawn)
    rules = ", ".join(f"{rule} x{count}" for rule, count in report.by_rule.items())
    lines = [
        f"model {recorded.model}, {report.n} of {recorded.drawn} briefings asked",
        f"failures {report.failures}",
        f"conformance {_rate(report.conformance)}",
        f"approval {_rate(report.approval)}",
        f"usable {_rate(report.usable)}",
        f"violations {rules or 'none'}",
        "",
    ]
    for entry, shot, score in zip(recorded.briefings, shots, scores, strict=True):
        lines.append(f"{entry.id}: {_verdict(shot)}{_measured(score)}")
    return "\n".join(lines) + "\n"


def missed_targets(report: Report) -> list[str]:
    """Which of Phase 3's targets a recording misses. Empty when it meets both."""
    missed = []
    if not report.conformance_met:
        missed.append(f"conformance {_rate(report.conformance)}")
    if not report.approval_met:
        missed.append(f"approval {_rate(report.approval)}")
    return missed


async def _drain(provider: CassetteProvider, request: Request) -> list[StreamEvent]:
    return [event async for event in provider.stream(request)]


def _failed(entry: Recorded, model: ModelSpec, on: date) -> Shot:
    return Shot(
        at=datetime(on.year, on.month, on.day, tzinfo=UTC),
        model=model.id,
        section=entry.section.name,
        bars=entry.section.bars,
        bpm=entry.section.bpm,
        ok=False,
        error=entry.failed,
        deadline_s=deadline_for(entry.section),
    )


def _verdict(shot: Shot) -> str:
    if not shot.ok:
        return f"failed ({shot.error.split(':')[0]})"
    found = "conformant" if shot.conformant else "violations " + ",".join(shot.violations)
    return found + (", repaired" if shot.repaired else "") + f", {shot.parts} parts"


def _measured(score: SectionScore | None) -> str:
    if score is None:
        return ""
    notes = " ".join(f"{part.instrument}={len(part.notes)}" for part in score.parts)
    collision = coherence_of(score).kit_collision
    return f"; {notes}; kit_collision={collision:.{METRIC_DECIMALS}f}"


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


# ---------------------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--replay", action="store_true", help="report on the cassettes; free")
    parser.add_argument("--yes", action="store_true", help="actually record; spends money")
    args = parser.parse_args()

    catalog = load_catalog(CATALOG)
    model = structural(catalog)

    if args.replay:
        recorded = load_set(args.dir)
        stale = mismatched(args.dir, recorded, model)
        if stale:
            sys.stderr.write(f"recorded for another prompt: {', '.join(stale)}. Record again.\n")
            return 1
        shots = replay(args.dir, recorded, model)
        scores = [played(args.dir, entry, model) for entry in recorded.briefings]
        sys.stderr.write(summary(recorded, shots, scores))
        missed = missed_targets(summarise(shots, drawn=recorded.drawn))
        sys.stderr.write(
            f"misses Phase 3's targets: {', '.join(missed)}\n"
            if missed
            else "meets Phase 3's targets\n"
        )
        return 1 if missed else 0

    count = len(the_set())
    estimate: Decimal = _bench().estimate_usd(model, count)
    sys.stderr.write(
        f"{count} section(s) against {model.id} into {args.dir} - at most ~${estimate:.2f} "
        "(pessimistic: assumes every call fills max_tokens)\n"
    )
    if not args.yes:
        sys.stderr.write("nothing sent. Re-run with --yes to record.\n")
        return 0
    provider = GuardedProvider(
        AnthropicAdapter.from_env(),
        governor=Governor(
            Budget(
                session_usd=BUDGET_USD,
                per_minute_usd=BUDGET_USD,
                max_in_flight=1,
                prices=prices_of(catalog),
            )
        ),
        breaker=CircuitBreaker(),
    )
    recorded = asyncio.run(record_set(provider, model, args.dir))
    failed = sum(1 for entry in recorded.briefings if entry.failed)
    sys.stderr.write(
        f"recorded {count - failed} of {count} into {args.dir}. Next: "
        "GARAGEM_UPDATE_GOLDEN=1 uv run pytest tests/regression -q, and read the diff.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
