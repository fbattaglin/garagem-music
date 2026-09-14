"""What a person at the controller asks the band for: a cue, or a macro. No MIDI here.

ADR-021 and ADR-022. The controller adapter turns a pad strike into a `Cue` and a knob
position into a `Macro`, and nothing past it knows a MiniLab exists. The scheduler, the fake
controller in the tests and a later voice plane all speak these two types.

**A cue is named by what the band does, not by where the pad is.** Which pad sends
`stop` is `controller.toml`'s business. A pad renamed there moves nothing in the music, and
a cue renamed here breaks the loader loudly rather than a performance quietly.

**The families have different timing** (ADR-022), so each kind says which it is:

- a *jump* fires a pre-written candidate section on the next bar;
- a *bar* cue fires a pre-written variant of the section that is playing, on the next bar;
- a *boundary* cue changes sections not yet written, and takes effect at a section change;
- a *mark* changes nothing that sounds: it records a verdict on the section playing, for
  curation (ADR-024).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

FROZEN = ConfigDict(frozen=True, extra="forbid")


class CueFamily(StrEnum):
    """When a cue can take effect, which decides what has to be written ahead for it."""

    JUMP = "jump"
    BAR = "bar"
    BOUNDARY = "boundary"
    MARK = "mark"


class CueKind(StrEnum):
    """A pad. The values are what `controller.toml` and the event log call them."""

    # The band cuts to the chorus on the next downbeat.
    CHORUS_NOW = "chorus_now"
    # The band hits the next downbeat and cuts; the drummer picks up into the bar after.
    STOP = "stop"
    # The drummer fills the next bar.
    FILL = "fill"
    # Guitar and keys drop out on the next bar, and come back with the next section.
    DRUMS_AND_BASS = "drums_and_bass"
    # The next section to be written is a bridge.
    NEXT_BRIDGE = "next_bridge"
    # This section finishes, then the outro and the final chord.
    END = "end"
    # Keep what is playing: a setlist pins its take. Nothing sounds different.
    KEEP = "keep"
    # Not this again: a setlist retires its take. Nothing sounds different now.
    VETO = "veto"

    @property
    def family(self) -> CueFamily:
        return FAMILIES[self]


FAMILIES: dict[CueKind, CueFamily] = {
    CueKind.CHORUS_NOW: CueFamily.JUMP,
    CueKind.STOP: CueFamily.BAR,
    CueKind.FILL: CueFamily.BAR,
    CueKind.DRUMS_AND_BASS: CueFamily.BAR,
    CueKind.NEXT_BRIDGE: CueFamily.BOUNDARY,
    CueKind.END: CueFamily.BOUNDARY,
    CueKind.KEEP: CueFamily.MARK,
    CueKind.VETO: CueFamily.MARK,
}


class MacroKind(StrEnum):
    """A knob. Only the two with a field on `Section` already; ADR-021 leaves six for later."""

    TENSION = "tension"
    DENSITY = "density"


class Cue(BaseModel):
    """A pad was struck."""

    model_config = FROZEN

    kind: CueKind


class Macro(BaseModel):
    """A knob is at `value`, from 0 at its left stop to 1 at its right.

    A position, not a movement. The MiniLab's knobs are absolute (`phase-4-findings.md` §7),
    so the latest value is the whole truth and older ones can be thrown away.
    """

    model_config = FROZEN

    kind: MacroKind
    value: float = Field(ge=0.0, le=1.0)


Control = Cue | Macro
