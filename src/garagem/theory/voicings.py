"""Turning a chord into actual pitches, inside an instrument's actual range.

Three functions, in the order an engine calls them: `voice` chooses which notes,
`voice_lead` chooses which octave each one sits in relative to the last chord, and
`fit_to_range` moves the result bodily until the instrument can play it.

`voice_lead` is what makes four chords sound like a part rather than four chords. A
guitar that jumps to root position on every change announces the arithmetic; a player
moves the shortest distance their hand allows. It is pure and its result is comparable,
so "movement never increases" is a property test rather than an opinion.

**Nothing here clips.** `fit_to_range` shifts by whole octaves and refuses when the
voicing cannot fit at all (`UnvoiceableError`), because a chord with a note pulled into
range individually is a chord with the wrong notes in it — and it would sound like a bug
in the engine, three layers away from here.

Drums have no entry in `RANGES` on purpose: a drum pitch is a General MIDI map lookup,
not a register, and an octave shift would turn a kick into a cowbell.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Final

from garagem.domain import Chord, Instrument, Quality
from garagem.theory.errors import TheoryError, UnvoiceableError
from garagem.theory.scales import SEMITONES_PER_OCTAVE, pitch_of

FIFTH: Final = 7


class Register(StrEnum):
    """The DSL's `reg=` field: roughly where in the instrument's range to sit."""

    LOW = "low"
    MID = "mid"
    HIGH = "high"


# The octave each register starts on before `fit_to_range` has its say. Nominal, not
# final: the instrument's range is what decides, and these only pick a starting point.
REGISTER_OCTAVES: Final[dict[Register, int]] = {
    Register.LOW: 2,
    Register.MID: 3,
    Register.HIGH: 4,
}

# The ranges the DSL skill's validator invariants name, as MIDI pitches.
RANGES: Final[dict[Instrument, tuple[int, int]]] = {
    Instrument.BASS: (28, 55),  # E1 - G3
    Instrument.GUITAR: (40, 76),  # E2 - E5
    Instrument.KEYS: (36, 84),  # C2 - C6
}

STYLES: Final[tuple[str, ...]] = ("pow", "triad", "sus2", "sus4", "drop2", "shell")


def voice(chord: Chord, style: str, register: Register) -> tuple[int, ...]:
    """The chord as absolute pitches, ascending. `style` is the DSL's `voi=` field."""
    if style not in STYLES:
        raise TheoryError(f"unknown voicing style {style!r}; known are {', '.join(STYLES)}")

    base = pitch_of(chord.root, REGISTER_OCTAVES[register])

    if style == "pow":
        # No third at all, which is why it sits over a major and a minor bar alike — but
        # the fifth is the chord's own. A perfect fifth on a diminished chord is a note
        # the chord does not contain, and on a `iidim` in dorian it is not even in the
        # key: the engine would be writing dissonance the briefing never asked for.
        return (base, base + fifth_of(chord))
    if style == "sus2":
        return tuple(base + step for step in _intervals(Quality.SUS2))
    if style == "sus4":
        return tuple(base + step for step in _intervals(Quality.SUS4))
    if style == "triad":
        return tuple(base + step for step in chord.intervals()[:3])
    if style == "shell":
        return tuple(base + step for step in _shell(chord))
    return _drop2(tuple(base + step for step in chord.intervals()))


def fifth_of(chord: Chord) -> int:
    """The chord's fifth, in semitones. Diminished chords have a flat one."""
    intervals = chord.intervals()
    return intervals[2] if len(intervals) > 2 else intervals[1]


def _intervals(quality: Quality) -> tuple[int, ...]:
    return Chord(root=0, quality=quality).intervals()


def _shell(chord: Chord) -> tuple[int, ...]:
    """Root, third and seventh: the fifth is the note a bass player is already on.

    A chord with nothing left after dropping the fifth keeps it — a one-note "voicing"
    would be a rest with extra steps.
    """
    without_fifth = tuple(step for step in chord.intervals() if step != FIFTH)
    return without_fifth if len(without_fifth) >= 2 else chord.intervals()


def _drop2(pitches: tuple[int, ...]) -> tuple[int, ...]:
    """The second voice from the top, dropped an octave. Opens the chord up.

    Fewer than three notes has no second-from-top worth moving, so it is left alone
    rather than refused: `voi=drop2` on a power chord is a pointless request, not an
    error the caller can do anything about.
    """
    if len(pitches) < 3:
        return pitches
    ordered = sorted(pitches)
    ordered[-2] -= SEMITONES_PER_OCTAVE
    return tuple(sorted(ordered))


def fit_to_range(pitches: Iterable[int], instrument: Instrument) -> tuple[int, ...]:
    """Shift the whole voicing by octaves until it fits. Never drops or clips a note.

    Idempotent, which matters because the repairer may run over a part the engine
    already fitted.
    """
    voicing = tuple(sorted(pitches))
    if not voicing:
        return ()

    try:
        low, high = RANGES[instrument]
    except KeyError:
        raise TheoryError(
            f"{instrument} has no range: a drum pitch is a map, not a register"
        ) from None

    span = voicing[-1] - voicing[0]
    if span > high - low:
        raise UnvoiceableError(
            f"a voicing spanning {span} semitones does not fit {instrument} ({low}-{high})"
        )

    shift = 0
    while voicing[0] + shift < low:
        shift += SEMITONES_PER_OCTAVE
    while voicing[-1] + shift > high:
        shift -= SEMITONES_PER_OCTAVE

    fitted = tuple(pitch + shift for pitch in voicing)
    if fitted[0] < low:
        raise UnvoiceableError(f"no octave of {voicing} lands inside {instrument} ({low}-{high})")
    return fitted


def voice_lead(previous: Sequence[int], current: Sequence[int]) -> tuple[int, ...]:
    """The inversion of `current` that moves least from `previous`.

    Candidates are the inversions of `current` — each formed by lifting its lowest notes
    an octave — plus a whole-voicing octave either side. Cost is the total distance every
    note of the candidate travels to the nearest note of `previous`, which is what a
    hand actually does and does not need the two chords to have the same number of notes.

    Ties break towards staying put: least octave displacement from `current`, then the
    lower voicing. Determinism here is not tidiness — the golden tests compare bytes.
    """
    voicing = tuple(sorted(current))
    if not voicing or not previous:
        return voicing

    best = min(
        _candidates(voicing),
        key=lambda option: (_movement(option, previous), _drift(option, voicing), option),
    )
    return best


def _candidates(voicing: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    inversions = []
    rotated = list(voicing)
    for _ in range(len(voicing)):
        inversions.append(tuple(sorted(rotated)))
        rotated = [*rotated[1:], rotated[0] + SEMITONES_PER_OCTAVE]

    seen: dict[tuple[int, ...], None] = {}
    for inversion in inversions:
        for octave in (-SEMITONES_PER_OCTAVE, 0, SEMITONES_PER_OCTAVE):
            seen[tuple(pitch + octave for pitch in inversion)] = None
    return tuple(seen)


def _movement(candidate: Sequence[int], previous: Sequence[int]) -> int:
    return sum(min(abs(pitch - other) for other in previous) for pitch in candidate)


def _drift(candidate: Sequence[int], voicing: Sequence[int]) -> int:
    return abs(sum(candidate) - sum(voicing))
