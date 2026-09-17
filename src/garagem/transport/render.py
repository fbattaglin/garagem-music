"""The one place a `domain.Note` becomes a `daw.MidiNote`.

`domain/` may not import `daw/` (`.claude/rules/domain-purity.md`), which is why there
are two note types at all: `domain.Note` is a musical object designed on musical grounds,
`MidiNote` is the Live Object Model's five-tuple in the LOM's field order. Keeping them
apart stops Live's serialisation from getting a vote on how music is modelled. This
module is the seam, and it is deliberately the only one.

Everything here is pure. The output goes through `daw.normalised` rather than through a
sort written here, and that is not tidiness: `normalised` is the function the Phase 1
idempotence criterion is *stated* in, so a rendered part and a part read back out of Live
compare equal with no tolerance argument at any call site.

`bar_offset` exists because a `SectionScore` counts beats from its own start. The
scheduler decides which bar of the song a section lands in; the score never knows, which
is what makes it a portable object that can be generated ahead of time and dropped into
whichever scene is free.
"""

from __future__ import annotations

from collections.abc import Mapping

from garagem.daw import MidiNote, normalised
from garagem.domain import BEATS_PER_BAR, Instrument, Note, Part, SectionScore

Pitches = Mapping[int, int]
"""What the band writes -> what this Set's instrument is sent (`session.toml`'s `pitches`).

A sampled kit lays its pieces out where its maker put them: the Dry Session Kit keeps its
high tom where `theory/percussion.py` writes a ride. Which note reaches which piece is a
property of the Set, so it is declared there and applied here, on the way out — the music
is written in the band's own vocabulary and nothing upstream of this module knows.
"""


def render_note(note: Note, *, bar_offset: int = 0, pitches: Pitches | None = None) -> MidiNote:
    """One note, shifted by whole bars. Beats stay beats; tempo is Live's."""
    return MidiNote(
        pitch=pitches.get(note.pitch, note.pitch) if pitches else note.pitch,
        start_beats=note.start_beats + bar_offset * BEATS_PER_BAR,
        duration_beats=note.duration_beats,
        velocity=note.velocity,
    )


def render_part(
    part: Part, *, bar_offset: int = 0, pitches: Pitches | None = None
) -> tuple[MidiNote, ...]:
    """One instrument's notes, ready for `write_notes`."""
    return normalised(
        render_note(note, bar_offset=bar_offset, pitches=pitches) for note in part.notes
    )


def render_score(
    score: SectionScore,
    *,
    bar_offset: int = 0,
    pitches: Mapping[Instrument, Pitches] | None = None,
) -> dict[Instrument, tuple[MidiNote, ...]]:
    """Every part of a section, keyed by instrument.

    A dict rather than a tuple because the caller's next question is "which track does
    this go on", and that is a mapping the session owns, not an order this module can
    guess.
    """
    return {
        part.instrument: render_part(
            part,
            bar_offset=bar_offset,
            pitches=pitches.get(part.instrument) if pitches else None,
        )
        for part in score.parts
    }
