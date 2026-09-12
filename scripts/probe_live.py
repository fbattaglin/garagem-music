"""Walks every AbletonOSC address the adapter uses, against a real Live, and reports.

    uv run python scripts/probe_live.py
    uv run python scripts/probe_live.py --address /live/clip/get/notes
    uv run python scripts/probe_live.py --timeout-s 2.0

Every address and every reply shape in `src/garagem/daw/abletonosc.py` is a claim about
somebody else's code. This is the one place those claims are cheap to check: one
command, one line per address, and a wrong constant shows up here rather than as an
integration test that fails for a reason nobody can see.

Three things in particular are worth reading off the output:

1. **`/live/clip/get/notes`** — does the reply echo `(track, clip)` before the flat
   five-tuples? `notes_from_reply` assumes it does.
2. **`/live/song/get/clip_trigger_quantization`** — is the integer for `1 Bar` really
   4? `QUANTIZATION_CODES` assumes so, and a reordered LOM enum would silently mistime
   every scene launch.
3. **`/live/track/get/output_meter_level`** — does it answer at all? It is the only
   evidence from code that an instrument actually made a sound.

**It only reads.** Setters are listed and skipped: probing one would change the Set, and
AbletonOSC answers a setter with nothing anyway, so there would be nothing to see. So are
the two beat-listener addresses, which change no clip but would leave a listener running
in Live — and `/live/song/get/beat`, which has no handler at all: Live only ever sends on
it.

The clip getters are the awkward case. Asking about an *empty* slot makes AbletonOSC's
handler raise on a `None` clip, and a raising handler replies with nothing — which is
byte for byte what a wrong address looks like. So the probe finds a slot that actually
holds a clip first, and says plainly when there is none rather than reporting a working
endpoint as broken.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from garagem.daw import ALL_ADDRESSES, DawError, OscSettings, UdpOscTransport
from garagem.daw.abletonosc import (
    ADD_NOTES,
    CREATE_CLIP,
    DELETE_CLIP,
    FIRE_SCENE,
    GET_BEAT,
    GET_CLIP_LENGTH,
    GET_DEVICE_NAMES,
    GET_HAS_CLIP,
    GET_HAS_MIDI_INPUT,
    GET_METER_LEVEL,
    GET_NOTES,
    GET_TRACK_ARM,
    GET_TRACK_NAME,
    REMOVE_NOTES,
    SET_LOOP,
    SET_QUANTIZATION,
    SET_TEMPO,
    SET_TRACK_ARM,
    SET_TRACK_NAME,
    START_LISTEN_BEAT,
    START_PLAYING,
    STOP_LISTEN_BEAT,
    STOP_PLAYING,
)

ROOT = Path(__file__).resolve().parents[1]

Arguments = dict[str, tuple[int, ...]]

# Which arguments each address needs. Track 0 exists in any Set worth probing;
# everything not listed here takes none.
ARGUMENTS: Arguments = {
    GET_TRACK_NAME: (0,),
    GET_DEVICE_NAMES: (0,),
    GET_METER_LEVEL: (0,),
    GET_HAS_CLIP: (0, 0),
    GET_HAS_MIDI_INPUT: (0,),
    GET_TRACK_ARM: (0,),
}

# These two read a clip, so they need a slot that holds one. See the module docstring.
NEEDS_A_CLIP: frozenset[str] = frozenset({GET_CLIP_LENGTH, GET_NOTES})

# `/live/song/get/beat` is where Live *sends* beats; it has no handler at all. Verified
# in AbletonOSC's `song.py`: `current_song_time_changed` calls `osc_server.send` on that
# address, and `add_handler` is never called for it. Asking would time out, and a timeout
# here is indistinguishable from a wrong address — the probe would report a working
# mechanism as broken, which is finding 9 of Phase 1 all over again.
PUSH_ONLY: frozenset[str] = frozenset({GET_BEAT})

WRITES: frozenset[str] = frozenset(
    {
        SET_TEMPO,
        SET_QUANTIZATION,
        SET_TRACK_NAME,
        SET_TRACK_ARM,
        SET_LOOP,
        START_PLAYING,
        STOP_PLAYING,
        FIRE_SCENE,
        CREATE_CLIP,
        DELETE_CLIP,
        ADD_NOTES,
        REMOVE_NOTES,
        # These two mutate Live's listener state rather than the Set, but a read-only
        # probe must not leave a listener running behind it either.
        START_LISTEN_BEAT,
        STOP_LISTEN_BEAT,
    }
)

# How far to look for a clip. A Set is small; this is cheap and bounded.
SEARCH_TRACKS = 8
SEARCH_SCENES = 8


def is_read_only(address: str) -> bool:
    """The probe must not change the Set, and a setter answers nothing to see anyway."""
    return address not in WRITES and address not in PUSH_ONLY


def find_a_clip(transport: UdpOscTransport, timeout_s: float) -> tuple[int, int] | None:
    """The first slot in the Set that holds a clip, or None if the Set is empty."""
    for track in range(SEARCH_TRACKS):
        for scene in range(SEARCH_SCENES):
            try:
                reply = transport.request(GET_HAS_CLIP, track, scene, timeout_s=timeout_s)
            except DawError:
                # The handler raised, so there is no such track: stop scanning scenes.
                break
            if len(reply) == 3 and reply[2]:
                return track, scene
    return None


def probe(
    transport: UdpOscTransport, address: str, timeout_s: float, arguments: Arguments
) -> tuple[str, float]:
    started = time.monotonic()
    try:
        reply = transport.request(address, *arguments.get(address, ()), timeout_s=timeout_s)
    except DawError as exc:
        return f"FAILED — {exc}", (time.monotonic() - started) * 1000
    return f"ok  {reply!r}", (time.monotonic() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout-s", type=float, default=2.0)
    parser.add_argument("--address", help="probe only this one")
    args = parser.parse_args()

    wanted = (args.address,) if args.address else ALL_ADDRESSES
    skipped = [address for address in wanted if not is_read_only(address)]
    to_probe = [address for address in wanted if is_read_only(address)]

    transport = UdpOscTransport(OscSettings(host=args.host, timeout_s=args.timeout_s))
    failed: list[str] = []
    unconfirmed: list[str] = []
    try:
        clip = find_a_clip(transport, args.timeout_s)
        arguments = dict(ARGUMENTS)
        if clip is not None:
            arguments |= dict.fromkeys(NEEDS_A_CLIP, clip)
            sys.stderr.write(f"reading clip {clip[0]}/{clip[1]} for the clip getters\n\n")

        for address in to_probe:
            if address in NEEDS_A_CLIP and clip is None:
                sys.stderr.write(f"{address:<48} {'':<10} {'':>7}      NOT PROBED — no clip\n")
                unconfirmed.append(address)
                continue
            outcome, elapsed_ms = probe(transport, address, args.timeout_s, arguments)
            shown = arguments.get(address, ())
            sys.stderr.write(f"{address:<48} {shown!s:<10} {elapsed_ms:7.1f} ms  {outcome}\n")
            if outcome.startswith("FAILED"):
                failed.append(address)
    finally:
        transport.close()

    for address in skipped:
        why = "Live pushes it, nobody answers it" if address in PUSH_ONLY else "it writes"
        sys.stderr.write(f"{address:<48} {'':<10} {'':>7}      skipped — {why}\n")

    if failed:
        sys.stderr.write(
            f"\n{len(failed)} of {len(to_probe)} addresses did not answer: {failed}\n"
            "If Live is open and AbletonOSC is enabled, the address is wrong for this "
            "build: fix it in src/garagem/daw/abletonosc.py (and ALL_ADDRESSES), update "
            "the tests, and record it in docs/architecture/phase-1-findings.md.\n"
        )
        return 1

    sys.stderr.write(f"\nall {len(to_probe) - len(unconfirmed)} probed addresses answered.\n")
    if unconfirmed:
        sys.stderr.write(
            f"{len(unconfirmed)} could not be confirmed because the Set holds no clip: "
            f"{unconfirmed}.\nBuild the Set (scripts/bootstrap_set.py says what is missing), "
            "write a clip, and run this again — the reply shape of /live/clip/get/notes is "
            "what notes_from_reply assumes.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
