---
name: phase-gate
description: Checks the exit criteria of the current GARAGEM roadmap phase before moving on. Invoke with /phase-gate.
disable-model-invocation: true
---

# Phase gate

Check the current phase's exit criteria before declaring any phase complete.
The current phase is recorded in `docs/architecture/STATUS.md`.

Steps:

1. Read `docs/architecture/STATUS.md` and identify the current phase and its criteria.
2. For each criterion, find objective evidence: a passing test, a measured number, a
   generated file. **A criterion without verifiable evidence counts as unmet.**
3. Run the full suite and the linter.
4. Produce a table: criterion | evidence | met (yes/no).
5. If all pass, propose updating `STATUS.md` to the next phase and list its first
   three steps.
6. If any fails, **do not advance**. List what is missing, ordered by effort.

Project rule: no phase starts before the previous one passes in full.
A "nearly met" criterion is an unmet criterion.
