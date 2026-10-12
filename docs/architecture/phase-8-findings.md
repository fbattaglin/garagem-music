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

## 2. The band's sound, chosen by ear (Stage B) — the tools, before the listening

What Stage B needs from code is built. The sound itself is chosen by Fabiano, by ear, in Live.

### The guitars: Lite's own, after Stratus was dropped

Fabiano first chose Impact Soundworks' **Shreddage 3 Stratus FREE** (2026-10-11), a sampled
electric guitar with its own amp, palm mutes and sustains, which runs in the free Kontakt
Player. Installing it, he dropped it: *"Muita confusao instalar o contact player. Ele vem cheio
de catchy stuff e freemiuns e uopgrades e acabou instalando várias coisas na minha máquina."*

Kontakt Player was removed, more than 1 GB of it. That covered the app, its AU, VST3, VST and AAX
plugins, its factory content, its preferences and its eight installer receipts. Nothing of it
ran in the background. Stratus still needed an Impact Soundworks account, their download
manager, a Native Instruments account and Native Access, so none of that was installed.

The guitars are now Core Library's **Guitar Electric Muted**, one palm-muted Strat sample,
through Lite's **Saturator**, with EQ Three's high band turned down to stand in for a cabinet.
GTR 2 gets a heavier Saturator preset. Nothing to install, no account, no licence.

- **The ceiling is the sample, not the drive.** One palm-muted note, stretched across the neck,
  chugs well in a verse. A chorus asks it to ring, and a palm mute does not ring. That is where
  the sound check will tell.
- **The next step, if a chorus is thin, is one plugin with no account:** Blue Cat's Free Amp
  in place of the Saturator. It changes the amp, not the sample.
- **`palm_mute_below` is gone from `session.toml`.** A single sample has no split to protect.
  The clamp stays in code, off unless a track declares it.

### What was built

- **`palm_mute_below` in `session.toml`.** The humaniser moves a velocity by up to 12, which
  carries a loud chug over any split and a quiet strum under it. `engines.guitar.articulated`
  clamps them on the way out, so the split is a contract rather than a likelihood. Off unless a
  track declares it.
- **The instrument is checked by name.** A device on the track must be called what
  `session.toml` says, or start with it. This would have caught the kit drifting from Dry
  Session to Gen Purpose, which `session.toml` now records.
