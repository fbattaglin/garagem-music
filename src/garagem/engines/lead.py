"""The lead: one hook, answering the band, silence the rest of the time — and the solo.

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

**In a `solo` section it does the opposite** (ADR-027). That section exists for this voice,
so there it plays in every bar, over the whole chart, through the section's own scale — and
the dynamic gate does not apply, because a solo section with nothing in it is not a quieter
section, it is an empty one. Everything else in this module is the hook.

**In a verse and a chorus it sings** (ADR-028). Fabiano asked for the lead to be "more than
colour", and in a rock song the voice that is more than colour carries the tune. So a verse
gets the song's verse melody, softly and low, and a chorus gets its chorus melody, higher and
at full strength. Every section of one song carries the same `tune`, so every verse sings the
same melody, fitted to its own chords. The hook is still what a bridge or an intro gets when
the knobs push it into a chorus's dynamic.

**It is last in `ENGINES`, and that is load-bearing.** The band shares one `Random`
(`engines/band.py`), so an engine that returns early without drawing from it would move
every engine after it. There is none after this one, which is what lets the silent case
be an early return rather than a motif generated and thrown away.
"""

from __future__ import annotations

from random import Random
from typing import Final
from zlib import crc32

from garagem.domain import (
    PITCH_CLASSES,
    SIXTEENTHS_PER_BAR,
    Chord,
    Instrument,
    Note,
    Part,
    Section,
    beats_of,
)
from garagem.engines.arranger import CHORUS, SOLO, VERSE
from garagem.engines.humanise import humanise, separate
from garagem.theory.scales import (
    SEMITONES_PER_OCTAVE,
    degree_to_pitch,
    pitch_of,
    scale_pitch,
    steps_of,
)
from garagem.theory.voicings import RANGES, fit_to_range

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

# How long a sixteenth is, in beats.
BEATS_PER_SIXTEENTH: Final = 0.25

# ------------------------------------------------------------------------------------ solo

# A bar of the solo: which eighth sounds, and how far up the section's scale it is from the
# note that bar began on. Every slot is even for the reason the motifs' are — Stage A took
# the whole band off the sixteenths between a shuffle's eighths (`phase-6-findings.md` §1).
Run = tuple[tuple[int, int], ...]

# **Every run opens and closes on step 0, 2 or 4**, and that is the whole legality argument.
# The bar's anchor is its chord's root as a step of the key (`_anchor`), so over a diatonic
# triad those three steps are the root, the third and the fifth: the bar line is a chord tone
# by construction, and the notes in between are the key's, which is all the dissonance budget
# counts (`theory/validator._dissonance_budget`). No repairer, no luck — the same bet
# `_in_the_chord` makes for the hook, made one level up.
RUNS: Final[tuple[Run, ...]] = (
    # Up the scale and back to the third: the first thing anybody plays, and it works.
    ((0, 0), (2, 1), (4, 2), (6, 3), (8, 4), (12, 2)),
    # Down from the fifth, with the middle of the bar left open for the band.
    ((0, 4), (2, 3), (4, 2), (10, 1), (12, 0)),
    # A leap to the fifth, and a walk home from it.
    ((0, 0), (4, 4), (6, 3), (8, 2), (10, 1), (12, 0)),
    # The same three-note shape twice, a step apart: something said, and said again.
    ((0, 2), (2, 3), (4, 1), (8, 3), (10, 4), (12, 2)),
)

# How far above its anchor a run may reach, and it is a width rather than a taste: a bar's
# line plus the spread of the anchors across the key is how wide the whole solo is, and
# `_placed` moves it by whole octaves. **Five was tried and it is one semitone too wide.**
# At step 5 the widest line spans nineteen semitones, which needs an eleven-semitone window
# inside the lead's twenty-nine — and a window narrower than an octave can fall between two
# octaves of the key's root, which is exactly what it did: `UnvoiceableError`, in E flat, from
# a floor that is not allowed to fail. Four spans seventeen and the window is thirteen.
TOP_STEP: Final = 4

# The solo is the one voice nothing else is covering, so it sits a little above what the hook
# would play at the same dynamic. The band is already out of its way: a `solo` section is
# `dyn` 3, under a chorus (`engines/arranger.SHAPES`).
SOLO_LIFT: Final = 8

# The solo's last note, on the downbeat of the last bar. Half a bar, so the phrase lands and
# the drummer still has the fill the bar is for.
LAND_BEATS: Final = 2.0

# Which steps of the anchor a run may start and end on. Read by the runs above and by the
# test that holds them to it, so the rule lives in one place.
CHORD_STEPS: Final[frozenset[int]] = frozenset({0, 2, 4})


# ---------------------------------------------------------------------------------- melody

