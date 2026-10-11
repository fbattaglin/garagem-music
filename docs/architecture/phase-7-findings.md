# Phase 7 findings

## 1. Relief in the form

Built on 2026-09-20, with no model and no network. Stage A of
[ADR-027](ADR-027-the-arrangement.md), and the reason is Phase 6's closing verdict: *"a
música número três foi mais chatinha e repetitiva entre elas"* (`phase-6-findings.md` §8).

### The rule

`arranger.TRANSITIONS` makes a bridge rare — one weight in seven out of a verse, three in
eight out of a chorus — so once the walk is past one, a song alternates verse-chorus for as
long as it lasts. **After `RELIEF_AFTER` sections of verse and chorus alone, the next kind is
forced to be one that is not.** The kind itself still comes from the same table with the same
weights, so what relief the song gets is still the song's own choice and only its *timing* is
forced. One draw either way, so a seed's stream stays aligned.

**Six, from his two data points and nothing else.** The song he heard as repetitive ran
twelve sections of alternation; the one he did not single out ran five. The line is drawn
just above what was heard to work — a musical choice settled by ear, not a threshold derived
from anything (ADR-019).

### What it does to the song he named

Seed 23, `Half light`, the halftime song:

    before  intro verse bridge verse chorus verse chorus verse chorus verse chorus verse chorus verse chorus outro
    after   intro verse bridge verse chorus verse chorus verse chorus bridge chorus verse chorus verse chorus outro

Its longest run of verse-and-chorus falls from **12 to 6**, and the bridge it gains lands at
section 9 — the middle. That is where song 2's second bridge was, and song 2 is the one he
did *not* call repetitive. Over 200 seeds the worst run is 6.

### It found a latent bug in two measurement rigs, and they are the interesting part

Changing the arranger turned 21 tests red, in two rigs that had nothing to do with the form.
Both said a version of the same thing, and both were right:

> *"The arranger has moved since this round was recorded; the corpus cannot be scored
> against it."*

**Both rigs rebuilt their population by replaying a generator that is free to change.** The
rows in `bench/sections-*.jsonl` and the cassettes in `cassettes/regression/` carry
measurements but not always the briefings they were measured on, so the briefings were
re-derived from `bench_sections.draw`, which walks `arranger.arrange`.

That is a rig for reading *history* depending on a table under active development. Phase 7
moves the arranger twice — this rule, and the solo section — so it would have fired twice.

- **The calibration corpus cannot be recorded again.** It is DSL paid for during Phase 3, and
  the money is spent. Its population is now written down in
  `bench/calibration-corpus.json`, reproduced from the arranger as it stood before this rule
  and frozen. `calibrate_metrics.frozen_corpus` reads it;
  `test_the_corpus_is_written_down_and_not_regenerated` pins its first rows so nobody
  regenerates it by accident.
- **The musical regression set already carried its own briefings** — a `Recorded` holds its
  `Section` — and the guard re-drew the set anyway and compared. **2 of 29 briefings had
  moved.** The guard now checks that the recording is consistent with itself: every row's id
  and seed still derive from the section it carries. Recording a fresh set stays a deliberate
  act with `--yes` behind it, and what it costs is ~$0.10.

Put to Fabiano with those numbers, he chose to freeze rather than re-record — which also
keeps the rates of Phases 3 to 6 comparable with whatever comes next.

**Nothing musical moved:** no golden file changed in this stage, and the whole suite is at
**2378 passed, 27 skipped** with `ruff` and `mypy` clean.

### Heard

One jam on seed 23 — the song he named — on 2026-09-23, with the network irrelevant because
nothing here asks for it. His verdict:

> *"Achei que teve um bom improvement comparado com a versao anterior. Podemos seguir com a
> etapà B"*

Criterion 1 is met: the property holds over every seed the strategies generate, and the song
that produced the complaint was heard again and heard as better. **The threshold stays at
six** — he did not ask for less, and moving it now would be moving a number that a listening
already settled.

## 2. The solo section

Built on 2026-09-23, with no model and no network. Stage B of
[ADR-027](ADR-027-the-arrangement.md), and the reason is the other half of Phase 6's closing
verdict: *"a guitarra … tem potencial para muito mais no futuro. Como a possibilidade de fazer
solos."*

### A fifth kind

`solo` joins intro, verse, chorus, bridge and outro in `arranger.SHAPES`: eight bars, `dyn` 3,
tension 0.65. It may follow a chorus and nothing else — a weight of 2 in 10 — and it leads
back into one, 7 in 8. It is in `RELIEF`, so it breaks a run of verse and chorus by existing,
which is the one change answering two complaints that ADR-027 was built around.

