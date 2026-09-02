"""One line of DSL at a time: untrusted text in, typed values or a named refusal out.

**Every refusal here is the exit criterion.** "≥95% schema conformance on the first pass"
is a division, and this module is where the denominator's failures are counted — so a
refusal must name the line and what was not understood, and it must never be softened
into a shrug. A parser that quietly accepted a 21-character grid would move the number
without moving the music, which is P4 abandoned: *never trust model output.*

**The model does not redefine the section** (ADR-011). We sent the briefing; the `SEC`
line that comes back is an echo, and an echo that disagrees is a `section_mismatch`
violation rather than a new instruction. The scheduler has already sized the clip from
our numbers.

**Two legal forms, and both are in the wild.** A bar-level line carries no bar index.
A model writes one `DRM` line for an eight-bar section and means all eight;
`dsl/serialize.py` writes eight and means one each. Verified across the recorded
cassettes. So: one line applies to every bar, N lines fill bars 1..N positionally, and
more lines than bars is a violation.

Positions on the wire are 1-indexed — `acc=1,9` — because the DSL is written for a model
to read. They are 0-indexed here. The conversion happens in this module and nowhere else.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from garagem.domain import (
    ATTACK,
    REST,
    SIXTEENTHS_PER_BAR,
    Chart,
    Grid,
    Instrument,
    Section,
    parse_grid,
    parse_positions,
)
from garagem.dsl.errors import LineError
from garagem.theory import TheoryError, Violation, parse_chart, render_chart, render_key

FROZEN = ConfigDict(frozen=True, extra="forbid")

SEC: Final = "SEC"
CHD: Final = "CHD"

# The rule name this module produces. `theory.validator.RULES` holds the ones `validate`
# produces; the event log counts the union, and each module owns its own names so that
# neither list can claim a rule nobody implements.
PARSE_RULES: Final[tuple[str, ...]] = ("section_mismatch", "schema")

# The DSL's three-letter tags are `Instrument`'s own values, so this needs no table.
BAR_TAGS: Final[tuple[str, ...]] = tuple(str(instrument) for instrument in Instrument)

# Every `SEC` field `brief()` states, and therefore every one the model can be held to.
SEC_FIELDS: Final[tuple[str, ...]] = ("bars", "key", "feel", "bpm", "dyn", "tension")

_FIELD: Final = re.compile(r"^([a-z_]+)=(.*)$")

DRUM_TAGS: Final[tuple[str, ...]] = ("K", "S", "H", "C")
VOICINGS: Final[frozenset[str]] = frozenset({"pow", "triad", "sus2", "sus4", "drop2", "shell"})

# Spellings the model reaches for that name exactly one of the six. `power` appeared 8
# times in 90 measured sections and **only ever in a chorus** — the model writes the
# English word when the musical idea is a power chord. The six voicings were already
# enumerated in the system block with a gloss each, and it kept happening, so this is not
# a prompt that has been left untried (`phase-3-findings.md` §5, §15).
#
# **This is not P4 erosion, and the line is exact.** An alias maps one *unambiguous*
# token to exactly one known value, and the accepted set stays closed — there is no fuzzy
# matching, no prefix rule, no edit distance. `powerful` is still refused, and so is a
# 15-character grid, because a short grid is *ambiguous*: which slot went missing cannot
# be recovered, and guessing would put a note where nobody wrote one. Widening a closed
# vocabulary by one known spelling and inventing a note are not the same act.
ALIASES: Final[dict[str, str]] = {"power": "pow"}
REGISTERS: Final[frozenset[str]] = frozenset({"low", "mid", "high"})


# ------------------------------------------------------------------------------ the lines


class DrumLine(BaseModel):
    """One bar of drums: a grid per voice. A missing voice is silence, not an error."""

    model_config = FROZEN

    kick: Grid = ()
    snare: Grid = ()
    hat: Grid = ()
    crash: Grid = ()


class BassLine(BaseModel):
    model_config = FROZEN

    degree: int = Field(ge=1, le=7)
    octave: int = Field(ge=0, le=8)
    rhythm: Grid
    # 0-indexed here; the wire says 1.
    ghosts: tuple[int, ...] = ()


class ChordLine(BaseModel):
    """Guitar or keys: a voicing name, a rhythm, and the instrument's own decorations."""

    model_config = FROZEN

    instrument: Instrument
    voicing: str
    rhythm: Grid
    palm_muted: bool = False
    accents: tuple[int, ...] = ()
    # `reg` rather than `register`: pydantic warns that the longer name shadows a
    # `BaseModel` attribute, and the short one is what the DSL calls it anyway.
    reg: str = "mid"


