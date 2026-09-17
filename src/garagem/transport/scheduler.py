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
  not by watching. Every write is also *measured*: the coherence metrics of exactly what
  was written, ending included, which is what Phase 4's amended criterion asks of every
  section and all ADR-019 lets them be.

**Transitions are composed here, at write time, and only when the caller passes them.**
This is the one place that knows which section a score is actually handing over to, and
the one place both sources pass through — a score from the buffer and a fallback from the
floor get the same ending (ADR-020). Composing can in principle break a rule the score
kept, so the result is validated, and a section whose ending would not validate plays as
it was generated, with the log saying so. `endings=None` is Phase 3's scheduler, byte for
byte.

**A person's cues arrive through a `CueQueue`, never a call** (ADR-022). Every one is logged
as `cue_received`, stamped with the beat it arrived at. **A jump cue is acted on** (Stage 3):
the candidate section written before the downbeat is fired for the next bar, and the form
after it is re-planned. Everything else is still only logged. `cues=None` is a scheduler with
no controller, byte for byte.

**A cue must be read inside the bar it arrives in**, or it fires for the bar after next.
Stage 2's gate measured that: 62 of 63 cues read a bar late, one two bars late
(`phase-4-findings.md` §8). So `run` waits for the bar in slices of `WAKE_S` and reads the
queue between them, and a section write reads it between tracks — a cue waits at most one
track's write, not the whole section's.

**Bar cues** — a stop, a fill, drums and bass only — are Stage 4, and their mechanics live in
`transport/bar_cues.py`: variants written a track per bar, fired per track with legato, and
returned from a bar later. The scheduler keeps the timing rules. A bar cue fires for the next
bar or not at all, and it never lands on a section change: in the bar the next section was
fired, or the bar before a boundary, it is declined and logged. A variant is written only in a
tick that wrote no section, and never into the scene a variant is sounding from.

**Boundary cues and the knobs** are Stage 5. "Next: bridge" and "end" re-plan from the first
section that can still change — the next one, if it has not been fired and there are
`REWRITE_BARS` to write it again, otherwise the one after — so they are heard at a section
boundary, by design. The knobs move every section from that point by an offset around the
plan (`engines.arranger.shifted`): read at most once a bar, applied only when the offset
changes, and published through the plan so the model is asked for the moved briefing. The
plan before the offsets is kept, so a knob returned to the middle gives the song back.

**Candidates never move the main scenes' alternation.** A jump plays the candidate from its
own scene; while it plays, both main scenes are silent, and the next section is written into
the first of them. A jump beats a section change fired in the same bar, because Live's last
trigger wins and the person is the one conducting.

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
from garagem.domain import CueFamily, CueKind, Instrument, Macro, MacroKind, Section, SectionScore
from garagem.engines import (
    Ending,
    candidate_for,
    coherence_of,
    compose,
    density_offset,
    endings_for,
    jump_plan,
    play_section,
    shifted,
    tail_bars,
    tension_offset,
)
from garagem.engines.arranger import BRIDGE, CHORUS, OUTRO
from garagem.obs import EventLog
from garagem.theory import validate
from garagem.transport.bar_cues import FILL, STOP, BarCues
from garagem.transport.buffer import ScoreBuffer
from garagem.transport.clock import BEATS_PER_BAR, NO_BEAT, BarClock
from garagem.transport.cues import CueQueue, Received, describe
from garagem.transport.plan import FormPlan
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

# Enough to tell 0.172 from 0.060 — the one difference the corpus ever showed
# (`phase-4-findings.md` §1) — and few enough that the log stays readable.
METRIC_DECIMALS: Final = 3

# How often `run` looks at the cue queue while it waits for the next bar. A bar at 132 BPM
# is 1.82 s; this is about one percent of it, and a wait on a condition costs nothing.
WAKE_S: Final = 0.02

