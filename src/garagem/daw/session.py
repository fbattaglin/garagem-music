"""\"Set as Code\": what the Live Set should be, what it is, and the difference.

ADR-013. `session.toml` describes the Set; this module reads it, observes the open Set
through a `DawPort`, and reports every divergence. It repairs only what the Live API can
repair safely — tempo, launch quantisation, the loop switch, track names and arm. A
missing track or a track with no instrument is the human's job: no LOM call loads an
instrument, so a track created from code would receive MIDI correctly and make no sound.

The split into `observe` -> `diff_session` -> `apply_session` is what makes almost all
of the bootstrap testable with Ableton closed: `diff_session` is pure, and the two
around it are thin. `apply_session` is idempotent **by construction** rather than by
inspection — it observes, writes only what diverged, observes again, and returns what is
left. Run it twice and the second pass finds nothing fixable, so it issues no writes at
all. That is the Phase 1 idempotence criterion, provable against `FakeDawAdapter`.

This module takes a `DawPort`. It knows nothing about OSC, sockets or AbletonOSC.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from garagem.daw.errors import SessionSpecError
from garagem.daw.port import ClipAddress, DawPort, Quantization

SCHEMA: Final = 1
# Ableton Live 12 Lite. ADR-013.
LITE_TRACK_LIMIT: Final = 8
# ADR-001 alternates scenes: with one, there is nowhere to write that is not playing.
MIN_SCENES: Final = 2
TEMPO_RANGE: Final[tuple[float, float]] = (20.0, 999.0)

KINDS: Final[tuple[str, ...]] = (
    "tempo",
    "quantization",
    "track_name",
    "missing_track",
    "extra_track",
    "missing_scene",
    "no_instrument",
    "not_a_midi_track",
    "armed",
    "loop",
    "wrong_instrument",
    "volume",
    "pan",
    "send",
)
# The ones the LOM can repair. Everything else is a human's job (ADR-013).
MAX_MIDI_NOTE: Final = 127

FIXABLE_KINDS: Final[frozenset[str]] = frozenset(
    {"tempo", "quantization", "track_name", "armed", "loop", "volume", "pan", "send"}
)
# A fader is a 32-bit float on the wire (`abletonosc.MIX_TOLERANCE`), and a mix this close
# is the same mix to any ear.
MIX_TOLERANCE: Final = 1e-3


@dataclass(frozen=True, slots=True)
class TrackSpec:
    index: int
    name: str
    role: str
    # What the human loads, since the API cannot (ADR-013). Checked by name since ADR-028:
    # some device on the track must be called this, or start with it ("Analog Lab" matches
    # "Analog Lab V"). The kit drifted from Dry Session to Gen Purpose unnoticed while the check
    # was only that *some* device was present. Empty means any instrument will do.
    instrument: str
    # `None` means the Set may have it either way. The band's tracks declare `false`: an
    # armed MIDI track plays whatever the MiniLab sends, cue pads included (ADR-022).
    armed: bool | None = None
    # Which note this Set's instrument answers to, for a note the band writes. A sampled
    # kit lays its pieces out where its maker put them, and that is a property of the Set
    # rather than of the music: `theory/percussion.py` stays the band's own vocabulary, and
    # this table says where this kit keeps it. Empty means the two already agree.
    pitches: tuple[tuple[int, int], ...] = ()
    # The mix, as Live stores it (ADR-028): the fader 0.0-1.0 where 0.85 is 0 dB, the pan
    # -1.0 (left) to 1.0, and one level per return track. `None` means the Set may have any.
    volume: float | None = None
    pan: float | None = None
    sends: tuple[float, ...] | None = None
    # The velocity below which this Set's guitar plays a palm mute. A sampler that picks its
    # articulation by velocity needs the band's muted notes and its ringing ones never to
    # cross; `transport/render.py` keeps them apart. `None`: the instrument does not care.
    palm_mute_below: int | None = None


@dataclass(frozen=True, slots=True)
class SceneSpec:
    index: int
    name: str


@dataclass(frozen=True, slots=True)
class SessionSpec:
    name: str
    tempo_bpm: float
    quantization: Quantization
    tracks: tuple[TrackSpec, ...]
    scenes: tuple[SceneSpec, ...]
    # `None` means either. `false` for a jam: the `BarClock` counts bars from the song
    # position, and an arrangement loop sends it back before the next section's bar.
    loop: bool | None = None


@dataclass(frozen=True, slots=True)
class ObservedSet:
    """One snapshot of the open Set — enough to diff, and no more."""

    tempo_bpm: float
    quantization: Quantization
    track_names: tuple[str, ...]
    device_names: tuple[tuple[str, ...], ...]
    accepts_midi: tuple[bool, ...]
    scene_count: int
    armed: tuple[bool, ...] = ()
    loop: bool | None = None
    # Per track, read only when the spec declares a mix (ADR-028).
    volumes: tuple[float, ...] = ()
    pans: tuple[float, ...] = ()
    sends: tuple[tuple[float, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class Divergence:
    kind: str
    detail: str
    # False means no LOM call can fix it, so nothing will try.
    fixable: bool
    # Which track, when the divergence is about one. Carried as data rather than read
    # back out of `detail`: the message is for a human and is free to change wording.
    track: int | None = None


def load_session(path: Path) -> SessionSpec:
    """Read and validate `session.toml`. Every refusal names the file and the value."""
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))

    if raw.get("schema") != SCHEMA:
        raise SessionSpecError(f"{path}: schema must be {SCHEMA}, got {raw.get('schema')!r}")

    tempo = float(raw.get("tempo_bpm", 0.0))
    low, high = TEMPO_RANGE
    if not low <= tempo <= high:
        raise SessionSpecError(f"{path}: tempo_bpm {tempo} is outside {low}-{high}")

    quantization = raw.get("quantization", "")
    try:
        quantum = Quantization(quantization)
    except ValueError as exc:
        known = ", ".join(q.value for q in Quantization)
        raise SessionSpecError(
            f"{path}: unknown quantization {quantization!r}. Known: {known}"
        ) from exc

    loop = raw.get("loop")
    if loop is not None and not isinstance(loop, bool):
        raise SessionSpecError(f"{path}: loop must be true or false, got {loop!r}")

    tracks = _tracks(path, raw.get("track", []))
    scenes = _scenes(path, raw.get("scene", []))
    return SessionSpec(
        name=str(raw.get("name", path.stem)),
        tempo_bpm=tempo,
        quantization=quantum,
        tracks=tracks,
        scenes=scenes,
        loop=loop,
    )


def _pitches(path: Path, entry: dict[str, Any]) -> tuple[tuple[int, int], ...]:
    """`pitches = { 50 = 47 }`: the band writes 50, this Set's instrument is sent 47."""
    raw = entry.get("pitches", {})
    if not isinstance(raw, dict):
        raise SessionSpecError(f"{path}: track {entry.get('index')}: pitches must be a table")
    pairs: list[tuple[int, int]] = []
    for key, value in raw.items():
        try:
            written, played = int(key), int(value)
        except (TypeError, ValueError) as exc:
            raise SessionSpecError(
                f"{path}: track {entry.get('index')}: pitches {key!r} = {value!r} is not two notes"
            ) from exc
        if not (0 <= written <= MAX_MIDI_NOTE and 0 <= played <= MAX_MIDI_NOTE):
            raise SessionSpecError(
                f"{path}: track {entry.get('index')}: pitches {written} = {played} is outside "
                f"0..{MAX_MIDI_NOTE}"
            )
        pairs.append((written, played))
    return tuple(pairs)


