"""Clip-ahead, double scene buffering, and the rules that must be impossible to break.

Everything here is driven by `FakeDawAdapter.push_beat` and `Scheduler.tick`. Nothing
sleeps and nothing opens a socket: musical time is a function call, so three minutes of
music costs milliseconds and the result is the same on every machine.

The assertions that carry the phase are the negative ones — no write ever landed in the
scene that was playing, and no fire happened with less than a bar of slack. Both are read
out of the event log rather than out of the scheduler's own opinion of itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pytest

from garagem.daw import ClipAddress, DawTimeoutError, FakeDawAdapter, MidiNote
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


# ------------------------------------------------------------------------ jumps (Stage 3)


CHORUS_SCENE = 2
JUMPING = {"chorus": CHORUS_SCENE}


class WatchedDaw(FakeDawAdapter):
    """A fake that remembers, for every write, which scene the scheduler said was playing."""

    def __init__(self) -> None:
        super().__init__(scenes=4)
        self.scheduler: Scheduler | None = None
        self.writes: list[tuple[int, int]] = []
        self.during_write: list[Callable[[], None]] = []

    def write_notes(self, at: ClipAddress, notes: Iterable[MidiNote]) -> None:
        playing = self.scheduler.playing_scene if self.scheduler is not None else -1
        self.writes.append((at.scene, playing))
        super().write_notes(at, notes)
        while self.during_write:
            self.during_write.pop(0)()


class JumpRig:
    """FORM with a chorus candidate and a cue queue, driven a beat at a time."""

    def __init__(self, *, candidates: dict[str, int] | None = None) -> None:
        self.daw = WatchedDaw()
        self.clock = BarClock(self.daw)
        self.clock.start()
        self.buffer = ScoreBuffer()
        self.log = EventLog(None)
        self.queue = CueQueue(stamp=lambda: self.clock.beat)
        self.scheduler = Scheduler(
            self.daw,
            self.clock,
            self.buffer,
            TRACKS,
            self.log,
            seed=7,
            cues=self.queue,
            candidates=JUMPING if candidates is None else candidates,
        )
        self.daw.scheduler = self.scheduler
        self.beat = 0

    def play(
        self,
        strikes: dict[int, CueKind] | None = None,
        after_tick: dict[int, Callable[[JumpRig], None]] | None = None,
        limit: int = 4000,
    ) -> JumpRig:
        strikes = strikes or {}
        after_tick = after_tick or {}
        self.scheduler.begin(FORM)
        while not self.scheduler.finished and self.beat < limit:
            self.daw.push_beat(self.beat)
            if self.beat in strikes:
                self.queue.offer(Cue(kind=strikes[self.beat]))
            self.scheduler.tick()
            if self.beat in after_tick:
                after_tick[self.beat](self)
            self.beat += 1
        return self

    def of_kind(self, kind: str) -> tuple[Event, ...]:
        return self.log.of_kind(kind)


def test_the_chorus_candidate_is_written_before_the_downbeat() -> None:
    rig = JumpRig()
    rig.scheduler.begin(FORM)
    kinds = [event.kind for event in rig.log]
    assert kinds.index("candidate_written") < kinds.index("scene_fired")
    assert rig.daw.has_clip(ClipAddress(track=TRACKS[Instrument.DRUMS], scene=CHORUS_SCENE))


def test_a_chorus_cue_is_fired_for_the_very_next_bar() -> None:
    """The criterion ADR-021 added: `fired_bar - cue_bar = 1`."""
    rig = JumpRig().play({13: CueKind.CHORUS_NOW})
    (applied,) = rig.of_kind("cue_applied")
    assert applied.detail["cue_bar"] == 3
    assert applied.detail["fired_bar"] == 4
    assert CHORUS_SCENE in rig.daw.fired


def test_after_a_jump_the_candidate_plays_and_the_song_is_re_planned_from_it() -> None:
    rig = JumpRig().play({13: CueKind.CHORUS_NOW})
    (applied,) = rig.of_kind("cue_applied")
    target = int(str(applied.detail["section"]))
    assert rig.scheduler.sections[target].name == "chorus"
    assert rig.scheduler.sections[-1].name == "outro"
    (replanned,) = rig.of_kind("form_replanned")
    assert replanned.detail["from_section"] == target
    assert rig.scheduler.finished


def test_no_write_ever_lands_in_the_scene_that_is_playing_even_across_jumps() -> None:
    rig = JumpRig().play({13: CueKind.CHORUS_NOW, 45: CueKind.CHORUS_NOW})
    candidate_writes = len(Instrument)
    assert len(rig.of_kind("cue_applied")) == 2
    for scene, playing in rig.daw.writes[candidate_writes + len(Instrument) :]:
        assert scene != playing
        assert scene != CHORUS_SCENE


def test_a_jump_in_the_bar_the_next_section_was_fired_replaces_that_section() -> None:
    """Live's last trigger wins, and ADR-022 says the person's is the one that should."""
    plain = Rig()
    plain.play()
    fired_at = next(e.at_beats for e in plain.of_kind("scene_fired") if e.detail["section"] == 2)
    cue_beat = int(fired_at) + 1
    rig = JumpRig().play({cue_beat: CueKind.CHORUS_NOW})
    (applied,) = rig.of_kind("cue_applied")
    assert applied.detail["cue_bar"] == int(fired_at // 4)
    boundary_beat = (int(str(applied.detail["fired_bar"]))) * 4
    rig_after = JumpRig().play(
        {cue_beat: CueKind.CHORUS_NOW},
        after_tick={boundary_beat: lambda r: setattr(r, "seen", r.scheduler.playing_scene)},
    )
    assert rig_after.seen == CHORUS_SCENE  # type: ignore[attr-defined]


def test_a_second_jump_while_the_chorus_plays_starts_it_again() -> None:
    rig = JumpRig().play({13: CueKind.CHORUS_NOW, 21: CueKind.CHORUS_NOW})
    applied = rig.of_kind("cue_applied")
    assert [event.detail["fired_bar"] for event in applied] == [4, 6]
    assert rig.daw.fired.count(CHORUS_SCENE) == 2
    assert rig.scheduler.finished


def test_a_jump_before_the_first_beat_is_declined() -> None:
    rig = JumpRig()
    rig.queue.offer(Cue(kind=CueKind.CHORUS_NOW))
    rig.play()
    (declined,) = rig.of_kind("cue_declined")
    assert declined.detail["reason"] == "before_the_downbeat"
    assert rig.of_kind("cue_applied") == ()


def test_without_a_candidate_a_jump_is_declined_and_the_song_is_unchanged() -> None:
    rig = JumpRig(candidates={}).play({13: CueKind.CHORUS_NOW})
    (declined,) = rig.of_kind("cue_declined")
    assert declined.detail["reason"] == "no_candidate"
    assert rig.scheduler.sections == FORM


def test_a_score_generated_for_a_briefing_the_jump_replaced_never_plays() -> None:
    def offer_stale(rig: JumpRig) -> None:
        target = int(str(rig.of_kind("cue_applied")[0].detail["section"]))
        rig.buffer.offer(target + 1, play_section(FORM[3], 1234))

    rig = JumpRig().play({13: CueKind.CHORUS_NOW}, after_tick={13: offer_stale})
    stale = [event for event in rig.of_kind("fallback") if event.detail.get("reason") == "stale"]
    assert stale
    assert 1234 not in [event.detail["seed"] for event in rig.of_kind("section_written")]


def test_a_performance_with_jumps_is_replayed_byte_for_byte_from_its_seed_and_cues() -> None:
    strikes = {13: CueKind.CHORUS_NOW, 45: CueKind.CHORUS_NOW}
    first, second = JumpRig().play(strikes), JumpRig().play(strikes)
    assert [(e.kind, musical_detail(e)) for e in first.log] == [
        (e.kind, musical_detail(e)) for e in second.log
    ]


def test_the_chorus_a_jump_lands_on_is_measured_like_any_section() -> None:
    rig = JumpRig().play({13: CueKind.CHORUS_NOW})
    target = rig.of_kind("cue_applied")[0].detail["section"]
    assert target in [event.detail["section"] for event in rig.of_kind("section_measured")]


def test_a_cue_that_arrives_during_a_section_write_is_fired_before_the_write_ends() -> None:
    """A write is up to two seconds; the cue waits one track, not four."""
    rig = JumpRig()

    def strike_during_the_next_write(r: JumpRig) -> None:
        r.daw.during_write.append(lambda: r.queue.offer(Cue(kind=CueKind.CHORUS_NOW)))
        r.daw.calls.clear()

    rig.play(after_tick={8: strike_during_the_next_write})
    (applied,) = rig.of_kind("cue_applied")
    assert int(str(applied.detail["fired_bar"])) - int(str(applied.detail["cue_bar"])) == 1
    calls = rig.daw.calls
    first_write = calls.index("write_notes")
    assert "fire_scene" in calls[first_write : first_write + 8]


def test_run_reads_a_cue_inside_the_bar_it_arrives_in() -> None:
    """Stage 2 read cues a bar late; `run` now wakes in slices (`phase-4-findings.md` §8)."""
    import threading
    import time

    daw = FakeDawAdapter(scenes=4)
    clock = BarClock(daw)
    clock.start()
    log = EventLog(None)
    queue = CueQueue(stamp=lambda: clock.beat)
    scheduler = Scheduler(
        daw,
        clock,
        ScoreBuffer(),
        TRACKS,
        log,
        seed=7,
        cues=queue,
        candidates=JUMPING,
        wake_s=0.002,
        bar_timeout_s=2.0,
    )

    def a_band_playing() -> None:
        time.sleep(0.05)
        for beat in range(80):
            daw.push_beat(beat)
            if beat == 13:
                time.sleep(0.01)
                queue.offer(Cue(kind=CueKind.CHORUS_NOW))
            time.sleep(0.03)
            if scheduler.finished:
                return

    pusher = threading.Thread(target=a_band_playing)
    pusher.start()
    scheduler.run(FORM)
    pusher.join()
    (applied,) = log.of_kind("cue_applied")
    assert int(str(applied.detail["fired_bar"])) - int(str(applied.detail["cue_bar"])) == 1


# --------------------------------------------------------------------- bar cues (Stage 4)


VARIANT_SCENES = {"stop": {0: 4, 1: 5}, "fill": {0: 6, 1: 7}}
# Eight-bar sections, as a real song has: intro bars 0-3, verse 4-11, chorus 12-19, outro
# 20-23. The verse plays from scene 1; its stop lives in scene 5 and its fill in scene 7.
LONG = (a_section("intro", 4), a_section("verse", 8), a_section("chorus", 8), a_section("outro", 4))
VERSE_STOP, VERSE_FILL, VERSE_MAIN = 5, 7, 1


class BarRig:
    """LONG with variant scenes, a chorus candidate and a cue queue, a beat at a time."""

    def __init__(self) -> None:
        self.daw = FakeDawAdapter(scenes=8)
        self.clock = BarClock(self.daw)
        self.clock.start()
        self.log = EventLog(None)
        self.queue = CueQueue(stamp=lambda: self.clock.beat)
        self.scheduler = Scheduler(
            self.daw,
            self.clock,
            ScoreBuffer(),
            TRACKS,
            self.log,
            seed=7,
            cues=self.queue,
            candidates={"chorus": 2},
            variants=VARIANT_SCENES,
        )
        self.sounding_at_write: list[tuple[int, int | None]] = []
        original = self.daw.write_notes

        def watched(at: ClipAddress, notes: Iterable[MidiNote]) -> None:
            self.sounding_at_write.append((at.scene, self.scheduler._bar_cues.sounding_scene()))
            original(at, notes)

        self.daw.write_notes = watched  # type: ignore[method-assign]
        self.calls_by_bar: dict[int, list[str]] = {}

    def play(self, strikes: dict[int, CueKind] | None = None) -> BarRig:
        strikes = strikes or {}
        self.scheduler.begin(LONG)
        beat = 0
        while not self.scheduler.finished and beat < 2000:
            self.daw.push_beat(beat)
            if beat in strikes:
                self.queue.offer(Cue(kind=strikes[beat]))
            before = len(self.daw.calls)
            self.scheduler.tick()
            self.calls_by_bar.setdefault(beat // 4, []).extend(self.daw.calls[before:])
            beat += 1
        return self

    def of_kind(self, kind: str) -> tuple[Event, ...]:
        return self.log.of_kind(kind)


def at(instrument: Instrument, scene: int) -> ClipAddress:
    return ClipAddress(track=TRACKS[instrument], scene=scene)


def test_variants_are_written_ahead_fill_drums_first_each_with_legato_on() -> None:
    rig = BarRig().play()
    verse = [e.detail for e in rig.of_kind("variant_written") if e.detail["section"] == 1]
    assert [(d["variant"], d["instrument"]) for d in verse] == [
        ("fill", "DRM"),
        ("stop", "DRM"),
        ("stop", "BAS"),
        ("stop", "GTR"),
        ("stop", "KEY"),
    ]
    assert rig.daw.clip_legato(at(Instrument.DRUMS, VERSE_FILL))
    assert all(rig.daw.clip_legato(at(instrument, VERSE_STOP)) for instrument in Instrument)


def test_a_variant_is_never_written_in_a_tick_that_wrote_a_section() -> None:
    rig = BarRig().play()
    section_beats = {e.at_beats for e in rig.of_kind("section_written")}
    assert not section_beats & {e.at_beats for e in rig.of_kind("variant_written")}


def test_a_stop_fires_every_track_into_the_stop_variant_for_the_next_bar() -> None:
    rig = BarRig().play({25: CueKind.STOP})
    (applied,) = rig.of_kind("cue_applied")
    assert (applied.detail["cue_bar"], applied.detail["fired_bar"]) == (6, 7)
    assert applied.detail["scene"] == VERSE_STOP
    assert rig.daw.fired_clips[:4] == [at(instrument, VERSE_STOP) for instrument in Instrument]


def test_a_bar_after_the_stop_every_track_goes_back_to_the_groove_with_legato() -> None:
    rig = BarRig().play({25: CueKind.STOP})
    (returned,) = rig.of_kind("variant_returned")
    assert returned.detail["via"] == "legato"
    assert returned.detail["fired_bar"] == 8
    assert rig.daw.fired_clips[4:8] == [at(instrument, VERSE_MAIN) for instrument in Instrument]
    assert rig.calls_by_bar[7].count("set_clip_legato") == 4
    # Once it has landed, the main clips lose legato again — or the verse's scene would start
    # its next section mid-way.
    assert rig.calls_by_bar[8].count("set_clip_legato") == 4
    assert not any(rig.daw.clip_legato(at(instrument, VERSE_MAIN)) for instrument in Instrument)


def test_a_fill_fires_and_returns_only_the_drums() -> None:
    rig = BarRig().play({33: CueKind.FILL})
    (applied,) = rig.of_kind("cue_applied")
    assert applied.detail["tracks"] == "DRM"
    assert rig.daw.fired_clips == [
        at(Instrument.DRUMS, VERSE_FILL),
        at(Instrument.DRUMS, VERSE_MAIN),
    ]


def test_drums_and_bass_stops_guitar_and_keys_until_the_next_section() -> None:
    rig = BarRig().play({25: CueKind.DRUMS_AND_BASS})
    (applied,) = rig.of_kind("cue_applied")
    assert (applied.detail["fired_bar"], applied.detail["tracks"]) == (7, "GTR,KEY")
    assert rig.daw.stopped_tracks == [TRACKS[Instrument.GUITAR], TRACKS[Instrument.KEYS]]
    assert rig.daw.fired_clips == []
    assert [e.detail["name"] for e in rig.of_kind("scene_fired")][2] == "chorus"


def test_a_stop_while_guitar_and_keys_are_out_leaves_them_out() -> None:
    rig = BarRig().play({21: CueKind.DRUMS_AND_BASS, 25: CueKind.STOP})
    stop = next(e for e in rig.of_kind("cue_applied") if e.detail["cue"] == "stop")
    assert stop.detail["tracks"] == "DRM,BAS"
    assert all(address.track not in (2, 3) for address in rig.daw.fired_clips)


def test_a_bar_cue_in_the_bar_the_next_section_was_fired_is_declined() -> None:
    rig = BarRig().play({44: CueKind.STOP})
    (declined,) = rig.of_kind("cue_declined")
    assert declined.detail["reason"] == "section_change"
    assert rig.daw.fired_clips == []


def test_a_variant_heard_in_the_last_bar_is_returned_by_the_section_change_not_a_fire() -> None:
    """Live's last trigger wins: a return fired beside the chorus would take its tracks."""
    rig = BarRig().play({43: CueKind.FILL})
    (returned,) = rig.of_kind("variant_returned")
    assert returned.detail["via"] == "section_change"
    assert rig.daw.fired_clips == [at(Instrument.DRUMS, VERSE_FILL)]


