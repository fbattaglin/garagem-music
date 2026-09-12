# ADR-019 — The ear is the instrument; the machine's job is to make listening cheap

Status: **accepted** · Drafted 2026-09-11 · **Accepted by Fabiano on 2026-09-12**, as drafted.
Amends ADR-000 §7's Phase 4 metrics criterion and discharges ADR-018's debt #1.
Depends on nothing; blocks nothing mechanical.

## Context

ADR-000 §7 asks Phase 4 for coherence metrics that are *"in range"*. ADR-018 made them a
gate before they became a tool, on the reasoning that a metric written against a human
verdict *"can be wrong in a way that is visible"*, while one written against intuition
*"would only ever agree with whoever wrote it"*. That order was right, and it is the only
reason this ADR can be written cheaply rather than after a phase of wasted work.

**Three mechanisms have now been proposed to explain what Fabiano hears. None survived.**

1. **`register_spread` and `harmonic_conformance`** — §16's mechanism, and the two metrics
   ADR-000 §7 names. Refuted structurally (`phase-4-findings.md` §1): `register_spread`
   measures 1.000 on all 112 recorded model sections, because the DSL never lets a model
   name a pitch. Out-of-chart notes and a band piled into one octave are things the
   architecture forbids the model to produce. Cost to find out: $0.
2. **`kit_collision` as a label for mess** — the one measured difference in the corpus
   pointing the same way as the three *"cleaner, less messy"* votes. 6 of 10 against a
   threshold of 8 (§3). The design error was in the question: it asked the ear to be a
   measuring instrument for a *word*, which is a different job from the one it is the
   reference for.
3. **`kit_collision` as a predictor of preference** — the re-aim, asking the question
   ADR-000 actually specifies. Pre-registered at 12 of 16; **measured 5 of 16, with the
   point estimate inverted** (§5). The take the metric calls messier was preferred in 10
   of 15 decisive pairs, and *"cleaner, less messy"* — the phrase the metric was built
   from — split 1–1.

Two facts bound what can be done next, and both are measured rather than assumed.

**The cheap search is over.** 23 briefings have been heard; exactly one new pair remains
constructible from the 107 sections Phase 3 paid for. Further calibration needs freshly
generated material — API spend and a listening session per round.

**The scarce resource is one pair of ears.** Not compute, not money: at n = 1, every
hypothesis costs a session, and a vote cannot say why it was cast. That was true when
ADR-018 named it and it is what makes a bad search expensive.

What has **not** been established is that no metric could work. Three were tried, in two
of the three cases against a mechanism invented after the fact. This ADR is about what to
do with that, not about closing the question.

## Decision

**1. No metric steers Stage 2.** The dynamics curve and the transitions — fills, breaks,
builds — are composed over the model's groove (ADR-017) and judged the way Phase 2's floor
was judged: **by ear, at the gate**. There is no validated number to tune against and
pretending otherwise is the failure mode this project has spent two phases avoiding.

**2. The metrics stay in the event log, explicitly barred from being targets.** They are
deterministic, free, and they describe what was played, which is useful telemetry. What
they may not be is an objective: a number that becomes a target stops describing. The bar
is written down here so it survives someone's good idea later.

**3. The inverted sign is recorded as a hypothesis and not acted on.** Flipping
`kit_collision` and steering by it would be reading a mechanism off a finished run — how
§13's chorus split and §16's register hypothesis both died. If it is tested, it needs its
own pre-registration written **before** the material exists, run on sections Stage 2
generates anyway so the question costs nothing extra.

**4. Phase 4's metrics criterion is amended**, not deleted: from *"coherence metrics on
every section, in range"* to **"every section carries its metrics in the event log, and no
metric is used as a target until one has passed a pre-registered preference gate."**
ADR-018's debt #2 — the blind A/B re-run at 8 of 12 — is **untouched**.

**5. The measurement instrument for this music is the ear, and the machine's job is to
make using it cheap**: blind, balanced across sections and feels, pre-registered,
resumable, and logged with the material beside the verdict. `scripts/ab_section.py` and
`scripts/calibrate_metrics.py` already are that instrument. This names it as the design
rather than as scaffolding for a metric that was going to replace it.

