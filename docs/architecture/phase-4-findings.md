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

## 8. Stage 2's gate, run twice: the song never left bar 5, and the first diagnosis was wrong

### First run

Fabiano ran `bootstrap_set.py --apply`, which disarmed KEYS, then
`jam.py --controller minilab --seconds 90` on 2026-09-12, touching **every control on the
MiniLab** — not only the mapped ones.

- **The controller path worked end to end.** Ten controls reached the event log, each
  stamped with the bar it arrived in. Seven of the eight mapped kinds arrived;
  **`fill` (pad 2, note 37) did not**.
- **The song ended ten seconds in, and the run said nothing.** The intro played and the
  verse fired at beat 20. Then no bar 6 ever came. Two later cues were stamped at beats 11
  and 14, *after* ones stamped 23. The scheduler waited `BAR_TIMEOUT_S`, 30 s, gave up — and
  `jam.py` exited 0, the code that means *the form was played to the end*.

Live's log also showed `MiniLab_3` in Control Surface slot 1, listening to
`Minilab3 (MIDI)` — the same port as the band. **The first diagnosis blamed it:** a MiniLab
button, through Live's surface, stopping and restarting the transport. That was written into
this section and into commit 9ef4716, and it was wrong.

### Second run, with Live's surface disconnected

`MiniLab_3`'s Input and Output were set to None, the new preflight confirmed the cue port was
free, and the jam ran again.

- **All eight mapped controls arrived**, `fill` included. The mapping holds with Live's
  surface out of the way.
- **The song stopped at bar 5 again**, exactly where it had before, with nothing of Live's
  listening to the MiniLab. The cue stamps told the real story: 9, 11, 16, 20, then 11,
  16, 8. The beats never stopped. The song position kept going **back**.

Asked directly, Live answered: **`loop` = True, `loop_start` = 8.0, `loop_length` = 16.0.**
The arrangement loop was on, over beats 8 to 24. Clip launching ignores it, so the intro and
the verse sounded. But the `BarClock` counts bars from the song position, which went back to
beat 8 every time it reached 24. It could never see bar 6, the one the scheduler was waiting
for. Both runs are that. When the loop was switched on is not known: it was off for every
earlier listening, and Stage 0's probe, when every MiniLab button was pressed with Live's
surface still attached, is the likeliest moment — likely, not shown.

### What changed

- **The loop switch is part of the Set's contract.** `session.toml` declares `loop = false`;
  the bootstrap reads `/live/song/get/loop`, reports it, and `--apply` turns it off.
  `jam.py` already refuses a Set that does not match, so a loop left on is now caught before
  the downbeat.
- **A run that ends early says why.** `Scheduler.run` logs `beat_lost` with
  `reason=transport_stopped` when the beats stopped, and `position_went_back` when they kept
  coming but the position jumped back before the awaited bar. `jam.py` exits 1 and names the
  bar and the likely cause for each.
- **`--controller` still refuses to start while a Live control surface listens to the cue
  port.** It is no longer credited with stopping the song. But the surface does hear every
  pad and button, can act on them, and is the likeliest way the loop got switched on.
  Keeping it off the port costs one setting.

The error at 16:22:27 in Live's log is neither cause. It is AbletonOSC's `clip_slot` handler
calling `logger.info` with the wrong arguments, a logging error on every slot query that
predates today.

### What the mistake teaches

The first diagnosis fitted the evidence available — beats that went quiet and a surface
that can move the transport — and it was committed before a second run could disagree. The
tell was in the first log all along: cue stamps going *backwards* is a moving position, not a
stopped one. A stopped transport stamps every later cue with the same beat. The scheduler now
tells the two apart itself, so the next reading does not depend on noticing it.

### Third and fourth runs: the gate passes

With the loop off and Live's surface off the cue port, the third run played the whole
song — eight sections, every fire with a bar of slack, every ending as planned, eight
`section_measured`, exit 0 — and heard no control, because the jam was started while
nobody was at the MiniLab. Fabiano started the fourth himself, hands on the controller.

**Fourth run, 2026-09-12: passed.**

- **The whole song**: intro to outro, eight fires, minimum slack one bar, no `beat_lost`,
  writes at most 1995 ms, endings `fill build fill stop fill stop fill final`.
