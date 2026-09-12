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

## 3. The gate is not met — and the run says more about the question than the ear

**6 of 10, one indistinguishable, 9 decisive. Threshold was 8. NOT MET**
(`bench/calibration.jsonl`, 2026-09-01, Fabiano).

`kit_collision` does not steer arrangement work. That is what ADR-018 asks of the gate and
the gate did its job.

### What the number does not mean, and a message that said it anyway

P(≥ 6 of 9 under a coin) = **0.25**. The result is consistent with no effect and equally
consistent with a modest one: ten trials reach a threshold of 8 only about **half the
time even when the metric is right 75% of the time**. The design was built to be hard to
pass, and it succeeded at that; it was never built to distinguish "no effect" from "an
effect this small sample cannot resolve".

`tally` originally printed *"kit_collision does not track the ear"* on any miss. That
sentence claims far more than the design can deliver, and it would have been believed —
it arrives precisely when the answer is unwelcome, which is when a too-strong conclusion
is least likely to be questioned. It is corrected, and
`test_a_missed_threshold_is_not_reported_as_a_refutation` stops it coming back.

### The one thing the run does say clearly

**"Can't tell" was available and was used once.** In nine of ten pairs Fabiano was willing
to name a side. So the pairs are not inaudibly similar — the material differs, and the
disagreement is about *which word fits it*, not about whether there is anything there.

### The design error, which is not in the ear

The test asked Fabiano to be a **measuring instrument for a label**: given two takes,
say which is *messier*. That is a different job from the one his ear is the reference
for. ADR-000's criterion is whether a section is **preferred**, and preference is a
judgement he makes unavoidably and by definition correctly — it is the target function.
Labelling is a description, and it can be unreliable in someone whose taste is not.

The word made it worse. *"Cleaner, less messy"* was **his** phrase, but he coined it about
whole sections with four instruments playing, as a *reason for preferring one*. This run
reused it for two takes of one briefing differing only in the drums. A word does not
have to survive that move, and there is no reason it should.

So: **6 of 10 is evidence about the test, not about the judge.** The honest correction is
to stop asking him to describe and go back to asking him to prefer — which is both the
thing he is uniquely qualified for and the thing ADR-000 actually specifies. A metric that
*predicts his preference* has earned its place whatever it is called; a metric that
matches his vocabulary has earned nothing.

### The possibility that has to be named

Two mechanisms have now been proposed and failed — §16's register/harmony (refuted
structurally, §1) and kit collision (unsupported at n=10). It is a live possibility that
**there is no cheap machine proxy for what makes this music good**, and that the honest
architecture is one where the human is the measurement, used sparingly, and the machine's
job is to make listening efficient — good sampling, blind, pre-registered, logged — rather
than to replace it. Phase 4's metrics criterion would then be met by a different kind of
instrument than ADR-000 §7 imagined.

## 4. The gate, re-aimed a second time: preference instead of description

Decided by Fabiano on 2026-09-01, from §3's reading. The question becomes the one ADR-000
actually specifies — **which side do you prefer** — and the metric is credited when the
take it scores *cleaner* is the one preferred. A metric that predicts preference has
earned its place whatever it is called; one that matches a vocabulary has earned nothing.

**Pre-registered, in the source, before the first note:** the cleaner take preferred in
**≥ 12 of 16**. P(≥ 12 of 16 under a coin) = 0.038.

Three limitations stated in advance, because a limitation found afterwards is an excuse:

- **Power is 0.63** if collisions cost preference 75% of the time, and 0.92 at 85%. This
  run can find a strong effect and is weak against a moderate one. The ceiling is the
  corpus, not a preference for small samples: **17 pairs remain** whose briefings the
  superseded run did not already play, and re-using the others would be asking about music
  he has already judged on another axis.
- **The sample is 12 chorus, 2 verse, 2 bridge**, and that is by construction: busier
  sections have more slots to collide in, so the widest gaps live there. Both sides of a
  pair are the same briefing, so this bounds what the answer covers — busy sections first —
  rather than confounding the comparison.
- **§3's 6 of 10 is not this run's baseline.** It asked a different question, and treating
  it as a prior for this one would be reading a label test as a preference test.

The reason menu is copied from `ab_section.py` unchanged. Two vocabularies would make the
two runs impossible to compare, and grouping losses by reason is the only thing that has
ever produced a mechanism in this project (§16).

    uv run python scripts/calibrate_metrics.py --dry-run   # the selection, no Live
    uv run python scripts/calibrate_metrics.py             # Live open, ~30 minutes

**If this one also misses, that is two failed hypotheses and a failed reformulation**, and
the honest conclusion moves from "we have not found the metric yet" to "there may be no
cheap proxy, and the architecture should say so" (§3's closing note).

