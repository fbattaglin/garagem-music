# ADR-018 — The blind A/B is waived, not met, and becomes a Phase 4 gate

Status: **accepted** · Date: 2026-09-01 · Written for the Phase 3 → Phase 4 gate.
Waives one clause of ADR-000 §7's Phase 3 exit criterion. Depends on ADR-017;
serves invariant P2.

## Context

Phase 3's last open criterion is the blind A/B: *"the generated section is preferred over
the deterministic one in ≥ 65% of cases"*, fixed as 8 of 12 pairs with Fabiano on
**2026-08-30, before any number existed**. Every other criterion in the phase is met with
evidence: 97% conformance (n=29), 93% validator approval, p95 0.84x of deadline, 25 live
tests passing, and a 90-second performance in which 6 of 6 askable sections came from the
model with 0 schema violations.

The A/B was measured three times — 18%, 58%, 42% — and the two post-composition runs
pool to **12 of 24. Exactly parity** (`phase-3-findings.md` §16). The threshold has never
been reached and was never moved.

Three things make this a decision rather than a failure to keep trying.

**The criterion has an answer.** Not "we do not know yet": twenty-four blind pairs say a
model-written section is neither better nor worse than the deterministic floor. Another
round of prompt work measured the same way would refine a number that is already
converged around a coin.

**The mechanism is identified and it is machine-measurable.** Grouped by the reason
Fabiano gave beside each vote, the floor won **3 of 3** pairs decided on *"cleaner, less
messy"* while the model won 4 of 6 decided on *"less boring"* or *"just sounds nicer"*.
The model writes more interesting material and messier material and the two cancel.
Messiness is notes colliding, instruments piled into one octave, pitches outside the
chart — which is precisely `register_spread` and `harmonic_conformance`, both of them
**Phase 4 deliverables** (ADR-000 §7).

**The loop that would close it is the slowest one the project owns.** Iterating against
the criterion means prompt change → 30 section-shots → 12 blind pairs → one pair of ears
at n=1, with no diagnosis at the end of it: a vote cannot say why. Phase 4 replaces the
ear with a metric on every section in the event log, and hands the ear back a shorter
question.

## Decision

**Phase 3 closes with one waiver, authorised by Fabiano on 2026-09-01. The criterion is
not met, is not marked met, and is not deleted — it is carried into Phase 4 with its
threshold intact.**

Three things this waiver owes, all of them Phase 4 gates:

1. **The metrics must reproduce the ear before anyone listens again.**
   `bench/ab-phase3-final.jsonl` is a **calibration set**: twelve sections, each with a
   blind verdict and a word for it. `register_spread` and `harmonic_conformance` must
   separate the three "messy" losses from the other nine. A metric that cannot is not
   measuring what was heard, and shipping it would mean Phase 4 tuning against a number
   with no known relationship to the music.
2. **The A/B is re-run at Phase 4's close: same design, same threshold, 8 of 12.**
   Blind, balanced across sections and feels, pre-registered. Waiving the gate does not
   lower the bar behind it.
3. **The waiver is named in Phase 4's exit criteria**, so closing Phase 4 without
   settling it requires a second explicit decision rather than silence.

## Rejected alternatives

**Lower the threshold to parity.** 12 of 24 clears 50% and the phase would close clean.
Rejected, and it is the alternative this ADR exists to refuse: moving a threshold after
seeing the number is the single thing pre-registration prevents, and this project has
already been paid twice for pre-registering — §13's chorus mechanism looked like p = 0.015
and replicated at p = 1.000. A criterion that moves to meet the data measures nothing.

**Hold Phase 3 open until the A/B passes.** The honest reading of the rule
(`.claude/skills/phase-gate/SKILL.md`: *"a nearly met criterion is an unmet criterion"*),
and it is why this is a waiver and not a pass. Rejected on leverage: the fix for
*messy* is arrangement and range control, which is Phase 4's work, and the metrics that
would tell us whether it worked are Phase 4's deliverables. Blocking spends the expensive
resource — a human ear at n=1 — on the loop with the worst diagnostic yield.

**Declare the criterion answered and drop it.** Parity answers *"is the model better than
the floor?"*. It does not answer the question ADR-000 actually cares about — whether the
model earns its latency, its money and its failure modes — and that one stays open. Under
P2 the floor plays when the network dies; if the model never beats the floor, ADR-005's
"engine as an instrument, not a fallback" stops being a design stance and becomes a
verdict on the LLM's place in the system. That is a Phase 4 conclusion, not a Phase 3
deletion.

**Add listeners to fix n = 1.** Real limitation, correctly named in `STATUS.md`: a
preference rate is one person's taste and no number of pairs makes it two people's.
Rejected as a fix for *this* gate — recruiting blind listeners is not Phase 4 work and
would not change the mechanism the reasons already exposed.

## Consequences

**The project has its first waiver, and Phase 2's "no waivers" now means something.**
Phase 0, 1 and 2 closed with every criterion met. This one did not, it says so in
`STATUS.md`, and the difference is legible at a glance.

**Phase 4 inherits a debt with a date on it.** Its exit criteria gain the A/B line and
the calibration check. `bench/ab-phase3-final.jsonl` becomes load-bearing evidence rather
than a bench artefact — it is the only file in the repo that carries a human verdict.

**The metrics get a falsifiable job before they get a tuning job.** Written against the
calibration set first, they can be wrong in a way that is visible. Written against
intuition, they would only ever agree with whoever wrote them.

**If Phase 4 closes and the A/B is still at parity, the finding is about the
architecture, not the prompt.** Two phases of evidence that the deterministic floor
matches a model that costs ~$0.0035 and 4.3 s per section would make the routing question
— when the model is worth calling at all — the real subject of Phase 5, ahead of Setlist
Mode's offline case, which already assumes the answer.

**What this does not fix.** Nothing about the music changed today. The model still writes
one bar-level line per instrument, a section's groove still does not vary bar to bar
(ADR-017), and the ear that judged it twice has not been asked a third time.
