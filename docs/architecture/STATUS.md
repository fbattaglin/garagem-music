# Roadmap status

**Current phase: 5 — Human in the loop and Setlist Mode.** The model writes, Fabiano chooses
([ADR-024](ADR-024-the-model-writes-fabiano-chooses.md))

## Phase 5 exit criteria

ADR-000 §7, amended by [ADR-021](ADR-021-the-minilab-joins-phase-4.md),
[ADR-023](ADR-023-the-second-ab-waiver.md) and
[ADR-024](ADR-024-the-model-writes-fabiano-chooses.md):

> **Exit criterion:** a 10-minute session driven only by the MiniLab and by voice; and a
> 10-minute session **with the Wi-Fi off** using a pre-baked setlist.

- **ADR-021** moved the MiniLab reading and its first two macros, tension and density, into
  Phase 4.
- **ADR-023** put a question ahead of the rest: **when is the model worth calling at all?**
  Three blind A/B runs came out at parity, 18 of 36.
- **ADR-024 answers it, agreed with Fabiano on 2026-09-13 before anything was measured.**
  - **The floor stays the live default.** The model's material reaches the stage through baked
    setlists, and Fabiano curates them with KEEP and VETO while he plays, blind to who wrote
    each section.
  - **No further model-against-floor A/B**, at section or song level. The A/B's record below
    stands, with its threshold unmoved.
  - **The six remaining macros are deferred** out of this phase.
  - **The Wi-Fi-off criterion is sharpened**, because the floor alone already met it
    (`phase-5-findings.md` §1).
- **Listening is kept short.** Fabiano's listening time is the scarce resource, so the phase takes
  its evidence from sessions he plays, and asks for one five-minute test.

- [ ] **When the model is worth calling: decided and applied** (ADR-024)
      - The decision is written down. — **met 2026-09-13**, ADR-024 committed before
        anything was measured.
      - The shuffle double swing (`phase-4-findings.md` §16) has its five-minute blind check,
        pre-registered in `phase-5-findings.md` before listening, and its consequence applied.
        The fix is applied unless the as-written side is preferred in 4 or more of 5.
        — **met 2026-09-13** (`phase-5-findings.md` §3): the take as written was preferred in
        0 of 5, "cleaner, less messy" in 4. Straightening is on for every model take, and the 8
        shuffle regression goldens were regenerated.
      - The setlist the Wi-Fi-off session plays was curated with Fabiano's KEEP and VETO, from
        sessions he played.
      - KEEP and VETO counts per author are reported at the gate, from the logs. They decide
        nothing further (ADR-019).
- [ ] **A 10-minute session driven only by the MiniLab and by voice**
      - *Log:* at least 600 s continuous, 0 beats lost, and every pad bar cue landing one bar
        after the pad.
      - *Log:* at least 5 voice commands applied, each logged from its tool call to
        `cue_received`, with the latency reported.
      - *Log:* voice drives boundary cues, the two macros and KEEP/VETO. Bar cues stay on the
        pads.
      - *Self-reported:* no keyboard or mouse during the session.
      - *By ear:* the verdict recorded verbatim.
- [ ] **A 10-minute session with the Wi-Fi off, played from the curated setlist**
      - *Log:* at least 600 s, 0 beats lost, and no network provider constructed. The network
        check reads zero calls.
      - *Log:* the share of sections played from the setlist's takes is at least a number fixed
        with Fabiano before the session, from an offline rehearsal. The floor alone cannot meet
        this line.
      - *Log:* conducted from the MiniLab.
      - *By ear:* the verdict recorded verbatim.

### Where the phase actually is

**Stage 0 is done: the plan is written.** ADR-024, these criteria and `phase-5-findings.md` §1,
agreed before anything was measured, baked or heard.

**Stage 1 is done.** Suite at **2141 passed, 27 skipped** (all live-marked); `ruff` and `mypy`
clean.
- **The live event log keeps the model's DSL.** Every `section_parsed`, and every refusal after
  a parse (stale, too late, irreparable, nothing playable), carries the text the model wrote.
- **Model shuffles are straightened.** Under a shuffle, `dsl/realise.py` moves the model's
  attacks between the eighths onto them (`straightened`), by default. The floor never passes
  through it.
- **Fabiano's blind check preferred the straightened side in 5 of 5 pairs** (`phase-5-findings.md`
  §3), against a veto pre-registered at 4 of 5 for the take as written. Four of the five reasons
  were "cleaner, less messy".
- **Two things found on the way, neither acted on** (§2). The floor's loudest shuffle pushes its
  kick with the figure the model put on its hat. And every A/B pair played at the Set's 132 BPM,
  whatever its briefing's tempo.

**Stage 2 is built: a setlist is baked once and played from disk** (`phase-5-findings.md` §4).
Suite at **2176 passed, 27 skipped**; `ruff` and `mypy` clean. Nothing has been spent.
- **`scripts/bake_setlist.py`** bakes `setlists/<name>.toml` into `<name>.json`. It stops unless
  `--yes`, and `--fake` bakes the floor's own DSL for free.
- **`jam.py --setlist <file> --song N`** plays a song with no network, no adapter and no key. The
  producer asks only for the briefings the bake holds, and the floor plays the rest.
- **`rehearse_session.py --setlist`** predicts how much of a song the setlist serves.
- **One take per briefing** (ADR-000's P6). `setlists/first.toml`, three songs and about eleven
  minutes, asks 18 calls, about $0.06 expected.
- **The rehearsal found what knobs do to a baked song.** A knob turn that changes an offset moves
  every briefing still to come off the bake, so the floor plays the rest: 2 or 3 sections of 16 or 18 from the setlist.
  What a knob should do from disk is open, and is decided before the Wi-Fi-off session.

Next, in order:

1. **The first real bake.** `uv run python scripts/bake_setlist.py setlists/first.toml --yes`,
   about $0.06, once Fabiano has read the songs it proposes.
2. **KEEP and VETO on pads 4 and 7, and curation from the logs.**
3. **Voice through `garagem-mcp`.** A spike of the voice path first, and the `mcp` dependency is
   asked for before it is added.
4. **The two ten-minute sessions, then the gate.**

About five minutes of dedicated listening in the whole phase, and under US$0.50 of model calls.

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

6. Timbre, mixing and the asset bakery
7. Extensions: a local symbolic engine, a listening loop, microtiming, jazz

Details and criteria for each phase: `ADR-000-baseline.md`, section 7.
