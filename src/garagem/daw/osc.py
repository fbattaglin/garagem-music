"""OSC over UDP: one request, one correlated reply, one deadline.

`python-osc` is here for its **codecs only** — `OscMessageBuilder` and `OscMessage`.

An earlier version of this docstring said a dispatcher "would add a thread and a queue
for a problem we do not have". **Phase 2 has the problem** (ADR-014): the BarClock reads
Live's transport from `/live/song/start_listen/beat`, which pushes an unsolicited
datagram to 11001 on every beat. A pure request/response socket eats those — `request`
drained the buffer before sending and discarded every reply whose address did not match.
Both were right for one bounded round trip and both destroy a beat message.

So this module now owns one background receive thread. It still does not use
`python-osc`'s servers: they bring a second socket, and the reply port is fixed at 11001
so two owners cannot coexist.

Two facts about AbletonOSC decide the design:

- **Replies always go to port 11001**, whatever port the request was sent from. So a
  single socket, *bound* to 11001, both sends and receives — and only one process on
  the machine can hold it at a time. A second one gets `DawUnavailableError` at
  construction, which is the honest answer.
- **A handler that raises replies with nothing at all.** There is no error address. So
  the only failure this layer can observe is silence, and silence is a timeout.

`OscTransport` is the seam, playing exactly the role `httpx.AsyncBaseTransport` plays in
the Anthropic adapter: unit tests drive the real adapter through a fake transport and
never open a socket.

Nothing here retries (P7). A datagram goes out once.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Sequence
from contextlib import suppress
from typing import Any, Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict
from pythonosc.osc_message import OscMessage, ParseError
from pythonosc.osc_message_builder import BuildError, OscMessageBuilder

from garagem.daw.errors import DawProtocolError, DawTimeoutError, DawUnavailableError

OscArg = int | float | str | bool

LOG_PATH: Final = "~/Music/Ableton/User Library/Remote Scripts/AbletonOSC/logs/abletonosc.log"


@runtime_checkable
class OscTransport(Protocol):
    """The seam between the AbletonOSC adapter and an actual socket."""

    def send(self, address: str, *args: OscArg) -> None:
        """Fire and forget. Only for calls whose effect is not observable yet."""
        ...

    def request(
        self, address: str, *args: OscArg, timeout_s: float | None = None
    ) -> tuple[OscArg, ...]:
        """Send, then wait for the reply to this same address, or raise."""
        ...

    def listen(self, address: str, handler: OscListener) -> None:
        """Route unsolicited messages at `address` to `handler`.

        The handler runs on the receive thread. It must not block and must do no musical
        work: set a value, set an `Event`, return. Everything else happens on the thread
        that is waiting. That boundary is P1's, and it is a data structure rather than a
        call (ADR-014).
        """
        ...

    def unlisten(self, address: str) -> None: ...

    def close(self) -> None: ...


OscListener = Callable[[tuple[OscArg, ...]], None]

# How long `close()` waits for the receive thread. It is a daemon, so a stuck join cannot
# hang the interpreter — this only decides how long we are polite about it.
JOIN_TIMEOUT_S: Final = 1.0


class OscSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = "127.0.0.1"
    send_port: int = 11000
    reply_port: int = 11001
    # ~50 control-surface ticks. Generous for a local round trip against a thread that
    # runs at 100 Hz, short enough that a closed Live is obvious inside a second.
    timeout_s: float = 0.5
    # The first call also pays for Live noticing us at all.
    warm_timeout_s: float = 2.0


def encode(address: str, args: Sequence[OscArg]) -> bytes:
    """Build the datagram.

    Public because the tests need to see exactly what would go over the wire, with no
    socket and no Live.
    """
    builder = OscMessageBuilder(address=address)
    for arg in args:
        builder.add_arg(arg)
    try:
        return bytes(builder.build().dgram)
    except BuildError as exc:  # pragma: no cover - only a bad type reaches this
        raise DawProtocolError(f"cannot encode {address} with {args!r}: {exc}") from exc


def decode(datagram: bytes) -> tuple[str, tuple[OscArg, ...]]:
    """Parse a datagram into its address and arguments. Public, same reason.

    Every argument is checked against `OscArg` rather than trusted: `python-osc` types
    its parameters as `Any`, and an unexpected blob reaching the adapter as a note
    position would be far harder to diagnose here than at the door.
    """
    try:
        message = OscMessage(datagram)
    except ParseError as exc:
        raise DawProtocolError(f"unparseable OSC datagram ({len(datagram)} bytes): {exc}") from exc
    return message.address, tuple(_checked(param, message.address) for param in message.params)


def _checked(param: Any, address: str) -> OscArg:  # noqa: ANN401 - pythonosc yields Any
    if isinstance(param, bool | int | float | str):
        return param
    raise DawProtocolError(
        f"{address} replied with an unsupported OSC type: {type(param).__name__}"
    )


class _Waiter:
    """One caller's slot: where its reply lands and how it learns the reply arrived."""

    __slots__ = ("arrived", "params")

    def __init__(self) -> None:
        self.arrived = threading.Event()
        self.params: tuple[OscArg, ...] = ()


