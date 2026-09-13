"""The General MIDI drum map, as far as this project uses it.

A drum "pitch" is a lookup, not a note: 36 is a kick because the standard says so, and
shifting it by an octave gives a different instrument rather than the same one higher.
That is why `RANGES` in `voicings.py` has no entry for drums and why every pitched rule
in the validator skips them.

It lives in `theory/` rather than in `engines/` because the validator needs it and the
validator must be able to disagree with the engine. A table both of them import from a
third place is what keeps "the engine produced a hi-hat conflict" a statement the
validator can make.
"""

from __future__ import annotations

from typing import Final

KICK: Final = 36
SNARE: Final = 38
CLOSED_HAT: Final = 42
PEDAL_HAT: Final = 44
OPEN_HAT: Final = 46
CRASH: Final = 49
RIDE: Final = 51

# Toms, high to low, as General MIDI numbers them. A fill cue that runs down the kit uses
# them (`engines/variants.py`). On a kit that is one synthesiser they are four pitches,
# which is exactly what makes a run audible as a run.
TOM_HIGH: Final = 50
TOM_MID: Final = 47
TOM_LOW: Final = 45
TOM_FLOOR: Final = 43
TOMS: Final[tuple[int, ...]] = (TOM_HIGH, TOM_MID, TOM_LOW, TOM_FLOOR)

# One pedal, one hi-hat: two of these sounding in the same slot is physically impossible
# and audibly wrong, which is the `hihat_conflict` rule.
HATS: Final[frozenset[int]] = frozenset({CLOSED_HAT, PEDAL_HAT, OPEN_HAT})

# The DSL's `DRM` line writes one grid per voice, tagged by letter.
DRUM_VOICES: Final[dict[str, int]] = {
    "K": KICK,
    "S": SNARE,
    "H": CLOSED_HAT,
    "C": CRASH,
}

# A kick drum pedal cannot return faster than this. It is a fact about a beater and a
# spring, so the rule is in milliseconds and not in sixteenths — at 132 BPM two
# sixteenths are 113 ms apart and legal; at 240 BPM they are not.
MIN_KICK_INTERVAL_MS: Final = 60.0

# Below this velocity a stroke is a ghost: the beater brushes the head and never returns
# to full extension, which is exactly the heel-toe technique drummers use for doubles
# faster than MIN_KICK_INTERVAL_MS. So the spacing rule counts full strokes only, and
# ghosting the second attack is a real repair rather than a way of hiding a violation.
GHOST_VELOCITY: Final = 30