- **63 controls, all eight mapped kinds**: `stop` ×9, `fill` ×11, `drums_and_bass` ×7,
  `chorus_now` ×5, `next_bridge` ×3, `end` ×8, `density` ×12, `tension` ×8 — from bar 0 to
  bar 57 of a 58-bar song, with pad stamps that never go backwards.

### What it says about Stage 3

**A cue is read a bar after it arrives: 62 of 63 were drained one bar later, and one two
bars later.** That is Stage 2 working as built — the scheduler drains once per bar, at the
tick — and it is exactly the latency Stage 3 cannot keep. A jump cue drained a bar late
can only fire for the bar after, so `fired_bar − cue_bar` would read 2, not 1. The one
drained two bars late arrived while a section write held the tick for up to two seconds.
ADR-022 already plans for both: `run` wakes in short slices rather than once per bar, and a
write checks for cues between tracks. Stage 3 has to show them working, measured the same
way.

## 9. Stage 3 is built: "chorus now" lands on the next bar, and the song re-plans behind it

ADR-022's jump, end to end, offline. **The gate — Fabiano conducting the band to the chorus
from pad 5, judged by ear — has not run.**

### What happens when the pad is struck

1. **Before the downbeat**, the scheduler writes the song's own first chorus, at its ordinary
   size, into the `CHORUS` scene (scene 2) — `candidate_written` in the log. A write costs
   nothing musical there.
2. **Inside the bar the cue arrives in**, the scheduler reads it. `run` waits for the next bar
   in 20 ms slices and reads the queue between them, and a section write reads it between
   tracks. Stage 2 read every cue a bar late (§8); this is what removes that.
3. **One send fires scene 2.** Live launches it on the next bar, from its first bar, crash
   included. If the scheduler had already fired the next section in that bar, Live's last
   trigger wins, and it is the person's.
4. **Then the bookkeeping, while Live counts down.**
   - The form after the jump is re-planned, `engines.jump_plan`: what played stays, the chorus
     comes next, and a new tail walks the transition table for about as long as the old one
     would have lasted, then the outro.
   - The climax moves to the tail's last chorus, never onto the candidate, which was written
     before it could be lifted.
   - Endings are recomputed.
   - The buffer drops everything generated past the jump.
   - The shared `FormPlan` is replaced.
   - The log gets `cue_applied` (with `cue_bar` and `fired_bar`) and `form_replanned`.
5. **While the chorus plays**, the section after it is written into a main scene — both are
   silent — and the producer, reading the same plan, asks the model for it.

### What is measured, offline

- A cue in bar 3 is fired for bar 4: `fired_bar − cue_bar = 1`. That holds when it arrives
  mid-bar with `run` driving a real `BarClock` on a thread, and when it arrives in the
  middle of a section write: the fire goes out between two tracks.
- No write lands in the scene that is playing across two jumps. After the downbeat, no
  write touches the candidate's scene at all.
- A jump in the bar the next section was fired replaces it; a second jump while the chorus
  plays starts it again; a jump before the first beat, or with no candidate, is declined and
  logged.
- **The model is asked for the section after the chorus with the re-planned briefing**, and
  a score generated for a briefing the jump replaced is refused twice. The producer refuses
  it before offering (`fallback reason=stale`), and the scheduler refuses it again on the way
  out of the buffer. Across a jump every section that plays is the plan's own.
- Seed plus cue log replays the performance byte for byte. Every section that plays is
  measured, the jumped-to chorus included.

Suite: **1895 passed, 27 live-marked skipped**; `ruff`, `mypy` and the timing properties
clean.

### What the ear is asked, written before it is asked

**Does the band follow you to the chorus?** Strike pad 5 anywhere in a song, several times,
and say whether the chorus arrives when you expect it and whether the song goes somewhere
sensible afterwards.

Named in advance:

- **The chorus always arrives on the next downbeat, however far into a bar the pad was
  struck.** Struck late in a bar, that is almost immediate. Struck early, it is nearly two
  seconds. `quantum_bars` exists to try "the next phrase" by ear if the downbeat feels wrong.
- **A jump cuts the section it interrupts wherever it is.** Its fill, build or stop is not
  heard, because the chorus replaces its last bars. A band cued mid-verse does the same, but
  whether it feels abrupt is the ear's to say.
- **The jumped-to chorus is always the deterministic one**, never the model's (ADR-022).

### The gate: passed, 2026-09-12

