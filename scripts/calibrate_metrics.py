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

**This script plays the extremes of that number and asks which is messier.** Not which is
better — preference is the A/B's question and it closes the phase. This one asks whether
the number is about anything audible at all.

Free by construction: every section is realised offline from DSL that was recorded and
paid for during Phase 3. No network, no key, no cost. Live must be open, because the
question is about sound.

    uv run python scripts/calibrate_metrics.py --dry-run   # the selection, no Live
    uv run python scripts/calibrate_metrics.py             # the listen
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
DEFAULT_LOG = ROOT / "bench" / "calibration.jsonl"

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

# Pre-registered here, in the source, before the first listen. Ten pairs of extremes; the
# metric is credited when the section it calls messier is heard as messier.
#
# Under a coin, P(>= 8 of 10) = 0.055. That is the same order as the A/B's 8 of 12 and it
# is deliberate: a gate that is easier to pass than the test it protects is not a gate.
PAIRS: Final = 10
THRESHOLD: Final = 8

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


def extremes(corpus: list[Scored], pairs: int) -> list[tuple[Scored, Scored]]:
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
    usable = [(messy, clean) for clean, messy in candidates if clean.collision > messy.collision]
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


def ask(trial: Trial, daw: DawPort, seconds: float, total: int) -> str | None:
    """Play both sides and ask which is messier. "A", "B", "same", or None to quit.

    *Messier*, not *better*. Preference is the A/B's question and it decides the phase;
    this one only asks whether the number is about anything a person can hear.
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
            "  [a] hear A  [b] hear B  [1] A messier  [2] B messier  [=] can't tell  [q] quit: "
        )
        choice = answer.strip().lower()
        if choice == "a":
            play(daw, SCENES[0], seconds)
        elif choice == "b":
            play(daw, SCENES[1], seconds)
        elif choice == "1":
            return "A"
        elif choice == "2":
            return "B"
        elif choice == "=":
            return "same"
        elif choice == "q":
            return None
        else:
            sys.stderr.write("  a, b, 1, 2, = or q.\n")


def record(path: Path, trial: Trial, vote: str, seconds: float) -> None:
    """The verdict and both sides' provenance. Written only after the answer is in."""
    agreed = "same" if vote == "same" else str((trial.first == "messy") == (vote == "A")).lower()
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


def tally(path: Path) -> str:
    """The count, the threshold, and — carefully — what the count does not license.

    An earlier version of this function printed "kit_collision does not track the ear"
    whenever the threshold was missed. That is a stronger claim than ten trials can carry:
    missing a bar set at p = 0.055 is not evidence of no effect, it is the absence of
    evidence for one. The two get confused precisely when the result is disappointing,
    which is when it matters most not to.
    """
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    agreed = sum(1 for row in rows if row["metric_agreed"] == "true")
    same = sum(1 for row in rows if row["metric_agreed"] == "same")
    decisive = len(rows) - same
    met = agreed >= THRESHOLD
    lines = [
        "",
        f"the metric was heard as messier in {agreed} of {len(rows)} pairs "
        f"({same} indistinguishable, {decisive} decisive)",
        f"pre-registered: >= {THRESHOLD} of {PAIRS}  ->  {'MET' if met else 'NOT MET'}",
        "",
    ]
    if not met:
        tail = _coin_tail(agreed, decisive) if decisive else 1.0
        lines += [
            f"P(>= {agreed} of {decisive} under a coin) = {tail:.2f}. The gate is not met,",
            "so kit_collision does not steer arrangement work — that is what ADR-018 asks",
            "of it. But this is not evidence that the metric is meaningless: ten trials",
            "would reach the threshold only about half the time even if the metric were",
            "right 75% of the time. Absence of evidence, at this n, is all it is.",
            "",
        ]
        if same < len(rows):
            lines += [
                f"What the run does say: {decisive} of {len(rows)} pairs were audibly",
                "different, so the material differs. It is the *word* that did not line up,",
                "not the sound.",
                "",
            ]
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
    args = parser.parse_args()

    corpus = load_corpus([ROOT / "bench" / name for name in DEFAULT_CORPUS])
    if not corpus:
        sys.stderr.write("no recorded sections found under bench/.\n")
        return 1
    trials_data = extremes(corpus, args.pairs)

    sys.stderr.write(
        f"{len(corpus)} recorded sections scored offline, no network.\n"
        f"  kit_collision: messiest {trials_data[0][0].collision:.3f}, "
        f"cleanest {trials_data[0][1].collision:.3f}\n"
        f"  pre-registered: the metric's pick is heard as messier in "
        f">= {THRESHOLD} of {args.pairs}\n"
        "  the question is *messier*, not *better*.\n\n"
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
            first = order.choice(("messy", "clean"))
            trial = Trial(index, messy, clean, first)
            seconds = args.seconds or messy.section.total_seconds()
            write(daw, messy.score if first == "messy" else clean.score, SCENES[0], tracks)
            write(daw, clean.score if first == "messy" else messy.score, SCENES[1], tracks)

            vote = ask(trial, daw, seconds, args.pairs)
            if vote is None:
                sys.stderr.write("\nstopped.\n")
                break
            record(args.log, trial, vote, seconds)

        sys.stderr.write(tally(args.log) if args.log.exists() else "No votes recorded.\n")
        return 0
    except DawError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        daw.close()


if __name__ == "__main__":
    raise SystemExit(main())