class Router:
    """Where a datagram goes: a waiting caller, a listener, or the dropped count.

    Split out of the transport so the decision can be tested without a socket. It is the
    part of ADR-014 that can go subtly wrong — a beat message stealing a reply, or a
    reply arriving after its caller gave up — and the `no_network` fuse means a test that
    binds a real port is not an option anyway.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiters: dict[str, _Waiter] = {}
        self._listeners: dict[str, OscListener] = {}
        # Observables, not diagnostics: `dropped` rising during a run is how Phase 2
        # learns that a write starved the beat listener, and `handler_errors` is how a
        # listener that raises stops being invisible.
        self.dropped = 0
        self.handler_errors = 0

    def expect(self, address: str) -> _Waiter:
        """Claim the next reply to `address`.

        One waiter per address: AbletonOSC's reply carries no correlation id, so two
        concurrent requests to the same address could not be told apart even in principle.
        """
        waiter = _Waiter()
        with self._lock:
            self._waiters[address] = waiter
        return waiter

    def give_up(self, address: str, waiter: _Waiter) -> None:
        with self._lock:
            if self._waiters.get(address) is waiter:
                del self._waiters[address]

    def listen(self, address: str, handler: OscListener) -> None:
        with self._lock:
            self._listeners[address] = handler

    def unlisten(self, address: str) -> None:
        with self._lock:
            self._listeners.pop(address, None)

    def route(self, address: str, params: tuple[OscArg, ...]) -> None:
        """A waiting caller first, then a listener, then the floor.

        A handler that raises is counted and swallowed: this runs on the receive thread,
        and a dead receive loop is a silent hang — every later request times out and the
        message blames Live.
        """
        with self._lock:
            waiter = self._waiters.pop(address, None)
            listener = self._listeners.get(address)
        if waiter is not None:
            waiter.params = params
            waiter.arrived.set()
            return
        if listener is not None:
            try:
                listener(params)
            except Exception:
                self.handler_errors += 1
            return
        # Nobody asked for it: a reply that arrived after its caller gave up, or an
        # address we never registered. Counting it is the whole point.
        self.dropped += 1


class UdpOscTransport:
    """One socket bound to the reply port, one receive thread, one `Router`.

    The thread reads every datagram and hands it to the router, which decides whether it
    belongs to a waiting caller, to a listener, or to nobody. `request` no longer touches
    the socket's receive side at all, which is what stops it from eating the beat
    messages (ADR-014).
    """

    def __init__(self, settings: OscSettings | None = None) -> None:
        self._settings = settings or OscSettings()
        self._target = (self._settings.host, self._settings.send_port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._socket.bind((self._settings.host, self._settings.reply_port))
        except OSError as exc:
            self._socket.close()
            raise DawUnavailableError(
                f"cannot bind the AbletonOSC reply port {self._settings.reply_port}: {exc}. "
                "AbletonOSC always replies to that port, so exactly one process at a time "
                "can talk to Live — close the other one."
            ) from exc

        self.router = Router()
        self._closing = threading.Event()
        self._receiver = threading.Thread(target=self._receive, name="osc-receive", daemon=True)
        self._receiver.start()

    # ------------------------------------------------------------------------ sending

    def send(self, address: str, *args: OscArg) -> None:
        self._sendto(address, args)

    def request(
        self, address: str, *args: OscArg, timeout_s: float | None = None
    ) -> tuple[OscArg, ...]:
        """Register, send, wait. Never retries (P7); the datagram goes out once."""
        budget = self._settings.timeout_s if timeout_s is None else timeout_s
        waiter = self.router.expect(address)
        try:
            self._sendto(address, args)
            if not waiter.arrived.wait(budget):
                raise _timed_out(address, budget)
            return waiter.params
        finally:
            self.router.give_up(address, waiter)

    # ---------------------------------------------------------------------- listening

    def listen(self, address: str, handler: OscListener) -> None:
        self.router.listen(address, handler)

    def unlisten(self, address: str) -> None:
        self.router.unlisten(address)

    # ------------------------------------------------------------------------ closing

    def close(self) -> None:
        self._closing.set()
        # Wake the blocking recvfrom by shutting the socket down under it. The thread is
        # a daemon, so even a join that never returns cannot hold the interpreter open.
        with suppress(OSError):
            self._socket.shutdown(socket.SHUT_RDWR)
        self._socket.close()
        if self._receiver.is_alive():
            self._receiver.join(JOIN_TIMEOUT_S)

    # ------------------------------------------------------------------------ the loop

    def _receive(self) -> None:
        """Read forever, route, never die.

        A handler that raises must not kill this thread: a dead receive loop is a silent
        hang — every later `request` times out and the message blames Live.
        """
        while not self._closing.is_set():
            try:
                datagram, _ = self._socket.recvfrom(65535)
            except (TimeoutError, InterruptedError):
                continue
            except OSError:
                return
            try:
                address, params = decode(datagram)
            except DawProtocolError:
                self.router.dropped += 1
                continue
            self.router.route(address, params)

    def _sendto(self, address: str, args: Sequence[OscArg]) -> None:
        try:
            self._socket.sendto(encode(address, args), self._target)
        except OSError as exc:
            raise DawUnavailableError(f"cannot send {address} to {self._target}: {exc}") from exc


# ------------------------------------------------------------- failure classification


def _timed_out(address: str, budget: float) -> DawTimeoutError:
    """Silence. It has three causes and the wire cannot tell them apart."""
    return DawTimeoutError(
        f"no reply to {address} within {budget:.2f} s. Either Live is closed, or the "
        "AbletonOSC control surface is not enabled in Live's settings, or the handler "
        "rejected the request — AbletonOSC answers all three with nothing at all. "
        f"The log says which: {LOG_PATH}. Not retried on purpose (P7)."
    )
