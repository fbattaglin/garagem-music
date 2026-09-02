"""Clip-ahead, double scene buffering, and the rules that must be impossible to break.

Everything here is driven by `FakeDawAdapter.push_beat` and `Scheduler.tick`. Nothing
sleeps and nothing opens a socket: musical time is a function call, so three minutes of
music costs milliseconds and the result is the same on every machine.

The assertions that carry the phase are the negative ones — no write ever landed in the
scene that was playing, and no fire happened with less than a bar of slack. Both are read
out of the event log rather than out of the scheduler's own opinion of itself.
"""

from __future__ import annotations

import pytest

from garagem.daw import DawTimeoutError, FakeDawAdapter
from garagem.domain import Feel, Instrument, Section
from garagem.engines import play_section
from garagem.obs import Event, EventLog
from garagem.theory import parse_chart
from garagem.transport import BarClock, Scheduler, ScoreBuffer

TRACKS = {
    Instrument.DRUMS: 0,
    Instrument.BASS: 1,
    Instrument.GUITAR: 2,
    Instrument.KEYS: 3,
}


def a_section(name: str = "verse", bars: int = 4, **extra: object) -> Section:
    base: dict[str, object] = {
        "name": name,
        "bars": bars,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": parse_chart("| Em | C | G | D |"),
    }
    return Section.model_validate(base | extra)


FORM = (a_section("intro", 2), a_section("verse", 4), a_section("chorus", 4), a_section("outro", 2))


class Rig:
    """A whole transport, offline. `play(beats)` is the passage of musical time."""

    def __init__(self, **kwargs: object) -> None:
        self.daw = FakeDawAdapter(scenes=4)
        self.clock = BarClock(self.daw)
        self.clock.start()
        self.buffer = ScoreBuffer()
        self.log = EventLog(None)
        self.scheduler = Scheduler(
            self.daw,
            self.clock,
            self.buffer,
            TRACKS,
            self.log,
            seed=7,
            **kwargs,  # type: ignore[arg-type]
        )
        self.beat = 0

    def play(self, sections: tuple[Section, ...] = FORM, limit: int = 2000) -> None:
        self.scheduler.begin(sections)
        while not self.scheduler.finished and self.beat < limit:
            self.daw.push_beat(self.beat)
            self.scheduler.tick()
            self.beat += 1

    def of_kind(self, kind: str) -> tuple[Event, ...]:
        return self.log.of_kind(kind)


# -------------------------------------------------------------------------- the sequence


def test_every_section_is_played_in_order() -> None:
    rig = Rig()
    rig.play()
    fired = rig.of_kind("scene_fired")
    assert [event.detail["section"] for event in fired] == [0, 1, 2, 3]
    assert [event.detail["name"] for event in fired] == ["intro", "verse", "chorus", "outro"]


def test_the_run_ends_after_the_last_section_rather_than_at_its_fire() -> None:
    rig = Rig()
    rig.play()
    assert rig.scheduler.finished
    assert rig.scheduler.index == len(FORM) - 1


def test_the_scenes_alternate() -> None:
    rig = Rig()
    rig.play()
    scenes = [event.detail["scene"] for event in rig.of_kind("scene_fired")]
    assert scenes == [0, 1, 0, 1]


def test_an_empty_form_finishes_without_touching_live() -> None:
    rig = Rig()
    rig.scheduler.begin(())
    assert rig.scheduler.finished
    assert rig.daw.calls == ["listen_beats"]


# ----------------------------------------------------------------- invariant 6, mechanically


def test_no_write_ever_landed_in_the_scene_that_was_playing() -> None:
    """Invariant 6. Checked from the log, not from the scheduler's opinion of itself."""
    rig = Rig()
    rig.play()

    playing: object = 0
    for event in rig.log:
        if event.kind == "section_written":
            assert event.detail["scene"] != playing or event.detail["section"] == 0
        elif event.kind == "scene_fired" and not event.detail["first"]:
            playing = event.detail["scene"]


def test_the_next_section_is_written_while_the_current_one_plays() -> None:
    """Written early, because four tracks of OSC cost ~400 ms of somebody's thread."""
    rig = Rig()
    rig.play()
    writes = {event.detail["section"]: event.at_beats for event in rig.of_kind("section_written")}
    fires = {
        event.detail["section"]: event.at_beats
        for event in rig.of_kind("scene_fired")
        if not event.detail["first"]
    }
    for section, fired_at in fires.items():
        assert writes[section] < fired_at


def test_writing_into_the_playing_scene_is_refused_outright() -> None:
    """Belt as well as braces: the rule is enforced, not only arranged for."""
    rig = Rig()
    rig.play()
    score = play_section(FORM[0], 7)
    with pytest.raises(Exception, match="invariant 6"):
        rig.scheduler._write(score, rig.scheduler.playing_scene, 99)


# --------------------------------------------------------------------------------- slack


def test_every_transition_fired_with_at_least_a_bar_of_slack() -> None:
    rig = Rig()
    rig.play()
    transitions = [event for event in rig.of_kind("scene_fired") if not event.detail["first"]]
    assert transitions
    assert all(int(str(event.detail["slack_bars"])) >= 1 for event in transitions)


