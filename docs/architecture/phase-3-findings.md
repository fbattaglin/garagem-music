# Phase 3 findings — First structural generation (section-shot)

What the phase met that the plan did not predict, written as it happened. Four
measurement rounds, 120 section-shots, **$0.49 spent of a $2.00 budget**.

The short version: **the conformance criterion is not met, and three of the four rounds
were spent finding defects in the measurement rather than in the model.** That is worth
saying plainly, because the first number this rig produced was 7% and the honest reading
of it was "my parser and my prompt are wrong", not "the model cannot write the DSL".

---

## 1. The first run measured 7%, and almost none of it was the model

Round 1 (`bench/sections-v1.jsonl`), 30 shots, $0.15:

| criterion | measured | target |
|---|---|---|
| schema conformance, first pass | **7%** | ≥95% |
| validator approval, no repair | 7% | ≥80% |
| p95 latency / deadline | 1.00x | ≤1.00x |

Every one of those three numbers was wrong for a different reason, and all three reasons
were mine.

**`section_mismatch` at 29 of 30 — I sent one chart and compared against another.**
`brief()` renders the chart one chord per bar (§3 below); `check_chd` compared the reply
against the original four-chord chart. The model echoed back exactly what it was given
and was marked down for it. `check_chd` now compares **bar by bar**, so a four-chord
chart and its eight-chord expansion are the same harmony written two ways — which they
are.

**`p95 1.00x, max 1.00x, over deadline 0/30` — incoherent on its face.** A call cancelled
*at* its deadline has an elapsed time of exactly the deadline, so the two failures were
pinning the percentile to 1.00x whatever the 28 successes did. A failed call has no
latency; it has a cancellation. `deadline_fraction` now returns `None` when `ok` is
false, and failures are counted in `failures` and `over_deadline` where they belong.

**The rig recorded rule names and not the text.** Diagnosing "17 × `schema`" required
three more calls to see what the model had actually written. `Shot` now carries the raw
`dsl`, which makes a run **re-scorable offline**: a parser fix can be tested against
thirty real responses for nothing instead of for another thirty calls.

## 2. Two prompt defects, and the difference between them

Both were fields whose legal values the prompt showed by example and never stated.

**`voi=min`, `voi=clean`, `voi=power`.** The prompt showed `voi=pow` and `voi=sus2` and
never said those were two of six. Under a minor chord, `min` is what inference produces.
Enumerating the six with a one-line gloss each took the recorded cassettes from one clean
response out of three to **three of three**.

**A four-chord chart under an eight-bar section is ambiguous**, and a model reads it the
way a musician would: two bars per chord. `Chart.at` wraps instead, so the two readings
are genuinely different progressions. `brief()` now writes the chart out one chord per
bar. It costs a few tokens and it is the only honest way to send a chart whose length
does not match the section's.

**One prompt change made things worse and had to be reverted.** "For an 8-bar section
write 8 DRM lines, 8 BAS lines…" multiplied the output by eight, and `claude-opus-5`
promptly blew the 5.8 s deadline while recording a cassette. The parser has always
accepted both forms — one line covers every bar — so the instruction bought nothing and
cost a factor of eight in output tokens. The prompt now says the cheap form is the
default and the per-bar form is for when the bars actually differ.

## 3. Models do not put spaces where a grammar assumes them

Two of the same class, both fixed in the tokeniser rather than the schema:

- `DRM K:x..x..x...x..x..S:....x.......x...` — no spaces between the drum voices.
- `KEY voi=sus4 rhy:x.......x.......reg=mid` — no space before the next field.

Both are unambiguous: a voice tag is one known letter and a colon, and a grid is exactly
sixteen characters of `x` and `.`, so both are self-terminating. Splitting on them is
fixing a tokeniser that assumed spaces, not loosening a schema — **the grid is still
refused at any length but sixteen, which is the check that carries musical weight.**

**And the first attempt at the second one did loosen it.** `rhy:([x.]{16})` matched the
first sixteen characters of a 21-character grid and split the rest off as a stray field,
so an over-long grid was silently truncated to the right length. The regression test for
exactly that grid — a real Gemini response from Phase 3's planning — is what caught it.
The rule is now "split only where a **new field** begins", `(?=[a-z]+[=:])`, which is the
principle the comment claimed all along.

## 4. A confounded sample cannot attribute a failure

Round 3 came back at 83% with four failures, and **all four were at 150 BPM**. They were
not. `briefings()` stepped `bpm` by `index % 4` and `feel` by `index % 4` as well, so
every 150 BPM sample was also a halftime one and the two variables could not be told
apart. The failures were the feel's.

The sample is now a genuine grid — `bpm` on `index % 4`, `feel` on `index // 4` — which
covers **16 of 16 combinations** in the first sixteen samples. The old version covered
four.

The finding it then allowed: **halftime is where the model miscounts**, 3 of 6 against
0 of 7 for shuffle. One of them wrote a 32-character grid — two bars in one — which is a
reasonable reading of "halftime" that the prompt never contradicted. It does now: *"the
grid is always one bar of 16 sixteenths, whatever the feel."*

## 5. Where the criteria actually stand

Round 4 (`bench/sections.jsonl`), 30 shots, decorrelated sample, both prompt fixes in:

