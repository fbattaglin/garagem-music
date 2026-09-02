"""The blind A/B: is a generated section better than a deterministic one?

    uv run python scripts/ab_section.py --pairs 12
    uv run python scripts/ab_section.py --resume        # continue where you stopped

The only question in Phase 3 that matters musically. Everything else measures whether the
model followed a grammar; this measures whether following it was worth four seconds of
latency and a network dependency. **A "no" here is the most valuable result the phase can
produce** — it would say the deterministic floor is already good enough, which is a real
answer and a cheap one.

The threshold is **8 of 12**, agreed with Fabiano on 2026-08-30, before any number
existed. That is the only time a threshold means anything.

How a pair works:

1. One briefing. Two realisations of it: one from `claude-sonnet-5`, one from
   `engines.band.play_section` with the same seed.
2. Both written into Live, into two scenes.
3. Played in an order the script chose from a seed and **does not print**.
4. You listen — as many times as you like — and say which you preferred.
5. Only then does the file record which was which.

Three rules that make the result mean something:

- **The order is hidden until the run ends.** It is stamped into the log at the moment of
  the vote, so it is recoverable and auditable, but nothing is printed to the terminal.
- **The tally appears only at the end.** An early run of A's would otherwise pull the
  rest of the answers along with it.
- **A pair whose two realisations are identical is refused**, not counted. It happens when
  a model returns nothing usable and the fallback fills every part: voting on it would be
  voting on the same music twice.

It saves after every pair, so it can be stopped and resumed. `--seconds` sets how long
each side plays; the default is one pass of an 8-bar section at the briefing's tempo.

**One event loop for the whole run**, via `asyncio.Runner`. Not a detail: the adapter
holds a persistent HTTP/2 pool (ADR-000 §7 asks for a warm one), and a pool is bound to
the loop that created it. Calling `asyncio.run()` once per pair closes that loop under
the pool, and the *second* pair dies with `RuntimeError: Event loop is closed`. A
`Runner` keeps one loop across as many `run()` calls as the listening takes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

from garagem.agents import request_for, structural
from garagem.daw import (
    AbletonOSCAdapter,
    ClipAddress,
    DawError,
    DawPort,
    OscSettings,
    diff_session,
    ensure_clip,
    load_session,
    observe,
    render_divergences,
)
from garagem.domain import Feel, Instrument, Section, SectionScore
from garagem.dsl import SectionStream, realise
from garagem.dsl.errors import DslError
from garagem.engines import SongBrief, arrange, play_section
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
    load_catalog,
    prices_of,
)
from garagem.theory import repair
from garagem.transport import render_score

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / "session.toml"
DEFAULT_CATALOG = ROOT / "config" / "models.toml"
DEFAULT_LOG = ROOT / "bench" / "ab-sections.jsonl"

# Agreed before any number existed (2026-08-30). ADR-000 §7 asks for ≥65%; 8 of 12 is 67%.
DEFAULT_PAIRS = 12
THRESHOLD = 8

SCENES = (0, 1)
BUDGET_USD = Decimal("0.50")

# How long to let each side play, when `--seconds` is not given: one whole pass, so a
# section is judged on its shape and not on its first bar.
LAUNCH_TIMEOUT_S = 4.0
POLL_S = 0.1

ROLE_TO_INSTRUMENT: dict[str, Instrument] = {
    "drums": Instrument.DRUMS,
    "bass": Instrument.BASS,
    "guitar": Instrument.GUITAR,
    "keys": Instrument.KEYS,
}


@dataclass(frozen=True, slots=True)
class Pair:
    """One briefing, realised twice. `first` is which side plays first — never printed."""

    index: int
    section: Section
    model: SectionScore
    floor: SectionScore
    first: str  # "model" or "floor"


def build_adapter(host: str, timeout_s: float) -> DawPort:
    return AbletonOSCAdapter(settings=OscSettings(host=host, timeout_s=timeout_s))


def build_provider(catalog: list[ModelSpec]) -> LLMProvider:
    return GuardedProvider(
        AnthropicAdapter.from_env(),
        governor=Governor(
            Budget(
                session_usd=BUDGET_USD,
                per_minute_usd=BUDGET_USD,
                prices=prices_of(catalog),
            )
        ),
        breaker=CircuitBreaker(BreakerPolicy()),
    )


# The twelve pairs, decided before a note is played. Two things the first two runs got
# wrong by accident rather than by choice:
#
# **halftime was unreachable.** The old rule was `feel=list(Feel)[(index // 4) % 4]`, which
# over twelve pairs only ever reaches indices 0, 1 and 2. Two whole A/B rounds covered
# three feels of four and the fourth was never a coin that came up tails — it was never
# tossed (`phase-3-findings.md` §10, §13).
#
# **the chorus split was found after the vote.** §13 noticed the model losing 1 of 6
# choruses against 6 of 6 everywhere else, at p = 0.015 on n = 12. Found afterwards, that
# is a hypothesis; fixed here beforehand, it is a test. Six choruses and six of everything
# else, alternating so a run of one kind cannot set the listener's expectations.
#
# Every feel appears exactly three times: chorus takes 0,1,2,3,0,1 and the rest take
# 2,3,0,1,2,3. All twelve are 8-bar sections, so the shortest deadline is 5.12 s at
# 150 BPM — above `MIN_DEADLINE_S`, and no pair is silently dropped for want of time.
# name, feel index, bpm — written out rather than computed, because every arithmetic
# shortcut tried here has produced a confound. `bpm=TEMPOS[index % 4]` alongside a feel
# that also cycles with period four put straight8 and shuffle at 110/132 and straight16
# and halftime at 96/150, so "the model is worse at sixteenths" and "the model is worse
# when the section is short" would have been the same column. §4 caught that once in the
# bench sample; this table is what stops it recurring here.
#
# Each feel appears three times, at three different tempos. Each tempo appears three
# times, across three different feels. Six choruses and six of everything else, alternating.
PLAN: Final[tuple[tuple[str, int, float], ...]] = (
    ("chorus", 0, 110.0),
    ("verse", 2, 110.0),
    ("chorus", 1, 132.0),
    ("verse", 3, 132.0),
    ("chorus", 2, 96.0),
    ("bridge", 0, 150.0),
    ("chorus", 3, 150.0),
    ("verse", 1, 110.0),
    ("chorus", 0, 96.0),
    ("bridge", 2, 132.0),
    ("chorus", 1, 150.0),
    ("verse", 3, 96.0),
)

# Pre-registered on 2026-09-01, before the run. Stated as a count rather than a rate so it
# cannot be reinterpreted afterwards.
CHORUS_PAIRS = sum(1 for name, _, _ in PLAN if name == "chorus")
CHORUS_THRESHOLD = 4


def briefings(count: int, seed: int) -> list[Section]:
    """The planned grid, seeded. Sections come from the arranger; which ones does not.

    `arrange` decides a whole song's form and `PLAN` picks out of it, so every briefing is
    still one the system genuinely generates — the sample is chosen, the material is not.
    """
    out: list[Section] = []
    for index in range(count):
        name, feel_index, bpm = PLAN[index % len(PLAN)]
        brief = SongBrief(
            key=(index * 5) % 12,
            scale="minor" if index % 3 else "major",
            bpm=bpm,
            feel=list(Feel)[feel_index],
            minimum_seconds=600.0,
        )
        form = arrange(brief, seed + index)
        matching = [section for section in form if section.name == name]
        if not matching:
            raise SystemExit(
                f"pair {index + 1} wanted a {name!r} and seed {seed + index} produced a form "
                f"without one: {sorted({section.name for section in form})}. "
                "Change the seed rather than the plan."
            )
        out.append(matching[0])
    return out


async def generate(
    provider: LLMProvider, section: Section, model: ModelSpec, seed: int
) -> SectionScore | None:
    """One section-shot, realised and repaired. `None` when nothing usable came back."""
    request = request_for(section, model)
    stream = SectionStream(section)
    try:
        async for event in provider.stream(request):
            stream.feed(event)
    except (ProviderError, DslError):
        return None

    parsed = stream.result()
    score = realise(parsed, seed)
    if not score.parts:
        return None

    # Complete from the floor, as `agents/producer.py` does: an incomplete score would
    # leave the previous section still sounding under this one.
    missing = [i for i in Instrument if i not in score.instruments()]
    if missing:
        floor = play_section(section, seed)
        score = score.model_copy(
            update={
                "parts": tuple(
                    sorted(
                        (*score.parts, *(floor.part(i) for i in missing)),
                        key=lambda part: list(Instrument).index(part.instrument),
                    )
                )
            }
        )
    repaired, left = repair(score)
    return None if left else repaired


def write(daw: DawPort, score: SectionScore, scene: int, tracks: dict[Instrument, int]) -> None:
    length = score.section.total_beats()
    for instrument, notes in render_score(score).items():
        track = tracks.get(instrument)
        if track is None:
            continue
        at = ClipAddress(track=track, scene=scene)
        ensure_clip(daw, at, length)
        daw.write_notes(at, notes)


def play(daw: DawPort, scene: int, seconds: float) -> None:
    """Fire a scene, let it play, stop. The transport is stopped between sides."""
    daw.fire_scene(scene)
    daw.start_playing()
    deadline = time.monotonic() + LAUNCH_TIMEOUT_S
    while time.monotonic() < deadline and not daw.is_playing():
        time.sleep(POLL_S)
    time.sleep(seconds)
    daw.stop_playing()


# Why one side won, in words a listener uses rather than words a score uses. The judge
# of this test is not a musician and does not need to be — ADR-000 asks whether a section
# is *preferred*, and most people who will ever hear this system are not musicians either.
# But a bare vote says only *that* the floor won, and finding out *why* cost a post-hoc
# hypothesis and a mine through 85 logged sections (`phase-3-findings.md` §13). One
# keystroke here would have said it on the night.
REASONS: Final[dict[str, str]] = {
    "1": "more energy",
    "2": "less boring",
    "3": "cleaner, less messy",
    "4": "just sounds nicer",
    "5": "better to move to",
}


def ask(pair: Pair, daw: DawPort, seconds: float, total: int) -> tuple[str, str] | None:
    """Play both sides, take a vote and a reason. `(vote, reason)`, or None to quit.

    `vote` is "A", "B" or "skip". Which side is which is never printed. The mapping lives
    in `pair.first` and reaches the log only after the vote.
    """
    sys.stderr.write(
        f"\npair {pair.index + 1}/{total} — {pair.section.name}, {pair.section.bars} bars "
        f"at {pair.section.bpm:g}, {pair.section.feel}\n"
    )
    heard = False
    while True:
        if not heard:
            sys.stderr.write("  playing A...\n")
            play(daw, SCENES[0], seconds)
            sys.stderr.write("  playing B...\n")
            play(daw, SCENES[1], seconds)
            heard = True
        answer = input("  [a] hear A  [b] hear B  [1] A better  [2] B better  [s] skip  [q] quit: ")
        choice = answer.strip().lower()
        if choice == "a":
            play(daw, SCENES[0], seconds)
        elif choice == "b":
            play(daw, SCENES[1], seconds)
        elif choice == "1":
            return "A", why()
        elif choice == "2":
            return "B", why()
        elif choice == "s":
            return "skip", ""
        elif choice == "q":
            return None
        else:
            sys.stderr.write("  a, b, 1, 2, s or q.\n")


def why() -> str:
    """One optional word about what the winner had. Never required, never theory."""
    menu = "  ".join(f"[{key}] {text}" for key, text in REASONS.items())
    answer = input(f"  why? {menu}  [enter] skip, or type your own: ").strip()
    return REASONS.get(answer, answer)


def record(path: Path, pair: Pair, vote: str, seconds: float, reason: str = "") -> None:
    """Append the vote *and* what each side was. Written only after the answer is in."""
    winner = (
        "skip"
        if vote == "skip"
        else (pair.first if vote == "A" else ("floor" if pair.first == "model" else "model"))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "pair": pair.index,
                    "section": pair.section.name,
                    "bars": pair.section.bars,
                    "bpm": pair.section.bpm,
                    "feel": str(pair.section.feel),
                    "first": pair.first,
                    "vote": vote,
                    "winner": winner,
                    "reason": reason,
                    "seconds": seconds,
                }
            )
            + "\n"
        )


def done_pairs(path: Path) -> set[int]:
    """Which pairs already have a vote, so `--resume` does not repeat one."""
    if not path.exists():
        return set()
    return {
        int(json.loads(line)["pair"])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def tally(path: Path) -> str:
    """The result, computed only at the end. Reading it early is what biasing looks like."""
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    votes = [row for row in rows if row["winner"] != "skip"]
    model = sum(1 for row in votes if row["winner"] == "model")
    if not votes:
        return "No votes recorded.\n"
    share = model / len(votes)
    met = model >= THRESHOLD and len(votes) >= DEFAULT_PAIRS
    lines = [
        "",
        f"model preferred in {model} of {len(votes)} pairs ({share:.0%})",
        f"threshold: {THRESHOLD} of {DEFAULT_PAIRS} (agreed 2026-08-30, before any number)",
        f"criterion: {'MET' if met else 'NOT MET'}",
    ]
    if len(votes) < DEFAULT_PAIRS:
        lines.append(f"({DEFAULT_PAIRS - len(votes)} pairs still to judge — --resume)")
    lines.append("")
    chorus = [row for row in votes if row["section"] == "chorus"]
    chorus_model = sum(1 for row in chorus if row["winner"] == "model")
    chorus_met = chorus_model >= CHORUS_THRESHOLD and len(chorus) >= CHORUS_PAIRS
    chorus_verdict = "MET" if chorus_met else "NOT MET"
    if chorus:
        lines += [
            "",
            f"pre-registered: chorus pairs, model in >= {CHORUS_THRESHOLD} of "
            f"{CHORUS_PAIRS} (fixed 2026-09-01, before the run)",
            f"  measured: {chorus_model} of {len(chorus)} — {chorus_verdict}",
        ]
        other = [row for row in votes if row["section"] != "chorus"]
        if other:
            lines.append(
                f"  everything else: {sum(1 for r in other if r['winner'] == 'model')} "
                f"of {len(other)}"
            )
    lines.append("")
    lines.append("by pair, now that voting is over:")
    for row in rows:
        reason = row.get("reason", "")
        lines.append(
            f"  {row['pair'] + 1:>2}  {row['section']:<7} {row['feel']:<11} "
            f"A was {row['first']:<5}  you chose {row['vote']:<4}  -> {row['winner']:<5}"
            + (f"  ({reason})" if reason else "")
        )

    # Grouped, because one reason repeated across five losses is a diagnosis and the same
    # five losses without it are only a number.
    by_reason: dict[str, list[str]] = {}
    for row in votes:
        if reason := row.get("reason", ""):
            by_reason.setdefault(reason, []).append(row["winner"])
    if by_reason:
        lines += ["", "why, grouped:"]
        for reason, winners in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            floor = winners.count("floor")
            lines.append(
                f"  {reason:<24} {len(winners):>2}x  "
                f"(floor won {floor}, model {len(winners) - floor})"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=DEFAULT_PAIRS)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--seconds", type=float, default=0.0, help="0 = one whole pass")
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout-s", type=float, default=0.5)
    parser.add_argument("--resume", action="store_true", help="skip pairs already judged")
    parser.add_argument("--tally", action="store_true", help="print the result and exit")
    args = parser.parse_args()

    if args.tally:
        sys.stderr.write(tally(args.log) if args.log.exists() else "Nothing judged yet.\n")
        return 0

    spec = load_session(args.session)
    tracks = {
        ROLE_TO_INSTRUMENT[track.role]: track.index
        for track in spec.tracks
        if track.role in ROLE_TO_INSTRUMENT
    }
    catalog = load_catalog(args.catalog)
    model = structural(catalog)

    try:
        provider = build_provider(catalog)
    except ProviderError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    # Read it either way: the point of the check is to catch a *second* run appending to
    # a file that already holds votes, and reading only under `--resume` meant the check
    # could never fire. Two runs over one log would double-count the same pair.
    judged = done_pairs(args.log)
    if judged and not args.resume:
        sys.stderr.write(
            f"{args.log} already holds {len(judged)} vote(s). Pass --resume to continue "
            "them, or move the file to start again.\n"
        )
        return 1
    already = judged if args.resume else set()

    sections = briefings(args.pairs, args.seed)
    daw = build_adapter(args.host, args.timeout_s)
    order = random.Random(args.seed)
    runner = asyncio.Runner()

    try:
        daw.warm()
        daw.stop_playing()
        divergences = diff_session(spec, observe(daw))
        if divergences:
            sys.stderr.write(render_divergences(divergences))
            sys.stderr.write("Run scripts/bootstrap_set.py before listening.\n")
            return 1

        # Printed **before** the first note, which is the whole of what makes it a
        # pre-registration. The same numbers appear in the tally at the end; if they ever
        # disagree, the one that was on screen first is the real one.
        sys.stderr.write(
            f"{args.pairs} pairs against {model.id}. Which side is which is not shown "
            "until the end.\n"
            f"  overall:        model preferred in >= {THRESHOLD} of {DEFAULT_PAIRS} "
            "(agreed 2026-08-30)\n"
            f"  pre-registered: chorus pairs, model in >= {CHORUS_THRESHOLD} of "
            f"{CHORUS_PAIRS} (fixed 2026-09-01)\n"
            f"  feels covered:  {', '.join(str(feel) for feel in Feel)}\n"
        )

        # One loop, held open across every pair. See the module docstring: the adapter's
        # HTTP pool belongs to the loop that made it, and a fresh loop per pair kills it.
        for index, section in enumerate(sections):
            if index in already:
                continue
            seconds = args.seconds or section.total_seconds()

            sys.stderr.write(f"\ngenerating pair {index + 1}/{args.pairs}...\n")
            generated = runner.run(generate(provider, section, model, args.seed + index))
            floor = play_section(section, args.seed + index)
            if generated is None:
                sys.stderr.write("  the model returned nothing usable — pair skipped.\n")
                continue
            if generated == floor:
                # Voting on it would be voting on the same music twice.
                sys.stderr.write("  both sides are identical — pair skipped.\n")
                continue

            first = order.choice(("model", "floor"))
            pair = Pair(index, section, generated, floor, first)
            write(daw, generated if first == "model" else floor, SCENES[0], tracks)
            write(daw, floor if first == "model" else generated, SCENES[1], tracks)

            answer = ask(pair, daw, seconds, args.pairs)
            if answer is None:
                sys.stderr.write("\nstopped. --resume continues where you left off.\n")
                break
            vote, reason = answer
            record(args.log, pair, vote, seconds, reason)

        sys.stderr.write(tally(args.log) if args.log.exists() else "No votes recorded.\n")
        return 0
    except DawError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        # Best-effort: if Live went away, it cannot be told to stop, and a teardown that
        # raised would replace the message explaining why.
        with suppress(DawError):
            daw.stop_playing()
        daw.close()
        runner.close()


if __name__ == "__main__":
    raise SystemExit(main())