**`dyn` 3, not 4, and that is the decision in the table.** The plan proposed chorus energy. It
would have cost an approved property: `test_tension_rises_into_every_chorus` has held since
Phase 4 that a chorus is a step up in *both* `dyn` and tension from whatever precedes it, and a
solo at `dyn` 4 makes that false for every chorus after a solo. Relaxing a pinned property to
fit a new feature in is the move this project does not make. It is also the better music: the
solo is the one voice nothing else is covering, so the band it plays over has to leave room,
and the chorus that answers it still arrives bigger. The solo has the stage *because* the band
steps back, not because it shouts.

Its charts move — four different chords, one a bar — because a solo over one chord has nothing
to play *over*. In minor the first is `i VII VI v`, the andalusian cadence; in major, `I IV V
IV`. `ENDINGS[(SOLO, CHORUS)]` is a `BUILD`: the roll under the last bars is the band coming up
under the soloist's last phrase. The stop is still saved for the last chorus whatever came
before it, which `endings_for` sees to and a test now pins.

### The floor's solo

Invariant 2 is not suspended for a section kind, so `engines/lead.py` grew a second half.

- **Two runs, alternating.** A run is a table of eighths and how far up the section's scale each
  is from the note that bar began on. The section draws a call and an answer and repeats the
  pair: one run eight times is a riff, eight fresh runs are eight beginnings.
- **The bar's anchor is its chord's root as a step of the key**, so the same written run sounds
  different over every chord — which is what makes the repeat worth hearing.
- **Every run opens and closes on 0, 2 or 4 steps above the anchor.** Over a diatonic triad
  those are the root, the third and the fifth, so **every bar line is a chord tone and every
  note between them is in the key** — which is all `_dissonance_budget` counts. Legal by
  construction, no repairer, the same bet `_in_the_chord` makes for the hook one level up.
- **The last bar is still the drummer's.** The solo lands on its downbeat, holds half a bar and
  gets out of the way.
- **The dynamic gate is not consulted.** The density knob may take the hook away; it cannot
  take the solo out of the section the solo is the reason for.

`theory/scales.py` gained one primitive for it, `scale_pitch`: a pitch counted in the *key's*
scale rather than in a chord's. `degree_to_pitch` asks each chord what scale it implies, which
is right for a bass playing that chord and wrong for a line crossing a chord change.

### The width was one semitone too wide, and a sweep found it rather than a test

The first version let a run reach 5 steps above its anchor. It played, it validated, and the
whole unit suite was green — and then the measurement sweep for criterion 2 crashed on the
fourth key it tried:

    UnvoiceableError: no octave of (66, …, 85) lands inside LED (55-84)

Arithmetic, not luck. A solo is as wide as one bar's run **plus the spread of the anchors
across the key**, and it is placed by whole octaves, so it fits only when some octave of the
key's root leaves room both under it and over it. At 5 steps the widest line spans 19
semitones, the lead's range is 29, and the window is `29 - 19 + 1 = 11` semitones — **narrower
than the octave lattice it has to land on**, so in some keys there is no octave at all.

At 4 steps the line spans 17 and the window is 13. `TOP_STEP` is now that number, with the
arithmetic as its comment and a test that asserts the window is at least an octave for every
scale this project knows — a test that fails at 5, checked. The old
`_in_range`, which delegates to `fit_to_range`, is still the hook's; the solo places itself,
because `fit_to_range` sorts what it returns (nothing to a chord, everything to a melody) and
raises when no octave fits, and a floor with a failure case is not a floor.

**The lesson is about where the bug was found.** 100 unit tests over four feels, twelve keys
and six scales were green. What caught it was generating every solo section of 3 200 arranged
songs — the thing the criterion asks for anyway. A property that holds for a sample of keys
and fails for a key is not a property, and the cheapest way to know which one you have is to
run the population the criterion names before writing the findings, not after.

### Measured

Every solo section of 3 200 arranged songs: 200 seeds × 4 scales × 4 feels, keys walking, each
section played by the floor with its own ending composed over it and validated.

| what | n | result |
| --- | --- | --- |
| solo sections, `validate` after `compose` | 3 376 | **0 violations** |
| bars of a solo section with the lead in them | 27 008 | **27 008 (100%)** |
| solos silenced by the density knob, over its whole travel | 660 | **0** |
| solos broken by either knob, over their whole travel | 660 | **0** |

139 276 lead notes, none outside the lead's range, none outside its key.

### What moved, and what did not

