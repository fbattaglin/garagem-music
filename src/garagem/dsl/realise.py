"""Parsed DSL to actual notes, reusing every primitive `theory/` already has.

The DSL gives grids, degrees and voicing names. The scheduler needs `Note`s. This is the
second caller of `degree_to_pitch`, `voice`, `fit_to_range`, `voice_lead` and
`DRUM_VOICES` — the engines were the first, and the fact that both need exactly the same
primitives is the strongest evidence available that `theory/` was cut in the right place.

**This is not a refactoring of the engines and must not become one.** The overlap is
real and the duplication is deliberate: the engines were approved by ear
(`STATUS.md`, Phase 2), and a shared constant is a shared constant — a change made here
for a model's output would silently move music a human already signed off on. Two
callers, one library, no merge.

**The chart is the briefing's, not the model's.** A `CHD` line that disagrees is already
a `section_mismatch` violation (ADR-011); realising against it as well would mean the
scheduler sized a clip from one harmony and wrote another into it.

**The model writes the groove; the arrangement decides where the bars differ.** Measured
across 85 sections and three prompts (`phase-3-findings.md` §11), the model writes one
bar-level line whatever the briefing asks for: zero responses with more than one line,
zero with a crash. So a realised section was a static loop, and the blind A/B that put it
against the engines' arranged eight bars was not comparing grooves — it was comparing
*form*, and form won nine of eleven. Composing the two is what makes that test measure
one variable.

The difference consists of exactly two decisions, both `engines/drums.py`'s and both pure
functions of the briefing: a crash on the first beat of bar 1, and `fill_for(tension)` in
place of the snare and hat of the last. Drums are the whole of it — bass varies with
`tension` but not with bar position, and guitar and keys do neither — so the arrangement
lives in `_drums` and nowhere else. The model keeps its kick, its snare and its hat in
every bar it is asked about.

This is not the merge the paragraph above forbids: `fill_for` is a lookup table that
`engines/groove.py` happens to hold, imported exactly as `humanise` and `separate`
already are. And it is P4 rather than a retreat from it — a variation the model proved it
will not write is a decision we take back, not one we trust it with.

It also closes something latent. `_for_bar` repeats a single line across every bar, so a
model that *did* write `C:x...............` would have put a crash on all eight. The
crash belongs to the arrangement now, and lands once.

Like every engine, this ends with `separate(humanise(...))`. A model's part needs the
release gap exactly as much as a generated one: Live silently truncates a note that
overlaps the next attack of the same pitch, and the write-then-confirm then fails
against a real Set and nowhere else (`phase-2-findings.md` §1).
"""

from __future__ import annotations

from random import Random
from typing import Final

from garagem.domain import (
    SIXTEENTHS_PER_BAR,
    Chord,
    Grid,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
    beats_of,
    parse_grid,
)
from garagem.dsl.lines import BarLine, BassLine, ChordLine, DrumLine
from garagem.dsl.stream import ORDER, ParsedSection
from garagem.engines.groove import fill_for, groove_for
from garagem.engines.humanise import humanise, separate
from garagem.theory.percussion import CLOSED_HAT, CRASH, GHOST_VELOCITY, KICK, SNARE
from garagem.theory.scales import degree_to_pitch
from garagem.theory.voicings import RANGES, Register, fit_to_range, voice, voice_lead

# Deliberately a second copy of the engines' levels rather than a shared import. See the
# module docstring: sharing them would let a change made for model output move music a
# human already approved.
BASE_VELOCITY: Final = 48
DYN_VELOCITY: Final = 13
DOWNBEAT_ACCENT: Final = 10
ACCENT: Final = 14

HIT_BEATS: Final = 0.125
BASS_BEATS: Final = 0.45
MUTED_BEATS: Final = 0.12
RING_BEATS: Final = 0.5

REGISTERS: Final[dict[str, Register]] = {
    "low": Register.LOW,
    "mid": Register.MID,
    "high": Register.HIGH,
}

DRUM_PITCHES: Final[tuple[tuple[str, int], ...]] = (
    ("kick", KICK),
    ("snare", SNARE),
    ("hat", CLOSED_HAT),
    ("crash", CRASH),
)

# The arrangement's two grids. Written as literals, like `engines/groove.py`'s fills, so
# a bar that stopped being sixteen slots long fails at import rather than in the music.
NO_ATTACKS: Final[Grid] = parse_grid("................")
CRASH_HEAD: Final[Grid] = parse_grid("x...............")


# Above the bass's ceiling, as in `engines/keys.py`: two instruments in one octave is mud.
KEYS_FLOOR: Final = RANGES[Instrument.BASS][1] + 1


