"""Asks the real Live what a cue can rely on, and reports what it answered.

    uv run python scripts/spike_cues.py            # needs Live open, transport stopped
    uv run python scripts/spike_cues.py --track 3  # measure on another track

Stage 0 of the MiniLab plan. A cue may cost a *fire*, never a *write* — a section write
takes about a bar — so everything a pad can trigger has to be written ahead and launched
by Live's quantisation. Whether that works depends on five things about clip launching
that the plan read from the manual and AbletonOSC's source and has never seen happen:

1. **Scene cap.** How many scenes this Live edition allows. Candidates and variants each
   need scenes, and Lite editions cap things.
2. **Clip fire is quantised.** `/live/clip/fire` launches on the next bar, like a scene.
3. **Legato continues position** when a clip is fired, and when a scene is fired.
4. **Legato can be set just before a fire** and still apply to that launch.
5. **A second trigger replaces the first** when both land before the same bar.
6. **Track stop is quantised.** `/live/track/stop_all_clips` waits for the bar.

Plus what each call costs.

**Every answer is an observation, not an assertion.** Either answer to each question is a
legitimate fact about Live, and the plan has a branch for each (`phase-4-findings.md` §7).
That is why this is a script that reports, rather than a test that fails.

How it measures without trusting a stopwatch: a playing clip reports `playing_position`,
and the song reports `current_song_time`. Read back to back, their difference is the beat
the clip launched on — a multiple of four if the launch was quantised to the bar, and the
same launch beat as the previous clip if legato carried the position over.

**It changes the Set, and puts it back.** It refuses to start while the transport runs or
if any slot it would use already holds a clip. It writes short clips into scenes 2 to 6 of
one track, plays them for about thirty seconds, adds scenes to find the cap, and in a
`finally` stops the transport and deletes every clip and scene it created. A quiet note on
each downbeat is the only sound.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Final

from garagem.daw import (
    AbletonOSCAdapter,
    ClipAddress,
    DawError,
    MidiNote,
    OscArg,
    OscSettings,
    UdpOscTransport,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "bench" / "spike-cues.json"

BEATS_PER_BAR: Final = 4.0
CLIP_BARS: Final = 8
CLIP_BEATS: Final = CLIP_BARS * BEATS_PER_BAR
# Scenes 0 and 1 are the scheduler's (ADR-001). The spike stays out of them.
A, B, C, D, E = 2, 3, 4, 5, 6
SCENES: Final = (A, B, C, D, E)

# Two positions within this many beats describe the same point in the clip. Two OSC round
# trips at ~10 ms each are 0.05 beats at 132 BPM; this is ten times that.
TOLERANCE_BEATS: Final = 0.5
POLL_S: Final = 0.02
# Fire in the middle of a bar, so "the next bar" and "right now" are two beats apart.
MID_BAR: Final = (1.5, 2.5)
SCENE_CAP_PROBE: Final = 32
QUIET_VELOCITY: Final = 40

FIRE_CLIP: Final = "/live/clip/fire"
SET_LEGATO: Final = "/live/clip/set/legato"
GET_LEGATO: Final = "/live/clip/get/legato"
GET_POSITION: Final = "/live/clip/get/playing_position"
GET_PLAYING_SLOT: Final = "/live/track/get/playing_slot_index"
STOP_TRACK: Final = "/live/track/stop_all_clips"
FIRE_SCENE: Final = "/live/scene/fire"
GET_SONG_TIME: Final = "/live/song/get/current_song_time"
SET_SONG_TIME: Final = "/live/song/set/current_song_time"
NUM_SCENES: Final = "/live/song/get/num_scenes"
CREATE_SCENE: Final = "/live/song/create_scene"
DELETE_SCENE: Final = "/live/song/delete_scene"


# ------------------------------------------------------------------------ pure reckoning


def next_bar(beat: float) -> float:
    """The bar line a quantised launch fired at `beat` lands on."""
    return math.floor(beat / BEATS_PER_BAR + 1e-9) * BEATS_PER_BAR + BEATS_PER_BAR


def launched_at(song_time: float, position: float) -> float:
    """The beat a clip launched on, from where it is now and where the song is."""
    return song_time - position


def same_beat(first: float, second: float, length: float = CLIP_BEATS) -> bool:
    """Whether two positions name the same point of a looping clip."""
    gap = abs(first - second) % length
    return min(gap, length - gap) <= TOLERANCE_BEATS


def verdict(position: float, continuing: float, restarted: float) -> str:
    """`legato` if the clip carried the old position over, `restart` if it began at 0."""
    if same_beat(position, continuing) and not same_beat(position, restarted):
        return "legato"
    if same_beat(position, restarted) and not same_beat(position, continuing):
        return "restart"
    return "unclear"


@dataclass(slots=True)
class Finding:
    question: str
    answer: str
    evidence: dict[str, float | int | str] = field(default_factory=dict)


# -------------------------------------------------------------------------- the live rig


class Live:
    """The adapter for what it already does, the raw transport for what it does not."""

    def __init__(self, transport: UdpOscTransport, track: int) -> None:
        self.transport = transport
        self.daw = AbletonOSCAdapter(transport=transport)
        self.track = track

    def at(self, scene: int) -> ClipAddress:
        return ClipAddress(track=self.track, scene=scene)

    def song_time(self) -> float:
        return float(self.transport.request(GET_SONG_TIME)[0])

    def position(self, scene: int) -> float:
        reply = self.transport.request(GET_POSITION, self.track, scene)
        return float(reply[-1])

    def playing_slot(self) -> int:
        return int(self.transport.request(GET_PLAYING_SLOT, self.track)[-1])

    def legato(self, scene: int) -> bool:
        return bool(self.transport.request(GET_LEGATO, self.track, scene)[-1])

    def set_legato(self, scene: int, on: bool) -> None:
        self.transport.send(SET_LEGATO, self.track, scene, on)

    def fire_clip(self, scene: int) -> None:
        self.transport.send(FIRE_CLIP, self.track, scene)

    def fire_scene(self, scene: int) -> None:
        self.transport.send(FIRE_SCENE, scene)

    def stop_track(self) -> None:
        self.transport.send(STOP_TRACK, self.track)

    def num_scenes(self) -> int:
        return int(self.transport.request(NUM_SCENES)[0])

    def send(self, address: str, *args: OscArg) -> None:
        self.transport.send(address, *args)

    def wait_until(self, beat: float, timeout_s: float = 30.0) -> float:
        """Poll the song until it reaches `beat`. The spike's only clock."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            now = self.song_time()
            if now >= beat:
                return now
            time.sleep(POLL_S)
        raise DawError(f"the song never reached beat {beat}; is the transport running?")

    def wait_for_mid_bar(self, timeout_s: float = 10.0) -> float:
        """Return once the song is between beats 1.5 and 2.5 of some bar."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            now = self.song_time()
            if MID_BAR[0] <= now % BEATS_PER_BAR <= MID_BAR[1]:
                return now
            time.sleep(POLL_S)
        raise DawError("the song never reached the middle of a bar; is the transport running?")


# ----------------------------------------------------------------------------- experiments


def clip_fire_is_quantised(live: Live) -> tuple[Finding, float]:
    fired = live.wait_for_mid_bar()
    live.fire_clip(A)
    live.wait_until(next_bar(fired) + 1.0)
    now, position = live.song_time(), live.position(A)
    launch = launched_at(now, position)
    expected = next_bar(fired)
    answer = "quantised" if abs(launch - expected) <= TOLERANCE_BEATS else "not quantised"
    return (
        Finding(
            "clip fire waits for the next bar",
            answer,
            {"fired_beat": round(fired, 3), "launched_beat": round(launch, 3), "bar": expected},
        ),
        launch,
    )


def legato_on_clip_fire(live: Live, launch_a: float) -> Finding:
    live.set_legato(B, True)
    confirmed = live.legato(B)
    live.wait_until(launch_a + 2 * BEATS_PER_BAR)
    fired = live.wait_for_mid_bar()
    live.fire_clip(B)
    live.wait_until(next_bar(fired) + 1.0)
    now, position = live.song_time(), live.position(B)
    return Finding(
        "legato continues position on clip fire",
        verdict(position, now - launch_a, now - next_bar(fired)),
        {"legato_confirmed": int(confirmed), "position": round(position, 3)},
    )


def legato_on_scene_fire(live: Live, launch_a: float) -> Finding:
    live.set_legato(C, True)
    fired = live.wait_for_mid_bar()
    live.fire_scene(C)
    live.wait_until(next_bar(fired) + 1.0)
    now, position = live.song_time(), live.position(C)
    return Finding(
        "legato continues position on scene fire",
        verdict(position, now - launch_a, now - next_bar(fired)),
        {"position": round(position, 3)},
    )


def legato_set_just_before_fire(live: Live, launch_a: float) -> Finding:
    live.set_legato(D, False)
    fired = live.wait_for_mid_bar()
    started = time.monotonic()
    live.set_legato(D, True)
    live.fire_clip(D)
    sent_ms = (time.monotonic() - started) * 1000.0
    live.wait_until(next_bar(fired) + 1.0)
    now, position = live.song_time(), live.position(D)
    return Finding(
        "legato set immediately before a fire applies to it",
        verdict(position, now - launch_a, now - next_bar(fired)),
        {"position": round(position, 3), "set_and_fire_ms": round(sent_ms, 2)},
    )


def second_trigger_replaces_first(live: Live) -> Finding:
    fired = live.wait_for_mid_bar()
    live.fire_clip(E)
    time.sleep(0.05)
    live.fire_clip(A)
    live.wait_until(next_bar(fired) + 1.0)
    slot = live.playing_slot()
    answer = {A: "the second wins", E: "the first wins"}.get(slot, f"neither (slot {slot})")
    return Finding("a second trigger before the bar replaces the first", answer, {"slot": slot})


def track_stop_is_quantised(live: Live) -> Finding:
    fired = live.wait_for_mid_bar()
    live.stop_track()
    stopped_at = None
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if live.playing_slot() < 0:
            stopped_at = live.song_time()
            break
        time.sleep(POLL_S)
    if stopped_at is None:
        return Finding("track stop waits for the next bar", "never stopped", {})
    bar = next_bar(fired)
    answer = "quantised" if abs(stopped_at - bar) <= TOLERANCE_BEATS else "immediate"
    return Finding(
        "track stop waits for the next bar",
        answer,
        {"fired_beat": round(fired, 3), "stopped_beat": round(stopped_at, 3), "bar": bar},
    )


def call_costs(live: Live) -> Finding:
    def timed(call: Callable[[], object], runs: int = 20) -> float:
        samples = []
        for _ in range(runs):
            started = time.monotonic()
            call()
            samples.append((time.monotonic() - started) * 1000.0)
        return round(median(samples), 2)

    return Finding(
        "what each call costs (median ms)",
        "measured",
        {
            "get_position_ms": timed(lambda: live.position(A)),
            "get_legato_ms": timed(lambda: live.legato(A)),
            "get_playing_slot_ms": timed(live.playing_slot),
            # A setter is a bare send, like a fire, and setting legato to what it already
            # is changes nothing — so it measures a fire's cost without firing anything.
            "send_ms": timed(lambda: live.set_legato(B, True)),
        },
    )


def scene_cap(live: Live, created: list[int]) -> Finding:
    """Append scenes until Live stops adding them. Every one added is recorded for removal."""
    before = live.num_scenes()
    count = before
    for _ in range(SCENE_CAP_PROBE):
        live.send(CREATE_SCENE, -1)
        time.sleep(0.1)
        now = live.num_scenes()
        if now == count:
            break
        created.append(now - 1)
        count = now
    capped = count < before + SCENE_CAP_PROBE
    return Finding(
        "how many scenes this Live allows",
        f"{count}" if capped else f"at least {count}",
        {"before": before, "reached": count},
    )


# ----------------------------------------------------------------------------- the run


def prepare(live: Live) -> list[ClipAddress]:
    """Refuse anything that would overwrite the human's work, then write the clips."""
    if live.daw.is_playing():
        raise DawError("the transport is running; stop it before the spike")
    if live.daw.scene_count() <= max(SCENES):
        raise DawError(f"the Set needs at least {max(SCENES) + 1} scenes for the spike")
    occupied = [scene for scene in SCENES if live.daw.has_clip(live.at(scene))]
    if occupied:
        raise DawError(f"track {live.track} already has clips in scenes {occupied}; refusing")
    notes = [
        MidiNote(
            pitch=60, start_beats=bar * BEATS_PER_BAR, duration_beats=0.25, velocity=QUIET_VELOCITY
        )
        for bar in range(CLIP_BARS)
    ]
    written = []
    for scene in SCENES:
        at = live.at(scene)
        live.daw.create_clip(at, CLIP_BEATS)
        written.append(at)
        live.daw.write_notes(at, notes)
    return written


