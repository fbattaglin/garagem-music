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
)
# The ones the LOM can repair. Everything else is a human's job (ADR-013).
FIXABLE_KINDS: Final[frozenset[str]] = frozenset(
    {"tempo", "quantization", "track_name", "armed", "loop"}
)


@dataclass(frozen=True, slots=True)
class TrackSpec:
    index: int
    name: str
    role: str
    # Informational: the API cannot load it. It tells the human what to drop in, and
    # the check is only that *some* device is present.
    instrument: str
    # `None` means the Set may have it either way. The band's tracks declare `false`: an
    # armed MIDI track plays whatever the MiniLab sends, cue pads included (ADR-022).
    armed: bool | None = None


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


def observe(daw: DawPort) -> ObservedSet:
    """One snapshot of the open Set, in the shape `diff_session` needs."""
    names = daw.track_names()
    return ObservedSet(
        tempo_bpm=daw.tempo(),
        quantization=daw.quantization(),
        track_names=names,
        device_names=tuple(daw.device_names(index) for index in range(len(names))),
        accepts_midi=tuple(daw.accepts_midi(index) for index in range(len(names))),
        scene_count=daw.scene_count(),
        armed=tuple(daw.track_armed(index) for index in range(len(names))),
        loop=daw.song_loop(),
    )


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
                    f"track {track.index} ({track.name}) does not exist",
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
        if not observed.device_names[track.index]:
            found.append(
                Divergence(
                    "no_instrument",
                    f"track {track.index} ({track.name}) carries no device, so it will be silent",
                    False,
                    track=track.index,
                )
            )

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


def apply_session(daw: DawPort, spec: SessionSpec) -> tuple[Divergence, ...]:
    """Repair what the LOM can repair; return what is left for a human.

    Idempotent by construction: the second pass finds nothing fixable and therefore
    issues no writes at all — not "writes the same thing again".
    """
    for divergence in diff_session(spec, observe(daw)):
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
    return diff_session(spec, observe(daw))


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
                " and drop Drift on it"
            )
        case "no_instrument":
            return (
                " — open the Set and drag an instrument onto that track: Live's browser,"
                " Instruments -> Drift, drag any preset onto the track"
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
