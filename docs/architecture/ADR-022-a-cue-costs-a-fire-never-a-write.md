# ADR-022 — A cue costs a fire, never a write

Status: **accepted** · Date: 2026-09-12 · Written for Stage 1 of the MiniLab plan, from
Stage 0's measurements. Extends ADR-001 to human cues. Depends on ADR-001, ADR-016,
ADR-020 and ADR-021; serves invariants 1, 2, 5, 6 and 7.

## Context

A human cue has to land on the next bar. Four measured numbers decide how.

- **A bar at 132 BPM is 1.82 s.**
- **A section write costs about a bar**: p50 1163 ms, max 2039 ms over four tracks
  (`phase-2-findings.md` §3; `bench/jam.jsonl`, 2026-09-12). A cue that needs a write
  arrives one bar late at best and two at worst.
- **A fire is free**: an unconfirmed send, ~0.01 ms. A request costs ~100 ms, which is
  0.22 beats (`phase-4-findings.md` §7).
- **The fast model is not fast enough**: `claude-haiku-4-5` measured p50 1.83 s and max
  15.04 s against a 0.73–2.91 s rewrite deadline (`phase-3-findings.md` §14).

Stage 0 then asked the real Set what a fire can rely on. Clip fires and track stops wait for
the bar. Legato carries a clip's position over on a clip fire and on a scene fire, and
applies when it is set just before the fire. When two triggers land before the same bar in
one track, the last one wins. This Live allows 16 scenes.

## Decision

**1. Everything a cue can trigger is written before it can be needed, into a slot that is
not playing, and the cue itself is only fires.** It never writes, never reads and never
waits (ADR-001, invariant 6). The model never serves a cue: it refines the section *after*
one, on the producer's thread, through the buffer, as for any section (ADR-016, P7).

**2. Three families of cue, each with its own pre-written material.**

- **Jump** ("chorus now"): fire a **candidate** scene.
  - Candidates are the floor's sections for the cued kinds. They are written before the
    downbeat, when nothing is playing and a write costs nothing musical.
  - Live starts the candidate from its bar 1, crash included, on the next bar.
  - The remaining form is then **re-planned** from the cued kind (§6). The section after the
    candidate is written into the free main scene during the candidate's own bars, and the
    producer asks the model for it.
- **Bar** ("stop", "fill"): fire **legato variant** clips of the section that is playing.
  - Variants are written during the previous section, after its main write.
  - Each track continues from the same position in its variant for one bar. The main clip is
    then fired back, with legato, from the same position.
  - "Drums and bass only" needs no variant. It is a quantised stop of the guitar and keys
    tracks, and the next section's scene fire brings them back.
- **Boundary** ("next: bridge", "end", and the knobs): change sections not yet written.
  - This means the next section, if it is not yet fired and there is time to rewrite its
    free scene, and otherwise the one after.
  - Knobs map to `dyn` (density) and `tension`, fields the briefing already has, so the
    model sees them at no schema cost.
  - These take effect at a section boundary, by design.

**3. Scene layout**, declared in `session.toml` and validated by the bootstrap:

| Scenes | Holds |
|---|---|
| 0, 1 | the main sections, alternating (ADR-001) |
| 2 | chorus candidate |
| 3 | bridge candidate |
| 4, 5 | STOP variants of the sections in 0 and 1 |
| 6, 7 | FILL variants of the sections in 0 and 1 |
| 8–15 | free |

A variant lives in the variant scene paired with its main scene, so the variant of a
playing section is never the slot being written for the next one.

**4. Legato is off on main clips and candidates, and on for variants.**
- A scene fire honours legato, so a main clip left with legato on would start the next
  section mid-way whenever the one before it was cut short.
- The return from a variant sets legato on the main clip immediately before the fire and
  off again after the launch. Stage 0 row four is the evidence that Live accepts this.

