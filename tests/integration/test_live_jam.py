"""The Phase 2 transport, against a real Ableton Live.

    uv run pytest -m live -q

Everything in `tests/unit/test_jam_offline.py` is already proven against the fake: the
sequence, the scene alternation, the slack, the determinism. What only a real Live can
answer is whether the *mechanism* works — whether Live actually pushes beats, whether the
BarClock tracks them, whether a write into the silent scene lands while the other one
plays, and whether all four instruments make a sound.

So this file runs one short performance, about forty seconds, and asks those questions of
it. The full three minutes is Step 38 of the plan and is run by hand, because it ends in
somebody listening.

The Set must already match `session.toml`. `uv run python scripts/bootstrap_set.py`
exits 0 when it does. These tests share one run and are ordered.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from garagem.daw import (
    AbletonOSCAdapter,
    UdpOscTransport,
    diff_session,
    load_session,
    observe,
    render_divergences,
)
from garagem.domain import Feel, Instrument
from garagem.engines import SongBrief, arrange
from garagem.obs import Event, EventLog
from garagem.transport import BarClock, Scheduler, ScoreBuffer

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_session(ROOT / "session.toml")

TRACKS = {
    Instrument.DRUMS: 0,
    Instrument.BASS: 1,
    Instrument.GUITAR: 2,
    Instrument.KEYS: 3,
}

SEED = 7
# Long enough for three section changes at 132 BPM, short enough that a failing suite
# does not cost a coffee. The three minutes is Step 38, by hand.
PERFORMANCE_SECONDS = 40.0

# One 1-bar quantum at 132 BPM is 1.82 s.
LAUNCH_TIMEOUT_S = 3.0
# The beat listener pushes every 455 ms at 132 BPM; three of those is a generous wait
# for the first one and still short enough that silence is obvious.
FIRST_BEAT_TIMEOUT_S = 1.5
METER_POLL_S = 0.05


class Run:
    """One whole performance against Live, with everything it produced."""

    def __init__(self) -> None:
        self.beats: list[int] = []
        self.bars: list[tuple[int, int]] = []
        self.meters: dict[Instrument, float] = dict.fromkeys(TRACKS, 0.0)
        self.log = EventLog(None)
        self.dropped = 0
        self.handler_errors = 0


@pytest.fixture(scope="module")
def performance() -> Iterator[Run]:
    """Plays a whole short song, sampling the meters as it goes.

    Deliberately does not skip when Live is closed: a skipped test reads as "nothing to
    see here", and `DawUnavailableError` with its own message is what gets Live opened.
    """
    daw = AbletonOSCAdapter.from_env()
    run = Run()
    clock = BarClock(daw)
    try:
        daw.warm()
        daw.stop_playing()

        divergences = diff_session(SPEC, observe(daw))
        assert divergences == (), f"\n{render_divergences(divergences)}"

        brief = SongBrief(
            key=4,
            scale="minor",
            bpm=SPEC.tempo_bpm,
            feel=Feel.STRAIGHT8,
            minimum_seconds=PERFORMANCE_SECONDS,
        )
        form = arrange(brief, SEED)

        # No second `listen_beats` here: registering one replaces the BarClock's, which
        # is exactly how the first version of this file managed to run a performance with
        # a clock that never advanced. Everything reads the clock instead.
        clock.start()
        daw.start_playing()

        scheduler = Scheduler(daw, clock, ScoreBuffer(), TRACKS, run.log, seed=SEED)
        scheduler.begin(form)
        while not scheduler.finished:
            if not clock.wait_for_bar(clock.bar + 1, timeout_s=15.0):
                break
            run.beats.append(clock.beat)
            run.bars.append((clock.beat, clock.bar))
            for instrument, track in TRACKS.items():
                run.meters[instrument] = max(run.meters[instrument], daw.meter_level(track))
            scheduler.tick()

        # The live suite runs against the real transport, which is the only one with a
        # router. Narrowed rather than ignored, so a fake here would fail loudly.
        transport = daw.transport
        assert isinstance(transport, UdpOscTransport)
        run.dropped = transport.router.dropped
        run.handler_errors = transport.router.handler_errors
        yield run
    finally:
        clock.stop()
        daw.stop_playing()
        daw.close()


def fires(run: Run) -> list[Event]:
    return list(run.log.of_kind("scene_fired"))


def test_live_pushed_beats_and_they_only_went_forward(performance: Run) -> None:
    """Push, not poll. If this is empty, `start_listen/beat` did not register."""
    assert performance.beats
    assert performance.beats == sorted(performance.beats)
    assert performance.beats[-1] > performance.beats[0]


def test_the_bar_clock_tracked_live_within_one_bar(performance: Run) -> None:
    """Bar-granular is the promise (ADR-015). Beat 8 is bar 2, and nothing else."""
    assert performance.bars
    assert all(bar == beat // 4 for beat, bar in performance.bars)


def test_no_beat_message_was_dropped_while_the_writes_were_happening(performance: Run) -> None:
    """A write costs ~2 s of the same control-surface thread that reports the beat.

    ADR-014's receive thread exists so those two do not collide. `dropped` rising here
    would mean they still do.
    """
    assert performance.dropped == 0
    assert performance.handler_errors == 0


def test_every_section_was_written_and_fired(performance: Run) -> None:
    written = performance.log.of_kind("section_written")
    assert len(fires(performance)) == len(written)
    assert len(written) >= 3


def test_sections_were_written_into_the_scene_that_was_not_playing(performance: Run) -> None:
    """Invariant 6, against a real Set: a playing clip is never rewritten."""
    playing: object = None
    for event in performance.log:
        if event.kind == "section_written" and playing is not None:
            assert event.detail["scene"] != playing
        elif event.kind == "scene_fired":
            playing = event.detail["scene"]


def test_every_transition_fired_with_a_bar_of_slack(performance: Run) -> None:
    transitions = [event for event in fires(performance) if not event.detail["first"]]
    assert transitions
    assert all(int(str(event.detail["slack_bars"])) >= 1 for event in transitions)


def test_all_four_instruments_made_a_sound(performance: Run) -> None:
    """This is a band now. One track rising above zero is not the same claim."""
    silent = [str(instrument) for instrument, peak in performance.meters.items() if peak <= 0.0]
    assert not silent, f"no signal from {silent}"


def test_the_whole_performance_made_no_network_call(performance: Run) -> None:
    """P2, asserted rather than assumed. The `live` mark lifts the fuse, so check the code."""
    import garagem.engines.band as band
    import garagem.transport.scheduler as scheduler

    for module in (band, scheduler):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert "httpx" not in source
        assert "socket" not in source
