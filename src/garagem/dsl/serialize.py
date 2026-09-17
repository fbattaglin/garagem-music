"""Domain to text: the DSL a model will read, and the exact form a golden test needs.

**Two renderers, because they answer two different questions.**

`serialize_section` writes the GARAGEM/0.1 DSL exactly as `.claude/skills/garagem-dsl`
specifies it — SEC, CHD, then DRM, BAS, GTR, KEY in the mandated order. It is a briefing
notation: a sixteen-slot grid, a degree, a voicing name. It cannot express a note pushed
nine milliseconds late or a velocity of 83, and it is not supposed to. This is the form
Phase 3 exchanges with a model.

`serialize_score` writes every note, exactly. It exists because invariant 7 says a
generation is byte-identical given a seed, and a golden file that could not see a
velocity change would be a test that passes while the music moves. Nothing sends this
anywhere; it is evidence.

**The parser is Phase 3's problem, not this module's**, and the asymmetry is deliberate.
Writing is a total function over a score we produced. Reading is incremental, untrusted
and partial — a different problem with a different failure mode (ADR-011), and pretending
one function inverts the other would smuggle that difference out of sight.

A part that plays nothing still gets its line, with a grid of rests. A missing line in a
stream means "not generated yet"; a line of rests means "chose not to play". Phase 3
cannot tell those apart if silence deletes the line.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Callable, Sequence
from typing import Final

from garagem.domain import (
    ATTACK,
    REST,
    SIXTEENTHS_PER_BAR,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
)
from garagem.theory.chords import render_chart, render_key
from garagem.theory.percussion import CRASH, GHOST_VELOCITY, HATS, KICK, SNARE
from garagem.theory.scales import DEGREES, degree_to_pitch
from garagem.theory.validator import grid_slots
from garagem.theory.voicings import RANGES, Register

DRUM_LINES: Final[tuple[tuple[str, tuple[int, ...]], ...]] = (
    ("K", (KICK,)),
    ("S", (SNARE,)),
    ("H", tuple(sorted(HATS))),
    ("C", (CRASH,)),
)

# Interval signatures, so a voicing is named by what it is rather than by what the engine
# happened to call it. Anything else is a triad as far as the DSL is concerned.
VOICINGS: Final[dict[tuple[int, ...], str]] = {
    (0, 7): "pow",
    # A power chord on a diminished chord takes the chord's own flat fifth
    # (`theory.voicings.fifth_of`, a Phase 2 finding). Two notes and a tritone is still
    # `voi=pow`; without this row it serialised as a triad and came back with a third
    # the guitar never played.
    (0, 6): "pow",
    (0, 2, 7): "sus2",
    (0, 5, 7): "sus4",
}

PALM_MUTE_BEATS: Final = 0.2
ACCENT_MARGIN: Final = 6


def serialize_section(score: SectionScore) -> str:
    """The DSL text for a whole section, in the mandated emission order."""
    section = score.section
    lines = [sec_line(section), f"CHD {render_chart(section.chart)}"]
    for instrument in Instrument:
        part = _part_or_silence(score, instrument)
        lines.extend(_part_lines(part, section))
    return "\n".join(lines) + "\n"


def serialize_score(score: SectionScore) -> str:
    """Every note, exactly, for the golden files. Not a wire format."""
    lines = [
        f"# seed={score.seed} scale={score.section.scale}",
        sec_line(score.section),
        f"CHD {render_chart(score.section.chart)}",
    ]
    for instrument in Instrument:
        part = _part_or_silence(score, instrument)
        lines.append(f"{instrument} notes={len(part.notes)}")
        lines.extend(_note_line(note) for note in part.notes)
    return "\n".join(lines) + "\n"


def _note_line(note: Note) -> str:
    """Fixed width, four decimals: a diff points at the field that moved."""
    return (
        f"  {note.pitch:3d} {note.start_beats:9.4f} {note.duration_beats:7.4f} {note.velocity:3d}"
    )


def sec_line(section: Section) -> str:
    """The `SEC` line for a briefing, field for field what `brief` sends and `check_sec` reads."""
    key = render_key(section.key, section.scale)
    return (
        f"SEC {section.name} bars={section.bars} key={key} "
        f"feel={section.feel} bpm={section.bpm:g} dyn={section.dyn} "
        f"tension={section.tension:g}"
    )


def _part_or_silence(score: SectionScore, instrument: Instrument) -> Part:
    try:
        return score.part(instrument)
    except KeyError:
        return Part(instrument=instrument)


def _part_lines(part: Part, section: Section) -> list[str]:
    """One line per bar, positional. Bar 1 is the section's first bar."""
    placed = _by_bar(part, section)
    if part.instrument is Instrument.DRUMS:
        return [_drum_line(placed[bar]) for bar in range(section.bars)]
    if part.instrument is Instrument.BASS:
        return [_bass_line(placed[bar], section, bar) for bar in range(section.bars)]
    return [
        _chordal_line(part.instrument, placed[bar], section.chart.at(bar).root)
        for bar in range(section.bars)
    ]


