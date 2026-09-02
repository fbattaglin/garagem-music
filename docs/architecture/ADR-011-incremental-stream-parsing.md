# ADR-011 — Incremental stream parsing: progressive parsing, atomic publication

Status: **accepted** · Date: 2026-08-30 · Written for Phase 3; listed as **New** in
ADR-000's decision table since Iteration 2. Depends on ADR-009 (tool use with a strict
schema) and ADR-002 (the compact symbolic DSL).

## Context

A section arrives from the model as fragments of a JSON tool input. ADR-000 §4.3 says
what to do with them:

> Since the output is a line-by-line DSL, the stream can be **parsed incrementally**:
> drums and bass usually arrive before guitar and keys. With an incremental parser, the
> first two parts can already be validated and written into the clip while the rest is
> still being generated. That halves effective latency and gives an elegant degradation
> path: if the stream is cut short, write what arrived and complete the rest locally.

Four facts about the ground this stands on, three of them measured rather than assumed:

- **The emission order is mandatory and it is what makes any of this decidable.**
  `SEC → CHD → DRM → BAS → GTR → KEY` is rhythmic priority
  (`.claude/skills/garagem-dsl`). Because it is fixed, a line for a later instrument is
  proof that an earlier one is finished. Without the order there is no moment at which
  drums are known to be complete except the end of the stream, and the whole idea
  collapses.
- **Anthropic streams the tool input in 45 fragments for one 8-bar section; Gemini 3.6
  Flash sends it in a single fragment.** Counted in `cassettes/anthropic_section.jsonl`
  and `cassettes/google_section_flash.jsonl`. So incremental parsing is worth real
  latency on one provider and exactly nothing on another, and the parser has to be
  correct for both without knowing which it is talking to.
- **The infrastructure was built for this two phases ago.** `llm/port.py`'s
  `ToolInputDelta` carries the docstring *"This is what lets the incremental parser write
  drums and bass into the ScoreBuffer while guitar and keys are still being generated."*
  It has been waiting since Phase 0.
- **The fragments are not JSON.** A fragment is a slice of a UTF-8 byte stream that will
  eventually be JSON. `json.loads` cannot help until the closing brace arrives, which is
  the exact moment at which incremental parsing has stopped being useful.

And one constraint that pulls the other way: `ScoreBuffer` holds a frozen `SectionScore`,
and `transport/scheduler.py` may `take` one at any moment from another thread.

## Decision

**Parse progressively. Publish atomically.**

Three layers, each testable alone, each with one job:

1. **`dsl/fragments.py` — a partial-JSON string decoder.** Accumulates fragments and
   yields the decoded characters of the `dsl` field so far. It knows about escapes and
   nothing else. Hand-rolled: the input is one object with one string field, and a
   streaming JSON dependency would be a large answer to a small question in a project
   that is deliberately lean.
2. **`dsl/lines.py` — text to typed values, one complete line at a time.** A partial line
   is never parsed and never guessed at. Every refusal is a `Violation` naming the line,
   because those refusals *are* the schema-conformance rate the phase is measured on.
3. **`dsl/stream.py` — the assembler.** Feeds events in, reports which instruments have
   become complete, accumulates violations rather than raising, and hands over a whole
   `ParsedSection` at the end.

**The section is offered to the `ScoreBuffer` once, complete.** Parsing is incremental;
publication is not. The latency that §4.3 promises is real and is paid to the *producer*,
which can start realising drums and bass while keys is still arriving — not to the
scheduler, which must never see a section grow after it has read it.

A stream that stops early yields the parts that arrived. The rest is the deterministic
engine's, which is P2 and costs nothing extra: `engines.band.play_section` is already the
scheduler's fallback for a section that never arrived at all.

## Rejected alternatives

**Wait for the whole tool input, then parse.** Correct, simple, and about four seconds
of dead time per section on the provider that actually streams. It also throws away the
degradation path: a truncated stream becomes a total loss instead of a partial section,
and §4.3's "write what arrived and complete the rest locally" stops being available. Kept
as the fallback shape of the code — the parser handles a single fragment identically —
but not as the design.

**A streaming JSON parser dependency** (`ijson`, `json-stream`). Handles the general case
of arbitrary nested documents arriving in pieces. We have one object with one string
field, whose shape we define ourselves in `ToolSchema`. The project rule is to ask before
adding a dependency and to stay lean; this is a case where the general tool is larger than
the problem, and its failure modes would be ours to learn.

**Publish each part into the buffer as it arrives** — offer a score with drums, then
replace it with drums+bass, and so on. Tempting, because it is the most literal reading of
"writing progressively into the Score Buffer", and wrong for a specific reason: the buffer
is the boundary between the cognitive clock and the musical one (invariant 1), and a score
that grows after publication is a score the scheduler can read half-written. The buffer's
whole claim — *"everything it holds is a frozen `SectionScore`, so a half-written section
cannot be observed"* — would become false. The latency saving is available inside the
producer without giving it up.

**Let the model define the section.** If the returned `SEC` line were treated as
authoritative, the parser would be simpler: no comparison, no `section_mismatch`
violation. But the section is the *briefing* — the scheduler has already sized the clip
and computed the boundary from it. A model that returned `bars=16` for a section the
transport is playing as 8 would not be creative, it would be a write into a clip of the
wrong length. The briefing wins, and a disagreement is a violation to count.

## Consequences

- **The decoder must survive an escape split across a fragment boundary.** `\n` can arrive
  as `…\` and then `n…`. It must emit a newline and never a backslash, and it must emit
  nothing at all while it is holding half of one. This is the single most likely bug in
  the phase and it gets its own test file.
- **A single-fragment response must give a byte-identical result to a 45-fragment one.**
  Asserted directly, from the same source string fed both ways.
- **Violations accumulate; they do not raise.** The same rule `theory/validator.py`
  already follows, and for the same reason: the repairer needs to see all of them at once,
  and the event log needs a count rather than a first-failure.
- **`theory.validator.RULES` gains `section_mismatch`**, so a model disagreeing with its
  briefing is counted like any other broken rule instead of being special-cased.
- **The conformance rate becomes computable.** Every refusal in `dsl/lines.py` is a named
  violation on a numbered line, so "≥95% schema conformance on the first pass" is a
  division rather than an impression.
- **This ADR does not decide where the parser runs.** That is ADR-016: not in
  `transport/`, which may not import `llm/` at all.