Fabiano ran `jam.py --controller minilab --seconds 120` and struck pad 5 ten times: mid-verse,
mid-bridge, during the chorus itself, and twice in the bar the scheduler had already fired
the next section.

- **All ten jumps landed one bar after the pad**, `fired_bar − cue_bar = 1` ×10, read from
  the log.
- **Both same-bar jumps replaced the scheduled section**, as ADR-022 says they should.
- **No write landed in a sounding scene.** Each of the 18 writes was checked against the
  scene the log's fires and jumps put on the speakers at that beat.
- The song played to its end with no `beat_lost`; the slowest write took 2033 ms.

Asked the three questions written down above, he answered:

1. Did the chorus arrive when expected? — *"Dentro do esperado."* Within what was expected.
2. Did the song go somewhere sensible afterwards? — *"Tudo correu bem."* It all went well.
3. Did the cut sound natural or abrupt? — *"Perceptível, mais natural."* Noticeable, but
   rather natural.

The first two are a pass. The third names the cost ADR-022 predicted — a jump cuts the
interrupted section's last bars, fill and all — and says it lands on the natural side.

### A defect the gate found: jumps lengthened the song

**The song asked for 102 seconds and played 216.** `jump_plan` was meant to reshape, not
lengthen, and did neither exactly, for two reasons:

- **Two outros.** The tail's budget still counted the outro it replaced, and then the tail
  added a new one.
- **Overshoot.** The walk ran until it *passed* its budget, like `arrange`, which must reach
  a minimum. A jump should aim at a length instead.

Each jump added about eleven seconds. Fixed:

- The tail counts its own outro.
- A section is added only if it brings the tail closer to its budget than stopping would.
- The bars a jump cuts from the interrupted section give their time back.

Replaying this gate's cue beats offline now gives **133 s against the planned 102**. Only
seven of the ten cues land before that shorter song ends, and all seven still land after
one bar. The remainder is section granularity: a tail can only be built from 8-bar
sections, so each jump can miss its budget by up to half of one. A test holds ten jumps to
within one section of the planned length.

## 10. Stage 4 is built: stop, fill, and the band down to drums and bass, from the next bar

The rest of ADR-022's next-bar cues, end to end, offline. **The gate — Fabiano striking pads
1, 2 and 3 during a song, judged by ear — has not run.**

### What happens when each pad is struck

**Behind the music, one track per bar**, the scheduler writes two variants of the section
that is playing and of the one after it. They go into the scenes paired with that section's
main scene: stop into 4 or 5, fill into 6 or 7.
- `stop_bars` turns every bar into a stop: the downbeat, the chord ringing a beat and a half,
  kick and crash, a snare pickup on beat four.
- `fill_bars` turns every bar into a fill: the kick keeps its groove, the snare fills at least
  as hard as a chorus's, the hats drop out.
- Both come from the section exactly as it was written, ending included, so a stopped bar
  carries that bar's chord.
- The fill's drums are written first. Every variant clip has legato on.
- No variant is written in a bar that already wrote a section, or into a scene a cue is
  sounding from.

**Pad 1, stop.** The four variant clips are fired for the next bar. Each track takes over at
the same position. At that bar, the main clips get legato on and are fired for the bar after,
so the band comes back into the groove where it would have been. Once they have landed, their
legato goes off again: a main clip left with legato would start its next section mid-way.

**Pad 2, fill.** The same, for the drums track alone; bass, guitar and keys never stop.

**Pad 3, drums and bass.** Guitar and keys are stopped at the next bar, and their own scene's
next fire brings them back with the next section. A stop struck while they are out leaves
them out.

**Precedence.** A bar cue is declined when the next bar belongs to another section — fired
already, or simply the boundary — because Live's last trigger would take that section's
tracks away. A variant heard in the last bar of a section fires no return: the section change
brings every track back. A jump cancels a pending return. A cue arriving before its variant is
written is declined as `unavailable`, and one struck while the chorus candidate plays is
declined as `no_variant`: candidates have no variants.

### What is measured, offline

- Every applied bar cue lands after one bar, alone and interleaved with jumps across a whole
  three-minute song.
- The return fires the main clips of exactly the tracks the cue changed, with legato set four
  times at the variant bar and reset four times after the return lands.
- A fill touches only the drums. Drums and bass stops tracks 2 and 3 and fires nothing.
- A stop during drums and bass fires only drums and bass.
- A cue in the bar a section was fired is declined; a fill heard in a section's last bar is
  returned by the section change.
