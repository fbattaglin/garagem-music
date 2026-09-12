"""Coherence metrics: the half of "is this good" that a machine can measure.

Phase 3's blind A/B came out at parity, and the reasons Fabiano gave beside each vote
said why. The floor won **3 of 3** pairs decided on *"cleaner, less messy"*; the model won
4 of 6 decided on *"less boring"* or *"just sounds nicer"*. The model writes more
interesting material and messier material, and the two cancel (`phase-3-findings.md` §16).

Interesting is not measurable here. **Messy is**, and §16 named the mechanisms: pitches
outside the chart and instruments piled into one octave. Those two are what `messiness`
aggregates. All four metrics ADR-000 §7 asks for are computed and reported; see
`MESSINESS_PARTS` for why only two of them compose.

**§16's mechanism was measured and refuted.** Over 112 recorded model sections,
`register_spread` is 1.000 for every one of them and for every floor section: the DSL
never lets a model name a pitch, so out-of-chart notes and a band piled into one octave
are things the architecture forbids it to produce (`phase-4-findings.md` §1). Those two
metrics are computed and reported because ADR-000 §7 asks for them, and they compose into
nothing.

What `messiness` reads instead is `kit_collision`, the one measured difference that points
the same way as the three votes. **Two blind listens disagreed with it** — 6 of 10 as a
label, 5 of 16 as a preference with the sign inverted (`phase-4-findings.md` §3, §5) — so
under ADR-019 every metric here is telemetry: logged for every section the scheduler
writes, and never a target.

Every metric returns a fraction in `[0, 1]` where **1 is the good end**, so a composite
needs no sign-juggling and a report reads the same way down every column.

`density_against_tension` takes its reference as an argument rather than computing one.
The engine already knows what a dynamic means for each feel — `groove_for` answers it, and
shuffle is not straight8 played louder — but `engines/` imports `theory/`, so asking the
question the other way round would invert the dependency. `engines/coherence.py` supplies
the number; this module only compares against it.
"""

from __future__ import annotations

from statistics import fmean

from pydantic import BaseModel, ConfigDict, Field

from garagem.domain import PITCH_CLASSES, Instrument, Part, SectionScore
from garagem.theory.percussion import KICK, SNARE
from garagem.theory.scales import pitch_classes
from garagem.theory.validator import chart_pitch_classes, grid_slots, nearest_slot
from garagem.theory.voicings import RANGES

# One measure, not an average of five. Each exclusion below was measured on the corpus
# rather than argued, and averaging a real signal with four constants would only dilute it.
#
# **Harmonic conformance and register spread are out**: 0.998 and 1.000 on the model,
# 0.996 and 1.000 on the floor. The realiser builds every pitched note from a chart degree
# and a register band, so neither failure is reachable (`phase-4-findings.md` §1).
#
# **Density is out** because a section too quiet for its briefing is *boring*, which is
# the other half of §16's split and the half the model was already winning.
#
# **Bass/kick alignment is out** because the deterministic floor scores 0.33 to 1.00 on
# it across feels — a halftime bridge puts kicks on 1 and 2.5 and 4 under a bass playing
# half notes, and only the downbeat coincides. A measure whose clean reference spans the
# whole range cannot be what separates clean from messy.
MESSINESS_PARTS = ("kit_collision",)


