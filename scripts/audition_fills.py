"""Plays six ways to fill a bar, blind, so the ear can pick the clearest (phase-4-findings §10).

    uv run python scripts/audition_fills.py --dry-run     # what will play, no Live
    uv run python scripts/audition_fills.py               # Live open, stopped; about two minutes
    uv run python scripts/audition_fills.py --reveal      # after answering: which number was which

Stage 4's gate approved the stop and the drop and heard the fill cue as *"não tão clara"*.
Three ideas could make it clearer — a rising snare, a run down the toms, a crash where the
groove comes back — and the ear is the only instrument that can choose between them
(ADR-019). This script is how that choice costs two minutes instead of six jam sessions.

**What plays.** Six passages, one per option. Each is the same five bars of a verse from the
default song — three bars of groove, **the fill bar**, and the bar the groove returns in —
played twice, then **one bar of silence**. The silence is how passages are counted without a
screen: passage 1 starts with the music, and every silence ends one.

**Blind.** The six options play in a shuffled order, numbered 1 to 6, and the terminal only
ever prints the numbers. The key goes to `bench/audition-fills.json` and is not printed until
`--reveal`. Say which numbers were clearest first; then reveal. A number chosen before the
name is known is the only kind of vote this project counts.

**It uses scenes 0 and 1**, which every jam rewrites, and stops the transport when it ends.
It refuses to start while Live is playing.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from garagem.daw import (
    AbletonOSCAdapter,
    ClipAddress,
    DawError,
    OscSettings,
    UdpOscTransport,
    ensure_clip,
    load_session,
)
from garagem.domain import BEATS_PER_BAR, Feel, Instrument, Note, Part, SectionScore
from garagem.engines import (
    FillStyle,
    SongBrief,
    arrange,
    compose,
    endings_for,
    fill_bars,
    land_bars,
    play_section,
    with_climax,
)
from garagem.transport import render_part

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / "bench" / "audition-fills.json"
SESSION = ROOT / "session.toml"

SONG_SEED: Final = 7
VERSE: Final = 1
PHRASE_BARS: Final = 5
FILL_BAR: Final = 3
RETURN_BAR: Final = 4
REPEATS: Final = 2
SILENT_BARS: Final = 1
PASSAGE_BARS: Final = PHRASE_BARS * REPEATS + SILENT_BARS
POLL_S: Final = 0.02

GET_SONG_TIME: Final = "/live/song/get/current_song_time"
SET_SONG_TIME: Final = "/live/song/set/current_song_time"

TRACKS: Final[dict[Instrument, int]] = {
    Instrument.DRUMS: 0,
    Instrument.BASS: 1,
    Instrument.GUITAR: 2,
    Instrument.KEYS: 3,
}


@dataclass(frozen=True, slots=True)
class Option:
    name: str
    style: FillStyle
    crash: bool


OPTIONS: Final[tuple[Option, ...]] = (
    Option("snare fill (the one heard at the gate)", FillStyle.SNARE, crash=False),
    Option("rising snare", FillStyle.RISING, crash=False),
    Option("run down the toms", FillStyle.TOMS, crash=False),
    Option("snare fill, crash on the return", FillStyle.SNARE, crash=True),
    Option("rising snare, crash on the return", FillStyle.RISING, crash=True),
    Option("run down the toms, crash on the return", FillStyle.TOMS, crash=True),
)


# --------------------------------------------------------------------------- the music


def the_verse() -> SectionScore:
    """The default song's first verse, as `jam.py` would play it, ending included."""
    brief = SongBrief(key=4, scale="minor", bpm=132.0, feel=Feel.STRAIGHT8, minimum_seconds=180)
    form = with_climax(arrange(brief, SONG_SEED))
    endings = endings_for(form)
    score = play_section(form[VERSE], SONG_SEED + VERSE)
    return compose(score, endings[VERSE], into=form[VERSE + 1])


def passage(verse: SectionScore, option: Option) -> dict[Instrument, tuple[Note, ...]]:
    """Every track's notes for one passage: the phrase with this fill, twice, then silence."""
    filled = fill_bars(verse, option.style).part(Instrument.DRUMS)
    landed = (
        land_bars(verse).part(Instrument.DRUMS) if option.crash else verse.part(Instrument.DRUMS)
    )
    phrase: dict[Instrument, list[Note]] = {}
    for part in verse.parts:
        if part.instrument is Instrument.DRUMS:
            notes = [
                *_bars(part, 0, FILL_BAR),
                *_bars(filled, FILL_BAR, FILL_BAR + 1),
                *_bars(landed, RETURN_BAR, RETURN_BAR + 1),
            ]
        else:
            notes = _bars(part, 0, PHRASE_BARS)
        phrase[part.instrument] = notes
    return {
        instrument: tuple(
            note.model_copy(
                update={"start_beats": note.start_beats + repeat * PHRASE_BARS * BEATS_PER_BAR}
            )
            for repeat in range(REPEATS)
            for note in notes
        )
        for instrument, notes in phrase.items()
    }