def _by_bar(part: Part, section: Section) -> list[dict[int, list[Note]]]:
    """Every note quantised back to the slot it was written for."""
    slots = grid_slots(section)
    placed: list[dict[int, list[Note]]] = [{} for _ in range(section.bars)]
    for note in part.notes:
        index = _slot_index(slots, note.start_beats)
        bar, slot = divmod(index, SIXTEENTHS_PER_BAR)
        placed[min(bar, section.bars - 1)].setdefault(slot, []).append(note)
    return placed


def _slot_index(slots: Sequence[float], at: float) -> int:
    index = bisect_left(slots, at)
    if index == 0:
        return 0
    if index == len(slots):
        return len(slots) - 1
    return index - 1 if at - slots[index - 1] <= slots[index] - at else index


def _grid(slots: dict[int, list[Note]], pitches: tuple[int, ...]) -> str:
    wanted = set(pitches)
    return "".join(
        ATTACK if any(note.pitch in wanted for note in slots.get(slot, ())) else REST
        for slot in range(SIXTEENTHS_PER_BAR)
    )


def _drum_line(bar: dict[int, list[Note]]) -> str:
    voices = " ".join(f"{tag}:{_grid(bar, pitches)}" for tag, pitches in DRUM_LINES)
    return f"DRM {voices}"


def _bass_line(bar: dict[int, list[Note]], section: Section, index: int) -> str:
    notes = [note for slot in sorted(bar) for note in bar[slot]]
    rhythm = "".join(ATTACK if slot in bar else REST for slot in range(SIXTEENTHS_PER_BAR))
    if not notes:
        return f"BAS deg=0 oct=0 rhy:{rhythm}"
    first = notes[0]
    degree = _degree_of(first.pitch, section, index)
    octave = first.pitch // 12 - 1
    ghosts = _positions(bar, lambda note: note.velocity < GHOST_VELOCITY)
    line = f"BAS deg={degree} oct={octave} rhy:{rhythm}"
    return f"{line} ghost={ghosts}" if ghosts else line


def _chordal_line(instrument: Instrument, bar: dict[int, list[Note]], root: int) -> str:
    tag = str(instrument)
    rhythm = "".join(ATTACK if slot in bar else REST for slot in range(SIXTEENTHS_PER_BAR))
    if not bar:
        return f"{tag} voi=none rhy:{rhythm}"
    first = bar[min(bar)]
    style = _voicing_of(tuple(sorted(note.pitch for note in first)), root)
    line = f"{tag} voi={style} rhy:{rhythm}"
    if instrument is Instrument.GUITAR:
        muted = all(note.duration_beats <= PALM_MUTE_BEATS for note in first)
        accents = _positions(bar, lambda note: note.velocity >= _loudest(bar) - ACCENT_MARGIN)
        line = f"{line} palm={'on' if muted else 'off'}"
        if accents:
            line = f"{line} acc={accents}"
    else:
        line = f"{line} reg={_register_of(first)}"
    return line


def _degree_of(pitch: int, section: Section, bar: int) -> int:
    """Which degree of the bar's chord this pitch is, or 0 when it is none of them."""
    chord = section.chart.at(bar)
    for degree in range(1, DEGREES + 1):
        if pitch % 12 == degree_to_pitch(chord, degree, 0) % 12:
            return degree
    return 0


def _voicing_of(pitches: tuple[int, ...], root: int) -> str:
    """Name the chord shape, whatever inversion it came out in.

    `voice_lead` turns a root-position power chord into a fourth from the bottom, and a
    serializer that read that as a different voicing would make the DSL line change every
    time the guitar moved its hand — which is exactly what voice leading is for.

    **The chord's root is required, and it is not a convenience.** A sus2 and a sus4 are
    the same set of pitch classes read from two different notes: F-G-C is Fsus2 from F and
    Csus4 from C. Guessing the root by trying each in turn picked whichever came first
    numerically, so an Fsus2 serialised as `sus4` and came back a semitone's worth of
    harmony away. Found by `tests/property/test_dsl_round_trip.py`, which is what a
    property test over the serializer's own output is for.
    """
    if not pitches:
        return "none"
    classes = sorted({pitch % 12 for pitch in pitches})
    signature = tuple(sorted((pitch - root) % 12 for pitch in classes))
    if signature in VOICINGS:
        return VOICINGS[signature]
    return "triad"


def _register_of(notes: list[Note]) -> str:
    low, high = RANGES[Instrument.KEYS]
    middle = sum(note.pitch for note in notes) / len(notes)
    third = (high - low) / 3
    if middle < low + third:
        return Register.LOW
    return Register.MID if middle < low + 2 * third else Register.HIGH


def _loudest(bar: dict[int, list[Note]]) -> int:
    return max(note.velocity for notes in bar.values() for note in notes)


def _positions(bar: dict[int, list[Note]], matches: Callable[[Note], bool]) -> str:
    """DSL positions are 1-indexed: the notation is written for a model to read."""
    chosen = [slot + 1 for slot in sorted(bar) if any(matches(note) for note in bar[slot])]
    return ",".join(str(position) for position in chosen)
