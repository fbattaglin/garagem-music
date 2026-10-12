"""Cutting a consolidated WAV into the regions its zones play (ADR-029)."""

from __future__ import annotations

import array
import io
import wave

import pytest

from garagem.sounds.audio import cut


def ramp(frames: int, rate: int = 44100) -> bytes:
    """A mono 16-bit WAV whose frame n holds the value n, so a cut shows where it came from."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(array.array("h", range(frames)).tobytes())
    return buffer.getvalue()


def frames_of(data: bytes) -> tuple[int, list[int]]:
    with wave.open(io.BytesIO(data), "rb") as source:
        return source.getframerate(), list(array.array("h", source.readframes(source.getnframes())))


def test_each_region_becomes_a_wav_holding_exactly_its_frames() -> None:
    first, second = cut(ramp(1000, rate=48000), [(10, 20), (500, 503)])

    assert (first.frames, first.rate) == (10, 48000)
    assert frames_of(first.data) == (48000, list(range(10, 20)))
    assert frames_of(second.data) == (48000, [500, 501, 502])


def test_a_region_outside_the_file_is_refused() -> None:
    with pytest.raises(ValueError, match="outside"):
        cut(ramp(100), [(90, 101)])
