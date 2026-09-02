"""The ScoreBuffer: what a gap means, and what it must never do.

Two of these tests are about behaviour the buffer deliberately does *not* have. `take`
does not block, and `take` does not raise. Both are P2: a missing section means the
deterministic engine plays instead, and a buffer that made the player wait would put the
generator back on the critical path — the exact coupling invariant 1 forbids.
"""

from __future__ import annotations

import threading

from garagem.domain import Chart, Chord, Feel, Quality, Section, SectionScore
from garagem.transport import WINDOW, ScoreBuffer

SECTION = Section(
    name="verse",
    bars=8,
    key=4,
    scale="minor",
    feel=Feel.STRAIGHT8,
    bpm=132.0,
    dyn=3,
    tension=0.4,
    chart=Chart(chords=(Chord(root=4, quality=Quality.MINOR),)),
)


def a_score(seed: int) -> SectionScore:
    return SectionScore(section=SECTION, parts=(), seed=seed)


# ------------------------------------------------------------------------- the round trip


def test_a_section_offered_comes_back() -> None:
    buffer = ScoreBuffer()
    assert buffer.offer(0, a_score(7))
    assert buffer.take(0) == a_score(7)


def test_taking_a_section_that_is_not_there_gives_none() -> None:
    """Which means *play the fallback*. It is not an error and never raises."""
    assert ScoreBuffer().take(3) is None


def test_taking_twice_gives_the_same_section() -> None:
    """A looping clip may need it again; `advance` is what evicts, not `take`."""
    buffer = ScoreBuffer()
    buffer.offer(1, a_score(7))
    assert buffer.take(1) == buffer.take(1)


# ------------------------------------------------------------------------------ the window


def test_a_section_for_an_index_already_past_is_refused() -> None:
    """The generator finished after the music needed it; the floor already played it."""
    buffer = ScoreBuffer()
    buffer.advance(4)
    assert not buffer.offer(3, a_score(7))
    assert buffer.refused == 1
    assert buffer.take(3) is None


def test_a_section_too_far_ahead_is_refused() -> None:
    """Otherwise a generator runs away from a transport somebody has stopped."""
    buffer = ScoreBuffer()
    assert not buffer.offer(WINDOW + 1, a_score(7))
    assert buffer.refused == 1


def test_the_window_never_holds_more_than_it_promises() -> None:
    buffer = ScoreBuffer()
    for index in range(20):
        buffer.offer(index, a_score(index))
    assert len(buffer) <= WINDOW + 1


def test_advancing_evicts_what_is_behind() -> None:
    buffer = ScoreBuffer()
    buffer.offer(0, a_score(0))
    buffer.offer(1, a_score(1))
    buffer.advance(1)
    assert buffer.pending() == (1,)
    assert buffer.floor == 1


def test_advancing_never_goes_backwards() -> None:
    buffer = ScoreBuffer()
    buffer.advance(5)
    buffer.advance(2)
    assert buffer.floor == 5


def test_clearing_throws_everything_away() -> None:
    """What a rewind means: those bars are not coming."""
    buffer = ScoreBuffer()
    buffer.offer(0, a_score(0))
    buffer.offer(1, a_score(1))
    buffer.clear()
    assert buffer.pending() == ()


# ------------------------------------------------------------------------------ reporting


def test_pending_reports_what_is_genuinely_there() -> None:
    buffer = ScoreBuffer()
    buffer.offer(1, a_score(1))
    assert buffer.pending() == (1,)


def test_wanted_names_the_gaps_inside_the_window() -> None:
    buffer = ScoreBuffer()
    buffer.offer(0, a_score(0))
    assert buffer.wanted() == (1, 2)


def test_wanted_is_empty_when_the_window_is_full() -> None:
    buffer = ScoreBuffer()
    for index in range(WINDOW + 1):
        buffer.offer(index, a_score(index))
    assert buffer.wanted() == ()


# ------------------------------------------------------------------------------- threads


def test_offering_and_taking_from_two_threads_loses_nothing() -> None:
    """The generator and the player never call each other; they meet only here."""
    buffer = ScoreBuffer(window=1000)
    start = threading.Barrier(2)
    taken: list[int] = []

    def generate() -> None:
        start.wait()
        for index in range(500):
            buffer.offer(index, a_score(index))

    def play() -> None:
        start.wait()
        for index in range(500):
            score = buffer.take(index)
            if score is not None:
                taken.append(score.seed)

    threads = [threading.Thread(target=generate), threading.Thread(target=play)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert len(taken) == len(set(taken))
    assert all(seed == index for index, seed in enumerate(sorted(taken)) if seed == index)
    assert len(buffer) == 500


def test_taking_never_blocks_even_while_a_writer_is_busy() -> None:
    """A `take` that waited would put the generator back on the critical path."""
    buffer = ScoreBuffer(window=100)
    done = threading.Event()

    def generate() -> None:
        for index in range(50):
            buffer.offer(index, a_score(index))
        done.set()

    writer = threading.Thread(target=generate)
    writer.start()
    for _ in range(200):
        buffer.take(0)
    writer.join(timeout=5.0)
    assert done.is_set()
