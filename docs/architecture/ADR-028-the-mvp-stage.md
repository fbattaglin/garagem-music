# ADR-028 — The MVP's last phase: a modern rock band, on a stage you can run

Status: **accepted** · Date: 2026-10-11 · Written as the Phase 8 plan, agreed with Fabiano
before anything is built. **Amends ADR-000 §7** (the extension list), **ADR-025 §3** (the
approved music changes, not only what it is played on) and **ADR-025 §5** (several songs in
one run). Depends on ADR-013, ADR-021, ADR-022, ADR-024 and ADR-026.

## Context

Phase 7 closed on 2026-10-10 with every criterion met. Fabiano calls Phase 8 **the final
version of this MVP**, and asked that it be planned around two things: **the experience of
running the band**, and whether the band **sounds like a modern rock band**. Read against
those two questions, the system is further away than seven phases of approvals suggest.

**The band plays piano parts on rock instruments.**
- The guitar's power chords start in octave 3, so their roots sit at MIDI 48–59 against a low E
  of 40. `voice_lead` turns many of them into fourths, and from `dyn` 4 — every chorus — they
  become close triads (`engines/guitar.py`).
- The bass roots sit at 36–47, an octave above the low strings (`engines/bass.py`).
- The drums never play a ride or an open hat; both are defined in `theory/percussion.py` and
  never written.
- The piano plays quarter-note triads in the chorus, in the same 56–66 band as the guitar's
  triads.

**The Set has no rock sound in it.**
- Live is **12 Lite** (12.4.6). Amp, Cabinet, Pedal, Overdrive, Roar, Drum Buss, Glue
  Compressor and EQ Eight are all unavailable in this edition (read from Live's own browser
  database).
- The rhythm guitar is one palm-muted Strat sample stretched across the keyboard, with no drive.
  The lead is one clean sample.
- The kit's bus devices are either ones Lite cannot run, or have every macro at 0.
- Every track is at 0 dB and centred, with no sends.
- **The kit drifted silently.** The Set holds *Gen Purpose Kit*, while `session.toml` says
  *Dry Session Kit*. The bootstrap checks that a device exists, not which one.
- Installed and unused: Arturia Analog Lab V (B-3, Stage-73, Wurli; licence unconfirmed) and UVI
  Grand Piano Model D, most likely from the MiniLab's bundle. Live has scanned no plugins at
  all, and no guitar amp plugin is installed.

**There is no operator interface.**
- A song is a `uv run python scripts/jam.py …` line of about 100 characters, and a show is one
  such line per song.
- While a song plays, nothing is printed. A pad strike is confirmed only by ear; `keep` and
  `veto` are not confirmed at all. A declined cue is silent until the report after the last bar.
- Errors speak the code's vocabulary (`quantization`, `section_change`), and each preflight
  failure stops at the first one.
- The README still describes four tracks.

## Decision

Taken by Fabiano on 2026-10-10 and 2026-10-11, each from options put to him.

**1. The references are arena rock and indie rock** — Foo Fighters and Queens of the Stone Age;
Arctic Monkeys, The Strokes and Kings of Leon — *"mas entendo se não der para conciliar"*.
**They are reconciled by the song's own dynamics**, which the arranger already writes:

- **A verse is indie.** One crunchy guitar, the bass moving, closed hats, the organ low or out.
- **A chorus is arena.** A second guitar enters, both high-gain and panned hard left and right.
  The drums open to the ride or open hat and crash. The organ holds the chords underneath.

This is arrangement, not automation: nothing in Live changes mid-song.

**2. The band plays rock parts.** This is the first deliberate change to approved parts since
Phase 6's shuffle, and it passes under ADR-025 §7's light gate:

- **Guitar:** power chords of root, fifth and octave, with roots on the E and A strings and
  moving in parallel. No close triads.
- **Double guitar:** a second, independently humanised guitar from `dyn` 4.
- **Bass:** roots on the low strings.
- **Drums:** ride, open hat and crash in a chorus.
- **Organ:** held chords instead of stabs.
- **The pocket:** a fixed per-voice lean, with no random draws. The snare is slightly late, the
  bass a touch behind the kick, and the chords get a few milliseconds of spread.

**3. The sound is chosen once, by hand and by ear, and then pinned as code.**
- Free plugins for the guitar. Fabiano installs only what he approves from a researched list.
  **Amended 2026-10-11:** he chose Shreddage 3 Stratus FREE, then dropped it while installing.
  Kontakt Player came with upsells and installers, and Stratus still needed two accounts, a
  download manager and an activation app. Kontakt was removed. The guitars are Core Library's
  palm-muted Strat through Lite's Saturator, with EQ Three's high band down for a cabinet. If a
  chorus sounds thin, the next step is one plugin with no account: Blue Cat's Free Amp.
  **Amended again the same day by [ADR-029](ADR-029-the-band-borrows-garagebands-library.md):**
  the guitars, then the drums and the bass, are GarageBand's own, rebuilt as Lite presets by
  code, with the Saturator and the EQ Three inside each preset.
- An organ on keys: Analog Lab's B-3, or Drift's Organ Analog as the Lite-only fallback.
- Six of Lite's eight tracks.
- `session.toml` names each track's instrument and its mix. The bootstrap checks the
  instrument by device name and applies volume, pan and sends.

There is still **no sound-design or mixing agent**. ADR-025 §3 said the approved music would
not change, only what it is played on; this phase changes both, on purpose, and says so.