- **Two arranger tests**, and this is the cost ADR-027 named up front: giving the chorus a
  third thing to choose changes its weights from 8 to 10, so **every form the arranger writes
  is different**. Seed 23's relief now falls in different places. The test that pinned it
  asserted `len(bridges) == 2`, which was a test pinning a specific song — the thing this
  module's own docstring warns against — and it now asserts the property instead: the longest
  run is still 6, and relief still lands inside the song rather than only at its edges.
- **No golden file moved.** Two were added: `solo-straight8-7.dsl` and `-1729.dsl`, the
  arranger's own solo shape over its first minor chart. The engine goldens are per briefing,
  not per form, which is why a change to the form costs nothing there.
- **The live prompt is byte-identical**, checked by comparing `SYSTEM`, `SYSTEM_ARRANGED`,
  `SYSTEM_DENSE`, `SYSTEM_POSITIONS` and `SYSTEM_THEME` against `HEAD`. The only prompt change
  is four lines inside `SYSTEM_SONGWRITER`, which is bake-only: *"A solo section is the
  lead's."* No cassette moved, and the musical regression suite is green.
- Suite at **2440 passed, 27 skipped**; `ruff` and `mypy` clean over 198 source files.

### Heard

`uv run python scripts/bootstrap_set.py` → `session.toml: the Set matches.`, and
`uv run pytest -m live -q` → **27 passed** against the five-track Set, on 2026-09-23. Then one
jam on seed 5 in the key and feel of `Half light`, 19 sections, two solos at 1:20 and 2:32, and
his verdict:

> *"Gostei dos solos, acho que temos um bom ponto de partida"*

Criterion 2 is met. The run is in `bench/jam.jsonl`: 19 scene fires, **every one with a full
bar of slack**, both solos included.

**And a detour worth recording, because it nearly cost a stage.** His first report was *"Foi
interessante mas eu nao diria que foi smooth. as transições ficaram um pouco truncadas"* —
which reads exactly like the open Phase 5 complaint, and the obvious move was to take it as
Stage C's brief. The event log said otherwise: its last run was **seed 23 with no solo in it**,
written the evening before, and reconstructing the form proved it was Stage A's listening.
Nothing from that day existed. Asked, he said it was the sound of `pytest -m live` playing
fragments into the Set, and then ran the jam. **A verdict is about a specific run, and the
event log is what says which run it was** — that is what invariant 7 and the log are for, and
this is the first time either has been used to check a listening rather than a bug.

## 3. The fill, announced — and a plan line the record contradicted

Built on 2026-09-23, with no model and no network. Stage C of
[ADR-027](ADR-027-the-arrangement.md), against a complaint open since Phase 5: the fill is
*"divertida"*, and one day should arrive *"de uma forma mais integrada e suave"*
(`phase-5-findings.md` §10).

### The section's own fill now grows out of the bar before it

`Ending.FILL` was the identity: the engines already put `fill_for(tension)` in the last bar and
`compose` returned the score untouched. It now composes one bar — **the one before the fill**.

- **The snare leans in on the last beat**, on the offbeat eighths only: slot 14 under tension
  0.5, slots 10 and 14 over it. Indexed by tension for `FILLS`' own reason — a fill a quiet
  section plays quietly should be announced quietly.
- **The hats stop for that beat.** The fill bar has no hats at all, so this is that gesture a
  beat early: the hats lift off, and the fill is heard coming.
- **Offbeats only, and never a downbeat**, which is how the module's promises stay true by
  construction here too: nothing on a beat is removed, no kick is added or moved, so kick
  spacing and the root under a chord change cannot break. `validate` clean over every feel and
  tension.
- **Drums only.** A band that all lifted off together would be a break, not an announcement.

This is the half of §10's question that is answerable: *"whether it should grow out of the bar
before it"* — yes, and here, because a section is written whole. The pad's fill cue cannot have
it, and the reason is ADR-022 rather than taste: a cue costs a fire and never a write, so the
variant exists for **every** bar and there is no bar known to come before.

    bar 3 S  ....s.......s...  ->  ....s.......s.s.
    bar 3 H  h.h.h.h.h.h.h.h.  ->  h.h.h.h.h.h.....
    bar 4 S  ............s.s.      the fill, unchanged

One new golden, `verse-straight8-7-fill.dsl` — `FILL` joins the endings the golden files pin,
now that there is something to pin. **No existing golden moved**, and the only unit test that
broke was the one asserting `compose(score, FILL, …) is score`, which is exactly the assertion
this change is about.

### The plan said to build the crash on the return. The record says he declined it

ADR-027's Stage C reads: *"`land_bars` — written in Phase 4 and never used by the cue — puts a
crash on the bar the groove comes back in."* Written as a thing to build. `phase-4-findings.md`
§10 says otherwise, and it is worth quoting because it is a decision and not a note:

> **The crash is ambiguous.** It lifted the toms from second to first, but dropped the snare
> from third to fifth and the rising snare from fourth to sixth. One ranking by one listener
> cannot say the crash helps […]
>
> **Decision, Fabiano's: the fill cue becomes the run down the toms, without the crash** […]
> The crash stays an idea with a cost attached; **an audition between just those two options is
> how to settle it.**

So the crash was **left out by his own choice**, with the way to settle it named. Building it
because a plan sentence said so would be overriding a by-ear decision with a to-do list. And
the other half of the plan's sentence has a prior against it too: **`RISING` was the same "start
softer and climb" idea on the snare, and the blind audition ranked it below the fill it was
meant to improve** — fourth of six, and sixth with the crash.

**So the cue's entry and return are auditioned, not built.** `TOMS_RISING` joins `FillStyle` as
a *candidate* — the same slots, the same drums, entered at the groove's own level and climbing
above it, which is the only thing ADR-022 leaves a cue — and `scripts/audition_fills.py` grew a
second round:

| round | passages | what it asks |
| --- | --- | --- |
| `phase4` | 6 | Phase 4's, kept reachable so its ranking can be reproduced rather than only read |
| `phase7` | 4 | the fill it chose × (flat or rising) × (crash on the return or not) |

Four passages, ~80 s, blind, in a shuffled order, the key written to
`bench/audition-fills.json` and not printed until `--reveal`. Whatever wins becomes
`FILL_CUE_STYLE` and, if the crash wins, gets the two extra scenes and the second return step
it costs — a cost the Phase 4 finding already priced.

### Deviation from the plan, written down rather than waived

ADR-027 criterion 3 says *"the pad cue … changes only its entry and its return."* **It may end
up changing neither**, if the audition ranks the fill as it plays today first. That is the
criterion being met by asking the question it exists to ask, and the answer being "leave it" is
an answer. What would *not* meet it is building both and calling the plan the evidence.

The measurement also turned up something in the solo, and it is recorded here and **left
alone**: under a `BUILD` into a chorus, the solo's own last phrase is attenuated to 76 from 93
by the band's swell, and the lead is silent for the 2 beats before the handover. The soloist
ducking with the band is arguably wrong. Fabiano heard those exact two handovers and said
*"Gostei dos solos"*, so nothing is changed on a hypothesis against a verdict. It is written
here so it is not rediscovered.

### The audition, ranked on 2026-09-28: the cue does not change

Seed 51277, four passages, blind, `bench/audition-fills.jsonl` line 2. He ranked **1, 2, 4, 3**
before revealing:

| Rank | Passage | Option |
| --- | --- | --- |
| 1 | 1 | **the fill cue as it plays today** — toms, no crash |
| 2 | 2 | toms rising, crash on the return |
| 3 | 4 | toms rising from the groove's level |
| 4 | 3 | the fill cue, crash on the return |

**So the cue changes neither its entry nor its return, and the deviation written down above is
the one that happened.** `FILL_CUE_STYLE` stays `TOMS`. No new scenes, no second return step,
no velocity ramp. The two candidates cost nothing to keep in `FillStyle`, and a candidate that
lost is what makes the one that won a choice rather than a default.

**Rising has now been auditioned twice and never won.** Fourth of six on the snare in Phase 4,
second and third of four on the toms here. Twice is enough to stop proposing it.

### And the crash reversed itself, which closes a question rather than leaving it open

`phase-4-findings.md` §10 called the crash on the return *"ambiguous"* and named the way to
settle it: *"an audition between just those two options."* That has now happened, and the same
pair came out in the opposite order:

| | toms, no crash | toms, crash on the return |
| --- | --- | --- |
| Phase 4, seed 69374, 6 passages | 2nd | **1st** |
| Phase 7, seed 51277, 4 passages | **1st** | 4th — last |

**The passages were the same five bars, note for note**, and that was checked rather than
assumed: the audition's verse has the same form position, chart, `dyn`, tension and ending in
both phases; `engines/drums.py` and `engines/humanise.py` are untouched since the Phase 4
commit; `variants._toms`, `TOM_RUN`, `land_bars` and `_downbeat_kicks_and_crashes` are untouched;
and the only changes to `groove.py`, `bass.py`, `guitar.py` and `keys.py` in between are
**shuffle rows**, while this passage is straight eights. The fill bar and the return bar the ear
was given are identical in the two rounds.

What differed is the round: six distractors against four, different seeds, different order, and
sixteen days apart. That is enough to move a ranking by a place. It is not enough to move an
option from first to last.

