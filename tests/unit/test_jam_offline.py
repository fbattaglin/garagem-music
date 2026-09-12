"""The whole Phase 2 exit criterion, in simulated musical time, with Ableton closed.

Three minutes of autonomous arrangement, section changes, zero dropouts, zero glitches,
zero network — asserted against the event log rather than against the audio, because
audio is the one thing no test can check and everything else is the one thing no ear can.

**If this does not pass, do not open Ableton.** It exists to prove the logic first. That
rule is why Phase 1 closed on its first live attempt with no adapter changes at all
(`phase-1-findings.md` §12), and it costs a fraction of a second to obey.
"""

from __future__ import annotations

from collections.abc import Iterable

from garagem.daw import ClipAddress, FakeDawAdapter, MidiNote
from garagem.domain import Feel, Instrument
from garagem.engines import SongBrief, arrange, compose, endings_for, play_section, with_climax
from garagem.obs import EventLog
from garagem.theory import validate
from garagem.transport import BarClock, Scheduler, ScoreBuffer

THREE_MINUTES = 180.0
BPM = 132.0
SEED = 7

TRACKS = {
    Instrument.DRUMS: 0,
    Instrument.BASS: 1,
    Instrument.GUITAR: 2,
    Instrument.KEYS: 3,
}

BRIEF = SongBrief(key=4, scale="minor", bpm=BPM, feel=Feel.STRAIGHT8, minimum_seconds=THREE_MINUTES)


class RecordingDaw(FakeDawAdapter):
    """A fake that also remembers *where* every write went, not only that one happened.

    `FakeDawAdapter.calls` records method names, which is enough for Phase 1. "No write
    landed in a playing clip" is a claim about addresses, so the address is what this
    records — and it records it independently of the event log, so the two can disagree.
    """

    def __init__(self) -> None:
        super().__init__(scenes=4)
        self.writes: list[tuple[int, int]] = []

    def write_notes(self, at: ClipAddress, notes: Iterable[MidiNote]) -> None:
        self.writes.append((at.track, at.scene))
        super().write_notes(at, notes)


def a_jam(
    seed: int = SEED, *, arranged: bool = False
) -> tuple[RecordingDaw, Scheduler, EventLog, int]:
    """One whole performance. Returns the rig and how many beats it took.

    `arranged` is Phase 4's: the last chorus lifted and every section handing over to the
    next. Without it this is the performance Phase 2 closed on.
    """
    daw = RecordingDaw()
    clock = BarClock(daw)
    clock.start()
    log = EventLog(None)
    scheduler = Scheduler(daw, clock, ScoreBuffer(), TRACKS, log, seed=seed)

    form = arrange(BRIEF, seed)
    if arranged:
        form = with_climax(form)
        scheduler.begin(form, endings=endings_for(form))
    else:
        scheduler.begin(form)
    beat = 0
    while not scheduler.finished and beat < 20_000:
        daw.push_beat(beat)
        scheduler.tick()
        beat += 1
    clock.stop()
    return daw, scheduler, log, beat


def test_the_run_covers_three_minutes_of_music() -> None:
    _, scheduler, _, beats = a_jam()
    assert scheduler.finished
    assert beats * 60.0 / BPM >= THREE_MINUTES


def test_there_are_at_least_four_section_changes() -> None:
    _, _, log, _ = a_jam()
    assert len(log.of_kind("scene_fired")) - 1 >= 4


def test_every_section_of_the_form_was_fired_exactly_once() -> None:
    _, _, log, _ = a_jam()
    fired = [event.detail["section"] for event in log.of_kind("scene_fired")]
    assert fired == list(range(len(arrange(BRIEF, SEED))))


def test_no_write_ever_targeted_the_scene_that_was_playing() -> None:
    """Invariant 6, checked twice over: from the log, and from the adapter's addresses.

    The log says which scene each section went into; the adapter says which addresses
    were actually written. Two independent records, so a scheduler that logged one thing
    and did another would be caught rather than believed.
    """
    daw, _, log, _ = a_jam()

    assert {scene for _, scene in daw.writes} == {0, 1}

    playing: object = None
    for event in log:
        if event.kind == "section_written" and playing is not None:
            assert event.detail["scene"] != playing
        elif event.kind == "scene_fired":
            playing = event.detail["scene"]

    # And the addresses agree: writes and fires strictly alternate between the two
    # scenes, which is what "double buffering" means when it is working.
    written_scenes = [scene for _, scene in daw.writes]
    fired_scenes = [event.detail["scene"] for event in log.of_kind("scene_fired")]
    assert written_scenes[:: len(TRACKS)] == fired_scenes


def test_every_track_of_every_section_was_written() -> None:
    daw, _, log, _ = a_jam()
    sections = len(log.of_kind("section_written"))
    assert len(daw.writes) == sections * len(TRACKS)
    assert {track for track, _ in daw.writes} == set(TRACKS.values())