def _tracks(path: Path, entries: Sequence[dict[str, Any]]) -> tuple[TrackSpec, ...]:
    if not entries:
        raise SessionSpecError(f"{path}: declares no [[track]]")
    if len(entries) > LITE_TRACK_LIMIT:
        raise SessionSpecError(
            f"{path}: {len(entries)} tracks, but Ableton Live 12 Lite caps a Set at "
            f"{LITE_TRACK_LIMIT} (ADR-013)"
        )
    tracks = tuple(
        TrackSpec(
            index=int(entry["index"]),
            name=str(entry["name"]),
            role=str(entry.get("role", "")),
            instrument=str(entry.get("instrument", "")),
            armed=_armed(path, entry),
            pitches=_pitches(path, entry),
            volume=_level(path, entry, "volume", 0.0, 1.0),
            pan=_level(path, entry, "pan", -1.0, 1.0),
            sends=_sends(path, entry),
            palm_mute_below=_palm(path, entry),
        )
        for entry in entries
    )
    _contiguous(path, "track", [track.index for track in tracks])

    names = [track.name for track in tracks]
    if any(not name.strip() for name in names):
        raise SessionSpecError(f"{path}: a track has an empty name")
    if len(set(names)) != len(names):
        raise SessionSpecError(f"{path}: duplicate track names in {names}")
    return tracks


