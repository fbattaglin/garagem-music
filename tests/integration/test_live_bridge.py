"""The Phase 1 exit criterion, against a real Ableton Live.

    uv run pytest -m live -q

ADR-000 §7 states it: "an integration test writes Em-C-G-D across 4 bars, fires the
scene, and audio comes out of the Scarlett. Idempotent."

Three of those four claims are machine-checkable here and are checked below: the notes
read back identical to what was written, firing the scene starts the transport, and
running the bootstrap twice leaves the Set unchanged. The fourth — signal arriving at
the Scarlett's outputs — is a fact about Live's audio preferences and a cable, and no
Python can observe it. What *can* be observed is `output_meter_level` on KEYS while the
clip plays: that proves MIDI reached an instrument and the instrument produced signal,
which is the whole chain except the last centimetre. The last centimetre is a human
confirmation, recorded by name and date in `STATUS.md`.

The Set has to be built by hand first — four MIDI tracks named DRUMS, BASS, GTR, KEYS,
each carrying Drift, at 132 BPM with launch quantisation `1 Bar` (ADR-013). Check it
with `uv run python scripts/bootstrap_set.py`, which exits 0 when it is ready.

These tests share one Live Set and run in order.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import EM_C_G_D, PROGRESSION_BEATS, chord_clip
from garagem.daw import (
    AbletonOSCAdapter,
    ClipAddress,
    DawPort,
    apply_session,
    diff_session,
    ensure_clip,
    load_session,
    normalised,
    observe,
    render_divergences,
)

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]
SPEC = load_session(ROOT / "session.toml")

# KEYS, in the scene that is not scene 0 — ADR-001 writes into the silent one.
KEYS = ClipAddress(track=3, scene=1)

# One 1-bar quantum at 132 BPM is 1.82 s; 3.0 s leaves room for the round trip without
# being long enough to hide a launch that never happened.
LAUNCH_TIMEOUT_S = 3.0
POLL_S = 0.1
# Long enough to cover a whole bar of the progression, sampled finely enough that a
# short attack is not missed between two reads.
LISTEN_S = 2.0
METER_POLL_S = 0.05


@pytest.fixture(scope="module")
def live_daw() -> Iterator[AbletonOSCAdapter]:
    """The real adapter. It deliberately does not skip when Live is closed.

    A skipped test reads as "nothing to see here". `DawUnavailableError` propagating
    with its own message — open the Set, enable the control surface — is the correct
    outcome, and it is the one that gets Live opened.
    """
    daw = AbletonOSCAdapter.from_env()
    try:
        daw.warm()
        daw.stop_playing()
        yield daw
    finally:
        daw.stop_playing()
        daw.close()


def test_live_answers_on_the_control_surface_port(live_daw: AbletonOSCAdapter) -> None:
    live_daw.warm()
    assert live_daw.tempo() > 0


def test_the_open_set_matches_the_session_spec(live_daw: AbletonOSCAdapter) -> None:
    """If this fails, the message says what to do in Live. Fix it there, not here."""
    left = apply_session(live_daw, SPEC)
    assert left == (), f"\n{render_divergences(left)}"
    assert diff_session(SPEC, observe(live_daw)) == ()


def test_the_bridge_writes_em_c_g_d_across_four_bars(live_daw: AbletonOSCAdapter) -> None:
    assert not live_daw.is_playing(), "every write happens with the transport stopped"

    written = chord_clip()
    ensure_clip(live_daw, KEYS, PROGRESSION_BEATS)
    live_daw.write_notes(KEYS, written)

    read_back = live_daw.read_notes(KEYS)
    assert len(read_back) == 3 * len(EM_C_G_D)
    assert read_back == normalised(written)


def test_firing_the_scene_starts_the_transport(live_daw: AbletonOSCAdapter) -> None:
    """The launch is quantised, so the confirmation is `is_playing`, not the fire itself."""
    live_daw.fire_scene(KEYS.scene)

    deadline = time.monotonic() + LAUNCH_TIMEOUT_S
    while time.monotonic() < deadline:
        if live_daw.is_playing():
            return
        time.sleep(POLL_S)
    pytest.fail(f"the transport did not start within {LAUNCH_TIMEOUT_S} s of firing the scene")


def test_the_instrument_actually_makes_a_sound(live_daw: AbletonOSCAdapter) -> None:
    """Everything but the last centimetre: MIDI reached Drift and Drift produced signal.

    Whether that signal comes out of the Scarlett is a Live audio-preferences fact
    Python cannot see. Listen, then record it in STATUS.md.
    """
    if not live_daw.is_playing():
        live_daw.fire_scene(KEYS.scene)
        time.sleep(LAUNCH_TIMEOUT_S)

    peak = 0.0
    deadline = time.monotonic() + LISTEN_S
    while time.monotonic() < deadline:
        peak = max(peak, live_daw.meter_level(KEYS.track))
        time.sleep(METER_POLL_S)

    assert peak > 0.0, (
        "KEYS never moved its output meter. The notes are in the clip, so either the "
        "track carries no instrument, or it is muted, or another track is soloed."
    )


def test_running_the_bootstrap_twice_leaves_the_set_identical(
    live_daw: AbletonOSCAdapter,
) -> None:
    live_daw.stop_playing()
    before = (observe(live_daw), live_daw.read_notes(KEYS))

    assert apply_session(live_daw, SPEC) == ()
    ensure_clip(live_daw, KEYS, PROGRESSION_BEATS)
    live_daw.write_notes(KEYS, chord_clip())

    after = (observe(live_daw), live_daw.read_notes(KEYS))
    assert after == before
    # The one that would show `/live/clip/add/notes` appending instead of replacing.
    assert len(after[1]) == 3 * len(EM_C_G_D)


def test_the_adapter_satisfies_the_port(live_daw: AbletonOSCAdapter) -> None:
    daw: DawPort = live_daw
    assert isinstance(daw, DawPort)
    assert daw.name == "abletonosc"
