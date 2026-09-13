"""The song's form: which sections, in which order, chosen from a seeded policy.

The phase's exit criterion asks for three minutes of **autonomous** arrangement, so the
form has to come from somewhere that is not a person typing it. It comes from here, and
it is reproducible: the same brief and the same seed give the same song, byte for byte,
which is invariant 7 and what puts a form in the event log as a single integer.

**A weighted transition table, not a random walk.** What may follow a chorus is a short,
arguable list — and it is written here as data precisely so it can be argued with. A walk
over all section kinds would produce sequences no band has ever played and give nobody
anything to disagree with.

**Charts are diatonic, derived from the brief's key and scale.** Nothing here writes
`Em`: it asks for degree 1 of the section's scale and lets `theory/` say what that chord
is. The same policy therefore works in every key and in both modalities, and a chart can
never fall outside its own key.

A written form file can be layered on top later without touching this module: `arrange`
returns sections, and the scheduler does not care who chose them.
"""

from __future__ import annotations

from collections.abc import Sequence
from random import Random
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from garagem.domain import MAX_DYN, MIN_DYN, PITCH_CLASSES, Chart, Chord, Feel, Quality, Section
from garagem.theory.errors import TheoryError
from garagem.theory.scales import DEGREES, steps_of

FROZEN = ConfigDict(frozen=True, extra="forbid")

INTRO: Final = "intro"
VERSE: Final = "verse"
CHORUS: Final = "chorus"
BRIDGE: Final = "bridge"
OUTRO: Final = "outro"


class SongBrief(BaseModel):
    """What the whole song is, before anyone decides what happens in it."""

    model_config = FROZEN

    key: int = Field(ge=0, le=PITCH_CLASSES - 1)
    scale: str = Field(min_length=1)
    bpm: float = Field(gt=20.0, lt=999.0)
    feel: Feel
    minimum_seconds: float = Field(gt=0.0)


class Shape(BaseModel):
    """What a kind of section is like. Read this table to know what the band plays."""

    model_config = FROZEN

    bars: int = Field(ge=1, le=32)
    dyn: int = Field(ge=1, le=5)
    tension: float = Field(ge=0.0, le=1.0)


SHAPES: Final[dict[str, Shape]] = {
    INTRO: Shape(bars=4, dyn=1, tension=0.20),
    VERSE: Shape(bars=8, dyn=2, tension=0.35),
    CHORUS: Shape(bars=8, dyn=4, tension=0.70),
    BRIDGE: Shape(bars=8, dyn=3, tension=0.55),
    OUTRO: Shape(bars=4, dyn=2, tension=0.15),
}

# What may follow what, and how often. No kind may follow itself: two identical adjacent
# sections is a repeat, and a repeat is what a longer section is for.
TRANSITIONS: Final[dict[str, tuple[tuple[str, int], ...]]] = {
    INTRO: ((VERSE, 1),),
    VERSE: ((CHORUS, 6), (BRIDGE, 1)),
    CHORUS: ((VERSE, 5), (BRIDGE, 3)),
    BRIDGE: ((CHORUS, 7), (VERSE, 1)),
}

# Chart shapes as scale degrees, per modality. Two per kind, so a seed has something to
# choose and a song does not always use the same four chords.
MINOR_CHARTS: Final[dict[str, tuple[tuple[int, ...], ...]]] = {
    INTRO: ((1, 1), (1, 7)),
    VERSE: ((1, 6, 3, 7), (1, 1, 6, 7)),
    CHORUS: ((6, 7, 1, 1), (4, 6, 7, 1)),
    BRIDGE: ((4, 7, 3, 6), (6, 3, 4, 7)),
    OUTRO: ((1, 6, 1, 1), (1, 7, 1, 1)),
}

MAJOR_CHARTS: Final[dict[str, tuple[tuple[int, ...], ...]]] = {
    INTRO: ((1, 1), (1, 5)),
    VERSE: ((1, 5, 6, 4), (1, 6, 4, 5)),
    CHORUS: ((4, 5, 1, 1), (1, 4, 5, 5)),
    BRIDGE: ((6, 4, 1, 5), (2, 5, 1, 6)),
    OUTRO: ((1, 4, 1, 1), (1, 5, 1, 1)),
}

MINOR_THIRD: Final = 3

# How much bigger the last chorus is than the others: one step of `dyn`, a little more
# tension. One step, because `dyn` indexes the groove table and two would skip a pattern.
CLIMAX_DYN: Final = 1
CLIMAX_TENSION: Final = 0.1

