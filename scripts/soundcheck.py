"""Loops a verse, a bridge and a chorus of the band, so its sounds can be chosen by ear.

    uv run python scripts/soundcheck.py                  # the whole band, E minor, straight
    uv run python scripts/soundcheck.py --only guitar    # one role; repeat --only for more
    uv run python scripts/soundcheck.py --pocket off     # without each player's lean
    uv run python scripts/soundcheck.py --feel shuffle --seed 5

ADR-028's Stage B. The band plays the parts Stage A gave it, and each section loops, so while
it plays a preset can be swapped in Live and heard at once. Type `v`, `b` or `c` and Enter to
move to the verse, the bridge or the chorus at the next bar, and `q` to stop.

- **A verse** (`dyn` 2) is the indie half: one palm-muted guitar, the bass, closed hats, no
  organ.
- **A bridge** (`dyn` 3) opens the guitar and brings in the organ's pad.
- **A chorus** (`dyn` 4) is the arena half: the second guitar, open hats, a crash every
  phrase, the organ holding the chord.

Everything it writes goes into the first three scenes, before the transport starts, and it
never writes while Live plays (invariant 6). It reads `session.toml` and never changes it. It
refuses a Set it cannot write into (a missing track or scene); a wrong or missing instrument
is exactly what it is for, so it only says so.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from garagem.daw import (
    AbletonOSCAdapter,
    ClipAddress,
    DawPort,
    DawUnavailableError,
    OscSettings,
    SessionSpec,
    diff_session,
    ensure_clip,
    load_session,
    observe,
    render_divergences,
)
from garagem.domain import Feel, Section, SectionScore
from garagem.engines import play_section
from garagem.stage import ROLE_TO_INSTRUMENT, palms_of, pitches_of, tracks_of
from garagem.theory import parse_chart
from garagem.transport import render_score

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / "session.toml"

# E minor, because a guitar's lowest note is E: the power chords sit on the open string.
CHART: Final = "| Em | C | G | D | Em | C | G | D |"
KEY: Final = 4

# What each scene loops, and the key that moves to it.
PARTS: Final[tuple[tuple[str, str, int], ...]] = (
    ("v", "verse", 2),
    ("b", "bridge", 3),
    ("c", "chorus", 4),
)

# A Set this wrong cannot be written into. Everything else is the sound check's business.
BLOCKING: Final[frozenset[str]] = frozenset({"missing_track", "not_a_midi_track", "missing_scene"})


def build_adapter(host: str, timeout_s: float) -> DawPort:
    return AbletonOSCAdapter(settings=OscSettings(host=host, timeout_s=timeout_s))


def section(name: str, dyn: int, feel: Feel, bpm: float) -> Section:
    return Section(
        name=name,
        bars=8,
        key=KEY,
        scale="minor",
        feel=feel,
        bpm=bpm,
        dyn=dyn,
        tension=0.5,
        chart=parse_chart(CHART),
    )


def scores(spec: SessionSpec, feel: Feel, seed: int) -> tuple[SectionScore, ...]:
    return tuple(
        play_section(section(name, dyn, feel, spec.tempo_bpm), seed) for _, name, dyn in PARTS
    )


def write(
    daw: DawPort,
    spec: SessionSpec,
    played: Sequence[SectionScore],
    *,
    only: frozenset[str],
    pocket: bool,
) -> None:
    """Every scene's clips, looping. A role left out of `only` gets an empty clip: silence."""
    tracks = tracks_of(spec)
    keep = {ROLE_TO_INSTRUMENT[role] for role in only} if only else set(tracks)
    for scene, score in enumerate(played):
        rendered = render_score(
            score, pitches=pitches_of(spec), pocket=pocket, palms=palms_of(spec)
        )
        for instrument, track in tracks.items():
            at = ClipAddress(track=track, scene=scene)
            ensure_clip(daw, at, score.section.total_beats())
            daw.write_notes(at, rendered.get(instrument, ()) if instrument in keep else ())
            daw.set_clip_looping(at, True)


def conduct(daw: DawPort, ask: Callable[[str], str]) -> None:
    """Fire the verse, then whatever is asked for, until `q` or the end of input."""
    scenes = {key: scene for scene, (key, _, _) in enumerate(PARTS)}
    names = {key: name for key, name, _ in PARTS}
    daw.fire_scene(0)
    daw.start_playing()
    prompt = "  ".join(f"[{key}] {name}" for key, name, _ in PARTS) + "  [q] stop > "
    while True:
        try:
            wanted = ask(prompt).strip().lower()[:1]
        except EOFError:
            return
        if wanted == "q":
            return
        if wanted in scenes:
            daw.fire_scene(scenes[wanted])
            sys.stderr.write(f"next bar: the {names[wanted]}\n")


def main(ask: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout-s", type=float, default=0.5)
    parser.add_argument("--feel", default=Feel.STRAIGHT8, choices=[str(f) for f in Feel])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        choices=sorted(ROLE_TO_INSTRUMENT),
        help="play only this role; repeat for more. The rest of the band is silent.",
    )
    parser.add_argument(
        "--pocket",
        choices=("on", "off"),
        default="on",
        help="each player's lean against the beat (ADR-028). Off, to hear the difference.",
    )
    args = parser.parse_args()

    spec = load_session(args.session)
    daw = build_adapter(args.host, args.timeout_s)
    started = False
    try:
        try:
            daw.warm()
        except DawUnavailableError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        if daw.is_playing():
            sys.stderr.write(
                "Live is playing. Stop it (press the space bar in Live) and run this again: "
                "nothing is written into a Set while it plays.\n"
            )
            return 1

        divergences = diff_session(spec, observe(daw))
        if any(divergence.kind in BLOCKING for divergence in divergences):
            sys.stderr.write(render_divergences(divergences))
            return 1
        if divergences:
            sys.stderr.write("Not yet what session.toml says, which is fine while choosing:\n")
            sys.stderr.write(render_divergences(divergences))

        played = scores(spec, Feel(args.feel), args.seed)
        write(daw, spec, played, only=frozenset(args.only), pocket=args.pocket == "on")
        sys.stderr.write(
            f"Looping at {spec.tempo_bpm:g} BPM, {args.feel}, pocket {args.pocket}. Swap a "
            "preset in Live while it plays: click the track's name, find the sound in the "
            "browser on the left, and drag it onto the track.\n"
        )
        started = True
        conduct(daw, ask)
        return 0
    finally:
        # Only a transport this run started: a Set someone else was playing is left alone.
        if started:
            try:
                daw.stop_playing()
            except DawUnavailableError:
                sys.stderr.write("could not stop the transport: press the space bar in Live\n")
        daw.close()


if __name__ == "__main__":
    raise SystemExit(main())