# A two-bar phrase of a melody: which sixteenth of the 32 it starts on, and how many it lasts.
# Every slot is even, for the motifs' reason. Each phrase leaves a breath, because a melody a
# singer could not sing is a synth line.
Phrase = tuple[tuple[int, int], ...]

# A verse comes in after the downbeat, the way a singer does once the band has stated the bar.
VERSE_PHRASES: Final[tuple[Phrase, ...]] = (
    ((4, 2), (6, 2), (8, 4), (12, 4), (20, 2), (22, 2), (24, 6)),
    ((2, 2), (4, 2), (6, 6), (16, 2), (18, 2), (20, 4), (24, 6)),
    ((4, 4), (8, 2), (10, 2), (12, 8), (24, 6)),
)

# A chorus says its line on the downbeat and holds it.
CHORUS_PHRASES: Final[tuple[Phrase, ...]] = (
    ((0, 6), (6, 2), (8, 8), (16, 6), (22, 2), (24, 6)),
    ((0, 4), (4, 4), (8, 4), (12, 4), (16, 12)),
    ((0, 8), (8, 4), (12, 4), (16, 6), (22, 2), (24, 6)),
)

PHRASE_SLOTS: Final = 2 * SIXTEENTHS_PER_BAR

# Beats 1 and 3: where a sung note is a tone of the bar's chord, by construction. Between
# them a note moves through the key by a step or two, which is all the dissonance budget
# counts (`theory/validator._dissonance_budget`) — the solo's legality argument, again.
STRONG_EVERY: Final = 8
CHORD_CHOICES: Final[tuple[int, ...]] = (0, 2, 4)
WALK: Final[tuple[int, ...]] = (-2, -1, -1, 1, 1, 2)

# How wide the tune may move, in steps of the key above its own lowest note: six steps is a
# seventh at most, what a voice sings comfortably, and narrow enough to leave the placement
# below a choice of octaves.
SPAN_STEPS: Final = 6

# Where each tune sits, as the MIDI note its middle is placed nearest. A verse sits as low as
# the lead goes and a chorus near D5: the lift a singer makes into the chorus. Measured over
# 720 arranged songs (60 seeds in 12 keys), the chorus sings above the verse in 678; in the
# rest the range leaves no higher octave for it. A description, not a target (ADR-019).
VERSE_CENTRE: Final = RANGES[Instrument.LEAD][0]
CHORUS_CENTRE: Final = 74

# A verse is sung softly whatever the band's dynamic; a chorus at the band's own.
VERSE_VELOCITY: Final = 66

# What tells the verse's tune from the chorus's, inside one song's `tune`.
SALTS: Final[dict[str, int]] = {VERSE: 1, CHORUS: 2}
SUNG: Final[frozenset[str]] = frozenset(SALTS)