## 5. The gate is missed a second time, and the sign is inverted

**5 of 16, one with no preference, 15 decisive. Threshold was 12. NOT MET**
(`bench/calibration-preference.jsonl`, 2026-09-04 and 2026-09-08, Fabiano).

`kit_collision` does not steer arrangement work. That is what ADR-018 asks of the gate,
and the gate has now answered twice.

### The result is not a near miss — it is a reversal

The take the metric scores *messier* was preferred in **10 of 15 decisive pairs**.

This matters more than the miss. P(>= 5 of 15 under a coin) = 0.94, which is the correct
number for *"did the run clear the bar"* and a misleading one for *"what happened"*: read
alone it looks like a coin and buries the reversal. The tail that describes the result is
P(<= 5 of 15) = **0.15**. Neither is significant at n = 15. But "we could not detect the
effect" and "the effect, if there is one, points the other way" are different statements,
and only the second is consistent with what was measured.

### The reporting defect, which is §3's with its sign flipped

`tally` printed only the upper tail, and its power sentence read *"ten trials would reach
the threshold only about half the time"* — a hard-coded description of the superseded
10-pair round, still standing after the design moved to 16 pairs with a pre-registered
power of 0.63.

§3 corrected this function for claiming **more** than the design can deliver. Here it
claimed **less**, and it did so precisely when the result was most interesting — which is
the same failure mode, because in both cases the sentence that survives is the one nobody
is motivated to question. The figure is now derived from `PAIRS` and `THRESHOLD` rather
than written out (`_power`), both tails are printed when the estimate is below chance, and
three tests hold it there. A fourth, `--tally`, exists because this run could not be read
back at all: `tally` was reachable only at the end of a listening session, so a finished
log had to be opened by hand to find out what it said.

### Why, in his words

The analysis §4 pre-registered, because grouping by reason is the only thing in this
project that has ever produced a mechanism (§16). Of the 15 decisive pairs:

| reason | the cleaner take won | the messier take won |
|---|---|---|
| more energy | 1 | 3 |
| less boring | 1 | 3 |
| just sounds nicer | 1 | 2 |
| better to move to | 1 | 1 |
| **cleaner, less messy** | **1** | **1** |

**Six of the eight pairs decided on energy or interest went to the collision-heavy take.**
And the bottom row is the one that undoes the hypothesis from the inside: *"cleaner, less
messy"* is the phrase the whole metric was built from, and it splits 1–1 — in one of those
two pairs Fabiano called the take the number scores as messy the *cleaner* of the two.

There is a musical reading, and it is ordinary. Kick and snare on the same sixteenth is not
two drums fighting for a slot; it is the kick reinforcing the backbeat, which is a standard
rock move and lands as weight rather than as mess. §1 counted those hits and called them
mess by definition. Nobody had checked that definition against an ear until now.

### What this does not say

- **2 to 4 votes per reason is anecdote.** The table is a hypothesis with a mechanism
  attached, exactly as `kit_collision` itself was after §1, and that one did not survive.
- **The inverted sign is not acted on here, deliberately.** Flipping the metric and using
  it would be reading a mechanism off a finished run, which is how §13's chorus split and
  §16's register hypothesis both died. If it is to be tested it needs its own
  pre-registration, written before the material exists.
- **n = 1 judge**, unchanged and unfixable at this scale (ADR-018 rejected recruiting
  listeners as a fix for this gate).

### The corpus is spent

23 briefings have now been heard across the two runs, and **exactly one new pair** remains
constructible from the 107 recorded sections. The offline corpus paid for in Phase 3 is
exhausted: any further calibration needs freshly generated material, which costs API spend
and a session. That is a planning constraint, not an aside — it is the reason the inverted
sign should be tested on sections Stage 2 generates anyway rather than on a round bought
for the purpose.

### The consequence was pre-registered

§4, before the first note of this run:

> **If this one also misses, that is two failed hypotheses and a failed reformulation**,
> and the honest conclusion moves from "we have not found the metric yet" to "there may be
> no cheap proxy, and the architecture should say so".

Three mechanisms have now been proposed and none survived: `register_spread` and
`harmonic_conformance`, refuted structurally because the DSL forbids the model to produce
what they measure (§1); `kit_collision` as a label for mess, unsupported at n = 10 and
mis-aimed by design (§3); and `kit_collision` as a predictor of preference, which this run
leaves pointing backwards.

What follows from that is an architecture question rather than a measurement one, and it is
drafted in `ADR-019-the-ear-is-the-instrument.md` for Fabiano to accept, amend or reject.
It was written as a proposal, with nothing in this document depending on its outcome, and
**Fabiano accepted it as drafted on 2026-09-12**.

## 6. Stage 2 is built: the song hands over from section to section, and the ear approves

