"""Rehearses a generated, conducted performance offline, and predicts what it will cost.

    uv run python scripts/rehearse_session.py                       # 8 minutes, conducted
    uv run python scripts/rehearse_session.py --conduct none        # nobody at the MiniLab
    uv run python scripts/rehearse_session.py --conduct pads --latency-beats 13

Stage 6 closes Phase 4 with one paid session, judged against criteria written down before
it runs. Rehearsing it first is what found that a conducted session spent a third to a half
of its calls on sections already written into Live (`phase-4-findings.md` §12). Its
predictions were also written down before any money was spent. They are only worth
something if anyone can run the rehearsal again, so it lives here and not in a scratch file.

**What is real:**

- the scheduler, the producer, the buffer, the shared plan and the cue queue;
- the governor, with `config/budget.toml` and the prices in `config/models.toml`;
- the report `scripts/jam.py` prints after a generated run.

**What is not:**

- **Live.** A fake one, where a write costs nothing, so no cue here misses its bar by
  landing behind a two-second write the way a real one can.
- **The model.** It is a perfect one. It answers every briefing `--latency-beats` after it
  is asked, and bills the usage Phase 3 measured for a section: 300 tokens in, 228 out.

**The conducting is real.** It replays the pad strikes and knob positions of the last `--runs`
conducted performances in `bench/jam.jsonl`, at the beats they arrived. The runs are played
one after another until the song ends. `end` is dropped, because an 8-minute rehearsal that
stops at minute three predicts nothing. `--conduct pads` keeps only the pads,
`--conduct knobs` only the knobs.

No network, no Live, no money.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import Final

from garagem.agents import Producer, structural
from garagem.daw import FakeDawAdapter
from garagem.domain import BEATS_PER_BAR, Control, Cue, CueKind, Feel, Instrument, Macro
from garagem.dsl import brief, serialize_section
from garagem.engines import SongBrief, arrange, endings_for, play_section, with_climax
from garagem.llm import (
    BreakerPolicy,
    CircuitBreaker,
    FakeProvider,
    FakeResponse,
    Governor,
    GuardedProvider,
    Request,
    StopReason,
    StreamEvent,
    Usage,
    load_budget,
    load_catalog,
    prices_of,
)
from garagem.obs import Event, EventLog, load_events, model_share, performance_checks, render_checks
from garagem.transport import BarClock, CueQueue, FormPlan, Scheduler, ScoreBuffer

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "bench" / "jam.jsonl"
CATALOG = ROOT / "config" / "models.toml"
BUDGET = ROOT / "config" / "budget.toml"

TRACKS: Final = {Instrument.DRUMS: 0, Instrument.BASS: 1, Instrument.GUITAR: 2, Instrument.KEYS: 3}
# The Set's layout (ADR-022), as `session.toml` names it.
CANDIDATES: Final = {"chorus": 2}
VARIANTS: Final = {"stop": {0: 4, 1: 5}, "fill": {0: 6, 1: 7}}
BPM: Final = 132.0
# Measured by `bench_sections.py` over nine rounds of 30 sections (`bench/sections-*.jsonl`).
SECTION_USAGE: Final = Usage(input_tokens=300, output_tokens=228)
# p50 3 to 4 s at 132 BPM, which is about eight beats.
LATENCY_BEATS: Final = 8
# Enough turns of the event loop for a stream to be parsed and published inside one beat.
STEPS_PER_BEAT: Final = 200
STYLES: Final = ("all", "pads", "knobs", "none")

Strikes = dict[int, list[Control]]


# ------------------------------------------------------------------------- the conducting


def conducted_runs(events: Sequence[Event], runs: int) -> list[list[Event]]:
    """The last `runs` performances in a jam log that received any control, oldest first."""
    split: list[list[Event]] = []
    for event in events:
        if event.kind == "scene_fired" and event.detail.get("first"):
            split.append([])
        if split:
            split[-1].append(event)
    conducted = [run for run in split if any(e.kind == "cue_received" for e in run)]
    return conducted[-runs:] if runs else []


def conducting(runs: Sequence[Sequence[Event]], style: str, until_beat: int) -> Strikes:
    """What arrives at which beat: the runs one after another, repeated, `end` left out."""
    strikes: Strikes = {}
    if style == "none" or not runs:
        return strikes
    offset = 0
    while offset < until_beat:
        for run in runs:
            for event in run:
                if event.kind != "cue_received":
                    continue
                control = _control(event)
                if control is None or not _kept(control, style):
                    continue
                strikes.setdefault(offset + int(event.at_beats), []).append(control)
            offset += int(max(played.at_beats for played in run) + BEATS_PER_BAR)
    return strikes


def _control(event: Event) -> Control | None:
    detail = event.detail
    if "cue" in detail:
        kind = CueKind(str(detail["cue"]))
        return None if kind is CueKind.END else Cue(kind=kind)
    return Macro.model_validate({"kind": detail["macro"], "value": detail["value"]})


def _kept(control: Control, style: str) -> bool:
    return style == "all" or (style == "pads") == isinstance(control, Cue)


# ------------------------------------------------------------------------------ the model


class PerfectModel:
    """Answers any briefing in the current plan, `latency_beats` after it was asked."""

    name = "perfect"

    def __init__(
        self, plan: FormPlan, seed: int, now: Callable[[], int], latency_beats: int
    ) -> None:
        self._plan = plan
        self._seed = seed
        self._now = now
        self._latency = latency_beats
        self.calls = 0

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        content = request.messages[0].content
        # Captured when asked: a model answers the briefing it was sent, however stale.
        section = next(s for s in self._plan.sections() if brief(s) == content)
        due = self._now() + self._latency
        while self._now() < due:
            await asyncio.sleep(0)
        response = FakeResponse(
            tool_name="write_section",
            tool_input=json.dumps({"dsl": serialize_section(play_section(section, self._seed))}),
            stop=StopReason.TOOL_USE,
            usage=SECTION_USAGE,
        )
        async for event in FakeProvider([response]).stream(request):
            yield event


# ------------------------------------------------------------------------ the performance


def rehearse(
    seconds: float, seed: int, strikes: Strikes, *, latency_beats: int = LATENCY_BEATS
) -> tuple[EventLog, int]:
    """One performance, a beat at a time. Returns its log and how many calls it made."""
    catalog = load_catalog(CATALOG)
    budget = load_budget(BUDGET)
    song = SongBrief(key=4, scale="minor", bpm=BPM, feel=Feel.STRAIGHT8, minimum_seconds=seconds)
    form = with_climax(arrange(song, seed))
    plan = FormPlan(form, endings_for(form))
    daw = FakeDawAdapter(scenes=8)
    clock = BarClock(daw)
    clock.start()
    buffer = ScoreBuffer()
    log = EventLog(None)
    queue = CueQueue(stamp=lambda: clock.beat)
    beat = 0
    model = PerfectModel(plan, seed, lambda: beat, latency_beats)
    governor = Governor(budget.fuse(prices_of(catalog)))
    provider = GuardedProvider(model, governor=governor, breaker=CircuitBreaker(BreakerPolicy()))
    producer = Producer(provider, buffer, log, plan, model=structural(catalog), seed=seed)
    scheduler = Scheduler(
        daw,
        clock,
        buffer,
        TRACKS,
        log,
        seed=seed,
        cues=queue,
        candidates=dict(CANDIDATES),
        variants={kind: dict(scenes) for kind, scenes in VARIANTS.items()},
        plan=plan,
    )

    loop = asyncio.new_event_loop()
    shot: asyncio.Task[bool] | None = None
    scheduler.begin(form, endings=endings_for(form))
    while not scheduler.finished and beat < 20_000:
        if shot is None or shot.done():
            index = producer._next_wanted()
            if index is not None:
                shot = loop.create_task(producer.produce(index))
        for _ in range(STEPS_PER_BEAT):
            loop.run_until_complete(asyncio.sleep(0))
        daw.push_beat(beat)
        for control in strikes.get(beat, []):
            queue.offer(control)
        scheduler.tick()
        beat += 1
    if shot is not None and not shot.done():
        shot.cancel()
        loop.run_until_complete(asyncio.gather(shot, return_exceptions=True))
    loop.close()

    spent = governor.snapshot()
    log.record(
        "session_ended",
        float(beat),
        finished=scheduler.finished,
        bpm=BPM,
        spent_usd=str(spent.spent_usd),
        estimated_usd=str(spent.estimated_usd),
        target_usd=str(budget.target_usd),
        cap_usd=str(budget.session_usd),
        killed=spent.killed,
    )
    return log, model.calls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=480.0)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--conduct", choices=STYLES, default="all")
    parser.add_argument("--latency-beats", type=int, default=LATENCY_BEATS)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help="where the conducting is")
    parser.add_argument("--runs", type=int, default=3, help="how many conducted runs to replay")
    args = parser.parse_args()

    runs = conducted_runs(load_events(args.log), args.runs) if args.conduct != "none" else []
    if args.conduct != "none" and not runs:
        sys.stderr.write(f"no conducted performance in {args.log} to replay\n")
        return 1
    until = int(args.seconds * BPM / 60) * 2
    strikes = conducting(runs, args.conduct, until)
    log, calls = rehearse(args.seconds, args.seed, strikes, latency_beats=args.latency_beats)

    arrived = sum(len(controls) for controls in strikes.values())
    sys.stderr.write(
        f"rehearsed {args.seconds:g}s, seed {args.seed}, conducted: {args.conduct} "
        f"({arrived} controls from {len(runs)} runs), a model {args.latency_beats} beats slow\n"
    )
    sys.stderr.write(render_checks(performance_checks(log.events), model_share(log.events)))
    sys.stderr.write(f"  {calls} calls to the model\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