class Coherence(BaseModel):
    """One section, scored. Every field is a fraction where 1 is the good end."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    harmonic_conformance: float = Field(ge=0.0, le=1.0)
    register_spread: float = Field(ge=0.0, le=1.0)
    bass_kick_alignment: float = Field(ge=0.0, le=1.0)
    density_against_tension: float = Field(ge=0.0, le=1.0)
    kit_collision: float = Field(ge=0.0, le=1.0)

    @property
    def messiness(self) -> float:
        """0 is clean. The composite the calibration set is used to falsify."""
        return 1.0 - fmean(getattr(self, name) for name in MESSINESS_PARTS)


def _pitched(score: SectionScore) -> list[Part]:
    return [part for part in score.parts if part.instrument is not Instrument.DRUMS and part.notes]


def harmonic_conformance(score: SectionScore) -> float:
    """The share of pitched notes whose pitch class the section actually admits.

    Chord tones count alongside the scale, for the reason `chart_pitch_classes` gives: a
    B7 in E minor has a D#, and a metric that called that a mistake would score every
    borrowed dominant as mess.

    Pooled over parts rather than averaged across them, so a four-note keys pad cannot
    outvote a forty-note bass line.
    """
    section = score.section
    parts = _pitched(score)
    if not parts:
        return 1.0
    allowed = pitch_classes(section.key, section.scale) | chart_pitch_classes(section.chart)
    notes = [note for part in parts for note in part.notes]
    inside = sum(1 for note in notes if note.pitch % PITCH_CLASSES in allowed)
    return inside / len(notes)


def register_spread(score: SectionScore) -> float:
    """How far apart the instruments sit, against how far apart they are built to sit.

    "Piled into one octave" is the failure this names. Each part is reduced to the mean
    pitch it occupies, and the spread of those means is compared with the spread implied
    by `RANGES` — the midpoints of the instruments that are actually playing, which is the
    arrangement those ranges describe. A band spread wider than its reference scores 1.0
    rather than being rewarded for extremes.

    One pitched part cannot be piled against anything, and scores 1.0.
    """
    parts = _pitched(score)
    if len(parts) < 2:
        return 1.0
    centroids = [fmean(note.pitch for note in part.notes) for part in parts]
    nominal = [fmean(RANGES[part.instrument]) for part in parts if part.instrument in RANGES]
    if len(nominal) < 2:
        return 1.0
    reference = max(nominal) - min(nominal)
    if reference <= 0:
        return 1.0
    return min(1.0, (max(centroids) - min(centroids)) / reference)


def bass_kick_alignment(score: SectionScore) -> float:
    """The share of kicks that have a bass note on them.

    Deliberately one-directional, and the direction was chosen against the floor rather
    than reasoned about. The first version took the harmonic mean of this and the share of
    *bass notes* landing on a kick, to stop a bass spraying sixteenths from scoring
    perfectly by covering everything. Measured on the engines, that scored 0.40 on a verse
    and 0.67 on a chorus — the deterministic floor, the one reference this project has
    approved by ear, failing a metric meant to detect mess.

    The reason is that the floor's bass plays eighths against two kicks in a bar: recall
    1.00, precision 0.25. Every kick is supported and the extra notes are a bass line, not
    a collision. A bass that covers everything *is* caught, by
    `density_against_tension`, and counting it twice inside `messiness` would weigh
    density above the two measures §16 actually points at.

    Onsets are compared on grid slots, not on raw beats: `humanise` pushes notes off the
    grid on purpose, and a metric that read that as disagreement would be measuring the
    humaniser.
    """
    present = score.instruments()
    if Instrument.BASS not in present or Instrument.DRUMS not in present:
        return 1.0
    bass, drums = score.part(Instrument.BASS), score.part(Instrument.DRUMS)
    if not bass.notes:
        return 1.0
    slots = grid_slots(score.section)
    kicks = {nearest_slot(slots, note.start_beats) for note in drums.notes if note.pitch == KICK}
    if not kicks:
        return 1.0
    bass_slots = {nearest_slot(slots, note.start_beats) for note in bass.notes}
    return len(kicks & bass_slots) / len(kicks)


def density_against_tension(score: SectionScore, reference_attacks: float) -> float:
    """Drum attacks per bar against what this briefing asks for.

    `reference_attacks` is the engine's own answer for the section's feel and dynamic —
    see the module docstring for why it arrives as an argument.

    Scored as a ratio rather than a difference, so that half as busy as asked and twice as
    busy come out equally wrong. `dyn` is a target and not a floor, and a difference would
    have made "too busy" unboundedly worse than "too quiet" — which is the opposite of
    what §16 found, where the model's failure was mess and not silence.
    """
    if Instrument.DRUMS not in score.instruments() or reference_attacks <= 0:
        return 1.0
    actual = len(score.part(Instrument.DRUMS).notes) / score.section.bars
    if actual <= 0:
        return 0.0
    return min(actual, reference_attacks) / max(actual, reference_attacks)


def kit_collision(score: SectionScore) -> float:
    """The share of struck slots where the kick and the snare are *not* fighting for one.

    The only measured difference between model output and the floor that points the same
    way as §16's three "cleaner, less messy" votes: the model stacks a kick and a snare on
    the same sixteenth 0.172 of the time against the curated grooves' 0.060, nearly three
    times as often (`phase-4-findings.md` §1).

    Kick and snare only. A hat sounds with everything and is supposed to — folding it in
    would bury the signal under the one simultaneity that is never mess. And two drums in
    one slot is not forbidden: the floor does it 6% of the time, deliberately. This counts
    how often, not whether.

    Slots, not raw beats, for the reason `bass_kick_alignment` gives: `humanise` moves
    notes off the grid on purpose.
    """
    if Instrument.DRUMS not in score.instruments():
        return 1.0
    slots = grid_slots(score.section)
    notes = score.part(Instrument.DRUMS).notes
    kicks = {nearest_slot(slots, note.start_beats) for note in notes if note.pitch == KICK}
    snares = {nearest_slot(slots, note.start_beats) for note in notes if note.pitch == SNARE}
    struck = kicks | snares
    if not struck:
        return 1.0
    return 1.0 - len(kicks & snares) / len(struck)
