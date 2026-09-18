"""The lead: one hook, answering the band, and silence the rest of the time.

**This voice exists to be written over.** ADR-026 gives the band a fifth track so the
songwriter has somewhere to put a riff. Until it writes one, something has to play there
without a network (invariant 2) — and a floor lead that soloed across every bar would
fight the model's line rather than stand in for it. So this engine rests more than it
plays: nothing at all below `LEAD_DYN`, and where it does speak it speaks in the second
half of the bar, after the band has stated it, and never in the last bar, which belongs
to the fill.

**One motif per section, repeated.** It is chosen once from a seeded table and played
again every other bar on the current chord's own notes, which is what makes a hook a hook
instead of a phrase that never comes back. Its degrees are chord tones, so the dissonance
budget holds by construction rather than by repair — the same bet `engines/bass.py` makes
with the root on a chord change.

**It is last in `ENGINES`, and that is load-bearing.** The band shares one `Random`
(`engines/band.py`), so an engine that returns early without drawing from it would move
every engine after it. There is none after this one, which is what lets the silent case
be an early return rather than a motif generated and thrown away.
"""

from __future__ import annotations

from random import Random
from typing import Final

from garagem.domain import (
    SIXTEENTHS_PER_BAR,
    Instrument,
    Note,
    Part,
    Section,
    beats_of,
)
from garagem.engines.humanise import humanise, separate
from garagem.theory.scales import degree_to_pitch
from garagem.theory.voicings import fit_to_range

# Below this the lead plays nothing. `dyn` is what makes a chorus a chorus here — the
# arranger gives a verse 2 and a chorus 4 (`engines/arranger.py`) — so this one number is
# ADR-026's "quiet in a verse and present in a chorus". The density knob can push a verse
# over it, which is the knob doing exactly what it is for (ADR-021).
LEAD_DYN: Final = 4

# The root at C4 (60) whatever the key, which sits above the guitar's voicings and leaves
# the top of the range unused. `_in_range` is what keeps that a fact rather than a hope.
LEAD_OCTAVE: Final = 4

# A figure: which sixteenth, and which degree of the bar's chord. Slots 8 and up are the
# second half of the bar, and `beats_of` swings them when the feel does — so one table
# reads straight or shuffled without a second entry.
#
# **Every slot is even, which is to say an eighth.** Stage A took the whole band off the
# sixteenths that fall between a shuffle's eighths (`phase-6-findings.md` §1); a lead that
# went back to them would be the one voice straightening still had work to do on.
Motif = tuple[tuple[int, int], ...]

# Two notes: a call the band can still be heard under.
QUIET: Final[tuple[Motif, ...]] = (
    ((8, 5), (12, 1)),
    ((8, 1), (12, 5)),
    ((10, 3), (14, 1)),
)

# Three, once the section has the tension to carry them.
BUSY: Final[tuple[Motif, ...]] = (
    ((8, 5), (10, 3), (12, 1)),
    ((8, 1), (10, 3), (12, 5)),
    ((8, 3), (12, 5), (14, 1)),
)

# The same line the bass draws to stop sitting on the root (`engines/bass.py`), for the
# same reason: tension is what buys movement.
BUSY_TENSION: Final = 0.35

BASE_VELOCITY: Final = 50
DYN_VELOCITY: Final = 12
NOTE_BEATS: Final = 0.5
# The figure's last note holds, so the phrase lands instead of stopping.
LAST_NOTE_BEATS: Final = 1.0


def play(section: Section, rng: Random) -> Part:
    """One lead part for the whole section — most often no notes at all."""
    if section.dyn < LEAD_DYN:
        return Part(instrument=Instrument.LEAD)

    motifs = BUSY if section.tension > BUSY_TENSION else QUIET
    motif = motifs[rng.randrange(len(motifs))]
    velocity = min(127, max(1, BASE_VELOCITY + DYN_VELOCITY * section.dyn))

    notes: list[Note] = []
    for bar in answering_bars(section.bars):
        chord = section.chart.at(bar)
        pitches = _in_range(
            tuple(degree_to_pitch(chord, degree, LEAD_OCTAVE) for _, degree in motif)
        )
        offset = bar * SIXTEENTHS_PER_BAR
        last = len(motif) - 1
        for index, ((slot, _), pitch) in enumerate(zip(motif, pitches, strict=True)):
            notes.append(
                Note(
                    pitch=pitch,
                    start_beats=beats_of(offset + slot, section.feel),
                    duration_beats=LAST_NOTE_BEATS if index == last else NOTE_BEATS,
                    velocity=velocity,
                )
            )

    return Part(instrument=Instrument.LEAD, notes=separate(humanise(notes, rng, feel=section.feel)))


def answering_bars(bars: int) -> range:
    """The second bar of each two-bar phrase, and never the section's last.

    One rule, two reasons. A hook on every bar answers nothing — which is the mistake the
    whole band was making under a shuffle (`phase-6-findings.md` §1). And the last bar is
    the fill's, composed after this engine has run (`engines/variants.py`); a lead playing
    across it would be the second thing in the arrangement arriving bolted on.
    """
    return range(1, max(bars - 1, 1), 2)


def _in_range(pitches: tuple[int, ...]) -> tuple[int, ...]:
    """The figure moved bodily into the lead's range, in the order it is played.

    `fit_to_range` sorts what it returns, which is nothing to a chord and everything to a
    melody. So what is taken from it is the octave shift it chose, applied to the notes as
    written — and that shift is why the validator's `range` rule cannot fire on this part.
    """
    if not pitches:
        return ()
    shift = fit_to_range(pitches, Instrument.LEAD)[0] - min(pitches)
    return tuple(pitch + shift for pitch in pitches)