| criterion | measured | target | met |
|---|---|---|---|
| schema conformance, first pass | **77%** | ≥95% | **no** |
| validator approval, no repair | **77%** | ≥80% | **no** |
| p95 latency / section deadline | **0.81x** | ≤1.00x | **yes** |
| *reached the buffer at all* | **93%** | — | — |

Round 3 measured 83% and 77% on a confounded sample; the two runs bracket the real
number somewhere near 80%. **Conformance is not met and is not close.**

What is left, in 30 shots: two `voi=power` (an abbreviation the prompt spells out), three
grids off by one or two characters, and two deadline overruns. There is no further prompt
lever visible — the set is enumerated, the length is stated in words and shown in four
examples, and the model still occasionally writes fifteen.

**The number that matters for P2 is the last row.** A rejected line costs one instrument
for one section, and the producer fills it from the deterministic engine (§4.3, and
`agents/producer.py`). So 77% conformance produced 93% of sections reaching the buffer
playable — and the 7% that did not were the two timeouts, which are exactly what the
deterministic floor exists for.

## 6. Latency is comfortable, and short sections are not

p50 **0.49x** of the section's own deadline, p95 **0.81x**, max 0.94x, **0 of 28
successful calls over**. Phase 0 predicted this and it held: `claude-sonnet-5` is the
model whose worst call fits.

But two calls timed out, at 8.0 s and 5.12 s. And in round 1, the single failure was a
**4-bar intro at 110 BPM, whose deadline is 3.49 s** — under the p95 of the successful
calls in the same run. `MIN_DEADLINE_S = 1.5` lets through sections nobody can answer
for. Measured across all four rounds, successful totals run 2.37–4.50 s, so a deadline
under about 4.5 s is a coin toss.

Not changed yet, and deliberately: raising the floor means more sections go straight to
the deterministic engine without asking, which is a musical decision rather than a
technical one and belongs in a phase gate rather than in a findings file.

## 7. The prompt cache works, and the run got cheaper

Round 1 cost $0.1534; rounds 2–4 cost about $0.098 each with a **longer** prompt. The
stable block is read from cache — a recorded call shows `cache_read_tokens: 1038` against
`input_tokens: 231` — which is §4.4's argument, measured rather than assumed.

The cache is also why one cassette had to be recorded twice: the first recording under a
new prompt is the one that *writes* the cache, so
`test_the_cached_prefix_was_actually_read` correctly failed against it.

## 8. The cassette fingerprint is a good alarm and an expensive one

Three prompt changes meant three re-records of three cassettes, and each one is a real
API call. The mechanism is right — `CassetteProvider` refusing a request whose
fingerprint has moved is exactly what stops a prompt change from being silently tested
against answers to a different question — but the cost is attention rather than money:
each round is a handful of calls that can fail for reasons of their own.

`gemini-3.6-flash` took **five attempts**, four of them exceeding a 60 s deadline and one
returning HTTP 503. Phase 0 measured that model at p50 12.31 s with 6 of 15 calls
failing, so this is that finding reasserting itself rather than anything new. The 60 s in
the recipe is not §4.2's deadline — that one lives in `agents/section.py` and is 40% of
the musical time; this one only stops a recording from hanging, and the comment in the
recipe now says so.

Worth knowing before Phase 4 adds a tactical prompt: **each prompt is a cassette
maintenance cost**, and a project with several will want the recording of them batched.

## 9. A persistent HTTP pool belongs to the loop that created it

`scripts/ab_section.py` called `asyncio.run()` once per pair. Pair 1 worked; pair 2 died
with `RuntimeError: Event loop is closed`, deep inside `httpcore` closing an HTTP/2
connection.

The cause is the thing ADR-000 §7 asks for: *"`httpx` client with a persistent, warm
HTTP/2 pool"*. A persistent pool is bound to the loop that opened it. `asyncio.run()`
creates a loop and closes it on the way out, so the second call finds the pool holding
connections whose loop no longer exists. The fix is `asyncio.Runner`, which keeps one
loop across as many `run()` calls as the listening takes.

**The smoke test could not have caught it and did not.** It ran exactly one pair —
the only count at which this bug is invisible. A one-pair rehearsal for a twelve-pair
run tests the first iteration and nothing about iteration itself.

Every other `asyncio.run()` in the project wraps a whole run and is fine:
`bench_sections.py`, `record_cassette.py`, `bench_latency.py` each make one call, and
`agents/producer.py` makes one on its own thread. `tests/unit/test_ab_section.py` now
checks that across **every** script rather than in the one that hit it — an
`asyncio.run` inside a `for` or `while` fails the suite with the reason attached.

## 10. The blind A/B: the deterministic floor won, 9 of 11

Fabiano listened on 2026-08-31, eleven pairs of the twelve (one was skipped when the
model returned nothing usable). **The generated section was preferred in 2 of 11 — 18%,
against a threshold of 8 of 12.** The criterion is not met and it is not close; it is the
opposite of the criterion.

**The result is credible, and the first thing to check is why.** A blind A/B can fail for
a reason that has nothing to do with the music — a listener who always picks whichever
plays first would produce a lopsided number out of nothing. That did not happen:

