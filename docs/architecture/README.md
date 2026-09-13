# Architecture

- `ADR-000-baseline.md` — the Iteration 1 (v2.0) design document. Source of truth for
  principles, decisions and roadmap.
- `STATUS.md` — current phase and exit criteria. Updated when a phase gate is passed.
- Subsequent ADRs: one file per decision, `ADR-NNN-title.md`.
  - `ADR-001-clip-ahead-and-quantised-launch.md` — how generation becomes sound on time.
  - `ADR-011-incremental-stream-parsing.md` — progressive parsing, atomic publication.
  - `ADR-013-set-as-code-in-toml.md` — `session.toml`, validate-don't-create, Drift.
  - `ADR-014-osc-receive-loop.md` — one receive thread; supersedes `osc.py`'s "no thread".
  - `ADR-015-barclock-is-not-an-audio-clock.md` — what `realtime.md`'s "< 2 ms" means.
  - `ADR-016-the-producer-thread.md` — why `transport/` may not import `llm/`.
  - `ADR-017-composition-over-generation.md` — the model writes the groove, the engines
    write the form.
  - `ADR-018-the-ab-waiver.md` — the Phase 3 blind A/B, waived with its threshold intact.
  - `ADR-019-the-ear-is-the-instrument.md` — no metric is a target until one passes a
    pre-registered preference gate; arrangement work is judged by ear.
  - `ADR-020-endings-are-composed-over-the-score.md` — builds, stops and the final chord,
    composed over a finished section by the scheduler, whoever wrote the groove.
  - `ADR-021-the-minilab-joins-phase-4.md` — the MiniLab becomes Phase 4's tactical input;
    Setlist Mode and voice stay in Phase 5.
  - `ADR-022-a-cue-costs-a-fire-never-a-write.md` — how a cue lands on the next bar:
    pre-written candidates and legato variants, fired, never written at cue time.
  - `ADR-023-the-second-ab-waiver.md` — the Phase 4 blind A/B, waived at parity with its
    threshold intact; when the model is worth calling opens Phase 5.
- `phase-0-findings.md` … `phase-4-findings.md` — what the measurements and the
  integrations actually met, as opposed to what ADR-000 assumed.

ADR format: context, decision, rejected alternatives, consequences.
A reversed decision is not deleted — it is replaced by a new ADR that supersedes it.
