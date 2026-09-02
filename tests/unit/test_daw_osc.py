"""The OSC codec and the receive loop's routing decision.

No `UdpOscTransport` is ever constructed here: constructing one binds port 11001 and the
default suite talks to nothing. The socket path is exercised in
`tests/integration/test_live_bridge.py`, against a real Live.

What *is* exercised is `Router`, which is the half of ADR-014 that can go wrong quietly —
a beat message stealing a reply, or a reply landing after its caller gave up. It owns no
socket for exactly that reason.
"""

from __future__ import annotations

import socket

import pytest
from pydantic import ValidationError

from garagem.daw import DawProtocolError, OscArg, OscSettings, Router, decode, encode
from garagem.daw.fake import FakeOscTransport
from garagem.daw.osc import _timed_out

# ------------------------------------------------------------------------ the datagram


def test_an_address_with_no_arguments_round_trips() -> None:
    assert decode(encode("/live/test", ())) == ("/live/test", ())


def test_mixed_types_come_back_in_order() -> None:
    args = (0, 1, "DRUMS", 2.5)
    address, decoded = decode(encode("/live/track/set/name", args))

    assert address == "/live/track/set/name"
    assert decoded == args


def test_a_beat_position_survives_the_round_trip() -> None:
    """OSC floats are 32-bit, so ask only for what a beat position actually needs."""
    (position,) = decode(encode("/live/clip/add/notes", (1.5,)))[1]
    assert position == pytest.approx(1.5)


def test_a_truncated_datagram_is_a_protocol_error() -> None:
    whole = encode("/live/song/get/tempo", (132.0,))
    with pytest.raises(DawProtocolError, match="unparseable"):
        decode(whole[:5])


# --------------------------------------------------------------------------- settings


def test_the_settings_are_frozen_and_refuse_an_unknown_key() -> None:
    settings = OscSettings()
    assert (settings.send_port, settings.reply_port) == (11000, 11001)
    with pytest.raises(ValidationError):
        settings.timeout_s = 5.0  # type: ignore[misc]
    with pytest.raises(ValidationError):
        OscSettings.model_validate({"timeout": 5.0})


# ------------------------------------------------------------- failure classification


def test_the_timeout_message_names_all_three_causes() -> None:
    """Silence is one event on the wire; the message has to carry the whole set."""
    message = str(_timed_out("/live/test", 0.5))

    assert "Live is closed" in message
    assert "control surface is not enabled" in message
    assert "rejected the request" in message
    assert "abletonosc.log" in message


# ------------------------------------------------------------------------- the fuse


def test_the_fuse_refuses_a_udp_datagram() -> None:
    """UDP never calls `connect`, so the fuse has to block `sendto` separately.

    Without this, a unit test that built a real transport would quietly fire packets
    at whatever Ableton Live happens to be open on the machine.
    """
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp,
        pytest.raises(RuntimeError, match="UDP datagram in a default-suite test"),
    ):
        udp.sendto(b"/live/test\x00\x00", ("127.0.0.1", 11000))


# ============================================================== the receive loop (ADR-014)
#
# `UdpOscTransport` itself is never constructed here: it binds 11001 and the `no_network`
# fuse refuses the datagram. What can go subtly wrong is the routing decision, and that
# is `Router`, which owns no socket precisely so this file can drive it.


def a_router() -> Router:
    return Router()


def test_a_reply_reaches_the_caller_that_asked_for_it() -> None:
    router = a_router()
    waiter = router.expect("/live/song/get/tempo")
    router.route("/live/song/get/tempo", (132.0,))
    assert waiter.arrived.is_set()
    assert waiter.params == (132.0,)


def test_an_unsolicited_message_reaches_its_listener() -> None:
    router = a_router()
    beats: list[tuple[OscArg, ...]] = []
    router.listen("/live/song/get/beat", beats.append)
    router.route("/live/song/get/beat", (4,))
    assert beats == [(4,)]


def test_a_beat_arriving_during_a_request_does_not_steal_its_reply() -> None:
    """The exact failure ADR-014 exists to prevent."""
    router = a_router()
    beats: list[tuple[OscArg, ...]] = []
    router.listen("/live/song/get/beat", beats.append)
    waiter = router.expect("/live/song/get/tempo")

    router.route("/live/song/get/beat", (7,))
    assert not waiter.arrived.is_set()
    assert beats == [(7,)]

    router.route("/live/song/get/tempo", (132.0,))
    assert waiter.params == (132.0,)
    assert router.dropped == 0


def test_a_message_nobody_claimed_is_counted() -> None:
    router = a_router()
    router.route("/live/song/get/beat", (1,))
    assert router.dropped == 1


def test_a_reply_that_arrives_after_its_caller_gave_up_is_counted_not_lost_silently() -> None:
    router = a_router()
    waiter = router.expect("/live/song/get/tempo")
    router.give_up("/live/song/get/tempo", waiter)
    router.route("/live/song/get/tempo", (132.0,))
    assert router.dropped == 1


def test_unlisten_stops_delivery() -> None:
    router = a_router()
    beats: list[tuple[OscArg, ...]] = []
    router.listen("/live/song/get/beat", beats.append)
    router.unlisten("/live/song/get/beat")
    router.route("/live/song/get/beat", (1,))
    assert beats == []
    assert router.dropped == 1


def test_a_listener_that_raises_does_not_stop_the_loop() -> None:
    """A dead receive thread is a silent hang: every later request blames Live."""
    router = a_router()
    seen: list[int] = []

    def explode(params: tuple[OscArg, ...]) -> None:
        seen.append(len(seen))
        raise RuntimeError("a bug in somebody's handler")

    router.listen("/live/song/get/beat", explode)
    router.route("/live/song/get/beat", (1,))
    router.route("/live/song/get/beat", (2,))
    assert seen == [0, 1]
    assert router.handler_errors == 2


def test_a_waiter_wins_over_a_listener_on_the_same_address() -> None:
    """A caller asked a question; the answer is theirs before it is anyone's news."""
    router = a_router()
    heard: list[tuple[OscArg, ...]] = []
    router.listen("/live/song/get/beat", heard.append)
    waiter = router.expect("/live/song/get/beat")
    router.route("/live/song/get/beat", (9,))
    assert waiter.params == (9,)
    assert heard == []


def test_the_fake_transport_delivers_the_same_way_live_does() -> None:
    """If the fake loses parity, the offline suite stops being evidence."""
    transport = FakeOscTransport(handler=lambda address, args: ())
    beats: list[tuple[OscArg, ...]] = []
    transport.listen("/live/song/get/beat", beats.append)
    transport.deliver("/live/song/get/beat", 3)
    assert beats == [(3,)]


def test_the_fake_counts_a_message_with_no_listener() -> None:
    transport = FakeOscTransport(handler=lambda address, args: ())
    transport.deliver("/live/song/get/beat", 3)
    assert transport.dropped == 1
