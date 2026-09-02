"""`FakeDawAdapter`: does the stand-in behave like Live where it matters?

The value of the fake is entirely in the places it refuses to be convenient. Each of
those is a real Live behaviour that would otherwise be discovered against a real Set,
at the point where the music is already wrong.
"""

from __future__ import annotations

import pytest

from garagem.daw import (
    ClipAddress,
    DawError,
    DawPort,
    DawTimeoutError,
    FakeDawAdapter,
    FakeOscTransport,
    MidiNote,
    Quantization,
    normalised,
)

AT = ClipAddress(track=3, scene=1)
CHORD = (
    MidiNote(pitch=64, start_beats=0.0, duration_beats=4.0),
    MidiNote(pitch=59, start_beats=0.0, duration_beats=4.0),
    MidiNote(pitch=55, start_beats=0.0, duration_beats=4.0),
)


# ------------------------------------------------------------------- the Set's shape


def test_the_fake_starts_as_the_template_set() -> None:
    daw = FakeDawAdapter()
    assert daw.track_names() == ("DRUMS", "BASS", "GTR", "KEYS")
    assert daw.device_names(0) == ("Drift",)
    assert daw.scene_count() == 2
    assert daw.accepts_midi(0) is True
    assert FakeDawAdapter(track_names=("A",), midi_tracks=(False,)).accepts_midi(0) is False


def test_renaming_a_track_is_visible_to_the_next_read() -> None:
    daw = FakeDawAdapter()
    daw.set_track_name(2, "GUITAR")
    assert daw.track_names()[2] == "GUITAR"


def test_a_tempo_change_is_visible_to_the_next_read() -> None:
    daw = FakeDawAdapter()
    daw.set_tempo(132.0)
    daw.set_quantization(Quantization.TWO_BARS)
    assert (daw.tempo(), daw.quantization()) == (132.0, Quantization.TWO_BARS)


# ------------------------------------------------------ Live behaviours worth copying


def test_creating_a_clip_where_one_exists_is_refused_as_live_refuses_it() -> None:
    daw = FakeDawAdapter()
    daw.create_clip(AT, 16.0)
    with pytest.raises(DawError, match="already holds a clip"):
        daw.create_clip(AT, 16.0)


def test_writing_the_same_notes_twice_replaces_rather_than_doubles_them() -> None:
    """The trap: `/live/clip/add/notes` appends. The adapter removes first."""
    daw = FakeDawAdapter()
    daw.create_clip(AT, 16.0)
    daw.write_notes(AT, CHORD)
    daw.write_notes(AT, CHORD)
    assert len(daw.read_notes(AT)) == len(CHORD)


def test_notes_come_back_normalised_not_in_the_order_they_were_written() -> None:
    daw = FakeDawAdapter()
    daw.create_clip(AT, 16.0)
    daw.write_notes(AT, CHORD)
    assert daw.read_notes(AT) == normalised(CHORD)


def test_deleting_a_clip_frees_the_slot() -> None:
    daw = FakeDawAdapter()
    daw.create_clip(AT, 16.0)
    daw.delete_clip(AT)
    assert not daw.has_clip(AT)
    daw.create_clip(AT, 8.0)
    assert daw.clip_length_beats(AT) == 8.0


def test_firing_a_scene_is_recorded_and_starts_the_transport() -> None:
    daw = FakeDawAdapter()
    daw.fire_scene(1)
    assert daw.fired == [1]
    assert daw.is_playing()


# --------------------------------------------------------------- the call transcript


def test_every_call_is_recorded_in_order() -> None:
    """What makes "the second run wrote nothing" a checkable statement."""
    daw = FakeDawAdapter()
    daw.tempo()
    daw.set_tempo(132.0)
    daw.track_names()
    assert daw.calls == ["tempo", "set_tempo", "track_names"]


def test_failure_can_be_injected_after_a_few_calls_succeed() -> None:
    daw = FakeDawAdapter(fail_with=DawTimeoutError("Live went away"), fail_after=2)
    daw.tempo()
    daw.track_names()
    with pytest.raises(DawTimeoutError, match="went away"):
        daw.scene_count()


# ------------------------------------------------------------------- the OSC seam


def test_a_silent_transport_times_out_without_waiting() -> None:
    """A handler returning None is Live saying nothing — the only failure it can express."""
    transport = FakeOscTransport(handler=lambda address, args: None)
    with pytest.raises(DawTimeoutError, match="Live said nothing"):
        transport.request("/live/test")
    assert transport.sent == [("/live/test", ())]


def test_the_fake_satisfies_the_port() -> None:
    daw: DawPort = FakeDawAdapter()
    assert isinstance(daw, DawPort)
    assert daw.name == "fake"


# ---------------------------------------------------------------------- pushing the beat


def test_the_fake_pushes_beats_synchronously() -> None:
    """Musical time, on demand: this is what lets a three-minute run be a unit test."""
    daw = FakeDawAdapter()
    beats: list[int] = []
    daw.listen_beats(beats.append)

    for beat in range(4):
        daw.push_beat(beat)

    assert beats == [0, 1, 2, 3]
    assert daw.song_position_beats == 3.0


def test_a_beat_pushed_with_nobody_listening_is_not_an_error() -> None:
    daw = FakeDawAdapter()
    daw.push_beat(4)
    assert daw.song_position_beats == 4.0


def test_unlistening_stops_the_push() -> None:
    daw = FakeDawAdapter()
    beats: list[int] = []
    daw.listen_beats(beats.append)
    daw.unlisten_beats()
    daw.push_beat(1)
    assert beats == []


def test_listening_is_recorded_like_every_other_call() -> None:
    daw = FakeDawAdapter()
    daw.listen_beats(lambda beat: None)
    daw.unlisten_beats()
    assert daw.calls[-2:] == ["listen_beats", "unlisten_beats"]


def test_unlisten_survives_injected_failure_the_way_close_does() -> None:
    """It runs in teardown; a raise there hides whatever actually went wrong."""
    daw = FakeDawAdapter(fail_with=DawTimeoutError("Live went away"), fail_after=0)
    daw.unlisten_beats()
