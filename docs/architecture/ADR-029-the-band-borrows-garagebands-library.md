# ADR-029 — The band borrows GarageBand's library

Status: **accepted** · Date: 2026-10-11 · Agreed with Fabiano from options put to him.
**Amends ADR-028 §3** (where the sound comes from). Depends on ADR-013 and ADR-028.

## Context

ADR-028 §3 has the sound chosen by ear and pinned as code. Three things learned on 2026-10-11
changed where that sound can come from:

- **Third-party installers are out.** Kontakt Player came with upsells and installed several
  things. Shreddage 3 Stratus would also have needed two accounts, a download manager and an
  activation app. Fabiano removed it all (phase-8-findings §2) and asked to *"minimizar downloads"*.
- **Upgrading Live does not fix Lite cheaply.** Upgrading from Lite to Standard costs about
  US$369, and Standard still has no Amp, Cabinet, Pedal, Roar or Sampler. Only Suite has those
  (Ableton's compare-editions page).
- **The ceiling is the sample, not the drive.** Core Library's rhythm guitar is a single
  palm-muted note stretched across the neck. A chorus needs chords that ring.

GarageBand is installed, and its library is already on disk. In `/Library/Application
Support/Logic/` and `.../GarageBand/Instrument Library/` there are:

- a **Vintage Strat** and a **Warm Electric**: each of the six strings sampled on its own, with
  an open (`Main`) and a palm-muted (`Mute`) group, the open one at two velocity layers;
- electric basses (Picked Rock, Fingerstyle, Muted, Liverpool);
- **Drum Kit Designer**'s SoCal, Heavy and Blue Ridge kits.

All of it is in EXS, Logic's sampler format. Live 12 Lite cannot open it, since it has no
Sampler.

## Decision

**1. GarageBand's instruments are rebuilt as Live presets by code.** A small reader for EXS goes
in `src/garagem/sounds/`, along with a mapping and a preset writer. `scripts/import_garageband.py`
runs them:

- it reads Apple's files;
- it decodes the audio with macOS's own `afconvert`;
- it writes WAVs and an `.adg` into Live's User Library.

There is no new dependency, no download and no account. The samples never enter this repository,
and nothing is redistributed: GarageBand's licence covers using its sounds in your own music.

**2. A preset is an Instrument Rack of Simplers, one per sample, zoned by key and velocity.**
That is Lite's own way to multisample. The rack is copied from a preset the installed Live ships
(`Guitar Electric Clean.adg`), so the XML matches the Live that reads it.

**3. Where Logic chooses with more than key and velocity, the choice is made once, here.**
- **The string.** A note goes to the lowest string that reaches it within the first frets, so
  a power chord on E is played on the E, A and D strings.
- **The articulation.** Velocities under `palm_mute_below` play the palm mute, and the rest
  ring. `engines.guitar.articulated` already clamps every guitar note to this split, so the
  split is a contract and not a hope.
- **Left out:** taps, ready-made chords and GarageBand's one-string groups.

**4. The drive is inside the preset.** The sample rack is nested in an outer rack and followed by
Lite's Saturator and an EQ Three standing in for a cabinet, the way Core Library nests its own
layered racks. Each guitar comes twice: a crunch for GTR and a heavier drive for GTR 2. One drag
brings a driven guitar, and the knobs are starting points that are moved by ear.

**5. The guitar goes first, and its listen decides whether the plan goes on.** The drums and the
bass use the same pipeline, but they come only after the guitar's verdict. If the verdict is no,
the next step is a paid guitar, with its install steps checked before anything is bought.

## Rejected alternatives

- **Upgrading Live to Standard (about $369).** It still has no Amp, Cabinet or Sampler. Suite
  does, at a price this does not justify.
- **A paid guitar plugin now**, for example Ample Sound at about $149 or more. It needs iLok,
  a vendor account and several GB of library. It is kept as the fallback if the Strat
  disappoints.
- **Kontakt-based libraries.** Dropped on 2026-10-11 (phase-8-findings §2).
- **Focusrite's Hitmaker bundle** (Addictive Drums 2, REAMP), which Fabiano may already own.
  It needs each vendor's installer and account.
- **Logic Pro (US$199).** Its amps and kits do not load in Live, and the band is driven through
  Live.
- **Building the racks by hand in Live**, one Simpler per sample. That is 58 for the Strat,
  and none of it would be reproducible.

## Consequences

**The Set depends on GarageBand's library being installed**, as ADR-028 accepted for plugins.
If an instrument or sample is missing, the import says what to do in GarageBand. The bootstrap
still checks each track's instrument by name.

**The EXS offsets are reverse-engineered.** The reader refuses what it cannot parse rather than
guess. It reads 211 of the 214 instruments on this Mac; the other three are a newer format,
and none of them is used.

**The XML is Live's, not ours.** If a future Live changes the preset format, the import still
copies its shape from that Live's own template. A rename of the elements it edits makes the
import fail with the missing element's name, instead of writing a preset that loads silent.