def _level(path: Path, entry: dict[str, Any], key: str, low: float, high: float) -> float | None:
    if key not in entry:
        return None
    value = entry[key]
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise SessionSpecError(
            f"{path}: track {entry.get('index')} {key} must be a number in {low}..{high}, "
            f"got {value!r}"
        )
    return float(value)


def _sends(path: Path, entry: dict[str, Any]) -> tuple[float, ...] | None:
    if "sends" not in entry:
        return None
    raw = entry["sends"]
    if not isinstance(raw, list):
        raise SessionSpecError(f"{path}: track {entry.get('index')} sends must be a list")
    return tuple(
        _level(path, {"index": entry.get("index"), "send": level}, "send", 0.0, 1.0) or 0.0
        for level in raw
    )


def _palm(path: Path, entry: dict[str, Any]) -> int | None:
    if "palm_mute_below" not in entry:
        return None
    value = entry["palm_mute_below"]
    if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= MAX_MIDI_NOTE:
        raise SessionSpecError(
            f"{path}: track {entry.get('index')} palm_mute_below must be a velocity in "
            f"2..{MAX_MIDI_NOTE}, got {value!r}"
        )
    return value


def _armed(path: Path, entry: dict[str, Any]) -> bool | None:
    """`true`, `false` or absent. A quoted `"false"` is refused: it is truthy in Python."""
    if "armed" not in entry:
        return None
    value = entry["armed"]
    if not isinstance(value, bool):
        raise SessionSpecError(
            f"{path}: track {entry.get('index')} armed must be true or false, got {value!r}"
        )
    return value


def _scenes(path: Path, entries: Sequence[dict[str, Any]]) -> tuple[SceneSpec, ...]:
    if len(entries) < MIN_SCENES:
        raise SessionSpecError(
            f"{path}: {len(entries)} [[scene]], but ADR-001 writes into the scene that is "
            f"not playing, so at least {MIN_SCENES} are needed"
        )
    scenes = tuple(
        SceneSpec(index=int(entry["index"]), name=str(entry.get("name", ""))) for entry in entries
    )
    _contiguous(path, "scene", [scene.index for scene in scenes])
    return scenes


def _contiguous(path: Path, kind: str, indices: Sequence[int]) -> None:
    if sorted(indices) != list(range(len(indices))):
        raise SessionSpecError(
            f"{path}: {kind} indices must be 0..{len(indices) - 1}, got {sorted(indices)}"
        )


def observe(daw: DawPort, spec: SessionSpec | None = None) -> ObservedSet:
    """One snapshot of the open Set, in the shape `diff_session` needs.

    The mix is read only when `spec` declares one, and only as many sends as it names: a
    Set checked against a spec with no mix costs no more requests than it ever did.
    """
    names = daw.track_names()
    volumes, pans, sends = _mix(daw, spec, len(names)) if spec is not None else ((), (), ())
    return ObservedSet(
        tempo_bpm=daw.tempo(),
        quantization=daw.quantization(),
        track_names=names,
        device_names=tuple(daw.device_names(index) for index in range(len(names))),
        accepts_midi=tuple(daw.accepts_midi(index) for index in range(len(names))),
        scene_count=daw.scene_count(),
        armed=tuple(daw.track_armed(index) for index in range(len(names))),
        loop=daw.song_loop(),
        volumes=volumes,
        pans=pans,
        sends=sends,
    )


def _mix(
    daw: DawPort, spec: SessionSpec, count: int
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[tuple[float, ...], ...]]:
    declared = [t for t in spec.tracks if t.volume is not None or t.pan is not None or t.sends]
    if not declared:
        return (), (), ()
    returns = max((len(track.sends or ()) for track in spec.tracks), default=0)
    volumes = tuple(daw.track_volume(index) for index in range(count))
    pans = tuple(daw.track_pan(index) for index in range(count))
    sends = tuple(
        tuple(daw.track_send(index, send) for send in range(returns)) for index in range(count)
    )
    return volumes, pans, sends