| | |
|---|---|
| chose A / chose B | **6 / 5** |
| A was floor / A was model | 4 / 7 |
| when A was the floor, the floor won | 4 of 4 |
| when A was the **model**, the floor won | **5 of 7** |

The votes track the content and not the position. The floor won from both sides.

### Why: every generated section is a static loop

Over 28 real sections in `bench/sections.jsonl`, the model wrote **exactly one bar-level
line per instrument, 28 times out of 28**. A single line covers every bar, so a generated
eight-bar section is the same bar eight times.

The deterministic engine writes eight lines, three of them distinct:

```
bar 1: DRM K:x.....x.x.....x. S:....x.......x... H:xxxxxxxxxxxxxxxx C:x...............
bar 4: DRM K:x.....x.x.....x. S:....x.......x... H:xxxxxxxxxxxxxxxx C:...............
bar 8: DRM K:x.....x.x.....x. S:........x.xxx.xx H:................ C:...............
```

A crash on bar 1, the groove in the middle, a fill on bar 8. **The A/B compared a loop
against an arrangement.** Of course the arrangement won.

### And I blamed the wrong thing — see §11

When this was first written I put the loop down to a prompt change of mine: I had briefly
asked for eight lines per instrument, `claude-opus-5` blew a deadline, and I reverted to
wording that reads as "one line is the right answer". That was a plausible chain and every
link of it is real.

**It was not the cause.** §11 measured the arranged form directly, and the model writes one
line whatever the prompt says. The revert changed nothing. This paragraph is left standing
rather than edited away because a wrong diagnosis that measurement overturned is worth as
much as a right one — and it was confident enough to have been acted on.

### What this does and does not mean

It does **not** mean the model writes worse music than the engines. It means the system as
configured never asked it for an arrangement — and ADR-000 §7 puts arrangement in
**Phase 4**: *"a dynamics curve and transitions between sections (fills, breaks,
builds)"*. Phase 2's engines already do that. So the A/B set a Phase 3 output against a
Phase 2 output that has Phase 4 features in it.

That is not an excuse and the criterion stays unmet. It is the actual finding, and it says
something about the roadmap rather than about the model: **the deterministic floor Phase 2
built is a higher bar than Phase 3's exit criterion assumed.**

### One flaw in the A/B's own sample

`briefings()` steps the feel by `index // 4`, which covers four feels in sixteen samples
and only **three in twelve**. **Halftime was never tested.** That is the feel the
conformance run found hardest (§4), so the missing cell is not a random one.

## 11. The per-bar form cannot be obtained by prompting

> ## THIS SECTION IS WRONG. The prompt it claims to have measured was never sent.
>
> `scripts/bench_sections.py` defined `--arranged`, threaded `arranged=` through
> `one_shot` and `measure`, and then called `measure(...)` without it. The parameter took
> its default. **Both "arranged" rounds sent the static prompt**, so what is reported
> below as three prompts is one prompt run three times, and the finding — that the model
> will not write a per-bar section — **is unmeasured, not refuted and not confirmed.**
>
> Nothing in the output betrayed it: conformance, latency and output tokens all looked
> like three plausible runs of three prompts. It surfaced on 2026-09-01 while wiring a
> *third* flag, and was settled by comparing input token counts row by row — **26 of 26
> comparable rows identical across all three logs**, when `SYSTEM_ARRANGED` alone is 710
> characters longer than `SYSTEM` and would have shown as ~175 tokens.
>
> Fixed, and `tests/unit/test_bench_sections.py` now fails on any script flag whose
> `args.<dest>` is never read. Verified against the broken source: it reports
> `['arranged', 'dense']`.
>
> **The section is left standing, wrong, rather than deleted.** It is the second time
> this phase that a confident diagnosis of mine was overturned by a measurement (§10 was
> the first), and both times the value was in the overturning. What follows is what it
> said; §14 is what it is actually worth.

The question §10 left open — *does an arranged section fit the deadline?* — was measured
directly on `claude-sonnet-5`, twice, and it has no answer, because **the model will not
produce an arranged section at all.**

| run | prompt | conformance | out tok p50 | p95 latency | DRM lines (median) | with a crash |
|---|---|---|---|---|---|---|
| static | one line per instrument | 77% | 229 | 0.80x | **1** | **0 / 28** |
| arranged v1 | prose asks for per-bar | 73% | 232 | 0.70x | **1** | **0 / 28** |
| arranged v2 | example *is* arranged | 77% | 227 | 0.77x | **1** | **0 / 29** |

**85 sections, three prompts, zero responses with more than one bar-line and zero with a
crash.** The output token count did not move: 229, 232, 227.

The escalation was thorough, which is what makes the result trustworthy:

- The **user message** says *"then write 8 bars each of DRM, BAS, GTR and KEY, arranged."*
- The **system block** says *"For an 8-bar section, write 8 DRM lines, 8 BAS lines, 8 GTR
  lines and 8 KEY lines. Open bar 1 with a crash. Put a fill in the last bar."*
- The **example** is a complete two-bar section with two different DRM lines, the first
  carrying `C:x...............` and the second a fill.

That is about as far as prompting goes. Between v1 and v2 one real defect was fixed —
v1's instruction sat in prose while its example still showed one line per instrument, and
an instruction that contradicts the example beside it loses to the example. Fixing it
changed nothing.

