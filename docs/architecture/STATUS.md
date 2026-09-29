# Roadmap status

**Current phase: 7 — the arrangement.** The band has its material; this phase decides where
things go in time — a solo section, relief in the form, and a fill that is announced
([ADR-027](ADR-027-the-arrangement.md)).

## Phase 7 exit criteria

[ADR-027](ADR-027-the-arrangement.md), agreed with Fabiano on 2026-09-20 **before anything is
measured or baked**. Each rate states its `n`.

- [x] **No form alternates without relief** — a property over every seed the strategies
      generate: no run longer than `RELIEF_AFTER` sections of verse and chorus alone. And the
      verdict on seed 23, the song heard as repetitive, recorded verbatim: *"Achei que teve um
      bom improvement comparado com a versao anterior"* (2026-09-23, `phase-7-findings.md` §1).
- [x] **The band has a solo section and plays it without a network** — 3 376 solo sections over
      3 200 arranged songs, **0 violations**; `pytest -m live` → 27 passed (2026-09-23);
      verdict: *"Gostei dos solos, acho que temos um bom ponto de partida"*
      (`phase-7-findings.md` §2).
- [x] **The fill is announced** — the section's own `FILL` ending carries a pickup in the bar
      before it. The pad cue keeps ADR-022 and, put to a blind audition, changes **neither** its
      entry nor its return: he ranked today's fill first (`phase-7-findings.md` §3, deviation
      written down before the audition ran). Verdict from one conducted jam, 8 announced fills
      and 3 pad strikes: *"A virada ficou mais integrada, achei bem melhor que a versão
      anterior"* (2026-09-29).
- [ ] **The bake writes solos** — ≥90% of baked sections conformant on the first pass and
      ≥80% approved without repair, `n` stated. The same bar as ADR-026, because it was met at
      100% and lowering it would be a metric moved. Beside them, as description and never as a
      target (ADR-019): the share of solo sections whose lead plays in every bar.
- [ ] **Cost per song inside a declared budget**, estimated before the bake, cap unchanged.
- [ ] **By ear:** one session from the new bake, played and curated, the verdict verbatim.
- [ ] **Nothing regresses** — the live prompt and its cassettes untouched, the musical
      regression suite green, and the golden files that move are the arranger's own,
      deliberately, with the diff read before it is kept.

### What the phase builds

1. **Relief in the form** — one rule in `arranger.arrange`, no new weights.
2. **The solo section** — a fifth kind, its charts, its ending, and the floor's own solo.
3. **The fill announced** — a pickup in the bar before a section's own fill; the pad cue's
   entry and return, inside ADR-022.
4. **The songwriter's solo** — a one-cent probe first, the notation only if the probe asks.
5. **Bake a session, play it, judge it.**

**Left open, and named so it is not rediscovered:** a pad for "next: solo" (all eight are
assigned), `--takes N` (still without a consumer), and live generation (frozen, ADR-025).

### Where the phase actually is

- **Stage A is built: the form gets relief** (`phase-7-findings.md` §1). After six sections
  of verse and chorus alone, the next kind is forced to be something else — the kind still
  chosen from `TRANSITIONS` with its own weights, so only the *timing* is forced. Seed 23,
  the song heard as repetitive, falls from twelve sections of alternation to six and gains a
  bridge in the middle. Worst run over 200 seeds: 6.
  - It turned 21 tests red in two measurement rigs, and both were right: each rebuilt its
    population by replaying a generator that is free to change. The Phase 3 calibration
    corpus is frozen in `bench/calibration-corpus.json` because it cannot be recorded again;
    the regression set already carried its own briefings, and its guard now checks the
    recording against itself. **2 of 29 briefings had moved.**
  - No golden file changed. Suite at **2378 passed, 27 skipped**; `ruff` and `mypy` clean.
  - **Heard on 2026-09-23**, one jam on seed 23: *"Achei que teve um bom improvement comparado
    com a versao anterior. Podemos seguir com a etapà B"*. Criterion 1 met; the threshold
    stays at six.
- **Stage B is built: the band has a solo section** (`phase-7-findings.md` §2). A fifth kind at
  8 bars, `dyn` 3, tension 0.65, after a chorus and back into one, in `RELIEF`. `dyn` 3 rather
  than the planned 4, so the Phase 4 property that a chorus steps up in both `dyn` and tension
  stays true — a new kind does not get an approved one relaxed to make room for it. The floor
  plays it: two runs alternating, every bar line a chord tone by construction, the last bar
  left to the drummer.
  - **3 376 solo sections over 3 200 arranged songs: 0 violations**, and the lead in 27 008 of
    27 008 bars. Neither knob can silence it or break it anywhere in its travel.
  - **A sweep found what 100 unit tests did not.** At 5 steps of compass the widest line spans
    19 semitones and needs an 11-semitone window inside the lead's 29 — narrower than the
    octave it has to land on, so some keys had no octave and the floor raised instead of
    playing. `TOP_STEP` is 4, and the window is now pinned as arithmetic, not as a sample.
  - No golden file moved; two were added. The live prompt is byte-identical, and the only
    prompt change is four bake-only lines. Suite at **2440 passed, 27 skipped**.
  - **Heard on 2026-09-23**, one jam on seed 5 (two solos, at 1:20 and 2:32), with
    `pytest -m live` at 27 passed and the bootstrap clean: *"Gostei dos solos, acho que temos um
    bom ponto de partida"*. Criterion 2 met. 19 fires, every one with a full bar of slack.
  - **A first report was about the wrong sound**, and the event log caught it: *"as transições
    ficaram um pouco truncadas"* turned out to be `pytest -m live` playing fragments, not the
    jam — the log's last run was Stage A's, from the night before. A verdict belongs to a run,
    and the log is what names the run.
- **Stage C is built: the section's own fill is announced, and the cue's two questions go to
  an audition** (`phase-7-findings.md` §3). `Ending.FILL` stopped being the identity: the snare
  leans in on the last beat of the bar before and the hats lift off for that beat. Offbeats
  only, drums only, `validate` clean over every feel and tension. One new golden; no existing
  golden moved.
  - **A plan line was wrong against the record and was not followed.** ADR-027 said to build
    the crash on the cue's return; `phase-4-findings.md` §10 records Fabiano *choosing* the toms
    without it and naming *"an audition between just those two options"* as the way to settle
    it. And the plan's other half, a rising entry, is the idea that ranked **below** the fill it
    was meant to improve when tried on the snare. So both go to the ear: `TOMS_RISING` is a
    candidate, and `audition_fills.py --round phase7` is four blind passages in ~80 s.
  - **The audition ranked on 2026-09-28 (seed 51277): the cue changes nothing.** He ranked
    1, 2, 4, 3 blind, and passage 1 was the fill as it plays today. `FILL_CUE_STYLE` stays
    `TOMS` — no new scenes, no second return step, no velocity ramp. The deviation written down
    before the audition is the one that happened, and "leave it" is an answer.
  - **The crash reversed itself between two blind rounds**, over the same five bars note for
    note (checked: the drums engine, `_toms`, `TOM_RUN` and `land_bars` are untouched since the
    Phase 4 commit, and the other engine changes in between are shuffle rows). 1st of 6 in
    Phase 4, **last of 4** in Phase 7. A preference that reverses is one this ear does not
    reliably hear, so the question is **closed** rather than open. Rising has now been
    auditioned twice and never won.
  - **Noticed in the solo and left alone:** under a `BUILD`, the solo's last phrase is
    attenuated to 76 from 93 by the band's swell and the lead is out for the 2 beats before the
    handover. He heard those two handovers and said *"Gostei dos solos"*, so nothing moves on a
    hypothesis against a verdict.
  - **Heard on 2026-09-29**, one conducted jam: seed 5, 14 sections, 8 announced fills, pad 2
    struck in a chorus, a bridge and a verse, all three landing one bar after the strike.
    *"A virada ficou mais integrada, achei bem melhor que a versão anterior"*. Criterion 3 met,
    and the Phase 5 complaint it answers is closed. Suite at **2497 passed, 27 skipped**.
- **Stage D is next: the songwriter's solo** — and it opens with a probe of about a cent, because
  Phase 6's most expensive lesson was two paid bakes spent on defects in our own notation
  (ADR-027: *ask first, build second*).

## Phase 6 — closed