- **The mix as code.** `volume`, `pan` and `sends` per track are read, diffed and applied
  through AbletonOSC, each write confirmed by a read within a float's tolerance. `bootstrap_set.py
  --mix` prints the open Set's mix as lines to paste in, so nobody types a fader position. A
  second `--apply` writes nothing.
- **`scripts/soundcheck.py`.** It loops a verse, a bridge and a chorus of the band. `--only
  ROLE` plays one role and `--pocket off` turns the players' leans off. A wrong instrument is
  reported but does not stop it, because choosing instruments is what it is for. A Set it
  cannot write into, or one that is already playing, is refused.
- **`src/garagem/stage/`** begins. It holds the roles table that `jam.py` and the sound check
  share, and Stage D grows from it.

Suite at **3088 passed, 27 skipped**.

### Waiting on Fabiano

Building the six-track Set, choosing the sounds with the sound check, pinning the mix, and one jam's verdict against the arena/indie reference.

## 3. A melody through the song (Stage C)

### The floor sings

`engines/lead.py` gives a verse and a chorus each a melody. Verses and choruses still have the
hook and the solo beside them, and the hook keeps the bridge and the intro.

- **A song has one tune.** `Section.tune` carries the song's seed: the arranger sets it on
  every section, and anything derived from a section inherits it. Every verse of a song sings
  the same phrase and contour, fitted to its own chords, and the chorus sings its own. A
  section with no tune (hand-written, or baked before ADR-028) takes one from its song's key,
  scale, feel and tempo, so its song still has one.
- **Legal by construction.** On beats 1 and 3 a note is a tone of the bar's chord; between
  them it moves through the key by a step or two. The solo's argument, made again.
- **A verse sits as low as the lead goes and a chorus near D5**, so the chorus lifts. Over 720
  arranged songs (60 seeds in 12 keys) the chorus sings above the verse in 678. In the rest,
  the range leaves no higher octave. This is a description, not a target.
- **The last bar is the fill's.** The melody lands on its downbeat, on the root, and holds.

Swept offline over **9 600 arranged songs, 70 944 verse and chorus sections: every one sings,
0 violations.** A take that writes an empty `LED` line still rests there. That is the
model's choice, and the floor does not overrule it.

### The bake asks for two melodies

`SYSTEM_THEME` asks for six lines: a riff, two bars of verse melody and two of chorus melody.
`SYSTEM_SONGWRITER` lost *"most bars should be [empty]"*. It now says the lead is the song's
singer, the guitar plays power chords, the organ holds and rests in a quiet verse, and the
bass is at `oct=1`. The live blocks are untouched, and still pinned by digest.

**Measured on the show's four songs, for $0.0188** (`--themes-only`): four themes, each in
the six-line shape, each chorus starting higher than its verse.

### Two things the probes found, and what was done

- **The parser let a line lose notes in silence.** `deg:1=5 hold=5,9=8,11=5 hold=13` kept the
  last `hold=` and dropped the first, and two notes with it. A field written twice is now
  refused. A `hold=` on a slot that strikes nothing is dropped instead of refused, because
  realising it always did that. One kept take in `arrangement.json` does it, and refusing it
  would have silenced a solo Fabiano kept. Every baked setlist still parses: 0 lines refused.
- **Given the six lines bare, the model sang them as one four-bar tune.** It sang verse and
  chorus melody in turn, in a verse and in a chorus alike (first probe, verse and chorus). The
  section's message now names the material (`riff:`, `verse melody:`, `chorus melody:`) and
  says which one this section sings. Re-probed, the verse sang only the verse melody (MIDI
  62–71), and the chorus only the chorus melody (67–79), landing on the root. Both had 0
  violations.

**Spent on Stage C: about $0.09–0.11**: themes $0.0188 and four probe calls at about $0.0175.
A shell mistake of mine may have sent one more probe call. The logs cannot confirm or rule it
out, and it would add about $0.0175.

**Not heard yet.** The floor's melody plays in the sound check and any jam. The model's
melodies are heard after the show's bake, which waits on Stage E's tempo per song.

## 4. The guitars come from GarageBand (Stage B, re-planned: ADR-029)

After a restart, Fabiano asked for a re-plan around what Stage B had taught: *"Minimizar
downloads … eu tenho garage band, posso comprar uma guitarra paga se ela valer muito a pena …
vamos ser criativos"*. He chose to rebuild GarageBand's own instruments for Live, with
nothing downloaded: guitar first, then drums and bass.

### What is on disk, and what was built

- **The Vintage Strat** has every string sampled on its own, ringing and palm-muted. It is
  239 zones over one 16-bit mono file of 9.7 minutes. Its offsets sit in an EXS file that
  `sounds/exs.py` now reads. It parses 211 of the Mac's 214 EXS instruments, and the three it
  refuses are a newer format that none of the band's instruments use.
- **The mapping keeps 58 of the 239 zones**:
  - each key on one string, the lowest that reaches it in the first frets;
  - palm mutes below velocity 80, ringing notes from 80, with the loud layer from 122;
  - every key from 36 to 91 and every velocity from 1 to 127 plays exactly one sample;
  - taps, ready-made chords and GarageBand's one-string groups are dropped.
- **Four presets**, in User Library › Presets › Instruments › Instrument Rack › GARAGEM:
  *GB Vintage Strat*, *GB Vintage Strat Heavy*, *GB Warm Electric* and *GB Warm Electric Heavy*.
  - Each is the sample rack nested inside an outer rack, then Saturator, then an EQ Three as
    the cabinet (lows −6 dB under 120 Hz, highs −20 dB over 3.5 kHz).
  - The crunch drives 15 dB on a medium curve; Heavy drives 27 dB on a hard curve. Both are
    starting points.
  - The samples take 42 MB, and an import takes about a second. A second run writes the same
    bytes.

### Found on the way

- **GarageBand normalises every sample and puts the level back in the zone.** The kits use
  this from −15 to −27 dB per layer, so the zone's level and its group's are carried into each
  Simpler. The Strat's only non-zero zones are taps, which are dropped.
- **The Strat's high E has one zone with its velocity range off**, lying over a soft layer
  with no loud layer beside it. Logic plays it as the loud layer, so the mapping trims it to the
  velocities nobody else plays instead of dropping it.
- **The Set had never been made six tracks.** The saved Set still has five, with a piano on
  KEYS and no Saturator, so the import prints the Live steps, including making GTR 2.

### Measured

- The suite is at **3288 passed and 27 skipped**. `ruff` and `mypy` are clean. `sounds/` is held
  pure by the architecture test.
- **Nothing of Apple's or Ableton's is committed.** The tests build EXS bytes and stand-in
  templates of their own. Where Live is installed, a test also edits Live's real templates.

### Waiting on Fabiano

**Not heard yet.** He drags *GB Vintage Strat* onto GTR and *GB Vintage Strat Heavy* onto GTR 2,
then runs `soundcheck.py --only guitar --only guitar_double` for about five minutes. A yes
goes on to the drums and the bass. A no means looking at a paid guitar.
