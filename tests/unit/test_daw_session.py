""" "Set as Code": loading the spec, diffing the Set, and repairing only what can be.

Every one of these runs with Ableton closed. That is the point of the
`observe` -> `diff_session` -> `apply_session` split: the diff is pure and the two
around it are thin enough to drive with `FakeDawAdapter`, so the whole bootstrap —
including its idempotence — is provable before Live is ever opened.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from garagem.daw import (
    LITE_TRACK_LIMIT,
    ClipAddress,
    Divergence,
    FakeDawAdapter,
    Quantization,
    SessionSpecError,
    apply_session,
    diff_session,
    ensure_clip,
    load_session,
    observe,
    render_divergences,
)

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "session.toml"

SPEC_TOML = """
schema = 1
name = "test"
tempo_bpm = 132.0
quantization = "1_bar"

[[track]]
index = 0
name = "DRUMS"
instrument = "Drift"

[[track]]
index = 1
name = "BASS"
instrument = "Drift"

[[scene]]
index = 0
name = "A"

[[scene]]
index = 1
name = "B"
"""


def a_spec(tmp_path: Path, body: str = SPEC_TOML) -> Path:
    path = tmp_path / "session.toml"
    path.write_text(body, encoding="utf-8")
    return path


def matching_daw() -> FakeDawAdapter:
    return FakeDawAdapter(
        track_names=("DRUMS", "BASS"),
        scenes=2,
        tempo_bpm=132.0,
        quantization=Quantization.BAR,
    )


def kinds(divergences: tuple[Divergence, ...]) -> list[str]:
    return [d.kind for d in divergences]


# ------------------------------------------------------------------ loading the spec


def test_the_shipped_session_file_loads() -> None:
    """The real file, not a fixture: a spec nobody can load is worse than none."""
    spec = load_session(SHIPPED)

    assert [track.name for track in spec.tracks] == ["DRUMS", "BASS", "GTR", "KEYS"]
    assert spec.quantization is Quantization.BAR
    assert spec.tempo_bpm == 132.0
    assert len(spec.scenes) >= 2


def test_a_wrong_schema_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SessionSpecError, match="schema"):
        load_session(a_spec(tmp_path, SPEC_TOML.replace("schema = 1", "schema = 2")))


def test_a_spec_with_no_tracks_is_refused(tmp_path: Path) -> None:
    trackless = """
schema = 1
name = "test"
tempo_bpm = 132.0
quantization = "1_bar"

[[scene]]
index = 0
name = "A"