**Latency was never the constraint.** p95 stayed at 0.70–0.80x of the deadline across all
three, and the arranged runs were, if anything, slightly faster. The 6.2 s estimate in §10
was arithmetic on an output that never grew.

### The likeliest reading, marked as a hypothesis

The model appears to treat a bar-level line as a **pattern definition for the section**
rather than as one bar of a sequence — which is how almost every drum-machine notation
works, and therefore how most of the notation in its training data works. If that is right,
no amount of instruction will move it, because it is not misreading the instruction: it is
reading the *notation*, and the notation looks like a pattern language.

Untested, and it would be cheap to test: the same request with the bar index written into
each line (`DRM 1 K:…`) would say whether the shape is what carries the meaning.

### What this changes

The three options at the end of §10 are no longer equal. "Measure it" is done and the
answer is *the model does not produce it*. What is left:

- **Give the DSL a compact way to say what the arrangement is** — `fill=last`, `crash=1`,
  or an `arc=` on the SEC line. One field rather than eight lines, and it plays to what
  the model demonstrably *does* do well: it writes a good groove, consistently, inside the
  deadline, at 77% first-pass conformance.
- **Compose the two.** The engines already arrange (`engines/drums.py` puts the crash on
  bar 1 and the fill in the last bar, from `tension`). The model writes the groove.
  `dsl/realise.py` could apply the engines' arrangement to the model's pattern, which is
  a small change and would give the blind A/B something fair to compare.
- **Move it to Phase 4**, where ADR-000 §7 already puts *"a dynamics curve and transitions
  between sections (fills, breaks, builds)"*.

The second is the one this finding actually argues for: **the model is good at grooves and
the engines are good at arranging them**, and nothing in the architecture says one call has
to do both.

## 12. The composition, and the fixed-point check that says it is the right one

Decided by Fabiano on 2026-09-01, from the three options at the end of §11: **compose.**
The model writes the groove; the arrangement decides where the bars differ.

The argument that settled it is not about the music, it is about the measurement. §10's
A/B put a **static loop** against **eight arranged bars** and reported 18%. That is two
variables at once — groove and form — and form is the louder of the two in a blind
listen. The A/B never measured what it was built to measure. Composing removes the
confound and makes it a one-variable test.

### What the change is

`dsl/realise.py`, inside `_drums`, and nowhere else. The whole of the difference between
a realised model section and an engine section turned out to be **two decisions**, both
in `engines/drums.py` and both pure functions of the briefing:

- a crash on the first beat of bar 1;
- `fill_for(section.tension)` in place of the last bar's snare, with the hat silenced and
  the kick playing through.

Drums are the entirety of it. `engines/bass.py` varies with `tension` but not with bar
position, and `engines/guitar.py` and `engines/keys.py` do neither — checked, not
assumed. So `_arranged()` is twelve lines and there is no second one.

The model keeps its kick, its snare and its hat in every bar it is asked about. On the
`anthropic_section` cassette:

    bar 1  K:x..x..x...x..x..  S:....x.......x...  H:x.x.x.x.x.x.x.x.  C:x...............
    bar 2  K:x..x..x...x..x..  S:....x.......x...  H:x.x.x.x.x.x.x.x.  C:................
    …
    bar 8  K:x..x..x...x..x..  S:........x.x.x.x.  H:................  C:................

### The fixed-point check

The strongest thing available to say about this change, and it costs nothing:

> Serialize an engine-produced section, parse it back, realise it, and the drum attacks
> are **identical** — 8 bars straight8, 4 bars shuffle, 8 bars halftime, 2 bars
> straight16.

That is not a coincidence to be noted, it is the claim. The arrangement now applied to
model output is *the same arrangement* the engines apply, and the engines' own output is
a fixed point of it. The Step 10 round-trip property test passed unchanged, which is the
same statement made continuously over generated sections rather than at four points.

It also closes something latent: `_for_bar` repeats one bar-level line across every bar,
so a model that *had* written `C:x...............` would have put a crash on all eight.
The crash belongs to the arrangement now and lands once.

### Why this is P4 rather than a retreat from it

"Never trust model output" is not the same as "ask the model for everything and check it
afterwards". A variation the model proved across 85 sections that it will not write is a
decision we take back, not one we keep asking for and keep validating. And this is not
the engine merge `dsl/realise.py`'s docstring forbids: `fill_for` is a lookup table,
imported exactly as `humanise` and `separate` already were. Two callers, one library,
no merge.

### What it does not yet do

**Nothing here has been heard.** The gate is green — 1495 passed, 15 skipped, `mypy`
clean over 136 files — and green tests are not a musical result. Until the blind A/B is
re-run, the honest statement of this section is: *the confound is removed and the test
is now worth running.* If the model still loses at 12 pairs, that is a real answer about
grooves and it was not available before.

## 13. The composition moved the A/B 40 points, and the gap that is left is the chorus

Re-run on 2026-09-01 against the composed realisation of §12, twelve pairs, same seeded
blind order, same threshold agreed on 2026-08-30.

| | preferred the model | rate |
|---|---|---|
| §10, static loop vs arranged floor | 2 of 11 | 18% |
| §13, composed vs floor | **7 of 12** | **58%** |