**A preference that reverses between two blind listenings is a difference this ear does not
reliably hear** — which is what "ambiguous" meant in Phase 4, now with a second reading behind
it. The crash costs two more scenes and a second return step. It does not get them, and the
question is **closed** rather than open: a third audition would be asking a coin to agree with
itself.

*Counted honestly: one listener, one ranking per round, and the project's own rule is that a
rate over five is an anecdote. What this supports is "do not spend scenes on it", not "the crash
is inaudible".*

### Heard

One conducted jam on 2026-09-29: seed 5, halftime, 14 sections, 189 s, **eight announced fills**
of the section's own, and pad 2 struck three times — in a chorus, in a bridge and in a verse.
All three landed one bar after the strike; two returned by their own legato fire with
`late_bars` 0 and one by the section change, which is the known case for a strike in a
section's last bar. His verdict:

> *"A virada ficou mais integrada, achei bem melhor que a versão anterior"*

**Criterion 3 is met**, and it is met against the sentence it existed to answer, from
2026-09-17: *"A virada é divertida, talvez no futuro vamos ter que penssar em ela entrando de
uma forma mais integrada e suave"* (`phase-5-findings.md` §10). Open since Phase 5, closed in
one bar of composition and one blind audition that changed nothing.

One accident worth keeping: the first strike fell in the **last bar** of a chorus, so the
announcement the section had already written in the bar before it led into the *pad's* toms fill
rather than into its own. The run-up works for either, which is not something the design set out
to do — it falls out of the announcement living in the main clip and the cue living in a variant.

Suite at **2497 passed, 27 skipped**; `ruff` and `mypy` clean.

## 4. Stage D's question, answered before the call was made

Built on 2026-09-29. `scripts/probe_solo.py` asks the model for **one** solo section — ADR-027's
*ask first, build second*, written after two Phase 6 bakes were spent on defects in our own
notation that a $0.0073 call would have found.

It asks the model the bake would ask (`structural(catalog)`, not the catalogue's first, which is
four times the price), over a solo section the arranger would write, with a **real theme read off
`setlists/songwriter.json`** — the third Phase 6 bake already paid for it, so the variable under
test is the solo section and not the material above it. One call, ~$0.0141, no file written.

### `--fake` answered half of it for nothing, and the answer is worse than expected

The probe also writes the **floor's own solo** in the bake's notation and reads it back. That
costs nothing and it needs no model, and it is the sharper question: *can this spelling carry a
solo at all?*

    5 of 43 notes move when it is written as `deg:` and read back; 4 of those land outside the key
      bar 3 slot 3 over C: 78 -> 77   <-- outside the key
      bar 3 slot 9 over C: 78 -> 77   <-- outside the key
      bar 4 slot 11 over Bm: 72 -> 71
      bar 7 slot 3 over C: 78 -> 77   <-- outside the key
      bar 7 slot 9 over C: 78 -> 77   <-- outside the key

**A degree is of the bar's chord's implied scale, so a line that moves through the *key* asks for
notes the chord's scale cannot spell.** Over `C` in E minor there is no degree that means F#,
because C's implied scale is C major and has F. The serializer writes the nearest degree it can,
and F# becomes F — a note in neither the key nor the chart.

**And the loss is silent.** The round trip still validates: four notes out of forty-three is
1.6% of nothing against a dissonance budget of `0.05 + 0.45 × 0.65 = 0.34` at a solo's tension,
so nothing refuses it and nothing repairs it. A notation that dropped notes loudly would be a
smaller problem than one that bends them quietly.

This was found by writing a test that asserted the round trip was **exact** and watching it fail
— the same way `_in_the_chord` was found in Phase 6, and for the same underlying reason: a degree
relative to a chord is not a degree relative to a key, and every time this project has forgotten
that it has cost a wrong note.

### What it does not yet answer

Whether **the model** needs `rel=key` is still open, and it is the question the cent buys: if it
writes bar-shaped figures that never cross a bar line, chord-relative degrees are all it is using
and a scale-relative spelling buys its output nothing. The floor does not go through the notation
at all in a real performance — `play_section` hands the scheduler a score — so what the free half
proves is about the notation's reach and about `--fake`'s fidelity, not about a paid bake.

### The paid call, 2026-10-10: three defects, all silent, none of them `rel=key`

One call, **$0.0222**. The model wrote a lead in **8 of 8 bars**, reached for degrees 8 and 9 —
the octave and the ninth, trying to get above the chord — and the section validated with **0
violations before and after repair**. It can write a solo. What it cannot do is keep it in one
place, and the notation is why.

**1. It never moved `oct=`.** All eight lines are `oct=4`. `deg:1` means *this bar's chord root,
in octave 4*, and the chart's roots run E, D, C, B — so a figure that reads identically in
degrees lands in four different registers. The steps across the bar lines were

    the model   -2, -6, +11, -14, -2, -6, +4
    the floor   +7, +2,  -5,  -4, +7, +2, -5

