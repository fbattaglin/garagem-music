"""Global suite configuration.

The default suite (`uv run pytest`) never touches the network and never talks to
Ableton Live. Tests marked `live` or `slow` only run when asked for explicitly,
e.g. `uv run pytest -m live`.

The stream helpers use `asyncio.run` on purpose: the port is asynchronous, but that
alone does not justify a plugin dependency just to drain an iterator.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from garagem.daw import MidiNote
from garagem.llm import LLMProvider, Request, StreamEvent

OPTIONAL_MARKS = ("live", "slow")

Collector = Callable[[LLMProvider, Request], list[StreamEvent]]


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    expression = str(config.getoption("-m") or "")
    for mark in OPTIONAL_MARKS:
        if mark in expression:
            continue
        skip = pytest.mark.skip(reason=f"marked as '{mark}'; run with -m {mark}")
        for item in items:
            if mark in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest) -> Iterator[None]:
    """The fuse: the default suite opens no connections at all.

    "A test that makes a real call is a bug" is only true if something checks. We
    block `connect`, not socket creation — asyncio's event loop uses socketpair
    internally and has nothing to do with the network.

    `sendto` is blocked as well, and for a different reason: UDP never calls `connect`,
    so a datagram to AbletonOSC would sail straight past the `connect` fuse and hit a
    real Ableton Live on the machine. `bind`, `send`, `recv` and `recvfrom` stay open —
    asyncio's internals use them.
    """
    if "live" in request.keywords:
        yield
        return

    def refuse(self: socket.socket, address: Any) -> None:
        raise RuntimeError(
            f"network connection in a default-suite test: {address!r}. "
            "Use a cassette, or mark the test as `live`."
        )

    def refuse_datagram(self: socket.socket, data: Any, address: Any = None) -> None:
        raise RuntimeError(
            f"UDP datagram in a default-suite test: {address!r}. "
            "Use FakeOscTransport or FakeDawAdapter, or mark the test as `live`."
        )

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    socket.socket.connect = refuse  # type: ignore[method-assign, assignment]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign, assignment]
    socket.socket.sendto = refuse_datagram  # type: ignore[method-assign, assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.socket.sendto = original_sendto  # type: ignore[method-assign]


@pytest.fixture
def collect() -> Collector:
    def _collect(provider: LLMProvider, request: Request) -> list[StreamEvent]:
        async def _drain() -> list[StreamEvent]:
            return [event async for event in provider.stream(request)]

        return asyncio.run(_drain())

    return _collect


def text_of(events: list[StreamEvent]) -> str:
    """Reassemble the text from the deltas."""
    return "".join(e.text for e in events if e.type == "text_delta")


def tool_input_of(events: list[StreamEvent]) -> object:
    """Reassemble and parse the tool's JSON input from the fragments."""
    raw = "".join(e.fragment for e in events if e.type == "tool_input_delta")
    return json.loads(raw)


# The Phase 1 exit criterion, as pitches: Em-C-G-D, one chord per bar, four bars.
# Root-position triads inside one register band — the point is timing, not voicing
# (ADR-013), and a narrow band makes a wrong octave visible in the read-back.
EM_C_G_D: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("Em", (52, 55, 59)),
    ("C", (48, 52, 55)),
    ("G", (43, 47, 50)),
    ("D", (50, 54, 57)),
)
PROGRESSION_BEATS = 16.0


def chord_clip(beats_per_bar: float = 4.0, velocity: int = 100) -> tuple[MidiNote, ...]:
    """Em-C-G-D as notes, one chord per bar.

    Shared between the offline rehearsal and the `live` test so that both provably
    write the same thing — otherwise "it worked against the fake" and "it worked
    against Live" would be claims about two different pieces of music.
    """
    return tuple(
        MidiNote(
            pitch=pitch,
            start_beats=bar * beats_per_bar,
            duration_beats=beats_per_bar,
            velocity=velocity,
        )
        for bar, (_, pitches) in enumerate(EM_C_G_D)
        for pitch in pitches
    )
