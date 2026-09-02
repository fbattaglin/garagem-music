# ADR-017 — The model writes the groove; the engines write the form

Status: **accepted** · Date: 2026-09-01 · Written for Phase 3. Supersedes part of
ADR-000 §7's Phase 4. Depends on ADR-005 and ADR-011; serves invariants P2 and P4.

## Context

ADR-000 §7 asks Phase 4 for *"complete per-section arrangement (4+ instruments in one
call), with a dynamics curve and transitions between sections"*. Phase 3 measured what
happens when you ask a model for that, and the answer is not a matter of degree.

**The arranged form does not fit the deadline. Thirty attempts, thirty cancellations**
(`phase-3-findings.md` §14). Deadlines from 3.49 s to 8.00 s, TTFT normal at a median of
1.64 s — the stream starts on time and never finishes. Asking for one bar-level line per
bar multiplies the output past what 40% of the musical time can carry, and §4.2's deadline
is a cancellation rather than a timeout noticed afterwards.

**Asked for one line, the model writes one line, and one density.** Under the static
prompt it wrote a single bar-level line per instrument in every one of 85 sections, and a
median of 14 drum attacks per bar at `dyn=2`, `dyn=3` and `dyn=4` alike (§13). So a
realised section was the same bar eight times, and a chorus was a verse played louder.

**And the deterministic engines already do all of it.** `engines/drums.py` opens bar 1
with a crash and closes the last with `fill_for(tension)`; `groove_for(feel, dyn, bpm)`
selects the subdivision. That music was approved by ear in Phase 2 — *"está total
aceitável, na verdade está super agradável"* — which makes it the only calibrated
reference the project owns.

The cost of not resolving this was measurable. The first blind A/B put a static loop
against eight arranged bars and the floor won **9 of 11**. That number was never about
grooves: it was about form, and the test could not tell the two apart.

## Decision

**Two sources, one score. The model contributes the groove; the arrangement is composed
over it deterministically.**

In `dsl/realise.py`, and nowhere else:

- **The crash belongs to the arrangement.** Bar 1, beat 1, whatever the model sent. A
  single bar-level line applies to every bar (`_for_bar`), so a model that *did* write
  `C:x...............` would have put a cymbal on all eight.
- **The last bar is `fill_for(section.tension)`** on the snare, with the hat silent and
  the model's kick playing through — exactly what `engines/drums.py` does.
- **The hat carries the subdivision the engine would play for this briefing**, and never
  more. Not "double it when `dyn >= 4`": that is true of straight8 and false of every
  other feel, because shuffle stays at eighths even at `dyn=5` and sixteenths on a swung
  hat are not a louder shuffle. The threshold is read from `groove_for`, which already
  knows it.
- **Everything else is the model's.** Kick, snare, bass, guitar, keys: untouched.

**The engines' own output is a fixed point.** Serialise a section from
`engines.band.play_section`, parse it back and realise it, and the drum attacks are
identical — in all four feels, at every dynamic. That is not a pleasant coincidence, it is
the property that says the composition agrees with the music a human signed off on, and it
is asserted twice: directly, and continuously through
`tests/property/test_dsl_round_trip.py`.

## Rejected alternatives

**Ask the model for the arrangement.** Measured, 30 of 30 over the deadline (§14). Not a
prompting problem with a prompting fix — the output simply does not arrive in time.

**Ask the model for the density.** Measured, and it *works*: stating what `dyn` means
moved the chorus from 14 attacks to 18. It costs **24 points of first-pass conformance**
(77% → 53%), almost all of it grids miscounted by one character, because a busier grid is
a longer thing to count. It also lifts every feel indistinguishably, including the ones
the engine deliberately leaves alone. Composition costs nothing and is feel-correct.

**A DSL field for the arrangement** — `fill=last`, `crash=1`, an `arc=` on the SEC line.
One field instead of eight lines, and cheap. Rejected *for now*: it adds schema surface to
a schema the model was at 77% on, and the two defects it still makes are vocabulary and
counting. It becomes the right move in Phase 4, as a modifier over an arrangement that
already exists rather than as the thing that creates one.

**Merge the realiser into the engines.** The overlap is real and the duplication is
deliberate (`dsl/realise.py`'s own docstring). A shared constant is a shared constant: a
value changed here for a model's output would silently move music a human approved. Two
callers, one library — `theory/` and `engines/groove.py` are imported, not absorbed.

**Defer it to Phase 4.** Leaves the blind A/B measuring form instead of grooves, which
means the phase's central criterion stays untested rather than unmet.

## Consequences

**The A/B became a one-variable test, and the number moved 40 points** — 18% to 58%
(§13). 58% is parity rather than superiority (P(≥7 of 12 | a coin) = 0.39) and the
criterion asks for 8 of 12, so this is not a pass. It is the difference between losing and
not knowing.

**Phase 4's arrangement work is composition work.** ADR-000 §7's dynamics curve, breaks
and builds are extensions of `_arranged()` and of the engines, gated on the coherence
metrics, not new things to ask a model for. The plan of 2026-09-01 rewrites that phase on
this basis.

**P4 is served, not eroded.** "Never trust model output" is not the same as "ask for
everything and check it afterwards". A variation the model demonstrably will not write is
a decision taken back, not one repeatedly requested and repeatedly validated.

**The engines acquire a second caller, and a duty.** `groove_for` and `fill_for` are now
load-bearing for model output as well as for the floor. Changing either moves both, and
the round-trip property test is what will say so.

**A live failure mode is closed.** A model crash repeated across every bar was possible
and unobserved — 0 of 85 sections carried one, so nothing had ever triggered it.

**What this does not fix.** The model still writes one bar-level line, so a section's
*groove* does not vary bar to bar; only its form does. Whether that matters is a question
for the ear, and the blind A/B is where it gets asked.
