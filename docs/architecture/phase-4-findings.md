# Phase 4 findings

## 1. §16's mechanism is refuted: the model cannot make the mess it was blamed for

Stage 1 of the phase plan exists to prove the coherence metrics track what Fabiano hears
before they are allowed to steer any arrangement work. They do not, and the reason is
structural rather than a matter of tuning.

`phase-3-findings.md` §16 named the mechanism behind *"cleaner, less messy"*: **notes
colliding, instruments piled into one octave, pitches outside the chart.** Two of those
three became `register_spread` and `harmonic_conformance`, which is what ADR-000 §7 asks
Phase 4 for and what ADR-018 made a gate. Both are now implemented
(`theory/coherence.py`), tested, and measured over every section this project has
recorded.

### The measurement

112 model sections across all four Phase 3 rounds — `sections-static`, `-fixed`, `-dense`,
`-positions` — each realised offline from its recorded DSL and scored against the floor
generated from the same briefing. **No network, no cost.** The briefings reconstruct
exactly: `bench_sections.briefings(30, 7)` is deterministic and matched all 29 rows of the
positions log on `(name, bars, bpm)`.

| | model (n=112) | floor (n=29) |
|---|---|---|
| `harmonic_conformance` | 0.998 (min 0.98) | 0.996 (min 0.98) |
| `register_spread` | **1.000 (min 1.000)** | **1.000 (min 1.000)** |
| `bass_kick_alignment` | 0.923 | 0.774 |
| `density_against_tension` | 0.920 (min 0.62) | 0.948 (min 0.91) |
| **`messiness`** | **0.0014** | **0.0022** |

**`register_spread` is 1.000 for all 112 model sections and all 29 floor sections.** It is
not a weak signal, it is a constant. And by the composite those two metrics make, the
model is *cleaner* than the floor — both indistinguishable from zero.

### Why, and why this was never going to work

**The DSL does not let the model name a pitch.** `BAS` carries `deg=` and `oct=`; `GTR`
and `KEY` carry `voi=` and `reg=low|mid|high`. `dsl/realise.py` turns those into notes
through `degree_to_pitch`, `voice_lead` and `fit_to_range`, against `RANGES`. A pitch
outside the chart and a band piled into one octave are **things the architecture forbids
the model to produce**, and they were forbidden before §16 was written.

So the two mechanisms §16 blamed cannot be what was heard in those three pairs. The
hypothesis was formed from a post-hoc reading of three votes, and it does not survive
contact with the corpus — which is the same lesson §16 itself recorded about the chorus
split, one hypothesis earlier.

`register_spread` has a second, independent defect worth naming: measured as centroid
spread against the spread of `RANGES` midpoints (18.5 semitones), real sections land at
19–35 semitones and the metric saturates. Even in an architecture that permitted piling,
this scaling would have to be rebuilt. It is left as written rather than tuned, because
tuning a metric that measures the wrong thing is the more expensive mistake.

### What does separate the model from the floor

The same corpus, asking where the model's material is genuinely its own. Drums are the
only such place: the model writes its own kick, snare and hat grids, while everything
pitched is reconstructed by the realiser.

| | model (n=105) | floor (n=29) |
|---|---|---|
| **kick/snare on the same slot** | **0.172 (max 0.47)** | **0.060 (max 0.25)** |
| backbeat coverage | 0.904 (min 0.06) | 0.789 (min 0.06) |

**The model stacks kick and snare on the same sixteenth nearly three times as often as
the curated grooves do.** Two drums fighting for one slot is mess in the ordinary sense of
the word, it is audible, and it is the one measured difference pointing the same way as
the three votes.

Backbeat coverage points the other way — the model is *more* conventional than the floor —
so it is not the signal, and it is recorded here so that it cannot be quietly rediscovered
later as one.

### What this does not say

- **It is a corpus difference, not a heard one.** Nobody has listened to a section chosen
  by this number. The Stage 1 gate is not passed by finding a signal; it is passed by a
  blind listen agreeing with it, and that has not happened.
- **n = 105 sections, but one judge and zero verdicts.** The 12 judged pairs cannot be
  scored: their model-side material was never persisted (`ab_section.py` now fixes that,
  Stage 0.4), so this corpus has no human labels in it at all.
- **The three "cleaner" votes remain unexplained.** Kick/snare collision is a candidate
  with a mechanism and a measurement, and nothing more than that.

### The cost of finding out

$0 and no listening session. That is the whole argument for the gate being where it is:
had the metrics been trusted and Stage 2's arrangement work tuned against `messiness`, the
phase would have spent weeks optimising a number that is a constant on real material.

## 2. The gate, re-aimed: what `scripts/calibrate_metrics.py` asks and why

ADR-018's debt #1 asked the metrics to separate the three "cleaner, less messy" losses in
`bench/ab-phase3-final.jsonl` from the other nine. §1 shows why that is not executable —
the model side of those twelve pairs was never persisted — and refutes the mechanism it
was built on. The gate is re-aimed rather than dropped, and the design is worth recording
because two of its choices were made against defects this project has already paid for.

**It asks *messier*, not *better*.** Preference is the A/B's question and it closes the
phase. This one asks only whether `kit_collision` is about anything a person can hear. A
metric can be perfectly correlated with mess and still not predict preference, and
conflating the two is how §13's chorus mechanism survived a whole round before
pre-registration killed it.

**Both sides of a pair are the same briefing.** The four Phase 3 rounds asked for the same
sample four times and got four different answers, so a pair holds chart, key, tempo, feel
and length fixed and varies only the drum pattern the model wrote. Pairing the global
extremes was the first design and it would have repeated §10 exactly: a listener asked to
compare a shuffle bridge in one key against a straight16 verse in another is not judging
mess, and would be right not to.

**Ten pairs, threshold 8, fixed in the source before the first note.** P(≥ 8 of 10) under
a coin is 0.055 — the same order as the A/B's 8 of 12. A gate easier to pass than the test
it protects is not a gate.

**Free.** 107 sections realised offline from DSL recorded and paid for in Phase 3. No
network, no key, no cost; Live is open only because the question is about sound.

### Two defects the corpus surfaced on the way

**`bench_sections.briefings` applied `worth_asking` inside the draw.** Raising
`MIN_DEADLINE_S` from 1.5 to 5.0 (§15) therefore did not merely change what gets asked —
it silently changed what the *older logs could be aligned against*, because the four-bar
intros they were recorded for are no longer in the list. `draw()` is now split from the
filter. Without that split, half the corpus would have been unreadable and nothing would
have said so.

**Alignment walks the draw per row, not by position.** The two eras skip differently, and
a mispaired briefing would score a section against the wrong chart — a wrong number that
looks exactly like a right one. The walk fails loudly when it cannot find a row rather
than guessing.

### What has to happen next, and by whom

    uv run python scripts/calibrate_metrics.py --dry-run   # the selection, no Live
    uv run python scripts/calibrate_metrics.py             # Live open, ~20 minutes

**Stage 2 does not begin until this runs.** If the metric is heard in fewer than 8 of 10,
it does not steer arrangement work, and the honest position is that Phase 4 has no
validated measure of mess — which would be the second refuted mechanism in two phases and
a finding in its own right.