**4. A melody runs through the song**, in verses and choruses, and the solos stay as they are.
- The floor plays the theme's melody, or a seeded one, without a network.
- The bake asks for a theme that is a riff plus a melody.
- The live prompt does not move (ADR-025's freeze, pinned by digest).

**5. The band is run from one command, with a ready check and a screen.**
- `garagem check | soundcheck | rehearse | bake | show | commands`, from a `[project.scripts]`
  entry. The orchestration moves into `src/garagem/stage/`, and the scripts stay as thin
  wrappers.
- `garagem check` reports every failure at once, each with a fix step in Live's own words.
- **The show screen** (stdlib `curses`, no new dependency) shows the song, the section, the bar,
  what comes next, the knobs, the last command and its outcome, and the cheat sheet. Every cue
  is acknowledged with where it lands, and every decline says why in plain words. **It never
  shows who wrote a section** (ADR-024).
- The screen draws from a tap on the event log, so what it shows is what the log records. It
  never calls into the scheduler.

**6. Commands are typed live**, beside the MiniLab and into the same `CueQueue`.
- A `ConsoleController` implements `ControllerPort`.
- `commands.toml` holds the words, and the cheat sheet is generated from it.
- Every pad has a word.
- Typing reaches what the pads could not: `solo` (`CueKind.NEXT_SOLO`), and the show's `next`,
  `last` and `quit`.

**7. The whole setlist plays in one run.** Between songs:
1. the final chord rings;
2. the transport stops;
3. the next song's **own tempo** is set and confirmed;
4. an *Up next* card shows;
5. a short silence;
6. **a count-in of four stick clicks**.

The show ends on a summary card that offers to save the keeps and vetoes. This amends ADR-025
§5, which built nothing for several songs in one run because its criterion did not need it.
This phase's does.

## Exit criteria

Each rate states its `n`, and each verdict is quoted verbatim.

1. **It sounds like modern rock.** Fabiano chooses the sounds in `soundcheck`; they are pinned
   in `session.toml` and checked by the bootstrap. One jam's verdict, judged against the
   arena/indie reference.
2. **It plays rock parts.** Property sweeps over seeds and feels with 0 violations:
   - the guitar's roots in 40–52 and never a triad;
   - the bass roots in 28–40;
   - the double silent below `dyn` 4;
   - the organ outside the guitar's register.
3. **The melody plays without a network.** The floor plays a melody in every verse of the
   sweep, with 0 validator violations. The bake's lead fill rate is set after the probe.
4. **Ready in one look.** `garagem check` reports every failure at once, each with a fix step,
   tested against the fake adapter for each failure kind.
5. **The screen keeps him informed.** Every cue is acknowledged with where it lands, every
   decline is explained, authorship is never shown, and a headless mode exists for tests.
6. **Typed commands.** Every pad cue and `solo` can be typed, and each lands on the bar a pad
   would. No input becomes a cue it did not name.
7. **The show.** The whole `show.json` plays in one `garagem show`, network off, with ≥ 2 tempos
   and every count-in at its song's tempo. It is conducted from keyboard and MiniLab,
   `setlist_report.py` passes, and the keeps are saved from the end card. Verdict quoted.
8. **Cost.** The bake stays inside an estimate declared before it runs.
9. **Nothing regresses.** The full suite, `ruff`, `mypy` and the bootstrap are clean, and
   `pytest -m live` is re-run at the gate. Golden files move only in the commits that change
   parts, each saying why.

## Rejected alternatives

**Swing and microtiming through Live's Groove Pool** (ADR-000 §7). This cannot be reached from
code: the installed AbletonOSC comments out `clip.groove`, and the LOM cannot load a groove into
the pool. Only the global `groove_amount` is settable. The pocket goes in the note data, where
it is seeded, logged and tested like everything else.

**Upgrading Live to Standard or Suite.** This would give native amp devices, but it costs money.
Free plugins come first; this stays the fallback if they disappoint.

**Running the guitar through Lite's Saturator alone.** This needs no installation and has a
lower ceiling, worst of all for an arena chorus. It was the floor beneath the plugins, not the
plan, until the plugin's install proved heavier than its sound was worth (amended above). It is
the plan now, and its ceiling is heard in Stage B's sound check.

**Going straight from one song into the next.** A medley sounds continuous, but a change of key
and tempo with no pause sounds raw. Declined.

**A pad for "next song".** All eight pads are assigned, and typing reaches it without taking one
away.

**A web or phone control app.** It is the largest of the options, and typed commands with a
terminal screen answer the same need with the standard library.

## Consequences

**Every golden file moves**, because the parts move. They move in the commits that change them,
one engine at a time, with the reason in the message. Setlists are safe: a bake stores its
takes and plays what was baked. The floor's sections in them, however, are played by the new
engines.

**The Set may no longer be reproducible from Core Library alone.** A plugin is a dependency
outside `uv`. That is why the bootstrap now checks instruments by name and the README lists every
install step. If a plugin is missing, the check fails with what to install, rather than the
show playing a silent track. Since the guitars stayed in Core Library, the only plugin left is
the organ, and only if it is Analog Lab's.

**The approved verdicts are re-earned.** Phase 2's band, the endings, the shuffle and the lead
were approved on the old parts and the old sound. Stage B's jam and the show are where they
are heard again.

**The MVP closes on what a person does, not on what the code can do.** After this phase,
running the band is `garagem check` then `garagem show`.
