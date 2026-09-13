"""Bar cues: a stop, a fill, or the band down to drums and bass, from the next bar (ADR-022).

The scheduler owns *when* — it knows the bar, the boundary and whether a section change is
already on its way — and this owns *what*: which variant clips exist, which tracks a cue
fires, and how those tracks get back to the groove. Kept apart so that the scheduler stays a
thing a person can read, and so every rule below has one place to be tested.

**A variant is written a track at a time, ahead of need.** For the section that is playing
and the one after it, `stop_bars` and `fill_bars` are rendered from the score exactly as it
was written — ending included — into the variant scenes paired with that section's main
scene (4 and 6 for scene 0, 5 and 7 for scene 1). Every variant clip gets legato on. The
fill's drums go first: one track, and the cue most likely to be struck.

**A cue fires only the tracks it changes.** A stop fires all four variant clips; a fill
fires the drums'. Live takes each track over at the next bar at the same position (legato,
measured in Stage 0), so the stopped bar is the bar the person was in.

**The return is a second legato fire, one bar later.** At the bar the variant is heard, the
main clips of those tracks get legato on and are fired for the bar after. Once that has
landed, their legato goes off again, because a main clip with legato on would start its
*next* section mid-way the next time its scene is fired. No return is fired when a section
change is already due at the next bar: that scene fire brings every track back on its own,
and a return fired alongside it would win, as Live's last trigger does.

**Drums and bass is a stop of two tracks, not a variant.** Guitar and keys stop at the next
bar and come back with the next section's scene fire. A stop or fill fired while they are
out leaves them out.

Nothing here decides whether a cue may fire at all — the scheduler asks `unavailable` for
the part that depends on what has been written, and keeps the timing rules to itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from garagem.daw import ClipAddress, DawError, DawPort
from garagem.daw.session import ensure_clip
from garagem.domain import Instrument, SectionScore
from garagem.engines import FillStyle, fill_bars, stop_bars
from garagem.obs import EventLog
from garagem.transport.render import render_part

STOP: Final = "stop"
FILL: Final = "fill"

# The fill a person gets from pad 2. Stage 4's gate heard the snare fill as "não tão clara";
# a blind audition of six fills ranked the run down the toms first and second, and Fabiano
# chose it without the crash on the return (`phase-4-findings.md` §10).
FILL_CUE_STYLE: Final = FillStyle.TOMS


def _fill_cue(score: SectionScore) -> SectionScore:
    return fill_bars(score, FILL_CUE_STYLE)


VARIANTS: Final[dict[str, Callable[[SectionScore], SectionScore]]] = {
    STOP: stop_bars,
    FILL: _fill_cue,
}

# Which tracks each variant changes — and therefore fires, and returns.
TRACKS: Final[dict[str, tuple[Instrument, ...]]] = {
    STOP: (Instrument.DRUMS, Instrument.BASS, Instrument.GUITAR, Instrument.KEYS),
    FILL: (Instrument.DRUMS,),
}

# Write order: the fill's single track first, then the stop's four.
WRITE_ORDER: Final[tuple[tuple[str, Instrument], ...]] = (
    (FILL, Instrument.DRUMS),
    *((STOP, instrument) for instrument in TRACKS[STOP]),
)

DROPPED: Final[tuple[Instrument, ...]] = (Instrument.GUITAR, Instrument.KEYS)


@dataclass(slots=True)
class Pending:
    """A variant fired, and where its return stands."""

    kind: str
    index: int
    main_scene: int
    variant_scene: int
    tracks: tuple[Instrument, ...]
    launch_bar: int
    return_bar: int | None = None


class BarCues:
    """Variant clips, bar cue fires and the way back to the groove."""

    def __init__(
        self,
        daw: DawPort,
        tracks: Mapping[Instrument, int],
        log: EventLog,
        beats: Callable[[], float],
        scenes: Mapping[str, Mapping[int, int]],
    ) -> None:
        self._daw = daw
        self._tracks = dict(tracks)
        self._log = log
        self._beats = beats
        # Variant kind -> main scene -> the scene its variant is written into.
        self._scenes = {kind: dict(pairs) for kind, pairs in scenes.items()}
        self._written: dict[int, tuple[SectionScore, int]] = {}
        self._variants: dict[tuple[int, str], SectionScore] = {}
        self._ready: dict[tuple[int, str], set[Instrument]] = {}
        self._pending: Pending | None = None
        self._dropped: set[Instrument] = set()
        self._legato_on: set[ClipAddress] = set()

    @property
    def enabled(self) -> bool:
        return bool(self._scenes)

    @property
    def pending(self) -> Pending | None:
        return self._pending

    def sounding_scene(self) -> int | None:
        """The variant scene a cue has fired and not yet returned from. Never written."""
        return None if self._pending is None else self._pending.variant_scene

    # ------------------------------------------------------------------ what was written

    def section_written(self, index: int, score: SectionScore, scene: int) -> None:
        """A main section landed in `scene`: its variants are now unwritten."""
        self._written[index] = (score, scene)
        for key in [key for key in self._ready if key[0] == index]:
            del self._ready[key]
        for key in [key for key in self._variants if key[0] == index]:
            del self._variants[key]
        for old in [old for old in self._written if old < index - 1]:
            del self._written[old]

    def forget_from(self, index: int) -> None:
        """A jump: sections from `index` on were re-planned, and every track is relaunched."""
        for key in [key for key in self._written if key >= index]:
            del self._written[key]
        self._pending = None
        self._dropped.clear()

    def section_replanned(self, index: int) -> None:
        """Sections from `index` on were re-planned; nothing already sounding changed."""
        for key in [key for key in self._written if key >= index]:
            del self._written[key]

    def section_changed(self) -> None:
        """A new section started from its own scene fire: guitar and keys are back."""
        self._dropped.clear()

    def reset(self) -> None:
        self._pending = None
        self._dropped.clear()

    # ------------------------------------------------------------------------ the cues

    def unavailable(self, kind: str, index: int, playing_scene: int) -> str | None:
        """Why this variant cannot fire for the section playing now, if it cannot."""
        scene = self._scenes.get(kind, {}).get(playing_scene)
        written = self._written.get(index)
        if scene is None or written is None or written[1] != playing_scene:
            return "no_variant"
        ready = self._ready.get((index, kind), set())
        if not set(TRACKS[kind]) <= ready:
            return "unavailable"
        return None

    def fire(self, kind: str, index: int, playing_scene: int, bar: int) -> Pending:
        """Fire the variant's tracks for the next bar. Guitar and keys stay out if dropped."""
        scene = self._scenes[kind][playing_scene]
        tracks = tuple(
            instrument
            for instrument in TRACKS[kind]
            if instrument not in self._dropped and instrument in self._tracks
        )
        for instrument in tracks:
            self._daw.fire_clip(ClipAddress(track=self._tracks[instrument], scene=scene))
        self._pending = Pending(
            kind=kind,
            index=index,
            main_scene=playing_scene,
            variant_scene=scene,
            tracks=tracks,
            launch_bar=bar + 1,
        )
        return self._pending

    def drop(self) -> tuple[Instrument, ...]:
        """Stop guitar and keys at the next bar."""
        dropped = tuple(instrument for instrument in DROPPED if instrument in self._tracks)
        for instrument in dropped:
            self._daw.stop_track(self._tracks[instrument])
        self._dropped.update(dropped)
        return dropped

    # ---------------------------------------------------------------------- the return

    def settle(self, bar: int, index: int, change_due: bool) -> None:
        """Fire the return when the variant is heard, and tidy legato once it has landed.

        `change_due` means a section change lands at the next bar, whoever fired it.
        """
        pending = self._pending
        if pending is not None:
            if pending.index != index:
                self._pending = None
            elif bar < pending.launch_bar:
                pass
            elif pending.return_bar is None:
                self._return(pending, bar, change_due)
            elif bar >= pending.return_bar:
                self._pending = None
        if self._legato_on and (self._pending is None or self._pending.return_bar is None):
            self._legato_off()

    def _return(self, pending: Pending, bar: int, change_due: bool) -> None:
        if change_due:
            self._log.record(
                "variant_returned",
                self._beats(),
                section=pending.index,
                variant=pending.kind,
                via="section_change",
            )
            self._pending = None
            return
        mains = [
            ClipAddress(track=self._tracks[instrument], scene=pending.main_scene)
            for instrument in pending.tracks
            if instrument not in self._dropped
        ]
        for at in mains:
            self._daw.set_clip_legato(at, True)
            self._legato_on.add(at)
        for at in mains:
            self._daw.fire_clip(at)
        pending.return_bar = bar + 1
        self._log.record(
            "variant_returned",
            self._beats(),
            section=pending.index,
            variant=pending.kind,
            via="legato",
            fired_bar=bar + 1,
            late_bars=bar - pending.launch_bar,
        )

    def _legato_off(self) -> None:
        for at in sorted(self._legato_on, key=lambda address: (address.track, address.scene)):
            try:
                self._daw.set_clip_legato(at, False)
            except DawError as error:
                self._log.record(
                    "beat_lost",
                    self._beats(),
                    reason="legato_not_reset",
                    track=at.track,
                    scene=at.scene,
                    error=str(error),
                )
        self._legato_on.clear()

    # ------------------------------------------------------------------- the variants

    def write_one(self, indices: tuple[int, ...]) -> bool:
        """Write the first missing variant track for these sections. True if one was written."""
        for index in indices:
            written = self._written.get(index)
            if written is None:
                continue
            score, main_scene = written
            for kind, instrument in WRITE_ORDER:
                scene = self._scenes.get(kind, {}).get(main_scene)
                if scene is None or instrument not in self._tracks:
                    continue
                ready = self._ready.setdefault((index, kind), set())
                if instrument in ready or scene == self.sounding_scene():
                    continue
                self._write_track(index, kind, score, instrument, scene)
                return True
        return False

    def _write_track(
        self, index: int, kind: str, score: SectionScore, instrument: Instrument, scene: int
    ) -> None:
        variant = self._variants.get((index, kind))
        if variant is None:
            variant = VARIANTS[kind](score)
            self._variants[(index, kind)] = variant
        at = ClipAddress(track=self._tracks[instrument], scene=scene)
        try:
            ensure_clip(self._daw, at, score.section.total_beats())
            self._daw.write_notes(at, render_part(variant.part(instrument)))
            self._daw.set_clip_legato(at, True)
        except DawError as error:
            self._log.record(
                "beat_lost",
                self._beats(),
                reason="variant_not_written",
                section=index,
                variant=kind,
                instrument=str(instrument),
                error=str(error),
            )
            return
        self._ready[(index, kind)].add(instrument)
        self._log.record(
            "variant_written",
            self._beats(),
            section=index,
            variant=kind,
            instrument=str(instrument),
            scene=scene,
        )
