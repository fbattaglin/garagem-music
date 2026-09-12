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

from garagem.daw import ClipAddress, DawTimeoutError, FakeDawAdapter
from garagem.domain import Cue, CueKind, Feel, Instrument, Macro, MacroKind, Section, SectionScore
from garagem.engines import Ending, coherence_of, compose, play_section
from garagem.obs import Event, EventLog
from garagem.theory import parse_chart
from garagem.theory.coherence import Coherence
from garagem.transport import BarClock, CueQueue, Scheduler, ScoreBuffer, render_score

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


# ---------------------------------------------------------------------------- endings


ENDINGS = (Ending.FILL, Ending.BUILD, Ending.STOP, Ending.FINAL)


class EndingRig(Rig):
    def play_with_endings(self, endings: tuple[Ending, ...] = ENDINGS) -> None:
        self.scheduler.begin(FORM, endings=endings)
        while not self.scheduler.finished and self.beat < 2000:
            self.daw.push_beat(self.beat)
            self.scheduler.tick()
            self.beat += 1


def test_without_endings_every_section_is_written_as_generated() -> None:
    """Phase 3's scheduler, byte for byte: the log says nothing about endings at all."""
    rig = Rig()
    rig.play()
    assert all("ending" not in event.detail for event in rig.of_kind("section_written"))


def test_every_written_section_names_the_ending_it_plays() -> None:
    rig = EndingRig()
    rig.play_with_endings()
    written = {
        event.detail["section"]: event.detail["ending"] for event in rig.of_kind("section_written")
    }
    assert written == {0: "fill", 1: "build", 2: "stop", 3: "final"}


def test_the_last_section_is_written_with_its_final_chord() -> None:
    rig = EndingRig()
    rig.play_with_endings()
    outro = FORM[-1]
    expected = compose(play_section(outro, 7 + 3), Ending.FINAL)
    written = rig.daw.read_notes(ClipAddress(track=TRACKS[Instrument.KEYS], scene=1))
    assert written == render_score(expected)[Instrument.KEYS]


def test_a_section_from_the_buffer_gets_the_same_ending_as_the_floor_would() -> None:
    """Both sources pass through one place, so the form does not depend on who wrote it."""
    rig = EndingRig()
    rig.buffer.offer(1, play_section(FORM[1], 1234))
    rig.play_with_endings()
    expected = compose(play_section(FORM[1], 1234), Ending.BUILD, into=FORM[2])
    # Section 1 went to scene 1 and was later overwritten by section 3, so read the log.
    written = [event for event in rig.of_kind("section_written") if event.detail["section"] == 1]
    assert written[0].detail["ending"] == "build"
    assert written[0].detail["notes"] == sum(len(part.notes) for part in expected.parts)


def test_an_ending_that_would_break_a_rule_is_declined_and_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P4 over our own composition: the section plays as generated, and the log says why."""
    import garagem.transport.scheduler as scheduler

    def breaks_the_range(score: SectionScore, ending: Ending, *, into: Section | None) -> object:
        if ending is Ending.FILL:
            return score
        bass = score.part(Instrument.BASS)
        low = bass.notes[0].model_copy(update={"pitch": 1})
        parts = tuple(
            part.model_copy(update={"notes": (low, *part.notes[1:])})
            if part.instrument is Instrument.BASS
            else part
            for part in score.parts
        )
        return score.model_copy(update={"parts": parts})

    monkeypatch.setattr(scheduler, "compose", breaks_the_range)
    rig = EndingRig()
    rig.play_with_endings()
    declined = rig.of_kind("transition_declined")
    assert [event.detail["ending"] for event in declined] == ["build", "stop", "final"]
    assert all("range" in str(event.detail["rules"]).split(",") for event in declined)
    written = [event.detail["ending"] for event in rig.of_kind("section_written")]
    assert written == ["fill", "fill", "fill", "fill"]


def test_endings_must_cover_the_whole_form() -> None:
    rig = Rig()
    with pytest.raises(ValueError, match="one ending per section"):
        rig.scheduler.begin(FORM, endings=(Ending.FILL,))


def test_a_run_with_endings_is_deterministic() -> None:
    first, second = EndingRig(), EndingRig()
    first.play_with_endings()
    second.play_with_endings()
    assert [musical_detail(event) for event in first.log] == [
        musical_detail(event) for event in second.log
    ]


# ----------------------------------------------------------------------------- metrics


METRICS = frozenset(Coherence.model_fields)


def test_every_written_section_is_measured_exactly_once() -> None:
    """Phase 4's amended criterion: every section carries its metrics in the log."""
    rig = EndingRig()
    rig.play_with_endings()
    written = [event.detail["section"] for event in rig.of_kind("section_written")]
    measured = [event.detail["section"] for event in rig.of_kind("section_measured")]
    assert measured == written == [0, 1, 2, 3]


