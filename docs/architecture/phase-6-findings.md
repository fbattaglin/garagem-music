# Phase 6 findings

## 1. The shuffle gets its own vocabulary

Built on 2026-09-17, with no model and no network. It is Stage A of
[ADR-026](ADR-026-the-songwriter.md), and the reason is Phase 5's closing verdict: *"A musica
número dois … foi sem dúvidas a menos interessante e mais mecanica delas"*
(`phase-5-findings.md` §13).

### What was wrong, in sound

Under a shuffle the whole band landed on the same eight attacks. The hats played the swung
eighths at every dynamic, the bass pulsed those same eighths, the guitar strummed them, and
straightening puts a model's take on them too. Nothing was left for anything to answer.

### What each player does now

| | Before | Now |
|---|---|---|
| Bass (`engines/bass.py`) | eighths | **the beats**, `x...x...x...x...` |
| Guitar (`engines/guitar.py`) | eighths | **the swung offbeats**, `..x...x...x...x.` |
| Keys, stabbing (`engines/keys.py`) | quarters | **the backbeat**, with the snare |
| Drums (`engines/groove.py`) | unchanged | unchanged, except the loudest kick |

**In sound:** the bass walks on the beat, the guitar chops the late half of each beat, the keys
punch with the snare, and the hats keep both halves. Four players, four places.

**The loudest shuffle's kick moved onto the swung eighths.** It was `1,4,7,9,12,15` — two kicks
a bar *between* them, the same three-by-three push the model wrote on its hat and that
straightening exists to remove (`phase-5-findings.md` §2). It is now `1,3,7,9,11,15`. That was
the one place the floor contradicted its own shuffle, and nobody is known to have heard it: no
A/B pair reached dyn 5.

### What did not move

- Fills, stops, builds and the final chord: feel-independent, and approved by ear.
- Every other feel. `straight8`, `straight16` and `halftime` are untouched, and the property
  tests over them are unchanged.
- The bass's tension behaviour: the fifth still arrives above 0.35 and the walk above 0.65. Four
  attacks a bar is exactly `WALKING_MIN_ATTACKS`, so a high-tension shuffle still walks into the
  next chord.

### What it cost to check

- Two golden files regenerated, `verse-shuffle-7.dsl` and `verse-shuffle-1729.dsl`, and the diff
  read before it was kept: the bass drops from 32 notes to 16, the guitar moves onto the
  offbeats, and the drums are identical.
- `test_dsl_straighten.py` says the new truth: **the floor's shuffle is now a fixed point of
  straightening at every dynamic**, flat out included. That test used to carry the exception.
- Suite: **2243 passed, 27 skipped**; `ruff` and `mypy` clean.

### Heard

One shuffle jam, `jam.py --seconds 120 --feel shuffle --seed 11`, on 2026-09-17. Fabiano:

> *"Achei que teve muito mais alma. Muito bom."*

That closes the gate ADR-025 asks for: approved music was changed on the strength of one verdict,
and the change was heard before anything was built on top of it. **The floor's shuffle is
approved as it now stands**, and it is Phase 6's criterion 2.

Worth keeping beside the verdict: the bass went from eight attacks a bar to four, which was the
risk in the change, and nothing came back as thin.

## 2. The fifth voice

Built on 2026-09-17, with no model and no network. Stage B of
[ADR-026](ADR-026-the-songwriter.md), and the reason it comes before any model work is
that the songwriter needs a track to write a riff *on* — one that plays without a network
like every other voice (invariant 2).

### What the floor's lead plays

`engines/lead.py`, and almost all of it is restraint:

| | |
|---|---|
| **When** | Only at `dyn` 4 and up — a chorus, or a verse the density knob pushed there. |
| **Where** | The second half of every other bar, and never the last bar, which is the fill's. |
| **What** | One motif per section, chosen from a seeded table and played again on each answering bar with that bar's own chord. Degrees 1, 3 and 5 only. |
| **How high** | G3–C6, above the guitar and starting where the bass stops. |