**5. Precedence is explicit, because Live's is "last trigger wins".**
- **A jump cue wins over a scheduled section change.** The person is the conductor; the
  scheduler does not fire what the cue replaced.
- **A bar cue never displaces a section change.** In the bar where the next section has
  already been fired, a bar cue is declined and logged.
- **A second cue in the same bar replaces the first**, as it would in Live, and the log
  records both.

**6. Human input stays replayable (invariant 7).**
- Every cue is logged with the bar it arrived in and the bar it was fired for.
- A re-plan is seeded from the song's seed and the ordinal of the cue that caused it, so the
  seed plus the cue log reproduces the performance — tested, not assumed.
- Knob values are logged when they change a briefing, not every time they move.

**7. The controller thread only enqueues.** The rtmidi callback puts a cue into a bounded,
lock-protected `CueQueue` and returns, in the ADR-014 idiom. The scheduler drains it:
- between bars, by waking from `wait_for_bar` in short slices;
- between the per-track steps of a write, so a cue waits at most one track.

`transport/` never imports `control/`. `jam.py` wires them together. Invariant 1 holds for
people as it does for models.

**8. The cue quantum is one bar**, as the criterion asks, and it is a setting
(`quantum_bars` in `controller.toml`), so "next phrase" can be tried by ear without code.

**9. The band's tracks are disarmed while it plays**, declared in `session.toml` and fixable
by `bootstrap_set.py --apply`. An armed track plays the MiniLab's notes, so a cue pad would
sound inside the band (`phase-4-findings.md` §7).

## Rejected alternatives

**Write at cue time.** Simplest, and it lands one bar late at best and two at worst. The
criterion says next bar, and the measurement says a write cannot do it.

**Cues only at section boundaries.** Needs no new material. A person who presses "stop"
and hears it fourteen seconds later has not been obeyed, and the criterion rules it out.

**Track mute and unmute for "drums and bass only".** Mute is immediate, not quantised, so
the moment the guitar drops out would be Python's timing — which ADR-001 and invariant 6
exist to keep away from the music.

**Clip follow actions to return from a variant.** Live has them, but AbletonOSC does not
expose them, and a returning clip driven by a property nothing here can read or set would be
behaviour the event log cannot see.

**Ask the fast model for the cue's bars.** Measured at p50 1.83 s and max 15.04 s against a
deadline under three seconds. The model's contribution is the section after the cue.

**Legato on every clip.** One rule instead of two, and every jump would start its section
wherever the interrupted one had got to.

## Consequences

**More is written per section.** On top of the next main section, each section's STOP and
FILL variants: about three more tracks of writes, at roughly 300–500 ms a track.
- They are spread one track per tick after the main write, and never inside the bar in
  which a fire is due. The fire check runs before any write.
- A variant not ready when its cue arrives is logged `cue_unavailable`, and nothing fires.
  The music continues, which is P2.
- `beat_lost` and each write's `ms` are watched in every live run, because this load shares
  Live's control-surface thread with the beat listener.

**A jump always lands on the floor's section**, never the model's. A candidate is written
before the song starts, and a model section cannot be. The model's work begins with the
section after the jump. This is the price of the next bar, and the blind A/B at the phase's
close already compares the two.

**The scheduler holds more state**: which scene carries what, which variants are ready, a
pending return, and the live form. Scene bookkeeping moves into its own module so the
invariant-6 check stays one function that can be read and tested alone. The form becomes a
versioned plan shared with the producer, and a score generated for a briefing the plan no
longer holds is refused as stale.

**The fake Live has to model launches per track** — quantised, legato-aware, last trigger
wins — so the offline suite can say what sounds in each bar. The launch semantics it models
are exactly the ones Stage 0 measured, and the spike script is how that stays true.

**What this does not fix.** Whether cueing feels good. Every rule here is about landing on
the bar; whether a stop on a pad, a jump to the chorus or a knob's first jump sounds right
is the gate at the end of each stage, by ear.