Closed on 2026-09-20 with every criterion met, and **one deviation written down rather than
waived** (criterion 6's golden-file clause; see below).

Re-verified at the gate on 2026-09-20:
- `uv run pytest -q` → **2335 passed, 27 live-marked skipped**.
- `uv run pytest -m live -q` → **27 passed**, against the five-track `garagem-band.als`.
- `uv run python scripts/bootstrap_set.py` → `session.toml: the Set matches.`
- `ruff check .`, `ruff format --check .` and `mypy` clean over 198 source files.
- Criteria 3 and 4 re-measured from `setlists/songwriter.json` rather than read from this
  file: **18 of 18 = 100.0%** conformant, **18 of 18 = 100.0%** approved without repair,
  0 takes drifted, **$0.0939 a song**.
- Not one line was removed from `src/garagem/dsl/schema.py` in the whole phase, and
  `cassettes/` is untouched. The live blocks are unchanged since 2026-09-01.
- The gate also caught a documentation error: two bakes were dated by the session rather
  than by their files. Corrected.

**What the phase cost: $0.855**, over three paid bakes and one themes-only check. Two of the
three bakes were consumed by defects in *our own notation* — no way to say "this instrument
rests this bar", and no degree above 7, so a melody could not reach the octave. Neither 89%
was re-scored after its fix.

## Phase 6 exit criteria, as met

[ADR-026](ADR-026-the-songwriter.md), agreed with Fabiano on 2026-09-17 **before anything was
measured or baked**, from [ADR-025](ADR-025-the-model-composes-offline.md)'s re-scoping. Each rate
states its `n`.

- [x] **The band has a fifth voice and plays it without a network** — met 2026-09-17
      - the property tests hold with five parts, over every briefing and seed;
      - `bootstrap_set.py` prints "the Set matches" against the five-track
        `garagem-band.als`, and `uv run pytest -m live -q` → **27 passed**;
      - a four-track Set still plays, so the voice is optional by construction
        (`test_a_set_without_a_lead_track_never_receives_the_part`).
- [x] **The shuffle has its own vocabulary**, and the verdict on it is recorded verbatim.
      *"Achei que teve muito mais alma. Muito bom."* — 2026-09-17, one shuffle jam
      (`phase-6-findings.md` §1).
- [x] **The bake writes pitched material** — met 2026-09-18, `setlists/songwriter.json`
      - **18 of 18 = 100%** conformant on the first pass, `n` = 18;
      - **18 of 18 = 100%** approved by the validator without repair;
      - description, never a target (ADR-019): the bass moves inside the bar in 18 of 18,
        9 of 9 choruses carry a lead line, the lead sounds in 66 of 144 bars, 0 takes drifted.
      - Two earlier paid bakes came back at 89% and were reported as not met, each for one
        notation defect (`phase-6-findings.md` §5, §7). Neither was re-scored after its fix.
- [x] **Cost per song inside a declared budget** — met 2026-09-18. **$0.094 a song**
      ($0.2817 for three), inside ADR-026's declared $0.10–0.15, against an estimate of
      ~$0.27 printed before the call was sent. `bake_setlist.py` cannot bake without
      printing it: `paid_provider` estimates, then stops unless `--yes`. The bake's own cap
      is unchanged at $1.00.
- [x] **By ear:** three whole songs from the songwriter, played and curated on 2026-09-20,
      the verdict verbatim (`phase-6-findings.md` §8). Nine keeps, no vetoes.
      *"Acho que elas são diferentes nas suas próprias formas e gostei do resultado …
      Dá para se perceber uma estrutura na música e alguns elementos repetitivos."*
- [x] **Nothing regresses** — met 2026-09-20, with the deviation below stated rather than
      smoothed over.
      - The live prompt is **byte-identical**: across the whole phase not one line was
        removed from `dsl/schema.py`, only added. The cassettes are untouched.
      - The musical regression suite is green, and the whole suite is at 2335 passed.
      - **Deviation:** golden files other than the shuffle's moved. See below.
      - **Deviation, 2026-09-17, Stage B.** The last clause is already broken and stays
        written as agreed. Adding a fifth voice moves every golden that enumerates the band:
        11 engine goldens gained a `LED` block (17 lines added, 0 removed) and 29 regression
        goldens changed only their digest. Stripping the new `LED notes=0` block reproduces
        the old digest in **29 of 29**, so no note, onset or velocity moved
        (`phase-6-findings.md` §2). The criterion's intent — no existing music changes —
        holds; its letter does not, and the gate reads both.

### What the phase builds

1. **The shuffle's own vocabulary** — the floor's shuffle bass, guitar, keys and grooves stop
   copying straight eighths.
2. **The fifth voice** — `LEAD`, a deterministic engine, a range, a track in `session.toml`.
3. **The notation, bake only** — a degree per struck slot for bass and lead, a superset of 0.1.
4. **The songwriter bake** — a theme call per song, then a call per briefing with the theme in
   hand, one line per bar.
5. **Bake a song, play it, judge it.**

**Left open, and named so it is not rediscovered:** how the fill arrives (`phase-5-findings.md`
§10).

### Where the phase actually is

- **Stage A is done and approved: the shuffle has its own vocabulary**
  (`phase-6-findings.md` §1). The bass takes the beats, the guitar the swung offbeats, the keys
  the backbeat, and the loudest kick moved onto the eighths it used to push between. Two golden
  files regenerated, and the floor's shuffle is now a fixed point of straightening at every
  dynamic.
  - Suite at **2243 passed, 27 skipped**; `ruff` and `mypy` clean.
  - **Heard on 2026-09-17**, one shuffle jam: *"Achei que teve muito mais alma. Muito bom."*
- **Stage B is done and approved: the band has a fifth voice** (`phase-6-findings.md` §2).
  A deterministic `LEAD` that plays a three-note hook in the second half of every other bar
  of a chorus, and nothing at all below `dyn` 4. A fifth `[[track]]` in `session.toml`; a
  Set with four tracks never receives the part.
  - It caught one real bug: the stop pad's readiness waited on tracks the Set may not
    have, which would have made the pad dead rather than leadless.
  - Every golden file gained a `LED` block and nothing else. The 29 regression goldens
    changed only their digest, and stripping the new block reproduces the old digest in
    29 of 29 — no note moved. **Criterion 6 said only the shuffle's goldens would move;
    this is the deviation, written down rather than smoothed over.**
  - Suite at **2281 passed, 27 skipped**; `ruff` and `mypy` clean.
  - **Heard on 2026-09-17**, the same shuffle jam as Stage A with track 4 in the Set:
    *"Acho que ela está de bom gosto e adiciona uma cor. Talvez no futuro podemos explorar
    a possibilidade de ela ser mais do que isso."* Approved as colour, which is what it was
    built to be; "more than that" is what Stage D asks the model for.
- **Stage C is built: the notation can name notes** (`phase-6-findings.md` §3). A degree
  per struck slot for the bass, and the `LED` line — read by the parser, written by
  `serialize_section(..., pitched=True)` and by nothing else, so the live dialect, its
  cassettes and every golden file are untouched. **No golden file moved in this stage.**
  - Truncation is now counted against the four voices the notation asks for, not the five
    the band has; counting the lead would have marked every live take truncated.
  - Its round-trip property found a real bug in `engines/lead.py`: a power or sus chord
    has no third, so degree 3 came out of the chord's implied scale and landed outside
    both the chord and the key. The lead takes the root there now.
  - Suite at **2323 passed, 27 skipped**; `ruff` and `mypy` clean.
  - **Nothing to hear yet:** the floor writes no `deg:` lines and no model has been asked
    for one.
- **Stage D is built: the songwriter bake** (`phase-6-findings.md` §4). One `write_theme`
  call per song, then every section written with that material in the message. Two new
  whole system blocks, both bake-only; the live prompt and its cassettes are untouched.
  - One retry, allowed because nothing is playing, and never for a budget or breaker
    refusal. The guard was wrong when written — the stored reason is the *subclass* name —
    and its own test caught it.
  - `--fake` bakes both stages offline: 18 of 18 delivered, every take `BAS,DRM,GTR,KEY,LED`,
    every digest matched. `--plain` is the pre-ADR-026 bake.
  - **The estimate, before anything is spent:** ~$0.24 for the three-song setlist, about
    $0.08 a song, against ADR-026's $0.10–0.15. The per-section usage is an estimate and
    says so; the pessimistic bound is above the $1.00 cap, which is the cap working.
  - **Left out and named:** `--takes N`. Nothing consumes a second take — no A/B at section
    level (ADR-024 §4), one take per briefing in `answers()`, and curation marks rather than
    chooses.
  - Suite at **2331 passed, 27 skipped**; `ruff` and `mypy` clean.
- **The phase is heard and every criterion is met** (`phase-6-findings.md` §8). Three songs
  from `setlists/songwriter.json` played from disk and conducted on 2026-09-20; nine takes
  kept, none vetoed. *"Elas são diferentes nas suas próprias formas … dá para se perceber
  uma estrutura na música e alguns elementos repetitivos."*
  - **Left open, with a named cause:** song 3 was heard as the repetitive one, and the
    cause is `engines/arranger.py`'s transition table, not the songwriter. It is the only
    song whose single bridge falls at section 2, leaving twelve sections of verse-chorus
    after it; the song he did *not* call repetitive is the only one with a bridge in the
    middle. `n` = 3, an anecdote with a checkable cause.
  - **Left open:** the lead could do more, and he named what — **solos**. A solo is a
    phrase longer than a bar, which neither the floor's lead nor a per-bar `LED` line
    reaches.
- **The first paid bake is done and says two things** (`phase-6-findings.md` §5).
  `setlists/songwriter.json`, the same three songs as `first.json`, 18 of 18 delivered for
  **$0.2808** against a $0.24 estimate.
  - **Criterion 3 is not met:** 16 of 18 conformant on the first pass = **89%**, against a
    pre-registered ≥90%. Approved without repair is 18 of 18 = 100%, against ≥80%.
  - Both misses are one defect: an empty voice (`rhy:`, `H:`), which the positions
    spelling makes unambiguous and the parser refuses anyway — while the `LED` line added
    the day before spells a rest exactly that way. **The fix is not credited to this bake**;
    it is measured on the next one, with its own `n`.
  - **The theme prompt failed:** two of three themes are byte-identical to the example in
    `SYSTEM_THEME` and the third differs in five slots. One riff and one hook for three
    songs, three feels and three keys. `phase-3-findings.md` §11's rule, the other way
    round: the example is a complete valid answer, so copying it is correct and cheap.
  - **Criterion 5 is not asked for yet.** A setlist whose three songs share a hook would
    spend a listening session on a prompt defect rather than on the songwriter.

**Two things Phase 5 ended on, in the order they were heard:**
1. **The shuffle is mechanical.** *"A musica número dois … foi sem dúvidas a menos interessante e
   mais mecanica delas"* (`phase-5-findings.md` §13). In a shuffle the whole band lands on one
   swung eighth-note grid: the hats stay on eighths at every dynamic, the bass pulses eighths,
   the guitar strums them, and straightening puts the model's takes on them too.
2. **The fill arrives bolted on.** *"A virada é divertida, talvez no futuro vamos ter que pensar
   em ela entrando de uma forma mais integrada e suave"* (§10).

## Phase 5 — closed

Closed on 2026-09-17 with every criterion met and **no waiver**.

Re-verified at the gate on 2026-09-17:
- `uv run pytest -q` → **2241 passed, 27 live-marked skipped**.
- `uv run pytest -m live -q` → **27 passed**, against `garagem-band.als`.
- `ruff check .` and `ruff format --check .` clean; `mypy` clean over 195 source files.
- CI green on GitHub, run 35295800253. The run before it failed on the formatting of one test
  file and the next commit fixed it.
- **Every criterion was read from committed evidence**, by the commands named below rather than
  by eye.

### The criteria

ADR-000 §7, amended by [ADR-021](ADR-021-the-minilab-joins-phase-4.md),
[ADR-023](ADR-023-the-second-ab-waiver.md), [ADR-024](ADR-024-the-model-writes-fabiano-chooses.md)
and [ADR-025](ADR-025-the-model-composes-offline.md):

> **Exit criterion:** a 10-minute session driven only by the MiniLab and by voice; and a
> 10-minute session **with the Wi-Fi off** using a pre-baked setlist.

- **ADR-021** moved the MiniLab and its first two macros into Phase 4.
- **ADR-024** decided when the model is worth calling. The floor plays live, and the model's
  takes reach the stage through setlists Fabiano curates with KEEP and VETO, blind to who wrote
  them. No further model-against-floor A/B is run, and the six remaining macros are deferred.
- **ADR-025, after a review on 2026-09-16:**
  - the voice session leaves the criterion;
  - the band's instruments replace Drift before the phase closes;
  - the Wi-Fi-off session is the setlist's songs played back to back;
  - a musical change passes on a short listen, with the verdict quoted.

- [x] **When the model is worth calling: decided and applied** (ADR-024)
      - The decision is written down. — **met 2026-09-13**, ADR-024.
      - The shuffle double swing fixed after a five-minute blind check. — **met 2026-09-13**
        (`phase-5-findings.md` §3): the take as written preferred in 0 of 5.
      - The setlist the Wi-Fi-off session plays was curated with Fabiano's KEEP and VETO, from
        sessions he played. — **met 2026-09-17**: `setlists/first.json` holds **8 takes kept, 1
        vetoed and 9 unmarked**, struck across four sessions he played (§7, §10, §13). The vetoed
        verse plays as the floor.
      - KEEP and VETO counts per author are reported at the gate, from the logs. They decide
        nothing further (ADR-019). — **reported 2026-09-17**, from `bench/jam.jsonl`:

        | | keep | veto |
        |---|---|---|
        | the model's takes | 13 | 2 |
        | the floor's music | 6 | 8 |

        In the Wi-Fi-off session alone: the model 6 keeps and no veto, the floor 2 keeps and 2
        vetoes. **This is not an A/B and decides nothing.** The marks are unpaired, struck freely,
        and under the knobs the floor plays far more sections than the takes do, so it is also
        more exposed.
- [x] **The band plays on its own instruments** (ADR-025)
      - The Set, `garagem-band.als`, has a Drum Rack kit and sampled instruments, and
        `bootstrap_set.py` and `pytest -m live` pass against it. — **met 2026-09-17**
        (`phase-5-findings.md` §10): Dry Session Kit, Electric Bass Raw, Guitar Electric Muted
        and Grand Piano; 27 of 27 live tests pass. The kit keeps its toms a piece lower than the
        band writes them, so `session.toml` now carries a `pitches` table per track.
      - *By ear:* the first song heard in the new sound, the verdict quoted. — **met
        2026-09-17** (`phase-5-findings.md` §10): *"A banda já soua mais como rock, o que era o
        obejtivo desde o inicio. E o uso dos instrumentos corretos faz a difereça."* Two musical
        notes are open: how the fill arrives, and an abrupt ending.
- [x] **A 10-minute session with the Wi-Fi off, played from the curated setlist**
      - The setlist's three songs, back to back, as three `jam.py --setlist` runs from the
        MiniLab (ADR-025).
      - *Log:* at least 600 s in total, 0 beats lost in each run, $0 spent and no adapter built.
      - *Log:* **at least 20 of the sections played come from the setlist's takes.** Fixed with
        Fabiano on 2026-09-17, before the session, from the offline rehearsal: it predicts 25 of
        48 under his heaviest recorded conducting, 42 of 48 with nobody at the MiniLab, and 0 for
        the floor alone (`phase-5-findings.md` §12). Read by
        `scripts/setlist_report.py --share 20`.
      - Both log lines — **met 2026-09-17** (`phase-5-findings.md` §13).
        `scripts/setlist_report.py --share 20` exits 0: **625 s in three songs, 0 beats lost,
        every song played to its end, nothing spent, no adapter built, 435 controls in 3 of 3
        songs, and 25 of the 46 sections played came from a take.**
      - *By ear:* the verdict quoted. — **met 2026-09-17**: *"A musica número dois começou de
        forma bagunçada. Ela também foi sem dúvidas a menos interessante e mais mecanica delas."*
        The log says song 2's start was mechanically identical to the other two, so what was heard
        is the music. It opens Phase 6.

### How the phase went

- **Stage 0, the plan:** ADR-024, agreed before anything was measured.
- **Stage 1, done:**
  - the live log keeps the model's DSL;
  - model shuffles are straightened, preferred in 5 of 5 blind pairs (§3).
- **Stage 2, done:** a setlist is baked once and played from disk (§4, §5).
  - `setlists/first.json`: 18 of 18 takes for $0.064.
  - All three songs played in the real Set, 220 s each, with 0 beats lost.
- **Stage 3, done:** pads 4 and 7 keep and veto, `curate_setlist.py` writes the marks, and
  `bake_setlist.py --rebake-vetoed` asks again (§6).
- **The knobs, decided** (§7): a knob moves the briefing and the take keeps playing
  (`setlist.reachable`).
  - Since 2026-09-16, a knob-served take echoes the briefing it answers, so it is no longer
    logged as a `section_mismatch`.
  - Rehearsed with the last three conducted runs: 20, 25 and 35 mismatches per song down to 0,
    with 6, 9 and 10 of 17 sections from takes.
- **Curation, over four sessions he played:** 8 takes kept, 1 vetoed, 9 unmarked. The vetoed
  verse plays as the floor, and is not re-baked, because Phase 6 replaces the bake's notation.
- **Stage 4, the voice spike, is parked** (ADR-025). `scripts/spike_voice.py` stays.
- **The review, 2026-09-16:** ADR-025.
- **The band's own instruments, 2026-09-17** (§10). `garagem-band.als` carries a Dry Session Kit,
  Electric Bass Raw, Guitar Electric Muted and a Grand Piano, all Core Library presets built from
  Drum Rack and Simpler. `session.toml` says where the kit keeps its toms, since it holds a ride
  where the band writes its high tom.
  - Song 1 played from it, conducted: 226 s, 0 beats lost, 10 of 11 bar cues one bar after the
    pad, two KEEPs struck and applied.
  - Fabiano: *"A banda já soua mais como rock, o que era o obejtivo desde o inicio. E o uso dos
    instrumentos corretos faz a difereça."*
  - **The last chord now has a bar to ring in**, after he heard the ending as abrupt. One golden
    file moved, and he heard the result: *"O final ficou muito melhor."*
  - **Open, not acted on:** how the fill arrives. It is heard as fun but bolted on.
- **Phase 5's own report** (§11): `jam.py --setlist` reads a song from disk against this phase's
  criteria rather than a generated session's, and `scripts/setlist_report.py` reads the session
  the log ends with. A conducted song is no longer held to its baked length, because `end` and a
  jump both cut bars on purpose.
- **The line the session was held to, fixed before it ran** (§12): 20 of the sections played,
  against a rehearsal predicting 25 of 48 conducted and 0 for the floor alone.
- **The Wi-Fi-off session, 2026-09-17** (§13): 625 s, 0 beats lost, no network, $0, 25 of 46
  sections from takes. It ended on the one thing Phase 6 opens with: the shuffle was heard as
  mechanical.

## Phase 4 — closed with one waiver

Closed on 2026-09-13. Nine criteria are met with evidence.
- **The blind A/B was not met, and Fabiano waived it**
  ([ADR-023](ADR-023-the-second-ab-waiver.md)). Its threshold is intact.
- **The debt that the metrics reproduce the ear** was answered rather than met
  ([ADR-019](ADR-019-the-ear-is-the-instrument.md)).
- **Both of the project's waivers fall on the same criterion.**

Re-verified at the gate on 2026-09-13:
- `uv run pytest -q` → **2093 passed, 27 live-marked skipped**.
- `ruff check .` and `ruff format --check .` clean, and `mypy` clean over 179 source files.
- CI green on GitHub, run 34775147569.
- **The session criteria were re-read from the committed `bench/jam.jsonl`:** events
  1839–3084 for the eight-minute session and 3085–3306 for the chaos test. Every number
  recorded on the day was reproduced.

ADR-000 §7, amended by [ADR-017](ADR-017-composition-over-generation.md),
`phase-3-findings.md` §14, [ADR-019](ADR-019-the-ear-is-the-instrument.md) and
[ADR-021](ADR-021-the-minilab-joins-phase-4.md): the
arrangement is composed deterministically over the model's groove, because asking for it in
one call was measured at 30 cancellations in 30 attempts; and a human cue takes effect
deterministically on the next bar while the model refines the next section, because the
1–4 bar rewrite deadline is 0.73–2.91 s and `claude-haiku-4-5` measured p50 1.83 s, max
15.04 s.

> **Exit criterion:** 8 minutes of continuous session; no deadline overrun left unhandled;
> metrics within range; cost per session within the declared budget; a chaos test (kill the
> network mid-session) with no audible interruption.

- [x] 8 minutes of continuous session with section changes throughout (machine, event log)
      — **met 2026-09-13** (`phase-4-findings.md` §12): 489 s, 31 section changes, played to
      its end, no beat lost, conducted from the MiniLab with the model generating.
- [x] No deadline overrun left unhandled — every one declines or falls back, logged with
      its reason and its seed. ADR-000 §9 still rates the tail High, and Phase 3's clean
      round (0 of 29 over) did not retire it.
      — **met 2026-09-13**: 67 sections asked, 51 delivered, none over its deadline. Every
      section the model did not have was played by the floor with its seed, and no boundary
      passed without its section. The tail is still not retired: this session never reached
      it.
- [x] Coherence metrics on every section in the event log — bass/kick alignment, harmonic
      conformance, register spread, density against the target `tension` — **and no
      metric used as a target until one has passed a pre-registered preference gate**

      **Amended by [ADR-019](ADR-019-the-ear-is-the-instrument.md), accepted by Fabiano on
      2026-09-12.** ADR-000 §7 asked for these *"in range"*, which assumed a cheap metric
      that tracks the ear exists; three mechanisms were proposed and none predicted what
      Fabiano hears (`phase-4-findings.md` §1, §3, §5). No threshold moved, and the
      amendment adds a prohibition the original text did not have.

      **The mechanism exists; the evidence does not yet.** Every section the scheduler
      writes now records a `section_measured` event beside its `section_written` — all
      five metrics of exactly what was written, ending included, with its seed — whether
      the model or the floor wrote it. Ticked when the 8-minute session's log shows one per
      section.

      — **met 2026-09-13**: 54 of 54 section writes measured, and no metric steered anything.
- [x] Cost per session inside the declared budget, hard-capped by the `Governor`
      — **met 2026-09-13**: $0.238 against a target of $0.30, which Fabiano raised from $0.10
      before the session (§12). The $1.00 cap never engaged.
- [x] Chaos test: the network dies mid-session and nothing is audible (P2, by ear as well
      as by log) — **met 2026-09-13** (`phase-4-findings.md` §14). The Wi-Fi went twice in a
      three-minute conducted song: 4 calls lost, the floor played those sections, 0 beats
      lost, and the model came back between the two losses. Fabiano: *"Não ouvi nenhuma
      interrupção."*
- [x] Musical regression suite in CI against cassettes, detecting model drift
      — **met 2026-09-13** (`phase-4-findings.md` §13). Phase 3's 29 sections recorded from
      `claude-sonnet-5` for $0.103: 29 of 29 conformant, none repaired. CI fails on a moved
      prompt, a missed target or a golden diff. Drift is caught when someone records again,
      never continuously — the reading Fabiano accepted before recording.

Added by [ADR-021](ADR-021-the-minilab-joins-phase-4.md), when the MiniLab moved into this
phase. How a cue reaches the bar is [ADR-022](ADR-022-a-cue-costs-a-fire-never-a-write.md).

- [x] A MiniLab cue takes effect on the next bar — `fired_bar − cue_bar = 1` for every
      next-bar cue in a session's event log — **met 2026-09-13**: 34 of 34 in the paid session
- [x] After a jump cue, the section that follows is requested from the model with the
      re-planned briefing, and a stale section never plays (event log) — **met 2026-09-13**:
      after each of 5 jumps the model was asked about the re-planned song. 13 stale scores
      were refused and none was written. "The section that follows" is read as the first one
      the model can still serve (§12).
- [x] A session directed from the MiniLab, judged by ear, the verdict recorded verbatim
      — **met 2026-09-13**, three conducted songs over the deterministic floor
      (`phase-4-findings.md` §11): *"Eu acredito que ficou tudo dentro do esperado."*

Carried out of Phase 3 as an explicit debt ([ADR-018](ADR-018-the-ab-waiver.md)):

- [~] **The metrics reproduce the ear before anyone listens again.**
      — **NOT MET. DISCHARGED by [ADR-019](ADR-019-the-ear-is-the-instrument.md) on
      2026-09-12**, by being answered: the metrics were given a falsifiable job before a
      tuning job, and they failed it twice. The evidence below is unchanged.

      **Re-aimed, because the debt as written is not executable and its mechanism is
      refuted** (`phase-4-findings.md` §1–2). The model side of the twelve judged pairs
      was never persisted, and `register_spread` measures 1.000 on all 112 recorded model
      sections: the DSL never lets a model name a pitch, so out-of-chart notes and a band
      piled into one octave are things the architecture forbids it to produce. §16's
      mechanism cannot be what was heard.

      What replaced it is `kit_collision` — kick and snare in the same slot, which the
      model does 0.172 of the time against the curated grooves' 0.060, the one measured
      difference in the corpus pointing the same way as those three votes.
      `scripts/calibrate_metrics.py` plays blind pairs of it, **both sides the same
      briefing**, so only the drum pattern the model wrote differs.

      **Run twice, missed twice** (`phase-4-findings.md` §3, §5). Asked as a *label* —
      which take is messier — it scored 6 of 10 against a threshold of 8, and the design
      error was in the question rather than in the ear: preference is the job his ear is
      the reference for, and describing is not. Re-aimed to ask which take is *preferred*
      and pre-registered at 12 of 16, it scored **5 of 16** — with the point estimate
      inverted, the take the metric calls messier preferred in 10 of 15 decisive pairs.

      **The gate did its job: `kit_collision` does not steer arrangement work**, and the
      phase has no validated measure of mess. Stage 2 is no longer held by this line — it
      proceeds judged by ear, the way Phase 2's floor was judged. The offline corpus that
      made both runs free is spent: one unheard pair remains of 107 sections.
- [~] **Blind A/B re-run at this phase's close — same design, same threshold: 8 of 12.**
      Blind, balanced across sections and feels, pre-registered. The Phase 3 waiver moved
      the gate; it did not lower the bar.
      — **NOT MET 2026-09-13** (`phase-4-findings.md` §15): the model was preferred in
      **6 of 12**. Pooled with Phase 3's runs after composition, that is 18 of 36, exact
      parity. The reasons repeat ADR-018's picture: "cleaner" went to the floor 5 of 5, and
      "less boring" to the model 4 of 5. **Waived by Fabiano on 2026-09-13**
      ([ADR-023](ADR-023-the-second-ab-waiver.md)): the threshold stands, and when the model
      is worth calling opens Phase 5. Fabiano heard the model's shuffles as the messy ones.
      §16 finds a mechanism that fits: the model writes its own swing, and the system swings
      it again. It is a lead for Phase 5, not a result.

### Where the phase actually is

Done, with the suite at **2093 passed, 27 skipped** (all live-marked), `ruff` and `mypy` clean:

- **Version control.** The project is under `git` for the first time; Phase 4 moves the
  eight golden files and reviewing them without a diff is not possible.
- **A cancelled call is no longer free.** `Usage` rides the `done` event, so a stream
  cancelled at its deadline was released and charged nothing — thirty billed calls at
  $0.0000 in Phase 3 (§14). It is now settled against a usage reconstructed from the
  prompt and from what arrived, flagged `estimated` and kept apart from measured spend.
  **The cost criterion below was unverifiable until this.**
- **The session budget is declared**, in `config/budget.toml` rather than as two constants
  inside `scripts/jam.py`.
- **Material survives.** `ab_section.py` persists the seed, the briefing and the model's
  raw DSL beside every vote — the defect that cost Phase 3 its calibration set.
- **The four metrics exist** (`theory/coherence.py`, `engines/coherence.py`), plus
  `kit_collision`, with the floor established as the clean reference by property test.
- **The provider is warmed on the producer's own loop**, which is the only loop that may
  own its pool (§9). `jam.py` never did this, so every first section paid the handshake.
- **CI exists** (`.github/workflows/ci.yml`): lint, format, types, tests. No key, no
  Ableton — the `no_network` fuse is what makes the default suite safe to run there.
- **The calibration gate ran, and missed.** Two listening sessions, 26 blind pairs across
  the two designs, and the metric they were built to validate does not predict preference
  (§3, §5). `tally` is corrected a second time — it reported this result as a near miss
  when it was a reversal — and `--tally` now reads a finished log back, which it could
  not do when this one finished.
- **[ADR-019](ADR-019-the-ear-is-the-instrument.md) accepted** by Fabiano on 2026-09-12.
  The metrics stay in the event log as telemetry and are barred from being targets; the
  inverted sign of `kit_collision` is a hypothesis, not a steer, and testing it needs its
  own pre-registration written before Stage 2's material exists.
- **Stage 2 is built, and approved by ear** (`phase-4-findings.md` §6,
  [ADR-020](ADR-020-endings-are-composed-over-the-score.md)). A verse builds into a chorus
  — snare roll, swell, the band letting go of the last beat; a bridge, and the step into
  the last chorus, stop dead with a drummer's pickup; the last chorus is lifted above the
  others; and the song ends on a ringing chord. Composed over the finished section by the
  scheduler, so a model's groove and the floor get the same form. The generators and their
  eight golden files are untouched; `jam.py --plain` plays the song as it was.
  **Fabiano listened on 2026-09-12**: *"Gostei muito do resultado."* — I liked the result a
  lot. The verdict is on the whole; no move was singled out as working or not.
- **Every section carries its metrics in the event log** (`section_measured`), as
  telemetry and never as a target (ADR-019). About 0.1 ms per section, at write time.
- **Stage 0 of the MiniLab plan is done** (`phase-4-findings.md` §7). The MiniLab moves into
  Phase 4 as the tactical layer's instrument — Setlist Mode and voice stay in Phase 5 — and
  the real Set answered what that rests on: clip fires and track stops wait for the bar,
  legato carries position and can be set just before a fire, the last trigger wins, and
  this Live allows 16 scenes. The MiniLab sends pads on channel 10, notes 36–43, and knobs
  as absolute CCs, all on one port, and Live launches nothing from them. `mido` and
  `python-rtmidi` are added; `scripts/probe_minilab.py` and `scripts/spike_cues.py` are
  how these were measured.
- **Stage 1: the decisions are written down.** [ADR-021](ADR-021-the-minilab-joins-phase-4.md)
  moves the MiniLab into this phase and adds the three criteria above;
  [ADR-022](ADR-022-a-cue-costs-a-fire-never-a-write.md) fixes the mechanism — candidates
  written before the downbeat, legato variants written a section ahead, a scene layout in
  eight scenes, legato off on main clips, and a jump cue beating a scheduled section change
  while a bar cue never displaces one.
- **Stage 2: the MiniLab is heard, and changes nothing yet.** `control/` holds the port, a
  fake and the `mido` adapter; `controller.toml` maps pads 36–43 on channel 10 and knobs 74
  and 71 to cues and the two macros; a `CueQueue` stamps each control with the beat it
  arrived at, coalesces knob turns and keeps pad strikes in order; the scheduler logs each as
  `cue_received`. `jam.py --controller minilab` prints the legend before the downbeat and a
  count after the last bar. `session.toml` declares every band track disarmed, which the
  bootstrap now checks and repairs — it caught KEYS armed in the real Set.
  **Gate passed on the fourth run, 2026-09-12** (`phase-4-findings.md` §8). The whole song
  played to its end while 63 controls arrived, all eight mapped kinds among them. The two
  runs that stopped at bar 5 were Live's arrangement loop, not the MiniLab as first
  diagnosed; the loop is now in `session.toml`, and a run that ends early says whether the
  transport stopped or the position went back. Cues are read a bar after they arrive — the
  latency Stage 3 must remove.
- **Stage 3: the band follows the MiniLab to the chorus — gate passed, 2026-09-12**
  (`phase-4-findings.md` §9). The song's chorus is written into scene 2 before the downbeat;
  pad 5 fires it for the next bar, read inside the bar it arrives in, and the rest of the
  song is re-planned behind it, with the model asked for what follows and stale sections
  refused twice. In the real Set, ten jumps all landed one bar after the pad and no write hit
  a sounding scene. Fabiano: *"Dentro do esperado"*, *"Tudo correu bem"*, the cut
  *"perceptível, mais natural"*. The gate also found jumps lengthening the song, 102 s to
  216 s; the re-plan now aims at the length it replaces.
- **Stage 4: stop, fill and drums-and-bass from the MiniLab — gate passed, 2026-09-12**
  (`phase-4-findings.md` §10). Stop and fill variants are written a track per bar into scenes
  4–7 and fired per track for the next bar, returning to the groove by a legato fire a bar
  later; pad 3 stops guitar and keys until the next section. In the real Set, 21 cues applied,
  20 landing after one bar and one after two (struck on the bar line), and all 13 returns on
  time. Fabiano: *"Achei tudo bem, talvez a virada não me parecia tão clara."* A blind
  audition of six fills put the run down the toms first and second; the fill cue becomes the
  toms.
- **Stage 5: "next: bridge", "end" and the knobs — gate passed, 2026-09-13**
  (`phase-4-findings.md` §11). Pad 6 puts a bridge, and pad 8 the outro, at the first section
  that can still change; the density and tension knobs move every section still to come
  around its plan, and the model is asked for the moved briefings. Over three conducted
  songs, 25 of 26 bar cues landed one bar after the pad, every boundary cue re-planned from
  the section it should, and no run lost a beat. Fabiano: *"Eu acredito que ficou tudo dentro
  do esperado. Inclusive o pad 5 no refrão além do impacto óbvio esperado."* The gate found
  two late moments, both behind the 0.8 s it costs to replace a clip of another length. It
  also found that a knob turn delays the stops' preparation. Neither was heard as a fault,
  and both are left open.

- **Stage 6's paid session: every criterion it could measure, met, 2026-09-13**
  (`phase-4-findings.md` §12).
  - `scripts/rehearse_session.py` plays the 8-minute session offline: a fake Live, a perfect
    model and the Stage 5 gate's conducting.
  - It found a third to a half of a conducted session's calls asking for sections already
    written into Live. The buffer now refuses them, and nothing audible changed.
  - `jam.py --generate` now reads every criterion back from its own log, spend included.
  - The predictions are written down: $0.105 with nobody at the MiniLab, $0.15 with pads,
    $0.25 with the knobs swept as at the gate.
  - The declared $0.10 target was below even the unconducted session. Fabiano raised it to
    **$0.30 before the session**, and the $1.00 cap stays.
  - Conducted, the model plays under half the song. That is by design (ADR-022), and written
    down for whoever listens.
  - **The session:** eight minutes with the model generating and Fabiano conducting.
    - Six criteria met: 489 s continuous, no deadline overrun, 54 of 54 writes measured,
      $0.238, 34 of 34 cues on the next bar, and nothing stale played after 5 jumps.
    - The model wrote 12 of the 36 sections that played.
    - Fabiano: *"Soou bem dentro do esperado."*

Stage 6, closing the phase with the instrument in hand:

- **Prepared while Fabiano was away** (`phase-4-findings.md` §13, §14). The chaos test has
  since run and passed, and so has the regression suite.
  - **Musical regression suite.** `scripts/record_regression.py` records Phase 3's closing
    population of 29 sections; `tests/regression/` judges the recording in CI. It fails on a
    moved prompt, on conformance or approval under Phase 3's targets, and on a golden diff.
    Drift is caught when someone records again, never continuously: CI holds no key.
    Fabiano accepted that reading on 2026-09-13. The recording costs about $0.10.
  - **Chaos test.** Preparing it found that a dead network killed the producer's thread: the
    breaker's refusal was not caught, so the model would never have come back. Fixed and
    tested. The report now reads the chaos criterion from the log.
  - **Chaos test: met, 2026-09-13.** The Wi-Fi went twice during a three-minute conducted
    song. The floor played the four sections the model could not, and no beat was lost.
    Fabiano: *"Tudo me pareceu ótimo. Não ouvi nenhuma interrupção."*
  - **Musical regression suite: met, 2026-09-13.** 29 of 29 recorded, conformant and
    unrepaired, for $0.103. The golden files were read before they were kept.
  - **Blind A/B at close: not met, 2026-09-13.** 6 of 12, pre-registered in §15, and waived
    by Fabiano (ADR-023).
  - **The gate, 2026-09-13.** Every criterion but the A/B was confirmed from the committed
    evidence, and Fabiano confirmed closing with the waiver.

## Phase 3 — closed with one waiver

Closed on 2026-09-01. Six criteria met with evidence; **the blind A/B was not met and was
waived by Fabiano**, with its threshold intact and carried into Phase 4
([ADR-018](ADR-018-the-ab-waiver.md)). Phase 0, 1 and 2 closed with no waivers; this one
did not, and the line below says so rather than being ticked.

Re-verified at the gate on 2026-09-01: `uv run pytest -q` → **1561 passed, 25 live-marked
skipped**; `ruff check .` clean; `mypy` clean over 137 source files.

ADR-000 §7:

> - Strict tool-use schema for the complete section; DSL ordered by rhythmic priority.
> - **Incremental stream parser** (ADR-011) writing progressively into the Score Buffer.
> - Semantic validator + repairer + fallback telemetry.
> - Prompt caching with the stable block marked for cache.
> - Per-layer routing: strong for structure, fast for tactics.
>
> **Exit criterion:** ≥95% schema conformance on the first pass; ≥80% validator approval
> without repair; p95 section latency < 40% of the available musical time; a blind A/B
> test where the generated section is preferred over the deterministic one in ≥65% of
> cases.

This is the first phase in which a model touches the music. Everything below it already
plays without one, which is the whole point of the order: **the LLM is added to a system
that already sounds like a band, so a failed call degrades the music instead of stopping
it** (P2). Phase 2's `bench/jam-phase2.jsonl` shows the scheduler taking the fallback path
fourteen times out of fourteen — Phase 3 is what finally fills the buffer it reads from.

Three criteria are *rates* rather than facts, so each one states its `n`. A rate measured
over five sections is an anecdote.

- [x] ≥95% schema conformance on the first pass (measured, n stated)
      — **met: 97%, n=29** (`bench/sections-positions.jsonl`, 2026-09-01,
      `claude-sonnet-5`). 77% → 93% → 97% across the phase.

      **What closed it is a defect class, not a rate.** A bar is now written as the slots
      that are struck — `K:1,4,7,11,14` instead of `K:x..x..x...x..x..`. The grid counted
      wrong by one character was the entire remaining gap, and it ran at **18 of 149
      sections** across every round this phase; positions produced **0 of 29**, with
      P(0 at that rate) = 0.024. There is nothing to count, so nothing gets counted wrong,
      and a slot outside 1..16 names itself where a short grid silently shifted the bar.

      Also faster and cheaper: p95 0.69x against 0.84x, 217 output tokens against 229.
      The single non-conformant row is a deadline overrun at a 6.98 s budget — the p99
      tail, which no notation addresses. `phase-3-findings.md` §17; ADR-002's grid stays
      reachable via `positions=False` and `bench_sections.py --grid`, because four
      cassettes were recorded against it.

- [x] ≥80% validator approval without repair (measured, n stated)
      — **met: 93%, n=29.** Same sample. Every violation is a schema violation: nothing
      the model wrote was musically invalid once it parsed, and the repairer was never
      needed. 100% of sections reached the buffer, against 93% before.
- [x] p95 section latency < 40% of the available musical time (measured against 5.8 s)
      — **met: p95 0.84x** of each section's own deadline, p50 0.56x, max 0.84x,
      **0 of 29 over, and 0 outright failures** (2026-09-01). Phase 0 predicted this and
      it held. The earlier round lost two calls to the tail at 8.0 s and 5.12 s budgets;
      **one clean round does not retire that risk**, which ADR-000 §9 rates High.
- [x] The incremental parser writes drums and bass before the stream ends (machine)
      — `tests/unit/test_dsl_stream.py`: drums become ready at an event index strictly
      before the last, driven by the 45 real fragments in
      `cassettes/anthropic_section.jsonl`. §4.3's claim as a number rather than an
      adjective. A single-fragment response (Gemini) gives a byte-identical result.
- [x] A section generated by a model plays through Live, in time, with no glitch (machine)
      — **met, 2026-09-01.** `uv run pytest -m live -q` → **25 passed** (15 + 10) in
      2:21, `tests/integration/test_live_generated.py`.

      **And a 90-second performance through the real script**, kept as evidence in
      `bench/jam-phase3.jsonl`: **6 of 6 askable sections came from the model**, all four
      instruments each, all played out of the buffer, **0 schema violations**, 8 scenes
      written and 8 fired. The two 4-bar sections were declined for `no_time` and played
      by the engine, which is the design. Phase 2's log had this at **0 of 14**.

      **It spends real money**, which nothing else in the suite does — three or four
      sections at ~$0.0035, hard-capped by the `Governor` at $0.10, and the run fails
      rather than degrading quietly if the cap is reached, because a live test that
      silently played the floor would prove nothing about generation.

      The load-bearing one is ADR-016's question, which no fake can answer: the producer
      holds a socket and an event loop, Live pushes beats into the control-surface thread,
      and a clip write costs ~1.2 s of that same thread. A companion test asserts that
      generation genuinely *overlapped* the music — otherwise "no beat was dropped" would
      only mean nothing was happening.
- [x] Every fallback is logged with its reason and its seed (event log)
      — `tests/unit/test_producer.py` and `test_jam_generated_offline.py`: every path out
      of `Producer.produce` records an event, and a provider that dies mid-performance
      leaves the music playing for the full three minutes with each remaining section
      played by the deterministic engine. **P2 as a mechanical check.**
- [~] Blind A/B: the generated section preferred in ≥8 of 12 pairs (human, named and dated)
      — **NOT MET. WAIVED by Fabiano on 2026-09-01**, threshold intact, carried into
      Phase 4 ([ADR-018](ADR-018-the-ab-waiver.md)). The evidence below is unchanged.
      — **not met. Measured three times: 18%, 58%, 42%.** Fabiano listened on 2026-08-31
      and twice on 2026-09-01. The threshold was agreed on 2026-08-30, before any number
      existed, and has not moved.

      **Pooled over the two post-composition runs: 12 of 24. Exactly parity.** Both are
      individually consistent with a coin, and pooling removes the temptation to read
      either as a trend. So the phase's central question has an answer, and it is not the
      one ADR-000 hoped for: **a model-written section is neither better nor worse than
      the deterministic floor.** The criterion asks for ≥65%.

      The first run's 18% was measuring form rather than grooves — a static loop against
      an arrangement — and ADR-017's composition closed that gap. What is left is a real
      comparison of two arrangements, and it comes out even.

      **The pre-registered sub-test failed and refuted its own mechanism.** Fixed before
      the run: chorus pairs, model in ≥4 of 6. Measured 2 of 6. But §13's claim was
      *differential* — chorus 1 of 6 against everything else 6 of 6, p = 0.015 — and it
      did not replicate: 2 of 6 against 3 of 6, **p = 1.000**. The model does not lose at
      choruses. It loses everywhere. That is exactly what pre-registration is for.

      **What did emerge is a mechanism a machine can test.** Grouped by the reason given:
      the floor won **3 of 3** pairs decided on *"cleaner, less messy"*, while the model
      won 4 of 6 decided on *"less boring"* or *"just sounds nicer"*. The model writes
      more interesting and messier material and the two cancel. `phase-3-findings.md` §16;
      the twelve judged sections are a calibration set for Phase 4's `register_spread` and
      `harmonic_conformance`.

      **Why it was waived rather than chased.** The criterion has an answer — parity, over
      24 pairs — and the mechanism behind it is the one thing this phase found that a
      machine can measure. Closing the gap means arrangement and range control, which is
      Phase 4's work, judged by metrics that are Phase 4's deliverables. Another round here
      would spend the project's scarcest resource, one pair of ears at n = 1, on the loop
      with the worst diagnostic yield: a vote cannot say why. **The threshold was not
      moved**, which is the only reason a waiver is honest — lowering 8 of 12 to parity
      after seeing 12 of 24 would delete the meaning of every threshold in this file.

Three decisions this phase rests on, each written down: parsing is progressive but
publication is atomic (ADR-011); the network lives on the producer's own thread rather
than in `transport/`, which `tests/unit/test_architecture.py` enforces statically
(ADR-016); and **the model writes the groove while the engines write the form**
([ADR-017](ADR-017-composition-over-generation.md)), which supersedes part of ADR-000 §7's
Phase 4 and is what moved the blind A/B from 18% to 58%.

The 12-pair A/B size and its 8/12 threshold were agreed with Fabiano on 2026-08-30,
**before any number existed** — which is the only time a threshold means anything.

**Who listened, stated because it is part of the evidence.** Fabiano is the sole judge,
and he judges by preference rather than by theory — he does not read the notation this
document is written in. That is not a weakness of the criterion, it is the criterion:
ADR-000 asks whether a section is *preferred*, and the people who will ever hear this
system are not musicians either. Two consequences that are real, though. **n = 1**: a
preference rate is one person's taste, and no amount of pairs makes it two people's.
And **a vote cannot diagnose** — finding out *why* the chorus lost took a post-hoc
hypothesis and a pass over 85 logged sections (`phase-3-findings.md` §13), which is why
`scripts/ab_section.py` now takes a reason in plain words beside each vote.

Findings: `phase-3-findings.md`. Four measurement rounds, 120 section-shots, **$0.49 of a
$2.00 budget** — and three of the four rounds were spent finding defects in the
*measurement* rather than in the model. The first run read 7% conformance; almost none of
that was the model.

The number P2 actually rests on is not in the table above: **93% of sections reached the
buffer playable**, because a rejected line costs one instrument for one section and the
producer fills it from the deterministic engine (§4.3). 77% conformance produced 93%
usable music.

**And the phase's real result is the A/B, not the rates.** The first run's 9 of 11 for the
floor was measuring form rather than grooves — one bar-level line per instrument covers
every bar, so a generated section was a static loop against an arrangement. ADR-017 closed
that gap and moved the number 40 points. What is left is a fair comparison of two
arrangements, and it comes out even: **the model is neither better nor worse than the
floor.** That is the phase's finding, it is not the one ADR-000 hoped for, and it is now
Phase 4's opening question rather than an open Phase 3 checkbox (ADR-018).

## Phase 2 — closed

Closed on 2026-08-30 with every criterion met, no waivers, and the human line confirmed
by ear.

ADR-000 §7 calls this "still the project's most important gate — and now more so,
because it is what guarantees P2 against network loss":

> `BarClock` slaved to the transport · `ScoreBuffer` with a 2-section window ·
> clip-ahead scheduler with double scene buffering · deterministic rock engines (drums,
> bass, guitar, keys) · the `theory/` layer · deterministic seeded humanisation.
>
> **Exit criterion:** 3 minutes of autonomous rock arrangement, with section changes,
> zero dropouts, zero glitches, zero network. A musician listening blind rates it
> "an acceptable demo".

Split below so that each line is either machine-checkable or explicitly human. The phase
adds four packages — `domain/`, `theory/`, `engines/`, `transport/` — plus the OSC
receive loop (ADR-014) and the event log. **Nothing in this phase makes a network call:
that is the point.** Every later phase adds an LLM to a system that must already sound
like a band without one.

- [x] `BarClock` follows Live's beat with the transport running (machine)
      — `tests/integration/test_live_jam.py`: Live pushed beats through a whole
      performance, monotonically, and the bar tracked them exactly (`bar == beat // 4`).
      Push, not poll: the clock issues no OSC call of its own at all
      (`test_the_clock_polls_live_for_nothing`).
- [x] `ScoreBuffer` holds a 2-section window and never hands out a section being written
      (machine)
      — `tests/unit/test_buffer.py`, 14 tests. The window is bounded, `take` never blocks
      and never raises, and a concurrent writer and reader lose nothing. Everything it
      holds is a frozen `SectionScore`, so a half-written section cannot be observed.
- [x] The four deterministic engines produce a valid section for any seed (property tests)
      — `tests/property/test_musical_invariants.py`: `validate(play_section(s, seed))` is
      empty for any briefing and any seed. Verified at 2000 examples per property (44 s);
      the committed profile runs 60, `derandomize=True`. No engine calls the validator and
      none needs the repairer to be legal.
- [x] Every generation is byte-identical given a seed (golden tests)
      — `tests/golden/`: four briefings × two seeds, both the DSL text and every note,
      compared byte for byte. Regenerating is deliberate and needs `GARAGEM_UPDATE_GOLDEN=1`.
- [x] 3 minutes of continuous playback with at least 4 section changes, zero network
      (machine)
      — `uv run python scripts/jam.py --seconds 180 --seed 7` against Live on 2026-08-30:
      **189 s, 14 sections, 13 section changes**, the last fired at beat 400 (181.8 s in).
      Zero network by construction — nothing in `domain/`, `theory/`, `engines/` or
      `transport/` may import a socket, and `tests/unit/test_architecture.py` now checks
      that statically instead of a rule file promising it.
- [x] Zero glitches: no write landed in a playing clip, every fire had at least 1 bar of
      slack (event log)
      — `bench/jam-phase2.jsonl`: 14 written, 14 fired, **zero writes into the playing
      scene**, scenes alternating 0/1 throughout, **every transition fired with exactly one
      bar of slack**, zero `beat_lost` and zero dropped datagrams. A section write costs
      p50 1163 ms and at most 1939 ms — five times the plan's prediction
      (`phase-2-findings.md` §3), which is why it happens at the start of a section and
      not near its boundary.
- [x] **A musician listening blind rates it "an acceptable demo"**
      — **Fabiano listened on 2026-08-30**, to `uv run python scripts/jam.py --seconds 180
      --seed 7` through the Scarlett Solo: 189 s, 14 sections, four deterministic engines,
      no network. The verdict, verbatim: *"Está total aceitável. Na verdade está super
      agradável."* — totally acceptable, and in fact really pleasant.

      That is the criterion ADR-000 §7 actually asks for, and it is the half no
      test can reach. The measured lines above say the transport never glitched; this one
      says the floor is musical. **P2 now rests on something that has been heard, not only
      on something that passed.**

Two decisions this phase is built on, both already written down: `BarClock` is driven by
beats Live pushes and is bar-granular, never a source of timing (ADR-015); the OSC
transport gains a receive thread, because a request/response socket silently eats the
unsolicited beat messages (ADR-014, which supersedes a paragraph of `daw/osc.py`'s own
docstring).

Findings: `phase-2-findings.md`. Three of them change numbers Phase 3 depends on — the
write budget (§3), the wire's precision (§2), and what a note may not overlap (§1).

Machine evidence, all of it reproducible:

    uv run pytest -q                       # 1188 passed, 15 live-marked skipped
    uv run pytest tests/property/ -k timing
    uv run pytest tests/golden/ -q
    uv run pytest -m live -q               # 15 passed, with Live open
    uv run python scripts/jam.py --seconds 180 --seed 7

## Phase 1 — closed

ADR-000 §7: "an integration test writes `Em–C–G–D` across 4 bars, fires the scene, and
audio comes out of the Scarlett. Idempotent." Superseded in part by ADR-013 (the file is
`session.toml`, the instrument is Drift, the bootstrap validates rather than provisions)
and written down in full by ADR-001 (clip-ahead and quantised launch).