**The criterion is not met.** The threshold is 8 of 12 and the result is 7.

And 58% is **parity, not superiority**: P(≥7 of 12 | a coin) = 0.39. What the composition
bought is not a win, it is the removal of a defeat — §10 was measuring form, and with
form equalised the model's grooves sit level with a floor that a human approved by ear.
That is a real result and it is not the one the criterion asks for.

Said once and not leaned on: 8 of 12 would itself have been p = 0.19. The threshold was
a decision rule agreed before any number existed, which is what makes it honest; it was
never a significance test, and twelve pairs cannot be one.

### Where the five losses are

| | preferred the model |
|---|---|
| intro, verse, bridge | **6 of 6** |
| chorus | **1 of 6** |

Fisher exact, two-tailed: **p = 0.015**. **This split was found after the vote, not
before it** — it is a hypothesis this run generated, not one it tested, and it needs its
own pre-registered test before it is treated as established.

**The apparent feel effect is this effect wearing a disguise.** straight16 went 1 of 4
and would read as "the model cannot do sixteenths" — but three of straight16's four pairs
were choruses, and its one verse went to the model. The same confound as §4, in the
sample rather than the briefings: a reader chasing the feel would be chasing nothing.

### Why the chorus loses, measured for free on a different sample

Every logged section-shot already carries its DSL (`Shot.dsl`, §1), so the question cost
nothing to answer over the 85 sections of §11 — a *different* dataset from the twelve
pairs that raised it.

Attacks per drum bar, model against the floor for the same briefing:

| section | `dyn` | n | model, median | model, range | floor |
|---|---|---|---|---|---|
| intro | 1 | 1 | 8 | 8–8 | 8 |
| verse | 2 | 26 | 14 | 6–15 | 12 |
| bridge | 3 | 14 | 14 | 10–15 | 13 |
| chorus | 4 | 44 | **14** | 10–24 | **22** |

**The model writes one density whatever `dyn` says.** Verse, bridge and chorus all come
back at a median of 14. That half stands.

> **The floor column above is wrong and is left standing, marked.** It is
> `groove_for(STRAIGHT8, dyn)` — one feel — while the model's column spans all four. Read
> against the floor for *each row's own* feel, the floor's chorus median is **14**, the
> same as the model's, and the "57% busier" sentence that stood here was an artefact of
> comparing four feels against one. The mistake was caught before the $0.10 run it would
> have justified, by recomputing the table rather than re-reading it.

Per feel, the floor's chorus (`dyn=4`) is 22 in straight8 and 23 in straight16 — where it
does lift hard — but 14 in shuffle and 13 in halftime, where it barely lifts at all. There
is no single floor number, and the model's flat 14 is below the floor in half the feels
and level with it in the other half.

The briefing is not at fault: `engines/arranger.py` gives a chorus `dyn=4, tension=0.70`
against a verse's `dyn=2, tension=0.35`, and both sides receive it. The difference is
what each does with it. **On the model's path `dyn` reaches the music as velocity and
nothing else** (`BASE_VELOCITY + DYN_VELOCITY * section.dyn`): the same groove, louder.

That last fact is the one worth keeping, and it does not depend on the A/B at all.
**`dyn` is a briefing field the system sends and the model does not act on** — 14, 14, 14
across three levels of it, over 85 sections. The floor honours it (8 → 12 → 13 → 22 in
straight8; 12 → 20 → 21 → 23 in straight16). A control that does nothing on the model path
is a defect whether or not it is the one the A/B heard, and ADR-000 §7 puts *"a dynamics
curve"* in Phase 4.

### A second post-hoc split, recorded and not acted on

Crossing the twelve votes against the floor's density *for each pair's own feel*: where
the floor played ≥20 attacks the model won **1 of 5**; where it played fewer, **6 of 7**.

That is cleaner than the chorus split — and it is **the second hypothesis fitted to the
same twelve points after the first one broke**, which is how a small sample is talked into
saying anything. It is also not independent of the first: the dense-floor pairs *are*
mostly the straight8 and straight16 choruses. It is written down so the next A/B can
pre-register it, and for no other purpose.

This is §11's shape on a second axis. There, the model wrote one *line* whatever the
prompt asked; here it writes one *density* whatever the briefing says.

### What must not be assumed

**That §11 transfers.** §11's hypothesis is about notation — that a bar-level line reads
as a pattern definition — and it explains a line *count*. It says nothing about whether
the model will write a busier grid when asked in so many words. Carrying it over without
measuring would be the same confident wrong diagnosis §10 already cost once.

The test is one bench run and about $0.10: state the density target in the briefing
("a chorus at dyn=4 is roughly 20–24 attacks per bar; a verse at dyn=2 is roughly 12"),
re-run 30 sections, and rebuild the table above. If the chorus median moves off 14, the
fix is a sentence. If it does not, density gets composed the way form was in §12 — and
that is a larger change than §12, because it means generating attacks the model did not
write rather than substituting a fill it already had.

### Two limits of this run, both structural

- **Position bias is not testable at this size.** The seeded order gave the model side A
  in 8 of 12; it won 5 of those 8 and 2 of the 4 where the floor went first. Four pairs
  on one arm can neither show a bias nor rule one out. (§10's run could: the floor won
  from both sides.)