def test_a_measurement_carries_every_metric_as_a_fraction_and_the_seed() -> None:
    rig = Rig()
    rig.play()
    for event in rig.of_kind("section_measured"):
        assert set(event.detail) >= METRICS
        assert all(0.0 <= float(str(event.detail[name])) <= 1.0 for name in METRICS)
        assert "seed" in event.detail


def test_what_is_measured_is_what_was_written_ending_and_all() -> None:
    """Not the section before its ending: the metrics describe what actually played."""
    rig = EndingRig()
    rig.play_with_endings()
    written = compose(play_section(FORM[-1], 7 + 3), Ending.FINAL)
    expected = coherence_of(written)
    last = rig.of_kind("section_measured")[-1]
    for name in METRICS:
        assert last.detail[name] == round(getattr(expected, name), 3)


# -------------------------------------------------------------------------------- cues


def a_performance_with_cues(strikes: dict[int, Cue | Macro]) -> tuple[Rig, CueQueue]:
    """Play FORM, offering each control at the beat it is keyed by, as a person would."""
    rig = Rig()
    queue = CueQueue(stamp=lambda: rig.clock.beat)
    rig.scheduler._cues = queue
    rig.scheduler.begin(FORM)
    while not rig.scheduler.finished and rig.beat < 2000:
        rig.daw.push_beat(rig.beat)
        if rig.beat in strikes:
            queue.offer(strikes[rig.beat])
        rig.scheduler.tick()
        rig.beat += 1
    return rig, queue


def test_a_cue_is_logged_with_the_beat_and_bar_it_arrived_in() -> None:
    rig, _ = a_performance_with_cues({10: Cue(kind=CueKind.STOP)})
    (received,) = rig.of_kind("cue_received")
    assert received.at_beats == 10.0
    assert received.detail["bar"] == 2
    assert received.detail["cue"] == "stop"
    assert received.detail["family"] == "bar"


def test_a_knob_is_logged_with_its_value() -> None:
    rig, _ = a_performance_with_cues({5: Macro(kind=MacroKind.TENSION, value=0.75)})
    (received,) = rig.of_kind("cue_received")
    assert received.detail["macro"] == "tension"
    assert received.detail["value"] == 0.75


def test_in_stage_2_a_cue_changes_nothing_that_is_played() -> None:
    """The controller is proved against a jam before it may move a note (ADR-022)."""
    cued, _ = a_performance_with_cues(
        {6: Cue(kind=CueKind.CHORUS_NOW), 20: Cue(kind=CueKind.STOP), 30: Cue(kind=CueKind.END)}
    )
    plain = Rig()
    plain.play()
    kinds = ("section_written", "scene_fired")
    assert [(event.kind, musical_detail(event)) for event in cued.log if event.kind in kinds] == [
        (event.kind, musical_detail(event)) for event in plain.log if event.kind in kinds
    ]


def test_without_a_queue_nothing_about_cues_is_logged() -> None:
    rig = Rig()
    rig.play()
    assert rig.of_kind("cue_received") == ()


# ---------------------------------------------------------------------- a stopped transport


def test_a_transport_stopped_from_outside_is_logged_and_the_run_is_not_finished() -> None:
    """From inside Python a stop is silence; the log is where it becomes a fact."""
    daw = FakeDawAdapter(scenes=4)
    clock = BarClock(daw)
    clock.start()
    log = EventLog(None)
    scheduler = Scheduler(daw, clock, ScoreBuffer(), TRACKS, log, seed=7, bar_timeout_s=0.05)
    scheduler.run(FORM)
    assert not scheduler.finished
    assert scheduler.stopped_because == "transport_stopped"
    (stopped,) = log.of_kind("beat_lost")
    assert stopped.detail["reason"] == "transport_stopped"
    assert stopped.detail["section"] == 0


def test_a_song_position_that_keeps_going_back_is_told_apart_from_a_stop() -> None:
    """What Live's arrangement loop did at the first MiniLab gate (`phase-4-findings.md` §8).

    Beats keep arriving, so nothing is silent — but the position jumps back before the bar
    the scheduler waits for, and the run can never reach it.
    """
    import threading
    import time

    daw = FakeDawAdapter(scenes=4)
    clock = BarClock(daw)
    clock.start()
    log = EventLog(None)
    scheduler = Scheduler(daw, clock, ScoreBuffer(), TRACKS, log, seed=7, bar_timeout_s=0.3)

    def a_looping_song() -> None:
        time.sleep(0.05)
        for beat in range(0, 12):
            daw.push_beat(beat)
            time.sleep(0.002)
        for beat in (4, 5, 6, 7, 8, 9, 10, 11, 4, 5):
            daw.push_beat(beat)
            time.sleep(0.002)

    pusher = threading.Thread(target=a_looping_song)
    pusher.start()
    scheduler.run(FORM)
    pusher.join()
    assert not scheduler.finished
    assert scheduler.stopped_because == "position_went_back"
    assert log.of_kind("beat_lost")[-1].detail["reason"] == "position_went_back"
