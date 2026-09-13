# ADR-023 — The blind A/B is waived a second time, and when the model is worth calling opens Phase 5

Status: **accepted** · Date: 2026-09-13 · Written for the Phase 4 → Phase 5 gate.
Waives, a second time, the clause ADR-018 carried into Phase 4. Depends on ADR-018 and
ADR-019; amends ADR-000 §7's Phase 5.

## Context

ADR-018 carried Phase 3's blind A/B into Phase 4: *"same design, same threshold: 8 of 12.
Blind, balanced across sections and feels, pre-registered."* It was re-run at Phase 4's
close, pre-registered in `phase-4-findings.md` §15, on 2026-09-13.

- **The model was preferred in 6 of 12 pairs,** and the criterion is not met.
- **Pooled with Phase 3's two runs after composition, it is 18 of 36:** three runs of the same
  design, converged on exact parity. Correcting for Fabiano's lean towards the second side
  heard does not move it (54%).
- **The reasons repeat ADR-018's picture.** Every pair decided on *"cleaner, less messy"*
  went to the floor, 5 of 5 across two runs. Most pairs decided on *"less boring"* went to the
  model, 4 of 5.
- **Fabiano heard where the mess is:** *"O modelo, nos testes shuffle, soa muito mais
  messy."* Four of the five "cleaner" verdicts were shuffle pairs. The notation holds a
  mechanism that fits (§16), found after the votes. Under a shuffle the model writes a
  triplet-like figure, and the system swings it a second time.
- **Every other Phase 4 criterion was met on 2026-09-13,** with evidence in the event log, by
  the regression suite and by ear.
- **What the model costs:** it wrote 12 of the 36 sections of the eight-minute conducted
  session, for $0.238. The floor plays for free and without a network.

ADR-018 wrote this outcome's meaning down before it happened: *"If Phase 4 closes and the
A/B is still at parity, the finding is about the architecture, not the prompt."*

## Decision

**Phase 4 closes with one waiver, authorised by Fabiano on 2026-09-13. The criterion is not
met, is not marked met, is not deleted, and its threshold does not move.** Closing still
waits for the gate (`/phase-gate`) to confirm every other criterion.

1. **Phase 5 opens with the question ADR-018 named: when is the model worth calling at all?**
   It comes ahead of Setlist Mode, whose offline case already assumes the answer. Its
   criteria are written when Phase 5 is planned, and agreed before anything is measured.
2. **Two leads go with it. Neither is a result.**
   - **The shuffle double swing** (`phase-4-findings.md` §16) is a concrete mechanism for
     "messy", and it is cheap to test: a pre-registered blind audition of model shuffle
     sections, as written and with the second swing taken out.
   - **"Less boring" belongs more to a song than to eight bars.** A section pair cannot hear
     it. A blind song-level pair can: the floor alone against the floor and the model
     together.
3. **Nothing about the music changes now.** The model keeps writing the grooves it has time
   for, and the floor plays the rest, as in the Stage 6 session Fabiano heard and approved.

## Rejected alternatives

**Hold Phase 4 open until the model wins.** The honest reading of the gate rule, and the
reason this is a waiver and not a pass.
- No measure of mess has passed a preference gate: `kit_collision` missed twice (§3, §5).
- Every attempt would cost a listening session, at n = 1.
- The one concrete lead is an experiment with its own pre-registered audition. Running it
  inside Phase 4 would keep a finished phase open for Phase 5's work.

**Make the floor the default now, and the model optional.** Parity says the model is not
better. It does not say the model is worth nothing: it wins on "less boring". Deciding the
routing before it is measured is what Phase 5 exists to avoid.

**Lower the threshold to parity.** This is ADR-018's refusal, and it stands for the same
reason. A criterion that moves to meet the data measures nothing.

## Consequences

**Both of the project's waivers fall on the same criterion.** Phase 4 closes with every other
criterion met with evidence and this one not, and `STATUS.md` says so.

**ADR-005's "engine as an instrument, not a fallback" now rests on 36 blind pairs.** Section
for section, the deterministic floor matches the model.

**The question ADR-000 cares about stays open, and it is first in line:** does the model earn
its latency, its money and its failure modes?

**These twelve pairs can be replayed.** The A/B log keeps the model's DSL, which Phase 3's did
not. The shuffle audition can therefore start from the exact sections that were judged.

**Not decided here: whether a section-level A/B gates Phase 5, and what it asks.** Phase 5's
plan decides that with Fabiano. Three runs have converged, and a fourth identical run would
measure the same coin.
