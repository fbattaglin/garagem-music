"""`CueQueue`: arrival beats, order, coalesced knobs, a bound, and no lost cue under threads."""

from __future__ import annotations

import threading

from garagem.domain import Cue, CueKind, Macro, MacroKind
from garagem.transport import NO_BEAT, CueQueue
from garagem.transport.cues import describe


class Beat:
    def __init__(self) -> None:
        self.now = NO_BEAT

    def __call__(self) -> int:
        return self.now


def test_a_cue_is_stamped_with_the_beat_it_arrived_at_not_the_one_it_was_read_at() -> None:
    beat = Beat()
    queue = CueQueue(stamp=beat)
    beat.now = 13
    queue.offer(Cue(kind=CueKind.STOP))
    beat.now = 40
    (received,) = queue.drain()
    assert received.beat == 13


def test_a_cue_before_the_first_beat_is_kept_and_says_so() -> None:
    queue = CueQueue(stamp=Beat())
    queue.offer(Cue(kind=CueKind.FILL))
    assert queue.drain()[0].beat == NO_BEAT


def test_cues_come_out_in_the_order_they_went_in() -> None:
    queue = CueQueue(stamp=Beat())
    for kind in (CueKind.STOP, CueKind.FILL, CueKind.STOP):
        queue.offer(Cue(kind=kind))
    assert [received.control for received in queue.drain()] == [
        Cue(kind=CueKind.STOP),
        Cue(kind=CueKind.FILL),
        Cue(kind=CueKind.STOP),
    ]


def test_a_knob_turn_is_coalesced_to_where_the_knob_ended_up() -> None:
    queue = CueQueue(stamp=Beat())
    for step in range(100):
        queue.offer(Macro(kind=MacroKind.DENSITY, value=step / 99))
    queue.offer(Macro(kind=MacroKind.TENSION, value=0.5))
    drained = [received.control for received in queue.drain()]
    assert drained == [
        Macro(kind=MacroKind.DENSITY, value=1.0),
        Macro(kind=MacroKind.TENSION, value=0.5),
    ]


def test_a_pad_struck_during_a_knob_turn_is_not_buried() -> None:
    queue = CueQueue(stamp=Beat(), capacity=4)
    for step in range(50):
        queue.offer(Macro(kind=MacroKind.DENSITY, value=step / 49))
        if step == 25:
            queue.offer(Cue(kind=CueKind.CHORUS_NOW))
    assert Cue(kind=CueKind.CHORUS_NOW) in [received.control for received in queue.drain()]
    assert queue.dropped == 0


def test_past_capacity_the_oldest_cue_is_dropped_and_counted() -> None:
    queue = CueQueue(stamp=Beat(), capacity=2)
    for kind in (CueKind.STOP, CueKind.FILL, CueKind.END):
        queue.offer(Cue(kind=kind))
    assert [received.control.kind for received in queue.drain()] == [CueKind.FILL, CueKind.END]
    assert queue.dropped == 1


def test_draining_empties_the_queue() -> None:
    queue = CueQueue(stamp=Beat())
    queue.offer(Cue(kind=CueKind.STOP))
    queue.drain()
    assert queue.drain() == ()
    assert len(queue) == 0


def test_cues_offered_from_many_threads_are_all_there() -> None:
    queue = CueQueue(stamp=Beat(), capacity=10_000)

    def strike() -> None:
        for _ in range(500):
            queue.offer(Cue(kind=CueKind.FILL))

    threads = [threading.Thread(target=strike) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    drained = queue.drain()
    assert len(drained) == 4000
    assert [received.order for received in drained] == sorted(r.order for r in drained)


def test_the_log_says_which_family_a_cue_is_and_what_value_a_macro_has() -> None:
    assert describe(Cue(kind=CueKind.STOP)) == {"cue": "stop", "family": "bar"}
    assert describe(Macro(kind=MacroKind.TENSION, value=0.33333)) == {
        "macro": "tension",
        "value": 0.333,
    }
