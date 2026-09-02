"""`BarClock`: where we are in the music, read from beats Live pushes.

**This is not an audio clock and must never become one** (ADR-015). It answers "which
bar are we in" and "how long until that bar", to a tolerance of hundreds of milliseconds.
It never interpolates between beats, never drives a note's onset, and never corrects
Live's drift — there is no drift to correct, because Live is the master and this is a
reader. `.claude/rules/realtime.md`'s "< 2 ms" is Live's audio clock, not this.

**Push, not poll.** `song_time_beats()` still exists and is still the wrong tool: every
call is a ~100 ms round trip on the same control-surface thread it is trying to measure.
`listen_beats` costs one datagram every 455 ms at 132 BPM and costs Live nothing.

**Loss is self-healing and needs no counter.** Live sends `int(current_song_time)`, an
absolute beat number rather than a delta, so a dropped datagram is corrected by the next
one. That is a property of AbletonOSC's `current_song_time_changed`, not an assumption.

**A rewind is visible, and is not a glitch.** The same handler fires when the playhead
jumps backwards, and a beat lower than the last means the musician moved it. `epoch`
increments when that happens. The scheduler compares epochs on its own thread and throws
away anything it had queued for a bar that is no longer coming — which is a data
structure crossing the boundary, not a callback (P1, ADR-014).

The beat handler runs on the transport's receive thread and does three things: store the
number, note the arrival, wake anybody waiting. Everything else happens on the waiting
thread.
"""

from __future__ import annotations

import threading
import time

from garagem.daw import DawPort

BEATS_PER_BAR = 4.0

# Before Live has said anything. Not 0: bar 0 is a real bar, and a clock that claimed to
# be in it before the transport rolled would have the scheduler writing into a Set that
# is not playing.
NO_BEAT = -1


class BarClock:
    """Live's transport position, in bars, as far as anyone above needs to know."""

    def __init__(self, daw: DawPort, *, beats_per_bar: float = BEATS_PER_BAR) -> None:
        self._daw = daw
        self._beats_per_bar = beats_per_bar
        self._changed = threading.Condition()
        self._beat = NO_BEAT
        self._arrived_at: float | None = None
        self._epoch = 0
        self._listening = False

    # ------------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Ask Live to push. Idempotent: starting twice is not an error."""
        if self._listening:
            return
        self._daw.listen_beats(self._on_beat)
        self._listening = True

    def stop(self) -> None:
        """Stop the push and wake every waiter, so nothing blocks through a teardown."""
        if self._listening:
            self._daw.unlisten_beats()
            self._listening = False
        with self._changed:
            self._changed.notify_all()

    # -------------------------------------------------------------------------- reading

    @property
    def beat(self) -> int:
        """The last beat Live reported, or `NO_BEAT` before the first one."""
        with self._changed:
            return self._beat

    @property
    def bar(self) -> int:
        """The bar that beat is in, or `NO_BEAT` before the first one."""
        with self._changed:
            return self._bar_of(self._beat)

    @property
    def epoch(self) -> int:
        """Increments on every rewind. A section queued in an older epoch is stale."""
        with self._changed:
            return self._epoch

    @property
    def listening(self) -> bool:
        return self._listening

    def seconds_since_beat(self) -> float | None:
        """Wall time since the last beat arrived, or `None` if none ever has.

        Wall time on purpose and only here: this answers "has Live gone quiet", which is
        a question about the network and not about the music.
        """
        with self._changed:
            if self._arrived_at is None:
                return None
            return time.monotonic() - self._arrived_at

    def bars_until(self, beat: int) -> float:
        """How many bars from where Live is now to `beat`. Negative once it has passed."""
        with self._changed:
            if self._beat == NO_BEAT:
                return float(beat) / self._beats_per_bar
            return (beat - self._beat) / self._beats_per_bar

    def wait_for_bar(self, bar: int, timeout_s: float) -> bool:
        """Block *the caller's* thread until Live reaches `bar`. Never the receive one.

        Returns False on timeout rather than raising: a bar that did not arrive is
        usually a transport somebody stopped, and the caller's answer to that is to stop
        too, not to handle an exception.
        """
        deadline = time.monotonic() + timeout_s
        with self._changed:
            while self._bar_of(self._beat) < bar:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._listening:
                    return self._bar_of(self._beat) >= bar
                self._changed.wait(remaining)
            return True

    # ------------------------------------------------------------------------ the handler

    def _on_beat(self, beat: int) -> None:
        """Runs on the receive thread. Store, stamp, wake. Nothing else (ADR-014)."""
        with self._changed:
            if beat < self._beat:
                self._epoch += 1
            self._beat = beat
            self._arrived_at = time.monotonic()
            self._changed.notify_all()

    def _bar_of(self, beat: int) -> int:
        if beat == NO_BEAT:
            return NO_BEAT
        return int(beat // self._beats_per_bar)
