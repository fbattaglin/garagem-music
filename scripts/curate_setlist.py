"""Curates a setlist from the keeps and vetoes struck while it played (ADR-024).

    uv run python scripts/curate_setlist.py setlists/first.json            # applies the marks
    uv run python scripts/curate_setlist.py setlists/first.json --dry-run  # says, writes nothing

Pad 4 keeps and pad 7 vetoes the section playing. Nothing sounds different when they are
struck. This is where they take effect: every mark in `bench/jam.jsonl` struck during a song of
this setlist is found (`obs.curation.marks`), joined to the take it fell on, and written into
the setlist as that take's status.

- **Keep** pins a take. **Veto** retires it: from the next time the song plays, the floor plays
  that briefing, until `bake_setlist.py --rebake-vetoed` asks the model for it again.
- **The last word on a take wins.** A take kept on Monday and vetoed on Tuesday is vetoed.
- **A mark on the floor's music is not curation.** It is counted, and it changes nothing in the
  file.
- **A mark on a take the setlist no longer holds** (re-baked since) is reported and skipped.
- **A take is matched on its body, not its `SEC` echo**, which a knob rewrites
  (`setlist.served`).

Applying the same log twice gives the same file. What it prints counts marks by kind, never
which sections the model wrote: the next session is played blind too.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from garagem.obs import Mark, load_events, marks
from garagem.setlist import (
    Setlist,
    SetlistError,
    TakeStatus,
    body,
    load_setlist,
    save_setlist,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "bench" / "jam.jsonl"

STATUS = {"keep": TakeStatus.KEPT, "veto": TakeStatus.VETOED}


def curate(setlist: Setlist, found: list[Mark]) -> tuple[Setlist, Counter[str]]:
    """The setlist with every mark struck during its songs applied, and what happened to each."""
    tally: Counter[str] = Counter()
    decided: dict[tuple[int, str], TakeStatus] = {}
    for mark in found:
        if mark.setlist != setlist.name or mark.song is None:
            continue
        if not 1 <= mark.song <= len(setlist.songs):
            tally["no_such_song"] += 1
            continue
        if mark.dsl is None:
            tally[f"{mark.mark} on the floor"] += 1
            continue
        song = setlist.songs[mark.song - 1]
        if not any(body(take.dsl) == body(mark.dsl) for take in song.takes):
            tally[f"{mark.mark} on a take no longer here"] += 1
            continue
        decided[(mark.song, body(mark.dsl))] = STATUS[mark.mark]
        tally[mark.mark] += 1

    songs = []
    for number, song in enumerate(setlist.songs, start=1):
        takes = tuple(
            take.model_copy(update={"status": decided[(number, body(take.dsl))]})
            if (number, body(take.dsl)) in decided
            else take
            for take in song.takes
        )
        songs.append(song.model_copy(update={"takes": takes}))
    return setlist.model_copy(update={"songs": tuple(songs)}), tally


def render(before: Setlist, after: Setlist, tally: Counter[str]) -> str:
    lines = []
    for label in ("keep", "veto"):
        lines.append(f"{tally[label]} {label} mark(s) on this setlist's takes")
    for label, count in sorted(tally.items()):
        if label not in ("keep", "veto"):
            lines.append(f"{count} {label}")
    for number, (old, new) in enumerate(zip(before.songs, after.songs, strict=True), start=1):
        statuses = Counter(take.status for take in new.takes)
        changed = sum(1 for a, b in zip(old.takes, new.takes, strict=True) if a.status != b.status)
        lines.append(
            f"song {number}, {new.title}: {statuses[TakeStatus.KEPT]} kept, "
            f"{statuses[TakeStatus.VETOED]} vetoed, {statuses[TakeStatus.UNMARKED]} unmarked"
            f"{f' ({changed} changed now)' if changed else ''}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("setlist", type=Path, help="setlists/<name>.json")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would change; write nothing"
    )
    args = parser.parse_args()

    try:
        setlist = load_setlist(args.setlist)
    except SetlistError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if not args.log.exists():
        sys.stderr.write(f"{args.log} does not exist: nothing has been played to curate\n")
        return 1

    curated, tally = curate(setlist, marks(load_events(args.log)))
    sys.stderr.write(render(setlist, curated, tally))
    if args.dry_run:
        sys.stderr.write("dry run: nothing written\n")
        return 0
    if curated != setlist:
        save_setlist(curated, args.setlist)
        sys.stderr.write(f"written to {args.setlist}\n")
    else:
        sys.stderr.write("nothing to change\n")
    vetoed = sum(
        1 for song in curated.songs for take in song.takes if take.status is TakeStatus.VETOED
    )
    if vetoed:
        sys.stderr.write(
            f"{vetoed} vetoed take(s) now play as the floor. To ask the model again: "
            f"uv run python scripts/bake_setlist.py <spec>.toml --rebake-vetoed\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