BarLine = DrumLine | BassLine | ChordLine


# -------------------------------------------------------------------------- SEC and CHD


def tag_of(line: str) -> str:
    """The line's leading tag, or `""` for a blank line."""
    stripped = line.strip()
    return stripped.split(maxsplit=1)[0] if stripped else ""


def parse_sec(line: str) -> dict[str, str]:
    """`SEC verse bars=8 key=Em …` -> a flat mapping. No validation, no coercion.

    Deliberately stringly-typed: `check_sec` compares against what `brief()` rendered, so
    the comparison is "did it echo what we sent" rather than "do two floats agree", and
    that needs the text.
    """
    parts = line.split()
    if not parts or parts[0] != SEC:
        raise LineError(f"not a SEC line: {line!r}")
    if len(parts) < 2:
        raise LineError(f"SEC has no section name: {line!r}")

    fields = {"name": parts[1]}
    for part in parts[2:]:
        match = _FIELD.match(part)
        if match is None:
            raise LineError(f"SEC: {part!r} is not a key=value pair, in {line!r}")
        fields[match.group(1)] = match.group(2)

    missing = [field for field in SEC_FIELDS if field not in fields]
    if missing:
        raise LineError(f"SEC is missing {', '.join(missing)}: {line!r}")
    unknown = sorted(set(fields) - set(SEC_FIELDS) - {"name"})
    if unknown:
        raise LineError(f"SEC has unknown field(s) {unknown}: {line!r}")
    return fields


def check_sec(fields: dict[str, str], asked: Section) -> tuple[Violation, ...]:
    """Every disagreement between the echo and the briefing, as violations.

    The briefing always wins. This does not correct anything and does not need to: the
    parser builds parts against `asked`, so a model that thought the section was sixteen
    bars simply wrote eight bars of lines we will read as eight.
    """
    expected = _expected(asked)
    return tuple(
        Violation(
            rule="section_mismatch",
            instrument=Instrument.DRUMS,
            detail=f"SEC {field}={fields[field]!r}, the briefing says {want!r}",
            repairable=True,
        )
        for field, want in expected.items()
        if fields.get(field) != want
    )


def _expected(asked: Section) -> dict[str, str]:
    """Exactly what `dsl.schema.brief` put in the message, field by field.

    The two must stay in step: `brief` renders these and `check_sec` compares against
    them, so a field added to one and not the other is a constraint nobody checks or a
    refusal nobody deserves. A test asserts the round trip rather than trusting the pair.
    """
    return {
        "name": asked.name,
        "bars": str(asked.bars),
        "key": render_key(asked.key, asked.scale),
        "feel": str(asked.feel),
        "bpm": f"{asked.bpm:g}",
        "dyn": str(asked.dyn),
        "tension": f"{asked.tension:g}",
    }


def parse_chd(line: str) -> Chart:
    """`CHD | Em | C | G | D |` -> `Chart`, via `theory.parse_chart`.

    One implementation of chord spelling, not two: `render_chart` wrote the line we sent
    and `parse_chart` reads the one that comes back.
    """
    parts = line.split(maxsplit=1)
    if not parts or parts[0] != CHD:
        raise LineError(f"not a CHD line: {line!r}")
    if len(parts) == 1:
        raise LineError(f"CHD has no chords: {line!r}")
    try:
        return parse_chart(parts[1])
    except TheoryError as error:
        raise LineError(f"CHD: {error}") from error


