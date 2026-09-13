"""`FakeDawAdapter` and `FakeOscTransport` — a Live Set that fits in a dictionary.

Three purposes, which is what the parameters are for:

1. **Standing in for Live in the default suite.** `.claude/rules/daw-integration.md`:
   "Every change here needs an equivalent in `FakeDawAdapter`, so that the main suite
   keeps running without Live." Everything in Phase 1 except the last centimetre —
   whether a speaker moves — is provable against this.
2. **Reproducing Live's *surprising* behaviours.** A fake that is merely convenient
   lets real bugs through. The three that matter are marked in the code: creating a
   clip on an occupied slot fails, `add/notes` appends rather than replaces, and notes
   come back in Live's order rather than the order they were written.
3. **Injecting failure** (`fail_with` / `fail_after`), the same way `FakeProvider` does,
   so the degradation path can be exercised without closing Ableton.

It never sleeps, never touches the clock and does no I/O.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from garagem.daw.errors import DawError, DawTimeoutError
from garagem.daw.osc import OscArg, OscListener
from garagem.daw.port import BeatHandler, ClipAddress, MidiNote, Quantization, normalised

DEFAULT_TRACKS: tuple[str, ...] = ("DRUMS", "BASS", "GTR", "KEYS")
DEFAULT_DEVICE: str = "Drift"


@dataclass
class _Clip:
    length_beats: float
    notes: tuple[MidiNote, ...] = ()
    legato: bool = False


class FakeDawAdapter:
    """A `DawPort` backed by dictionaries. Deterministic, instant, offline."""

    name = "fake"

    def __init__(
        self,
        *,
        track_names: Sequence[str] = DEFAULT_TRACKS,
        device_names: Sequence[Sequence[str]] | None = None,
        midi_tracks: Sequence[bool] | None = None,
        armed: Sequence[bool] | None = None,
        scenes: int = 2,
        tempo_bpm: float = 120.0,
        quantization: Quantization = Quantization.BAR,
        loop: bool = False,
        fail_with: Exception | None = None,
        fail_after: int = 0,
    ) -> None:
        self._track_names = list(track_names)
        self._device_names = (
            [tuple(names) for names in device_names]
            if device_names is not None
            else [(DEFAULT_DEVICE,) for _ in self._track_names]
        )
        self._midi_tracks = (
            list(midi_tracks) if midi_tracks is not None else [True] * len(self._track_names)
        )
        self._armed = list(armed) if armed is not None else [False] * len(self._track_names)
        self._scenes = scenes
        self._tempo_bpm = tempo_bpm
        self._quantization = quantization
        self._loop = loop
        self._playing = False
        self._beat_handler: BeatHandler | None = None
        self._clips: dict[tuple[int, int], _Clip] = {}
        self._fail_with = fail_with
        self._fail_after = fail_after
        # Method names in order, mirroring `FakeProvider.calls`. This is what makes
        # idempotence machine-checkable: a second `apply_session` must record no
        # `set_*` call at all, which is a stronger claim than "the Set looks the same".
        self.calls: list[str] = []
        # Clip fires and track stops, in order, as a test would want to read them back.
        self.fired_clips: list[ClipAddress] = []
        self.stopped_tracks: list[int] = []
        self.fired: list[int] = []
        # A plain attribute, so a test can move the playhead without a clock.
        self.song_position_beats: float = 0.0

    # -- lifecycle

    def warm(self) -> None:
        self._record("warm")

    def listen_beats(self, handler: BeatHandler) -> None:
        self._record("listen_beats")
        self._beat_handler = handler

    def unlisten_beats(self) -> None:
        # Outside the failure injection, for the same reason as `close`: it runs in
        # teardown, and a raise there hides whatever actually went wrong.
        self.calls.append("unlisten_beats")
        self._beat_handler = None

    def push_beat(self, beat: int) -> None:
        """Live reaching the given beat. The whole of musical time, on demand.

        Synchronous and on the caller's thread, which is what lets the scheduler be
        driven through three minutes of music in a unit test with no clock and no
        sleeping. A test that slept would be testing the machine it runs on.
        """
        self.song_position_beats = float(beat)
        if self._beat_handler is not None:
            self._beat_handler(beat)

    def close(self) -> None:
        # Deliberately outside the failure injection: teardown runs in a `finally`, and
        # a close() that raises there masks whatever actually went wrong.
        self.calls.append("close")

    # -- transport and global state

    def tempo(self) -> float:
        self._record("tempo")
        return self._tempo_bpm

    def set_tempo(self, bpm: float) -> None:
        self._record("set_tempo")
        self._tempo_bpm = bpm

    def song_time_beats(self) -> float:
        self._record("song_time_beats")
        return self.song_position_beats

    def is_playing(self) -> bool:
        self._record("is_playing")
        return self._playing

    def start_playing(self) -> None:
        self._record("start_playing")
        self._playing = True

    def stop_playing(self) -> None:
        self._record("stop_playing")
        self._playing = False

    def quantization(self) -> Quantization:
        self._record("quantization")
        return self._quantization

    def set_quantization(self, quantization: Quantization) -> None:
        self._record("set_quantization")
        self._quantization = quantization

    # -- the Set's shape

    def song_loop(self) -> bool:
        self._record("song_loop")
        return self._loop

    def set_song_loop(self, on: bool) -> None:
        self._record("set_song_loop")
        self._loop = on

    def track_names(self) -> tuple[str, ...]:
        self._record("track_names")
        return tuple(self._track_names)

    def set_track_name(self, track: int, name: str) -> None:
        self._record("set_track_name")
        self._track(track)
        self._track_names[track] = name

    def device_names(self, track: int) -> tuple[str, ...]:
        self._record("device_names")
        self._track(track)
        return tuple(self._device_names[track])

    def accepts_midi(self, track: int) -> bool:
        self._record("accepts_midi")
        self._track(track)
        return self._midi_tracks[track]

    def track_armed(self, track: int) -> bool:
        self._record("track_armed")
        self._track(track)
        return self._armed[track]

    def set_track_armed(self, track: int, armed: bool) -> None:
        self._record("set_track_armed")
        self._track(track)
        self._armed[track] = armed

    def scene_count(self) -> int:
        self._record("scene_count")
        return self._scenes

    # -- clips

    def has_clip(self, at: ClipAddress) -> bool:
        self._record("has_clip")
        return self._key(at) in self._clips

    def clip_length_beats(self, at: ClipAddress) -> float:
        self._record("clip_length_beats")
        return self._clip(at).length_beats

    def create_clip(self, at: ClipAddress, length_beats: float) -> None:
        self._record("create_clip")
        key = self._key(at)
        # Live refuses this outright rather than replacing the clip. A fake that
        # overwrote would hide the bug until the Set had two sections in one slot.
        if key in self._clips:
            raise DawError(f"clip slot {at.track}/{at.scene} already holds a clip")
        self._clips[key] = _Clip(length_beats=length_beats)

    def delete_clip(self, at: ClipAddress) -> None:
        self._record("delete_clip")
        del self._clips[self._key(at)]

    def read_notes(self, at: ClipAddress) -> tuple[MidiNote, ...]:
        self._record("read_notes")
        # Live returns notes in its own order, so callers must not depend on the order
        # they were written in. Normalising here is what makes that impossible to rely on.
        return normalised(self._clip(at).notes)

    def write_notes(self, at: ClipAddress, notes: Iterable[MidiNote]) -> None:
        self._record("write_notes")
        # A *replace*, matching the adapter's remove-then-add. `/live/clip/add/notes`
        # appends, so a fake that appended here would let a doubled section through.
        self._clip(at).notes = normalised(notes)

    def fire_scene(self, scene: int) -> None:
        self._record("fire_scene")
        if not 0 <= scene < self._scenes:
            raise DawError(f"scene {scene} does not exist (the Set has {self._scenes})")
        self.fired.append(scene)
        self._playing = True

    def fire_clip(self, at: ClipAddress) -> None:
        self._record("fire_clip")
        self._clip(at)
        self.fired_clips.append(at)
        self._playing = True

    def stop_track(self, track: int) -> None:
        self._record("stop_track")
        self._track(track)
        self.stopped_tracks.append(track)

    def clip_legato(self, at: ClipAddress) -> bool:
        self._record("clip_legato")
        return self._clip(at).legato

    def set_clip_legato(self, at: ClipAddress, on: bool) -> None:
        self._record("set_clip_legato")
        self._clip(at).legato = on

    # -- internals

    def _record(self, method: str) -> None:
        if self._fail_with is not None and len(self.calls) >= self._fail_after:
            self.calls.append(method)
            raise self._fail_with
        self.calls.append(method)

    def _key(self, at: ClipAddress) -> tuple[int, int]:
        self._track(at.track)
        if not 0 <= at.scene < self._scenes:
            raise DawError(f"scene {at.scene} does not exist (the Set has {self._scenes})")
        return (at.track, at.scene)

    def _track(self, track: int) -> None:
        if not 0 <= track < len(self._track_names):
            raise DawError(f"track {track} does not exist (the Set has {len(self._track_names)})")

    def _clip(self, at: ClipAddress) -> _Clip:
        key = self._key(at)
        if key not in self._clips:
            raise DawError(f"clip slot {at.track}/{at.scene} is empty")
        return self._clips[key]


# A handler returning None means "Live said nothing" — which is the only failure
# AbletonOSC can actually express (see `osc.py`).
OscHandler = Callable[[str, tuple[OscArg, ...]], Sequence[OscArg] | None]


@dataclass
class FakeOscTransport:
    """An `OscTransport` driven by a handler, the way `httpx.MockTransport` is.

    Lets the *real* `AbletonOSCAdapter` be tested end to end — its wire payloads, its
    confirming reads, its failure classification — with no socket and no Live.
    """

    handler: OscHandler
    sent: list[tuple[str, tuple[OscArg, ...]]] = field(default_factory=list)
    listeners: dict[str, OscListener] = field(default_factory=dict)
    closed: bool = False
    dropped: int = 0

    def send(self, address: str, *args: OscArg) -> None:
        self.sent.append((address, args))
        self.handler(address, args)

    def request(
        self, address: str, *args: OscArg, timeout_s: float | None = None
    ) -> tuple[OscArg, ...]:
        self.sent.append((address, args))
        reply = self.handler(address, args)
        if reply is None:
            # Silence, immediately: the fake must never actually wait out a deadline.
            raise DawTimeoutError(f"no reply to {address} (fake): Live said nothing")
        return tuple(reply)

    def listen(self, address: str, handler: OscListener) -> None:
        self.listeners[address] = handler

    def unlisten(self, address: str) -> None:
        self.listeners.pop(address, None)

    def deliver(self, address: str, *args: OscArg) -> None:
        """Push an unsolicited message, the way Live pushes a beat.

        Without this the fake could no longer reproduce Live, and the moment the offline
        suite stops being able to do that it stops being evidence for anything. Delivery
        is synchronous and on the caller's thread: a test drives musical time by calling
        this, and never by sleeping.
        """
        listener = self.listeners.get(address)
        if listener is None:
            self.dropped += 1
            return
        listener(args)

    def close(self) -> None:
        self.closed = True