**In sound:** the band states the bar, and in the second half of every other bar a clean
guitar answers with a three-note figure falling to the root. Over one arranged song that
is nine notes a chorus and nothing anywhere else. A chorus in D gets A–F♯–D; the same
shape on E gets B–G–E, so the hook transposes with the harmony instead of repeating a
pitch that stops fitting.

**Why so little.** ADR-026 says it: a floor lead that played everywhere would fight the
model's line rather than stand in for it. What is wanted here is a voice that is *present
and optional*, not a soloist.

### Optional by construction, and one bug that proved it

A Set with four tracks never receives the part: every writer maps instruments through
`session.toml`, so an instrument with no track is skipped. That was already true of the
scheduler. **It was not true of the stop pad.** The bar-cue readiness check compared the
tracks written against `TRACKS[STOP]` — the band's list — so on a four-track Set the stop
would have waited forever for a lead that could never be written, and the pad would have
gone dead rather than leadless. Readiness now counts the tracks the Set actually has
(`bar_cues._expected`), and two tests hold the line: a four-track Set still stops, and a
five-track Set stops the lead with the rest.

### What moved, and what did not

- **The notation did not move.** GARAGEM/0.1 still has four lines. `dsl.WIRE_INSTRUMENTS`
  is that list by name, `serialize_section` writes it, and `parse_bar_line` refuses `LED`
  rather than half understanding it. The live prompt, its cassettes and the regression
  suite are untouched, which is what ADR-025's freeze requires.
- **Every golden file gained a `LED` block and nothing else.** The eleven engine goldens:
  17 lines added, 0 removed, 0 changed. The 29 musical-regression goldens changed by
  exactly one character run each — their digest — and stripping the new `LED notes=0`
  block from the rendering reproduces the old digest in **29 of 29**. No note, onset or
  velocity moved. This is the deviation from criterion 6's letter, stated here rather
  than smoothed over: the criterion said only the shuffle's goldens would move, and a
  fifth voice moves every file that enumerates the band.
- **The Set report now names the preset to load.** It used to say "drop Drift on it",
  which has been wrong since ADR-025 gave the band its own instruments. It now reads the
  instrument out of `session.toml` — and it is what Fabiano reads while adding track 4.
- Suite: **2281 passed, 27 skipped**; `ruff` and `mypy` clean.

### Heard

Track 4 went into `garagem-band.als` with *Guitar Electric Clean* on it, and
`bootstrap_set.py` reported **"the Set matches"** against the five-track spec. Fabiano
then played the same shuffle jam as Stage A, now with the lead in it:

> *"Acho que ela está de bom gosto e adiciona uma cor. Talvez no futuro podemos explorar a
> possibilidade de ela ser mais do que isso."*

**The floor's lead is approved as it stands, and as what it is: colour.** That is the
restraint it was built with, and it landed.

Criterion 1 is met with that: five parts in the property tests, `bootstrap_set.py` clean
against the five-track Set, `pytest -m live -q` at **27 passed**, and a four-track Set
still playing.

**The wish is this phase's own next step, not a new open item.** "More than that" is a
lead that carries a hook the song comes back to — which is exactly what Stage D asks the
model for: a theme per song, then each section written with that theme in hand. The
floor's lead stays sparse on purpose, because it plays underneath and instead of the
model's. If, after a song from the songwriter, he still wants more from the *floor's*
lead, that is a separate finding and the table in `engines/lead.py` is where it goes.

## 3. The notation learns to name notes

Built on 2026-09-17, with no model and no network. Stage C of
[ADR-026](ADR-026-the-songwriter.md). It is the stage that removes the reason the A/B came
out at parity: **in GARAGEM/0.1 the model cannot name a pitch.** `BAS deg=1` is one degree
for a whole bar, there is no line for a lead, and what is left to choose is which of
sixteen slots to strike — out of the floor's own vocabulary.