def check_chd(chart: Chart, asked: Section) -> tuple[Violation, ...]:
    """A chart that is not the one we asked for is a mismatch, not a suggestion.

    Compared **bar by bar**, not list against list. A four-chord chart under an eight-bar
    section and its eight-chord expansion are the same harmony written two ways, and
    `brief()` sends the expansion — so comparing the literal lists flagged the model for
    echoing back exactly what it was given. Measured at 29 of 30 sections before this
    line was a loop.
    """
    if all(chart.at(bar) == asked.chart.at(bar) for bar in range(asked.bars)):
        return ()
    return (
        Violation(
            rule="section_mismatch",
            instrument=Instrument.DRUMS,
            detail=(f"CHD {render_chart(chart)}, the briefing says {render_chart(asked.chart)}"),
            repairable=True,
        ),
    )


# ------------------------------------------------------------------------- the bar lines


def parse_bar_line(line: str) -> BarLine:
    """One `DRM`, `BAS`, `GTR` or `KEY` line into its typed form."""
    parts = line.split()
    if not parts:
        raise LineError("an empty line is not a bar line")
    tag = parts[0]
    if tag == str(Instrument.DRUMS):
        return _drums(parts[1:], line)
    if tag == str(Instrument.BASS):
        return _bass(parts[1:], line)
    if tag in (str(Instrument.GUITAR), str(Instrument.KEYS)):
        return _chordal(Instrument(tag), parts[1:], line)
    raise LineError(f"{tag!r} is not a DSL tag; known are {', '.join(BAR_TAGS)}: {line!r}")


# `K:x...S:x...` with no spaces. Models write it that way and it is unambiguous: a voice
# tag is one known letter followed by a colon, and a grid is a fixed sixteen characters
# of `x` and `.`, so nothing else can look like the start of the next voice. Tokenising on
# this is fixing a tokeniser that assumed spaces, not loosening the schema — the grid is
# still refused at any length but sixteen, which is the check that carries musical weight.
_VOICE = re.compile(rf"([{''.join(DRUM_TAGS)}]):([^{''.join(DRUM_TAGS)}\s]*)")


def _drums(parts: list[str], line: str) -> DrumLine:
    voices: dict[str, Grid] = {}
    for part in parts:
        found = _VOICE.findall(part)
        if not found:
            tag = part.split(":", 1)[0]
            if ":" in part and tag not in DRUM_TAGS:
                known = ", ".join(DRUM_TAGS)
                raise LineError(f"DRM: {tag!r} is not a voice; known are {known}")
            raise LineError(f"DRM: {part!r} is not VOICE:grid, in {line!r}")
        if "".join(f"{tag}:{grid}" for tag, grid in found) != part:
            raise LineError(f"DRM: {part!r} has something that is not a voice, in {line!r}")
        for tag, grid in found:
            voices[tag] = _grid(grid, line)
    return DrumLine(
        kick=voices.get("K", ()),
        snare=voices.get("S", ()),
        hat=voices.get("H", ()),
        crash=voices.get("C", ()),
    )


def _bass(parts: list[str], line: str) -> BassLine:
    fields = _fields(parts, line, tag="BAS")
    rhythm = _grid(_required(fields, "rhy", line), line)
    return BassLine(
        degree=_integer(fields, "deg", line),
        octave=_integer(fields, "oct", line),
        rhythm=rhythm,
        ghosts=_positions(fields.get("ghost", ""), line),
    )


def _chordal(instrument: Instrument, parts: list[str], line: str) -> ChordLine:
    fields = _fields(parts, line, tag=str(instrument))
    voicing = _required(fields, "voi", line)
    voicing = ALIASES.get(voicing, voicing)
    if voicing not in VOICINGS:
        known = ", ".join(sorted(VOICINGS))
        raise LineError(f"{instrument}: {voicing!r} is not a voicing; known are {known}")
    register = fields.get("reg", "mid")
    if register not in REGISTERS:
        known = ", ".join(sorted(REGISTERS))
        raise LineError(f"{instrument}: {register!r} is not a register; known are {known}")
    palm = fields.get("palm", "off")
    if palm not in ("on", "off"):
        raise LineError(f"{instrument}: palm is on or off, got {palm!r}")
    return ChordLine(
        instrument=instrument,
        voicing=voicing,
        rhythm=_grid(_required(fields, "rhy", line), line),
        palm_muted=palm == "on",
        accents=_positions(fields.get("acc", ""), line),
        reg=register,
    )