- No write lands in a sounding variant scene, and a performance with bar cues replays byte
  for byte.
- Both variants validate for any briefing and seed (2000 examples before committing at 60),
  never invent a pitch, and never overlap a note of their own pitch.

Suite: **1963 passed, 27 live-marked skipped**; `ruff`, `mypy` and the timing properties
clean.

### What the ear is asked, written before it is asked

1. **Does the stop feel like the band stopping with you?** One bar of hit-and-silence, then
   back in.
2. **Does the fill sound like a fill, and does the groove come back in the right place?**
3. **Does dropping to drums and bass, and the others coming back with the next section, feel
   intentional?**

Named in advance:

- **A cue struck early in a section may be declined as `unavailable`.** On the first section,
  and after a jump, the variants of the section that is playing are still being written, a
  track a bar. The summary counts declines by reason, so this is visible rather than a pad
  that silently did nothing.
- **Nothing happens on the pads while the jumped-to chorus plays.** Candidates have no
  variants yet; two more scenes would give them some.
- **The return costs legato round trips.** Four confirmed sets before the return fire, about
  400 ms inside a 1.82 s bar. It fits, and it is the first thing to look at if a return
  arrives a bar late.

### The gate: passed, with the fill in question, 2026-09-12

Fabiano ran `jam.py --controller minilab --seconds 150` and struck pads 1, 2 and 3 through a
twelve-section song. The run ended normally. The exit code 1 his terminal showed came from
the `!` that led the pasted second line, which the shell reads as "negate".

- **21 cues applied**: `fill` ×13, `drums_and_bass` ×6, `stop` ×2.
  - One stop fired only drums and bass, because guitar and keys were out, as designed.
- **Every return went back to the groove by its own legato fire, on time** — `late_bars` 0
  in all 13.
- **20 of 21 landed one bar after the pad. One landed two.** That fill arrived stamped with
  the last beat of bar 24, and was read after the clock had turned to bar 25, so it could only
  be fired for bar 26.
  - The clock only knows the last beat Live pushed, and Live pushes it on its control-surface
    tick, so a strike on the bar line itself can be stamped with the bar before.
  - A strike on a downbeat is heard by the person as "now". The system can only give it the
    next quantum, which is then a bar further than it looks.
  - That is latency in the beat's arrival, not in the queue. `fired_bar − cue_bar = 1` is a
    criterion a person can miss by striking on the line, and the log should read with that in
    mind.
- **Five cues declined**, each for its stated reason.
  - `section_change` ×4 — struck in the bar the next section was fired, or the bar before a
    boundary.
  - `unavailable` ×1 — a stop in the first verse, whose variants were still being written
    after a four-bar intro.

Asked §10's questions, he answered:

> *"Achei tudo bem, talvez a virada (pad 2) não me parecia tão clara, mas pode ser porque sou
> destreinado."* — I thought it was all fine; maybe the fill (pad 2) didn't seem that clear to
> me, but that may be because I'm untrained.

The stop and the drop pass. **The fill passes with a question on it, and the question is
not dismissed as an untrained ear.** ADR-019 makes his ear the instrument, and "not that
clear" is a reading from it. There are two plain reasons it could be true of the sound:

- **The fill changes only the snare**, over the second half of the bar, on a drum kit that
  is one Drift synthesiser. A kick carrying on underneath and hats dropping out are subtle
  on a synth.
- **A fill in a song lands on a crash.** This one returns to a groove bar that has none.

Making it clearer is a by-ear choice between concrete options, not a threshold: a fuller
and rising snare, a falling run of pitched drum hits in place of toms, a crash on the bar
the groove returns in. It is left open here rather than guessed at.

### The fill, auditioned blind

`scripts/audition_fills.py` played six fills, blind:
- the approved snare fill, a rising snare, and a run down four toms;
- each of the three again with a crash on the bar the groove returns in.

Every passage was the same five bars of the default song's first verse, twice, with a bar
of silence between passages to count them by. Fabiano asked to hear it twice. The second run
was the one he ranked (seed 69374), before anything was revealed:

> *"Mais claro em ordem 3, 5, 6, 4, 2, 1."*

Revealed:

| Rank | Passage | Fill |
|---|---|---|
| 1 | 3 | run down the toms, crash on the return |
| 2 | 5 | run down the toms |
| 3 | 6 | snare fill (the one heard at the gate) |
| 4 | 4 | rising snare |
| 5 | 2 | snare fill, crash on the return |
| 6 | 1 | rising snare, crash on the return |

- **The toms won outright**, first and second, with the crash and without.
- **The rising snare did not help.** It ranked below the fill it was meant to improve.
- **The crash is ambiguous.** It lifted the toms from second to first, but dropped the snare
  from third to fifth and the rising snare from fourth to sixth. One ranking by one listener
  cannot say the crash helps, and it is the expensive half: a crash on the return needs two
  more scenes and a second return step.

**Decision, Fabiano's: the fill cue becomes the run down the toms, without the crash** — his
second choice, a place behind the first, and a one-constant change. The crash stays an idea
with a cost attached; an audition between just those two options is how to settle it.

## 11. Stage 5 is built: "next: bridge", "end", and the knobs

The last of ADR-022's cues, end to end, offline. **The gate — Fabiano steering a whole song
from the MiniLab alone, by ear — has not run.**

### What each control does, in sound

**Pad 6, "next: bridge", and pad 8, "end", take effect at a section boundary, by design.**
Both re-plan from the first section that can still change. That is the next one, if it has
not been fired and there are two bars left to write it again; otherwise the one after.

- "Next: bridge" puts the song's own bridge there, at its ordinary size, and walks a new tail
  after it about as long as the old one.
- "End" puts the outro there, and the song finishes on its final chord.
- Struck with a bridge already next, or with the outro playing, they are declined and say so.

**Knob 1, density, and knob 2, tension, move the song around its plan rather than setting
it.** At the middle of their travel the song is as arranged. At the ends every section still
to come is up to two steps of `dyn` sparser or busier, and up to 0.3 calmer or tenser.
- The choice was made so a chorus stays bigger than a verse however far the knob is turned.
  An absolute knob would set both to the same size and flatten the shape the arrangement
  exists to give.
- The knobs are read at most once a bar and applied only when their step changes.
- They reach the next section when it can still be rewritten, or the one after.
- The plan before them is kept, so a knob turned back to the middle gives the song back.
- A chorus jumped to after a turn keeps its own size, because it was written before the song
  began; the tail after it is moved.

**The model hears all of it.** Every re-plan and every knob step is published through the
shared plan, so the producer asks for the moved briefing, and a score for the old one is
refused as stale.

### What is measured, offline

- "Next: bridge" early in a verse rewrites the chorus after it as a bridge, and the bridge
  is the scene fired. Late in the verse it changes the section after that instead.
- "End" in a verse plays the outro next and finishes on it.
- Density turned right puts `dyn` +2 on every section still to come, clamped at 5; left
  clamps at 1. Tension moves by 0.3.
- A turn inside one step re-plans nothing. A turn back to the middle restores the plan.
- The section a turn reaches is written again, as moved.
- After a turn, the model is asked for the moved briefing.
- A three-minute song conducted with stop, fill, drums and bass, "chorus now" and "next:
  bridge" plays to its end, every bar cue on the next bar, with no write in a scene a variant
  is sounding from.
- Seed plus cue and knob log replays byte for byte.

Suite: **2011 passed, 27 live-marked skipped**; `ruff`, `mypy` and the timing properties
clean.

### What the ear is asked, written before it is asked

1. **Does the bridge arrive where you asked for it, and the song end when you asked it to?**
2. **Do the knobs make the band sparser, busier, calmer and tenser in a way you can hear?**
3. **Across a whole song, does the MiniLab feel like conducting a band?** This is ADR-021's
   criterion: a session directed from the MiniLab, judged by ear.

Named in advance:

- **Nothing changes the moment a boundary cue or a knob is touched.** They wait for the next
  section that can change, often one section away. That is the design, and a person used
  to the pads' next bar may hear it as the controller not listening.
- **The first touch of a knob can jump.** The knob's position was unknown until it moved,
  so a knob sitting at the far right moves the song two steps at once.
- **The knobs' size is a guess**: two steps of `dyn`, 0.3 of tension. The ear is what can
  say whether that is enough, or too much.

### The gate: passed, 2026-09-13

Fabiano ran `jam.py --controller minilab --seconds 180` three times, conducting each song with
every pad and both knobs. The first run's song played to its end, and the script then failed
while printing the summary. `render_cues` read `fired_bar` from every applied cue, and a
boundary cue has none: it fires nothing, it re-plans from a section. The summary now names the
section each boundary cue re-planned from, and the knobs' last offsets. The second and third
runs printed it whole.