- **Halftime has still never been in an A/B.** Twelve pairs reach three of four feels,
  for the second run running.

## 14. What §11 would have found if it had run: both answers, and they differ

Two rounds of thirty on `claude-sonnet-5`, 2026-09-01, with the flag actually wired.

| run | prompt | conformance | reached buffer | p95 latency | out tok | chorus attacks/bar |
|---|---|---|---|---|---|---|
| static | the baseline all of §11 really sent | 77% | 93% | 0.81x | 229 | 14 |
| **dense** | `dyn` explained | **53%** | **97%** | 0.91x | 231 | **18** |
| **arranged** | one line per bar | **0%** | **0%** | — | — | — |

### The arranged form does not fit the deadline. 30 of 30.

§10 asked whether an arranged section fits inside 40% of the musical time. §11 claimed
the question was moot. It is not moot and the answer is **no, categorically**: every one
of thirty calls was cancelled at its deadline, across deadlines from 3.49 s to 8.00 s.

**TTFT was normal** — median 1.64 s, max 2.18 s, in line with every other round. The
stream started on time and never finished. Whatever the model is doing with the arranged
prompt, it is producing far more output than 229 tokens' worth, which is exactly what §11
predicted would happen and then reported as not happening because it never asked.

Two things this run cannot say, and neither should be read into it:

- **How much had arrived at the cancel.** `one_shot` returns early on the exception
  without calling `stream.result()`, so `parts=0` on those rows is a code path and not a
  measurement. §4.3's *"write what arrived"* is precisely what the bench rig does not
  measure, and the producer — which does implement it — was not the thing under test.
- **What it cost.** Recorded as $0.0000 because `Usage` arrives on the `done` event and a
  cancelled stream never sends one. Tokens were generated and billed. **The true cost of
  this round is unmeasured and is not zero**, which is a hole in the rig's accounting and
  is listed as open.

So §12's composition is not merely a good idea, it is the only one of §10's three options
that survives contact with the deadline. That it was already built, and already worth 40
points of A/B, is luck rather than judgement — the judgement was made on a finding that
had not been measured.

### `dyn` does move the model, and it costs conformance

The half of §13 that survived its own correction was: **`dyn` is a briefing field the
model does not act on** — 14 attacks per bar at dyn=2, dyn=3 and dyn=4 alike. One
paragraph in the stable block fixes it:

| | verse (dyn=2) | bridge (dyn=3) | chorus (dyn=4) |
|---|---|---|---|
| static | 14 | 15 | 14 |
| dense | **12** | **15** | **18** |

A flat line became a curve. The model was not refusing to vary density; **it was never
told what the number meant.** For the record, that is the opposite of §11's hypothesis
about the model being deaf to instruction, and it is a second reason to distrust §11.

**The price is 24 points of first-pass conformance: 77% → 53%.** The cause is not
mysterious and it is the phase's oldest known weakness:

| | static | dense |
|---|---|---|
| grid off by one character | 3 | **8** |
| `voi=power` for `pow` | 2 | 6 |

A busier grid is a longer thing to count, and counting sixteen characters of `x` and `.`
is the one thing a tokeniser makes hard. Asking for density buys density and buys
miscounts with it.

**But the number P2 rests on went up, not down: 97% reached the buffer against 93%.**
The extra failures are off-by-one grids, and an off-by-one grid is a line the repairer
handles. Conformance measures whether the model got it right; `usable` measures whether
the music plays. This round moved those two in opposite directions, which is the clearest
argument yet that the phase is being judged on the first when it cares about the second.

### The trade this hands back, undecided

**+4 attacks of chorus lift for −24 points of conformance**, with `usable` up 4 points and
p95 latency up from 0.81x to 0.91x. Both numbers are real and they point opposite ways.
Nothing in this file should choose: the conformance target is ADR-000's, and moving it or
accepting a miss against it is not a finding, it is a decision.

## 15. The cheap fixes were worth 16 points, and the residue is one defect

Stage A1–A4 of the 2026-09-01 plan, re-measured on `claude-sonnet-5`, 30 briefings drawn.

| | static (before) | fixed (after) |
|---|---|---|
| schema conformance, first pass | 77% | **93%** |
| validator approval, no repair | 77% | **93%** — target is 80%, **met** |
| p95 latency / deadline | 0.81x | 0.84x — **met** |
| reached the buffer | 93% | **100%** |
| outright failures | 2 of 30 | **0 of 29** |
| cost | $0.0993 | $0.1036 |

**Two of Phase 3's failing criteria now pass.** Approval clears 80% with room, and it did
so without a single line of the repairer being invoked: every section that parsed was
musically valid, which was true before as well and is now true of 93% of them.

### What each fix actually bought, and what it did not

**A1, the `power` alias: 2 of the 7 known failures, and it is gone from the sample.**
Zero occurrences in 29 sections against 8 in the previous 90. It only ever appeared in
choruses, which is consistent with the model naming a musical idea rather than making a
typo.

**A2, `MIN_DEADLINE_S` 1.5 s → 5.0 s: not what the plan claimed.** The plan predicted it
would remove two deadline failures. It removes **none of them** — both static failures had
budgets of 8.00 s and 5.12 s, the most generous in the sample, and were the p99 *tail*
rather than short sections. What it actually does is decline one four-bar intro in thirty
before spending a call on it. That is worth doing and it is a smaller claim than the one
the plan made; the plan was corrected before the code was written.

