"""The whole Phase 1 script, run against the fake: bootstrap, write, fire.

This is the dress rehearsal. Every step the `live` integration test performs happens
here first, in the same order, against `FakeDawAdapter` — including the two claims that
are easiest to get wrong and hardest to see in Live: that running the script twice
leaves an identical Set, and that nothing is ever written into a clip that is playing.

If this does not pass, opening Ableton will only make the same bug harder to read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import EM_C_G_D, PROGRESSION_BEATS, chord_clip
from garagem.daw import (
    ClipAddress,
    Divergence,
    FakeDawAdapter,
    MidiNote,
    ObservedSet,
    Quantization,
    SessionSpec,
    apply_session,
    ensure_clip,
    load_session,
    observe,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_session(ROOT / "session.toml")
KEYS = ClipAddress(track=3, scene=1)


def a_live_set() -> FakeDawAdapter:
    """A Set that already matches `session.toml` — what Step 18 builds by hand."""
    return FakeDawAdapter(
        track_names=tuple(track.name for track in SPEC.tracks),
        scenes=len(SPEC.scenes),
        tempo_bpm=SPEC.tempo_bpm,
        quantization=SPEC.quantization,
    )


def play_the_progression(daw: FakeDawAdapter, spec: SessionSpec) -> tuple[Divergence, ...]:
    """Bootstrap, write Em-C-G-D into the silent scene, fire it. The whole phase."""
    left = apply_session(daw, spec)
    ensure_clip(daw, KEYS, PROGRESSION_BEATS)
    daw.write_notes(KEYS, chord_clip())
    daw.fire_scene(KEYS.scene)
    return left


def snapshot(daw: FakeDawAdapter) -> tuple[ObservedSet, tuple[MidiNote, ...]]:
    return observe(daw), daw.read_notes(KEYS)


# ------------------------------------------------------------------- the progression


def test_the_progression_is_four_bars_of_triads() -> None:
    notes = chord_clip()
    assert len(notes) == 3 * len(EM_C_G_D)
    assert {note.start_beats for note in notes} == {0.0, 4.0, 8.0, 12.0}
    assert max(note.start_beats + note.duration_beats for note in notes) == PROGRESSION_BEATS


def test_the_whole_script_leaves_the_chords_in_the_clip() -> None:
    daw = a_live_set()
    assert play_the_progression(daw, SPEC) == ()
    assert daw.read_notes(KEYS) == chord_clip()


def test_firing_the_scene_is_the_last_thing_that_happens() -> None:
    """Write first, launch second: the clip is complete before Live is asked for it."""
    daw = a_live_set()
    play_the_progression(daw, SPEC)
    assert daw.calls.index("write_notes") < daw.calls.index("fire_scene")
    assert daw.fired == [KEYS.scene]


# ---------------------------------------------------------------------- idempotence


def test_running_the_whole_script_twice_leaves_an_identical_set() -> None:
    daw = a_live_set()
    play_the_progression(daw, SPEC)
    first = snapshot(daw)

    play_the_progression(daw, SPEC)
    assert snapshot(daw) == first


def test_the_second_pass_does_not_double_the_notes() -> None:
    """The failure this catches is `/live/clip/add/notes` appending instead of replacing."""
    daw = a_live_set()
    play_the_progression(daw, SPEC)
    play_the_progression(daw, SPEC)
    assert len(daw.read_notes(KEYS)) == 3 * len(EM_C_G_D)


def test_the_second_bootstrap_writes_nothing_at_all() -> None:
    daw = a_live_set()
    play_the_progression(daw, SPEC)
    daw.calls.clear()
    apply_session(daw, SPEC)
    assert not [call for call in daw.calls if call.startswith("set_")]


# --------------------------------------------------------------------- invariant 6


def test_nothing_is_written_into_a_clip_that_is_playing() -> None:
    """ADR-001: scene N sounds while scene N+1 is written. Never the same one."""
    daw = a_live_set()
    playing = ClipAddress(track=3, scene=0)
    ensure_clip(daw, playing, PROGRESSION_BEATS)
    daw.fire_scene(playing.scene)
    assert daw.is_playing()

    daw.calls.clear()
    ensure_clip(daw, KEYS, PROGRESSION_BEATS)
    daw.write_notes(KEYS, chord_clip())

    assert daw.fired == [playing.scene]
    assert daw.read_notes(playing) == ()
    assert daw.read_notes(KEYS) == chord_clip()


def test_the_set_the_phase_needs_has_somewhere_to_write_ahead_into() -> None:
    with pytest.raises(Exception, match="scene 2 does not exist"):
        FakeDawAdapter(scenes=2).fire_scene(2)
    assert Quantization.BAR is SPEC.quantization