def play(section: Section, rng: Random) -> Part:
    """One lead part for the whole section: the solo, a melody, the hook, or nothing."""
    if section.name == SOLO:
        return _solo(section, rng)
    if section.name in SUNG:
        return _sung(section, rng)
    if section.dyn < LEAD_DYN:
        return Part(instrument=Instrument.LEAD)

    motifs = BUSY if section.tension > BUSY_TENSION else QUIET
    motif = motifs[rng.randrange(len(motifs))]
    velocity = min(127, max(1, BASE_VELOCITY + DYN_VELOCITY * section.dyn))

    notes: list[Note] = []
    for bar in answering_bars(section.bars):
        chord = section.chart.at(bar)
        pitches = _in_range(
            tuple(
                degree_to_pitch(chord, _in_the_chord(chord, degree), LEAD_OCTAVE)
                for _, degree in motif
            )
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


def _solo(section: Section, rng: Random) -> Part:
    """The lead's own section: a line in every bar, over the whole chart.

    **Two runs, alternating.** One run played eight times is a riff and eight fresh runs are
    eight beginnings, so the section draws a call and an answer and repeats the pair. They
    sound different each time anyway, because each bar re-roots on its own chord.

    **The dynamic gate is not consulted.** The knobs can take the hook away — that is what a
    density knob is for (ADR-021) — but they cannot take the solo out of the section the solo
    is the reason for, and invariant 2 says it has to be there with the network off.

    The last bar is the fill's, so the solo lands on its downbeat and holds, rather than
    playing across it. That is the one thing the hook and the solo agree on.
    """
    call, answer = _two_runs(rng)
    velocity = min(127, max(1, BASE_VELOCITY + DYN_VELOCITY * section.dyn + SOLO_LIFT))

    # slot in the section, step of the key's scale, how long it sounds.
    figures: list[tuple[int, int, float]] = []
    for bar in range(section.bars - 1):
        run = call if bar % 2 == 0 else answer
        anchor = _anchor(section, bar)
        last = len(run) - 1
        figures.extend(
            (
                bar * SIXTEENTHS_PER_BAR + slot,
                anchor + step,
                LAST_NOTE_BEATS if index == last else NOTE_BEATS,
            )
            for index, (slot, step) in enumerate(run)
        )
    landing = section.bars - 1
    figures.append((landing * SIXTEENTHS_PER_BAR, _anchor(section, landing), LAND_BEATS))

    pitches = _placed(tuple(step for _, step, _ in figures), section)
    notes = [
        Note(
            pitch=pitch,
            start_beats=beats_of(slot, section.feel),
            duration_beats=held,
            velocity=velocity,
        )
        for (slot, _, held), pitch in zip(figures, pitches, strict=True)
    ]
    return Part(instrument=Instrument.LEAD, notes=separate(humanise(notes, rng, feel=section.feel)))


def _sung(section: Section, rng: Random) -> Part:
    """The song's melody for this kind of section, fitted to this section's chords.

    The phrase and its shape come from the song's tune, not from `rng`, so every verse of a
    song sings the same melody: what changes from one verse to the next is only the chord each
    note is fitted to. `rng` humanises the result, like every other part.

    The last bar is the fill's, as for the solo: the melody lands on its downbeat, on the root,
    and holds.
    """
    tune = Random(_tune_of(section) * 1_000_003 + SALTS[section.name])
    phrases = VERSE_PHRASES if section.name == VERSE else CHORUS_PHRASES
    phrase = phrases[tune.randrange(len(phrases))]
    shape = tuple(
        CHORD_CHOICES[tune.randrange(len(CHORD_CHOICES))]
        if slot % STRONG_EVERY == 0
        else WALK[tune.randrange(len(WALK))]
        for slot, _ in phrase
    )

    # slot in the section, step of the key's scale, how long it sounds.
    figures: list[tuple[int, int, float]] = []
    last_bar = section.bars - 1
    for start in range(0, last_bar * SIXTEENTHS_PER_BAR, PHRASE_SLOTS):
        step = _anchor(section, start // SIXTEENTHS_PER_BAR)
        for (slot, length), move in zip(phrase, shape, strict=True):
            at = start + slot
            if at >= last_bar * SIXTEENTHS_PER_BAR:
                break
            bar = at // SIXTEENTHS_PER_BAR
            step = _anchor(section, bar) + move if slot % STRONG_EVERY == 0 else step + move
            figures.append((at, step, length * BEATS_PER_SIXTEENTH))
    figures.append((last_bar * SIXTEENTHS_PER_BAR, _anchor(section, last_bar), LAND_BEATS))

    centre = VERSE_CENTRE if section.name == VERSE else CHORUS_CENTRE
    pitches = _sung_placed(tuple(step for _, step, _ in figures), section, centre)
    velocity = (
        VERSE_VELOCITY
        if section.name == VERSE
        else min(127, max(1, BASE_VELOCITY + DYN_VELOCITY * section.dyn))
    )
    notes = [
        Note(
            pitch=pitch,
            start_beats=beats_of(slot, section.feel),
            duration_beats=held,
            velocity=velocity,
        )
        for (slot, _, held), pitch in zip(figures, pitches, strict=True)
    ]
    return Part(instrument=Instrument.LEAD, notes=separate(humanise(notes, rng, feel=section.feel)))


def _tune_of(section: Section) -> int:
    """The song's tune, or one read off what the section says about its song.

    A section the arranger wrote carries its song's seed. One that did not (a hand-written
    briefing, a setlist baked before ADR-028) still belongs to a song with one key, scale,
    feel and tempo, so those make a tune that every section of that song shares. `crc32`,
    not `hash`: Python salts `hash` of a string per process, and a tune must be the same tune
    tomorrow.
    """
    if section.tune is not None:
        return section.tune
    return crc32(f"{section.key}:{section.scale}:{section.feel}:{section.bpm:g}".encode())


def _sung_placed(steps: tuple[int, ...], section: Section, centre: int) -> tuple[int, ...]:
    """The melody as pitches: kept within an octave, then moved bodily nearest `centre`.

    The walk between chord tones can drift, so the line is first folded into `SPAN_STEPS`
    above its lowest note — a step that leaves the window comes back an octave nearer, which
    is the same note of the key. Then the whole line moves by octaves to sit around `centre`
    without leaving the lead's range, which an octave-wide line inside a 29-semitone range
    always can.
    """
    scale_size = len(steps_of(section.scale))
    floor = min(steps)
    folded = tuple(
        floor + (step - floor) % scale_size if step - floor > SPAN_STEPS else step for step in steps
    )
    pitches = [scale_pitch(section.key, section.scale, step, LEAD_OCTAVE) for step in folded]
    low, high = RANGES[Instrument.LEAD]
    middle = (min(pitches) + max(pitches)) / 2
    shift = round((centre - middle) / SEMITONES_PER_OCTAVE) * SEMITONES_PER_OCTAVE
    while min(pitches) + shift < low:
        shift += SEMITONES_PER_OCTAVE
    while max(pitches) + shift > high:
        shift -= SEMITONES_PER_OCTAVE
    return tuple(_folded(pitch + shift, low, high) for pitch in pitches)


def _two_runs(rng: Random) -> tuple[Run, Run]:
    """A call and an answer, never the same run twice. Two draws whichever pair comes out."""
    first = rng.randrange(len(RUNS))
    second = (first + 1 + rng.randrange(len(RUNS) - 1)) % len(RUNS)
    return RUNS[first], RUNS[second]


def _anchor(section: Section, bar: int) -> int:
    """Which step of the section's scale a bar starts on: the one nearest its chord's root.

    Where the arranger wrote the chart it *is* the root, because the chart is diatonic — so
    the bar begins and ends on a chord tone. Where a chart argues with its key, a hand-written
    `E7` in A minor, the nearest step is the honest answer: it is still a note of the key,
    which is the thing the dissonance budget counts, and the alternative is a line that leaves
    the key to chase a chord the rest of the band is voicing anyway.
    """
    steps = steps_of(section.scale)
    interval = (section.chart.at(bar).root - section.key) % PITCH_CLASSES
    return min(range(len(steps)), key=lambda index: abs(steps[index] - interval))


def _placed(steps: tuple[int, ...], section: Section) -> tuple[int, ...]:
    """The whole solo as pitches, moved bodily by octaves until it sits in the lead's range.

    Not `_in_range`: that asks `fit_to_range`, which sorts, which is nothing to a chord and
    everything to a melody — and which raises when no octave fits. A solo is most of two
    octaves wide once the chart has moved its anchor around the key, and *where* an octave of
    the key's root lands inside the range depends on the key, so the octave is chosen here
    from the range rather than written down. `TOP_STEP` is what makes a choice exist.

    The fold at the end cannot fire under any chart the arranger writes, because the arranger
    only writes seven-note scales and `TOP_STEP` is set for those. It is here because a
    five-note scale handed in by hand would be wider than the lattice allows, and the answer
    to that is a note an octave from where the line wanted it — same note of the key, same
    tone of its chord, a little less contour — rather than an engine that raises. A floor with
    a failure case is not a floor (invariant 2).
    """
    low, high = RANGES[Instrument.LEAD]
    offsets = tuple(
        scale_pitch(section.key, section.scale, step, LEAD_OCTAVE) - pitch_of(section.key, 0)
        for step in steps
    )
    root = pitch_of(section.key, 0)
    while root + min(offsets) < low:
        root += SEMITONES_PER_OCTAVE
    while root + max(offsets) > high:
        root -= SEMITONES_PER_OCTAVE
    return tuple(_folded(root + offset, low, high) for offset in offsets)


def _folded(pitch: int, low: int, high: int) -> int:
    """`pitch` moved by whole octaves into `low`..`high`. Terminates: the range is wider."""
    while pitch < low:
        pitch += SEMITONES_PER_OCTAVE
    while pitch > high:
        pitch -= SEMITONES_PER_OCTAVE
    return pitch


def answering_bars(bars: int) -> range:
    """The second bar of each two-bar phrase, and never the section's last.

    One rule, two reasons. A hook on every bar answers nothing — which is the mistake the
    whole band was making under a shuffle (`phase-6-findings.md` §1). And the last bar is
    the fill's, composed after this engine has run (`engines/variants.py`); a lead playing
    across it would be the second thing in the arrangement arriving bolted on.
    """
    return range(1, max(bars - 1, 1), 2)


def _in_the_chord(chord: Chord, degree: int) -> int:
    """`degree`, or the root when the chord does not actually contain it.

    **A third is not always there.** A power chord has none and a sus chord has none, and
    `degree_to_pitch` answers those from the chord's *implied scale* — so under a chart
    that disagrees with its key, degree 3 of `C5` in C dorian is a major third that is in
    neither the key nor the chord. A lead that played it would break the dissonance budget
    on its own and make the floor depend on the repairer, which is a floor with a hole in
    it. `engines/keys.py` guards the same trap on a sus2 pad, for the same reason.

    Found by `tests/property/test_dsl_round_trip.py` once the bake's notation could carry
    a lead at all: 50% of one section's lead notes outside the key, budget 5%.

    The root is in every chord, which is what makes it the safe answer rather than a
    chosen one.
    """
    return (
        degree if degree_to_pitch(chord, degree, 0) % PITCH_CLASSES in chord.pitch_classes() else 1
    )


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