# How far the MiniLab's knobs move the song from its plan (ADR-021, Stage 5). A knob is an
# offset around the plan, centred: at the middle of its travel the song is as arranged, and
# at either end every section is up to this much sparser or busier, tenser or calmer. An
# absolute knob would set a verse and a chorus to the same `dyn` and flatten the very shape
# the arrangement exists to give — so the shape is kept, and moved as a whole.
MACRO_DYN_RANGE: Final = 2
MACRO_TENSION_RANGE: Final = 0.3
SECONDS_PER_MINUTE: Final = 60.0
BEATS_PER_BAR: Final = 4.0


def arrange(brief: SongBrief, seed: int) -> tuple[Section, ...]:
    """A whole song's form: `intro verse chorus ... outro`, at least as long as asked.

    Length is met by adding sections, never by stretching one: the criterion counts
    section changes as well as seconds, and a single very long verse would satisfy the
    clock while proving nothing about the scheduler.
    """
    charts = _charts_for(brief.scale)
    rng = Random(seed)

    kinds = [INTRO]
    seconds = _seconds(brief, INTRO)
    while seconds < brief.minimum_seconds:
        options, weights = zip(*TRANSITIONS[kinds[-1]], strict=True)
        kind = rng.choices(options, weights=weights, k=1)[0]
        kinds.append(kind)
        seconds += _seconds(brief, kind)
    kinds.append(OUTRO)

    return tuple(_section(brief, kind, charts, rng) for kind in kinds)


def with_climax(form: Sequence[Section]) -> tuple[Section, ...]:
    """The same song with its last chorus lifted above the others: the dynamics curve.

    Every chorus in `SHAPES` is the same size, so a song that repeats one five times has a
    level rather than a shape. Lifting the last is the smallest change that gives it a peak,
    and it is where a band would put one. A song with one chorus has nothing to rise above
    and comes back as it was.

    A separate function rather than a change to `arrange`, so the form a seed produced
    before Phase 4 stays reachable: `scripts/jam.py --plain` plays it.
    """
    choruses = [index for index, section in enumerate(form) if section.name == CHORUS]
    if len(choruses) < 2:
        return tuple(form)
    return _lift_last_chorus(form)


def candidate_for(form: Sequence[Section], kind: str, seed: int) -> Section:
    """The section a jump cue to `kind` lands on, decided before the song starts (ADR-022).

    It has to be written before the downbeat, so it cannot wait to see where the song is.
    It is the song's own first section of that kind, at that kind's ordinary size: the chorus
    the person has heard, or is about to, rather than a stranger. A form without one gets a
    fresh section of the kind from the seed, in the song's key.
    """
    for section in form:
        if section.name == kind:
            shape = SHAPES[kind]
            return section.model_copy(update={"dyn": shape.dyn, "tension": shape.tension})
    reference = form[0]
    rng = Random(seed)
    return _section(_brief_like(reference), kind, _charts_for(reference.scale), rng)


def continue_from(reference: Section, kind: str, seed: int, seconds: float) -> tuple[Section, ...]:
    """What follows a section of `kind`: sections lasting as close to `seconds` as the walk
    allows, *including* the outro that ends them.

    The same weighted walk as `arrange`, started from a kind instead of from the intro, in the
    reference section's key, scale, tempo and feel. Unlike `arrange`, which must reach its
    minimum, this aims at a length: a section is added only if it brings the tail closer to
    `seconds` than stopping would. No time left is still an ending — the outro alone.
    """
    brief = _brief_like(reference)
    charts = _charts_for(reference.scale)
    rng = Random(seed)
    budget = seconds - _seconds(brief, OUTRO)
    kinds: list[str] = []
    elapsed = 0.0
    last = kind
    while last in TRANSITIONS:
        options, weights = zip(*TRANSITIONS[last], strict=True)
        following = rng.choices(options, weights=weights, k=1)[0]
        length = _seconds(brief, following)
        if abs(budget - (elapsed + length)) >= abs(budget - elapsed):
            break
        kinds.append(following)
        elapsed += length
        last = following
    kinds.append(OUTRO)
    return tuple(_section(brief, name, charts, rng) for name in kinds)


