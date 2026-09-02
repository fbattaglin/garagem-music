"""A model-generated section, through a real Ableton Live.

    uv run pytest -m live -q

`test_live_jam.py` proved the transport against Live with the deterministic engine
driving it. This file adds the one thing Phase 3 built and never tried against real
hardware: a `Producer` on its own thread, calling a real model, while the bar loop plays.

**The question this exists to answer is ADR-016's**, and it cannot be asked of a fake.
The producer holds an event loop and a network socket; the beat listener holds the
control-surface thread that Live pushes into; a clip write costs ~1.2 s of that same
thread (`phase-2-findings.md` §3). Everything offline says those three do not collide.
Only a real Set, a real socket and a real four-second API call can say it for certain, and
`dropped` rising by one is what "they still collide" looks like.

**This test spends real money**, which nothing else in the suite does. Three or four
sections at roughly $0.0035 each, hard-capped by the `Governor` at `BUDGET_USD` — if the
cap is ever hit the run fails rather than degrading quietly, because a live test that
silently played the floor would prove exactly nothing about generation.

The Set must already match `session.toml`; `uv run python scripts/bootstrap_set.py` exits
0 when it does. These tests share one run and are ordered.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from garagem.agents import Producer, structural, worth_asking
from garagem.agents.section import deadline_for
from garagem.daw import (
    AbletonOSCAdapter,
    UdpOscTransport,
    diff_session,
    load_session,
    observe,
    render_divergences,
)
from garagem.domain import Feel, Instrument, Section
from garagem.engines import SongBrief, arrange
from garagem.llm import (
    AnthropicAdapter,
    BreakerPolicy,
    Budget,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    load_catalog,
    prices_of,
)
from garagem.obs import Event, EventLog
from garagem.transport import BarClock, Scheduler, ScoreBuffer

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_session(ROOT / "session.toml")
CATALOG = load_catalog(ROOT / "config" / "models.toml")
MODEL = structural(CATALOG)

TRACKS = {
    Instrument.DRUMS: 0,
    Instrument.BASS: 1,
    Instrument.GUITAR: 2,
    Instrument.KEYS: 3,
}

SEED = 7

# Long enough for three section changes at 132 BPM and for the producer to stay busy
# throughout, short enough that a failing suite costs cents. `test_live_jam.py` uses the
# same figure so the two runs are comparable.
PERFORMANCE_SECONDS = 40.0

# A hard ceiling, not an estimate. Four sections measured at ~$0.0035 each leaves an order
# of magnitude of headroom, so hitting this means something is wrong rather than expensive.
BUDGET_USD = Decimal("0.10")

# The bounded wait `scripts/jam.py` does before the transport rolls. Without it the first
# section is always the floor: `Scheduler.begin` writes and fires immediately, and no
# four-second generation beats that.
PRIME_MARGIN_S = 1.0
PRIME_POLL_S = 0.05


class Run:
    """One whole performance against Live, with everything it produced."""

    def __init__(self) -> None:
        self.beats: list[int] = []
        self.meters: dict[Instrument, float] = dict.fromkeys(TRACKS, 0.0)
        self.log = EventLog(None)
        self.dropped = 0
        self.handler_errors = 0
        self.spent_usd = Decimal(0)
        self.form: tuple[Section, ...] = ()
        # What the producer had attempted when the transport started rolling, against what
        # it had attempted when the music stopped. The gap is the evidence that generation
        # and beat handling genuinely overlapped — without it, `dropped == 0` says only
        # that nothing was happening.
        self.attempted_at_start = 0
        self.attempted_at_end = 0
        self.primed_s = 0.0


def prime(buffer: ScoreBuffer, first: Section) -> float:
    """Wait for section 0, or give up. `scripts/jam.py`'s wait, and for its reason."""
    timeout_s = deadline_for(first) + PRIME_MARGIN_S
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        if buffer.take(0) is not None:
            break
        time.sleep(PRIME_POLL_S)
    return time.monotonic() - started


@pytest.fixture(scope="module")
def performance() -> Iterator[Run]:
    """A whole short song with a model writing it, sampling the meters as it goes.

    Deliberately does not skip when Live is closed or the key is missing: a skipped test
    reads as "nothing to see here", and the adapter's own error naming the environment
    variable is what actually gets it set.
    """
    daw = AbletonOSCAdapter.from_env()
    governor = Governor(
        Budget(
            session_usd=BUDGET_USD,
            per_minute_usd=BUDGET_USD,
            prices=prices_of(CATALOG),
        )
    )
    provider = GuardedProvider(
        AnthropicAdapter.from_env(), governor=governor, breaker=CircuitBreaker(BreakerPolicy())
    )
    run = Run()
    clock = BarClock(daw)
    producer: Producer | None = None
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
        run.form = arrange(brief, SEED)
        buffer = ScoreBuffer()

        producer = Producer(provider, buffer, run.log, run.form, model=MODEL, seed=SEED)
        producer.start()
        run.primed_s = prime(buffer, run.form[0])

        # No second `listen_beats`: registering one replaces the BarClock's, which is how
        # an earlier version of the sibling file ran a performance on a clock that never
        # advanced. Everything reads the clock instead.
        clock.start()
        daw.start_playing()

        scheduler = Scheduler(daw, clock, buffer, TRACKS, run.log, seed=SEED)
        scheduler.begin(run.form)
        run.attempted_at_start = len(producer.attempted)
        while not scheduler.finished:
            if not clock.wait_for_bar(clock.bar + 1, timeout_s=15.0):
                break
            run.beats.append(clock.beat)
            for instrument, track in TRACKS.items():
                run.meters[instrument] = max(run.meters[instrument], daw.meter_level(track))
            scheduler.tick()
        run.attempted_at_end = len(producer.attempted)

        transport = daw.transport
        assert isinstance(transport, UdpOscTransport)
        run.dropped = transport.router.dropped
        run.handler_errors = transport.router.handler_errors
        run.spent_usd = governor.snapshot().spent_usd
        yield run
    finally:
        if producer is not None:
            producer.stop()
        clock.stop()
        daw.stop_playing()
        daw.close()