def test_the_opening_fire_is_marked_as_the_downbeat_not_as_a_late_transition() -> None:
    """There is no predecessor to be late for."""
    first = rig_first_fire()
    assert first.detail["first"] is True
    assert first.detail["section"] == 0


def rig_first_fire() -> Event:
    rig = Rig()
    rig.play()
    return rig.of_kind("scene_fired")[0]


# ------------------------------------------------------------------------- the fallback


def test_a_section_missing_from_the_buffer_is_generated_and_logged_as_a_fallback() -> None:
    """In Phase 2 this is always the path: there is no LLM yet."""
    rig = Rig()
    rig.play()
    fallbacks = rig.of_kind("fallback")
    assert len(fallbacks) == len(FORM)
    assert {event.detail["reason"] for event in fallbacks} == {"not_in_buffer"}


def test_a_section_in_the_buffer_is_used_instead_of_generated() -> None:
    rig = Rig()
    rig.buffer.offer(0, play_section(FORM[0], 1234))
    rig.play()
    from_buffer = [
        event for event in rig.of_kind("section_generated") if event.detail["source"] == "buffer"
    ]
    assert [event.detail["seed"] for event in from_buffer] == [1234]


def musical_detail(event: Event) -> dict[str, object]:
    """Everything but `ms`, which is a measurement rather than a musical decision.

    `section_written` carries how long the write took in wall time — the number
    `phase-2-findings.md` is written from. It is the one field that is allowed to differ
    between two identical runs, and excluding it here is what keeps the determinism claim
    about the music rather than about the machine.
    """
    return {key: value for key, value in event.detail.items() if key != "ms"}


def test_the_fallback_is_deterministic_from_the_schedulers_seed() -> None:
    first, second = Rig(), Rig()
    first.play()
    second.play()
    assert [musical_detail(event) for event in first.log] == [
        musical_detail(event) for event in second.log
    ]


# ------------------------------------------------------------ a write that does not land


def test_a_write_that_fails_does_not_fire_and_the_clip_simply_repeats() -> None:
    """A repeat is not a glitch; a gap would be. Nothing retries (P7)."""
    rig = Rig()
    rig.scheduler.begin(FORM)
    rig.daw._fail_with = DawTimeoutError("Live went quiet")
    rig.daw._fail_after = 0

    for beat in range(40):
        rig.daw.push_beat(beat)
        rig.scheduler.tick()

    assert rig.scheduler.index == 0
    assert any(event.detail.get("reason") == "not_written" for event in rig.of_kind("fallback"))
    assert len(rig.of_kind("scene_fired")) == 1


# ------------------------------------------------------------------------------- rewinds


def test_a_rewind_throws_away_what_was_queued_for_bars_that_are_not_coming() -> None:
    rig = Rig()
    rig.scheduler.begin(FORM)
    for beat in range(8):
        rig.daw.push_beat(beat)
        rig.scheduler.tick()
    rig.buffer.offer(rig.buffer.floor, play_section(FORM[0], 99))

    rig.daw.push_beat(0)
    rig.scheduler.tick()

    assert rig.buffer.pending() == ()
    assert any(event.detail.get("reason") == "rewind" for event in rig.of_kind("beat_lost"))


def test_the_run_keeps_going_after_a_rewind() -> None:
    rig = Rig()
    rig.scheduler.begin(FORM)
    for beat in range(6):
        rig.daw.push_beat(beat)
        rig.scheduler.tick()
    rig.daw.push_beat(0)
    rig.scheduler.tick()

    beat = 1
    while not rig.scheduler.finished and beat < 500:
        rig.daw.push_beat(beat)
        rig.scheduler.tick()
        beat += 1

    assert rig.scheduler.finished


# ------------------------------------------------------------------------ before the beat


def test_nothing_is_decided_before_live_reports_a_beat() -> None:
    """The scene was fired and the transport is still catching up to the quantum."""
    rig = Rig()
    rig.scheduler.begin(FORM)
    written_before = len(rig.of_kind("section_written"))
    rig.scheduler.tick()
    assert len(rig.of_kind("section_written")) == written_before


def test_a_section_that_never_writes_stops_the_run_instead_of_looping_forever() -> None:
    """A repeat is a degradation; an unbounded number of them is a hang.

    The first live run of `jam.py` looped one verse for four minutes because every write
    was refused and the boundary moved with it. The command never returned, which is not
    what "the music degrades, it never stops" is supposed to mean.
    """
    rig = Rig()
    rig.scheduler.begin(FORM)
    rig.daw._fail_with = DawTimeoutError("Live stopped taking writes")
    rig.daw._fail_after = 0

    for beat in range(400):
        rig.daw.push_beat(beat)
        rig.scheduler.tick()
        if rig.scheduler.finished:
            break

    assert rig.scheduler.finished
    assert any(
        event.detail.get("reason") == "repeated_too_long" for event in rig.of_kind("fallback")
    )