### What the bake can write that the live prompt cannot

    BAS oct=2 deg:1=1,5=5,9=7,13=1       a degree per struck slot: a line that moves
    LED oct=4 deg:9=5,11=3,13=1 hold=13  the fifth voice; hold= rings to the next attack
    LED oct=4 deg:                       a bar the lead sits out, which is most of them

The struck slots **are** the keys of the map, so one field carries the rhythm and the
pitch and there is no second spelling of the bar to disagree with it. Writing `deg:` and
`rhy:` together is refused rather than resolved, the way a fifteen-character grid is.

**`deg=` and `deg:` are told apart by the separator**, which used to be noise: the parser
split fields on `=` first, and a degree map's values contain `=`, so `deg:1=1,5=5` read as
the key `deg:1`. Splitting on whichever separator comes first fixes it and moves nothing
older — every GARAGEM/0.1 field holds exactly one separator.

### The live notation did not move, and that is the load-bearing part

- `serialize_section` writes GARAGEM/0.1 unless it is handed `pitched=True`. Every
  cassette, every golden file and every prompt example is in that dialect, and a
  serializer that quietly started writing more would move all three at once. **No golden
  file changed in this stage.**
- The parser reads the superset. Reading more than we write is exactly what lets a bake
  carry a lead while the live request stays byte-identical.
- **Truncation is now measured against the four voices the notation asks for, not the five
  the band has.** `LED` is optional even in a bake — a section whose lead rests has no line
  to write — and counting it would have marked every live take truncated overnight and
  every leadless bake a fallback. The tests that caught it: `test_llm_baked` and
  `test_dsl_stream`.

### It found a bug in the floor's own lead

The bake notation's round-trip property — five parts out, five parts back, still valid —
failed on a briefing nobody would have thought to write by hand: `C5` under C dorian, at
tension 0. **50% of the section's lead notes outside the key, against a 5% budget.**

The round trip was faithful; the floor was wrong. A power chord has no third and a sus
chord has none either, and `degree_to_pitch` answers for them out of the chord's *implied
scale* — so degree 3 of `C5` is a major third that is in neither the chord nor the key.
`engines/keys.py` has guarded the same trap on a sus2 pad since Phase 2, for the same
stated reason: a floor that needs the repairer to be legal is a floor with a hole in it.

`engines/lead.py` now takes the root wherever the chord does not contain the degree the
motif names, and two parametrised tests hold it over every chord quality the DSL has.

### What it cost to check

- `tests/unit/test_dsl_pitched.py`, 22 tests: both bass forms, the lead line, eight named
  refusals, what it realises, how it straightens, and that the live dialect is unchanged.
- A new round-trip property over the superset, and the lead engine's own no-third tests.
- Suite: **2323 passed, 27 skipped**; `ruff` and `mypy` clean; no golden file moved.

### Unheard, and nothing to hear yet

Nothing in this stage changes what plays: the floor writes no `deg:` lines and no model
has been asked for one. Stage D is what asks.

## 4. The songwriter: a theme, then the sections

Built on 2026-09-17. Stage D of [ADR-026](ADR-026-the-songwriter.md), and the first stage
that can spend money — it has not yet.

### What the bake asks now

Two questions per song instead of one per section:

1. **`write_theme`**, once: *write this song's material — a bass riff and a lead hook, two
   to four bars, in the notation.* No `SEC`, no `CHD`: material, not a section.
2. **`write_section`**, per distinct briefing, with that material at the top of the
   message: *write these eight bars, arranged, using the material where it fits.*

That is what makes a song come back to something. Degrees are relative to each bar's
chord, so one riff transposes through the whole progression rather than being written out
per chord — which is also why the theme is short enough to paste into every call.

**The theme travels in the message, never in the system block.** The block is the cache
prefix (`Request.cache_system`), and a theme inside it would change per song and take the
hit rate to zero. Both new blocks — `SYSTEM_THEME` and `SYSTEM_SONGWRITER` — are whole
strings, for the reason `SYSTEM_ARRANGED` is whole: a prefix assembled from pieces moves
when any piece does.