## The move this ADR is making, stated plainly

**This amends an exit criterion after seeing the data.** ADR-018 refused exactly that
shape of move — it declined to lower the A/B threshold to parity after seeing 12 of 24,
and wrote: *"A criterion that moves to meet the data measures nothing."*

The distinction claimed here is between a **bar** and a **premise**. ADR-000 §7 assumed a
cheap metric that tracks the ear exists; §1, §3 and §5 are evidence against that
assumption rather than against any threshold. **That distinction is also exactly what a
motivated reading would produce**, and it deserves suspicion rather than acceptance. Three
checks it has to pass to be honest, all of them falsifiable by reading the diff:

- **No threshold moves.** The A/B stays at 8 of 12; the calibration gate's 12 of 16 is
  recorded as missed, not lowered. If this were threshold-lowering in disguise, that is
  where it would show.
- **The amended criterion is harder in one direction.** It forbids using any metric as a
  target, which the original text permitted. A criterion bent to fit the data does not
  usually add a prohibition.
- **Nothing is marked met.** Phase 4 still cannot close on this line, and `STATUS.md`
  still carries it unticked.

If those three do not convince, the honest alternative is on the record below: hold the
criterion exactly as ADR-000 wrote it and spend money on a fresh corpus. That is a
legitimate call and it was Fabiano's to make. **He chose this ADR over it on 2026-09-12.**

## Rejected alternatives

**Flip `kit_collision`'s sign and steer by it.** The reversal is the most interesting
thing in §5 and it is 10 of 15 at p = 0.15 — a hypothesis read off a finished run.
Rejected on the project's own two precedents: §13's chorus mechanism looked like
p = 0.015 and replicated at p = 1.000.

**Tune the metrics until they agree with the sixteen votes.** Fitting noise at n = 16.
Worse, it destroys the property ADR-018 built the gate for: a metric tuned against the ear
it failed to predict has no falsifiable job left, and would thereafter agree with whoever
tuned it.

**Delete the metrics.** They cost nothing to compute, they are deterministic, and a
section's numbers beside its seed in the event log is useful telemetry regardless of
whether it predicts taste. Removing them loses that and gains nothing.

**Buy a fresh corpus now and keep hunting.** Legitimate, and rejected on **sequencing
rather than on principle**. Stage 2 generates sections anyway; the same question can be
asked a phase later for the cost of the listening alone. If the hunt should continue now,
this is the alternative to choose, and choosing it means keeping ADR-000 §7's criterion
exactly as written.

**Recruit more listeners to fix n = 1.** A real limitation, correctly named in `STATUS.md`
and already rejected for this gate by ADR-018. Nothing since has changed the argument.

**Hold Phase 4 open until some metric passes.** This honours the phase-gate rule
(*"a nearly met criterion is an unmet criterion"*) most literally. Rejected because it
blocks the phase on an open-ended search, funded by the scarcest resource the project has,
with the corpus that made iteration free already spent.

## Consequences

**ADR-000 §7's Phase 4 metrics paragraph is amended, not deleted**, in the one place named
above. The roadmap keeps its original text and points here.

**ADR-018's debt #1 is discharged, by being answered.** The metrics were given a
falsifiable job before a tuning job, and they failed it twice. That is a closed loop and a
result, not an outstanding obligation.

**Stage 2 has no numeric target, so the ear becomes the gate.** Listening sessions turn
load-bearing for arrangement work, and they are slow and n = 1. That is the real cost of
this decision and it should be stated as a cost, not smoothed over.

**The routing question moves up the roadmap.** ADR-018 already observed that if the model
never beats the floor, ADR-005's *"engine as an instrument, not a fallback"* stops being a
design stance and becomes a verdict. There is now also no cheap metric to adjudicate it,
which makes *when the model is worth calling at all* a plausible real subject for Phase 5,
ahead of Setlist Mode.

**What this does not fix.** Nothing about the music changed today. n = 1 is unchanged.
And the possibility that a good metric exists and three wrong places were searched stays
open — this ADR says the **cheap** search is finished, not that the answer is no.