def realise(parsed: ParsedSection, seed: int) -> SectionScore:
    """Everything that arrived, as a playable score. Seeded, pure, and total.

    Takes a seed rather than a `Random` for the same reason `engines.band.play_section`
    does: a `SectionScore` must be able to name what produced it (invariant 7), and a
    generator handed in mid-stream cannot be re-run. One `Random`, created here.

    Instruments that did not arrive are simply absent — the caller fills them from the
    deterministic engine, which is P2 and is already the scheduler's behaviour for a
    section that never arrived at all.
    """
    section = parsed.section
    rng = Random(seed)
    parts = [
        part
        for instrument in ORDER
        if (part := _part(instrument, parsed.lines.get(instrument, ()), section, rng)) is not None
    ]
    return SectionScore(section=section, parts=tuple(parts), seed=seed)


def _part(
    instrument: Instrument, lines: tuple[BarLine, ...], section: Section, rng: Random
) -> Part | None:
    if not lines:
        return None
    if instrument is Instrument.DRUMS:
        notes = _drums(lines, section)
    elif instrument is Instrument.BASS:
        notes = _bass(lines, section)
    else:
        notes = _chordal(instrument, lines, section)
    return Part(
        instrument=instrument,
        notes=separate(humanise(notes, rng, feel=section.feel)),
    )


def _for_bar(lines: tuple[BarLine, ...], bar: int) -> BarLine:
    """One line covers every bar; N lines fill bars positionally and then repeat.

    Both forms are in the wild — a model writes one line for eight bars and
    `dsl/serialize.py` writes eight — and the modulo is what makes them the same rule.
    """
    return lines[bar % len(lines)]


# --------------------------------------------------------------------------------- drums


def _drums(lines: tuple[BarLine, ...], section: Section) -> list[Note]:
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn
    notes: list[Note] = []
    for bar in range(section.bars):
        line = _for_bar(lines, bar)
        if not isinstance(line, DrumLine):
            continue
        offset = bar * SIXTEENTHS_PER_BAR
        for field, pitch in DRUM_PITCHES:
            grid = _arranged(line, field, bar, section)
            for slot, attack in enumerate(grid):
                if not attack:
                    continue
                notes.append(
                    Note(
                        pitch=pitch,
                        start_beats=beats_of(offset + slot, section.feel),
                        duration_beats=HIT_BEATS,
                        velocity=_accented(velocity, slot),
                    )
                )
    return notes


def _arranged(line: DrumLine, field: str, bar: int, section: Section) -> Grid:
    """The model's grid for this bar, with the section's form imposed on it.

    `engines/drums.py`'s two decisions and only those. The crash is the arrangement's
    outright — a section opens with one and a single bar-level line would otherwise
    repeat it through the section. The fill replaces the last bar's snare and silences
    its hat, and keeps the kick, which is what the engine does and what a drummer does.

    A one-bar section has no last bar to fill: it *is* the section, and a fill would be
    the whole of it. Same guard as the engine's `section.bars > 1`.
    """
    if field == "crash":
        return CRASH_HEAD if bar == 0 else NO_ATTACKS
    if bar == section.bars - 1 and section.bars > 1:
        if field == "snare":
            return fill_for(section.tension)
        if field == "hat":
            return NO_ATTACKS
    grid: Grid = getattr(line, field)
    if field == "hat":
        return _lifted(grid, section)
    return grid


def _lifted(grid: Grid, section: Section) -> Grid:
    """The hat at the subdivision the engine would play for this briefing, never past it.

    The model writes one density whatever `dyn` says — a median of 14 attacks per bar at
    dyn=2, 3 and 4 alike over 85 sections — so its chorus is its verse played louder
    (`phase-3-findings.md` §13). Saying what `dyn` means in the prompt fixes it and costs
    24 points of conformance (§14); composing it costs nothing.

    **The threshold is read off `groove_for`, not chosen.** A first attempt used
    `dyn >= 4`, which is right for straight8 (8 hat hits at dyn 2 and 3, 16 at 4 and 5) and wrong
    for every other feel: shuffle stays at eighths even at dyn=5, because sixteenths on a
    swung hat are not a louder shuffle, they are the end of one. halftime only reaches
    sixteenths at dyn=5. The round-trip property test caught it. So the question asked
    here is not "is dyn high" but "would the engine be playing something finer than this",
    and the engine answers it.

    **The floor is a fixed point by construction.** For an engine-produced section the
    model's hat *is* `groove_for`'s hat, so the first guard always holds and nothing is
    lifted — which is what keeps `test_dsl_round_trip.py` true.
    """
    floor = groove_for(section.feel, section.dyn, section.bpm).hat
    if sum(floor) <= sum(grid):
        return grid
    doubled = _doubled(grid)
    # One doubling at a time, and never denser than the engine itself would play.
    return doubled if sum(doubled) <= sum(floor) else grid