**The live prompt did not move.** `SYSTEM`, `SYSTEM_ARRANGED`, `SYSTEM_DENSE`,
`SYSTEM_POSITIONS` and `brief()` are untouched, the cassettes still match, and
`--plain` and `--rebake-vetoed` still send the live request.

### The one retry, and where it is allowed

P7 forbids a retry **on the critical path**, where a second call costs the bar it was for.
A bake is planning and nothing is sounding, so a refused section is asked once more and the
log says `(asked twice)`. A budget or breaker refusal is never retried: that is the system
saying stop, not the model having a bad moment.

**That guard was wrong when first written, and its own test caught it.** `shoot` stores
`type(error).__name__`, and what actually arrives is a subclass — a budget refusal is a
`SessionBudgetExceededError`, never a bare `BudgetError`. A set of base names would have
matched nothing and retried the one thing that must not be retried. The set is now built by
walking the hierarchies.

### What it cost to check, with no network

`--fake` bakes the floor's own DSL through **both** stages, in the bake's own notation, so
the whole path is exercised before a penny is spent:

    3 songs, 10.9 minutes at 132 BPM, 48 sections: 21 calls (3 themes, 18 sections)
    song 1 theme   4 bar lines
    song 1 section  2/16 verse   delivered
    ...
    18 of 18 delivered; spent $0.0000

Every take came back with `BAS,DRM,GTR,KEY,LED`, its per-slot bass and its `LED` lines
parsed, realised and matched its stored digest.

### The cost, written down before anything is spent

ADR-026's criterion 4 asks for the estimate first, so here it is, for the three-song
setlist at `claude-sonnet-5`:

    expected ~$0.24 at the usage ADR-026 estimated, which is not yet measured;
    at most ~$1.81 if every call filled max_tokens; capped at $1.00

About **$0.08 a song**, inside the $0.10–0.15 ADR-026 predicted. The per-section figure is
an estimate and the code says so where it is written: 900 tokens in, 1000 out, from the
shape of the answer (five instruments × eight bars) and not from a measurement. The
pessimistic bound is above the cap, which is the cap working — a runaway bake stops rather
than finishing.

### Left out, and named rather than dropped quietly

**`--takes N`** — asking for several takes of one briefing — is in the Phase 6 plan and is
not built. Nothing consumes a second take: ADR-024 §4 rules out A/B at section level,
`answers()` keys one take per briefing, and curation marks a take rather than choosing
between two. Building the knob now would mean building the chooser too, for a comparison
nobody has asked to make. It is one line of plan to reinstate when something needs it.

### Unheard, and the next step spends money

Nothing has been asked of a model yet. Stage E is one paid bake of one song, played and
curated, and its verdict is criterion 5.

## 5. The first paid bake, and the two things it says

Baked on 2026-09-17 by `claude-sonnet-5`, into `setlists/songwriter.json`: the same three
songs as `first.json`, same keys, same feels, same seeds, so the forms are identical and
the only thing that differs is who wrote the material. **18 of 18 sections delivered, for
$0.2808.**

### Criterion 3, measured. One of its two rates is not met.

| | | |
|---|---|---|
| Conformant on the first pass | **16 of 18 = 89%** | **not met**, against ≥90% |
| Approved by the validator without repair | **18 of 18 = 100%** | met, against ≥80% |

Beside them, as description and never as a target (ADR-019):

- the bass moves inside the bar in **18 of 18** takes — the thing GARAGEM/0.1 could not say;
- **9 of 9** choruses carry a lead line;
- the lead sounds in **70 of 144** bars, so it rests about half the time.

Median usage 425 tokens in, 1286 out. **Spent $0.2808 against an estimate of $0.24** — 17%
over, because the sections are longer than the 1000 output tokens ADR-026 guessed. The
estimate is now a measurement and the constant should say so before the next bake.

### Both misses are the same defect, and the notation has the answer already

    KEY voi=sus2 rhy:
    DRM K:1,7,9,12 S:1,5,9,11,12,13,14,15,16 H:

The model means *this voice is silent this bar*, and in the positions spelling an empty
list says exactly that and nothing else. The parser refuses it, because `_grid("")` routes
an empty value to the grid reader, which counts zero characters and asks for sixteen.

**This is not the ambiguity P4 exists to refuse.** A fifteen-character grid is ambiguous —
which slot went missing cannot be recovered — and is rightly refused. An empty *list* is
not: nothing was struck. The lead line ADR-026 added already spells a rest that way, on
purpose (`LED oct=4 deg:`), so the notation contradicts itself between two lines written a
day apart.

**The fix is not credited to this bake.** The rate was pre-registered at ≥90% and it came
back at 89%; changing the parser after reading the number and then calling the criterion
met is the exact move this project's discipline exists to prevent. The change is made
deliberately, and it is measured on the *next* bake, whose `n` is stated as its own.

### The theme prompt failed, and it failed in a way this project has already measured once

Two of the three themes are **byte-identical to the example in `SYSTEM_THEME`**, and the
third differs in five slots of the bass. Three songs, three feels, three keys — one riff
and one hook between them.

`phase-3-findings.md` §11 found the same thing and stated it as a rule: **an instruction
that contradicts its example loses to the example.** The correction then was to make the
example *be* the thing asked for. Here that correction is the defect: the example is a
complete, valid, plausible answer, so returning it is both the cheapest move and a correct
one. Nothing in the prompt makes a copy wrong.

It is worth naming precisely what this does and does not show. It does **not** show that
the model cannot write material. It shows that **we did not ask in a way that made copying
impossible**, and a bake that gives three songs one theme cannot be the evidence for
criterion 5 — every song would come back to the same hook, and the ear would be judging
one theme played three ways.

### Where this leaves the phase

Criterion 5 is not asked for yet: playing a setlist whose three songs share a hook would
spend a listening session on a prompt defect rather than on the songwriter. The bake stands
as evidence and as a working end-to-end path — 18 of 18, five voices, pitched material,
inside budget — and the next bake is the one that answers criterion 3 and criterion 5.

## 6. Both defects fixed, and the cheap check that says so

### An empty voice is a bar of rests

`_grid("")` now returns a bar of rests instead of asking for sixteen characters. The
reversal is argued in `tests/unit/test_dsl_lines.py`, against the decision it overturns
("`K:` is as likely a dropped field as an intended rest"), on three grounds:

- **evidence** — both non-conformant sections of the paid bake were this and nothing else,
  in streams that were not truncated, with more lines arriving after them;
- **a hole in the notation** — in the positions spelling there was *no way* to say an
  instrument rests a bar. The grid form has sixteen dots; lines are positional, so the
  instrument cannot leave the line out. The `LED` line added the day before spells a rest
  exactly this way, so the notation contradicted itself;
- **refusing is the more expensive mistake** — a refused line does not cost that bar a
  rest, it costs the *line*, and `_for_bar` wraps another bar's line into its place, so
  every bar after it is wrong rather than one.

It is not the widening P4 refuses: a fifteen-character grid is ambiguous and stays refused;
an empty list is not.

**Not credited to the bake that exposed it.** The 89% stands as measured. The next bake's
rate is its own, with its own `n`.

### The theme prompt now shows two songs that are not yours

`SYSTEM_THEME` carries **two** contrasting examples, labelled as other songs, followed by
*"Neither of those is your song, and your material must not be either of them"*, and a line
on what each feel does to where the notes fall.

`--themes-only` asks for the first stage alone and prints it: **three calls, $0.0073, no
file written.** The theme is what every section of a song is written against, so a bad one
is paid for eighteen times over; a cent to read it first is the cheapest check in the phase.

Asked again with the new prompt, on the same three songs:

| song | bass | lead |
|---|---|---|
| Seven, straight8 | `1,3,5,7,9,11,13,15` with a flat seventh in it | enters off the beat, `8,10,12`, holding the root |
| Swing low, shuffle | `1,4,7,10,13,16` — three sixteenths apart | **rests bar 1**, answers in bar 2 |
| Half light, halftime | `1,9,12` — the bar left open | a long phrase from slot 5, holding at 11 |

