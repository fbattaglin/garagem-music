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

## 3. The shuffle check: straightened in 5 of 5, and the fix is applied

Fabiano ran `scripts/audition_shuffle.py` in Terminal on 2026-09-13: five pairs in one sitting,
under four minutes, none skipped. The votes are in `bench/audition-shuffle.jsonl`.

| Pair | Take | Section | BPM | A was | Voted | Winner | Reason |
|---|---|---|---|---|---|---|---|
| 1 | regression: 25 | chorus | 96 | straightened | A | straightened | cleaner, less messy |
| 2 | regression: 07 | chorus | 110 | as written | B | straightened | cleaner, less messy |
| 3 | phase 3: 10 | bridge | 150 | as written | B | straightened | just sounds nicer |
| 4 | phase 3: 24 | bridge | 132 | straightened | A | straightened | cleaner, less messy |
| 5 | regression: 08 | verse | 132 | straightened | A | straightened | cleaner, less messy |

**The take as written was preferred in 0 of 5, against a veto at 4. The fix is applied.**

### What the votes say, and what they do not

- **The straightened side won wherever it played.** It won the 3 pairs where it came first (A)
  and the 2 where it came second (B). The lean towards the second side heard, which §2 arranged
  to favour the take as written, did not decide any pair.
- **The reason, 4 times of 5, was "cleaner, less messy".** In the A/B runs that same phrase went
  to the floor 5 of 5 (`phase-4-findings.md` §15), and 4 of those 5 were shuffle pairs.
- **The check was pre-registered as a veto, not as a test of the mechanism.** A coin gives 5 of 5
  one time in 32, which is reported and decides nothing beyond the veto.
- **What it is consistent with:** §16's reading that the model's shuffles were heard as messy
  because the system swung them a second time.
- **What it does not show:** that the A/B's shuffle losses would now go the other way. No
  model-against-floor pair was played, and ADR-024 runs none.
- **One pair was heard again before voting:** pair 1, side A. In the other four each side was
  heard once.

### Applied

- **`realise` straightens by default.** Every model take gets it: the producer, the regression
  replay, and every bake and playback to come.
- **Only two callers ask for the take as written:** the audition's other side, and the
  notation's own round trip (`tests/property/test_dsl_round_trip.py`). The round trip carries
  the floor's loudest shuffle kick, which sits between the eighths on purpose (§2).
- **The 8 shuffle golden files in `tests/regression/` were regenerated**, with the summary line
  for each.
  - **The drums keep the same number of hits.** Each hat moves onto the eighths without meeting
    another.
  - **The guitar loses notes where two strokes meet on one eighth.** Chorus 07 drops from 168 to
    144, chorus 09 from 112 to 96, bridge 10 from 128 to 112, bridge 24 from 112 to 96, and
    chorus 25 from 168 to 144.
  - **Bass and keys counts are unchanged.**
  - **Nothing else moved:** conformance, approval and `kit_collision` are identical, and no other
    section's golden file changed.

## 4. Stage 2: a setlist is baked once and played from disk

Built on 2026-09-13. Nothing was spent and nothing was heard. The paid bake is Fabiano's to run.

### What was built

- **`setlists/<name>.toml`, the spec.** A person writes it: songs in play order, each with key,
  scale, feel, length and seed. `setlists/first.toml` is a proposal for the ten-minute
  sessions: three songs of about 218 s each, in straight eighths, shuffle and halftime. The
  first is seed 7 in E minor, the song Fabiano approved in Phase 2.
- **`scripts/bake_setlist.py` writes `setlists/<name>.json`, the bake.**
  - It estimates and stops unless `--yes`.
  - Each song is arranged exactly as `jam.py` arranges one. The form and endings are stored.
  - It makes the producer's own call, with the same request and deadline and no retry. A miss is
    stored with its reason.
  - It has its own cap, $1.00 by default, and never overwrites an existing bake.
- **`--fake` bakes the floor's own DSL**, free and offline, into `<name>.fake.json`. It exists to
  check playback before paying.
