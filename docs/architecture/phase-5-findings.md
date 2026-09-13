# Phase 5 findings

## 1. What planning the phase found

Found on 2026-09-13 while writing the Phase 5 plan with Fabiano, before anything was measured,
baked or heard. Each one shapes [ADR-024](ADR-024-the-model-writes-fabiano-chooses.md).

### The live event log does not keep what the model wrote

- **`section_parsed` records the briefing, the seed and the tokens, not the DSL.** The scheduler's
  `section_written` records the note count.
- **`bench/jam.jsonl` holds 3,307 events and 59 `section_parsed` rows, and none carries the DSL.**
- **So the model's material in every live session is gone.** The 12 sections the model wrote in
  Phase 4's paid eight-minute session (`phase-4-findings.md` §12) cannot be replayed, measured
  or curated.
- **It is the defect that cost Phase 3 its calibration set.** Phase 4 fixed it in
  `scripts/ab_section.py` ("Material survives", `STATUS.md`), and the live path was never
  checked.
- **Why it matters now:** ADR-024 has Fabiano curate the model's takes while he plays. A take
  whose text is lost cannot be kept. The fix comes before anything else in the phase.

### The Wi-Fi-off criterion is already met by the floor

- **ADR-000 §7 asks for** *"a 10-minute session with the Wi-Fi off using a pre-baked setlist"*.
- **`jam.py` without `--generate` already plays for as long as asked, with no network**, and has
  since Phase 2.
- **As written, the criterion cannot tell a setlist from the floor.** A session that baked
  nothing and played the floor for ten minutes would meet it.
- **Rewritten in ADR-024:** a stated share of the sections played must come from the setlist's
  takes, with the number fixed before the session from an offline rehearsal.

### 19 model shuffle sections have their DSL, not 11

`STATUS.md` counted 11 for the shuffle audition. Every model section recorded in the positions
notation was counted again:

| Source | Shuffle sections with DSL | Seeds |
|---|---|---|
| `bench/ab-phase4.jsonl` (the closing A/B) | 3 | in the log |
| `cassettes/regression/` (recorded 2026-09-13) | 8 | `set.json` |
| `bench/sections-positions.jsonl` (Phase 3's closing round) | 8 | the same draw as the regression set |

- **The last 8 are separate takes of the regression set's 8 shuffle briefings.** The same
  briefings were asked twice, a phase apart, and the model answered differently.
- **These are the 19 that §16 of `phase-4-findings.md` measured**, where 18 of 19 had a run of four
  or more attacks three sixteenths apart.
- **What changed because of it:** the planned audition of all 19 was declined as too much listening
  (ADR-024). The five-minute check picks its five pairs from these 19, before anything is heard.
