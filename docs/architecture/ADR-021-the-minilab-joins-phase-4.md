# ADR-021 — The MiniLab joins Phase 4; Phase 5 keeps Setlist Mode and voice

Status: **accepted** · Date: 2026-09-12 · Decided by Fabiano, written for Stage 1 of the
MiniLab plan. Amends ADR-000 §7's Phases 4 and 5. Depends on ADR-017 and ADR-020; its
mechanism is ADR-022. **§3's six macros are deferred out of Phase 5 by
[ADR-024](ADR-024-the-model-writes-fabiano-chooses.md)** on 2026-09-13.

## Context

Phase 4's remaining piece of design is the tactical layer: *a human cue takes effect
deterministically on the next bar while the model refines the next section* (`STATUS.md`,
from `phase-3-findings.md` §14). A cue has to come from somewhere, and ADR-000 §7 puts the
instrument that sends them — the MiniLab 3 — in Phase 5. The proposal on the table was an
intermediate step: the computer keyboard during `jam.py`, or a file of cues at given bars.

Fabiano asked whether to skip it and unify with Phase 5. Three things were weighed.

**The mechanism does not care where a cue comes from.** Getting a cue onto the next bar is
the hard part — a section write costs about a bar, so nothing a cue triggers can be written
when it arrives (ADR-022). The source is a port with a fake, the same shape as `DawPort` and
`FakeDawAdapter`. A keyboard adapter would be built, tested and thrown away.

**The gate for this work is a person with an instrument.** Phase 2's floor and Stage 2's
endings were approved by ear; cueing adds the hands. Whether a stop on a pad feels on time
is a question a keyboard cannot put to him.

**Phase 5 is three unrelated things.** The MiniLab, Setlist Mode — a repertoire generated
online and played offline — and a voice/MCP control plane. Merging all of it would stack
about eleven criteria on one gate. It would also hold Phase 4's cheap, independent criteria
(the 8-minute session, the chaos test, the cost check, the CI drift suite, the closing A/B)
hostage to two large pieces of work they have nothing to do with.

Stage 0 then removed the uncertainty that made going direct risky
(`phase-4-findings.md` §7). The real Set confirmed the launch semantics the design needs.
The real MiniLab sends everything on one port. Live acted on none of it.

## Decision

**1. The MiniLab 3 is the tactical layer's input in Phase 4, with no intermediate step.**
There is no keyboard adapter and no user-facing cue file. Scripted cues exist only in
tests, through a fake controller.

**2. Fabiano directs; he does not play along.** Pads send cues and knobs shape what comes
next. Playing notes that the band follows — ADR-000's Architecture C — is out of scope, and
recorded as a direction a later phase may take up.

**3. Phase 5 keeps** Setlist Mode, the voice/MCP control plane, KEEP/VETO curation, and the
six macros that Phase 4 does not take: brightness, syncopation, harmonic_risk, humanize,
arrangement_size and lead_activity. Phase 4 takes the two that already have a briefing
field: **tension** and **density** (`dyn`).

**4. Phase 4's exit criteria gain three lines**, unticked until evidence exists:

- A MiniLab cue takes effect on the next bar, read from the event log as
  `fired_bar − cue_bar = 1` for next-bar cues, over a session.
- After a jump cue, the section that follows is requested from the model with the
  re-planned briefing, and a stale section never plays.
- A session directed from the MiniLab is judged by ear, with the verdict recorded verbatim.

Phase 5's criterion — *a 10-minute session driven only by the MiniLab and by voice* — stays
as written. Its MiniLab half is delivered here; Phase 5 adds the voice.

**5. `mido` and `python-rtmidi` are the MIDI dependency**, approved by Fabiano. They are
confined to a new infrastructure package, `control/`, and to the probe script, and every
pure layer is forbidden to import them.

## Rejected alternatives

**A keyboard or cue-file step first.** Cheaper to start, and it tests nothing a person will
use. Everything it would have exercised — the queue between threads, the fires, the
re-plan — is exercised by the fake controller in the offline suite, where scripted cues
belong.

**Unify Phases 4 and 5 entirely.** Less ceremony, and a gate nobody could close for weeks.
Phase 2 and Phase 3 each closed on a list short enough to read; this would not.

**Leave the MiniLab in Phase 5 and build the tactical layer blind.** Phase 4's criterion is
about a human cue. Building the mechanism without the human's instrument would defer its
only real test to a later phase, which is exactly what ADR-018 found costly with the A/B.

## Consequences

**Phase 4 is longer.** Stages 2 to 5 add controller input, jump cues, bar cues and knobs,
each gated by ear and hand. The phase's other criteria wait for none of them, and Stage 6
runs them as MiniLab sessions rather than separately.

**Hardware enters the live tests.** `-m live` gains tests that need the MiniLab connected.
The default suite and CI stay hardware-free: every cue path runs against the fake.

**The Set gains a rule.** The KEYS track was found armed in Stage 0, and an armed track
plays the MiniLab's notes — a cue pad would sound inside the band. `session.toml` declares
the band's tracks disarmed, and the bootstrap enforces it.

**ADR-000 §7 is amended where it stands.** The roadmap keeps its text, and both phases point
here, as they already do for ADR-017 and ADR-019.

**What this does not decide.** How a cue becomes sound — that is ADR-022. Nor which pads do
what: the control map is data in `controller.toml`, chosen by ear.