def _bars(part: Part, first: int, last: int) -> list[Note]:
    """The notes that start in bars `first` to `last - 1`, cut to end before `last`."""
    start, end = first * BEATS_PER_BAR, last * BEATS_PER_BAR
    # Humanisation can put a downbeat a hair early; a note belongs to the bar it is nearest.
    tolerance = 0.05
    kept = [n for n in part.notes if start - tolerance <= n.start_beats < end - tolerance]
    return [
        n.model_copy(
            update={"duration_beats": max(0.02, min(n.duration_beats, end - 0.01 - n.start_beats))}
        )
        for n in kept
    ]


def blind_order(seed: int) -> list[int]:
    """Which option plays as passage 1, 2, ... — shuffled, and stable for a seed."""
    order = list(range(len(OPTIONS)))
    random.Random(seed).shuffle(order)
    return order


# ------------------------------------------------------------------------------- Live


def wait_until(transport: UdpOscTransport, beat: float, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if float(transport.request(GET_SONG_TIME)[0]) >= beat:
            return
        time.sleep(POLL_S)
    raise DawError(f"the song never reached beat {beat}; is the transport running?")


def write(daw: AbletonOSCAdapter, notes: dict[Instrument, tuple[Note, ...]], scene: int) -> None:
    length = PASSAGE_BARS * BEATS_PER_BAR
    for instrument, track in TRACKS.items():
        at = ClipAddress(track=track, scene=scene)
        ensure_clip(daw, at, length)
        daw.write_notes(at, render_part(Part(instrument=instrument, notes=notes[instrument])))


def perform(order: list[int], emit: Callable[[str], object] = sys.stderr.write) -> None:
    verse = the_verse()
    passages = [passage(verse, OPTIONS[option]) for option in order]
    transport = UdpOscTransport(OscSettings(timeout_s=1.0))
    daw = AbletonOSCAdapter(transport=transport)
    try:
        daw.warm()
        if daw.is_playing():
            raise DawError("Live is playing; stop the transport and run this again")
        write(daw, passages[0], scene=0)
        transport.send(SET_SONG_TIME, 0.0)
        daw.fire_scene(0)
        daw.start_playing()
        emit("passage 1 — listen\n")
        for number in range(1, len(passages)):
            starts_at = number * PASSAGE_BARS * BEATS_PER_BAR
            write(daw, passages[number], scene=number % 2)
            wait_until(transport, starts_at - BEATS_PER_BAR + 1.0)
            daw.fire_scene(number % 2)
            wait_until(transport, starts_at)
            emit(f"passage {number + 1} — listen\n")
        wait_until(transport, len(passages) * PASSAGE_BARS * BEATS_PER_BAR - BEATS_PER_BAR)
    finally:
        try:
            daw.stop_playing()
        except DawError as exc:
            emit(f"could not stop the transport: {exc}\n")
        transport.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="say what would play; no Live")
    parser.add_argument("--reveal", action="store_true", help="print which passage was which")
    parser.add_argument("--seed", type=int, default=int(time.time()) % 100_000)
    args = parser.parse_args()

    if args.reveal:
        if not KEY_FILE.exists():
            sys.stderr.write("nothing to reveal: run the audition first\n")
            return 1
        key = json.loads(KEY_FILE.read_text(encoding="utf-8"))
        for number, name in enumerate(key["passages"], start=1):
            sys.stderr.write(f"passage {number}: {name}\n")
        return 0

    order = blind_order(args.seed)
    seconds = len(OPTIONS) * PASSAGE_BARS * BEATS_PER_BAR * 60 / load_session(SESSION).tempo_bpm
    if args.dry_run:
        sys.stderr.write(
            f"{len(OPTIONS)} passages of {PASSAGE_BARS} bars each, about {seconds:.0f}s, "
            "in a shuffled order that is not shown\n"
        )
        return 0

    KEY_FILE.write_text(
        json.dumps(
            {"seed": args.seed, "passages": [OPTIONS[option].name for option in order]}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    sys.stderr.write(
        f"{len(OPTIONS)} passages, about {seconds:.0f}s. Each is the same phrase twice, then a "
        "bar of silence. Note which numbers make the fill clearest; then run --reveal.\n"
    )
    try:
        perform(order)
    except DawError as exc:
        sys.stderr.write(f"audition stopped: {exc}\n")
        return 1
    sys.stderr.write("done. Which passages had the clearest fill? Then: --reveal\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
