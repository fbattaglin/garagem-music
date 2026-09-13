"""Five pairs, blind: a model shuffle as it wrote it, against the same section straightened.

    uv run python scripts/audition_shuffle.py --table     # the 19 takes and the five chosen
    uv run python scripts/audition_shuffle.py             # Live open, stopped; about five minutes
    uv run python scripts/audition_shuffle.py --tally     # the result, after the last vote

ADR-024 fixes the shuffle double swing as a defect (`phase-4-findings.md` §16): under a
shuffle, `dsl/realise.py` can move the model's attacks between the eighths onto the eighths
(`straightened`). This check is the ear's veto over that fix, and it claims nothing more.
**The fix is applied unless the side as written is preferred in 4 or more of the 5 pairs.**
A skipped pair counts for neither side.

**The material is recorded, so no call is made.** Every model shuffle section kept with its
DSL, 19 in all (`phase-5-findings.md` §1): 3 from the closing A/B, 8 from the regression
recording, and 8 from Phase 3's closing round, which answered the regression set's briefings
a phase earlier.

**Which five, by a rule and not by ear** (`choose`). Not the three from the closing A/B:
Fabiano heard those on the day this was written, and does not vote again on sections he has
already heard (`phase-4-findings.md` §15). Of the rest, most attacks moved first. At most one
take of a briefing, at most two pairs at one tempo, and at most two of one section kind. Ties
go to source order. `--table` prints the rule's working before anything is heard.

**Each side is what the producer would offer.** The take is realised, completed from the
floor where a part is missing, and repaired. Neither side gets an ending, as in the A/B.

**Blind, and leaning the safe way.** Which side plays first comes from a fixed seed, and the
straightened side plays first in three of the five pairs. The last A/B found a lean towards
the side heard second (B in 9 of 12). Here that lean can only help the take as written, which
is what the veto protects.

**Heard at its own tempo.** Live is set to each section's tempo before its pair plays, and the
Set's tempo is put back at the end. `scripts/ab_section.py` never did this: every A/B pair
played at the Set's 132 BPM, for as long as the section lasts at its own tempo
(`phase-5-findings.md` §2).

It uses scenes 0 and 1, which every jam rewrites, and stops the transport when it ends.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Final

from garagem.daw import (
    AbletonOSCAdapter,
    DawError,
    DawPort,
    OscSettings,
    diff_session,
    load_session,
    observe,
    render_divergences,
)
from garagem.domain import Feel, Grid, Instrument, Section, SectionScore
from garagem.dsl import ParsedSection, decode_fragments, parse_section, realise
from garagem.dsl.lines import BassLine, ChordLine, DrumLine
from garagem.engines import play_section
from garagem.llm import EVENT_ADAPTER, StreamDone, StreamEvent, ToolInputDelta, ToolUseStart
from garagem.theory import repair

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "session.toml"
AB_LOG = ROOT / "bench" / "ab-phase4.jsonl"
REGRESSION = ROOT / "cassettes" / "regression"
POSITIONS = ROOT / "bench" / "sections-positions.jsonl"
DEFAULT_LOG = ROOT / "bench" / "audition-shuffle.jsonl"

PAIRS: Final = 5
VETO: Final = 4
STRAIGHT_FIRST: Final = 3
ORDER_SEED: Final = 2026
MAX_PER_TEMPO: Final = 2
MAX_PER_KIND: Final = 2
SCENES: Final = (0, 1)

# Sources whose takes Fabiano has already voted on.
HEARD: Final = frozenset({"ab"})

STRAIGHTENED: Final = "straightened"
AS_WRITTEN: Final = "as_written"


@dataclass(frozen=True, slots=True)
class Take:
    """One recorded model section: where it came from, what it was asked, what it wrote."""

    source: str
    briefing_id: str
    section: Section
    seed: int
    dsl: str

    @property
    def name(self) -> str:
        return f"{self.source}:{self.briefing_id}"


# ----------------------------------------------------------------------------- material


def build_adapter(host: str, timeout_s: float) -> DawPort:
    return AbletonOSCAdapter(settings=OscSettings(host=host, timeout_s=timeout_s))


def _ab_script() -> ModuleType:
    """`scripts/ab_section.py`, loaded by path: its Live helpers and reasons, not copies."""
    spec = importlib.util.spec_from_file_location("ab_section", ROOT / "scripts" / "ab_section.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("ab_section", module)
    spec.loader.exec_module(module)
    return module


def _cassette_dsl(path: Path) -> str:
    events = [
        EVENT_ADAPTER.validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()[1:]
        if line.strip()
    ]
    return decode_fragments(
        [event.fragment for event in events if event.type == "tool_input_delta"]
    )


def takes(
    ab_log: Path = AB_LOG, regression: Path = REGRESSION, positions: Path = POSITIONS
) -> list[Take]:
    """Every recorded model shuffle section with its DSL, in source order."""
    out: list[Take] = []
    for line in ab_log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["feel"] == Feel.SHUFFLE and row.get("model_dsl"):
            section = Section.model_validate(row["briefing"])
            out.append(
                Take("ab", f"pair-{row['pair'] + 1}", section, row["seed"], row["model_dsl"])
            )

    recorded = json.loads((regression / "set.json").read_text(encoding="utf-8"))["briefings"]
    for entry in recorded:
        section = Section.model_validate(entry["section"])
        if section.feel is Feel.SHUFFLE and not entry["failed"]:
            dsl = _cassette_dsl(regression / f"{entry['id']}.jsonl")
            out.append(Take("regression", entry["id"], section, entry["seed"], dsl))

    # Phase 3's round asked the same draw, in the same order, a phase earlier.
    rows = [json.loads(line) for line in positions.read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != len(recorded):
        raise SystemExit(f"{positions} has {len(rows)} rows and the regression set {len(recorded)}")
    for entry, row in zip(recorded, rows, strict=True):
        section = Section.model_validate(entry["section"])
        if (row["section"], row["bars"], row["bpm"]) != (section.name, section.bars, section.bpm):
            raise SystemExit(f"{positions} row for {entry['id']} does not match its briefing")
        if section.feel is Feel.SHUFFLE and row["ok"] and row["dsl"]:
            out.append(Take("phase3", entry["id"], section, entry["seed"], row["dsl"]))
    return out


def parsed_of(take: Take) -> ParsedSection:
    events: list[StreamEvent] = [
        ToolUseStart(id=take.name, name="write_section"),
        ToolInputDelta(fragment=json.dumps({"dsl": take.dsl})),
        StreamDone(stop="tool_use"),
    ]
    return parse_section(events, take.section)


# --------------------------------------------------------------------------- the choice


def _off(grid: Grid) -> int:
    return sum(1 for slot, attack in enumerate(grid) if attack and slot % 2)


def moved(take: Take) -> dict[str, int]:
    """Attacks between the eighths, per part, over the distinct lines the model wrote."""
    counts: Counter[str] = Counter()
    for lines in parsed_of(take).lines.values():
        for line in dict.fromkeys(lines):
            if isinstance(line, DrumLine):
                counts["kick"] += _off(line.kick)
                counts["snare"] += _off(line.snare)
                counts["hat"] += _off(line.hat)
            elif isinstance(line, BassLine):
                counts["bass"] += _off(line.rhythm)
            elif isinstance(line, ChordLine):
                counts[str(line.instrument).lower()] += _off(line.rhythm)
    return dict(counts)


def choose(pool: list[Take], count: int = PAIRS) -> list[Take]:
    """Not already heard; most moved first; one take a briefing, two a tempo, two a section
    kind; ties in source order."""
    ranked = sorted(enumerate(pool), key=lambda item: (-sum(moved(item[1]).values()), item[0]))
    chosen: list[Take] = []
    for _, take in ranked:
        if len(chosen) == count:
            break
        if take.source in HEARD or sum(moved(take).values()) == 0:
            continue
        if any(other.briefing_id == take.briefing_id for other in chosen):
            continue
        if sum(1 for other in chosen if other.section.bpm == take.section.bpm) >= MAX_PER_TEMPO:
            continue
        if sum(1 for other in chosen if other.section.name == take.section.name) >= MAX_PER_KIND:
            continue
        chosen.append(take)
    return chosen


def first_sides(count: int = PAIRS, seed: int = ORDER_SEED) -> list[str]:
    """Which side plays first in each pair: straightened in exactly `STRAIGHT_FIRST`."""
    sides = [STRAIGHTENED] * STRAIGHT_FIRST + [AS_WRITTEN] * (count - STRAIGHT_FIRST)
    random.Random(seed).shuffle(sides)
    return sides


def sides_of(take: Take) -> dict[str, SectionScore]:
    """Both realisations, each as the producer would offer it: completed and repaired."""
    parsed = parsed_of(take)
    out: dict[str, SectionScore] = {}
    for side, straighten in ((AS_WRITTEN, False), (STRAIGHTENED, True)):
        score = realise(parsed, take.seed, straighten=straighten)
        missing = [instrument for instrument in Instrument if instrument not in score.instruments()]
        if missing:
            floor = play_section(take.section, take.seed)
            score = score.model_copy(
                update={
                    "parts": tuple(
                        sorted(
                            (*score.parts, *(floor.part(instrument) for instrument in missing)),
                            key=lambda part: list(Instrument).index(part.instrument),
                        )
                    )
                }
            )
        out[side], _ = repair(score)
    return out


def render_table(pool: list[Take], chosen: list[Take]) -> str:
    parts = ("hat", "kick", "snare", "bass", "gtr", "key")
    header = f"{'take':<34} {'section':<7} {'bpm':>4}  " + " ".join(f"{p:>5}" for p in parts)
    lines = [header + "  total  chosen"]
    for take in pool:
        counts = moved(take)
        mark = (
            f"pair {chosen.index(take) + 1}"
            if take in chosen
            else ("heard in the A/B" if take.source in HEARD else "")
        )
        lines.append(
            f"{take.name:<34} {take.section.name:<7} {take.section.bpm:>4g}  "
            + " ".join(f"{counts.get(p, 0):>5}" for p in parts)
            + f"  {sum(counts.values()):>5}  {mark}"
        )
    lines.append(
        f"\n{len(pool)} takes. Chosen, of those not already heard, by attacks moved, "
        "one take a briefing, at most "
        f"{MAX_PER_TEMPO} a tempo and {MAX_PER_KIND} a section kind."
    )
    lines.append(
        f"The fix is applied unless the take as written is preferred in {VETO} or more of "
        f"{PAIRS}. Straightened plays first in {STRAIGHT_FIRST} pairs, from seed {ORDER_SEED}."
    )
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------- votes


def record(path: Path, index: int, take: Take, first: str, vote: str, reason: str) -> None:
    """The vote and which side was which, written only after the answer is in."""
    second = AS_WRITTEN if first == STRAIGHTENED else STRAIGHTENED
    winner = "skip" if vote == "skip" else (first if vote == "A" else second)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        row = {
            "at": datetime.now(UTC).isoformat(),
            "pair": index,
            "take": take.name,
            "section": take.section.name,
            "bpm": take.section.bpm,
            "first": first,
            "vote": vote,
            "winner": winner,
            "reason": reason,
            "seed": take.seed,
            "briefing": take.section.model_dump(mode="json"),
            "dsl": take.dsl,
        }
        handle.write(json.dumps(row) + "\n")


def judged(path: Path) -> set[int]:
    if not path.exists():
        return set()
    lines = path.read_text(encoding="utf-8").splitlines()
    return {int(json.loads(line)["pair"]) for line in lines if line.strip()}


def tally(path: Path) -> str:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    votes = [row for row in rows if row["winner"] != "skip"]
    kept = sum(1 for row in votes if row["winner"] == AS_WRITTEN)
    vetoed = kept >= VETO
    lines = [
        "",
        f"as written preferred in {kept} of {len(votes)} judged pairs; "
        f"straightened in {len(votes) - kept}",
        f"veto: as written in {VETO} or more of {PAIRS}",
        "result: NOT APPLIED — the take as written stays"
        if vetoed
        else "result: APPLIED — shuffle takes are straightened",
    ]
    if len(rows) < PAIRS:
        lines.append(f"({PAIRS - len(rows)} pairs still to judge — --resume)")
    lines += ["", "by pair, now that voting is over:"]
    for row in rows:
        reason = f"  ({row['reason']})" if row.get("reason") else ""
        lines.append(
            f"  {row['pair'] + 1}  {row['take']:<34} A was {row['first']:<12} "
            f"you chose {row['vote']:<4} -> {row['winner']}{reason}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------- Live


def ask(
    ab: ModuleType, daw: DawPort, index: int, take: Take, seconds: float
) -> tuple[str, str] | None:
    """Play A then B, then take a vote and a reason. `None` to stop."""
    sys.stderr.write(f"\npair {index + 1}/{PAIRS} — {take.section.name} at {take.section.bpm:g}\n")
    sys.stderr.write("  playing A...\n")
    ab.play(daw, SCENES[0], seconds)
    sys.stderr.write("  playing B...\n")
    ab.play(daw, SCENES[1], seconds)
    while True:
        answer = input("  [a] hear A  [b] hear B  [1] A better  [2] B better  [s] skip  [q] quit: ")
        choice = answer.strip().lower()
        if choice == "a":
            ab.play(daw, SCENES[0], seconds)
        elif choice == "b":
            ab.play(daw, SCENES[1], seconds)
        elif choice in ("1", "2"):
            return ("A" if choice == "1" else "B"), ab.why()
        elif choice == "s":
            return "skip", ""
        elif choice == "q":
            return None
        else:
            sys.stderr.write("  a, b, 1, 2, s or q.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", action="store_true", help="print the choice and exit; no Live")
    parser.add_argument("--tally", action="store_true", help="print the result and exit")
    parser.add_argument("--resume", action="store_true", help="skip pairs already judged")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout-s", type=float, default=0.5)
    args = parser.parse_args()

    pool = takes()
    chosen = choose(pool)
    if args.table:
        sys.stderr.write(render_table(pool, chosen))
        return 0
    if args.tally:
        sys.stderr.write(tally(args.log) if args.log.exists() else "Nothing judged yet.\n")
        return 0

    done = judged(args.log)
    if done and not args.resume:
        sys.stderr.write(f"{args.log} already holds votes. Pass --resume, or move the file.\n")
        return 1
    if not sys.stdin.isatty():
        sys.stderr.write("Each pair ends in a typed vote: run this in Terminal, not through `!`.\n")
        return 1

    ab = _ab_script()
    spec = load_session(SESSION)
    tracks = {
        ab.ROLE_TO_INSTRUMENT[track.role]: track.index
        for track in spec.tracks
        if track.role in ab.ROLE_TO_INSTRUMENT
    }
    daw = build_adapter(args.host, args.timeout_s)
    try:
        daw.warm()
        daw.stop_playing()
        divergences = diff_session(spec, observe(daw))
        if divergences:
            sys.stderr.write(render_divergences(divergences))
            sys.stderr.write("Run scripts/bootstrap_set.py before listening.\n")
            return 1
        sys.stderr.write(
            f"{PAIRS} pairs. The fix is applied unless the take as written is preferred in "
            f"{VETO} or more. Which side is which is not shown until the end.\n"
        )
        for index, (take, first) in enumerate(zip(chosen, first_sides(), strict=True)):
            if index in done:
                continue
            sides = sides_of(take)
            second = AS_WRITTEN if first == STRAIGHTENED else STRAIGHTENED
            daw.set_tempo(take.section.bpm)
            ab.write(daw, sides[first], SCENES[0], tracks)
            ab.write(daw, sides[second], SCENES[1], tracks)
            answer = ask(ab, daw, index, take, take.section.total_seconds())
            if answer is None:
                sys.stderr.write("\nstopped. --resume continues where you left off.\n")
                break
            vote, reason = answer
            record(args.log, index, take, first, vote, reason)
        sys.stderr.write(tally(args.log) if args.log.exists() else "No votes recorded.\n")
        return 0
    except DawError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        # Best effort, and in this order: stop, then give the Set its tempo back.
        with suppress(DawError):
            daw.stop_playing()
        with suppress(DawError):
            daw.set_tempo(spec.tempo_bpm)
        daw.close()


if __name__ == "__main__":
    raise SystemExit(main())
