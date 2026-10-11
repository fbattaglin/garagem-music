# Phase 8 findings

## 1. The band plays rock parts (Stage A)

ADR-028 found the band playing piano parts on rock instruments. Stage A changes the parts and
nothing else: the Set, the sound and the listening are Stage B's. **Not heard yet.**

### What changed, voice by voice

| Voice | Before | Now |
|---|---|---|
| Guitar | Power chords from octave 3 (roots 48–59), voice-led into fourths; close triads from `dyn` 4 | Root, fifth and octave with the root on the E or A string (40–51), slid in parallel; never a triad. Rings into the next strum from `dyn` 4 |
| Second guitar | — | `GUITAR_DOUBLE`: the same part with its timing mirrored around the grid, from `dyn` 4. Derived, not notated |
| Bass | Roots in octave 2 (36–47) | Roots between E1 and D#2 (28–39) |
| Drums | Closed hats at every dynamic, sixteenths in a straight8 chorus; one crash per section | From `dyn` 4: open hats on the eighths, and a crash on every phrase (bars 1, 5, …). Straight16 keeps its closed sixteenths |
| Keys | Piano: sus2 pads, quarter-note triad stabs from `dyn` 4 | Organ: rests below `dyn` 3, a sus2 pad at 3, the full chord held across the bar from 4, always above the guitar (≥ 64) |
| Pocket | — | Fixed leans on the way out to Live: snare +0.008 beats, hats −0.003, bass +0.005, lead +0.004, a low-to-high strum of 0.003 per string. No random draws; `pocket=False` switches it off |

A verse is therefore muted guitar, bass and closed hats, with no organ: the indie half. A chorus
adds the second guitar, open hats, phrase crashes and the held organ: the arena half.

### Decisions worth knowing

- **The second guitar mirrors rather than redraws.** Where the first guitar was 7 ms late, the
  double is 7 ms early, so the two stay inside the grid tolerance by construction and draw
  nothing from the section's `Random`. No other part moved because it exists.
- **The pocket lives in `transport/render.py`, not in the engines.** Every note that reaches
  Live passes through there, including the endings and the cue variants. The validator, the
  golden files and the round trip all judge the grid without it.
- **The notation's `H` is "the hat", and the arrangement chooses which one** (`groove.hat_for`).
  Realising a model's take uses the same rule, so the round trip stays exact. A model's
  sixteenth hat in a chorus opens on the eighths and closes between them.
- **A model's `GTR voi=pow` now plays the floor's power chord.** A model's `voi=triad` still
  plays a triad: that is the take's choice, not the floor's.

### Found on the way

- **The serializer wrote a line no parser ever accepted.** A resting guitar or keys bar came out
  as `voi=none`, which the parser refuses. It was never written before, because nothing rested
  until the organ did in a verse. It now writes a voicing with a rhythm of rests.
- **The bake teaches the bass an octave too high.** `SYSTEM_THEME` and `SYSTEM_SONGWRITER` say
  `oct=2`, which is where the floor's bass used to be. They are bake-only, so they change with
  Stage C's prompt work. The live blocks keep `oct=2` under the freeze.

### Measured

- `uv run pytest` → **3064 passed, 27 skipped**. `ruff`, `ruff format` and `mypy` are clean over
  204 source files.
- **Golden files moved deliberately**: all 14 in `tests/golden/` and the 29-entry musical
  regression set. In every diff, only the voices above changed.
- **New property tests** check, over every feel and dynamic:
  - the guitar's roots are in 40–51, and it never plays a triad;
  - every bass downbeat is a root between E1 and D#2;
  - the double plays the guitar's pitches, is not quite together with it, stays on the grid,
    and is silent below `dyn` 4;
  - the organ sits above the guitar;
  - every lean stays within the room the grid leaves the humaniser.