and bar 3 ended on **C4 (60)**, which is inside the guitar's range (40–76) rather than above it.
The lead's whole reason for existing at 55–84 is to be heard over the band. The floor's own
serialization moves the octave — `4, 5, 5, 4, 4, 5, 5, 4` — for exactly this reason, and the
model had no way to know that from a prompt whose only example says `oct=4` twice.

**2. One note fell a semitone past the ceiling and took an octave off.** In bar 8's run of
sixteenths the model wrote `… 8, 9, 8 …` over a `Bm`. Degree 9 of `Bm` is MIDI **85**; the lead's
ceiling is **84**. `realise._inside` folded that one note an octave down, so a step became a
ten-semitone hole:

    wanted   71 74 78 83 85 83 78 74 …
    played   71 74 78 83 73 83 78 74 …

**3. All three are silent.** Nothing refused any of it: the pitch classes are the ones that were
written, every note is in the key, and the dissonance budget was never in question. A notation
that dropped notes loudly would be a smaller problem.

### What was fixed, and what was deliberately not

**Fixed, because it is ours:** `realise._lead` now places a bar's line **bodily** by octaves
instead of folding note by note, falling back to the old behaviour only for a bar wider than the
instrument. A bodily octave keeps every interval in the bar; folding one note destroys two —
which is the same call `engines/lead._in_range` already makes for the floor, for the same reason.
The whole suite passed unchanged, so nothing had been relying on the fold.

**Tried before built:** the register problem gets **one paragraph in `SYSTEM_SONGWRITER`** before
it gets new notation. The prompt's only `LED` example says `oct=4`, and
`phase-3-findings.md` §11 and `phase-6-findings.md` §7 are both about this model copying the
example it was given — once byte for byte. The paragraph states the rule, gives the per-bar
sequence for this very chart, and names the lead's range so there is room left at the top.
`rel=key` stays unbuilt until a second probe says a sentence was not enough.

**And a block changed by accident, which is why the live prompt is now pinned.** The example edit
I first made was a bare string replace, and the same two lines appear in `SYSTEM_THEME`: it
changed a second block in silence. An ad-hoc comparison against `HEAD` caught it, nothing else
would have, and ADR-025's freeze had been held for four phases by care alone. The example edit
was reverted — it taught nothing, since the example's only sounding bar is one chord — and
`test_the_live_prompt_has_not_moved_since_adr_025_froze_it` now pins `SYSTEM`, `SYSTEM_ARRANGED`,
`SYSTEM_DENSE` and `SYSTEM_POSITIONS` by digest, with a second test that fails if a block is
added to `system_for` and not to the table. Checked non-vacuous: one added space fails three of
the four. `SYSTEM_THEME` and `SYSTEM_SONGWRITER` are deliberately outside it — they are bake-only
and this phase changes them on purpose.

### Cost, which criterion 5 will need

**$0.0222 for one solo section against $0.0141 estimated — 57% over.** The estimate uses the
*median* section of the third Phase 6 bake, and that bake's sections were mostly verses and
choruses while a solo writes a degree per sixteenth. `ONE_SECTION` is left at the median on
purpose, because it is the bake's own figure and the two should not drift apart; the overrun is
carried into Stage E's estimate instead. At this rate a song with one solo section costs about
**$0.10**, which is inside the $0.10–0.12 ADR-027 declared, and the $1.00 cap is untouched.

### The second call, $0.0220: the paragraph worked, and that is how we know it is not enough

| | worst step across a bar line | mean |
| --- | --- | --- |
| probe 1, no paragraph | **14** | 6.43 |
| probe 2, with it | **10** | 5.00 |
| the floor, same briefing | 7 | 4.57 |

**It moved `oct=`, and on exactly the bars the paragraph named.** `4 4 5 4 4 4 5 4` — the two
`oct=5` bars are the two `C` bars, and the paragraph said *"over `| Em | D | C | Bm |` the same
figure wants oct=4, oct=4, oct=5, oct=4, because C's root is the lowest of the four."* It did
what it was told, to the letter.

**And then it reached for the eleventh.** Bars 4 and 8 are `deg:…=11` over a `Bm` at `oct=4`,
which is MIDI **88** against a ceiling of **84**:

    wanted   81 83 86 88 86 83 81 78 74 71
    played   69 71 74 76 74 71 69 66 62 59   <- the whole bar, moved by this phase's own fix

