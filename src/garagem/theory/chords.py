"""The text boundary: chord symbols in, `Chord` out, and back again.

This is the only module that knows a chord has a name. `domain/harmony.py` deals in
pitch classes precisely so that the enharmonic question — is that note F# or Gb? — is
asked once, here, and answered the same way every time.

**Canonical form is sharps and `m`.** `Gb` parses and renders as `F#`; `Ebm7` renders as
`D#m7`. Rendering is therefore not always the inverse of parsing, and that is the point:
one spelling per chord means a serialised section is comparable byte for byte, which is
what the golden tests need (invariant 7). A key-aware speller that wrote Eb in Cm would
be more correct musically and would make every generated section unstable under a key
change; that trade is worth stating rather than discovering.

**The grammar is exactly the DSL's, and no wider.** `.claude/skills/garagem-dsl` writes
`| Em | Em | C | D |` and `B7`; those suffixes and no others parse. A permissive parser
here becomes a validator that lets model output through in Phase 3, which is the one
thing P4 exists to stop.
"""

from __future__ import annotations

from typing import Final

from garagem.domain import PITCH_CLASSES, Chart, Chord, Quality
from garagem.theory.errors import TheoryError

# The natural notes and their pitch classes. Accidentals are applied on top, so `Cb`,
# `E#` and the rest fall out of the arithmetic instead of needing a table each.
NATURALS: Final[dict[str, int]] = {
    "C": 0,
    "D": 2,
    "E": 4,
    "F": 5,
    "G": 7,
    "A": 9,
    "B": 11,
}

SHARP: Final = "#"
FLAT: Final = "b"

# What each pitch class is called when we write it. Sharps, always.
NAMES: Final[tuple[str, ...]] = (
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
)

# Suffix to quality. The empty suffix is a major triad, which is why a bare `C` is a
# chord and not a parse error.
SUFFIXES: Final[dict[str, Quality]] = {
    "": Quality.MAJOR,
    "m": Quality.MINOR,
    "7": Quality.DOM7,
    "m7": Quality.MIN7,
    "maj7": Quality.MAJ7,
    "sus2": Quality.SUS2,
    "sus4": Quality.SUS4,
    "dim": Quality.DIM,
    "5": Quality.POWER,
}

QUALITY_SUFFIX: Final[dict[Quality, str]] = {
    quality: suffix for suffix, quality in SUFFIXES.items()
}

BAR_SEPARATOR: Final = "|"

# Which scales the DSL's `key=` field spells with a trailing `m`. The field carries a
# modality, not a mode: `key=Em` says minor and does not say dorian. That is the DSL's own
# limit, and it lives here because it is a spelling question — the same reason sharps and
# `m` live here rather than in `domain/`.
MINOR_FLAVOURED: Final[frozenset[str]] = frozenset(
    {"minor", "dorian", "locrian", "pentatonic_minor", "blues"}
)


def render_key(key: int, scale: str) -> str:
    """The DSL's `key=` field: a root name plus `m` when the scale is minor-flavoured."""
    return NAMES[key] + ("m" if scale in MINOR_FLAVOURED else "")


def parse_chord(symbol: str) -> Chord:
    """`Em`, `B7`, `Csus2`, `F#m7`, `A5` -> `Chord`.

    Raises `TheoryError` naming the symbol and the part of it that was not understood,
    because the caller is either a person or a language model and both need to be told
    which half was wrong.
    """
    text = symbol.strip()
    if not text:
        raise TheoryError("an empty chord symbol")

    letter = text[0].upper()
    if letter not in NATURALS:
        raise TheoryError(f"{symbol!r}: {text[0]!r} is not a note name (A-G)")

    root = NATURALS[letter]
    rest = text[1:]
    if rest.startswith((SHARP, FLAT)):
        root += 1 if rest[0] == SHARP else -1
        rest = rest[1:]
    root %= PITCH_CLASSES

    try:
        quality = SUFFIXES[rest]
    except KeyError:
        known = ", ".join(repr(suffix) for suffix in SUFFIXES if suffix)
        raise TheoryError(
            f"{symbol!r}: {rest!r} is not a chord quality; known are {known}"
        ) from None

    return Chord(root=root, quality=quality)


def render_chord(chord: Chord) -> str:
    """The canonical spelling: sharps, and `m` rather than `min`."""
    return NAMES[chord.root] + QUALITY_SUFFIX[chord.quality]


def parse_chart(line: str) -> Chart:
    """`| Em | Em | C | D |` -> `Chart`. The DSL's CHD line, one chord per bar.

    The outer pipes are optional and whitespace is free, because a model writing the
    line will not be consistent about either and neither carries meaning. An empty bar
    is refused rather than filled: a chart with a hole in it would play a bar of
    something nobody chose.
    """
    symbols = [cell.strip() for cell in line.strip().strip(BAR_SEPARATOR).split(BAR_SEPARATOR)]
    if not any(symbols):
        raise TheoryError(f"a chart needs at least one chord, got {line!r}")
    for index, symbol in enumerate(symbols):
        if not symbol:
            raise TheoryError(f"bar {index + 1} of {line!r} is empty")
    return Chart(chords=tuple(parse_chord(symbol) for symbol in symbols))


def render_chart(chart: Chart) -> str:
    """The inverse, with the outer pipes the DSL's own example writes."""
    cells = " | ".join(render_chord(chord) for chord in chart.chords)
    return f"{BAR_SEPARATOR} {cells} {BAR_SEPARATOR}"