**The 0 failures are one clean round and do not retire the tail.** p95 0.84x, max 0.84x —
nothing came close this time. ADR-000 §9 rates the tail High-probability and one quiet
afternoon is not evidence against it.

### The residue is a single defect class

Two violations in 29, and both are the same thing:

    a grid is 16 characters, got 15: 'x......x.......'   (DRM K)
    a grid is 16 characters, got 17: 'x.......x.x....x.' (BAS rhy)

No voicing errors, no missing fields, no prose, no truncation. **Counting sixteen
characters of `x` and `.` is the only thing left standing between this phase and its
conformance target**, which is what §5 suspected, what §14 confirmed under load, and what
the plan named as the condition for taking the notation change seriously.

### And 95% is granular at this sample size

At n = 29 each section is worth 3.4 points. 28 of 29 is 96.6% and 27 of 29 is 93.1%:
there is no value between them. **The criterion as stated is therefore "at most one
violation in thirty"**, and the run produced two. That is worth saying plainly rather than
reporting 93% as though the gap were a slope — closing it means removing an entire defect
class, not tuning one.

The options are unchanged and the decision is not a findings-file decision. What has
changed is that one of them is now specific: **attack positions (`K:0,3,6,10,13`) instead
of a fixed-width grid** would remove the only class of error the model still makes, is not
longer in tokens, and turns a rejected bar into a misplaced note. Against it: the DSL's
whole premise is that the model can *see* the grid, and §11's pattern-language hypothesis
was never tested. One 30-section run per notation would settle it for ~$0.20.

## 16. The pre-registered A/B: 5 of 12, and it refutes §13's mechanism

Third run, 2026-09-01, against the composed realisation, on the balanced grid: six
choruses and six of everything else, four feels three times each, each feel at three
different tempos.

| run | design | preferred the model |
|---|---|---|
| §10 | static loop vs arranged floor | 2 of 11 — 18% |
| §13 | composed, accidental sample | 7 of 12 — 58% |
| §16 | composed, balanced and pre-registered | **5 of 12 — 42%** |

**Not met.** The threshold is 8 of 12 and it has never been reached.

### Pooled, the answer is parity, and that is the finding

The two post-composition runs together: **12 of 24. Exactly 50%.** Both are individually
consistent with a coin (P(≤5 of 12) = 0.39; P(≥7 of 12) = 0.39), and pooling them removes
the temptation to read either as a trend.

So the phase's central question has an answer, and it is not the one ADR-000 hoped for:
**a model-written section is neither better nor worse than the deterministic floor.** The
criterion asks for ≥65%. Twenty-four blind pairs say 50%.

This is the result the original plan called the most valuable one available — *"it says
the model is not yet worth its latency, and that is a finding, not a setback"* — and it
is worth more now than it would have been in §10, because §10 was comparing a loop against
an arrangement and this compares two arrangements.

### The pre-registration failed its threshold and refuted its own mechanism

Fixed before the run: **chorus pairs, model in ≥4 of 6.** Measured: **2 of 6.** Not met.

But the threshold is not the interesting half. §13's claim was *differential* — chorus
1 of 6 against everything else 6 of 6, Fisher p = 0.015. Tested properly:

| | §13 (post-hoc) | §16 (pre-registered) |
|---|---|---|
| chorus | 1 of 6 | 2 of 6 |
| everything else | **6 of 6** | **3 of 6** |
| chorus vs rest | p = 0.015 | **p = 1.000** |

**The chorus is not where the model loses. It loses everywhere.** §13's "6 of 6" did not
replicate at all, and with it goes the reading that the model's weakness is a failure to
lift the chorus. That reading survived a density measurement on a separate sample and
still did not survive a pre-registered test, which is the whole reason to pre-register.

The density composition of A4 is not thereby wrong — it makes the model's chorus match
what the engine plays, which is right on its own terms. It is simply not what the ears
were reacting to.

### What the ears were reacting to, which is new

The reason capture added on 2026-09-01 earned itself on its first run:

| reason given | model won |
|---|---|
| **cleaner, less messy** | **0 of 3** |
| more energy | 1 of 3 |
| just sounds nicer | 2 of 3 |
| less boring | 2 of 3 |

**Every pair the floor won on "cleaner" it won.** And the model wins on "less boring" and
"just sounds nicer", 4 of 6 between them. That is a coherent picture rather than noise:
**the model writes more interesting material and messier material, and the two cancel.**

Twelve pairs is twelve pairs and this is one run of it. But unlike every split this phase
has chased, *messiness is a mechanism, and a machine can measure it*: notes colliding,
instruments piled into one octave, pitches outside the chart. Phase 4's `register_spread`
and `harmonic_conformance` are exactly those metrics, and this run has handed them a
**calibration set** — twelve sections, each with a human verdict and a word for it. A
metric that cannot separate the three "messy" losses from the other nine is not measuring
what the ear heard, and that is a test the metrics can be held to before anyone listens
again.

### Two things this run does not say