def diff_session(spec: SessionSpec, observed: ObservedSet) -> tuple[Divergence, ...]:
    """Pure: what is different, and whether anything can be done about it from here."""
    found: list[Divergence] = []

    if abs(observed.tempo_bpm - spec.tempo_bpm) > 1e-3:
        found.append(
            Divergence("tempo", f"{observed.tempo_bpm} BPM, expected {spec.tempo_bpm}", True)
        )
    if observed.quantization is not spec.quantization:
        found.append(
            Divergence(
                "quantization",
                f"{observed.quantization.value}, expected {spec.quantization.value}",
                True,
            )
        )
    if spec.loop is not None and observed.loop is not None and observed.loop != spec.loop:
        found.append(
            Divergence(
                "loop",
                f"the arrangement loop is {'on' if observed.loop else 'off'}, "
                f"expected {'on' if spec.loop else 'off'}",
                True,
            )
        )

    for track in spec.tracks:
        if track.index >= len(observed.track_names):
            found.append(
                Divergence(
                    "missing_track",
                    f"track {track.index} ({track.name}) does not exist; "
                    f"it wants {track.instrument!r}",
                    False,
                    track=track.index,
                )
            )
            continue
        if not observed.accepts_midi[track.index]:
            # Renaming it would make the Set look right and guarantee silence: an audio
            # track holds no MIDI clip and takes no instrument. Same trap as ADR-013's
            # refusal to create tracks, so the same answer — tell the human.
            found.append(
                Divergence(
                    "not_a_midi_track",
                    f"track {track.index} is an audio track, but {track.name} needs MIDI",
                    False,
                    track=track.index,
                )
            )
            continue

        seen = observed.track_names[track.index]
        if seen != track.name:
            found.append(
                Divergence(
                    "track_name",
                    f"track {track.index} is {seen!r}, expected {track.name!r}",
                    True,
                    track=track.index,
                )
            )
        if (
            track.armed is not None
            and track.index < len(observed.armed)
            and observed.armed[track.index] != track.armed
        ):
            state = "armed" if observed.armed[track.index] else "disarmed"
            found.append(
                Divergence(
                    "armed",
                    f"track {track.index} ({track.name}) is {state}, expected "
                    f"{'armed' if track.armed else 'disarmed'}",
                    True,
                    track=track.index,
                )
            )
        devices = observed.device_names[track.index]
        if not devices:
            found.append(
                Divergence(
                    "no_instrument",
                    f"track {track.index} ({track.name}) carries no device, so it will be "
                    f"silent; it wants {track.instrument!r}",
                    False,
                    track=track.index,
                )
            )
        elif track.instrument and not _carries(devices, track.instrument):
            found.append(
                Divergence(
                    "wrong_instrument",
                    f"track {track.index} ({track.name}) carries {list(devices)}, "
                    f"but it wants {track.instrument!r}",
                    False,
                    track=track.index,
                )
            )
        found.extend(_mix_divergences(track, observed))

    if len(observed.track_names) > len(spec.tracks):
        extra = observed.track_names[len(spec.tracks) :]
        found.append(Divergence("extra_track", f"the Set has extra tracks: {list(extra)}", False))

    if observed.scene_count < len(spec.scenes):
        found.append(
            Divergence(
                "missing_scene",
                f"{observed.scene_count} scenes, expected at least {len(spec.scenes)}",
                False,
            )
        )
    return tuple(found)


def _carries(devices: Sequence[str], instrument: str) -> bool:
    wanted = instrument.casefold()
    return any(device.casefold().startswith(wanted) for device in devices)


def _mix_divergences(track: TrackSpec, observed: ObservedSet) -> list[Divergence]:
    found: list[Divergence] = []
    where = f"track {track.index} ({track.name})"
    if track.volume is not None and track.index < len(observed.volumes):
        seen = observed.volumes[track.index]
        if abs(seen - track.volume) > MIX_TOLERANCE:
            found.append(
                Divergence(
                    "volume",
                    f"{where} fader is {seen:.3f}, expected {track.volume:.3f}",
                    True,
                    track=track.index,
                )
            )
    if track.pan is not None and track.index < len(observed.pans):
        seen = observed.pans[track.index]
        if abs(seen - track.pan) > MIX_TOLERANCE:
            found.append(
                Divergence(
                    "pan",
                    f"{where} pan is {seen:+.2f}, expected {track.pan:+.2f}",
                    True,
                    track=track.index,
                )
            )
    if track.sends is not None and track.index < len(observed.sends):
        seen_sends = observed.sends[track.index]
        for send, level in enumerate(track.sends):
            if send < len(seen_sends) and abs(seen_sends[send] - level) > MIX_TOLERANCE:
                found.append(
                    Divergence(
                        "send",
                        f"{where} send {chr(ord('A') + send)} is {seen_sends[send]:.3f}, "
                        f"expected {level:.3f}",
                        True,
                        track=track.index,
                    )
                )
    return found


