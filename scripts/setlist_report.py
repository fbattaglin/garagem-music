"""Reads the last setlist session out of an event log, against Phase 5's criteria (ADR-025).

    uv run python scripts/setlist_report.py --share 20

The Wi-Fi-off session is not one run: it is the setlist's songs played one after another, each
its own `jam.py --setlist`. `jam.py` reports each song as it ends; this reports the session they
add up to, which is what the phase gate is held to.

**A session is the log's trailing run of setlist songs** — every performance after the last one
that was not played from a setlist. So an ordinary jam played in between starts a new session,
and the report says how many songs it found rather than assuming three.

Read-only: it opens no socket, needs no Live and spends nothing. It exits 1 when a criterion is
not met, so the gate can be run as a command rather than by eye.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from garagem.obs import (
    SETLIST_SESSION_S,
    load_events,
    render_checks,
    setlist_session_checks,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "bench" / "jam.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument(
        "--share",
        type=int,
        help="how many sections must have played from the setlist's takes, fixed before the "
        "session from an offline rehearsal (ADR-025)",
    )
    parser.add_argument("--seconds", type=float, default=SETLIST_SESSION_S)
    args = parser.parse_args()

    if not args.log.exists():
        sys.stderr.write(f"{args.log} does not exist: nothing has been played to report on\n")
        return 1

    events = list(load_events(args.log))
    checks = setlist_session_checks(events, minimum_seconds=args.seconds, share_floor=args.share)
    # No share line here: `model_share` would count the whole log, and the session's own
    # share is what `--share` already checks.
    sys.stderr.write(render_checks(checks, phase="Phase 5, the session this log ends with"))
    return 0 if all(check.met for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