- **straight16 went 0 of 3**, and that is not evidence. With four feels at n=3, the
  chance that *some* feel shows 0 of 3 under a coin is about 41%. It is the second run in
  a row where straight16 came last (1 of 7 pooled, p = 0.06 across two different sample
  designs), which makes it a candidate worth a targeted run and nothing more. §13 read the
  same signal as the chorus effect in disguise; the chorus effect is now gone and the
  signal is still there, so that reading was wrong too.
- **Position bias, still not testable.** The seeded order put the model first in 8 of 12
  again; it won 3 of those 8 and 2 of the 4 where the floor led. The direction is the
  opposite of §13's, which is what no bias looks like, and four pairs on one arm settle
  nothing either way.

## 17. Positions instead of a grid: the last defect class, removed

`K:1,4,7,11,14` in place of `K:x..x..x...x..x..`. Thirty briefings, 29 askable, the same
rig and the same seed as §15, on 2026-09-01.

| | grid (§15) | positions |
|---|---|---|
| schema conformance, first pass | 93% | **97%** — target is 95%, **met** |
| **schema violations** | **2** | **0** |
| outright failures | 0 | 1 (the p99 tail) |
| reached the buffer | 100% | 97% |
| p95 latency / deadline | 0.84x | **0.69x** |
| output tokens, median | 229 | **217** |
| cost | $0.1036 | $0.0996 |

**The rate is not the result. The defect class going away is.** 93% and 97% differ by one
row out of 29, which is noise. What is not noise: the grid miscount ran at **18 of 149
sections** across every round this phase, and positions produced **0 of 29**. P(0 of 29
at that rate) = **0.024**. There is nothing to count, so nothing gets counted wrong.

The one non-conformant row is a `DeadlineExceededError` at a 6.98 s budget — the tail,
which ADR-000 §9 rates High-probability and which no notation addresses.

### Why it was worth measuring rather than assuming

The DSL's premise (ADR-002) is that the model can *see* the grid, and a fixed-width bar is
the notation drum machines use. Trading it for a slot list could have cost legibility for
nothing. It did not: positions are shorter, faster and refused-by-number when wrong.

**Out of range is now detectable.** A grid short by one silently shifts the bar and is
only caught because we count characters; slot 99 names itself. That is the structural
difference, and the reason this is a class removed rather than a rate improved.

### One-indexed, because half the DSL already was

`ghost=` and `acc=` have taken 1-indexed positions since Step 7. A bar written `K:0,3,...`
beside `ghost=1,...` would have put two conventions in one line — so slot 1 is the
downbeat, and `render_positions` is the exact inverse.

The parser takes **both** spellings and always will. A grid is sixteen characters of `x`
and `.`, a slot list is digits and commas, the alphabets are disjoint, and dispatching on
`x`/`.` first is what keeps every existing error message — including the regression
pinning the real 21-character guitar grid from `google_section_flash`.

### What it did not change, which is a useful negative

§11 guessed the model writes one bar-level line because grid notation *looks like* a
pattern language. Under a completely different notation:

- **DRM lines per section: median 1, max 1.** Unchanged.
- **Sections with a crash: 0 of 28.** Unchanged.

So the notation was not what made the model write one line. The pattern-language reading
loses its last support, and ADR-017's composition remains the answer rather than a
workaround for a syntax problem.

### Adopted, with the old block kept

Positions are the default from 2026-09-01: `system_for()` returns `SYSTEM_POSITIONS` and
`positions=False` returns `SYSTEM`. `SYSTEM` is untouched and stays reachable, because
four cassettes and every earlier measurement in this phase were taken against it and a
comparison you cannot re-run is not a comparison. `bench_sections.py --grid` re-runs it.

## What is still open

- **The rig does not price a cancelled call.** `Usage` arrives on `done`; a stream
  cancelled at its deadline never sends one, so thirty billed calls recorded $0.0000
  (§14). Every deadline round this phase has under-reported its own cost.
- **Whether to buy chorus lift with conformance** (§14), which is ADR-000's target and
  therefore not a findings-file decision.


- **The conformance criterion.** 77–83% against a 95% target, with no prompt lever left
  in view. Options, in ascending order of how much they give up: a stricter tool schema
  (a JSON array of 16 booleans rather than a 16-character string, which trades tokens and
  legibility for a length the API itself enforces); a repair path for an off-by-one grid;
  routing the structural layer to `claude-opus-5` and accepting its tail; or accepting
  ~80% and leaning on the 93% that reaches the buffer. **None of these should be chosen
  in a findings file.**
- **`MIN_DEADLINE_S`**, per §6.
- **Whether the chorus density is a prompt or a composition** (§13). One 30-section run
  at ~$0.10 settles it, and nothing should be built until it has. **Do not assume §11
  transfers** — it is about a line count, not a grid.
- **Whether the chorus split is real.** Found after the vote, p = 0.015 on n = 12, and
  confirmed on a separate sample only as a *density* gap, not as a cause of preference.
  The next A/B should pre-register "chorus pairs ≥ 4 of 6" so the question is tested
  rather than noticed again.
- **Position bias in a 12-pair design**, per §13: four pairs on one arm settle nothing.
- **The pattern-language hypothesis** in §11, which one cheap run would test.
- **Halftime in the A/B**, per §10.
