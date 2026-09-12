"""The AbletonOSC adapter: wire payloads, confirming reads, failure classification.

Every test drives the *real* adapter through a `FakeOscTransport`, so the payload
building, the confirmation logic and the error classification are all genuinely
exercised — with no socket opened and no Live running. The reply shapes below are
taken from AbletonOSC's own handlers: `_get_property` answers `(value, *params)`,
track callbacks prepend the track index, clip callbacks prepend `(track, clip)`, and
every setter answers nothing at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from garagem.daw import (
    ClipAddress,
    DawPort,
    DawProtocolError,
    DawTimeoutError,
    DawWriteNotConfirmedError,
    FakeOscTransport,
    MidiNote,
    OscArg,
    Quantization,
    notes_from_reply,
    notes_payload,
)
from garagem.daw.abletonosc import (
    ADD_NOTES,
    ALL_ADDRESSES,
    CREATE_CLIP,
    FIRE_SCENE,
    GET_BEAT,
    GET_CLIP_LENGTH,
    GET_DEVICE_NAMES,
    GET_HAS_CLIP,
    GET_HAS_MIDI_INPUT,
    GET_IS_PLAYING,
    GET_LOOP,
    GET_METER_LEVEL,
    GET_NOTES,
    GET_NUM_SCENES,
    GET_QUANTIZATION,
    GET_SONG_TIME,
    GET_TEMPO,
    GET_TRACK_ARM,
    GET_TRACK_NAMES,
    REMOVE_NOTES,
    SET_LOOP,
    SET_QUANTIZATION,
    SET_TEMPO,
    SET_TRACK_ARM,
    SET_TRACK_NAME,
    START_LISTEN_BEAT,
    START_PLAYING,
    STOP_LISTEN_BEAT,
    STOP_PLAYING,
    TEST,
    AbletonOSCAdapter,
)

AT = ClipAddress(track=3, scene=1)
CHORD = (
    MidiNote(pitch=52, start_beats=0.0, duration_beats=4.0),
    MidiNote(pitch=55, start_beats=0.0, duration_beats=4.0),
    MidiNote(pitch=59, start_beats=0.0, duration_beats=4.0),
)

# What AbletonOSC answers a healthy Set with. A setter is absent on purpose: it
# answers nothing, which is what `None` means to `FakeOscTransport`.
HEALTHY: dict[str, tuple[OscArg, ...]] = {
    TEST: ("ok",),
    GET_TEMPO: (132.0,),
    GET_SONG_TIME: (4.0,),
    GET_IS_PLAYING: (True,),
    GET_NUM_SCENES: (2,),
    GET_QUANTIZATION: (4,),
    GET_TRACK_NAMES: ("DRUMS", "BASS", "GTR", "KEYS"),
    GET_DEVICE_NAMES: (3, "Drift"),
    GET_METER_LEVEL: (3, 0.42),
    GET_HAS_CLIP: (3, 1, True),
    GET_HAS_MIDI_INPUT: (3, True),
    GET_TRACK_ARM: (3, False),
    GET_LOOP: (False,),
    GET_CLIP_LENGTH: (3, 1, 16.0),
    GET_NOTES: (3, 1),
}


def serving(**replies: object) -> FakeOscTransport:
    """A transport answering `HEALTHY`, with the named addresses overridden.

    Keys are the constant names (`GET_TEMPO=...`), because an OSC address is not a
    valid keyword. A value of `None` means Live said nothing.
    """
    table = dict(HEALTHY)
    for name, reply in replies.items():
        address = globals()[name]
        if reply is None:
            table.pop(address, None)
        else:
            assert isinstance(reply, tuple)
            table[address] = reply

    def handler(address: str, args: tuple[OscArg, ...]) -> Sequence[OscArg] | None:
        return table.get(address)

    return FakeOscTransport(handler=handler)


def adapter(transport: FakeOscTransport | None = None) -> AbletonOSCAdapter:
    return AbletonOSCAdapter(transport=transport or serving())


def sent(transport: FakeOscTransport) -> list[str]:
    return [address for address, _ in transport.sent]


# --------------------------------------------------------------------- wire payloads


def test_the_note_payload_is_the_address_then_five_fields_per_note() -> None:
    payload = notes_payload(AT, CHORD)

    assert payload[:2] == (3, 1)
    assert len(payload) == 2 + 5 * len(CHORD)
    assert payload[2:7] == (52, 0.0, 4.0, 100, False)


def test_a_note_reply_is_parsed_back_into_the_notes_that_were_written() -> None:
    reply = notes_payload(AT, CHORD)
    assert notes_from_reply(AT, reply) == CHORD


def test_a_reply_that_does_not_divide_by_five_is_a_protocol_error() -> None:
    """A truncated reply must not arrive as a section quietly missing its last chord."""
    with pytest.raises(DawProtocolError, match="not a multiple of 5"):
        notes_from_reply(AT, (3, 1, 52, 0.0, 4.0, 100))


def test_a_reply_about_another_clip_is_a_protocol_error() -> None:
    with pytest.raises(DawProtocolError, match="not 3/1"):
        notes_from_reply(AT, (0, 0, 52, 0.0, 4.0, 100, False))


def test_reading_notes_asks_about_the_right_clip() -> None:
    transport = serving(GET_NOTES=notes_payload(AT, CHORD))
    assert adapter(transport).read_notes(AT) == CHORD
    assert transport.sent[-1] == (GET_NOTES, (3, 1))


# ------------------------------------------------------------------ confirming reads


def test_reading_the_global_state_unwraps_the_single_value() -> None:
    daw = adapter()
    assert daw.tempo() == 132.0
    assert daw.song_time_beats() == 4.0
    assert daw.is_playing() is True
    assert daw.scene_count() == 2
    assert daw.quantization() is Quantization.BAR


def test_track_and_clip_getters_drop_the_echoed_index() -> None:
    daw = adapter()
    assert daw.track_names() == ("DRUMS", "BASS", "GTR", "KEYS")
    assert daw.device_names(3) == ("Drift",)
    assert daw.has_clip(AT) is True
    assert daw.clip_length_beats(AT) == 16.0
    assert daw.meter_level(3) == pytest.approx(0.42)
    assert daw.accepts_midi(3) is True
    assert daw.track_armed(3) is False


def test_setting_the_tempo_sends_it_and_then_reads_it_back() -> None:
    transport = serving()
    adapter(transport).set_tempo(132.0)
    assert sent(transport) == [SET_TEMPO, GET_TEMPO]


def test_a_setter_that_did_not_take_is_not_confirmed() -> None:
    transport = serving(GET_TEMPO=(120.0,))
    with pytest.raises(DawWriteNotConfirmedError, match="did not take"):
        adapter(transport).set_tempo(132.0)


def test_setting_the_quantisation_sends_lives_integer_code() -> None:
    transport = serving(GET_QUANTIZATION=(3,))
    adapter(transport).set_quantization(Quantization.TWO_BARS)
    assert transport.sent[0] == (SET_QUANTIZATION, (3,))


def test_renaming_a_track_is_confirmed_against_the_track_names() -> None:
    transport = serving(GET_TRACK_NAMES=("DRUMS", "BASS", "GTR", "KEYS"))
    adapter(transport).set_track_name(2, "GTR")
    assert sent(transport) == [SET_TRACK_NAME, GET_TRACK_NAMES]


def test_the_loop_switch_is_read_and_turning_it_off_is_confirmed() -> None:
    transport = serving()
    daw = adapter(transport)
    assert daw.song_loop() is False
    transport.sent.clear()
    daw.set_song_loop(False)
    assert transport.sent == [(SET_LOOP, (False,)), (GET_LOOP, ())]


def test_a_loop_that_stayed_on_is_not_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("garagem.daw.abletonosc.SETTLE_S", 0.05)
    transport = serving(GET_LOOP=(True,))
    with pytest.raises(DawWriteNotConfirmedError, match="did not take"):
        adapter(transport).set_song_loop(False)
    assert sent(transport).count(SET_LOOP) == 1


def test_a_loop_live_applies_a_tick_later_is_confirmed_without_writing_twice() -> None:
    """What Live did on 2026-09-12: the first read still said on, the next said off."""
    answers = iter([(True,), (False,)])

    def handler(address: str, args: tuple[OscArg, ...]) -> Sequence[OscArg] | None:
        if address == GET_LOOP:
            return next(answers)
        return HEALTHY.get(address)

    transport = FakeOscTransport(handler=handler)
    adapter(transport).set_song_loop(False)
    assert sent(transport) == [SET_LOOP, GET_LOOP, GET_LOOP]


def test_disarming_a_track_is_confirmed_by_reading_the_arm_back() -> None:
    transport = serving()
    adapter(transport).set_track_armed(3, False)
    assert transport.sent == [(SET_TRACK_ARM, (3, False)), (GET_TRACK_ARM, (3,))]


def test_a_track_that_stayed_armed_is_not_confirmed() -> None:
    transport = serving(GET_TRACK_ARM=(3, True))
    with pytest.raises(DawWriteNotConfirmedError, match="did not take"):
        adapter(transport).set_track_armed(3, False)


def test_creating_a_clip_is_confirmed_by_asking_whether_the_slot_has_one() -> None:
    transport = serving()
    adapter(transport).create_clip(AT, 16.0)
    assert transport.sent == [(CREATE_CLIP, (3, 1, 16.0)), (GET_HAS_CLIP, (3, 1))]


def test_creating_a_clip_that_did_not_appear_is_not_confirmed() -> None:
    transport = serving(GET_HAS_CLIP=(3, 1, False))
    with pytest.raises(DawWriteNotConfirmedError):
        adapter(transport).create_clip(AT, 16.0)


def test_writing_notes_removes_the_old_ones_before_adding_the_new_ones() -> None:
    """`/live/clip/add/notes` appends. Without the removal, a rewrite doubles the part."""
    transport = serving(GET_NOTES=notes_payload(AT, CHORD))
    adapter(transport).write_notes(AT, CHORD)
    assert sent(transport) == [REMOVE_NOTES, ADD_NOTES, GET_NOTES]


def test_the_removal_clears_every_pitch_over_the_whole_clip() -> None:
    transport = serving(GET_NOTES=notes_payload(AT, CHORD))
    adapter(transport).write_notes(AT, CHORD)
    assert transport.sent[0] == (REMOVE_NOTES, (3, 1, 0, 127, -8192, 16384))


def test_a_write_that_read_back_different_is_not_confirmed() -> None:
    transport = serving(GET_NOTES=notes_payload(AT, CHORD[:2]))
    with pytest.raises(DawWriteNotConfirmedError, match="3 notes"):
        adapter(transport).write_notes(AT, CHORD)


def test_firing_a_scene_is_not_confirmed_by_a_read() -> None:
    """At `1 Bar` the launch is up to 1.82 s away — there is nothing to read yet."""
    transport = serving()
    daw = adapter(transport)
    daw.fire_scene(1)
    daw.start_playing()
    daw.stop_playing()
    assert sent(transport) == [FIRE_SCENE, START_PLAYING, STOP_PLAYING]


# ------------------------------------------------------------- failure classification


def test_silence_from_live_is_a_timeout_and_is_not_retried() -> None:
    transport = serving(TEST=None)
    with pytest.raises(DawTimeoutError):
        adapter(transport).warm()
    assert len(transport.sent) == 1


def test_a_warm_that_answers_something_other_than_ok_is_a_protocol_error() -> None:
    with pytest.raises(DawProtocolError, match="expected"):
        adapter(serving(TEST=("nope",))).warm()


def test_an_unknown_quantisation_code_says_to_run_the_probe() -> None:
    """The one place a reordered LOM enum can be caught before it mistimes the music."""
    with pytest.raises(DawProtocolError, match="probe_live"):
        adapter(serving(GET_QUANTIZATION=(99,))).quantization()


def test_a_reply_about_the_wrong_track_is_a_protocol_error() -> None:
    with pytest.raises(DawProtocolError, match="index 3"):
        adapter(serving(GET_DEVICE_NAMES=(0, "Drift"))).device_names(3)


def test_a_getter_that_answers_two_values_is_a_protocol_error() -> None:
    with pytest.raises(DawProtocolError, match="expected one value"):
        adapter(serving(GET_TEMPO=(132.0, 0.0))).tempo()


# ------------------------------------------------------------------------- plumbing


def test_warming_asks_live_to_confirm_it_is_there() -> None:
    transport = serving()
    adapter(transport).warm()
    assert transport.sent == [(TEST, ())]


def test_closing_the_adapter_closes_the_transport() -> None:
    transport = serving()
    adapter(transport).close()
    assert transport.closed


def test_the_adapter_satisfies_the_port() -> None:
    daw: DawPort = adapter()
    assert isinstance(daw, DawPort)
    assert daw.name == "abletonosc"


# ============================================================ the beat listener (ADR-014)


def test_listening_for_beats_registers_and_asks_live_to_push() -> None:
    """`send`, not `request`: Live answers this one at GET_BEAT, not at the address."""
    transport = FakeOscTransport(handler=lambda address, args: ())
    adapter = AbletonOSCAdapter(transport=transport)
    beats: list[int] = []

    adapter.listen_beats(beats.append)

    assert (START_LISTEN_BEAT, ()) in transport.sent
    assert GET_BEAT in transport.listeners


def test_a_pushed_beat_reaches_the_handler_as_an_integer() -> None:
    transport = FakeOscTransport(handler=lambda address, args: ())
    adapter = AbletonOSCAdapter(transport=transport)
    beats: list[int] = []
    adapter.listen_beats(beats.append)

    transport.deliver(GET_BEAT, 7)
    assert beats == [7]


def test_a_beat_arriving_as_a_float_is_still_a_beat() -> None:
    """Live's own handler sends `int(current_song_time)`, but the wire has no int type
    guarantee across builds and a float here must not crash the receive thread."""
    transport = FakeOscTransport(handler=lambda address, args: ())
    adapter = AbletonOSCAdapter(transport=transport)
    beats: list[int] = []
    adapter.listen_beats(beats.append)

    transport.deliver(GET_BEAT, 12.0)
    assert beats == [12]


def test_a_beat_message_with_nothing_in_it_is_a_protocol_error() -> None:
    transport = FakeOscTransport(handler=lambda address, args: ())
    adapter = AbletonOSCAdapter(transport=transport)
    adapter.listen_beats(lambda beat: None)

    with pytest.raises(DawProtocolError, match="no beat number"):
        transport.deliver(GET_BEAT)


def test_unlistening_stops_live_pushing_and_drops_the_route() -> None:
    transport = FakeOscTransport(handler=lambda address, args: ())
    adapter = AbletonOSCAdapter(transport=transport)
    beats: list[int] = []
    adapter.listen_beats(beats.append)

    adapter.unlisten_beats()

    assert (STOP_LISTEN_BEAT, ()) in transport.sent
    assert GET_BEAT not in transport.listeners
    transport.deliver(GET_BEAT, 3)
    assert beats == []


def test_the_three_beat_addresses_are_in_all_addresses() -> None:
    """`probe_live.py` walks that tuple; an address missing from it is never checked."""
    assert {START_LISTEN_BEAT, STOP_LISTEN_BEAT, GET_BEAT} <= set(ALL_ADDRESSES)
