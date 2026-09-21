# ADR-027 — The arrangement: a solo section, relief in the form, and a fill that is announced

Status: **accepted** · Date: 2026-09-20 · Written as the Phase 7 plan, agreed with Fabiano
before anything is measured or baked. **Amends ADR-000 §7**, which left Phase 7 as
"Extensions" — Architecture C, a multimodal listening loop, the Groove Pool, jazz — and none
of those is this. Depends on ADR-020, ADR-022, ADR-025 and ADR-026.

## Context

Phase 6 closed with the songwriter working and heard. Its closing verdict named two things
and left a third standing:

- *"a música número três foi mais chatinha e repetitiva entre elas"* — and the cause is
  measured, and it is **not** the songwriter. `arranger.TRANSITIONS` makes a bridge rare, so
  once the walk is past one the song alternates verse-chorus for as long as it lasts. Song 3
  ran twelve sections that way; song 2, the one *not* called repetitive, ran five
  (`phase-6-findings.md` §8). `n` = 3, an anecdote with a cause in a table.
- *"a guitarra … tem potencial para muito mais no futuro. Como a possibilidade de fazer
  solos."* — the second time the lead has been asked to do more, the first time with a name.
- **The fill arrives bolted on** (`phase-5-findings.md` §10), open since Phase 5.

None of the three is about *what* the band plays. All three are about **where things go in
time**, which is exactly what Phase 6 did not touch: it gave the band material — a fifth
voice, a notation that can name pitches, a theme per song — and left the form alone.

## Decision

Taken by Fabiano on 2026-09-20, each from options put to him.

**1. The phase is the arrangement, and all three go in it.** Form, solo and fill.

**2. A solo lives in a section of its own** — a fifth kind in `arranger.SHAPES`, beside
intro, verse, chorus, bridge and outro. It is where a band puts a solo, and it breaks the
verse-chorus alternation by existing, so one change answers two of the three complaints. The
alternative — a solo played over a section that already exists — was declined: it would put
the solo against a chorus that is already the loudest thing in the song instead of giving it
the stage.

**3. The form gains a relief rule, not new weights.** After a run of sections that are only
verse and chorus, the next kind is forced to be something else. New weights would make a long
alternation *less likely*; a rule makes it impossible, and can be stated, tested and argued
with.

**4. The floor plays a solo too.** Invariant 2 is not suspended for a section kind: a solo
section must sound with the network off. The floor's solo may use the section's scale rather
than only the bar's chord — the dissonance budget already allows every pitch class of the key
— which is the same by-construction legality `engines/lead._in_the_chord` gives the hook.

**5. The live prompt still does not move.** ADR-025's freeze stands. Everything the model
learns here goes in the bake-only blocks, which is what keeps the cassettes, the musical
regression suite and its golden files valid. The live blocks have not changed since
2026-09-01, through Phases 4, 5 and 6.

## Exit criteria

Each rate states its `n`. A rate over five sections is an anecdote.

1. **No form alternates without relief.** A property over every seed the strategies generate:
   no run longer than `RELIEF_AFTER` sections of verse and chorus alone. And Fabiano's verdict
   on seed 23 — the song he heard as repetitive — recorded verbatim.
2. **The band has a solo section and plays it without a network.** `validate` clean over every
   briefing and seed with a solo in it, `pytest -m live` green, and the verdict on hearing one
   recorded verbatim.
3. **The fill is announced.** The section's own `FILL` ending carries a pickup in the bar
   before it; the pad cue keeps ADR-022 and changes only its entry and its return. Verdict
   verbatim from one conducted jam.
4. **The bake writes solos.** ≥90% of baked sections conformant on the first pass and ≥80%
   approved by the validator without repair, `n` stated — **the same bar as ADR-026**, because
   it was met at 100% and lowering it would be a metric moved. Beside them, as description and
   never as a target (ADR-019): the share of solo sections whose lead plays in every bar.
5. **Cost per song inside a declared budget**, estimated before the bake, and the bake's own
   cap unchanged.
6. **By ear:** one session from the new bake, played and curated, the verdict recorded
   verbatim.
7. **Nothing regresses.** The live prompt and its cassettes are untouched, the musical
   regression suite is green, and the golden files that move are the arranger's own,
   deliberately, with the diff read before it is kept.

## Rejected alternatives

**Put the solo inside a section that already exists.** Nothing approved would move and it is
reversible. But the solo would compete with a chorus rather than have the stage, and the
repetition complaint would stand untouched. Declined by Fabiano.

**Change the transition weights instead of adding a rule.** Simpler, and it answers a
complaint about one specific song with a probability. A rule can be stated in one sentence
and held by a property test over every seed.

**Give the fill cue a pickup in the bar before it.** Ruled out by ADR-022 rather than by
preference, and the constraint is worth writing down: *a cue costs a fire and never a write*,
so the fill variant is written ahead for **every** bar of the section — there is no "bar
before", because any bar may be the one the person strikes in. What is available to the cue is
how it starts and how it returns. The *section's own* ending fill has no such constraint: the
whole section is written at once, so it can be announced.

**Build the scale-relative notation before asking the model for a solo.** Phase 6's lesson,
and it cost $0.57 to learn: two paid bakes were spent on defects in our own notation that a
one-cent probe would have found. Ask first, build second.

## Consequences

**Every song the arranger writes from now on has a different form**, including the Phase 2
song approved by ear on 2026-08-30. Setlists are safe — a bake stores its form and plays what
was baked, so `first.json` and `songwriter.json` are untouched — and what changes is new
arrangements. That is why the solo stage ends in a listening.

**The floor grows a part that is hard to make good.** A deterministic solo is the most exposed
thing this system will have played: it is the one voice nothing else is covering, and a
mediocre hook hides in a band in a way a mediocre solo does not.

**`endings_for` gains a case and keeps its shape.** The step into the last chorus stays a
stop, whatever the solo does before it.

**The notation may not need to change at all**, and the phase is arranged so that question is
answered for a cent before anything is built.