| Run | Bar cues applied | Landed after | Boundary cues applied | Knob steps | Declined | Song |
|---|---|---|---|---|---|---|
| 1 | 6 | 1 bar ×6 | `next_bridge` ×3, `end` ×2 | 12 | 6 | 61 bars |
| 2 | 12 | 1 bar ×12 | `end` ×1 | 14 | 3 | 68 bars |
| 3 | 8 | 1 bar ×7, 2 bars ×1 | `end` ×1 | 10 | 4 | 49 bars |

Every run: no `beat_lost`, no stale section, `section_measured` on every section.

**What the log says was played:**

- **"Next: bridge" and "end" re-planned where they should.** Each re-planned from the first
  section that could still change, and every song finished on its final chord.
  - In run 1, pads 6 and 8 were struck five times in six bars, and the last one struck won.
  - A sixth "next: bridge", with the outro next, was declined as `no_section_left`.
- **The knobs moved what was written, by as much as the table allows.**
  - A verse turned busier went from about 300 notes to about 500.
  - A chorus turned sparser went from about 520 to about 300.
  - A chorus turned busier, or a verse turned sparser, barely changed: they already sit near
    the end of the range the knob pushes them towards.
- **Pad 5 overrode the knobs every time.** In all three runs it was struck over a section the
  knobs had shaped, and the chorus it fires was written before the song began, so it does not
  follow them.
- **Pad 5 inside a chorus starts the chorus again from its first bar.** Struck during the
  outro, it cancels the ending, and the song goes on to another chorus and another outro
  (run 2). Neither was designed as a special case; both follow from "a jump beats a section
  change".

Asked §11's questions, he answered:

> *"Eu acredito que ficou tudo dentro do esperado. Inclusive o pad 5 no refrão além do impacto
> óbvio esperado."* — I believe it was all within what was expected. Including pad 5 in the
> chorus, beyond the obvious expected impact.

**The gate passes, and with it ADR-021's criterion of a session directed from the MiniLab,
judged by ear.** Pad 5 restarting a chorus is kept as it is: it was heard, asked about, and
accepted. The toms fill played in all three songs and was not singled out, either way.

The verdict is on the deterministic floor. No model played in these sessions, so the
criterion that a stale section never plays after a jump is still for Stage 6's paid session
to measure.

### What the gate found, not heard as a fault

**Two late moments, both behind a two-second write.**

- **Run 3: a fill landed two bars after the pad.** It was struck on the last beat of a bar
  while the next chorus was being written. Cues are read between one track's write and the
  next, and the track being written crossed the bar line.
- **Run 2: a fill's return went a bar late, so the fill ran for two bars.** Returns are
  settled once per bar, not between tracks, and that bar was spent writing a section.

**Every two-second write replaces a clip.**

- Across the three runs, every write whose slot held a clip of another length took
  1,910–2,031 ms: an eight-bar section after a four-bar one, or the other way round.
  `ensure_clip` deletes that clip and creates another.
- Every write into a slot of the same length took 1,107–1,230 ms.
- Replacing a clip costs about 0.8 s, which is close to half a bar at 132 BPM.

**A knob turn costs the bar cues their preparation.**

- Stop and fill variants are written one track per bar, and never in a bar that wrote a
  section.
- A turn that reaches the next section writes that section again, and that uses a bar.
- In run 3, a turn at the end of the first verse left the chorus's stop without its keys
  track until the chorus ended. Pad 1 was declined twice in that chorus as `unavailable`.

The **known limitations** stand as named. Boundary cues and knobs wait for a section that can
still change, and a strike on the bar line can be a bar late.

**Two cheap remedies are left open, not applied:**

- settle returns between tracks, as cues already are;
- write a variant track every half bar instead of every bar.

Both add work on the thread that carries Live's beat listener. Neither is worth doing before
a person hears the fault they remove.

## 12. Stage 6, rehearsed before it is paid for

