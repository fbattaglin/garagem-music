"""The `DawPort` port — the only boundary between the system and Ableton Live.

Everything above this layer writes notes into clips and fires scenes. It does not know
whether the other side is Live over OSC, a fake in a unit test, or nothing at all.

Three decisions shape what is here, and — more visibly — what is not:

- **ADR-001: writes go into the next scene, and a playing clip is never rewritten.**
  So there is no way to edit a note, move the playhead or nudge a clip mid-flight. The
  shape of this port is itself the enforcement: what would be racy is not expressible.
- **Synchronous, on purpose.** The only consumer is `transport/`, where
  `.claude/rules/realtime.md` forbids awaiting I/O on the musical path. OSC is bounded
  request/response against a control-surface thread that ticks at ~100 Hz: there is no
  stream, no TTFT and nothing an event loop would buy. Deadlines are
  `socket.settimeout()`, one authority, no competing clocks.
- **P7: no retries.** No attempt count, no backoff, no reconnection loop. A call fails
  once and the caller decides — which, in this system, means the deterministic engine
  keeps playing (P2).

Deliberately absent, each for its own reason:

- **Track create and delete** — policy, not an API limit. `/live/song/create_midi_track`
  exists; ADR-013 declines to use it because no LOM call can load an instrument onto the
  new track, so it would receive MIDI correctly and make no sound.
- **Loading an instrument** — a genuine API limit. `device_names()` reports what is
  there; nothing installs it.
- **Device parameters** (sound design, mixing) — Phase 6 owns those.
- **Push notifications / listeners** — Phase 2 decides how the BarClock reads Live;
  until it does, this port only pulls.
- **Audio clips, per-note editing, the master track** — no caller needs them yet, and
  an unused method is an untested one.

`MidiNote` lives here rather than in `domain/` because it is the LOM's five-tuple, in
the LOM's units, in the LOM's field order — a wire concern. `domain.Note` is a musical
object Phase 2 gets to design on musical grounds; letting Live's serialisation define it
first would be the tail wagging the dog, and `domain/` stays pure by construction.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

FROZEN = ConfigDict(frozen=True, extra="forbid")

# What a beat listener is handed: the absolute beat number Live reported.
BeatHandler = Callable[[int], None]


class Quantization(StrEnum):
    """Live's global launch quantum — the thing that makes the switch sample-accurate.

    Part of the contract, not a user preference (ADR-001): with `NONE`, a fired scene
    launches the instant the datagram lands, which is mid-bar and audibly wrong.
    """

    NONE = "none"
    EIGHT_BARS = "8_bars"
    FOUR_BARS = "4_bars"
    TWO_BARS = "2_bars"
    BAR = "1_bar"
    HALF = "1_2"
    QUARTER = "1_4"


# `Live.Song.Quantization` crosses the wire as an int. These are its indices, and they
# are a guess about someone else's enum until a machine confirms them:
# `scripts/probe_live.py` walks them, which is what catches a reordering in a new Live.
QUANTIZATION_CODES: Final[dict[Quantization, int]] = {
    Quantization.NONE: 0,
    Quantization.EIGHT_BARS: 1,
    Quantization.FOUR_BARS: 2,
    Quantization.TWO_BARS: 3,
    Quantization.BAR: 4,
    Quantization.HALF: 5,
    Quantization.QUARTER: 7,
}

QUANTIZATION_BY_CODE: Final[dict[int, Quantization]] = {
    code: quantization for quantization, code in QUANTIZATION_CODES.items()
}


class MidiNote(BaseModel):
    """One note as Live stores it: pitch, position and length in beats, velocity, mute.

    Beats, not seconds and not ticks — Live's own unit, so a tempo change moves the
    music rather than breaking it.
    """

    model_config = FROZEN

    pitch: int = Field(ge=0, le=127)
    start_beats: float = Field(ge=0.0)
    # Strictly positive: a zero-length note is not a short note, it is silence with a
    # velocity, and Live will happily store one.
    duration_beats: float = Field(gt=0.0)
    # Velocity 0 is a note-off in MIDI, never a quiet note. Refuse it here rather than
    # let a whole part go silent because a generator scaled a dynamic to zero.
    velocity: int = Field(ge=1, le=127, default=100)
    mute: bool = False


class ClipAddress(BaseModel):
    """Where a clip lives: track index and scene index, both zero-based as in the LOM."""

    model_config = FROZEN

    track: int = Field(ge=0)
    scene: int = Field(ge=0)


# Live returns beat positions as floats it computed itself, so a read-back of 1.0 can
# come home as 0.9999999999.
#
# Four places, not six, and the reason is the wire rather than the music. **OSC floats
# are 32 bits.** A 24-bit mantissa carries about seven significant decimal digits, so at
# beat 17 the smallest representable step is already ~1e-6 — the same size as the sixth
# decimal place. Rounding finer than the wire compares noise: Phase 2's first live write
# failed with `want 17.018598, got 17.018599`, a single unit in a place no format can
# preserve and no ear can hear (`phase-2-findings.md`).
#
# 1e-4 of a beat is 45 microseconds at 132 BPM — 200 times finer than the humaniser's
# own maximum push, and about six times coarser than the worst float32 error anywhere in
# a 32-bar section. That gap is what makes the round trip exact rather than usually
# exact, which is what an idempotence criterion needs.
BEAT_PLACES: Final = 4


def normalised(notes: Iterable[MidiNote]) -> tuple[MidiNote, ...]:
    """Rounded and sorted, so what was written can be compared with what came back.

    Public because idempotence is the Phase 1 exit criterion, and a criterion that
    needs a tolerance argument at every call site is a criterion nobody states the same
    way twice. Sorted by start then pitch: Live returns notes in its own order, so
    equality has to be order-free.
    """
    rounded = [
        note.model_copy(
            update={
                "start_beats": round(note.start_beats, BEAT_PLACES),
                "duration_beats": round(note.duration_beats, BEAT_PLACES),
            }
        )
        for note in notes
    ]
    return tuple(sorted(rounded, key=lambda n: (n.start_beats, n.pitch)))


@runtime_checkable
class DawPort(Protocol):
    """Everything the system is allowed to do to a Live Set.

    Every method may raise `DawUnavailableError` (or its `DawTimeoutError` subclass)
    when Live does not answer, and `DawProtocolError` when it answers something the
    address did not promise. Setters raise `DawWriteNotConfirmedError` when the
    confirming read disagrees. None of them retries.
    """

    @property
    def name(self) -> str: ...

    # -- lifecycle
    def warm(self) -> None:
        """Prove Live is there and the control surface is loaded, before it matters."""
        ...

    def close(self) -> None: ...

    # -- transport and global state
    def tempo(self) -> float: ...
    def set_tempo(self, bpm: float) -> None: ...
    def song_time_beats(self) -> float:
        """The playhead, in beats. Phase 2's BarClock reads this; nothing writes it."""
        ...

    def is_playing(self) -> bool: ...
    def start_playing(self) -> None: ...
    def stop_playing(self) -> None: ...
    def quantization(self) -> Quantization: ...
    def set_quantization(self, quantization: Quantization) -> None: ...
    def song_loop(self) -> bool:
        """Is the arrangement loop switch on? The song position then jumps back forever.

        Clip launching does not care, but the `BarClock` counts bars from the song
        position: with the loop on it never reaches the bar the scheduler waits for
        (`phase-4-findings.md` §8).
        """
        ...

    def set_song_loop(self, on: bool) -> None: ...

    # -- the Set's shape
    def track_names(self) -> tuple[str, ...]: ...
    def set_track_name(self, track: int, name: str) -> None: ...
    def device_names(self, track: int) -> tuple[str, ...]:
        """What is loaded on the track. Empty means it will be silent (ADR-013)."""
        ...

    def accepts_midi(self, track: int) -> bool:
        """Is this a MIDI track? An audio track cannot hold a clip or an instrument.

        Renaming an audio track into a musical role would make the Set *look* right and
        guarantee silence — the same trap ADR-013 refuses track creation over.
        """
        ...

    def track_armed(self, track: int) -> bool:
        """Is the track armed? An armed MIDI track plays whatever a controller sends.

        Which is why the band's tracks are declared disarmed: with the MiniLab connected,
        a cue pad pressed over an armed track sounds a note inside the band (ADR-022).
        """
        ...

    def set_track_armed(self, track: int, armed: bool) -> None: ...

    def scene_count(self) -> int: ...

    # -- clips
    def has_clip(self, at: ClipAddress) -> bool: ...
    def clip_length_beats(self, at: ClipAddress) -> float: ...
    def create_clip(self, at: ClipAddress, length_beats: float) -> None: ...
    def delete_clip(self, at: ClipAddress) -> None: ...
    def read_notes(self, at: ClipAddress) -> tuple[MidiNote, ...]: ...
    def write_notes(self, at: ClipAddress, notes: Iterable[MidiNote]) -> None:
        """Replace the clip's contents. Never called on a clip that is playing."""
        ...

    def fire_scene(self, scene: int) -> None:
        """Ask Live to launch the scene at the next quantum. Returns immediately.

        Not confirmed by a read: at `1 Bar` the launch is up to 1.82 s away, so there
        is nothing to confirm yet. `is_playing()` is the caller's evidence (ADR-001).
        """
        ...

    def fire_clip(self, at: ClipAddress) -> None:
        """Launch one clip at the next quantum, in its track only. Returns immediately.

        Quantised like a scene fire, unconfirmed for the same reason — measured in Stage 0
        (`phase-4-findings.md` §7). A bar cue fires the tracks it changes and no others.
        """
        ...

    def stop_track(self, track: int) -> None:
        """Stop whatever the track plays, at the next quantum. Returns immediately."""
        ...

    def clip_legato(self, at: ClipAddress) -> bool: ...

    def set_clip_legato(self, at: ClipAddress, on: bool) -> None:
        """Whether a launch of this clip takes over the playing clip's position (ADR-022)."""
        ...

    # ------------------------------------------------------------------------ the beat

    def listen_beats(self, handler: BeatHandler) -> None:
        """Have Live push every integer beat to `handler`.

        Push, not poll. `song_time_beats()` still exists and is still the wrong tool for
        a clock: every call is a ~100 ms round trip on the same control-surface thread it
        is measuring (ADR-015).

        The handler runs on whatever thread the transport receives on. It must not block
        and must do no musical work — store the number, set an event, return.

        **One listener at a time.** Registering a second replaces the first, silently,
        because the transport routes by address and there is one beat address. Whatever
        else wants to know where the music is should ask the `BarClock`, which is the
        thing that owns this listener.
        """
        ...

    def unlisten_beats(self) -> None:
        """Stop the push. Idempotent: stopping a listener nobody started is not an error."""
        ...