Closed on 2026-08-30 with every criterion met, no waivers.

- [x] `DawPort` port + AbletonOSC adapter + `FakeDawAdapter`
      — `src/garagem/daw/`: `port.py`, `osc.py`, `abletonosc.py`, `fake.py`,
      `session.py`. 291 tests pass with Ableton closed, `mypy --strict` over 61 files,
      `ruff` clean. Every setter is write-then-confirm; nothing retries.
- [x] "Set as Code", idempotent, validated and never created
      — `session.toml` at the root, `load_session`/`diff_session`/`apply_session`.
      Idempotence is mechanical, not observed: `test_applying_a_matching_session_writes_nothing_at_all`
      asserts the second pass issues no `set_*` call at all.
- [x] The default suite still opens no socket
      — the `no_network` fuse now blocks `sendto` as well as `connect`; UDP would
      otherwise have sailed straight through it (`phase-1-findings.md` §7).
- [x] AbletonOSC installed
      — `scripts/install_abletonosc.py`, run on 2026-08-30 into
      `~/Music/Ableton/User Library/Remote Scripts/AbletonOSC`. Installing twice
      leaves the same tree.
- [x] **AbletonOSC enabled in Live and answering**
      — enabled on 2026-08-30 in a free Control Surface slot (slot 1 is the MiniLab 3,
      which Phase 5 needs — see `phase-1-findings.md` §8). `scripts/probe_live.py`:
      13 of 15 readable addresses answered in ~100 ms each against Live 12.4. The two
      clip getters are NOT PROBED because the Set holds no clip yet (§9), not because
      they failed. **`clip_trigger_quantization` = 4 for `1 Bar` and
      `output_meter_level` answers `(track, level)` — both confirmed, both were
      assumptions.**
