# ADR-024 — The model writes, Fabiano chooses

Status: **accepted** · Date: 2026-09-13 · Decided by Fabiano, written as the Phase 5 plan.
Answers the question ADR-023 opened. Amends ADR-000 §7's Phase 5 and ADR-021 §3. Partly
revisits an alternative ADR-023 rejected, and says so below.

## Context

ADR-023 closed Phase 4 at parity and opened Phase 5 with a question: **when is the model worth
calling at all?** Its criteria were to be written with Fabiano before anything was measured.

**What the evidence already says.**
- **Section for section, the floor matches the model.** Three blind A/B runs of the same design
  converged on 18 of 36.
- **The reasons repeat.** "Cleaner, less messy" went to the floor 5 of 5. "Less boring" went to
  the model 4 of 5.
- **Fabiano's ear has been consistent.** Three runs, the same answer, the same words. One
  listener is not the flaw here: the system is built for his taste (ADR-019).
- **What the model costs:** about $0.0035 a section, a network dependency, and failure modes the
  floor already covers inaudibly (the chaos test, `phase-4-findings.md` §14).

**What a first plan asked for.** The plan first drafted for this phase answered the question
with two dedicated listening tests:
- a blind audition of 19 model shuffle sections, as written and with the second swing taken out
  (about 25 minutes);
- a blind song-level pair: 12 three-minute songs, each played by the floor alone and by the
  floor with the model, a branch taken at 9 of 12 either way (about 80 minutes, two sittings).

With the sessions the phase needs anyway, that was about three hours of focused listening.

**Fabiano asked whether all of it was needed**, given that the sample is one listener. It is
not. The scarce resource is his listening time, and every vote carries noise: fatigue, the day,
a lean towards the second side heard (B was chosen in 9 of 12 pairs in §15). Many small tests
spend the scarce thing on noisy votes.

**Three findings from planning shape the decision** (`phase-5-findings.md` §1):
- the `jam.py` event log does not keep the model's DSL, so no live session's model material can
  be replayed or curated;
- the Wi-Fi-off criterion, as written, is already met by the floor, so it measures nothing;
- 19 recorded model shuffle sections have their DSL, not 11.

## Decision

**1. The routing is decided now: the model writes, Fabiano chooses.**
- **The floor stays the live default.** It already is: `jam.py` makes no call without
  `--generate`, and `--generate` stays available.
- **The model's material reaches the stage through baked setlists.** A setlist is generated
  online before the performance and played from disk.
- **Fabiano curates while he plays.** Pad 4 is KEEP and pad 7 is VETO. A strike marks the
  section sounding, and the terminal never shows who wrote it, so the curation is blind to
  authorship.
- **A vetoed take is baked again or dropped to the floor. A kept take is pinned. An unmarked
  take stays**, so he marks only what stands out.

**2. Curation answers "when is the model worth calling" in use, instead of in a lab test.** It
converges on the right outcome whichever way the truth lies:
- if the model is better, his KEEPs hold its takes;
- if it is messier, his VETOs remove them;
- at parity, the "less boring" takes stay and the "messy" ones go.

**KEEP and VETO counts per author are reported at the phase gate**, read from the logs. They are
telemetry and decide nothing further (ADR-019).

**3. The shuffle double swing is fixed as a defect, with a five-minute blind check.**
- **The mechanism is a defect, not a taste:** the system swings a shuffle for the model, the
  prompt never says so, and the model swings it again (`phase-4-findings.md` §16).
- **The fix is composition:** under a shuffle, `dsl/realise.py` moves the model's attacks off the
  eighths onto the eighths, the way `_lifted` composes density. The floor never passes through
  it, so the floor does not change. *Corrected before the check:* this line first said every
  floor section is a fixed point of it. The floor's loudest shuffle is not
  (`phase-5-findings.md` §2).
- **The check can stop it and claims nothing more.** Five pairs, as written against
  straightened, chosen and listed before listening. The fix is applied unless the as-written side
  is preferred in 4 or more of the 5.

**4. No further model-against-floor A/B, at section or song level.** The section A/B's record
stays in `STATUS.md`, not met twice, both times waived, its threshold of 8 of 12 unmoved.

**5. The six remaining macros are deferred out of Phase 5.** Brightness, syncopation,
harmonic_risk, humanize, arrangement_size and lead_activity are not in the exit criterion, and
each would need its own listening. Brightness is timbre, which is Phase 6's work. Knobs 3 to 8
stay free. KEEP/VETO stays in the phase, because the setlist depends on it.

**6. Phase 5's exit criteria are rewritten** (`STATUS.md`):
- **When the model is worth calling: decided and applied.** This ADR; the shuffle check run and
  its consequence applied; the setlist of the offline session curated with Fabiano's KEEP/VETO;
  the counts per author reported.
- **A 10-minute session driven only by the MiniLab and by voice**, read from the log and judged
  by ear.
- **A 10-minute session with the Wi-Fi off, played from the curated setlist.** A stated share of
  the sections played must come from the setlist's takes, with the number fixed before the
  session from an offline rehearsal, so the floor alone cannot meet it.

## Rejected alternatives

**The 12-song blind pair.** The cleanest answer on offer, and the most expensive: about 80
minutes over two sittings, with parity its likeliest outcome, and parity's branch was this
decision. Declined by Fabiano on 2026-09-13.

**The 19-pair shuffle audition, decided at 14 of 19.** Strong evidence for a fix that is cheap,
reversible and does not touch the floor. About 25 minutes where five buy the protection that
matters: a veto if the fix sounds worse. Declined by Fabiano on 2026-09-13.

**Keep the model live by default.** It costs little, and the floor covers its failures. It would
also put material heard as "messy" in front of the ear unfiltered. Three blind runs over two
phases have measured that as a wash.

**Another section-level A/B.** ADR-023: *"a fourth identical run would measure the same coin."*

## What this revisits, stated plainly

**ADR-023 rejected *"Make the floor the default now, and the model optional"***, reasoning that
*"deciding the routing before it is measured is what Phase 5 exists to avoid."* This decision is
close to that alternative, and it deserves the same suspicion ADR-019 asked for its own move.

- **What changed:** the measurement moves from a lab test to curation in use. It is not dropped.
  The same ear still decides which of the model's takes reach the stage, blind to who wrote them.
- **What is lost:** a clean, blind, pre-registered answer to *"should the model play live,
  unfiltered?"* That question is left open on purpose.
- **What does not move:** no threshold. The A/B's 8 of 12 stands as not met.

## Consequences

**Setlist Mode stops assuming the answer.** ADR-023 put the routing question ahead of Setlist
Mode because its offline case assumed the model is worth baking. With curation, the setlist holds
only the model material that survived Fabiano's ear.

**Fabiano's listening becomes mostly playing.** About five minutes of testing, then the sessions
the criteria ask for: playing baked songs while curating, and the two ten-minute sessions.

**The model's DSL must survive in every log.** Curating a live take needs the text the model
wrote, and the event log does not keep it (`phase-5-findings.md` §1). That is fixed first.

**The evidence for the model's worth is weaker than a blind pair, and gathered for free.** KEEP
and VETO are not paired: a section can be marked for what came before it. The counts are read as
telemetry, and the setlist itself is what they decide.

**Anthropic stays the provider for baking**, and `claude-sonnet-5` the structural model, by the
measurements in `agents/routing.py`. Nothing here re-opens the Google comparison.