def test_every_transition_had_at_least_a_bar_of_slack() -> None:
    """Zero glitches, mechanically: nothing was fired against the boundary."""
    _, _, log, _ = a_jam()
    transitions = [event for event in log.of_kind("scene_fired") if not event.detail["first"]]
    assert transitions
    assert all(int(str(event.detail["slack_bars"])) >= 1 for event in transitions)


def test_the_music_never_stopped() -> None:
    """A fire for every section means the clip changed rather than ran out."""
    _, _, log, _ = a_jam()
    fired = len(log.of_kind("scene_fired"))
    written = len(log.of_kind("section_written"))
    assert fired == written


def test_nothing_was_lost_and_nothing_rewound() -> None:
    _, _, log, _ = a_jam()
    assert log.of_kind("beat_lost") == ()


def musical(log: EventLog) -> list[tuple[str, float, dict[str, object]]]:
    """The log without `ms`: the decisions, not how long the machine took to make them."""
    return [
        (event.kind, event.at_beats, {k: v for k, v in event.detail.items() if k != "ms"})
        for event in log
    ]


def test_the_whole_run_is_byte_identical_for_the_same_seed() -> None:
    """Invariant 7, at the scale of a performance rather than a section."""
    assert musical(a_jam()[2]) == musical(a_jam()[2])


def test_a_different_seed_is_a_different_performance() -> None:
    assert musical(a_jam(7)[2]) != musical(a_jam(11)[2])


def test_every_section_the_band_played_validates() -> None:
    """The floor held for a whole song, not only for a section somebody picked."""
    form = arrange(BRIEF, SEED)
    assert all(
        validate(play_section(section, SEED + index)) == () for index, section in enumerate(form)
    )


def test_the_run_makes_no_network_call() -> None:
    """The `no_network` fuse is autouse, so this is free — asserted so the claim is visible.

    Phase 2's whole point is that the band plays without a network. A test that relied on
    a fixture nobody reads to prove it would be a claim, not evidence.
    """
    import socket

    assert socket.socket.connect.__name__ == "refuse"
    assert socket.socket.sendto.__name__ == "refuse_datagram"
    a_jam()


def test_the_log_replays_into_the_same_section_sequence() -> None:
    """P6: the session *is* the log. If it cannot be replayed, it is only a diary."""
    _, _, log, _ = a_jam()
    form = arrange(BRIEF, SEED)
    replayed = [str(event.detail["name"]) for event in log.of_kind("scene_fired")]
    assert replayed == [section.name for section in form]


# ------------------------------------------------------------------------------ Phase 4


def test_an_arranged_song_is_still_three_minutes_with_no_glitch() -> None:
    """Transitions change the notes, never the transport: same fires, same slack."""
    _, scheduler, log, _ = a_jam(arranged=True)
    assert scheduler.finished
    fired = log.of_kind("scene_fired")
    assert len(fired) == len(arrange(BRIEF, SEED))
    assert all(int(str(event.detail["slack_bars"])) >= 1 for event in fired[1:])
    assert log.of_kind("beat_lost") == ()


def test_every_section_of_an_arranged_song_hands_over_as_planned() -> None:
    """No ending was declined: the floor composes validly for a whole song."""
    _, _, log, _ = a_jam(arranged=True)
    form = with_climax(arrange(BRIEF, SEED))
    written = [str(event.detail["ending"]) for event in log.of_kind("section_written")]
    assert written == [str(ending) for ending in endings_for(form)]
    assert log.of_kind("transition_declined") == ()


def test_every_section_of_an_arranged_song_validates() -> None:
    form = with_climax(arrange(BRIEF, SEED))
    endings = endings_for(form)
    for index, (section, ending) in enumerate(zip(form, endings, strict=True)):
        into = form[index + 1] if index + 1 < len(form) else None
        assert validate(compose(play_section(section, SEED + index), ending, into=into)) == ()


def test_an_arranged_run_is_byte_identical_for_the_same_seed() -> None:
    assert musical(a_jam(arranged=True)[2]) == musical(a_jam(arranged=True)[2])


def test_the_arranged_song_is_audibly_not_the_plain_one() -> None:
    """Otherwise the listening would be comparing a performance with itself."""

    def notes(log: EventLog) -> list[object]:
        return [event.detail["notes"] for event in log.of_kind("section_written")]

    plain = notes(a_jam()[2])
    arranged = notes(a_jam(arranged=True)[2])
    assert plain != arranged


def test_every_section_of_a_whole_song_carries_its_metrics() -> None:
    """The metrics criterion over three minutes, arranged and plain alike."""
    for arranged in (False, True):
        _, _, log, _ = a_jam(arranged=arranged)
        written = [event.detail["section"] for event in log.of_kind("section_written")]
        measured = [event.detail["section"] for event in log.of_kind("section_measured")]
        assert measured == written
        assert len(set(measured)) == len(arrange(BRIEF, SEED))