def parsed(run: Run) -> list[Event]:
    """Sections the model delivered. `section_parsed`, never `section_generated`."""
    return list(run.log.of_kind("section_parsed"))


# ---------------------------------------------------------------- the model was in it


def test_the_model_wrote_at_least_one_section_that_played(performance: Run) -> None:
    """The whole point. Phase 2 ran this path fourteen times out of fourteen on the floor.

    Not "every section": a four-bar intro falls under `MIN_DEADLINE_S` and is declined on
    purpose, and a real network can lose one to the tail. One section that a model wrote,
    coming out of real speakers, is the claim this criterion makes.
    """
    delivered = parsed(performance)
    assert delivered, "no section reached the buffer from the model"
    assert all(event.detail["source"] == "model" for event in delivered)

    from_buffer = [
        event
        for event in performance.log.of_kind("section_generated")
        if event.detail.get("source") == "buffer"
    ]
    assert from_buffer, "the model delivered, but the scheduler still played the floor"


def test_the_run_stayed_inside_its_budget(performance: Run) -> None:
    """A cap that is never approached is the point; one that is hit is a bug report."""
    assert performance.spent_usd > 0, "nothing was spent, so nothing was generated"
    assert performance.spent_usd < BUDGET_USD


def test_every_section_the_producer_skipped_said_why(performance: Run) -> None:
    """Declining is not failing, and the log has to tell them apart (§15)."""
    declined = {
        str(event.detail.get("reason"))
        for event in performance.log.of_kind("fallback")
        if event.detail.get("reason") == "no_time"
    }
    unaskable = [section for section in performance.form if not worth_asking(section)]
    assert bool(declined) == bool(unaskable)


# --------------------------------------------------------------- ADR-016, against Live


def test_no_beat_was_dropped_while_a_generation_was_in_flight(performance: Run) -> None:
    """The question ADR-016 exists to answer, asked of real hardware.

    The producer's thread holds a socket and an event loop; Live pushes beats into the
    control-surface thread; a clip write costs ~1.2 s of that same thread. `dropped`
    rising by one means the three collided after all.
    """
    assert performance.dropped == 0
    assert performance.handler_errors == 0


def test_generation_actually_overlapped_the_music(performance: Run) -> None:
    """Otherwise the test above proves only that nothing was happening.

    The producer must still have been working *after* the transport started rolling. If
    priming happened to fetch everything up front, this fails and the assertion about
    dropped beats is worthless — better to know that than to bank it.
    """
    assert performance.attempted_at_end > performance.attempted_at_start, (
        f"the producer attempted {performance.attempted_at_start} sections before the "
        "music started and none during it; the dropped-beat assertion proves nothing"
    )


def test_the_clock_kept_moving_the_whole_time(performance: Run) -> None:
    """A generation must never stall the bar loop. It has its own thread so it cannot."""
    assert performance.beats
    assert performance.beats == sorted(performance.beats)
    assert performance.beats[-1] > performance.beats[0]


# ------------------------------------------------------------- the music came out right


def test_a_generated_section_went_into_the_scene_that_was_not_playing(
    performance: Run,
) -> None:
    """Invariant 6 against a real Set, with the model in the loop this time."""
    playing: object = None
    for event in performance.log:
        if event.kind == "section_written" and playing is not None:
            assert event.detail["scene"] != playing
        elif event.kind == "scene_fired":
            playing = event.detail["scene"]


def test_every_transition_fired_with_a_bar_of_slack(performance: Run) -> None:
    """Generation eats into the lookahead; the slack is what says it did not eat it all."""
    transitions = [
        event for event in performance.log.of_kind("scene_fired") if not event.detail["first"]
    ]
    assert transitions
    assert all(int(str(event.detail["slack_bars"])) >= 1 for event in transitions)


def test_all_four_instruments_made_a_sound(performance: Run) -> None:
    """A model wrote some of these parts. One track rising is not the same claim."""
    silent = [str(instrument) for instrument, peak in performance.meters.items() if peak <= 0.0]
    assert not silent, f"no signal from {silent}"


def test_whatever_the_model_got_wrong_was_logged_with_enough_to_fix_it(
    performance: Run,
) -> None:
    """The telemetry path, against output no fake ever produces.

    A real model writes real violations — a grid of fifteen characters, a voicing spelled
    out in English. The offline suite can only replay the ones already recorded. This
    asserts the shape of what gets logged when a fresh one arrives: a rule name and the
    text of what was actually wrong, which is the difference between knowing the rate and
    being able to change the prompt (`phase-3-findings.md` §1).

    Zero violations is a passing run, not a skipped one: 93% of sections have none.
    """
    for event in performance.log.of_kind("schema_violation"):
        assert event.detail.get("rule"), "a violation with no rule name counts nothing"
        assert str(event.detail.get("detail", "")).strip(), (
            f"rule {event.detail.get('rule')!r} logged without its text; diagnosing it "
            "would cost another run against a real Set"
        )
        assert event.detail.get("section") is not None