# Which cue jumps to which kind of section. The only jump in Stage 3.
JUMPS: Final[dict[CueKind, str]] = {CueKind.CHORUS_NOW: CHORUS}

# Which cue fires which variant (Stage 4). Drums-and-bass is handled apart: it is a stop of
# two tracks, not a variant.
BAR_VARIANTS: Final[dict[CueKind, str]] = {CueKind.STOP: STOP, CueKind.FILL: FILL}

# How many bars a re-planned next section needs before its fire: one tick to be rewritten
# (a section write is about a bar) and one of slack. Fewer, and the change waits a section.
REWRITE_BARS: Final = 2
BOUNDARY_SEED_STEP: Final = 1_000_000

# Seeds for material that is not a section of the planned form, kept far from `seed + index`
# so a candidate or a re-planned tail never shares a seed with a planned section by accident.
CANDIDATE_SEED: Final = 90_000
JUMP_SEED_STEP: Final = 100_000

# Who wrote a section, as a mark logs it.
MODEL: Final = "model"
FLOOR: Final = "floor"


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
        cues: CueQueue | None = None,
        bar_timeout_s: float = BAR_TIMEOUT_S,
        candidates: Mapping[str, int] | None = None,
        plan: FormPlan | None = None,
        wake_s: float = WAKE_S,
        variants: Mapping[str, Mapping[int, int]] | None = None,
        pitches: Mapping[Instrument, Mapping[int, int]] | None = None,
    ) -> None:
        self._daw = daw
        self._clock = clock
        self._buffer = buffer
        self._tracks = dict(tracks)
        self._log = log
        self._scenes = scenes
        self._fire_lead_bars = fire_lead_bars
        self._seed = seed
        self._cues = cues
        self._bar_timeout_s = bar_timeout_s
        # Kind of section -> the scene its candidate is written into (ADR-022's layout).
        self._candidate_scenes = dict(candidates or {})
        self._plan = plan
        self._wake_s = wake_s
        # Variant kind -> main scene -> variant scene (ADR-022's layout). Empty: no bar cues.
        # What this Set's instruments answer to (`transport.render.Pitches`).
        self._pitches = {instrument: dict(m) for instrument, m in (pitches or {}).items()}
        self._bar_cues = BarCues(daw, tracks, log, self._beats, variants or {}, self._pitches)

        self._sections: tuple[Section, ...] = ()
        self._endings: tuple[Ending, ...] | None = None
        self._index = -1
        self._playing_scene = scenes[0]
        self._start_bar = NO_BEAT
        self._prepared = -1
        self._fired = -1
        self._epoch = 0
        self._repeats = 0
        self.finished = False
        self.stopped_because: str | None = None

        # Written before the downbeat, by kind. A jump can only land on one of these.
        self._candidates: dict[str, SectionScore] = {}
        # A jump fired but not yet heard: the bar it lands on, and the scene it plays from.
        self._boundary_override: int | None = None
        self._jump_scene: int | None = None
        self._jumps = 0
        # Bumped whenever the form is re-planned, so a write that straddled a jump knows
        # the section it wrote is no longer the next one.
        self._generation = 0
        # Stage 5: the plan before the knobs moved it, the offsets in force, the knobs' last
        # positions, and how many boundary cues have re-planned (for their seeds).
        self._base: tuple[Section, ...] = ()
        self._offsets: tuple[int, float] = (0, 0.0)
        self._knobs: dict[MacroKind, float] = {}
        self._knobs_moved = False
        self._replans = 0
        # Who wrote each section as last written, and its seed: what a keep or a veto marks.
        self._authors: dict[int, tuple[str, int]] = {}

    # ---------------------------------------------------------------------------- state

    @property
    def index(self) -> int:
        """Which section is playing. -1 before the first has been fired."""
        return self._index

    @property
    def playing_scene(self) -> int:
        return self._playing_scene

    def free_scene(self) -> int:
        """The main scene that is not playing. The only legal write target (invariant 6).

        While a candidate plays, both main scenes are silent and the first one is used.
        """
        first, second = self._scenes
        if self._playing_scene == first:
            return second
        return first

    def boundary_bar(self) -> int:
        """The bar at which the current section ends and the next one starts.

        After a jump it is the bar the candidate was fired for, whatever the interrupted
        section's length said.
        """
        if self._boundary_override is not None:
            return self._boundary_override
        if self._start_bar == NO_BEAT or not self._sections:
            return NO_BEAT
        return self._start_bar + self._sections[self._index].bars

    @property
    def sections(self) -> tuple[Section, ...]:
        """The form as it stands, after any re-plan."""
        return self._sections

    # ------------------------------------------------------------------------- the loop

    def run(
        self,
        sections: Sequence[Section],
        seed: int | None = None,
        *,
        endings: Sequence[Ending] | None = None,
    ) -> None:
        """Play the whole form. Returns when it has been played out, or when Live stopped.

        `finished` says which. A caller that reports success must check it: at the first
        MiniLab gate a song ended ten seconds in, with Live's arrangement loop sending the
        position back before the second section's bar, and the run returned exactly as if
        it had played to the end (`phase-4-findings.md` §8).

        `stopped_because` says why it did not: `transport_stopped` when the beats simply
        stopped, `position_went_back` when they kept coming but the song position jumped
        back before the next bar — which is what Live's arrangement loop does.
        """
        self.begin(sections, seed, endings=endings)
        waiting_for = self._clock.bar + 1
        deadline = time.monotonic() + self._bar_timeout_s
        while not self.finished:
            if self._clock.wait_for_bar(waiting_for, self._wake_s):
                self.tick()
                waiting_for = self._clock.bar + 1
                deadline = time.monotonic() + self._bar_timeout_s
                continue
            # Inside the bar: a cue read now can still be fired for the next one.
            self._conduct()
            if time.monotonic() < deadline:
                continue
            # The next bar never came. Ending is the honest answer: nothing here retries,
            # and a scheduler that kept firing into a transport it cannot follow would fill
            # the Set with clips nobody asked for. But it is written down, because from
            # inside Python both causes look like silence.
            self.stopped_because = (
                "position_went_back" if self._clock.epoch != self._epoch else "transport_stopped"
            )
            self._log.record(
                "beat_lost",
                self._beats(),
                reason=self.stopped_because,
                bar=self._clock.bar,
                waiting_for_bar=waiting_for,
                section=self._index,
                waited_s=self._bar_timeout_s,
            )
            break
        # A cue struck in the last bar would otherwise be heard and never written down.
        self._conduct()

    def begin(
        self,
        sections: Sequence[Section],
        seed: int | None = None,
        *,
        endings: Sequence[Ending] | None = None,
    ) -> None:
        """Write the first section into the first scene and fire it.

        `endings`, when given, is one per section: how each hands over to the next
        (`engines.endings_for`). Without it every section plays exactly as generated.
        """
        if endings is not None and len(endings) != len(sections):
            raise ValueError(f"one ending per section: {len(endings)} for {len(sections)}")
        if not sections:
            self.finished = True
            return
        self._sections = tuple(sections)
        self._endings = None if endings is None else tuple(endings)
        if seed is not None:
            self._seed = seed
        self._index = 0
        self._playing_scene = self._scenes[0]
        self._epoch = self._clock.epoch
        self._base = self._sections
        if self._plan is not None:
            self._plan.replace(self._sections, self._endings)

        # Before the downbeat, when a write costs nothing musical (ADR-022).
        for kind, scene in self._candidate_scenes.items():
            self._write_candidate(kind, scene)

        score, ending = self._section_score(0)
        self._write(score, self._playing_scene, 0, ending)
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
        """One bar's worth of decisions, then the cues. False once the run is over."""
        if self.finished:
            return False
        self._decide()
        self._conduct()
        return not self.finished

    def _decide(self) -> None:
        bar = self._clock.bar
        if bar == NO_BEAT:
            # Live has not reported a beat yet: the scene was fired and the transport is
            # still catching up to the launch quantum. Nothing to decide.
            return

        if self._clock.epoch != self._epoch:
            self._on_rewind(bar)
            return

        if self._start_bar == NO_BEAT:
            self._start_bar = bar
            self._buffer.advance(self._index)

        self._apply_knobs(bar)
        prepared = self._prepared
        self._prepare_next()
        self._fire_if_due(bar)
        self._advance_if_past(bar)
        if self.finished:
            return
        self._bar_cues.settle(bar, self._index, change_due=self._change_due(bar))
        if self._prepared == prepared and self._bar_cues.enabled:
            # One variant track a bar, and never in a bar that already paid for a section.
            self._bar_cues.write_one((self._index, self._index + 1))

    # ------------------------------------------------------------------------ the steps

    def _prepare_next(self) -> None:
        """Write N+1 into the silent scene, now rather than near the boundary."""
        following = self._index + 1
        if following >= len(self._sections) or self._prepared >= following:
            return
        scene = self.free_scene()
        generation = self._generation
        try:
            score, ending = self._section_score(following)
            self._write(score, scene, following, ending)
        except DawError as error:
            # Not fatal and not retried (P7): the current clip loops, the next tick tries
            # again, and the log says the write did not land.
            self._log.record(
                "beat_lost", self._beats(), section=following, scene=scene, error=str(error)
            )
            return
        if self._generation != generation:
            # A jump re-planned the form while this was being written. What was written is
            # not the next section any more, and the jump has already said what is.
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
            if bar < boundary + self._tail():
                # The last chord is still ringing into the tail its clip carries. Stopping
                # the transport on the beat it ends is what Fabiano heard as an abrupt end
                # (`phase-5-findings.md` §10).
                return
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
        self._bar_cues.section_changed()
        self._playing_scene = (
            self._jump_scene if self._jump_scene is not None else self.free_scene()
        )
        self._start_bar = boundary
        self._boundary_override = None
        self._jump_scene = None
        self._repeats = 0
        self._buffer.advance(self._index)

    def _on_rewind(self, bar: int) -> None:
        """The playhead moved. Everything queued was for bars that are not coming."""
        self._epoch = self._clock.epoch
        self._buffer.clear()
        self._prepared = self._index
        self._fired = self._index
        self._start_bar = bar
        self._boundary_override = None
        self._jump_scene = None
        self._bar_cues.reset()
        self._log.record("beat_lost", self._beats(), reason="rewind", bar=bar)

    # ----------------------------------------------------------------------------- cues

    def _conduct(self) -> None:
        """Log every control that arrived, and act on the jumps. Never waits."""
        if self._cues is None:
            return
        for received in self._cues.drain():
            self._log.record(
                "cue_received",
                float(max(received.beat, 0)),
                bar=_bar_of(received.beat),
                drained_bar=self._clock.bar,
                **describe(received.control),
            )
            control = received.control
            if isinstance(control, Macro):
                # A position, not an event: read at most once a bar, at the next tick.
                self._knobs[control.kind] = control.value
                self._knobs_moved = True
                continue
            if control.kind in JUMPS:
                self._jump(received, control.kind, JUMPS[control.kind])
            elif control.kind in BAR_VARIANTS:
                self._bar_cue(received, control.kind, BAR_VARIANTS[control.kind])
            elif control.kind is CueKind.DRUMS_AND_BASS:
                self._drop(received)
            elif control.kind in (CueKind.NEXT_BRIDGE, CueKind.END):
                self._boundary(received, control.kind)
            elif control.kind.family is CueFamily.MARK:
                self._mark(received, control.kind)

    # -------------------------------------------------------------------------------- marks

    def _mark(self, received: Received, cue: CueKind) -> None:
        """Keep or veto the section that was sounding when the pad was struck (ADR-024).

        Nothing is fired, written or re-planned: a mark changes no sound. It is logged with who
        wrote the section and its seed, and curation reads the take from the log afterwards.
        A strike in the bar a section ended in, read after the next one began, marks the one
        that was heard.
        """
        cue_bar = _bar_of(received.beat)
        if self._index < 0 or self._start_bar == NO_BEAT:
            self._decline(received, cue, "before_the_downbeat")
            return
        index = self._index
        if cue_bar < self._start_bar and index > 0:
            index -= 1
        author, seed = self._authors.get(index, (FLOOR, self._seed + index))
        self._log.record(
            "take_marked",
            self._beats(),
            mark=str(cue),
            cue_bar=cue_bar,
            section=index,
            name=self._sections[index].name,
            author=author,
            seed=seed,
        )

    # ------------------------------------------------------------ boundary cues and knobs

    def _boundary(self, received: Received, cue: CueKind) -> None:
        """Re-plan from the first section that can still change: a bridge next, or the end."""
        bar = self._clock.bar
        at = self._first_changeable(bar)
        declined = self._why_not_boundary(bar, at, cue)
        if declined is not None:
            self._decline(received, cue, declined)
            return
        self._replans += 1
        seed = self._seed + BOUNDARY_SEED_STEP * self._replans
        if cue is CueKind.END:
            outro = candidate_for(self._base, OUTRO, seed)
            base = (*self._base[:at], outro)
        else:
            bridge = candidate_for(self._base, BRIDGE, seed)
            base = jump_plan(self._base, at - 1, bridge, seed)
        self._replan(at, base)
        self._log.record(
            "cue_applied",
            self._beats(),
            cue=str(cue),
            cue_bar=_bar_of(received.beat),
            section=at,
            names=",".join(section.name for section in self._sections[at:]),
        )
        self._log.record(
            "form_replanned",
            self._beats(),
            from_section=at,
            seed=seed,
            sections=len(self._sections),
            names=",".join(section.name for section in self._sections[at:]),
        )

    def _why_not_boundary(self, bar: int, at: int, cue: CueKind) -> str | None:
        if self.finished:
            return "song_over"
        if bar == NO_BEAT or self._start_bar == NO_BEAT:
            return "before_the_downbeat"
        if at >= len(self._sections):
            return "already_ending" if cue is CueKind.END else "no_section_left"
        target = self._sections[at]
        if cue is CueKind.END and target.name == OUTRO and at == len(self._sections) - 1:
            return "already_ending"
        if cue is CueKind.NEXT_BRIDGE and target.name == BRIDGE:
            return "already_next"
        return None

    def _first_changeable(self, bar: int) -> int:
        """The first section a re-plan may still change, and be heard changed."""
        following = self._index + 1
        if self._fired >= following or self._boundary_override is not None:
            return following + 1
        if bar != NO_BEAT and bar + REWRITE_BARS < self.boundary_bar() - self._fire_lead_bars:
            return following
        return following + 1

    def _apply_knobs(self, bar: int) -> None:
        """Move the unwritten song by the knobs' offsets, once a bar, only when they change."""
        if not self._knobs_moved:
            return
        self._knobs_moved = False
        offsets = (
            density_offset(self._knobs.get(MacroKind.DENSITY, 0.5)),
            tension_offset(self._knobs.get(MacroKind.TENSION, 0.5)),
        )
        if offsets == self._offsets:
            return
        self._offsets = offsets
        at = self._first_changeable(bar)
        self._log.record(
            "macro_changed",
            self._beats(),
            density=round(self._knobs.get(MacroKind.DENSITY, 0.5), 3),
            tension=round(self._knobs.get(MacroKind.TENSION, 0.5), 3),
            dyn_offset=offsets[0],
            tension_offset=offsets[1],
            from_section=at,
        )
        if at < len(self._sections):
            self._replan(at, self._base)

    def _replan(self, at: int, base: tuple[Section, ...]) -> None:
        """Sections from `at` become `base`'s, moved by the knobs, and everyone is told."""
        self._base = base
        dyn, tension = self._offsets
        self._sections = (
            *self._sections[:at],
            *(shifted(section, dyn, tension) for section in base[at:]),
        )
        self._endings = None if self._endings is None else endings_for(self._sections)
        self._generation += 1
        self._buffer.discard_from(at)
        self._bar_cues.section_replanned(at)
        if at == self._index + 1:
            # The next section is written but not fired, and there is time: write it again.
            self._prepared = min(self._prepared, self._index)
        if self._plan is not None:
            self._plan.replace(self._sections, self._endings)

    def _bar_cue(self, received: Received, cue: CueKind, variant: str) -> None:
        """Fire a variant for the next bar, or decline it and say why."""
        bar = self._clock.bar
        declined = self._why_not_now(bar) or self._bar_cues.unavailable(
            variant, self._index, self._playing_scene
        )
        if declined is not None:
            self._decline(received, cue, declined)
            return
        pending = self._bar_cues.fire(variant, self._index, self._playing_scene, bar)
        self._log.record(
            "cue_applied",
            self._beats(),
            cue=str(cue),
            cue_bar=_bar_of(received.beat),
            fired_bar=bar + 1,
            scene=pending.variant_scene,
            section=self._index,
            tracks=",".join(str(instrument) for instrument in pending.tracks),
        )

    def _drop(self, received: Received) -> None:
        """Guitar and keys out from the next bar until the next section brings them back."""
        bar = self._clock.bar
        declined = self._why_not_now(bar)
        if declined is not None:
            self._decline(received, CueKind.DRUMS_AND_BASS, declined)
            return
        dropped = self._bar_cues.drop()
        self._log.record(
            "cue_applied",
            self._beats(),
            cue=str(CueKind.DRUMS_AND_BASS),
            cue_bar=_bar_of(received.beat),
            fired_bar=bar + 1,
            section=self._index,
            tracks=",".join(str(instrument) for instrument in dropped),
        )

    def _why_not_now(self, bar: int) -> str | None:
        """The timing rules every bar cue shares (ADR-022)."""
        if self.finished:
            return "song_over"
        if bar == NO_BEAT or self._start_bar == NO_BEAT:
            return "before_the_downbeat"
        if self._change_due(bar):
            # A section change is on its way: a bar cue fired now would land on it, and
            # Live's last trigger would take the new section's tracks away.
            return "section_change"
        return None

    def _change_due(self, bar: int) -> bool:
        """Whether the next bar belongs to another section, fired or about to be."""
        return self._fired > self._index or bar + 1 >= self.boundary_bar()

    def _decline(self, received: Received, cue: CueKind, reason: str) -> None:
        self._log.record(
            "cue_declined",
            self._beats(),
            cue=str(cue),
            cue_bar=_bar_of(received.beat),
            reason=reason,
        )

    def _jump(self, received: Received, cue: CueKind, kind: str) -> None:
        """Fire the candidate for the next bar, then re-plan everything after it.

        The fire comes first and costs one send: it is the only part with a deadline. The
        re-plan is bookkeeping, done while Live counts down to the bar.
        """
        bar = self._clock.bar
        cue_bar = _bar_of(received.beat)
        declined = self._why_not_jump(bar, kind)
        if declined is not None:
            self._log.record(
                "cue_declined", self._beats(), cue=str(cue), cue_bar=cue_bar, reason=declined
            )
            return

        scene = self._candidate_scenes[kind]
        self._daw.fire_scene(scene)

        candidate = self._candidates[kind]
        target = self._index + 1
        self._jumps += 1
        seed = self._seed + JUMP_SEED_STEP * self._jumps
        # The bars of the interrupted section the jump cuts give their time back to the song.
        playing = self._sections[self._index]
        cut_bars = max(0, self.boundary_bar() - (bar + 1))
        cut_seconds = cut_bars * BEATS_PER_BAR * 60.0 / playing.bpm
        sections = jump_plan(
            self._sections, self._index, candidate.section, seed, unplayed_seconds=cut_seconds
        )
        # The tail a jump plans is at the plan's own size; the knobs move it, never the
        # candidate, which was written before the song began.
        self._base = (*self._base[:target], *sections[target:])
        dyn, tension = self._offsets
        sections = (
            *sections[: target + 1],
            *(shifted(section, dyn, tension) for section in sections[target + 1 :]),
        )
        self._sections = sections
        self._endings = None if self._endings is None else endings_for(sections)
        self._generation += 1
        self._boundary_override = bar + 1
        self._jump_scene = scene
        self._prepared = target
        self._fired = target
        self._buffer.discard_from(target)
        self._buffer.written(target)
        # The candidate was written by the floor before the song began.
        self._authors[target] = (FLOOR, candidate.seed)
        self._bar_cues.forget_from(target)
        self._bar_cues.section_written(target, candidate, scene)
        if self._plan is not None:
            self._plan.replace(sections, self._endings)

        self._log.record(
            "cue_applied",
            self._beats(),
            cue=str(cue),
            cue_bar=cue_bar,
            fired_bar=bar + 1,
            scene=scene,
            section=target,
            name=candidate.section.name,
            seed=candidate.seed,
        )
        self._log.record(
            "form_replanned",
            self._beats(),
            from_section=target,
            seed=seed,
            sections=len(sections),
            names=",".join(section.name for section in sections[target:]),
        )
        self._measure(candidate, target)

    def _why_not_jump(self, bar: int, kind: str) -> str | None:
        if self.finished:
            return "song_over"
        if bar == NO_BEAT or self._start_bar == NO_BEAT:
            return "before_the_downbeat"
        if kind not in self._candidates:
            return "no_candidate"
        return None

    # ------------------------------------------------------------------------- plumbing

    def _section_score(self, index: int) -> tuple[SectionScore, Ending | None]:
        """From the buffer if it is there, from the deterministic floor if it is not.

        Then its ending, when this run has endings. Returns the ending that actually plays.
        """
        section = self._sections[index]
        score = self._buffer.take(index)
        if score is not None and score.section != section:
            # Generated for a briefing a jump has since replaced. It must never play.
            self._log.record("fallback", self._beats(), section=index, reason="stale")
            score = None
        if score is not None:
            self._log.record(
                "section_generated", self._beats(), section=index, seed=score.seed, source="buffer"
            )
            self._authors[index] = (MODEL, score.seed)
        else:
            seed = self._seed + index
            score = play_section(section, seed)
            self._log.record(
                "fallback", self._beats(), section=index, seed=seed, reason="not_in_buffer"
            )
            self._authors[index] = (FLOOR, seed)
        return self._ended(score, index)

    def _ended(self, score: SectionScore, index: int) -> tuple[SectionScore, Ending | None]:
        """The section's transition composed over it, unless that would break a rule.

        Declining is not an error and is not retried (P7): the section already ends on the
        fill its generator wrote, which is music, and the log names the rules and the
        ending that was wanted.
        """
        if self._endings is None:
            return score, None
        ending = self._endings[index]
        following = index + 1
        into = self._sections[following] if following < len(self._sections) else None
        composed = compose(score, ending, into=into)
        if composed is score:
            return score, ending
        broken = validate(composed)
        if broken:
            self._log.record(
                "transition_declined",
                self._beats(),
                section=index,
                ending=str(ending),
                rules=",".join(sorted({violation.rule for violation in broken})),
            )
            return score, Ending.FILL
        return composed, ending

    def _write(
        self, score: SectionScore, scene: int, index: int, ending: Ending | None = None
    ) -> None:
        """Every track of one section into one scene. Never the scene that is playing."""
        if self._index >= 0 and scene == self._playing_scene and index != self._index:
            raise DawError(
                f"refusing to write section {index} into scene {scene}, which is playing "
                "(invariant 6: never rewrite a clip that is playing)"
            )
        if scene == self._bar_cues.sounding_scene():
            raise DawError(
                f"refusing to write section {index} into scene {scene}, which a bar cue is "
                "sounding from (invariant 6)"
            )
        ms = self._write_tracks(score, scene, tail_bars(ending) if ending else 0)
        self._log.record(
            "section_written",
            self._beats(),
            section=index,
            scene=scene,
            seed=score.seed,
            # The score's own briefing, not the plan's: what a stale section would betray.
            briefing=score.section.label(),
            notes=sum(len(part.notes) for part in score.parts),
            ms=ms,
            **({} if ending is None else {"ending": str(ending)}),
        )
        self._buffer.written(index)
        self._measure(score, index)
        self._bar_cues.section_written(index, score, scene)

    def _write_candidate(self, kind: str, scene: int) -> None:
        """A section a jump cue can land on, written before the song starts."""
        if scene in self._scenes:
            raise ValueError(f"candidate scene {scene} is a main scene {self._scenes}")
        seed = self._seed + CANDIDATE_SEED + scene
        score = play_section(candidate_for(self._sections, kind, seed), seed)
        try:
            ms = self._write_tracks(score, scene)
        except DawError as error:
            self._log.record(
                "fallback",
                self._beats(),
                reason="candidate_not_written",
                section_kind=kind,
                error=str(error),
            )
            return
        self._candidates[kind] = score
        self._log.record(
            "candidate_written",
            self._beats(),
            section_kind=kind,
            scene=scene,
            seed=seed,
            notes=sum(len(part.notes) for part in score.parts),
            ms=ms,
        )

    def _write_tracks(self, score: SectionScore, scene: int, tail: int = 0) -> float:
        """Every track of a score into one scene; the cost in milliseconds.

        The cue queue is read between tracks: a section write is up to two seconds, and a
        jump that waited for all of it would land a bar late (`phase-4-findings.md` §8).

        `tail` is bars of silence the clip carries past its section, so the song's last chord
        has somewhere to ring (`engines.tail_bars`). Only the final section ever has one.
        """
        length = score.section.total_beats() + tail * BEATS_PER_BAR
        # Wall time, and only here. `at_beats` is the event's musical position and stays
        # that way (P6); `ms` is how much of a bar the write actually cost, which is the
        # one number `write_lead` has to be sized against and cannot be read in beats.
        started = time.monotonic()
        for instrument, notes in render_score(score, pitches=self._pitches).items():
            track = self._tracks.get(instrument)
            if track is None:
                continue
            at = ClipAddress(track=track, scene=scene)
            ensure_clip(self._daw, at, length)
            self._daw.write_notes(at, notes)
            self._conduct()
        return round((time.monotonic() - started) * 1000.0, 1)

    def _measure(self, score: SectionScore, index: int) -> None:
        coherence = coherence_of(score)
        self._log.record(
            "section_measured",
            self._beats(),
            section=index,
            seed=score.seed,
            **{
                name: round(value, METRIC_DECIMALS)
                for name, value in coherence.model_dump().items()
            },
        )

    def _tail(self) -> int:
        """Bars the section playing rings into, past its own last bar. Only a final one does."""
        if self._endings is None or not (0 <= self._index < len(self._endings)):
            return 0
        return tail_bars(self._endings[self._index])

    def _beats(self) -> float:
        beat = self._clock.beat
        return 0.0 if beat == NO_BEAT else float(beat)


def _bar_of(beat: int) -> int:
    return NO_BEAT if beat == NO_BEAT else int(beat // BEATS_PER_BAR)