def cleanup(
    live: Live, clips: list[ClipAddress], scenes: list[int], write: Callable[[str], object]
) -> None:
    """Best effort, every step, whatever failed before it."""
    try:
        live.daw.stop_playing()
    except DawError as exc:
        write(f"could not stop the transport: {exc}\n")
    for index in sorted(scenes, reverse=True):
        try:
            live.send(DELETE_SCENE, index)
            time.sleep(0.05)
        except DawError as exc:
            write(f"could not delete scene {index}: {exc}\n")
    for at in clips:
        try:
            live.daw.delete_clip(at)
        except DawError as exc:
            write(f"could not delete clip {at.track}/{at.scene}: {exc}\n")


def render(findings: list[Finding]) -> str:
    lines = []
    for finding in findings:
        evidence = ", ".join(f"{key}={value}" for key, value in finding.evidence.items())
        lines.append(f"- {finding.question}: **{finding.answer}**  ({evidence})")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", type=int, default=3, help="track to measure on (default KEYS)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    transport = UdpOscTransport(OscSettings(host=args.host, timeout_s=1.0))
    live = Live(transport, args.track)
    write = sys.stderr.write
    findings: list[Finding] = []
    clips: list[ClipAddress] = []
    scenes: list[int] = []
    try:
        live.daw.warm()
        clips = prepare(live)
        live.send(SET_SONG_TIME, 0.0)
        live.daw.start_playing()
        live.wait_until(0.5)

        finding, launch_a = clip_fire_is_quantised(live)
        findings.append(finding)
        findings.append(legato_on_clip_fire(live, launch_a))
        findings.append(legato_on_scene_fire(live, launch_a))
        findings.append(legato_set_just_before_fire(live, launch_a))
        findings.append(second_trigger_replaces_first(live))
        findings.append(track_stop_is_quantised(live))
        findings.append(call_costs(live))
        live.daw.stop_playing()
        time.sleep(0.3)
        findings.append(scene_cap(live, scenes))
    except DawError as exc:
        write(f"spike stopped: {exc}\n")
        return 1
    finally:
        cleanup(live, clips, scenes, write)
        transport.close()
        if findings:
            write(render(findings))
            args.report.write_text(
                json.dumps([asdict(finding) for finding in findings], indent=2) + "\n",
                encoding="utf-8",
            )
            write(f"-> {args.report}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