- [x] **The template Set exists and matches `session.toml`**
      — four MIDI tracks DRUMS, BASS, GTR, KEYS, each carrying **Drift**, 132 BPM,
      launch quantisation `1 Bar`, 8 scenes. `uv run python scripts/bootstrap_set.py`
      exits 0 with `the Set matches`. Getting there took two things the bootstrap could
      not do and correctly refused to fake: a default Live Set opens with two audio
      tracks, which had to be deleted and replaced with MIDI ones
      (`phase-1-findings.md` §10), and no LOM call loads an instrument (ADR-013).
- [x] **`scripts/probe_live.py`: every address answers**
      — 15 readable addresses, ~100 ms each, against Live 12.4 on 2026-08-30, exit 0.
      All three assumptions the probe exists to check are now facts:
      `clip_trigger_quantization` = 4 for `1 Bar`; `output_meter_level` answers
      `(track, level)`; and `/live/clip/get/notes` echoes `(track, clip)` then five
      fields per note — 12 notes in 62 arguments, exactly what `notes_from_reply`
      assumes (`phase-1-findings.md` §11).
- [x] **The integration test writes Em–C–G–D, fires the scene, and the instrument sounds**
      — `uv run pytest -m live -q`: **7 passed in 12.1 s**, first attempt after the Set
      matched. Machine-checked: the 12 notes read back identical under `normalised()`,
      firing scene 1 starts the transport within one 1-bar quantum, `meter_level` on
      KEYS rose above 0 while the clip played, and running the whole script twice left
      the Set byte-identical with 12 notes rather than 24. The default suite still
      passes with Live closed (291 tests, `sendto` fused).