def test_a_bar_cue_before_its_variant_is_written_is_declined_as_unavailable() -> None:
    rig = BarRig().play({0: CueKind.STOP})
    (declined,) = rig.of_kind("cue_declined")
    assert declined.detail["reason"] == "unavailable"


def test_a_bar_cue_while_the_chorus_candidate_plays_is_declined() -> None:
    rig = BarRig().play({25: CueKind.CHORUS_NOW, 33: CueKind.STOP})
    (declined,) = rig.of_kind("cue_declined")
    assert declined.detail["reason"] == "no_variant"


def test_a_jump_right_after_a_stop_cancels_its_return() -> None:
    rig = BarRig().play({25: CueKind.STOP, 26: CueKind.CHORUS_NOW})
    assert rig.of_kind("variant_returned") == ()
    assert at(Instrument.DRUMS, VERSE_MAIN) not in rig.daw.fired_clips


def test_no_write_ever_lands_in_the_scene_a_bar_cue_is_sounding_from() -> None:
    rig = BarRig().play({25: CueKind.STOP, 33: CueKind.FILL, 41: CueKind.STOP})
    assert all(scene != sounding for scene, sounding in rig.sounding_at_write)


def test_a_performance_with_bar_cues_replays_byte_for_byte() -> None:
    strikes = {21: CueKind.DRUMS_AND_BASS, 25: CueKind.STOP, 33: CueKind.FILL}
    first, second = BarRig().play(strikes), BarRig().play(strikes)
    assert [(e.kind, musical_detail(e)) for e in first.log] == [
        (e.kind, musical_detail(e)) for e in second.log
    ]


def test_the_fill_a_pad_fires_is_the_run_down_the_toms_the_audition_chose() -> None:
    """phase-4-findings.md §10: ranked first and second of six, blind."""
    from garagem.theory.percussion import TOMS

    rig = BarRig().play()
    fill = rig.daw.read_notes(at(Instrument.DRUMS, VERSE_FILL))
    assert set(TOMS) <= {note.pitch for note in fill}