- **`jam.py --setlist <file> --song N` plays a song from disk.**
  - The takes answer through `llm/baked.py`'s `BakedProvider`, behind the same governor and
    breaker, billing $0. No adapter is built and no key is read.
  - The producer asks only for the briefings the bake holds (`agents/routing.py`'s `only`). Any
    other briefing is declined as `not_routed`, and the floor plays it.
  - The log records `setlist_loaded`. Nothing printed while it plays says who wrote a section.
- **`rehearse_session.py --setlist`** plays a baked song offline through the real scheduler and
  producer, conducted as before.
- **`engines.completed`** fills a partial take from the floor. It was copied in three places and
  is now one function, used by the producer, the bake and the audition.

### Three decisions made while building it

**One take per briefing, not per section.**
- A second verse briefed exactly like the first plays the first verse's take, with its own seed.
  The groove repeats and the humanisation does not, which is what a band does with a verse.
- This is ADR-000's P6: *"sections already generated from the same briefing are reused rather than
  regenerated, saving latency and cost, and forming the basis of Setlist Mode."*
- A veto therefore removes a groove everywhere it would have played.
- It makes the bake cheaper: `first.toml` asks 18 calls for 48 sections, about $0.06 expected.
- Live, the producer still asks per section.

**Takes are keyed by the briefing text, not by the request's fingerprint.**
- A cassette refuses a moved prompt, which is its job as a drift alarm.
- A curated take is material. The key is `dsl.brief` of the stored briefing, computed at playback,
  so a reworded prompt does not strand a setlist.

**A take is stored as DSL and a seed, with a digest of the notes it made.**
- The notes are made again at playback, so straightening and any later composition fix reach
  takes already baked.
- `jam.py` warns when a take no longer plays what it played at bake time.

### What the rehearsal predicts

`first.fake.json`, every song, with the conducting of the last three conducted runs in
`bench/jam.jsonl`. "From the setlist" counts sections that played from a take.

| Song | Nobody at the MiniLab | Pads only | Knobs only | Pads and knobs |
|---|---|---|---|---|
| 1, straight eighths | 14 of 16 | 13 of 18 | 3 of 16 | 2 of 18 |
| 2, shuffle | 14 of 16 | 9 of 18 | 3 of 16 | 2 of 18 |
| 3, halftime | 14 of 16 | 11 of 18 | 3 of 16 | 2 of 18 |

- **Unconducted, the setlist plays all but the intro and the outro.** Those are four bars and
  never asked, live or baked.
- **Pads cost a little.** A jump's chorus and the section after it are the floor's, as live
  (`phase-4-findings.md` §12).
- **Knobs cost almost everything.**
  - A knob moves `dyn` or `tension` for every section still to come. None of the moved briefings
    is in the bake, so the floor plays the rest of the song.
  - The conducting replayed is the Stage 5 gate's, with knobs swept hundreds of times. But the
    first knob step that changes an offset moves the whole rest of the song just the same.
  - Live, the model is asked again for the moved briefings. From disk, nobody can be.

### Open, and to be decided before the Wi-Fi-off session

**What a knob should do to a baked song.** Three answers, none taken yet.
1. **Re-realise the take under the moved briefing.** The model's groove stays, and the system's
   own density and tension respond to the knob. This is ADR-000's *"parameterised deterministic
   material"*, taken literally. It is a musical change, and would be heard in the curation
   session rather than in a test.
2. **Leave the knobs alone in Session S.** The criterion's share is then the pads-only column.
3. **Bake the knobs' neighbours.** At 65 knob positions per briefing, this is expensive, and
   rejected here unless the other two fail.

Suite: **2176 passed, 27 skipped**; `ruff` and `mypy` clean.

## 5. The first real bake, and the first song played from it

**The bake, 2026-09-13.** Fabiano ran `bake_setlist.py setlists/first.toml --yes` against
`claude-sonnet-5`. The file records the date in UTC: 2026-09-14.

| Song | Feel | Takes | Missed | Cost |
|---|---|---|---|---|
| Seven | straight8 | 6 of 6 | 0 | $0.0256 |
| Swing low | shuffle | 6 of 6 | 0 | $0.0195 |
| Half light | halftime | 6 of 6 | 0 | $0.0191 |

- **18 of 18 delivered, every take with all four parts from the model.** Nothing was completed
  from the floor, and no call missed its deadline.
- **$0.0642 against the $0.06 expected**, at the usage Phase 4 measured.
- `setlists/first.json` is committed. It is material, and it will hold the curation.

**Every song played from it in the real Set,** one after another, unconducted:
`jam.py --setlist setlists/first.json --song N`.

| Song | Played | Beats lost | From the setlist | Spent | Slowest write |
|---|---|---|---|---|---|
| 1, Seven | 220 s, to its end | 0 | 14 of 16 | $0 | 1,987 ms |
| 2, Swing low | 220 s, to its end | 0 | 14 of 16 | $0 | 1,983 ms |
| 3, Half light | 220 s, to its end | 0 | 14 of 16 | $0 | 2,001 ms |

- **Eleven minutes of music from disk, and nothing failed.** No adapter was built and no key was
  read.
- **The 4-bar intro and outro of each song are the floor's.** They are never asked, as the
  rehearsal predicted.
- **No take drifted.** The shuffle's takes were baked after straightening, and they play what they
  played at bake time.
- **The slowest clip writes, about 2 s, are inside what Phase 4's sessions saw.**
- **No verdict by ear was asked for.** These runs checked that playback works; curation (Stage 3)
  is where the ear decides.
- **The report still reads Phase 4's criteria.** Its "after a jump" line is "NOT met" whenever no
  jump is struck, which says nothing about a setlist. Stage 5 writes Phase 5's report. The length
  line now names a song's own length in seconds, where it printed "3.63636 minutes".

## 6. Stage 3: keep and veto, and curation from the log

Built on 2026-09-13. Nothing was spent and nothing was heard.

**The decision, taken with Fabiano before building:** a mark changes nothing that sounds.
- A veto is curation for the next time the song plays, not a cue for now.
- Changing the music at the strike would be a new musical move, with its own listening, and the
  phase keeps those few (ADR-024).

### What was built

- **Pads 4 and 7 are `keep` and `veto`** (`controller.toml`, notes 39 and 42, heard by the probe
  in Phase 4). They are a new cue family, `mark`, and all eight pads now ask for something.
- **The scheduler logs `take_marked`** for the section that was sounding when the pad was struck:
  its index, its name, who wrote it (`model` or `floor`) and its seed.
  - A strike in a section's last bar, read after the next section began, marks the one that was
    heard.
  - A jump's chorus is marked as the floor's, with the candidate's seed.
  - Nothing is fired, written or re-planned, and a test holds the music identical with and
    without marks.
  - The take's text is never serialised on the bar loop (invariant 3).
- **`obs/curation.py` joins each mark to its take offline**, from the order of the log. The last
  `section_parsed` for a section is the take the buffer held; `section_generated` from the buffer
  says it was written; a `not_in_buffer` fallback or a jump says the floor's was. `per_author`
  counts keeps and vetoes by author, which is the telemetry ADR-024 asks the gate to report.
- **`scripts/curate_setlist.py setlists/<name>.json` writes the marks into the setlist.**
  - Keep pins a take and veto retires it. The last word on a take wins.
  - A mark on the floor's music, on another setlist, or on a take re-baked since is counted and
    changes nothing.
  - Applying one log twice gives one file. `--dry-run` writes nothing.
  - Its output counts marks by kind and never says which sections the model wrote, so the next
    session is blind too.
- **`bake_setlist.py --rebake-vetoed` asks the model again for each vetoed briefing, once.**
  - A delivered take replaces the vetoed one, unmarked.
  - The vetoed take is kept in the song's `retired`, because a veto is a preference and the take
    it fell on is half of that evidence.
  - A miss leaves the veto standing, and the floor keeps that briefing.
- **`jam.py`'s closing summary adds the marks**, by kind, with no authors.

### Rehearsed on the real bake

Song 1 of `setlists/first.json` was played offline through the real scheduler and producer,
curated in memory without writing the file. Three marks were struck:

| Struck in | Fell on | Author | Curation |
|---|---|---|---|
| bar 1 | the intro | floor | counted, nothing changed |
| bar 6 | the first verse | model | take kept |
| bar 14 | the first chorus | model | take vetoed |

Every mark reached the take that was playing.

### How it is used

1. Play the setlist, pads only. The knobs move every briefing still to come off the bake
   (§4), so marks would fall on the floor.
2. Strike pad 4 on what should stay and pad 7 on what should not. Unmarked takes stay as they
   are.
3. `uv run python scripts/curate_setlist.py setlists/first.json`
4. If anything was vetoed and the model should try again:
   `uv run python scripts/bake_setlist.py setlists/first.toml --rebake-vetoed --yes`
   costs about $0.004 per vetoed briefing.

Suite: **2197 passed, 27 skipped**; `ruff` and `mypy` clean.