So the two remaining ±10 steps are **not** the chord re-rooting any more. They are the range fit
moving a bar bodily, because three of its notes do not fit — and the paragraph did tell it to
leave room at the top. Staying under the ceiling means knowing that degree 11 of `Bm` at `oct=4`
is 88, which is the chord root plus the octave plus the degree: **three variables combined, which
is exactly the arithmetic a sentence cannot make reliable.**

Two probes, 4.4 cents, and a clean verdict: the model follows the instruction it can follow and
fails the one that needs arithmetic. ADR-027 authorised `rel=key` *"only if the probe says so."*
It says so.

### `rel=key`, built

Additive, bake-only, and **`rel=chord` remains the default**, so every take on disk and every
hook keeps its meaning.

- `dsl/lines.py` — `LeadLine.relative`, parsed from `rel=`, `chord` or `key`, refused by name
  otherwise. `RELATIVE_TO` names both.
- `dsl/realise.py` — `_sounds` asks the section's scale instead of the bar's chord when
  `rel=key`, through the `scale_pitch` primitive Stage B already added for the floor.
- `dsl/serialize.py` — **whichever spelling says what it means.** A bar is written `rel=chord`
  while that is exact, and `rel=key` only when it is not. The floor's own solo now comes out as
  five chord-relative bars and three key-relative ones — and the three are precisely the `C` and
  `Bm` bars, the ones whose implied scale disagrees with E minor.
- `dsl/schema.py` — `SYSTEM_SONGWRITER` learns it, with the register paragraph rewritten around
  it: *"In a solo, write the LED line as `rel=key`… then oct= is one register for the whole solo
  and you do not have to change it."* The arithmetic is gone rather than explained.

**The measurement that opened this section closes it:**

    5 of 43 notes move      ->      0 of 43 notes move
    4 of them out of the key        0 out of the key

Two tests that asserted the loss now assert its absence; one of them said *"if this is ever empty
the notation stopped needing rel=key"*, and it did. **No golden file moved, no cassette moved,
and the four live blocks are byte-identical** — checked against `HEAD` and now pinned by digest.
Suite at **2521 passed, 27 skipped**.

### The third call, $0.0227: the model used it, and the number I had been quoting went the wrong way

**`rel=key` on all eight bars, `oct=4` on all eight, nothing clipped by the ceiling.** And the
line it wrote:

    the degree each bar starts on   1, 2, 3, 5, 1, 2, 3, 5
    steps across the bar lines      0, 0, 0, -8, -13, -9, 0

| | worst step | mean | bar lines where the phrase hands over on the same note |
| --- | --- | --- | --- |
| probe 1, `rel=chord`, no paragraph | 14 | 6.43 | **0 of 7** |
| probe 2, `rel=chord`, paragraph | **10** | 5.00 | **0 of 7** |
| probe 3, `rel=key` | 13 | 4.29 | **4 of 7** |
| the floor | 7 | 4.57 | 0 of 7 |

**The worst step got worse — 10 to 13 — and this is the most useful thing the stage produced.**
Had "worst step across a bar line" been a target, `rel=key` would now read as a regression and
would be reverted. Look at what the steps *are* instead: four of the seven are **zero**, where a
bar begins on the note the one before it ended on, and all three non-zero steps are downward.
That is a rising sequence — the same figure four times up the scale, each phrase handed to the
next — restated from the top, and then dropped back to start again. Probes 1 and 2 had **no**
bar line where a phrase connected; every step was the chord re-rooting under a figure. Probe 3's
large steps are the solo choosing to start a phrase lower.

So the number stopped measuring what it was a proxy for. It was a good diagnostic for *"the
notation is making the line jump arbitrarily"* and it is a bad one for *"the solo has phrase
structure"*. **ADR-019 is not a slogan here: a metric that disagrees with the thing it stands in
for is retired, not optimised.** It is reported as description from here and the ear decides at
Stage E.

What can still be said in numbers, and is worth saying: the solo spans 64–79, fifteen semitones,
the same width as the floor's 66–81; one register, as asked; `0` violations before and after
repair; and nothing was moved by the range fit, so what came back is what was written.

**Stage D is done.** Three calls, **$0.067** all told, and the shape of the spend is the point:
ADR-027's *ask first, build second* cost seven cents to settle a notation question that Phase 6
answered twice at $0.57 a time by baking first.

## 5. The bake writes solos, and criteria 4 and 5 are met

Baked on 2026-10-10 by `claude-sonnet-5` into `setlists/arrangement.json`: the same three
songs, keys, feels and seeds as `songwriter.json`, so what differs is the arrangement and the
notation. **22 of 22 sections delivered, for $0.3384.**

### Criterion 4, measured. `n = 22` sections across 3 songs

