"""The second guitar: the rhythm part played again, so a chorus has two guitars panned apart.

A double-tracked guitar is the arena half of ADR-028's sound. Two takes of the same part,
panned hard left and right, are heard as one wide guitar *because* the two takes are not
quite together: identical MIDI on two tracks is one guitar in the middle.

**The second take is the first one's timing mirrored around the grid.** Where the guitarist
was 7 ms late, the double is 7 ms early, so the two drift apart by twice the humanisation
and never further. That keeps the double inside the grid tolerance by construction, and it
draws nothing from the section's `Random`: no engine after it can move, and no golden file
outside the double's own lines changes because it exists.

**It is derived, not written.** No notation line carries it (`DERIVED_INSTRUMENTS`), so a
model's take gets one exactly as the floor does, from whatever guitar part the take has.
Below `DOUBLE_DYN` the part is empty rather than missing, and that difference matters: the
scheduler writes an empty clip, which silences the previous section's double, where a missing
part would leave it sounding.
"""

from __future__ import annotations

from typing import Final

from garagem.domain import Instrument, Note, Part, Section
from garagem.engines.humanise import separate
from garagem.theory.validator import grid_slots, nearest_slot

# A chorus and the climax: where the arena half of the sound is (ADR-028).
DOUBLE_DYN: Final = 4


def double(guitar: Part, section: Section) -> Part:
    """The second guitar for `section`, made from its first guitar part."""
    if section.dyn < DOUBLE_DYN or not guitar.notes:
        return Part(instrument=Instrument.GUITAR_DOUBLE, notes=())
    slots = grid_slots(section)
    mirrored = (_mirrored(note, nearest_slot(slots, note.start_beats)) for note in guitar.notes)
    return Part(instrument=Instrument.GUITAR_DOUBLE, notes=separate(mirrored))


def _mirrored(note: Note, slot: float) -> Note:
    start = max(0.0, round(2 * slot - note.start_beats, 6))
    return note.model_copy(update={"start_beats": start})
