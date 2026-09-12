"""Does `kit_collision` hear what Fabiano hears? A blind, pre-registered listen.

ADR-018 made the coherence metrics a Phase 4 gate: they must be shown to track the ear
*before* they are allowed to steer arrangement work. The debt as written asked them to
separate the three "cleaner, less messy" losses in `bench/ab-phase3-final.jsonl` from the
other nine. That is not executable — the model side of those twelve pairs was never
persisted, and an LLM call is not reproducible from a seed (`phase-4-findings.md` §1).

So the gate is re-aimed rather than dropped, and it asks a sharper question. §16's
mechanism was refuted: over 112 recorded sections `register_spread` is 1.000 for all of
them, because the DSL never lets a model name a pitch. The one measured difference that
points the same way as those three votes is that the model stacks a kick and a snare in
one slot 0.172 of the time against the floor's 0.060.

**It first asked which side was messier, and that was the wrong question.** 6 of 10, one
indistinguishable, against a threshold of 8 (`phase-4-findings.md` §3). The run asked
Fabiano to be a measuring instrument for a *label*, which is a different job from the one
his ear is the reference for: ADR-000's criterion is whether a section is **preferred**,
and "cleaner, less messy" was his phrase about whole sections as a reason for preferring
one — not about two takes of a briefing differing only in the drums.

**So it now asks which side he prefers.** A metric that predicts his preference has
earned its place whatever it is called; a metric that matches his vocabulary has earned
nothing. The old run stays in `bench/calibration.jsonl` and is not overwritten.

Free by construction: every section is realised offline from DSL that was recorded and
paid for during Phase 3. No network, no key, no cost. Live must be open, because the
question is about sound.

    uv run python scripts/calibrate_metrics.py --dry-run   # the selection, no Live
    uv run python scripts/calibrate_metrics.py             # the listen, ~30 minutes
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from math import comb
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_sections import draw

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
from garagem.domain import Instrument, Section, SectionScore
from garagem.dsl import parse_section, realise
from garagem.dsl.errors import DslError
from garagem.engines import coherence_of
from garagem.llm import StreamDone, StreamEvent, ToolInputDelta, ToolUseStart
from garagem.transport import render_score

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / "session.toml"
DEFAULT_LOG = ROOT / "bench" / "calibration-preference.jsonl"
# The first, superseded run: it asked for a label rather than a preference (§3). Read to
# skip the briefings it already used, never appended to.
JUDGED_LOG = ROOT / "bench" / "calibration.jsonl"

# Every round of Phase 3 that produced usable DSL. The arranged rounds are absent because
# they produced none: 30 of 30 were cancelled at their deadline (§14).
DEFAULT_CORPUS: Final = (
    "sections-static.jsonl",
    "sections-fixed.jsonl",
    "sections-dense.jsonl",
    "sections-positions.jsonl",
)

# The bench rig's own defaults, and the only way the briefings come back: the draw is a
# pure function of `(index, seed)`. The *unfiltered* draw, deliberately — `briefings`
# applies `worth_asking`, and that filter moved when `MIN_DEADLINE_S` went from 1.5 to 5.0
# (§15), so the four-bar intros in the earlier rounds are no longer in it.
CORPUS_SEED: Final = 7
CORPUS_DRAWN: Final = 30

# Pre-registered here, in the source, before the first listen. The metric is credited when
# the take it scores cleaner is the one preferred.
#
# **P(>= 12 of 16 under a coin) = 0.038**, and the power is stated up front rather than
# discovered afterwards: 0.63 if collisions cost preference 75% of the time, 0.92 at 85%.
# So this run can find a strong effect and is weak against a moderate one. That ceiling is
# the corpus, not a choice — 17 pairs remain whose briefings the superseded run did not
# already play, and reusing those would be asking about music he has heard.
#
# The previous design, 8 of 10, failed at 6 (§3) and is not this one's baseline: it asked
# a different question.
PAIRS: Final = 16
THRESHOLD: Final = 12

SCENES = (0, 1)
LAUNCH_TIMEOUT_S = 4.0
POLL_S = 0.1
# One whole pass, so a section is judged on its shape and not on its first bar.
DEFAULT_SECONDS = 0.0

ROLE_TO_INSTRUMENT: dict[str, Instrument] = {
    "drums": Instrument.DRUMS,
    "bass": Instrument.BASS,
    "guitar": Instrument.GUITAR,
    "keys": Instrument.KEYS,
}


@dataclass(frozen=True, slots=True)
class Scored:
    """One recorded section, realised and measured, with where it came from."""

    source: str
    row: int
    section: Section
    score: SectionScore
    collision: float


@dataclass(frozen=True, slots=True)
class Trial:
    """One forced choice. `first` is which side plays first and is never printed."""

    index: int
    messy: Scored
    clean: Scored
    first: str  # "messy" or "clean"


def as_stream(dsl: str) -> list[StreamEvent]:
    """The recorded text put back on the wire, one fragment, as Gemini sends it."""
    return [
        ToolUseStart(id="calibration", name="write_section"),
        ToolInputDelta(fragment=json.dumps({"dsl": dsl})),
        StreamDone(stop="tool_use"),
    ]


def load_corpus(logs: list[Path]) -> list[Scored]:
    """Every section this project has on disk, realised offline and scored.

    The briefing is not in the log — a `Shot` carries the section's name, bars and tempo
    but not its key, chart or feel — so it is regenerated from the same seeded function
    the bench rig drew it from. That the two agree is checked, not assumed.
    """
    drawn = draw(CORPUS_DRAWN, CORPUS_SEED)
    out: list[Scored] = []
    for log in logs:
        if not log.exists():
            continue
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        cursor = 0
        for index, row in enumerate(rows):
            cursor, section = _align(drawn, cursor, row, log.name, index)
            if not row.get("dsl"):
                continue
            try:
                realised = realise(parse_section(as_stream(row["dsl"]), section), index)
            except DslError:
                continue
            if Instrument.DRUMS not in realised.instruments():
                continue
            out.append(
                Scored(
                    source=log.name,
                    row=index,
                    section=section,
                    score=realised,
                    collision=coherence_of(realised).kit_collision,
                )
            )
    return out


def _align(
    drawn: list[Section], cursor: int, row: dict[str, object], log: str, index: int
) -> tuple[int, Section]:
    """Walk the seeded draw forward until it matches this row, and say where it stopped.

    Positional alignment would be simpler and is wrong: `sections-static.jsonl` was
    recorded while `MIN_DEADLINE_S` was 1.5, so four-bar intros were still asked for, and
    raising the floor to 5.0 (§15) removed them from what `worth_asking` admits today. The
    rows of the older rounds therefore skip differently from the newer ones. Searching
    forward handles both without the caller having to know which era a log belongs to,
    and still fails loudly if the arranger itself has moved.
    """
    want = (row["section"], row["bars"], row["bpm"])
    for position in range(cursor, len(drawn)):
        section = drawn[position]
        if want == (section.name, section.bars, section.bpm):
            return position + 1, section
    raise ValueError(
        f"{log} row {index} is {want[0]}/{want[1]}/{float(str(want[2])):g}, which the "
        f"seeded draw does not contain from position {cursor} on. The arranger has moved "
        "since this round was recorded; the corpus cannot be scored against it."
    )


def _composition(trials: list[tuple[Scored, Scored]]) -> str:
    counts: dict[str, int] = {}
    for messy, _ in trials:
        counts[messy.section.name] = counts.get(messy.section.name, 0) + 1
    return ", ".join(f"{n} {name}" for name, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def already_heard(path: Path) -> set[tuple[str, int, float, str]]:
    """The briefings the superseded run played, so this one does not replay them.

    A preference asked about music he has already judged on another axis is not a fresh
    judgement, and there is no way to un-hear the first pass.
    """
    if not path.exists():
        return set()
    return {
        (row["section"], row["bars"], row["bpm"], row["feel"])
        for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    }


def extremes(
    corpus: list[Scored], pairs: int, *, skip: set[tuple[str, int, float, str]] | None = None
) -> list[tuple[Scored, Scored]]:
    """For each briefing, its messiest recorded take against its cleanest.

    **Both sides of a pair are the same briefing** — same chart, same key, same tempo,
    same bars — because the four Phase 3 rounds asked for the same sample four times and
    got four different answers. So the only thing that differs across a pair is the drum
    pattern the model wrote, which is the only thing `kit_collision` reads.

    Pairing the global extremes instead would have been simpler and would have repeated
    §10's mistake: it put a static loop against an arrangement and spent a whole round
    measuring two variables at once. A listener told to compare a shuffle bridge in one
    key against a straight16 verse in another is not judging mess, and would be right not
    to.

    The briefings with the widest gap come first: if the number means nothing, that is
    where it shows up soonest.
    """
    # The whole briefing as the key, not a summary of it: two verses can share a name, a
    # length, a tempo and a feel and still be in different keys over different charts.
    by_briefing: dict[str, list[Scored]] = {}
    for item in corpus:
        by_briefing.setdefault(item.section.model_dump_json(), []).append(item)

    candidates = [
        (max(takes, key=lambda s: s.collision), min(takes, key=lambda s: s.collision))
        for takes in by_briefing.values()
        if len(takes) > 1
    ]
    # `clean` is the higher score: kit_collision is 1.0 when nothing collides.
    heard = skip or set()
    usable = [
        (messy, clean)
        for clean, messy in candidates
        if clean.collision > messy.collision
        and (messy.section.name, messy.section.bars, messy.section.bpm, str(messy.section.feel))
        not in heard
    ]
    if len(usable) < pairs:
        raise ValueError(
            f"only {len(usable)} briefings have takes that differ; {pairs} pairs asked for"
        )
    usable.sort(key=lambda both: both[1].collision - both[0].collision, reverse=True)
    return usable[:pairs]


def tracks_of(spec_tracks: object) -> dict[Instrument, int]:
    return {
        ROLE_TO_INSTRUMENT[track.role]: track.index
        for track in spec_tracks  # type: ignore[attr-defined]
        if track.role in ROLE_TO_INSTRUMENT
    }


def write(daw: DawPort, score: SectionScore, scene: int, tracks: dict[Instrument, int]) -> None:
    """Deliberately a copy of `ab_section.py`'s. Sharing it would put a listening rig's
    `time.sleep` inside `transport/`, and nothing on the real-time path may sleep."""
    length = score.section.total_beats()
    for instrument, notes in render_score(score).items():
        track = tracks.get(instrument)
        if track is None:
            continue
        at = ClipAddress(track=track, scene=scene)
        ensure_clip(daw, at, length)
        daw.write_notes(at, notes)


def play(daw: DawPort, scene: int, seconds: float) -> None:
    daw.fire_scene(scene)
    daw.start_playing()
    deadline = time.monotonic() + LAUNCH_TIMEOUT_S
    while time.monotonic() < deadline and not daw.is_playing():
        time.sleep(POLL_S)
    time.sleep(seconds)
    daw.stop_playing()


# Why one side won, in words a listener uses. Copied from `ab_section.py` on purpose: the
# same vocabulary across both tests is what let §16 group losses by reason at all, and two
# menus would make the two runs incomparable.
REASONS: Final[dict[str, str]] = {
    "1": "more energy",
    "2": "less boring",
    "3": "cleaner, less messy",
    "4": "just sounds nicer",
    "5": "better to move to",
}


def why() -> str:
    """One optional word about what the winner had. Never required, never theory."""
    menu = "  ".join(f"[{key}] {text}" for key, text in REASONS.items())
    answer = input(f"  why? {menu}  [enter] skip, or type your own: ").strip()
    return REASONS.get(answer, answer)


def ask(trial: Trial, daw: DawPort, seconds: float, total: int) -> tuple[str, str] | None:
    """Play both sides and ask which is preferred. `(vote, reason)`, or None to quit.

    *Preferred*, not *cleaner*. Asking for a label is what the superseded run did, and it
    asked the ear to do a job it is not the reference for (§3). Preference is the job it
    is, by ADR-000's own words.
    """
    section = trial.messy.section
    sys.stderr.write(
        f"\npair {trial.index + 1}/{total} — {section.name}, {section.bars} bars "
        f"at {section.bpm:g}, {section.feel}\n"
    )
    heard = False
    while True:
        if not heard:
            sys.stderr.write("  playing A...\n")
            play(daw, SCENES[0], seconds)
            sys.stderr.write("  playing B...\n")
            play(daw, SCENES[1], seconds)
            heard = True
        answer = input(
            "  [a] hear A  [b] hear B  [1] A better  [2] B better  [=] no preference  [q] quit: "
        )
        choice = answer.strip().lower()
        if choice == "a":
            play(daw, SCENES[0], seconds)
        elif choice == "b":
            play(daw, SCENES[1], seconds)
        elif choice == "1":
            return "A", why()
        elif choice == "2":
            return "B", why()
        elif choice == "=":
            return "same", ""
        elif choice == "q":
            return None
        else:
            sys.stderr.write("  a, b, 1, 2, = or q.\n")


def record(path: Path, trial: Trial, vote: str, seconds: float, reason: str = "") -> None:
    """The verdict and both sides' provenance. Written only after the answer is in.

    `metric_agreed` is true when the *cleaner* take won: the hypothesis under test is that
    kick/snare collisions cost preference.
    """
    agreed = "same" if vote == "same" else str((trial.first == "clean") == (vote == "A")).lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "pair": trial.index,
                    "section": trial.messy.section.name,
                    "bars": trial.messy.section.bars,
                    "bpm": trial.messy.section.bpm,
                    "feel": str(trial.messy.section.feel),
                    "first": trial.first,
                    "vote": vote,
                    "metric_agreed": agreed,
                    "reason": reason,
                    "messy_collision": round(trial.messy.collision, 4),
                    "clean_collision": round(trial.clean.collision, 4),
                    "messy_from": f"{trial.messy.source}:{trial.messy.row}",
                    "clean_from": f"{trial.clean.source}:{trial.clean.row}",
                    "seconds": seconds,
                }
            )
            + "\n"
        )


def _coin_tail(hits: int, trials: int) -> float:
    """P(at least `hits` of `trials`) under a coin. Exact, and small enough to just sum."""
    return sum(comb(trials, k) for k in range(hits, trials + 1)) * 0.5**trials


def _coin_low_tail(hits: int, trials: int) -> float:
    """P(at most `hits` of `trials`) under a coin. The tail a reversal lives in."""
    return sum(comb(trials, k) for k in range(hits + 1)) * 0.5**trials


def _power(rate: float) -> float:
    """P(reaching THRESHOLD of PAIRS) if the metric is right `rate` of the time.

    Derived from the pre-registration rather than written out as a sentence. A hard-coded
    figure survives a change to THRESHOLD and then describes a run that never happened,
    which is precisely what it did between the superseded 10-pair round and this one
    (`phase-4-findings.md` §5).
    """
    return float(
        sum(
            comb(PAIRS, k) * rate**k * (1 - rate) ** (PAIRS - k)
            for k in range(THRESHOLD, PAIRS + 1)
        )
    )


def tally(path: Path) -> str:
    """The count, the threshold, and — carefully — what the count does not license.

    An earlier version of this function printed "kit_collision does not track the ear"
    whenever the threshold was missed. That is a stronger claim than ten trials can carry:
    missing a bar set at p = 0.055 is not evidence of no effect, it is the absence of
    evidence for one. The two get confused precisely when the result is disappointing,
    which is when it matters most not to.

    It was corrected a second time, in the other direction (`phase-4-findings.md` §5).
    The 16-pair run came back at 5 of 16 with the estimate *inverted*, and this function
    reported it as a near miss: it printed only the upper tail, 0.94, which reads as a
    coin and hides a 10-of-15 reversal, above a power sentence still describing the
    10-pair round. Claiming less than the design delivers is the same defect as claiming
    more — the sentence nobody is motivated to question is the one that survives.
    """
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    agreed = sum(1 for row in rows if row["metric_agreed"] == "true")
    same = sum(1 for row in rows if row["metric_agreed"] == "same")
    decisive = len(rows) - same
    met = agreed >= THRESHOLD
    lines = [
        "",
        f"the take the metric scores cleaner was preferred in {agreed} of {len(rows)} "
        f"pairs ({same} with no preference, {decisive} decisive)",
        f"pre-registered: >= {THRESHOLD} of {PAIRS}  ->  {'MET' if met else 'NOT MET'}",
        "",
    ]
    if not met:
        tail = _coin_tail(agreed, decisive) if decisive else 1.0
        lines += [
            f"P(>= {agreed} of {decisive} under a coin) = {tail:.2f}. The gate is not met,",
            "so kit_collision does not steer arrangement work — that is what ADR-018 asks",
            f"of it. But this is not evidence that the metric is meaningless: {PAIRS} trials",
            f"would reach the threshold only {_power(0.75):.0%} of the time even if the metric",
            "were right 75% of the time. Absence of evidence, at this n, is all it is.",
            "",
        ]
        if decisive and agreed * 2 < decisive:
            lines += [
                "And the point estimate runs the other way. The take scored *messier*",
                f"was preferred in {decisive - agreed} of {decisive} decisive pairs, so the "
                "tail above describes",
                "the bar rather than the result. The one that describes the result is",
                f"P(<= {agreed} of {decisive}) = {_coin_low_tail(agreed, decisive):.2f}, "
                "also not significant. A reversal this size is a",
                "hypothesis for a run that does not exist yet; acting on it here would be",
                "reading a mechanism off a finished run, which is how §13 and §16 died.",
                "",
            ]
        if same < len(rows):
            lines += [
                f"What the run does say: {decisive} of {len(rows)} pairs drew a preference,",
                "so the material differs audibly. What is unsupported is that kick/snare",
                "collision is what the preference is about.",
                "",
            ]
    reasons: dict[str, int] = {}
    for row in rows:
        if row.get("reason"):
            reasons[str(row["reason"])] = reasons.get(str(row["reason"]), 0) + 1
    if reasons:
        lines.append("why, in his words:")
        lines += [
            f"  {count:>2}  {text}"
            for text, count in sorted(reasons.items(), key=lambda kv: -kv[1])
        ]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS)
    parser.add_argument("--pairs", type=int, default=PAIRS)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout-s", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true", help="the selection, no Live")
    parser.add_argument("--tally", action="store_true", help="re-read a finished log, no Live")
    args = parser.parse_args()

    if args.tally:
        if not args.log.exists():
            sys.stderr.write(f"{args.log} does not exist.\n")
            return 1
        sys.stderr.write(tally(args.log))
        return 0

    corpus = load_corpus([ROOT / "bench" / name for name in DEFAULT_CORPUS])
    if not corpus:
        sys.stderr.write("no recorded sections found under bench/.\n")
        return 1
    trials_data = extremes(corpus, args.pairs, skip=already_heard(JUDGED_LOG))

    sys.stderr.write(
        f"{len(corpus)} recorded sections scored offline, no network.\n"
        f"  kit_collision: messiest {trials_data[0][0].collision:.3f}, "
        f"cleanest {trials_data[0][1].collision:.3f}\n"
        f"  pre-registered: the cleaner take is preferred in >= {THRESHOLD} of {args.pairs}"
        f"  (p = 0.038 under a coin)\n"
        "  the question is *better*, not *cleaner* — the superseded run asked the other\n"
        "  one and that was the mistake (phase-4-findings.md §3).\n"
        f"  power: 0.63 if collisions cost preference 75% of the time, 0.92 at 85%.\n"
        f"  sample: {_composition(trials_data)} — busier sections have more slots to\n"
        "  collide in, so the widest gaps are found there and the result generalises to\n"
        "  busy sections first. Both sides of a pair are the same briefing, so this\n"
        "  biases what the answer covers, not the comparison itself.\n\n"
    )

    if args.dry_run:
        for index, (messy, clean) in enumerate(trials_data):
            sys.stderr.write(
                f"  {index + 1:2}. {messy.section.name:7} {messy.section.feel!s:11} "
                f"messy={messy.collision:.3f} ({messy.source}:{messy.row})  vs  "
                f"clean={clean.collision:.3f} ({clean.source}:{clean.row})\n"
            )
        return 0

    if args.log.exists():
        sys.stderr.write(f"{args.log} already has votes in it. Move it to start again.\n")
        return 1

    spec = load_session(args.session)
    tracks = tracks_of(spec.tracks)
    daw = AbletonOSCAdapter(settings=OscSettings(host=args.host, timeout_s=args.timeout_s))
    order = random.Random(args.seed)
    try:
        daw.warm()
        daw.stop_playing()
        divergences = diff_session(spec, observe(daw))
        if divergences:
            sys.stderr.write(render_divergences(divergences))
            sys.stderr.write("Run scripts/bootstrap_set.py before listening.\n")
            return 1

        for index, (messy, clean) in enumerate(trials_data):
            first = order.choice(("clean", "messy"))
            trial = Trial(index, messy, clean, first)
            seconds = args.seconds or messy.section.total_seconds()
            write(daw, messy.score if first == "messy" else clean.score, SCENES[0], tracks)
            write(daw, clean.score if first == "messy" else messy.score, SCENES[1], tracks)

            answer = ask(trial, daw, seconds, args.pairs)
            if answer is None:
                sys.stderr.write("\nstopped.\n")
                break
            vote, reason = answer
            record(args.log, trial, vote, seconds, reason)

        sys.stderr.write(tally(args.log) if args.log.exists() else "No votes recorded.\n")
        return 0
    except DawError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        daw.close()


if __name__ == "__main__":
    raise SystemExit(main())