def jump_plan(
    form: Sequence[Section],
    playing: int,
    candidate: Section,
    seed: int,
    *,
    unplayed_seconds: float = 0.0,
) -> tuple[Section, ...]:
    """The form after a jump from section `playing` to `candidate`.

    What has played stays, the candidate comes next, and a new tail follows it. **A jump
    reshapes the song rather than lengthening it:** the tail, outro included, fills what the
    planned sections after `playing` would have lasted, plus `unplayed_seconds` — the part of
    the interrupted section the jump cut — less the candidate.

    Stage 3's gate is why that sentence has a clause for the outro. Before it, the tail's
    budget still counted the old outro and then added a new one, and the walk ran past its
    budget by up to a section: ten jumps turned a 102-second song into 216 seconds
    (`phase-4-findings.md` §9).

    The climax moves to the tail's last chorus — never onto the candidate, which was written
    before the song began and cannot be lifted after.
    """
    remaining = sum(section.total_seconds() for section in form[playing + 1 :])
    budget = remaining + unplayed_seconds - candidate.total_seconds()
    tail = continue_from(form[playing], candidate.name, seed, budget)
    return (*form[: playing + 1], candidate, *_lift_last_chorus(tail))


def density_offset(knob: float) -> int:
    """A knob position, 0 to 1, as whole steps of `dyn` around the plan: 0.5 is no change."""
    return round((knob - 0.5) * 2 * MACRO_DYN_RANGE)


def tension_offset(knob: float) -> float:
    """A knob position, 0 to 1, as tension around the plan, in steps of 0.05."""
    return round(round((knob - 0.5) * 2 * MACRO_TENSION_RANGE / 0.05) * 0.05, 2)


def shifted(section: Section, dyn: int, tension: float) -> Section:
    """`section` moved by the knobs' offsets, kept inside what a `Section` may be."""
    if dyn == 0 and tension == 0.0:
        return section
    return section.model_copy(
        update={
            "dyn": min(MAX_DYN, max(MIN_DYN, section.dyn + dyn)),
            "tension": min(1.0, max(0.0, round(section.tension + tension, 2))),
        }
    )


def _lift_last_chorus(form: Sequence[Section]) -> tuple[Section, ...]:
    choruses = [index for index, section in enumerate(form) if section.name == CHORUS]
    if not choruses:
        return tuple(form)
    last = choruses[-1]
    peak = form[last]
    lifted = peak.model_copy(
        update={
            "dyn": min(MAX_DYN, peak.dyn + CLIMAX_DYN),
            "tension": min(1.0, round(peak.tension + CLIMAX_TENSION, 2)),
        }
    )
    return (*form[:last], lifted, *form[last + 1 :])


def _brief_like(section: Section) -> SongBrief:
    """The song a section belongs to, as far as generating more of it needs."""
    return SongBrief(
        key=section.key,
        scale=section.scale,
        bpm=section.bpm,
        feel=section.feel,
        minimum_seconds=section.total_seconds(),
    )


def _section(
    brief: SongBrief,
    kind: str,
    charts: dict[str, tuple[tuple[int, ...], ...]],
    rng: Random,
) -> Section:
    shape = SHAPES[kind]
    degrees = rng.choice(charts[kind])
    return Section(
        name=kind,
        bars=shape.bars,
        key=brief.key,
        scale=brief.scale,
        feel=brief.feel,
        bpm=brief.bpm,
        dyn=shape.dyn,
        tension=shape.tension,
        chart=Chart(chords=tuple(diatonic(brief.key, brief.scale, degree) for degree in degrees)),
    )


def _seconds(brief: SongBrief, kind: str) -> float:
    return SHAPES[kind].bars * BEATS_PER_BAR * SECONDS_PER_MINUTE / brief.bpm


def _charts_for(scale: str) -> dict[str, tuple[tuple[int, ...], ...]]:
    steps = steps_of(scale)
    if len(steps) != DEGREES:
        raise TheoryError(
            f"a song needs a seven-note scale to build chords on, {scale!r} has {len(steps)}"
        )
    return MINOR_CHARTS if steps[2] <= MINOR_THIRD else MAJOR_CHARTS


def diatonic(key: int, scale: str, degree: int) -> Chord:
    """The triad on `degree` of `scale` in `key`. Stacked thirds, classified by ear.

    Public because the arranger is not the only thing that will want it: a chart written
    by hand, or by a model, is checked against the same notion of what is in the key.
    """
    steps = steps_of(scale)
    index = degree - 1
    root, third, fifth = (
        steps[(index + step) % DEGREES] + 12 * ((index + step) // DEGREES) for step in (0, 2, 4)
    )
    return Chord(root=(key + root) % PITCH_CLASSES, quality=_quality(third - root, fifth - root))


def _quality(third: int, fifth: int) -> Quality:
    if fifth == 6:
        return Quality.DIM
    if third == MINOR_THIRD:
        return Quality.MINOR
    if fifth == 8:
        # An augmented triad, which only the harmonic scales produce. Nothing in this
        # project's vocabulary can voice one, and a power chord is the honest reduction:
        # it drops the note that does not fit rather than pretending it does.
        return Quality.POWER
    return Quality.MAJOR
