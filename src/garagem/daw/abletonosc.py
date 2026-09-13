"""AbletonOSC adapter — the `DawPort` implementation that talks to a running Live.

Raw OSC over our own socket rather than `python-osc`'s servers, for the reasons in
`osc.py`. The cost of that choice, exactly as with the Anthropic adapter, is that the
wire format is now ours to track: every address and every reply shape below is a claim
about someone else's code. Two things pin those claims — `scripts/probe_live.py`, which
walks `ALL_ADDRESSES` against a real Live and reports what came back, and the `live`
integration tests. When AbletonOSC changes a reply, one command says which one.

Nothing here retries (P7) and nothing here decides. It translates, confirms, and
classifies failures so the caller can tell "Live is gone" from "we are wrong about
the format".

**Every setter is write-then-confirm.** OSC is UDP: a setter reply does not exist —
AbletonOSC answers a successful `set` with nothing at all, exactly as it answers a
failed one. So a write is only known to have landed once the matching getter says so,
and a Set that silently ignored a write would play something other than what was
generated. The three exceptions are `fire_scene`, `start_playing` and `stop_playing`:
their effect is up to a bar in the future (ADR-001), so there is nothing to read back
yet. `is_playing()` is the caller's evidence.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Iterable, Sequence
from typing import Any, Final

from garagem.daw.errors import (
    DawProtocolError,
    DawTimeoutError,
    DawWriteNotConfirmedError,
)
from garagem.daw.osc import LOG_PATH, OscArg, OscSettings, OscTransport, UdpOscTransport
from garagem.daw.port import (
    QUANTIZATION_BY_CODE,
    QUANTIZATION_CODES,
    BeatHandler,
    ClipAddress,
    MidiNote,
    Quantization,
    normalised,
)

TEST: Final = "/live/test"
VERSION: Final = "/live/application/get/version"

GET_TEMPO: Final = "/live/song/get/tempo"
SET_TEMPO: Final = "/live/song/set/tempo"
GET_SONG_TIME: Final = "/live/song/get/current_song_time"
GET_IS_PLAYING: Final = "/live/song/get/is_playing"
START_PLAYING: Final = "/live/song/start_playing"
STOP_PLAYING: Final = "/live/song/stop_playing"
GET_TRACK_NAMES: Final = "/live/song/get/track_names"
GET_NUM_SCENES: Final = "/live/song/get/num_scenes"
GET_QUANTIZATION: Final = "/live/song/get/clip_trigger_quantization"

# Live pushes, we do not poll. `start_listen/beat` registers a listener on Live's side;
# from then on every integer beat arrives unsolicited at GET_BEAT with `(beat,)` — read
# out of AbletonOSC's own `song.py`, `current_song_time_changed`. At 132 BPM that is one
# datagram every 455 ms, which is the whole cost of knowing where the music is (ADR-015).
START_LISTEN_BEAT: Final = "/live/song/start_listen/beat"
STOP_LISTEN_BEAT: Final = "/live/song/stop_listen/beat"
GET_BEAT: Final = "/live/song/get/beat"
SET_QUANTIZATION: Final = "/live/song/set/clip_trigger_quantization"

GET_TRACK_NAME: Final = "/live/track/get/name"
SET_TRACK_NAME: Final = "/live/track/set/name"
GET_DEVICE_NAMES: Final = "/live/track/get/devices/name"
GET_HAS_MIDI_INPUT: Final = "/live/track/get/has_midi_input"
# How long a setter Live applies on its next update may take to read back. Measured at
# one tick; this is five of AbletonOSC's ~100 ms round trips.
SETTLE_S: Final = 0.5
SETTLE_POLL_S: Final = 0.05

GET_LOOP: Final = "/live/song/get/loop"
SET_LOOP: Final = "/live/song/set/loop"
GET_TRACK_ARM: Final = "/live/track/get/arm"
SET_TRACK_ARM: Final = "/live/track/set/arm"
GET_METER_LEVEL: Final = "/live/track/get/output_meter_level"

FIRE_SCENE: Final = "/live/scene/fire"
FIRE_CLIP: Final = "/live/clip/fire"
STOP_TRACK: Final = "/live/track/stop_all_clips"
GET_CLIP_LEGATO: Final = "/live/clip/get/legato"
SET_CLIP_LEGATO: Final = "/live/clip/set/legato"

CREATE_CLIP: Final = "/live/clip_slot/create_clip"
DELETE_CLIP: Final = "/live/clip_slot/delete_clip"
GET_HAS_CLIP: Final = "/live/clip_slot/get/has_clip"
GET_CLIP_LENGTH: Final = "/live/clip/get/length"
ADD_NOTES: Final = "/live/clip/add/notes"
REMOVE_NOTES: Final = "/live/clip/remove/notes"
GET_NOTES: Final = "/live/clip/get/notes"

# `scripts/probe_live.py` walks exactly this tuple, so a version skew in AbletonOSC is
# found by one command rather than by an integration test failing for a reason nobody
# can see. Anything the adapter sends belongs here.
ALL_ADDRESSES: Final[tuple[str, ...]] = (
    TEST,
    VERSION,
    GET_TEMPO,
    SET_TEMPO,
    GET_SONG_TIME,
    GET_IS_PLAYING,
    START_PLAYING,
    STOP_PLAYING,
    GET_TRACK_NAMES,
    GET_NUM_SCENES,
    GET_QUANTIZATION,
    SET_QUANTIZATION,
    GET_LOOP,
    SET_LOOP,
    START_LISTEN_BEAT,
    STOP_LISTEN_BEAT,
    GET_BEAT,
    GET_TRACK_NAME,
    SET_TRACK_NAME,
    GET_DEVICE_NAMES,
    GET_HAS_MIDI_INPUT,
    GET_TRACK_ARM,
    SET_TRACK_ARM,
    GET_METER_LEVEL,
    FIRE_SCENE,
    FIRE_CLIP,
    STOP_TRACK,
    GET_CLIP_LEGATO,
    SET_CLIP_LEGATO,
    CREATE_CLIP,
    DELETE_CLIP,
    GET_HAS_CLIP,
    GET_CLIP_LENGTH,
    ADD_NOTES,
    REMOVE_NOTES,
    GET_NOTES,
)


def _note_difference(wanted: Sequence[MidiNote], seen: Sequence[MidiNote]) -> tuple[str, str]:
    """What to print when a write did not take. The first note that differs, if any.

    Counts alone are not enough and that is not hypothetical: Live silently shortens a
    note that overlaps the next attack of the same pitch, so the count matches, the
    contents do not, and "12 notes vs 12 notes" tells nobody anything
    (`phase-2-findings.md`).
    """
    if len(wanted) != len(seen):
        return f"{len(wanted)} notes", f"{len(seen)} notes"
    for mine, theirs in zip(wanted, seen, strict=True):
        if mine != theirs:
            return (
                f"pitch {mine.pitch} at {mine.start_beats:g} for {mine.duration_beats:g} "
                f"vel {mine.velocity}",
                f"pitch {theirs.pitch} at {theirs.start_beats:g} for "
                f"{theirs.duration_beats:g} vel {theirs.velocity}",
            )
    return f"{len(wanted)} notes", f"{len(seen)} notes"


def _beat_of(params: tuple[OscArg, ...]) -> int:
    """The beat number out of a pushed `/live/song/get/beat`.

    Live sends `int(current_song_time)`, so the value is absolute rather than a delta.
    That is what makes a lost datagram self-healing: the next one resyncs, and no counter
    has to be kept anywhere.
    """
    if not params:
        raise DawProtocolError(f"{GET_BEAT} arrived with no beat number")
    first = params[0]
    if not isinstance(first, int | float):
        raise DawProtocolError(f"{GET_BEAT} sent {type(first).__name__}, not a beat number")
    return int(first)


# pitch, start_time, duration, velocity, mute — AbletonOSC's flat note encoding.
NOTE_FIELDS: Final = 5

# `/live/clip/remove/notes` with these four arguments removes everything: every pitch,
# and a time span far wider than any clip. AbletonOSC's own default, made explicit.
ALL_PITCHES_ALL_TIME: Final[tuple[int, int, int, int]] = (0, 127, -8192, 16384)


# --------------------------------------------------------------------- wire payloads


def notes_payload(at: ClipAddress, notes: Sequence[MidiNote]) -> tuple[OscArg, ...]:
    """The arguments for `/live/clip/add/notes`: the address, then five per note.

    Public because the tests need to see exactly what would go over the wire, without
    a socket or Live.
    """
    flat: list[OscArg] = [at.track, at.scene]
    for note in notes:
        flat += [
            note.pitch,
            note.start_beats,
            note.duration_beats,
            note.velocity,
            note.mute,
        ]
    return tuple(flat)


def notes_from_reply(at: ClipAddress, reply: Sequence[OscArg]) -> tuple[MidiNote, ...]:
    """Parse `/live/clip/get/notes`: the echoed address, then five fields per note.

    Public, same reason. A reply that does not divide evenly is a `DawProtocolError`
    and not a shorter list of notes: silently dropping a remainder would arrive as a
    section that is quietly missing its last chord.
    """
    if len(reply) < 2:
        raise _bad_reply(GET_NOTES, f"expected at least the echoed address, got {reply!r}")
    track, scene, *rest = reply
    if (track, scene) != (at.track, at.scene):
        raise _wrong_index(GET_NOTES, at, reply)
    if len(rest) % NOTE_FIELDS:
        raise _bad_reply(
            GET_NOTES,
            f"{len(rest)} note fields is not a multiple of {NOTE_FIELDS} — "
            "the reply is truncated or the format changed",
        )
    return tuple(
        MidiNote(
            pitch=int(rest[offset]),
            start_beats=float(rest[offset + 1]),
            duration_beats=float(rest[offset + 2]),
            velocity=int(rest[offset + 3]),
            mute=bool(rest[offset + 4]),
        )
        for offset in range(0, len(rest), NOTE_FIELDS)
    )


class AbletonOSCAdapter:
    """`DawPort` over AbletonOSC. Synchronous, unretried, confirmed."""

    name = "abletonosc"

    def __init__(
        self,
        *,
        settings: OscSettings | None = None,
        transport: OscTransport | None = None,
    ) -> None:
        self._settings = settings or OscSettings()
        # Lazily real: a unit test injects a fake and never binds port 11001.
        self._transport = transport if transport is not None else UdpOscTransport(self._settings)

    @classmethod
    def from_env(cls, **kwargs: Any) -> AbletonOSCAdapter:  # noqa: ANN401 — passthrough
        """Build from `GARAGEM_LIVE_HOST`, defaulting to this machine."""
        host = os.environ.get("GARAGEM_LIVE_HOST")
        if host and "settings" not in kwargs:
            kwargs["settings"] = OscSettings(host=host)
        return cls(**kwargs)

    # -- lifecycle

    def warm(self) -> None:
        try:
            reply = self._transport.request(TEST, timeout_s=self._settings.warm_timeout_s)
        except DawTimeoutError as exc:
            # Re-raised as a timeout, not widened to `DawUnavailableError`: silence is
            # what a closed Live looks like, and the caller may want to say so. Other
            # `DawUnavailableError`s — a taken reply port, a refused send — already
            # carry their own instruction and would only be made wrong by this one.
            raise DawTimeoutError(
                f"Ableton Live did not answer {TEST}. Open the Set, then check that "
                "Settings -> Link/Tempo/MIDI -> Control Surface has AbletonOSC in some "
                "slot (the first free one — do not displace the MiniLab 3) "
                "— and that Live was restarted completely after it was installed. "
                f"{exc}"
            ) from exc
        if reply != ("ok",):
            raise _bad_reply(TEST, f"expected ('ok',), got {reply!r}")

    @property
    def transport(self) -> OscTransport:
        """The seam, for the caller that needs its counters.

        On `AbletonOSCAdapter` and deliberately not on `DawPort`: `dropped` is a fact
        about a socket, and a port that exposed it would be a port that knows it has one.
        The live suite reads it to prove a two-second write did not starve the beat
        listener (ADR-014).
        """
        return self._transport

    def close(self) -> None:
        self._transport.close()

    # ----------------------------------------------------------------- the beat listener

    def listen_beats(self, handler: BeatHandler) -> None:
        """Ask Live to push every beat, and route it to `handler`.

        `send`, not `request`: AbletonOSC answers `start_listen/beat` at GET_BEAT, not at
        the address that was called, so a request would wait for a reply that is never
        coming and time out on a call that worked.

        `handler` runs on the receive thread and must do no musical work (ADR-014).
        """
        self._transport.listen(GET_BEAT, lambda params: handler(_beat_of(params)))
        self._transport.send(START_LISTEN_BEAT)

    def unlisten_beats(self) -> None:
        self._transport.send(STOP_LISTEN_BEAT)
        self._transport.unlisten(GET_BEAT)

    # -- transport and global state

    def tempo(self) -> float:
        return float(self._one(GET_TEMPO))

    def set_tempo(self, bpm: float) -> None:
        self._transport.send(SET_TEMPO, bpm)
        if not math.isclose(self.tempo(), bpm, rel_tol=0.0, abs_tol=1e-3):
            raise _unconfirmed(SET_TEMPO, bpm, self.tempo())

    def song_time_beats(self) -> float:
        return float(self._one(GET_SONG_TIME))

    def is_playing(self) -> bool:
        return bool(self._one(GET_IS_PLAYING))

    def start_playing(self) -> None:
        # Not confirmed by a read: see the module docstring and ADR-001.
        self._transport.send(START_PLAYING)

    def stop_playing(self) -> None:
        self._transport.send(STOP_PLAYING)

    def quantization(self) -> Quantization:
        code = int(self._one(GET_QUANTIZATION))
        if code not in QUANTIZATION_BY_CODE:
            raise _bad_reply(
                GET_QUANTIZATION,
                f"Live reports quantisation code {code}, which is not one this port "
                "knows. Run scripts/probe_live.py: the LOM enum may have been reordered.",
            )
        return QUANTIZATION_BY_CODE[code]

    def set_quantization(self, quantization: Quantization) -> None:
        self._transport.send(SET_QUANTIZATION, QUANTIZATION_CODES[quantization])
        if (seen := self.quantization()) is not quantization:
            raise _unconfirmed(SET_QUANTIZATION, quantization, seen)

    # -- the Set's shape

    def song_loop(self) -> bool:
        return bool(self._one(GET_LOOP))

    def set_song_loop(self, on: bool) -> None:
        """Set the loop switch, and confirm it by *reading* until Live has applied it.

        Unlike the tempo or a track name, Live applies `song.loop` on its next update, not
        inside the handler: on 2026-09-12 the confirming read in the same tick answered
        `True` 0.1 ms after the write, and `False` a moment later. So the read is repeated
        for up to `SETTLE_S`. The write is sent once and never again — nothing here retries
        a write, which is what P7 forbids.
        """
        self._transport.send(SET_LOOP, on)
        deadline = time.monotonic() + SETTLE_S
        while (seen := self.song_loop()) != on:
            if time.monotonic() >= deadline:
                raise _unconfirmed(SET_LOOP, on, seen)
            time.sleep(SETTLE_POLL_S)

    def track_names(self) -> tuple[str, ...]:
        return tuple(str(name) for name in self._transport.request(GET_TRACK_NAMES))

    def set_track_name(self, track: int, name: str) -> None:
        self._transport.send(SET_TRACK_NAME, track, name)
        if (seen := self.track_names()[track]) != name:
            raise _unconfirmed(SET_TRACK_NAME, name, seen)

    def device_names(self, track: int) -> tuple[str, ...]:
        reply = self._transport.request(GET_DEVICE_NAMES, track)
        return tuple(str(name) for name in self._after_index(GET_DEVICE_NAMES, track, reply))

    def accepts_midi(self, track: int) -> bool:
        reply = self._transport.request(GET_HAS_MIDI_INPUT, track)
        return bool(self._after_index(GET_HAS_MIDI_INPUT, track, reply)[0])

    def track_armed(self, track: int) -> bool:
        reply = self._transport.request(GET_TRACK_ARM, track)
        return bool(self._after_index(GET_TRACK_ARM, track, reply)[0])

    def set_track_armed(self, track: int, armed: bool) -> None:
        self._transport.send(SET_TRACK_ARM, track, armed)
        if (seen := self.track_armed(track)) != armed:
            raise _unconfirmed(SET_TRACK_ARM, armed, seen)

    def scene_count(self) -> int:
        return int(self._one(GET_NUM_SCENES))

    def meter_level(self, track: int) -> float:
        """Output level, 0.0 to 1.0. Not on the port — evidence, not a control.

        The Phase 1 exit criterion says audio comes out. Nothing in Python can hear a
        speaker, but this says MIDI reached an instrument and the instrument produced
        signal, which is the whole chain minus the last centimetre. The scheduler has
        no use for it, so it does not belong on `DawPort`.
        """
        reply = self._transport.request(GET_METER_LEVEL, track)
        return float(self._after_index(GET_METER_LEVEL, track, reply)[0])

    # -- clips

    def has_clip(self, at: ClipAddress) -> bool:
        return bool(self._clip_reply(GET_HAS_CLIP, at)[0])

    def clip_length_beats(self, at: ClipAddress) -> float:
        return float(self._clip_reply(GET_CLIP_LENGTH, at)[0])

    def create_clip(self, at: ClipAddress, length_beats: float) -> None:
        self._transport.send(CREATE_CLIP, at.track, at.scene, length_beats)
        if not self.has_clip(at):
            raise _unconfirmed(CREATE_CLIP, f"a clip at {at.track}/{at.scene}", "an empty slot")

    def delete_clip(self, at: ClipAddress) -> None:
        self._transport.send(DELETE_CLIP, at.track, at.scene)
        if self.has_clip(at):
            raise _unconfirmed(DELETE_CLIP, "an empty slot", f"a clip at {at.track}/{at.scene}")

    def read_notes(self, at: ClipAddress) -> tuple[MidiNote, ...]:
        return normalised(
            notes_from_reply(at, self._transport.request(GET_NOTES, at.track, at.scene))
        )

    def write_notes(self, at: ClipAddress, notes: Iterable[MidiNote]) -> None:
        """Replace: remove everything, add the new notes, then read back and compare.

        `/live/clip/add/notes` *appends*. Writing a section twice without the removal
        would double every note, and the Set would still look plausible.
        """
        wanted = normalised(notes)
        self._transport.send(REMOVE_NOTES, at.track, at.scene, *ALL_PITCHES_ALL_TIME)
        self._transport.send(ADD_NOTES, *notes_payload(at, wanted))
        if (seen := self.read_notes(at)) != wanted:
            raise _unconfirmed(ADD_NOTES, *_note_difference(wanted, seen))

    def fire_scene(self, scene: int) -> None:
        # Deliberately not confirmed: at `1 Bar` the launch is up to 1.82 s away, so a
        # read now would only prove the packet was slow. ADR-001.
        self._transport.send(FIRE_SCENE, scene)

    def fire_clip(self, at: ClipAddress) -> None:
        # Unconfirmed, like a scene fire, and a bar cue cannot afford the read anyway: a
        # request is a fifth of a beat (`phase-4-findings.md` §7).
        self._transport.send(FIRE_CLIP, at.track, at.scene)

    def stop_track(self, track: int) -> None:
        self._transport.send(STOP_TRACK, track)

    def clip_legato(self, at: ClipAddress) -> bool:
        return bool(self._clip_reply(GET_CLIP_LEGATO, at)[0])

    def set_clip_legato(self, at: ClipAddress, on: bool) -> None:
        self._transport.send(SET_CLIP_LEGATO, at.track, at.scene, on)
        if (seen := self.clip_legato(at)) != on:
            raise _unconfirmed(SET_CLIP_LEGATO, on, seen)

    # -- internals

    def _one(self, address: str) -> OscArg:
        reply = self._transport.request(address)
        if len(reply) != 1:
            raise _bad_reply(address, f"expected one value, got {reply!r}")
        return reply[0]

    def _after_index(self, address: str, index: int, reply: Sequence[OscArg]) -> tuple[OscArg, ...]:
        """Track and clip getters echo their index back; drop it, after checking it."""
        if not reply:
            raise _bad_reply(address, "empty reply")
        if reply[0] != index:
            raise _bad_reply(address, f"asked about index {index}, got {reply[0]!r}")
        return tuple(reply[1:])

    def _clip_reply(self, address: str, at: ClipAddress) -> tuple[OscArg, ...]:
        reply = self._transport.request(address, at.track, at.scene)
        if len(reply) < 3:
            raise _bad_reply(address, f"expected the echoed address and a value, got {reply!r}")
        if (reply[0], reply[1]) != (at.track, at.scene):
            raise _wrong_index(address, at, reply)
        return tuple(reply[2:])


# ------------------------------------------------------------- failure classification


def _unconfirmed(address: str, wanted: object, seen: object) -> DawWriteNotConfirmedError:
    return DawWriteNotConfirmedError(
        f"{address} did not take: asked for {wanted!r}, Live still reports {seen!r}. "
        "OSC setters are unacknowledged, so this is what a lost or refused write looks "
        f"like. The log says which: {LOG_PATH}"
    )


def _bad_reply(address: str, detail: str) -> DawProtocolError:
    return DawProtocolError(f"{address} replied with something unexpected: {detail}")


def _wrong_index(address: str, at: ClipAddress, reply: Sequence[OscArg]) -> DawProtocolError:
    return DawProtocolError(
        f"{address} answered about clip {reply[0]!r}/{reply[1]!r}, not {at.track}/{at.scene}. "
        "A reply was correlated to the wrong request."
    )
