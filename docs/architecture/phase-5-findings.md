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

## 2. The shuffle check, pre-registered

Written and committed before a single pair is played. Fabiano agreed its shape on
2026-09-13 in ADR-024: a five-minute blind check that can stop the fix and claims nothing
more.

### The fix

**In sound:** under a shuffle, the notes the model puts between the two pulses of each beat
are pulled back onto the pulse just before them. The swing is then the system's alone.

**In the notation:** `straightened` in `dsl/realise.py`, reached by
`realise(..., straighten=True)` and off by default.
- A sixteenth that is not an eighth moves one sixteenth earlier. The "e" joins its beat and
  the "a" joins its "and". No attack leaves its beat or its bar.
- Every part the model writes: kick, snare, hat, bass rhythm and ghosts, guitar and keys
  rhythms.
- Two attacks landing together are one. It keeps an accent if either had one, and is a ghost
  only if both were.
- The hat's lift (`_lifted`) could put an attack back between the eighths. Under the flag it
  cannot.
- The model's hat `1,4,7,10,13,16` becomes `1,3,7,9,13,15`.
- Other feels, and the arrangement's own fill and crash, are untouched.

**What it moves in each recorded take** (`scripts/audition_shuffle.py --table`): attacks between
the eighths, per distinct line the model wrote.

| Take | Section | BPM | Hat | Bass | Guitar | Total | |
|---|---|---|---|---|---|---|---|
| ab: pair 2 | verse | 110 | 2 | 0 | 2 | 4 | heard in the A/B |
| ab: pair 5 | chorus | 96 | 3 | 2 | 2 | 7 | heard in the A/B |
| ab: pair 10 | bridge | 132 | 3 | 2 | 3 | 8 | heard in the A/B |
| regression: 07 | chorus | 110 | 3 | 1 | 3 | 7 | **pair 2** |
| regression: 08 | verse | 132 | 3 | 0 | 3 | 6 | **pair 5** |
| regression: 09 | chorus | 96 | 3 | 0 | 3 | 6 | |
| regression: 10 | bridge | 150 | 3 | 1 | 2 | 6 | |
| regression: 23 | bridge | 110 | 3 | 0 | 3 | 6 | |
| regression: 24 | bridge | 132 | 3 | 0 | 3 | 6 | |
| regression: 25 | chorus | 96 | 3 | 2 | 3 | 8 | **pair 1** |
| regression: 26 | verse | 150 | 3 | 0 | 3 | 6 | |
| phase 3: 07 | chorus | 110 | 3 | 2 | 2 | 7 | |
| phase 3: 08 | verse | 132 | 3 | 0 | 3 | 6 | |
| phase 3: 09 | chorus | 96 | 3 | 0 | 3 | 6 | |
| phase 3: 10 | bridge | 150 | 3 | 1 | 3 | 7 | **pair 3** |
| phase 3: 23 | bridge | 110 | 0 | 0 | 0 | 0 | nothing to move |
| phase 3: 24 | bridge | 132 | 3 | 2 | 2 | 7 | **pair 4** |
| phase 3: 25 | chorus | 96 | 3 | 0 | 3 | 6 | |
| phase 3: 26 | verse | 150 | 3 | 0 | 3 | 6 | |

No take has an attack between the eighths on the kick, the snare or the keys.

### The choice of five, by a rule

1. **Not the three A/B takes.** Fabiano heard them today, and does not vote again on sections he
   has already heard, as in `phase-4-findings.md` §15.
2. **Most attacks moved first**, because a veto is only worth something where the fix changes the
   most.
3. **At most one take of a briefing, two pairs at one tempo, and two of one section kind.**
4. **Ties go to source order.**

The five cover all four tempos, with two choruses, two bridges and a verse.
`tests/unit/test_audition_shuffle.py` pins them, so a moved recording or a moved rule fails
before anyone listens.

### How it plays

- **Each side is what the producer would offer:** realised, completed from the floor where a
  part is missing, and repaired. Neither side gets an ending.
- **A, then B, once each and automatically.** Either can be heard again before voting, but
  nothing asks for it.
- **The order comes from seed 2026 and is not printed.** The straightened side plays first in
  three of the five pairs. The last A/B leaned towards the side heard second (B in 9 of 12), so
  here a lean can only help the take as written, which is what the veto protects.
- **Each pair plays at its section's own tempo.** Live is set to it before the pair, and the
  Set's 132 BPM is put back at the end (the next finding says why).
- **Log:** `bench/audition-shuffle.jsonl`. Every vote is stored with which side was which, the
  seed, the briefing and the DSL.

### What decides

- **The fix is applied unless the take as written is preferred in 4 or more of the 5 pairs.**
- **A skipped pair counts for neither side.** Skip only for a failure of the rig: a silent side,
  Live stalling, the sound cutting out.
- **If applied:**
  - the flag is on wherever a model take is realised: the producer, the regression replay, and
    every bake and playback after it;
  - the 8 shuffle golden files in `tests/regression/` are regenerated, and the commit says the
    diff is intended.
- **If not applied:** the flag stays off, and the mechanism in `phase-4-findings.md` §16 is
  recorded as not what the ear hears.

### How to listen

- **One question: which of the two would you rather hear in the song?**
- **Do not try to guess which side was changed.** If one seems recognisable, vote for the one
  preferred anyway.
- **The same headphones, and the volume left alone.**

### The command

Live open and stopped, in Terminal (not through `!`), about five minutes, no model call:

```
uv run python scripts/audition_shuffle.py
```

`--resume` continues a stopped run. `--tally` prints the result afterwards.

### Two things writing this found

**The floor has the same figure, in its loudest shuffle.**
- `engines/groove.py`'s "shuffle, flat out" groove, at dyn 5, has the kick at `1,4,7,9,12,15`:
  two kicks between the eighths, the three-by-three push the model writes on its hat.
- **In sound:** at the loudest shuffle, the floor's kick pushes the same way the model's hat
  does.
- **A shuffle song reaches it in its last chorus.** `with_climax` lifts that chorus from dyn 4
  to 5, as seeds 7, 1 and 2026 all show. A density knob turned up can reach it too.
- **Found by a property test**, which expected every floor shuffle to be a fixed point of the
  straightening and failed only at dyn 5.
- **Not acted on.** Straightening never touches the floor, and the floor's grooves were approved
  by ear. Whether this groove was ever heard is not known. No A/B pair reached dyn 5, and the
  jam logs do not record a song's feel; `jam.py`'s default is straight8.

**Every A/B pair played at the Set's tempo, 132 BPM.**
- `scripts/ab_section.py` writes both sides and plays each for as long as the section lasts at
  *its briefing's* tempo, but never sets Live's tempo. `diff_session` holds the Set at 132
  before listening. The script as imported at the Phase 3 gate did not set it either.
- **At 150 BPM** a side played for 12.8 s, about seven bars at 132, so its last bar, where the
  fill is, was cut off almost entirely.
- **At 96 and 110 BPM** it ran on for roughly three and two bars past its eighth.
- **What this does not change:** both sides of every pair were treated the same, so the votes
  stand as comparisons.
- **What it does change:** no pair away from 132 BPM was heard at its briefing's tempo, in Phase
  3 or Phase 4, and "listen to all eight bars" (`phase-4-findings.md` §15) could not be done at
  150.
- **This check sets the tempo per pair.** `ab_section.py` is not changed, because ADR-024 runs no
  further A/B.