- [x] **Audio confirmed by ear at the Scarlett**
      — **Fabiano listened on 2026-08-30 and heard Em–C–G–D through the Scarlett Solo**,
      four passes of the 4-bar progression, one Drift on the KEYS track. Peak
      `output_meter_level` during the run: 0.869.

      Confirming it needed a tool that did not exist. `uv run pytest -m live -q` passes
      while playing only **1.1 bars**: `LISTEN_S` is 2.0 s and the progression is 7.27 s
      at 132 BPM, so the suite fires the scene, samples the meter for two seconds and
      stops. The first attempt at this criterion produced "the tests passed but I only
      heard two notes", which was the suite behaving exactly as written. A test suite is
      built to be fast and listening happens in real time; the two cannot be the same
      command. See `phase-1-findings.md` §13. Phase 2 gives that tool a proper home:
      `scripts/jam.py --seconds N`.

Findings: `phase-1-findings.md`. Three of them contradict ADR-000 and are recorded as
decisions in ADR-013.

## Phase 0 — closed

- [x] Repo with `uv`, `ruff`, `mypy --strict`, `pytest` running clean
- [x] `LLMProvider` port + Anthropic and Google adapters, both with cassettes
      — three cassettes recorded against the live APIs on 2026-08-30 and replayed by
      `tests/unit/test_recorded_cassettes.py`. Gemini 3.1 Pro is not served on this
      key's free tier, so the structural-layer Google recording is against 3.6 Flash.