ADR-019 took the metric out of Stage 2's way. What replaced it is built and tested, and the
decision about where it lives is ADR-020. **This section records what exists and what the
ear is being asked, before the listening, so the listening can disagree with it.**

### What the band now does, in sound

- **Into a chorus from a verse, a build.** Over the last two bars the snare rolls —
  quarters, eighths, then sixteenths — with the hi-hat gone and the kick still on the
  groove. The whole band drops a little and swells, and on the very last beat everyone but
  the drummer lets go, so the roll is alone for a beat before the crash.
- **Into a chorus from a bridge, and into the last chorus from anything, a stop.** The band
  hits the downbeat of the last bar with a crash and cuts. A beat and a half of the chord
  rings, then silence, then the drummer picks up on the last beat into the chorus.
- **The last chorus is the biggest.** One step up the groove table and a harder fill.
- **The song ends on a chord.** Before, the outro ended on a fill leading into nothing and
  the transport stopped. Now the last bar is one hit, kick and crash, and the chord rings
  to the end.
- **Everywhere else, the fill the band already played.**

For the default song (`jam.py --seed 7`): intro fill, then build, stop (after the bridge),
build, build, build, **stop into the last chorus**, and the final chord.

### What is measured

- `play_section` and `realise` are unchanged: **all eight golden files are byte-identical**.
  Three new golden files pin the build, the stop and the final chord over one briefing.
- For any briefing, seed, ending and following section, **the composed section validates
  with no violations** — held at 2000 examples before being committed at the suite's 60 —
  keeps all four instruments, invents no pitch, and rings nothing into the next clip.
- **All three recorded model responses compose validly under every ending**, so a model's
  groove gets the same form the floor does.
- A three-minute arranged run against the fake Live fires every section with a bar of
  slack, loses no beat, declines no ending, and is byte-identical for a seed.
- Composing and validating one eight-bar section costs **under 1 ms**.

Suite: **1734 passed, 25 live-marked skipped**; `ruff` and `mypy` clean.

### What the ear is asked, written before it is asked

The reference is `--plain`, which is the song every earlier listening heard.

1. **Does the song go somewhere now?** The whole three minutes, arranged against plain.
   This is the Stage 2 gate as ADR-019 describes it. No threshold, because n = 1 and one
   comparison cannot carry one; the answer is recorded verbatim, as Phase 2's was.
2. **Which of the three moves work, and which do not?** Build, stop, final chord — each can
   be kept, changed or removed independently, because each is a row in a table.

Named in advance so they are not discovered afterwards as excuses:

- **Drift's velocity response is unknown.** Every instrument is Drift. If it barely answers
  velocity, the swell is inaudible and the build is carried by the roll alone.
- **Five identical builds in three minutes may be the problem**, rather than the build.
  ADR-020 rejected seeded variety on purpose; this is the evidence that would reverse it.
- **The drums are a synthesiser.** A "snare roll" is one Drift note repeated, and may not
  read as a roll at all.

### The listening

**Fabiano listened on 2026-09-12** and said: *"Gostei muito do resultado."* — I liked the
result a lot.

What he heard is in `bench/jam.jsonl`, appended by the run itself: **the arranged song
twice**, 14 sections each, every ending exactly as planned — `build` four times, `stop`
twice, `final` once — and **the plain song for four sections** in between, stopped early.
Against the real Set: **zero endings declined**, every one of the 31 fires with at least a
bar of slack, and the slowest section write 2039 ms, against Phase 2's 1939 ms maximum —
within the same band, and the write happens at the start of a section, not near its
boundary.

That answers question 1 in the affirmative, as a verdict on the whole, in the same form
Phase 2's floor was approved in. It does not answer question 2: no move was named as
working or failing, so the three risks above are neither confirmed nor retired — they are
simply not what was heard as a problem. n = 1, unblinded, and he knew which version he was
listening to, which is what ADR-019 accepted as the cost of judging arrangement by ear.
Every section played from the floor (`not_in_buffer`, no `--generate`), so this approves
the endings over the deterministic band; over a model's groove they are validated, not
yet heard.

### What this does not touch

No model material was generated. ADR-019's condition on the inverted `kit_collision` sign —
a pre-registration written before Stage 2 generates any — is unaffected, and still has to
be written before the first `jam.py --generate` of this stage if that question is going to
be asked.

## 7. Stage 0 of the MiniLab plan: what Live actually does when a cue fires

The tactical layer's design rests on one rule — **a cue may cost a fire, never a write**,
because a section write costs about a bar (§3 of Phase 2; 2039 ms at worst on 2026-09-12).
Everything a pad can trigger is therefore written ahead and launched by Live. Whether that
can work was, until this run, read from the manual and from AbletonOSC's source.
`scripts/spike_cues.py` asked the real Set on 2026-09-12 (Live 12 Lite, 132 BPM, `1 Bar`),
and put it back: 8 scenes, transport stopped, no clip left behind. Raw answers in
`bench/spike-cues.json`.