def _doubled(grid: Grid) -> Grid:
    """An attack at the midpoint of every gap: twice the density, the same shape.

    Measured over 85 sections, the model writes one density whatever `dyn` says — a
    median of 14 attacks per bar at dyn=2, dyn=3 and dyn=4 alike — so its chorus is its
    verse played louder (`phase-3-findings.md` §13). Stating what `dyn` means in the
    prompt does fix it and costs 24 points of conformance (§14), because a busier grid is
    a longer thing to miscount. Composing it costs nothing.

    **Doubling rather than overwriting.** Setting the hat to straight sixteenths would
    reach the floor's number and throw away the pattern the model wrote, which is the one
    thing ADR-017 says we keep. Filling the midpoints lifts an eighth-note hat to
    sixteenths (8 attacks to 16, exactly the floor's dyn=4 figure) and a quarter-note hat
    to eighths, in both cases keeping where the model put its accents.

    A gap of one is already maximal and a gap of three has no integer midpoint; neither is
    touched, because inventing a placement is the thing this whole file refuses to do.
    """
    attacks = [slot for slot, attack in enumerate(grid) if attack]
    if not attacks:
        return grid
    filled = set(attacks)
    wrapped = [*attacks[1:], attacks[0] + SIXTEENTHS_PER_BAR]
    for start, end in zip(attacks, wrapped, strict=True):
        gap = end - start
        if gap >= 2 and gap % 2 == 0:
            filled.add((start + gap // 2) % SIXTEENTHS_PER_BAR)
    return tuple(slot in filled for slot in range(SIXTEENTHS_PER_BAR))


# ---------------------------------------------------------------------------------- bass


def _bass(lines: tuple[BarLine, ...], section: Section) -> list[Note]:
    low, high = RANGES[Instrument.BASS]
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn
    notes: list[Note] = []
    for bar in range(section.bars):
        line = _for_bar(lines, bar)
        if not isinstance(line, BassLine):
            continue
        chord = section.chart.at(bar)
        pitch = _inside(degree_to_pitch(chord, line.degree, line.octave), low, high)
        offset = bar * SIXTEENTHS_PER_BAR
        for slot, attack in enumerate(line.rhythm):
            if not attack:
                continue
            ghost = slot in line.ghosts
            notes.append(
                Note(
                    pitch=pitch,
                    start_beats=beats_of(offset + slot, section.feel),
                    duration_beats=BASS_BEATS,
                    velocity=GHOST_VELOCITY - 1 if ghost else _accented(velocity, slot),
                )
            )
    return notes


# ------------------------------------------------------------------------ guitar and keys


def _chordal(instrument: Instrument, lines: tuple[BarLine, ...], section: Section) -> list[Note]:
    velocity = BASE_VELOCITY + DYN_VELOCITY * section.dyn
    notes: list[Note] = []
    previous: tuple[int, ...] = ()
    for bar in range(section.bars):
        line = _for_bar(lines, bar)
        if not isinstance(line, ChordLine):
            continue
        shape = _shape(section.chart.at(bar), line, instrument, previous)
        previous = shape
        offset = bar * SIXTEENTHS_PER_BAR
        length = MUTED_BEATS if line.palm_muted else RING_BEATS
        for slot, attack in enumerate(line.rhythm):
            if not attack:
                continue
            at = beats_of(offset + slot, section.feel)
            level = velocity + (ACCENT if slot in line.accents else 0)
            notes.extend(
                Note(
                    pitch=pitch,
                    start_beats=at,
                    duration_beats=length,
                    velocity=min(127, max(1, level)),
                )
                for pitch in shape
            )
    return notes


def _shape(
    chord: Chord, line: ChordLine, instrument: Instrument, previous: tuple[int, ...]
) -> tuple[int, ...]:
    """Voiced, led from the last chord, and fitted to what the instrument can play."""
    shape = fit_to_range(voice(chord, line.voicing, REGISTERS[line.reg]), instrument)
    shape = fit_to_range(voice_lead(previous, shape), instrument)
    if instrument is Instrument.KEYS:
        shape = _above_the_bass(shape)
    return shape


def _above_the_bass(pitches: tuple[int, ...]) -> tuple[int, ...]:
    ceiling = RANGES[Instrument.KEYS][1]
    while pitches and pitches[0] < KEYS_FLOOR and pitches[-1] + 12 <= ceiling:
        pitches = tuple(pitch + 12 for pitch in pitches)
    return pitches


# -------------------------------------------------------------------------------- helpers


def _accented(velocity: int, slot: int) -> int:
    return min(127, max(1, velocity + (DOWNBEAT_ACCENT if slot % 4 == 0 else 0)))


def _inside(pitch: int, low: int, high: int) -> int:
    while pitch < low:
        pitch += 12
    while pitch > high:
        pitch -= 12
    return pitch
