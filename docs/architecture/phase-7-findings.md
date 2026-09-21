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

### Unheard

The rule changes the form of every song the arranger writes, which is approved music
changing, so ADR-025's light gate applies. The listening is one jam on seed 23 — the song he
named — and his words.