Three songs, three riffs, three hooks, none of them either example, and degrees 6 and 7
appear where the old theme only ever used 1, 3 and 5.

**The shuffle theme is written the way a model writes a shuffle** — an attack every three
sixteenths, the same figure `phase-4-findings.md` §16 found on the hat and ADR-024's
straightening exists to remove. Straightening handles it, and Stage C's degree map travels
with it: `1,4,7,10,13,16` becomes `1,3,7,9,13,15` with each slot keeping its degree. That
is the first time the new notation and an old fix have met on real model output, and they
agree.

### The estimate is a measurement now

`SONGWRITER_USAGE` is the first bake's median, 425 tokens in and 1286 out, replacing the
900/1000 guess that came in 17% under. The estimate for the three-song setlist reads ~$0.27.

## 7. The second and third bakes: the notation was short of an octave

### What the second bake said

The rewritten theme prompt worked — three distinct themes — and the bake still came back
at **16 of 18 = 89%**, the same rate for a different reason, plus **one song's theme
missing entirely.** All three failures were one line form:

    LED oct=4 deg:1=1,3=3,5=5,7=8,9=7,11=5,12=3,13=1,14=3,15=5,16=7
                                ^^^

**Degree 8 — the octave.** The most ordinary thing a melody does, and the notation capped
degrees at 7. The cap was never a musical decision: `degree_to_pitch` takes 1..7 because a
scale has seven notes, and the line form inherited that number without anyone asking what
a *melody* needs. A musician counts past it — 8 is the root an octave up, 9 the ninth, 13
the thirteenth — and the model counted the way a musician does.

It cost song 2 its whole theme, because `theme_shot` drops a theme whose lines will not
parse, which is right: a bad theme is pasted into every section of the song and paid for
eighteen times.

**And the fallback could not say why.** `theme_shot` returned a bare string, so a missing
theme printed `missed` and nothing else; the diagnosis cost another call. It now returns
the reason and the bake prints it. A fallback that cannot name its reason cannot be fixed.

### The fix, and the test that caught its own bug

`TOP_DEGREE = DEGREES * 2`, and `realise._at_degree` does the division — the octave belongs
to the notation, not to `theory/`, which is right to say a scale has seven degrees.

While fixing it, `--themes-only` tripped
`test_every_script_that_streams_more_than_once_reuses_its_loop`: an `asyncio.run` inside a
`for`, which had already killed the adapter's HTTP client once in this session. The test
was written after the first time this happened and it caught the second.

### The third bake, which is the one that counts

`setlists/songwriter.json`, 2026-09-17, `claude-sonnet-5`, **$0.2817**.

| criterion 3 | | |
|---|---|---|
| Conformant on the first pass | **18 of 18 = 100%** | met, against ≥90% |
| Approved by the validator without repair | **18 of 18 = 100%** | met, against ≥80% |

Description, never a target (ADR-019): the bass moves inside the bar in **18 of 18**,
**9 of 9** choruses carry a lead line, the lead sounds in **66 of 144** bars, and **0**
takes drifted.

**Criterion 4 is met:** $0.2817 for three songs is **$0.094 a song**, inside ADR-026's
declared $0.10–0.15, against an estimate of ~$0.27 written before the bake — 4% under.

The three themes, each its own song, and the third reaching the octave the notation had
been refusing:

    Seven      BAS 1,3,5,7,9,11,13,15 · LED enters on 8, holds the fifth
    Swing low  BAS 1,4,7,10,13,16 · LED enters on 7, holds the fifth, rests bar 2
    Half light BAS 1,7,10 · LED 4=5,6=6,8=8 — the octave, held

**What the phase spent to get here: $0.855** over three bakes and one themes-only check.
Two of those bakes were paid for a defect each, and both defects were the notation's rather
than the model's. The themes-only check found the second one for $0.0073, which is the
lesson worth keeping: **ask for the cheap half first.**