# -------------------------------------------------------------------------------- helpers


# `rhy:x.......x.......reg=mid` with no space. Same case as the drum voices and the same
# argument: a grid is exactly sixteen characters of `x` and `.`, so `rhy:` is
# self-terminating and what follows can only be the next field. Splitting here is fixing a
# tokeniser that assumed spaces — the grid is still refused at any other length, which is
# the check that carries musical weight.
# The lookahead is the whole safety of this: split only where a *new field* begins — a
# key followed by `=` or `:`. Without it, `rhy:` followed by five more grid characters was
# read as a valid sixteen plus a stray, which silently truncated a 21-character grid to
# the right length. That is the loosening this comment claims not to be, and the existing
# regression test for exactly that grid is what caught it.
# Both spellings, and the lookahead guards both: `[\d,]+` is greedy and would happily
# swallow a following field, so the requirement that a *new key* follows is what stops it.
_GRID_FIELD = re.compile(rf"(rhy):([x.]{{{SIXTEENTHS_PER_BAR}}}|[0-9,]+)(?=[a-z]+[=:])")


def _fields(parts: list[str], line: str, *, tag: str) -> dict[str, str]:
    """`deg=1 rhy:x...` — the DSL uses both separators, and both mean the same thing."""
    fields: dict[str, str] = {}
    for part in _split_fields(parts):
        for separator in ("=", ":"):
            key, found, value = part.partition(separator)
            if found:
                fields[key] = value
                break
        else:
            raise LineError(f"{tag}: {part!r} is not a field, in {line!r}")
    return fields


def _split_fields(parts: list[str]) -> list[str]:
    """Break a run-together `rhy:<grid>` off whatever followed it with no space."""
    out: list[str] = []
    for part in parts:
        match = _GRID_FIELD.match(part)
        if match and match.end() < len(part):
            out.append(match.group(0))
            out.append(part[match.end() :])
        else:
            out.append(part)
    return out


def _required(fields: dict[str, str], key: str, line: str) -> str:
    if key not in fields:
        raise LineError(f"missing {key}: {line!r}")
    return fields[key]


def _integer(fields: dict[str, str], key: str, line: str) -> int:
    raw = _required(fields, key, line)
    try:
        return int(raw)
    except ValueError:
        raise LineError(f"{key}={raw!r} is not a whole number, in {line!r}") from None


def _grid(text: str, line: str) -> Grid:
    """A bar, in either accepted spelling. `parse_grid` and `parse_positions` refuse by name.

    That refusal *is* the conformance check the phase is measured on — the 21-character
    guitar grid a real model produced fails exactly here.

    **Both forms, and the two cannot be confused.** A grid is sixteen characters of `x`
    and `.`; a position list is digits and commas. The character sets are disjoint, so the
    dispatch is a fact about the text rather than a guess about intent.

    Dispatching on `x`/`.` *first* is what keeps every existing error message: a
    15-character grid still fails with "a grid is 16 characters, got 15" rather than being
    re-read as a malformed position list, and the regression test pinning the real
    21-character failure still fails there.
    """
    try:
        if any(character in text for character in (ATTACK, REST)) or not text:
            return parse_grid(text)
        return parse_positions(text)
    except ValueError as error:
        raise LineError(f"{error}, in {line!r}") from error


def _positions(text: str, line: str) -> tuple[int, ...]:
    """`ghost=7,15` -> `(6, 14)`. 1-indexed on the wire, 0-indexed everywhere inside."""
    if not text:
        return ()
    positions = []
    for item in text.split(","):
        try:
            position = int(item)
        except ValueError:
            raise LineError(f"{item!r} is not a position, in {line!r}") from None
        if not 1 <= position <= SIXTEENTHS_PER_BAR:
            raise LineError(f"position {position} is outside 1..{SIXTEENTHS_PER_BAR}, in {line!r}")
        positions.append(position - 1)
    return tuple(positions)
