"""Cuts a decoded WAV into the regions a preset plays (ADR-029).

GarageBand keeps a whole guitar in one file, every zone one after the next. Live's Simpler
plays a file from its start, so each region a `Part` uses becomes a WAV of its own.
"""

from __future__ import annotations

import io
import wave
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Cut:
    """A region of the source as a WAV of its own."""

    data: bytes
    frames: int
    rate: int


def cut(wav: bytes, regions: Sequence[tuple[int, int]]) -> tuple[Cut, ...]:
    """One WAV per `(start, end)` region, in frames, end exclusive, same format as `wav`."""
    with wave.open(io.BytesIO(wav), "rb") as source:
        params = source.getparams()
        cuts: list[Cut] = []
        for start, end in regions:
            if not 0 <= start < end <= params.nframes:
                raise ValueError(
                    f"region {start}..{end} is outside a file of {params.nframes} frames"
                )
            source.setpos(start)
            frames = source.readframes(end - start)
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as target:
                target.setnchannels(params.nchannels)
                target.setsampwidth(params.sampwidth)
                target.setframerate(params.framerate)
                target.writeframes(frames)
            cuts.append(Cut(data=buffer.getvalue(), frames=end - start, rate=params.framerate))
    return tuple(cuts)