Stage 6 opens with the phase's one paid session: an 8-minute `jam.py --generate --controller
minilab`. Before any money was spent, it was rehearsed offline with
`scripts/rehearse_session.py`.

- **Real:** the scheduler, the producer, the buffer, the shared plan, the governor and the
  prices.
- **Fake:** Live, where a write costs nothing, and the model. The model is a perfect one that
  answers eight beats after it is asked (Phase 3's p50 of 3–4 s) and bills the usage
  `bench_sections.py` measured, 300 tokens in and 228 out.
- **Replayed:** the pads and knobs of the three Stage 5 gate songs, one after another until
  the song ends, with `end` left out.

### What the rehearsal found

**A conducted session spent a third to a half of its calls on music nobody could hear.**

- The producer asked for any section in the buffer's window that had no score, starting from
  the section playing.
- The scheduler writes the next section in the first bar of the one playing. After a jump or
  a knob turn, the floor writes that section at once, and the model was then asked for it
  anyway.
- The rehearsal counted those shots: 18 of 57 calls with pads only, and 53 of 99 with the
  gate's pads and knobs together.

**Fixed, with nothing audible changed.**

- `ScoreBuffer.written` records the last section the scheduler put into Live. The buffer
  neither wants nor accepts music for that section or any before it.
- The scheduler marks every section it writes, and the candidate a jump fires.
- A section a knob re-plans stays marked. The floor writes it again at the next tick, sooner
  than any model could answer.

| Conducting (`--conduct`) | Calls before → after | Spend before → after | Model wrote, before → after |
|---|---|---|---|
| `none` | 33 → 33 | $0.105 → $0.105 | 31 → 32 of 35 |
| `pads` | 57 → 48 | $0.181 → $0.153 | 20 → 21 of 46 |
| `knobs` | 77 → 62 | $0.245 → $0.197 | 8 → 13 of 35 |
| `all`, as the gate played | 99 → 79 | $0.315 → $0.251 | 4 → 8 of 46 |

"Model wrote" counts the sections that actually played: the last write of each section before
its scene fired, with a jump's chorus counted as the floor's.

**The $0.10 target cannot be reached by an 8-minute session, conducted or not.**

- Eight minutes at 132 BPM is 35 sections, and 33 of them are long enough to ask about. At the
  measured $0.0035 a section, that is $0.105–0.115 with nobody touching the MiniLab.
- ADR-000 §4.4 estimated $0.08 for a three-minute song, which is about $0.21 for eight
  minutes.
- `target_usd = 0.10` was written in Stage 0, before anyone counted an 8-minute form's
  sections.

**Conducted, the model plays under half of the song, and with the knobs swept, a sixth.**

- A jump fires the floor's chorus. The floor also writes the section after it, within two
  bars.
- Each knob step rewrites the next section from the floor.
- This is ADR-022 working as designed: the model never serves a cue, only the sections after
  one. It is not a criterion. It is written down so that whoever listens to the paid session
  knows how much of what they hear is the model.
- The rehearsal leaves one saving unmade: calls still in flight when a re-plan makes their
  briefing stale run to the end and are billed.

### How the log is read, written before the session

`scripts/jam.py --generate` now ends by printing each criterion with the numbers it was
decided on (`obs/performance.py`). It also writes the governor's spend into the log as
`session_ended`, so the verdict can be read again from `bench/jam.jsonl`. Every
`section_requested`, `section_parsed` and `section_written` now carries its briefing, so
staleness is checked from the log, independently of the scheduler's guard.

- **8 minutes of continuous session:**
  - the song played to its end;
  - no `beat_lost`;
  - at least 480 s from the downbeat to the end.
- **No deadline overrun left unhandled:**
  - no boundary passed without its section (`not_written`, `repeated_too_long`);
  - no write failed.
  - Overruns are counted and reported.
- **Metrics:** every `section_written` has a `section_measured` with the same section and
  seed.
- **Cost:** the spend, measured plus estimated, is at or under `target_usd`. The $1.00 cap is
  the fuse, not the criterion.
- **Next bar:** every cue that fires has `fired_bar − cue_bar = 1`.
  - Counted strictly. A late cue is reported with the beat it was struck on, and is not
    excused afterwards.
  - The real Live can still make one late, as happened once in Stage 4 and once in Stage 5.
- **No stale section, and the model asked again after a jump:**
  - no model score was written under a briefing other than the one it was delivered for;
  - after each jump, the next section the producer asks about carries the re-planned song's
    name.
  - That is read as the first section after the jump that the model can still serve. The
    section straight after the chorus is written by the floor within two bars, faster than
    any model answers. Asking for it is the waste this section removed.
  - A session with no jump does not meet this criterion.
- **`kit_collision` is not tested.** Its inverted sign was not pre-registered, so this session
  cannot test it (ADR-019 §3).

### Predictions, written before the session

From `scripts/rehearse_session.py`, after the fix:

| `--conduct` | `--latency-beats` | Calls | Spend | Model wrote |
|---|---|---|---|---|
| `none` | 8 | 33 | $0.105 | 32 of 35 |
| `pads` | 8 | 48 | $0.153 | 21 of 46 |
| `knobs` | 8 | 62 | $0.197 | 13 of 35 |
| `all` | 8 | 79 | $0.251 | 8 of 46 |
| `pads` | 13 | 45 | $0.143 | 18 of 46 |
| `all` | 13 | 64 | $0.204 | 7 of 46 |

### The target, settled before the session

Asked before any money was spent, Fabiano raised `target_usd` from $0.10 to **$0.30** on
2026-09-13. The $1.00 cap is unchanged.

- The new target covers conducting as freely as the Stage 5 gate did, with room for what the
  rehearsal cannot model (below).
- The two alternatives were declined:
  - keeping $0.10 and deciding about a waiver after the session;
  - cancelling calls that a re-plan makes stale before paying. That saves up to about $0.05 and
    still does not reach $0.10.
- The criterion's text is unchanged. What changed is the declared number it points at, and it
  changed before anything was measured against it.

The real session adds four things the rehearsal does not model:

- the model's real token counts;
- streams cancelled at their deadline;
- deadline misses, of which there were none here;
- two-second writes into the real Live.

Suite: **2040 passed, 27 live-marked skipped**; `ruff` and `mypy` clean.

### The session: every criterion it could measure, met, 2026-09-13

Fabiano ran `jam.py --generate --controller minilab --seconds 480` with `claude-sonnet-5`
generating. He conducted with every pad except "end", and turned both knobs. The report it
printed, read from its own log:

| Criterion | Result |
|---|---|
| 8 minutes of continuous session | 489 s, 31 section changes, played to its end, 0 beats lost |
| No deadline overrun left unhandled | 67 asked, 51 delivered, 0 over deadline; 28 floor writes, each with its seed |
| Coherence metrics on every section | 54 of 54 section writes measured |
| Cost inside the declared budget | $0.238, none of it estimated, against the $0.30 target; the $1.00 cap never engaged |
| A MiniLab cue takes effect on the next bar | 34 of 34 landed one bar after the pad |
| After a jump, the model is asked again, and nothing stale plays | 5 jumps, asked after 5; 13 stale scores refused, 0 written |

**What was played:**

- **Controls received:** 619, of which 573 were knob positions.
- **Bar cues applied:**
  - `fill` ×17
  - `drums_and_bass` ×7
  - `stop` ×5
  - `chorus_now` ×5
- **Other pads and knobs:**
  - `next_bridge` re-planned the song 4 times.
  - The knobs moved the plan 31 times.
- **Declined:** 8 cues, for the stated reasons.
  - `section_change` ×5
  - `unavailable` ×2
  - `already_next` ×1

**Against the predictions written before it:**

- The rehearsal of this style of conducting (`--conduct all`) predicted 79 calls and $0.251.
  The session made 67 calls and spent $0.238.
- Each delivered section averaged 295 tokens in and 235 out, where the rehearsal assumed 300
  and 228.
- No stream was cancelled, so none of the spend is estimated.
- **The model wrote 12 of the 36 sections that played.** The rehearsal predicted 8 of 46 for
  the gate's heavier conducting, and a sixth to a half across the styles it tried. The rest
  were the floor, as §12 warned: a jump's chorus, the section after each jump, and each
  section a knob step rewrote.

**Not criteria, and not heard as faults:**

- A fill's return went a bar late once, in the outro, so that fill lasted two bars.
- Two section writes crossed 1.8 s, the clip replacements of §11. Neither cost a cue its
  bar.

Asked how it sounded, with the model's sections mixed among the floor's, he answered:

> *"Soou bem dentro do esperado."* — It sounded well within what was expected.

**Six of Phase 4's criteria are met by this session:** continuity, deadlines, metrics, cost, the
next-bar cue, and no stale section after a jump. Three remain:

- the chaos test;
- the musical regression suite in CI;
- the blind A/B at close.

The verdict is on the whole session. No section, and neither author, was singled out.
