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
