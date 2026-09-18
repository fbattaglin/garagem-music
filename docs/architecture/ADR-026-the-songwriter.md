# ADR-026 — The songwriter: a fifth voice, a notation with notes in it, and a theme per song

Status: **accepted** · Date: 2026-09-17 · Written as the Phase 6 plan, agreed with Fabiano
before anything is measured or baked. Realises [ADR-025](ADR-025-the-model-composes-offline.md)'s
Phase 6 and fills in ADR-000 §7's Phase 6, which it supersedes. Depends on ADR-011, ADR-017 and
ADR-024.

## Context

Phase 5 closed with no waiver, and with a verdict on its last session: *"A musica número dois
começou de forma bagunçada. Ela também foi sem dúvidas a menos interessante e mais mecanica
delas"* (`phase-5-findings.md` §13).

ADR-025 had already named the mechanism. **To fit a live 5.8 s deadline, the model's role had
narrowed until it picks one-bar rhythms out of the floor's own vocabulary:** the DSL lets it name
no pitch, the charts are the arranger's and the form is the engines'. Section for section, that
came out at parity over 36 blind pairs, which is what a shared vocabulary predicts.

**Offline, none of that constraint exists.** A bake has no deadline, can be retried, can ask for
several takes and can afford a bigger answer. What it has been missing is something to ask *for*.

Two findings of Phase 5 shape the phase:
- **the shuffle is where the floor has the least to play with:** the hats stay on eighths at
  every dynamic, the bass pulses eighths, the guitar strums them, and straightening puts the
  model's takes on the same eighths, so nothing syncopates;
- **the fill arrives bolted on** (§10), which is left open.

## Decision

Taken by Fabiano on 2026-09-17, each from options put to him.

**1. The band gains a fifth voice, `LEAD`.** Its own track, its own instrument and its own
deterministic engine, so it plays without a network like every other voice (invariant 2). It is
optional by construction: a Set with four tracks never receives the part, so the old Set, the
live tests and every bake already on disk keep working.

**2. The shuffle gets its own vocabulary first,** deterministically, before any model work. It is
the thing he has already asked for, it is cheap, and it improves the floor, which is what plays
live.

**3. The notation gains pitched material, for the bake only.** A degree per struck slot for the
bass and for the lead, as a superset of GARAGEM/0.1. **The live prompt does not move**, which is
what keeps the cassettes, the musical regression suite and its golden files valid, and what keeps
live generation frozen as ADR-025 requires.

**4. The model writes a theme, then sections.** One call writes the song's material — a riff, a
hook, the rhythmic idea — and each section is then written with that material in hand, one line
per bar. It is how a song gets something that comes back, and it is why the phase is not a
per-section prompt change.

**5. The ear decides on a whole song**, played and curated with KEEP and VETO. No A/B, at section
or song level: ADR-024 §4 stands.

## Exit criteria

Each rate states its `n`; a rate over five sections is an anecdote.

1. **The band has a fifth voice and plays it without a network.** The property tests hold with
   five parts, `bootstrap_set.py` exits 0 against the five-track Set, `pytest -m live` passes, and
   a four-track Set still plays.
2. **The shuffle has its own vocabulary,** and Fabiano's verdict on it is recorded verbatim.
3. **The bake writes pitched material.** ≥90% of baked sections conformant on the first pass and
   ≥80% approved by the validator without repair. Beside them, as description and never as a
   target (ADR-019): the share of sections whose bass moves inside the bar, and whose chorus
   carries a lead line.
4. **Cost per song inside a declared budget,** with the estimate written down before the bake and
   the bake's own cap unchanged.
5. **By ear:** one whole song from the songwriter, played and curated, the verdict recorded
   verbatim.
6. **Nothing regresses.** The live prompt and its cassettes are untouched, the musical regression
   suite is green, and the only golden files that move are the shuffle's, deliberately.

## Rejected alternatives

**Keep four voices and put the riffs in the bass and the guitar.** Cheaper, and it leaves the
song without a voice that carries a hook over the band. Declined by Fabiano.

**One call writes the whole song.** The most coherent answer and the largest: one refusal spoils
the song, and validating it is all-or-nothing. A theme plus sections keeps the take-per-briefing
format the setlist and curation already work in.

**A per-section prompt change, offline.** Safer, and nothing ties one section to another, so no
theme returns. That is the thing the phase exists to add.

**Fix the shuffle inside the model's material.** A riff would cover it, but the floor plays live
and plays every section the setlist does not hold; leaving its shuffle flat would leave the
default flat.

## Consequences

**The approved music changes for the first time since Phase 2 — deliberately, and with a
reason.** The shuffle tables were approved by ear; his verdict is the reason to move them, and a
short listen is the gate (ADR-025).

**The notation grows without the live path moving.** `dsl/` gains line forms that the live prompt
never asks for. That asymmetry is the point: one notation, two vocabularies, and the frozen half
is the one with cassettes against it.

**The floor gains a voice that can be wrong.** A lead that plays everywhere would fight the
model's, so the floor's rests more than it plays, and what it plays comes from the chord.

**The bake gets more expensive and stays cheap.** Per-bar output costs perhaps four times a
groove's, which is cents a song.