### The Live half

| Question | Answer | Evidence |
|---|---|---|
| Does `/live/clip/fire` wait for the next bar? | **Yes** | fired at beat 1.56, launched at 3.78 against a bar line at 4.0 |
| Does legato carry position on a clip fire? | **Yes** | the new clip picked up at 13.57, where the old one was |
| …and on a scene fire? | **Yes** | 17.55, continuing |
| Does legato set immediately before a fire apply to it? | **Yes** | both sends took 0.18 ms together |
| Two triggers in one track before the same bar? | **The second wins** | the track played the later clip |
| Does `/live/track/stop_all_clips` wait for the bar? | **Yes** | sent at 29.69, stopped at 32.33 against 32.0 |
| How many scenes does this Live allow? | **16** | appending stopped at 16 from 8 |
| What does a call cost? | **send ~0.01 ms; request ~100 ms** | median of 20 each |

**The 0.22-beat offsets are the measurement, not Live.** Every launch and stop above reads
about a fifth of a beat early or late, and that is exactly one request: a read costs
~100 ms, which is 0.22 beats at 132 BPM, and the song time and the clip position are two
reads in a row. The launches themselves are on the bar.

### What it decides

- **The "next bar" promise holds for every cue in the plan.** Jump cues fire a pre-written
  scene; bar cues fire legato variants; DRUMS+BASS stops two tracks — all quantised by Live,
  none needing a write at cue time.
- **The scene budget is 16, not 8.** The plan's cramped branch is not taken: A/B, a chorus
  and a bridge candidate, and a variant pair each for STOP and FILL fit with room to spare.
- **Legato must be off on the main clips.** A scene fire honours legato, so a jump into a
  candidate — or the scheduler's own section change — would otherwise start the new section
  mid-way. Variants carry legato; the return to a main clip sets it on just before the fire
  and off again after, which the fourth row shows Live accepts.
- **The last trigger wins, so precedence is the scheduler's to decide.** A cue pressed in
  the bar after the scheduler fired the next section silently replaces that fire, and the
  reverse. It has to be an explicit rule with a test, not whichever send happened last.
- **A cue must never wait on a read.** A request is a fifth of a beat; a send is nothing.
  Fires stay unconfirmed, as ADR-001 already has them.

### The MiniLab half

Fabiano touched every control for 120 s on 2026-09-12 with `scripts/probe_minilab.py`
listening on all four MiniLab ports and Live open.

**Everything arrived on `Minilab3 MIDI`, and nothing on `DIN THRU`, `MCU/HUI` or `ALV`.**

| Control | What it sends |
|---|---|
| 8 pads | `note_on`, channel 10, notes **36–43**, with velocity — and polytouch pressure while held |
| 8 knobs | CC on channel 1, in the order touched **74, 71, 76, 77, 93, 18, 19, 16**; absolute 0–127 |
| 4 faders | CC on channel 1, **82, 83, 85, 17**; absolute 0–127 |
| keys | `note_on`, channel 1; 36–81 heard across the octave buttons |
| two buttons | CC **9** and CC **105**, 127 then 0 — press and release; which buttons, not confirmed |
| touch strips, main encoder | nothing heard |

The pad rows of that run's summary counted pressure together with strikes, which is why
one pad read as three hundred presses; the probe now keeps polytouch on a row of its own.

**Live launched nothing.** Read straight after the run: transport stopped, no slot fired
and none playing on any track. In this mode the pads reach Python and the `MiniLab_3`
control-surface script does not turn them into clip launches.

**But the KEYS track is armed**, with monitoring on Auto. While it is, every note the
MiniLab sends — pads included — plays KEYS' Drift. A pad pressed as a cue would sound a
note inside the band.

### What the MiniLab half decides

- **Python listens to `Minilab3 MIDI` alone.**
- **A cue is a strike:** `note_on` with velocity above zero on channel 10. Releases and
  pressure are ignored, or a held pad would cue again every few milliseconds.
- **Knobs and faders are absolute.** A value maps straight to a macro with nothing to
  accumulate. The knob's physical position is unknown until it moves, so a macro starts
  from the briefing's value and jumps to the knob's the first time it is turned — named
  here so the listening can say whether that jump is audible.
- **The band's tracks are disarmed while it plays**, declared in `session.toml` and checked
  by the bootstrap. `arm` is writable over AbletonOSC, so `--apply` can fix it; nothing
  else stops a cue from being heard as a note.
- **The Stage 0 gate is met:** every control touched was named by the probe.

Still open, and only Fabiano can answer it: whether anything in Live visibly reacted, or
was heard, when the pads were pressed.
