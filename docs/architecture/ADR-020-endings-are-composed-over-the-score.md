# ADR-020 — Endings are composed over the finished score, by the scheduler

Status: **accepted** · Date: 2026-09-12 · Written for Phase 4, Stage 2.
Refines ADR-017's "extensions of `_arranged()` and of the engines". Depends on ADR-017
and ADR-019; serves invariants P2, P4 and P7.

## Context

ADR-000 §7 asks Phase 4 for *"a dynamics curve and transitions between sections (fills,
breaks, builds)"*. ADR-017 settled that this is composition, not generation — asked for in
one call, the arranged form was cancelled 30 times in 30 — and said the work would be
*"extensions of `_arranged()` and of the engines"*. `STATUS.md` carried that as the plan.

Writing it showed three reasons that location does not fit what a transition is.

**A transition is the whole band, and `_arranged()` is the drums.** A stop silences the
bass, the guitar and the keys after the downbeat; a final chord lengthens all three. Inside
the generators that is the same decision written in four engines and three realiser paths,
seven copies of one piece of form, with a round-trip property test needed to keep each
pair agreeing.

**A transition depends on the section after it, and no generator is told what that is.**
`play_section(section, seed)` and `realise(parsed, seed)` see one briefing. The obvious fix
— a field on `Section` — puts it on the `SEC` line the model is held to (`SEC_FIELDS`,
`check_sec`), in the briefing the prompt is built from, for a decision ADR-017 already
took away from the model.

**The form should not depend on who wrote the groove.** ADR-017's own principle is "two
sources, one score". A build that the floor plays and a model's section does not, or plays
differently, would put form back into the A/B that ADR-017 took it out of.

## Decision

**1. An ending is composed over a finished `SectionScore`**, in `engines/transitions.py:
compose(score, ending, into=...)`. Four endings: `FILL` (the identity — the generators
already end on a fill, approved by ear in Phase 2), `BUILD`, `STOP`, `FINAL`.

**2. It never invents a pitch.** It removes notes, moves velocities, lengthens hits and
adds drum hits. Which chord rings at a stop is the groove's, and the chart is the
briefing's. That keeps range, kick spacing and the root under a chord change true by
construction, and a property test holds the rest over any briefing, seed and ending.

**3. The scheduler applies it, at write time, only when it is given endings.** It is the
one place both sources pass through — a score from the buffer and a fallback from the
floor — and the one place that knows which section actually follows. What `compose`
returns is validated; if it breaks a rule the score kept, the section plays as generated
and the log records `transition_declined` (P4 over our own composition, P7: not retried).
`endings=None` is Phase 3's scheduler, byte for byte.

**4. Which ending, and the dynamics curve, are data.** `ENDINGS` maps pairs of section
kinds — verse into chorus builds, bridge into chorus stops — and everything else is a
fill. Two positional rules: the last section ends the song, and the step into the last
chorus stops when there is more than one. `arranger.with_climax` lifts that last chorus
one `dyn` and 0.1 tension above the others. No randomness: the same form gives the same
endings.

**5. `play_section` and `realise` are unchanged**, and so are their eight golden files.
`scripts/jam.py --plain` plays the form as every listening before Phase 4 heard it.

## Rejected alternatives

**Extend `_arranged()` and the four engines**, as ADR-017 and `STATUS.md` said. Seven
copies of the form, a generator signature that has to learn about its successor, and a
fixed-point test per copy. Rejected on the count, not on principle: the first fill and
crash stay exactly where ADR-017 put them.

**A `Section` field for the ending or the next section.** Cheapest to thread through, and
it puts an arrangement decision on the `SEC` line, where an echo that disagrees is a
`section_mismatch` and where every change moves the briefing a model is sent.

**Compose in the producer.** It covers the model's sections and misses the fallback, so the
same song would end its sections one way when the network is up and another when it is
not — P2 would degrade the form, not only the groove.

**Choose endings from the seed.** Variety is cheap to add and hard to argue with: a table
can be pointed at and disagreed with by ear, a weighted draw cannot. If five identical
builds in three minutes turns out to be what the ear objects to, that is the change to
make, and it is a change to a table.

## Consequences

**The music that was approved by ear now plays differently in a song, and has not been
heard.** The generators are untouched, but every section's last bars can change, the last
chorus is louder, and the song ends on a chord. Phase 2's verdict does not cover this. It
is judged by ear at the Stage 2 gate (ADR-019), with `--plain` as the reference.

**The scheduler does a little more at write time**: one composition and one validation per
section, measured under 1 ms on an eight-bar section, at the point where it already
generates a fallback. Nothing moves closer to the boundary.

**A repeated section replays its ending into itself.** When the next section is not ready
the clip loops (ADR-001), and a build now builds into the verse it came from. It was
already a degradation; it is now an audible one.

**The last chorus's briefing changes** — `dyn=5 tension=0.8` in the default song — so a
model generating it is asked for more than it was.

**`kit_collision` rises in a build**, because the roll lands on the kick. ADR-019 bars the
metrics from being targets; this is recorded so nobody reads the rise as a regression.

**The tactical layer has somewhere to land.** A cue that means "stop here" is an ending
chosen by a person instead of by the table, through the same function.

**What this does not fix.** Whether Drift answers velocity is unknown: every instrument in
the Set is Drift, and if its velocity sensitivity is low the swell is inaudible and only
the roll's density carries the build. Nothing here has been listened to.