def apply_session(daw: DawPort, spec: SessionSpec) -> tuple[Divergence, ...]:
    """Repair what the LOM can repair; return what is left for a human.

    Idempotent by construction: the second pass finds nothing fixable and therefore
    issues no writes at all — not "writes the same thing again".
    """
    for divergence in diff_session(spec, observe(daw, spec)):
        if divergence.kind == "tempo":
            daw.set_tempo(spec.tempo_bpm)
        elif divergence.kind == "quantization":
            daw.set_quantization(spec.quantization)
        elif divergence.kind == "loop" and spec.loop is not None:
            daw.set_song_loop(spec.loop)
        elif divergence.kind == "track_name" and divergence.track is not None:
            daw.set_track_name(divergence.track, spec.tracks[divergence.track].name)
        elif divergence.kind == "armed" and divergence.track is not None:
            wanted = spec.tracks[divergence.track].armed
            if wanted is not None:
                daw.set_track_armed(divergence.track, wanted)
        elif divergence.kind in ("volume", "pan", "send") and divergence.track is not None:
            _apply_mix(daw, spec.tracks[divergence.track], divergence.kind)
    return diff_session(spec, observe(daw, spec))


def _apply_mix(daw: DawPort, track: TrackSpec, kind: str) -> None:
    if kind == "volume" and track.volume is not None:
        daw.set_track_volume(track.index, track.volume)
    elif kind == "pan" and track.pan is not None:
        daw.set_track_pan(track.index, track.pan)
    elif kind == "send" and track.sends is not None:
        for send, level in enumerate(track.sends):
            if abs(daw.track_send(track.index, send) - level) > MIX_TOLERANCE:
                daw.set_track_send(track.index, send, level)


def render_mix(daw: DawPort, spec: SessionSpec, returns: int = 2) -> str:
    """The open Set's mix as `session.toml` lines, one block per track, to paste in.

    The mix is made by ear in Live and pinned afterwards: nobody should have to type a fader
    position. Read-only.
    """
    lines: list[str] = []
    for track in spec.tracks:
        sends = ", ".join(f"{daw.track_send(track.index, send):.3f}" for send in range(returns))
        lines.extend(
            [
                f"# track {track.index}: {track.name}",
                f"volume = {daw.track_volume(track.index):.3f}",
                f"pan = {daw.track_pan(track.index):.2f}",
                f"sends = [{sends}]",
                "",
            ]
        )
    return "\n".join(lines)


def ensure_clip(daw: DawPort, at: ClipAddress, length_beats: float) -> None:
    """Make the slot hold a clip of exactly this length, doing nothing if it already does."""
    if not daw.has_clip(at):
        daw.create_clip(at, length_beats)
        return
    if abs(daw.clip_length_beats(at) - length_beats) > 1e-3:
        # Live has no way to resize a clip's loop from here, so replace it.
        daw.delete_clip(at)
        daw.create_clip(at, length_beats)


def render_divergences(divergences: Sequence[Divergence]) -> str:
    """One line each, saying who fixes it and how. Empty when the Set matches."""
    if not divergences:
        return ""
    lines = [
        f"{'fix:' if d.fixable else 'HUMAN:'} [{d.kind}] {d.detail}{_instruction(d)}"
        for d in divergences
    ]
    return "\n".join(lines) + "\n"


def _instruction(divergence: Divergence) -> str:
    """What to do in Live. Only for the ones no script can fix."""
    match divergence.kind:
        case "missing_track":
            return (
                " — open the Set, add a MIDI track at that position, name it as above,"
                " and load the preset named above onto it"
            )
        case "no_instrument":
            return (
                " — open the Set and load the instrument named above onto that track:"
                " search Live's browser by its name (Plug-Ins for Analog Lab)"
            )
        case "wrong_instrument":
            return (
                " — in Live, click that track, find the instrument named above in the"
                " browser and drag it onto the track's device area, replacing the one there;"
                " or, if the one there is the one you chose, write its name in session.toml"
            )
        case "extra_track":
            return " — remove them in Live, or add them to session.toml if they belong"
        case "not_a_midi_track":
            return (
                " — delete it in Live and insert a MIDI track at that position"
                " (an audio track cannot be converted)"
            )
        case "missing_scene":
            return " — add scenes in Live until there are enough (Create -> Insert Scene)"
        case _:
            return ""
