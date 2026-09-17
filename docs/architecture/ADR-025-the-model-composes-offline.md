# ADR-025 — The model composes offline, and the band gets its sound

Status: **accepted** · Date: 2026-09-16 · Decided by Fabiano after a review of Phases 0 to 5.
Amends ADR-000 §7 (Phases 5 and 6) and ADR-024 §6. Pulls the instruments forward from ADR-013's
deferral.

## Context

With Phase 5 half built, the project stopped to review the band against everything the phases
had found.

**What held up, and stays as it is:**
- the floor first, approved by ear and inaudible when the network died;
- clip-ahead and a cue that costs a fire: 0 beats lost in every session;
- thresholds that never moved.

**What the review found:**

1. **The parity measured the notation, not the model.** Under the live deadline, each step
   narrowed what the model writes.
   - Positions instead of grids, and composition instead of arrangement (ADR-017).
   - It names no pitch: the bass is a chord degree on a rhythm, and guitar and keys are a
     voicing and a rhythm.
   - The arranger writes the charts, and the engines write the form.
   - `phase-4-findings.md` §1: the drums are the only place the material is the model's own.
   - So model and floor choose inside the same small space. The song 1 verse Fabiano vetoed
     is the plainest rock bar there is. 18 of 36 was the expected result.
2. **ADR-024 moved the model offline, but the bake still sends the live request, with the live
   deadline.** None of the constraints that narrowed the notation applies to a bake.
3. **The band has no riff, melody or hook.** Four accompaniment parts.
4. **Every verdict so far was heard through four Drift synths, the drums included.**
   - ADR-013 deferred a Drum Rack because Phase 1 was about timing.
   - `phase-4-findings.md` §6 named the cost: *"the drums are a synthesiser"*.
   - The Live on this machine ships acoustic kits and sampled bass and piano presets.
5. **Live generation is the most complex part of the system, and serves the least used mode.**
   Conducted, the model wrote 12 of 36 sections (`phase-4-findings.md` §12), and since ADR-024
   the floor is the live default.
6. **Phase 5's criteria had been patched to fit a roadmap written before the findings.**
   - The Wi-Fi-off line needed three amendments.
   - Voice would drive, seconds late, what the pads already do on the bar.
7. **The process weighed more than the music.** About 14k lines of source, 19k of tests, 6k of
   scripts and 7k of documents. The rigor found real defects, but went almost all to transport
   and measurement, while the musical vocabulary is still Phase 2's floor plus Phase 4's endings
   and cues.

## Decision

Taken by Fabiano on 2026-09-16, each from options put to him.

1. **GARAGEM is a composer and a stage.** The model writes songs offline, before the
   performance. The floor and the curated setlist play, and Fabiano conducts from the MiniLab.
2. **Live generation is frozen, not removed.** `jam.py --generate` stays working and tested,
   and is still P2's proof. No new live-model feature is built.
3. **The sound comes first.** The four Drifts are replaced with a Drum Rack kit and sampled
   instruments, in the Set, before the next long listening. This is timbre only, pulled forward
   from Phase 6: no sound-design or mixing agent. The approved music does not change, only what
   it is played on.
4. **Voice leaves Phase 5's exit criterion.** `scripts/spike_voice.py` stays as a script.
   Talking to the band comes back for what a pad cannot say, in pre-production ("a darker song
   in D, with a riff"), not as a remote control for the bar.
5. **The Wi-Fi-off session is the setlist played through.** Its three songs play back to back
   as three `jam.py --setlist` runs:
   - at least 600 s in total;
   - 0 beats lost in each run;
   - $0 spent and no adapter built;
   - at least N sections from takes, with N fixed from a rehearsal before the session.
   Nothing is built to play several songs in one run, because the criterion does not need it.
6. **Phase 6 is the songwriter.**
   - **A notation for the bake only, with pitched material:** bass lines, riffs, a lead voice,
     bars that vary within a phrase, and a motif the chorus brings back.
   - **The whole song is written in context, with no deadline.** Several variants per section,
     and a retry at bake time: P7 forbids retries only on the critical path.
   - **Density and tension move out of the take**, and the realiser composes them.
   - Its criteria are written when it is planned.
   - The mixing agent and the asset bakery leave the roadmap until something asks for them.
7. **A musical change passes on a short listen.**
   - Fabiano hears it in a session he plays anyway, and his verdict is quoted in the findings.
   - Pre-registration and thresholds are kept for decisions that cost money or are hard to
     reverse.
   - A findings section fits on a screen.
   - ADR-019 stands: no metric is a target.

## Rejected alternatives

**Close Phase 5 as written, voice included.** It builds a slower path to controls the pads
already have, before the band sounds like a band.

**Invest in making live generation earn its place.** The live deadline is what narrowed the
model to rhythms. Widening the notation live runs into the 30 cancellations in 30 attempts of
`phase-3-findings.md` §14 again. Offline, it does not.

**The songwriter before the sound.** It would add melodies and riffs heard through synth blips,
and judge them by an ear that has not yet heard the band's real instruments.

**Another model-against-floor test.** ADR-024 §4 stands.

## Consequences

**The model's worth is now a question for the songwriter, not the rhythm picker.** ADR-023's
open question moves to where the model has room to answer it. It is judged by playing songs,
with KEEP/VETO and a verdict on the whole song, never by an A/B.

**Every verdict before the new sound was heard through Drift.** They stand. A move that sounds
wrong on real instruments (the toms fill, the snare roll, the palm mutes) is fixed as its own
small change, and the old Set, `garagem-phase1.als`, stays for a comparison.

**Phase 5 closes sooner.** What remains is the new sound, the curation already under way, and
one Wi-Fi-off session.

**The live path keeps its guarantees and gains no features.** P2 still rests on it: the floor
plays whatever the setlist does not hold, with or without a network.
