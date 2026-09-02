"""Compares the open Live Set against `session.toml`, and repairs what it safely can.

    uv run python scripts/bootstrap_set.py             # check only: reports, changes nothing
    uv run python scripts/bootstrap_set.py --apply     # repairs tempo, quantisation, names
    uv run python scripts/bootstrap_set.py --apply --force   # even while Live is playing

Four rules, each of them load-bearing (ADR-013):

- **It never creates or deletes a track.** The Live API cannot load an instrument onto
  a track, so a track created from here would receive MIDI correctly and make no sound
  at all — a bootstrap that reports success and produces silence. Missing tracks and
  missing instruments are printed as instructions for a human.
- **It refuses to run against a playing transport.** Renaming a track or changing the
  tempo under a playing Set is exactly the kind of write invariant 6 forbids. `--force`
  is there for when you know the Set is idle and Live disagrees.
- **It fails fast if Live is not answering.** No retry, no wait (P7).
- **Running it twice produces an identical Set.** The second run finds nothing fixable
  and therefore issues no writes at all, which is the Phase 1 idempotence criterion.

Exit code 0 means the Set matches the spec. 1 means something is still different — in
check mode, everything; with `--apply`, only what a human has to do in Live.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from garagem.daw import (
    AbletonOSCAdapter,
    DawPort,
    DawUnavailableError,
    OscSettings,
    apply_session,
    diff_session,
    load_session,
    observe,
    render_divergences,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / "session.toml"


def build_adapter(host: str, timeout_s: float) -> DawPort:
    return AbletonOSCAdapter(settings=OscSettings(host=host, timeout_s=timeout_s))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout-s", type=float, default=0.5)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="repair what the Live API can repair. Without it, nothing is written.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="run even while the transport is playing. Writes under a playing Set are "
        "what invariant 6 forbids — use only when you know it is idle.",
    )
    args = parser.parse_args()

    spec = load_session(args.session)
    daw = build_adapter(args.host, args.timeout_s)
    try:
        try:
            daw.warm()
        except DawUnavailableError as exc:
            # Expected, and the message already says what to do. A traceback here would
            # only bury it. Still exit 1: nothing was checked.
            sys.stderr.write(f"{exc}\n")
            return 1

        if daw.is_playing() and not args.force:
            sys.stderr.write(
                "Live is playing. Writing to a Set while it plays is what invariant 6 "
                "forbids: stop the transport, or pass --force if you know it is idle.\n"
            )
            return 1

        left = apply_session(daw, spec) if args.apply else diff_session(spec, observe(daw))
        if not left:
            sys.stderr.write(f"{args.session.name}: the Set matches.\n")
            return 0

        sys.stderr.write(render_divergences(left))
        if not args.apply and any(divergence.fixable for divergence in left):
            sys.stderr.write("Re-run with --apply to fix the lines marked `fix:`.\n")
        return 1
    finally:
        daw.close()


if __name__ == "__main__":
    raise SystemExit(main())