- [x] `scripts/bench_latency.py` produces a report with p50/p95/p99 TTFT per model,
      measured on the real link, at no fewer than three different times of day
      — **78 samples across three windows on 2026-08-30**, $0.35 spent: morning
      (09:03-10:09), afternoon (15:21) and evening (18:00). The report reads `3/3 yes`
      for every one of the five models. `docs/architecture/latency-report.md`.

      The third window settled the phase's most consequential finding, and reversed it:
      the fat tail of the first window was **first contact, not the time of day**
      (`phase-0-findings.md` §1). Two later cold processes came back clean, so the
      "warming is a correctness requirement" conclusion written after one window was
      wrong — it is an optimisation worth about a second. What the deadline actually has
      to defend against is Haiku's 7.37 s on the *fourth* call of a warm evening run.

      `claude-sonnet-5` is the only model measured whose worst call fit inside the
      5.8 s section deadline: 16 calls, TTFT spread of 260 ms, total time p50 4.29 s and
      max 4.52 s — a margin of 1.28 s. Opus has the same median and misses by 3.08 s at
      worst. That margin is the input the Phase 2 ScoreBuffer window is sized on.

- [x] `governor` cuts off a simulated retry storm in under 2 s (automated test)
- [x] `breaker` transitions closed -> open -> half-open under injected failure
- [x] No test in the default suite makes a real network call

Findings from those measurements: `phase-0-findings.md`. Re-running the rig accumulates
into the same log and sharpens the percentiles, which the tail still needs — the maxima
that set Opus's 3.9x and Haiku's 13.3x are first-contact calls that three later windows
never reproduced:

    uv run python scripts/bench_latency.py --runs 5 --yes

Several of those findings change decisions further down the roadmap. The one Phase 3
depends on: `claude-sonnet-5` is the only model measured whose worst call fits the 5.8 s
section deadline — 16 calls, total time p50 4.29 s and max 4.52 s, a margin of 1.28 s.

## Following phases

7. Extensions: a local symbolic engine, a listening loop, microtiming, jazz

Details and criteria for each phase: `ADR-000-baseline.md`, section 7.