[[scene]]
index = 1
name = "B"
"""
    with pytest.raises(SessionSpecError, match=re.escape("no [[track]]")):
        load_session(a_spec(tmp_path, trackless))


def test_more_tracks_than_live_lite_allows_is_refused(tmp_path: Path) -> None:
    extra = "".join(
        f'\n[[track]]\nindex = {i}\nname = "T{i}"\ninstrument = "Drift"\n'
        for i in range(2, LITE_TRACK_LIMIT + 1)
    )
    with pytest.raises(SessionSpecError, match="Lite"):
        load_session(a_spec(tmp_path, SPEC_TOML + extra))


def test_non_contiguous_track_indices_are_refused(tmp_path: Path) -> None:
    with pytest.raises(SessionSpecError, match="track indices"):
        load_session(
            a_spec(
                tmp_path, SPEC_TOML.replace('index = 1\nname = "BASS"', 'index = 5\nname = "BASS"')
            )
        )


def test_duplicate_track_names_are_refused(tmp_path: Path) -> None:
    with pytest.raises(SessionSpecError, match="duplicate"):
        load_session(a_spec(tmp_path, SPEC_TOML.replace('name = "BASS"', 'name = "DRUMS"')))


def test_an_empty_track_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SessionSpecError, match="empty name"):
        load_session(a_spec(tmp_path, SPEC_TOML.replace('name = "BASS"', 'name = "  "')))


def test_a_single_scene_is_refused_because_adr_001_needs_somewhere_to_write(
    tmp_path: Path,
) -> None:
    body = SPEC_TOML.rsplit("[[scene]]", 1)[0]
    with pytest.raises(SessionSpecError, match="ADR-001"):
        load_session(a_spec(tmp_path, body))


def test_non_contiguous_scene_indices_are_refused(tmp_path: Path) -> None:
    with pytest.raises(SessionSpecError, match="scene indices"):
        load_session(
            a_spec(tmp_path, SPEC_TOML.replace('index = 1\nname = "B"', 'index = 7\nname = "B"'))
        )


@pytest.mark.parametrize("tempo", ["0.0", "1200.0"])
def test_an_impossible_tempo_is_refused(tmp_path: Path, tempo: str) -> None:
    with pytest.raises(SessionSpecError, match="tempo_bpm"):
        load_session(
            a_spec(tmp_path, SPEC_TOML.replace("tempo_bpm = 132.0", f"tempo_bpm = {tempo}"))
        )


def test_an_unknown_quantisation_is_refused_and_lists_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(SessionSpecError, match="1_bar"):
        load_session(a_spec(tmp_path, SPEC_TOML.replace('"1_bar"', '"3_bars"')))


# --------------------------------------------------------------------- diffing the Set


def test_a_matching_set_diverges_in_nothing(tmp_path: Path) -> None:
    spec = load_session(a_spec(tmp_path))
    assert diff_session(spec, observe(matching_daw())) == ()


def test_the_repairable_differences_are_marked_fixable(tmp_path: Path) -> None:
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(
        track_names=("DRUMS", "BAIXO"),
        tempo_bpm=120.0,
        quantization=Quantization.NONE,
    )
    found = diff_session(spec, observe(daw))

    assert kinds(found) == ["tempo", "quantization", "track_name"]
    assert all(d.fixable for d in found)


def test_a_track_with_no_instrument_is_reported_and_not_fixable(tmp_path: Path) -> None:
    """No LOM call loads a device, so a script that "fixed" this would produce silence."""
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(
        track_names=("DRUMS", "BASS"),
        device_names=(("Drift",), ()),
        tempo_bpm=132.0,
    )
    (found,) = diff_session(spec, observe(daw))

    assert (found.kind, found.fixable, found.track) == ("no_instrument", False, 1)


def test_an_audio_track_in_a_musical_role_is_reported_and_not_fixable(tmp_path: Path) -> None:
    """Renaming it would make the Set look right and guarantee silence."""
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(
        track_names=("DRUMS", "2-Audio"),
        midi_tracks=(True, False),
        tempo_bpm=132.0,
    )
    (found,) = diff_session(spec, observe(daw))

    assert (found.kind, found.fixable, found.track) == ("not_a_midi_track", False, 1)


def test_an_audio_track_is_not_renamed_by_apply(tmp_path: Path) -> None:
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(
        track_names=("DRUMS", "2-Audio"), midi_tracks=(True, False), tempo_bpm=132.0
    )
    left = apply_session(daw, spec)

    assert daw.track_names() == ("DRUMS", "2-Audio")
    assert kinds(left) == ["not_a_midi_track"]


def test_the_report_tells_the_human_an_audio_track_cannot_be_converted() -> None:
    report = render_divergences(
        (Divergence("not_a_midi_track", "track 1 is audio", False, track=1),)
    )
    assert "insert a MIDI track" in report


def test_a_missing_track_is_reported_and_not_fixable(tmp_path: Path) -> None:
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(track_names=("DRUMS",), tempo_bpm=132.0)
    assert kinds(diff_session(spec, observe(daw))) == ["missing_track"]


def test_extra_tracks_and_missing_scenes_are_reported(tmp_path: Path) -> None:
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(track_names=("DRUMS", "BASS", "STRINGS"), tempo_bpm=132.0, scenes=1)
    assert kinds(diff_session(spec, observe(daw))) == ["extra_track", "missing_scene"]


# -------------------------------------------------------------------------- repairing


def test_applying_repairs_what_it_can_and_returns_what_it_cannot(tmp_path: Path) -> None:
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(track_names=("DRUMS", "BAIXO"), tempo_bpm=120.0, scenes=1)
    left = apply_session(daw, spec)

    assert daw.track_names() == ("DRUMS", "BASS")
    assert daw.tempo() == 132.0
    assert kinds(left) == ["missing_scene"]


def test_applying_a_matching_session_writes_nothing_at_all(tmp_path: Path) -> None:
    """Idempotence, proved mechanically: the second pass issues no write, not the same write."""
    spec = load_session(a_spec(tmp_path))
    daw = FakeDawAdapter(track_names=("DRUMS", "BAIXO"), tempo_bpm=120.0)

    assert apply_session(daw, spec) == ()
    daw.calls.clear()
    assert apply_session(daw, spec) == ()
    assert not [call for call in daw.calls if call.startswith("set_")]


# ------------------------------------------------------------------------------ clips


def test_ensuring_a_clip_creates_it_when_the_slot_is_empty() -> None:
    daw = FakeDawAdapter()
    at = ClipAddress(track=0, scene=1)
    ensure_clip(daw, at, 16.0)
    assert daw.clip_length_beats(at) == 16.0


def test_ensuring_a_clip_of_the_right_length_does_nothing() -> None:
    daw = FakeDawAdapter()
    at = ClipAddress(track=0, scene=1)
    ensure_clip(daw, at, 16.0)
    daw.calls.clear()
    ensure_clip(daw, at, 16.0)
    assert "create_clip" not in daw.calls and "delete_clip" not in daw.calls


def test_ensuring_a_clip_of_the_wrong_length_replaces_it() -> None:
    daw = FakeDawAdapter()
    at = ClipAddress(track=0, scene=1)
    ensure_clip(daw, at, 8.0)
    ensure_clip(daw, at, 16.0)
    assert daw.clip_length_beats(at) == 16.0


# ---------------------------------------------------------------------------- report


def test_a_matching_set_renders_nothing() -> None:
    assert render_divergences(()) == ""


def test_the_report_says_who_fixes_each_line_and_how() -> None:
    report = render_divergences(
        (
            Divergence("tempo", "120.0 BPM, expected 132.0", True),
            Divergence("no_instrument", "track 1 (BASS) carries no device", False, track=1),
        )
    )

    assert "fix: [tempo]" in report
    assert "HUMAN: [no_instrument]" in report
    assert "Instruments -> Drift" in report
