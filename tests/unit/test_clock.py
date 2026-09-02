"""The BarClock, driven entirely by `FakeDawAdapter.push_beat`.

Nothing here sleeps. Musical time is a function call, which is what makes a three-minute
run a unit test rather than a three-minute unit test.

Two behaviours are worth reading closely. A skipped beat number still gives the right
bar, because Live sends absolute positions and loss is therefore self-healing. And a
beat that goes *backwards* is a rewind rather than a glitch: AbletonOSC's own
`current_song_time_changed` fires on that case, and the scheduler needs to know so it can
throw away a section queued for a bar that is no longer coming.
"""

from __future__ import annotations

import threading

from garagem.daw import FakeDawAdapter
from garagem.transport import NO_BEAT, BarClock


def a_clock() -> tuple[FakeDawAdapter, BarClock]:
    daw = FakeDawAdapter()
    clock = BarClock(daw)
    clock.start()
    return daw, clock


# ------------------------------------------------------------------------------ position


def test_before_live_says_anything_there_is_no_beat() -> None:
    """Not bar 0: bar 0 is a real bar, and writing into a Set that is not playing is not."""
    _, clock = a_clock()
    assert clock.beat == NO_BEAT
    assert clock.bar == NO_BEAT


def test_the_bar_advances_every_four_beats() -> None:
    daw, clock = a_clock()
    seen = []
    for beat in range(9):
        daw.push_beat(beat)
        seen.append(clock.bar)
    assert seen == [0, 0, 0, 0, 1, 1, 1, 1, 2]


def test_a_skipped_beat_still_gives_the_right_bar() -> None:
    """Absolute positions, so a lost datagram is corrected by the next one."""
    daw, clock = a_clock()
    daw.push_beat(0)
    daw.push_beat(9)
    assert clock.beat == 9
    assert clock.bar == 2


def test_bars_until_counts_forward_and_then_backward() -> None:
    daw, clock = a_clock()
    daw.push_beat(4)
    assert clock.bars_until(12) == 2.0
    assert clock.bars_until(0) == -1.0


def test_bars_until_before_the_first_beat_measures_from_the_start() -> None:
    _, clock = a_clock()
    assert clock.bars_until(8) == 2.0


# ------------------------------------------------------------------------------- rewinds


def test_a_rewind_bumps_the_epoch_rather_than_going_negative() -> None:
    daw, clock = a_clock()
    daw.push_beat(16)
    assert clock.epoch == 0

    daw.push_beat(0)
    assert clock.epoch == 1
    assert clock.beat == 0
    assert clock.bar == 0


def test_moving_forward_never_bumps_the_epoch() -> None:
    daw, clock = a_clock()
    for beat in range(20):
        daw.push_beat(beat)
    assert clock.epoch == 0


def test_two_rewinds_are_two_epochs() -> None:
    daw, clock = a_clock()
    daw.push_beat(8)
    daw.push_beat(0)
    daw.push_beat(8)
    daw.push_beat(4)
    assert clock.epoch == 2


# ------------------------------------------------------------------------------- waiting


def test_waiting_for_a_bar_already_reached_returns_at_once() -> None:
    daw, clock = a_clock()
    daw.push_beat(8)
    assert clock.wait_for_bar(1, timeout_s=0.0)


def test_waiting_returns_true_when_the_bar_arrives() -> None:
    """The push comes from another thread, as it does from Live's receive thread."""
    daw, clock = a_clock()
    arrived = threading.Thread(target=lambda: daw.push_beat(8))

    result: list[bool] = []
    waiter = threading.Thread(target=lambda: result.append(clock.wait_for_bar(2, 2.0)))
    waiter.start()
    arrived.start()
    arrived.join()
    waiter.join(timeout=2.0)

    assert result == [True]


def test_waiting_returns_false_on_timeout_rather_than_raising() -> None:
    """A bar that never came is usually a transport somebody stopped."""
    daw, clock = a_clock()
    daw.push_beat(0)
    assert not clock.wait_for_bar(99, timeout_s=0.01)


def test_stopping_wakes_a_waiter_instead_of_leaving_it_blocked() -> None:
    daw, clock = a_clock()
    daw.push_beat(0)
    result: list[bool] = []
    waiter = threading.Thread(target=lambda: result.append(clock.wait_for_bar(99, 5.0)))
    waiter.start()
    clock.stop()
    daw.push_beat(1)
    waiter.join(timeout=2.0)

    assert not waiter.is_alive()
    assert result == [False]


# ----------------------------------------------------------------------------- lifecycle


def test_starting_asks_live_to_push() -> None:
    daw, clock = a_clock()
    assert "listen_beats" in daw.calls
    assert clock.listening


def test_starting_twice_registers_once() -> None:
    daw, clock = a_clock()
    clock.start()
    assert daw.calls.count("listen_beats") == 1


def test_stopping_unlistens() -> None:
    daw, clock = a_clock()
    clock.stop()
    assert daw.calls[-1] == "unlisten_beats"
    assert not clock.listening


def test_the_clock_polls_live_for_nothing() -> None:
    """A clock built on `song_time_beats` would burn the thread it is measuring."""
    daw, clock = a_clock()
    for beat in range(16):
        daw.push_beat(beat)
        _ = clock.bar, clock.beat, clock.epoch
    assert daw.calls == ["listen_beats"]


def test_the_arrival_stamp_is_none_until_live_speaks() -> None:
    daw, clock = a_clock()
    assert clock.seconds_since_beat() is None
    daw.push_beat(0)
    since = clock.seconds_since_beat()
    assert since is not None and since >= 0.0
