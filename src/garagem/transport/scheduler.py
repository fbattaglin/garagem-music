"""Clip-ahead with double scene buffering: the part of the phase that has to be checkable.

The loop, stated plainly, because a reader must be able to verify it against ADR-001:

1. Section N is playing in scene A. Scene B is silent.
2. **The moment N starts, N+1 is written into scene B.** Not near the boundary: a write
   is `ensure_clip` plus `write_notes` per track, four tracks, and Phase 1 measured every
   OSC round trip at ~100 ms on the same control-surface thread the beat listener uses.
   Writing late would compete with the clock for the thread that reports it.
3. N+1 comes from the `ScoreBuffer`. `None` means *play the fallback* — `band.play_section`
   generates it here and now and the event log says `fallback`. In Phase 2 that is the
   only path, because there is no LLM yet; in Phase 3 it becomes the degradation path,
   and P2 says it must sound like music rather than like an error.
4. One bar before the boundary, `fire_scene(B)`. Unconfirmed (ADR-001): at `1 Bar`
   quantisation the launch is up to a bar away, so there is nothing to read back yet.
5. Swap A and B, and repeat.

Three rules the code makes it hard to break, each named where it is enforced:

- **Never write into the scene that is playing** (invariant 6). `_free_scene` is the only
  source of a write target and it is asserted, not assumed.
- **Never wait on generation with the playhead closing in** (P7 in spirit). If N+1 is not
  ready at the boundary the scene simply is not fired, the current clip loops for another
  section's length, and the log says so. A repeat is not a glitch; a gap would be.
- **Every write and every fire is an event, stamped with the beat it happened at.** That
  is where the "zero glitches" criterion is read from — mechanically, out of the log,
  not by watching.

**Bar-driven, not time-driven.** `tick()` makes one bar's worth of decisions from the
clock's current position and returns; `run()` is the thin wrapper that waits for the next
bar and calls it. That split is what lets the whole three-minute run be a unit test:
`tick()` needs no clock of its own, so a test drives it with `FakeDawAdapter.push_beat`
and never sleeps.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Final

from garagem.daw import ClipAddress, DawError, DawPort
from garagem.daw.session import ensure_clip
from garagem.domain import Instrument, Section, SectionScore
from garagem.engines import play_section
from garagem.obs import EventLog
from garagem.transport.buffer import ScoreBuffer
from garagem.transport.clock import NO_BEAT, BarClock
from garagem.transport.render import render_score

# How long `run` will wait for a bar that should be one bar away before deciding the
# transport has stopped. Generous: at 40 BPM a bar is 6 s, and being wrong here means
# ending a performance early.
BAR_TIMEOUT_S: Final = 30.0

# How many bars before the boundary the next scene is fired. One is the minimum that
# still guarantees a full bar of slack against a `1 Bar` launch quantum, and the log
# records the actual slack of every fire so the claim is measured rather than asserted.
FIRE_LEAD_BARS: Final = 1

# How many extra passes of a section to accept before deciding Live is not taking writes.
# A repeat is the right answer to a section that is not ready — the music keeps playing,
# which is P2 — but an unbounded number of them is not a degradation, it is a hang: the
# first live run of `jam.py` looped a verse for four minutes because every write was
# refused and the boundary moved with it. Two passes is about thirty seconds at 132 BPM,
# long enough to survive one bad section and short enough that a command still returns.
MAX_REPEATS: Final = 2


class Scheduler:
    """Plays a sequence of sections through two scenes, writing one ahead."""

    def __init__(
        self,
        daw: DawPort,
        clock: BarClock,
        buffer: ScoreBuffer,
        tracks: Mapping[Instrument, int],
        log: EventLog,
        *,
        scenes: tuple[int, int] = (0, 1),
        fire_lead_bars: int = FIRE_LEAD_BARS,
        seed: int = 0,
    ) -> None:
        self._daw = daw
        self._clock = clock
        self._buffer = buffer
        self._tracks = dict(tracks)
        self._log = log
        self._scenes = scenes
        self._fire_lead_bars = fire_lead_bars
        self._seed = seed

        self._sections: tuple[Section, ...] = ()
        self._index = -1
        self._playing_scene = scenes[0]
        self._start_bar = NO_BEAT
        self._prepared = -1
        self._fired = -1
        self._epoch = 0
        self._repeats = 0
        self.finished = False

    # ---------------------------------------------------------------------------- state

    @property
    def index(self) -> int:
        """Which section is playing. -1 before the first has been fired."""
        return self._index

    @property
    def playing_scene(self) -> int:
        return self._playing_scene

    def free_scene(self) -> int:
        """The scene that is not playing. The only legal write target (invariant 6)."""
        first, second = self._scenes
        return second if self._playing_scene == first else first

    def boundary_bar(self) -> int:
        """The bar at which the current section ends and the next one starts."""
        if self._start_bar == NO_BEAT or not self._sections:
            return NO_BEAT
        return self._start_bar + self._sections[self._index].bars

    # ------------------------------------------------------------------------- the loop

    def run(self, sections: Sequence[Section], seed: int | None = None) -> None:
        """Play the whole form. Returns when the last section has been played out."""
        self.begin(sections, seed)
        while not self.finished:
            if not self._clock.wait_for_bar(self._clock.bar + 1, BAR_TIMEOUT_S):
                # The transport stopped, or Live went quiet. Ending is the honest answer:
                # nothing here retries, and a scheduler that kept firing into a stopped
                # transport would fill the Set with clips nobody asked for.
                break
            self.tick()

    def begin(self, sections: Sequence[Section], seed: int | None = None) -> None:
        """Write the first section into the first scene and fire it."""
        if not sections:
            self.finished = True
            return
        self._sections = tuple(sections)
        if seed is not None:
            self._seed = seed
        self._index = 0
        self._playing_scene = self._scenes[0]
        self._epoch = self._clock.epoch

        score = self._section_score(0)
        self._write(score, self._playing_scene, 0)
        self._daw.fire_scene(self._playing_scene)
        # `first=True` and no slack: there is no predecessor to be late for. Anything
        # reading the log for "every fire had a bar of slack" means the transitions, and
        # this one is the downbeat of the performance.
        self._log.record(
            "scene_fired",
            self._beats(),
            scene=self._playing_scene,
            section=0,
            name=score.section.name,
            slack_bars=0,
            first=True,
        )
        self._fired = 0

    def tick(self) -> bool:
        """One bar's worth of decisions. False once the run is over."""
        if self.finished:
            return False
        bar = self._clock.bar
        if bar == NO_BEAT:
            # Live has not reported a beat yet: the scene was fired and the transport is
            # still catching up to the launch quantum. Nothing to decide.
            return True

        if self._clock.epoch != self._epoch:
            self._on_rewind(bar)
            return True

        if self._start_bar == NO_BEAT:
            self._start_bar = bar
            self._buffer.advance(self._index)

        self._prepare_next()
        self._fire_if_due(bar)
        self._advance_if_past(bar)
        return not self.finished

    # ------------------------------------------------------------------------ the steps

    def _prepare_next(self) -> None:
        """Write N+1 into the silent scene, now rather than near the boundary."""
        following = self._index + 1
        if following >= len(self._sections) or self._prepared >= following:
            return
        scene = self.free_scene()
        try:
            score = self._section_score(following)
            self._write(score, scene, following)
        except DawError as error:
            # Not fatal and not retried (P7): the current clip loops, the next tick tries
            # again, and the log says the write did not land.
            self._log.record(
                "beat_lost", self._beats(), section=following, scene=scene, error=str(error)
            )
            return
        self._prepared = following

    def _fire_if_due(self, bar: int) -> None:
        following = self._index + 1
        boundary = self.boundary_bar()
        if following >= len(self._sections) or self._fired >= following:
            return
        if bar < boundary - self._fire_lead_bars:
            return
        if self._prepared < following:
            # Not ready at the boundary. Do not fire: the current scene loops for another
            # section's length, which is a repeat and not a gap.
            self._log.record("fallback", self._beats(), section=following, reason="not_written")
            return
        scene = self.free_scene()
        self._daw.fire_scene(scene)
        self._log.record(
            "scene_fired",
            self._beats(),
            scene=scene,
            section=following,
            name=self._sections[following].name,
            slack_bars=boundary - bar,
            first=False,
        )
        self._fired = following

    def _advance_if_past(self, bar: int) -> None:
        boundary = self.boundary_bar()
        if bar < boundary:
            return
        if self._index + 1 >= len(self._sections):
            # The last section has played out. Ending here rather than at its fire is
            # what makes `run` return after the music, not before it.
            self.finished = True
            return
        if self._fired <= self._index:
            # The boundary passed without a fire: the clip loops, so the section simply
            # lasts another pass. Move the boundary rather than the music.
            self._repeats += 1
            self._start_bar = boundary
            if self._repeats > MAX_REPEATS:
                self._log.record(
                    "fallback",
                    self._beats(),
                    section=self._index + 1,
                    reason="repeated_too_long",
                    repeats=self._repeats,
                )
                self.finished = True
            return
        self._index += 1
        self._playing_scene = self.free_scene()
        self._start_bar = boundary
        self._repeats = 0
        self._buffer.advance(self._index)

    def _on_rewind(self, bar: int) -> None:
        """The playhead moved. Everything queued was for bars that are not coming."""
        self._epoch = self._clock.epoch
        self._buffer.clear()
        self._prepared = self._index
        self._fired = self._index
        self._start_bar = bar
        self._log.record("beat_lost", self._beats(), reason="rewind", bar=bar)

    # ------------------------------------------------------------------------- plumbing

    def _section_score(self, index: int) -> SectionScore:
        """From the buffer if it is there, from the deterministic floor if it is not."""
        section = self._sections[index]
        score = self._buffer.take(index)
        if score is not None:
            self._log.record(
                "section_generated", self._beats(), section=index, seed=score.seed, source="buffer"
            )
            return score
        seed = self._seed + index
        score = play_section(section, seed)
        self._log.record(
            "fallback", self._beats(), section=index, seed=seed, reason="not_in_buffer"
        )
        return score

    def _write(self, score: SectionScore, scene: int, index: int) -> None:
        """Every track of one section into one scene. Never the scene that is playing."""
        if self._index >= 0 and scene == self._playing_scene and index != self._index:
            raise DawError(
                f"refusing to write section {index} into scene {scene}, which is playing "
                "(invariant 6: never rewrite a clip that is playing)"
            )
        length = score.section.total_beats()
        # Wall time, and only here. `at_beats` is the event's musical position and stays
        # that way (P6); `ms` is how much of a bar the write actually cost, which is the
        # one number `write_lead` has to be sized against and cannot be read in beats.
        started = time.monotonic()
        for instrument, notes in render_score(score).items():
            track = self._tracks.get(instrument)
            if track is None:
                continue
            at = ClipAddress(track=track, scene=scene)
            ensure_clip(self._daw, at, length)
            self._daw.write_notes(at, notes)
        self._log.record(
            "section_written",
            self._beats(),
            section=index,
            scene=scene,
            seed=score.seed,
            notes=sum(len(part.notes) for part in score.parts),
            ms=round((time.monotonic() - started) * 1000.0, 1),
        )

    def _beats(self) -> float:
        beat = self._clock.beat
        return 0.0 if beat == NO_BEAT else float(beat)