| | | |
|---|---|---|
| Conformant on the first pass | **22 of 22 = 100%** | met, against ≥90% |
| Approved by the validator without repair | **22 of 22 = 100%** | met, against ≥80% |

**The same bar as ADR-026**, which is the point: it was met at 100% there and lowering it to
accommodate a new section kind would have been a metric moved. The first songwriter bake came
in at 89% conformant and the parser defect behind it was fixed without crediting the rate
(`phase-6-findings.md` §5); this is the first bake in the project's history with nothing to
excuse.

Beside them, as description and never as a target (ADR-019):

- **both solo sections carry the lead in 8 of 8 bars** — the figure ADR-027 named;
- all **22 of 22** sections carry a lead line, against 9 of 9 choruses in Phase 6;
- the lead sounds in **98 of 176** bars, so it still rests about half the time;
- **16 LED lines are written `rel=key`, and all 16 are in the two solos.** The prompt says
  *"outside a solo, leave rel= out: a hook belongs to its chord"*, and there is not one
  exception in 22 sections. The spelling went exactly where it was built to go.

### Criterion 5, met: $0.3384 against $0.33 estimated

**2.5% over**, which is the closest an estimate has come in this project — Phase 6's first bake
was 17% over and the solo probe 57%. The estimate is the same `SONGWRITER_USAGE` median, and it
holds across a bake because only 2 of 22 sections are solos: the probe's 57% overrun was one
solo measured alone.

**$0.113 a song**, inside the $0.10–0.12 ADR-027 declared before anything was spent, and the
$1.00 cap is unchanged and untouched. **Phase 7 has spent $0.405 in total**: $0.067 on three
probes and $0.338 on the bake.

### Heard and curated, 2026-10-10

Two sessions from this bake, played with the MiniLab. His verdict:

> *"Achei ambos os solos muito bons. A song 1 em especial estava bem agradável e com um ótimo
> groove"*

**He struck KEEP six times, and two of them are the two solos.** `Swing low`'s solo at section
3 and `Seven`'s at section 14, beside three choruses. Nothing was vetoed. Written into the
setlist by `curate_setlist.py`, which also skipped ten older keeps as *"on a take no longer
here"* — correctly, and that is checked below.

Criterion 6 is met: played, curated, and the verdict quoted.

`Half light` has no solo, because the arranger's walk gave it none. Forcing one would have been
arranging the evidence.

## 6. `--out` gave two setlists the same name, and the log could not tell them apart

Found while curating, and it is the kind of defect that looks like nothing until it costs a
curation.

**A setlist's `name` is its identity in the event log, not a label.** `jam.py` writes it with
every mark and `curate_setlist.py` joins marks to takes by it. `setlists/songwriter.toml` says
so in its own header, as the reason it has a name of its own:

> *"A separate name, not a second bake of `first`, so the event log can tell a session of one
> from a session of the other and `first.json`'s curation is never at risk."*

Baking `songwriter.toml` into `arrangement.json` with `--out` produced **a second setlist called
`songwriter`**, so the log's marks from Phase 6's sessions and from these were indistinguishable
by name. `curate_setlist.py setlists/arrangement.json` reported ten of them as *"on a take no
longer here"* — which it got right, and the reason it got it right is the second guard, not the
first: takes are matched on their **body**, and **0 of 22 take bodies coincide between the two
bakes**. Checked, because a curation that happened to be correct is not the same as one that had
to be.

Two guards, one of them broken by a flag. **`_named_after` now names a setlist after the file it
lands in**, whatever the spec called it — the file is what a person passes to `jam.py`, so the
file is what the name follows. `--fake` keeps the name it stands in for, since
`<name>.fake.json` exists to rehearse the real thing's playback and is the same setlist.

`arrangement.json` keeps the name it was baked and played under. Renaming it now would orphan
its own six marks in the log, which is worse than a collision with a Phase 6 file nobody is
going to replay.

## 7. Criterion 7: nothing regressed

- **The four live blocks are byte-identical to the Phase 6 close** (`aedc33e`), checked block by
  block, and now pinned by digest so the next phase does not hold the freeze by care alone.
- **No cassette changed.** `git diff aedc33e HEAD -- cassettes/` is empty.
- **The musical regression suite is green**: 35 passed.
- **No golden file moved.** ADR-027 allowed for the arranger's own goldens to move deliberately,
  with the diff read before it was kept. In the event **three were added and none changed** —
  `solo-straight8-7.dsl`, `solo-straight8-1729.dsl` and `verse-straight8-7-fill.dsl`, 586 lines
  inserted and 0 removed. The engine goldens are per briefing rather than per form, which is why
  a phase that rewrote every song's form cost them nothing.
