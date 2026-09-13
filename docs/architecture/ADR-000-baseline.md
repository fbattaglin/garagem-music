# GARAGEM Project — Iteration 1, v2.0: Design & Architecture

**Autonomous multi-agent system for near-real-time music generation, arrangement and manipulation**
Target: Mac mini M4 Pro (14C/20C, 24 GB UMA) · Ableton Live 12.4 Suite · MiniLab 3 · Scarlett Solo
**Inference: cloud APIs (Anthropic / Google). No local LLM.**

Version: 2.0 · Date: 2026-08-19 · Supersedes v1.0
Prices and models verified in August 2026 — re-check before committing budget.

---

## 0. Delta against v1.0 — what "no local LLM" changes

The project's dominant constraint has moved. This is not a configuration tweak; it is a change of architectural axis.

| Dimension | v1.0 (local LLM) | **v2.0 (cloud)** |
|---|---|---|
| **Dominant constraint** | Unified RAM (24 GB shared with Ableton) | **Network latency, variance (p99) and availability** |
| **Model quality** | Hard ceiling around 9B-4bit during the session | **No ceiling. Frontier available.** |
| **Latency bottleneck** | Decode (tok/s limited by memory bandwidth) | **TTFT + RTT.** Decode stopped mattering |
| **Main failure mode** | Memory pressure -> audio dropout | **Network down / rate limit / p99 tail** |
| **Marginal cost** | Zero | Real, but **far smaller than it looks** (§4.4) |
| **Agent topology** | Cascade of 4 small agents, 1 call per bar | **One call per *section*, generating the whole band** |
| **Structured output** | GBNF / decoder grammar | Tool use with a strict schema (server-side) |
| **Privacy / offline** | Local-first, works on a plane | **Depends on the internet.** Requires Setlist Mode (§7) |
| **Ableton's RAM budget** | A tight 3–5 GB | **~18 GB free.** Heavy Sets, sample libraries, 128 buffer |

### The three consequences that actually matter

**1. The architecture gets simpler, not more complex.**
In v1.0, the hierarchical cascade of four agents (Drums -> Bass -> Guitar -> Keys) existed to **compensate for the weakness of a 9B model**: small models cannot hold coherence across four simultaneous parts, so coherence was imposed by architecture. With a frontier model, **a single call can generate all four parts of an entire section, coherent with one another by construction**. Fewer round-trips, less code, better music. The cascade was a crutch; the crutch can go.

**2. The temporal regime moves from "per bar" to "per section".**
API latency cannot be amortised over 1.8 s of bar, but amortises perfectly over 15–30 s of section. The natural unit of planning becomes the **musical section**, not the bar — which, incidentally, is how human musicians think.

**3. The deterministic floor (P2) becomes more critical, not less.**
Before, failure meant latency degradation. Now failure is **binary**: the network drops, the band goes silent. A system that needs a network to make sound is a toy. The deterministic engine stops being a safety net and becomes **the instrument**; the LLM is what writes the score for it.

---

## 1. Engineering principles (invariants)

### P1 — Separation of temporal domains (Two-Clock Principle) — *retained*

```
MUSICAL CLOCK (hard real-time)          COGNITIVE CLOCK (soft real-time)
├─ Tolerable jitter: < 2 ms             ├─ Latency: 0.4 s – 15 s, long tail
├─ Absolute deadline                    ├─ Negotiable deadline
├─ Owner: Ableton Live's transport      ├─ Owner: Python orchestrator + remote API
└─ Local, synchronous, deterministic    └─ Remote, asynchronous, fallible
```

The boundary remains a data structure — the **Score Buffer** — and not a function call. No network call crosses the boundary.

### P2 — The system plays without a network — *reinforced*

Every agent has a local deterministic counterpart. If the API fails, times out or is rate-limited, the bar is filled locally and the event is logged. **The only acceptable "the internet went down" scenario is the band becoming musically more predictable — never falling silent.**

### P3 — Tokens are still latency, but for a different reason — *revised*

Remote decode is fast; what costs is **TTFT + output size + variance**. The compact DSL still pays off, now for three reasons: it reduces section generation time, reduces cost, and **reduces the parsing error surface**. But it is no longer the critical variable it was.

### P4 — Never trust model output — *retained, with a new mechanism*

Layer 1: **tool use with a strict JSON Schema** (server-side guarantee, replaces GBNF).
Layer 2: a local **deterministic musical validator** — range, harmonic conformance, instrumental physicality, voice leading. A schema guarantees shape; it does not guarantee the music is any good.

### P5 — Hexagonal architecture, pure domain — *retained*
### P6 — The session is an event log — *retained and made more valuable*

With the cloud, the event log gains an extra function: **semantic cache**. Sections already generated from the same briefing are reused rather than regenerated — saving latency *and* cost, and forming the basis of Setlist Mode.

### P7 — **No network call is retried on the critical path** — *new*

A retry is a **planning** decision, never an **execution** one. If the call for section N+2 fails, there is time to try again. If the call for section N+1 fails at the wire, it falls back to the deterministic engine and that is that. Never wait on the network with the playhead closing in.

---

## 2. Collaboration architectures — reassessed

### Architecture A — "Production Line" (offline, asynchronous)

A sequential pipeline Composer -> Arranger -> Instrumentalist -> Sound Designer, generating a whole Live Set. **It gained a great deal from the cloud**: it can use the strongest available model with extended reasoning, unhurried, and with the Batch API at a 50% discount. It stops being "the conservative option" and becomes the system's legitimate **pre-production mode**.

### Architecture B' — "The Band (section-shot)" ⭐ **RECOMMENDED**

A revision of v1.0's B. The change is in granularity and topology.

```
   [CONDUCTOR / section] ── 1 call, strong model, every 8–16 bars ──┐
   Generates in one go: chart, form, and the parts for ALL          │
   instruments                                                      ▼
                                              ┌──────── SCORE BUFFER ────────┐
                                              │  section N (playing)          │
                                              │  section N+1 (validated,      │
                                              │              written)         │
                                              │  section N+2 (generating)     │
                                              └───────────┬──────────────────┘
   [ADJUSTER / bar] ── fast model, only when ────────────►│
   the human moves a macro or fires a cue                 │
                                                          ▼
                             VALIDATOR ─→ CLIP-AHEAD SCHEDULER ─→ AbletonOSC ─→ Live
                                                          ▲
                             DETERMINISTIC ENGINE ────────┘  (variations, fills, fallback)
```

**Three operating rates, not two:**

| Layer | Trigger | Model | Tolerable latency | Role |
|---|---|---|---|---|
| **Structural** | section boundary (~15–30 s) | strong (Opus 5 / Gemini 3.1 Pro) | 5 – 15 s | Form, chart, full section arrangement |
| **Tactical** | human cue, macro change | fast (Haiku 4.5 / Flash-Lite) | 0.4 – 1.2 s | Rewrites 1–4 bars under the current plan |
| **Reflex** | every bar | **none — local code** | < 1 ms | Variation, humanisation, fills, fallback |

This is the right control structure for the cloud: **expensive, rare inference where it adds value (structure), cheap and fast inference where there is interaction (cues), and zero inference where there is a deadline (execution)**.

### Architecture C — "Reactive Improviser"

Unchanged in essence, and the cloud **does not help** here — it makes things worse. Note-by-note interplay needs < 10 ms; no API delivers that. The fast layer remains a **local symbolic engine** (Factor Oracle / VMO / grammars) — which is not an LLM, so the "no local LLM" decision still holds. The cloud LLM acts as a meta-controller, rewriting the fast engine's policy every phrase.

**What is genuinely new from the cloud for Architecture C:** multimodal models accept **native audio**. Capturing 8 bars of what the band is playing through BlackHole and sending it for analysis ("this is dragging", "the guitar is masking the vocal") was impossible with a local 9B. That opens a real listening loop in Iteration 3+.

---

## 3. Control plane: CLI vs. API — the distinction that defines the project

You mentioned "the Claude or Google CLI". There is an important architectural difference here, and getting it wrong would cost weeks.

### `claude -p` is **not** a model call

The Claude Code documentation defines print mode as (cite index="56-1">"query via the SDK, then exit"</cite> — (cite index="55-1">headless mode and the Agent SDK describe the same product; print mode is not a lightweight cousin of the SDK, it is the SDK dressed as a command line</cite>. It runs the **full agent loop**: gathers context, calls tools, verifies the work, repeats. The documentation routes this explicitly: (cite index="58-1">Claude Code is primarily a CLI and agentic coding tool, whereas the Claude API is the surface for model calls from your application; for direct model calls, use the Messages API</cite>.

**Practical consequence:** each `claude -p` costs a process spawn, session initialisation and a multi-turn loop of non-deterministic latency — **seconds, with high variance**. That is poison for a scheduler with a musical deadline.

### The correct allocation of each surface

| Surface | Role in GARAGEM | Rationale |
|---|---|---|
| **Messages API (Anthropic) / Gemini API** | **Musical inference plane.** All music generation goes through here | Single call, predictable latency, prompt caching, tool use with a strict schema, streaming |
| **Claude Code (interactive)** | **Tool for building the project itself.** Writing the code for Phases 0–6 | It is what it was made for, and it is excellent at it |
| **Claude Code / Gemini CLI (headless) + MCP** | **Conversational control plane.** Talking to the band in natural language, background tasks | An agentic loop is appropriate when tolerable latency is seconds and the task is multi-step |
| **`garagem-mcp` (our MCP server)** | Bridge between the two worlds | Exposes `set_section`, `set_tension`, `regenerate`, `save_take`, `bake_setlist` |
| **Batch API (Anthropic / Google)** | Pre-production and Setlist mode | 50% discount, 24 h SLA — irrelevant for overnight work |

**Rule:** the musical loop talks to the **API**. The human talks to the **CLI**. The CLI talks to the musical loop **via MCP**. Never the CLI inside the loop.

---

## 4. Feasibility: latency, variance, cost and hardware

### 4.1 Hardware stopped being a problem — and became an advantage

Without a local model, the 24 GB budget looks like this:

| Consumer | Usage |
|---|---|
| macOS + background | 5.0 – 6.5 GB |
| Python runtime + network | 0.3 – 0.6 GB |
| Anti-swap reserve | 2.0 GB |
| **Available to Ableton Live** | **≈ 15 – 17 GB** |

**This is a real and immediate gain in sound quality.** Sets with large sample libraries, multiple convolution reverb instances, heavy amp sims, a 128-sample audio buffer (2.7 ms) with no memory-bandwidth contention against LLM decode. v1.0 spent half its engineering budget defending Ableton from a neighbour that now does not exist. The M4 Pro's 20 GPU cores are free for plugins that use them.

### 4.2 Latency profile — the new map

| Stage | Typical latency | Variance | Comment |
|---|---|---|---|
| RTT Mexico City -> us-east-1 | 40 – 80 ms | low | Fixed, predictable |
| TLS handshake | 0 (persistent connection) | — | **Keep an HTTP/2 pool open and warm** |
| TTFT — fast model (Haiku 4.5 / Flash-Lite) | 300 – 700 ms | medium | Tactical layer |
| TTFT — strong model, no thinking | 0.6 – 1.5 s | medium | |
| TTFT — strong model, thinking on | 2 – 10 s | **high** | Structural layer only |
| Streaming ~800 output tokens | 4 – 12 s | medium | Amortised over the section |
| **p99 of any call** | **2 – 5× the p50** | — | **This is the enemy, not the p50** |
| OSC -> AbletonOSC -> LOM | 5 – 20 ms | low | Unchanged |
| Live's quantised scene launch | sample accurate | — | Unchanged — still the central trick |

**Budget per section @ 132 BPM:**
- An 8-bar section = **14.5 s**; a 16-bar section = **29.1 s**
- A full structural call (chart + 4 parts + dynamics): TTFT ~1.2 s + ~800 output tokens ≈ **6 – 13 s**
- With a **2-section** lookahead -> a budget of **29 – 58 s** to spend 6–13 s -> a **3–4× margin**

That margin is what absorbs the p99. It would not exist in v1.0's per-bar regime — one more reason for the change of granularity.

**Deadline rule:** every call has a `timeout` = 40% of the musical time remaining until the point of use. If it overruns -> cancel, log, use the deterministic engine, and **do not try again for that section**.

### 4.3 Partial streaming as a perceived-latency reducer

Since the output is a line-by-line DSL, the stream can be **parsed incrementally**: drums and bass usually arrive before guitar and keys. With an incremental parser, the first two parts can already be validated and written into the clip while the rest is still being generated. That halves effective latency and gives an elegant degradation path: if the stream is cut short, write what arrived and complete the rest locally.

**Design requirement for the DSL:** order the output by **rhythmic priority** (drums -> bass -> harmony -> lead). v1.0's cascade survives, but as **token order within a single call**, not as four calls. Elegant: the same coherence guarantee, a quarter of the round-trips.

### 4.4 Cost — the arithmetic (and why it is not the bottleneck)

Prices verified in August 2026, per million tokens:

| Model | Input | Cache read | Output |
|---|---|---|---|
| Claude Haiku 4.5 | $1.00 | $0.10 | $5.00 |
| Claude Sonnet 5 | $2.00 (promo until 31 Aug; $3.00 standard) | $0.20 | $10.00 |
| Claude Opus 5 | $5.00 | $0.50 | $25.00 |
| Gemini 3.1 Flash-Lite | $0.25 | $0.025 | $1.50 |
| Gemini 3.6 Flash | $1.50 | $0.15 | $7.50 |
| Gemini 3.1 Pro | $2.00 | ~$0.20 | $12.00 |

Cache hits cost 10% of base input at Anthropic; the Batch API gives a further 50%. The default cache TTL of 5 minutes fits a musical session perfectly, where calls follow one another seconds apart.

**Cost per session (working estimate):**

*Structural layer* — 1 call per section: ~2500 input tokens (2000 cached: DSL rules, personas, session context) + ~800 output.
- Sonnet 5: ≈ **$0.009 per section** -> a 3-minute song (~8 sections) ≈ **$0.08**
- Opus 5: ≈ **$0.023 per section** -> ≈ **$0.19 per song**

*Tactical layer* — Haiku 4.5, ~1500 in (1200 cached) + 120 out ≈ **$0.001 per call**. Even with a cue every 4 bars across an hour of jamming, that is pennies.

**A two-hour session of intense jamming costs between $2 and $8.** Cost is **not** this project's bottleneck for personal use. That frees the model decision to be made on quality rather than price — exactly the opposite of v1.0's situation.

**The real cost risk is not normal use — it is the retry storm.** A bug that makes the orchestrator resend in a loop can burn in minutes what a week of sessions would cost. Therefore: **a budget governor is mandatory from Phase 0** — a hard per-session cap, a per-minute cap, an in-flight call counter, a kill switch. It is not an optimisation; it is a fuse.

### 4.5 New failure modes and their defences

| Failure | Symptom | Defence |
|---|---|---|
| Network drops mid-session | No new sections | Circuit breaker -> deterministic mode; log and retry reconnection in the background |
| Rate limit (429) | Calls rejected | Local token bucket **below** the real limit; backoff only off the critical path |
| p99 tail | Section arrives too late | Per-call deadline (§4.2) + 2-section lookahead |
| Schema-valid but musically invalid response | The band plays something wrong | P4 validator + deterministic repair |
| Provider degrades or changes the model | Behaviour changes without warning | Pin explicit model IDs; musical regression suite in CI |
| Session with no internet (rehearsal, gig) | System useless | **Setlist Mode** (§7, Phase 5) |
| Retry storm | The bill explodes | Budget governor + kill switch |

### 4.6 Libraries — unchanged, minus one removal

`python-osc` (core) · `mido`+`python-rtmidi` (I/O only, never scheduling) · `pretty_midi` and `music21` (offline) · `pydantic` (domain and tool-use schemas) · `hypothesis` (property tests) · `httpx` with a persistent HTTP/2 pool (new, core) · **`mlx-lm`, `llama-cpp-python`, `ollama` — removed.**

---

## 5. Architecture comparison (revised for the cloud)

| Criterion | **A — Offline production** | **B' — Section-shot band** | **C — Reactive improviser** |
|---|---|---|---|
| Achievable musical quality | **Maximum** (strong model + thinking + batch) | High | Medium-high (depends on the symbolic engine) |
| Perceived latency | Irrelevant | Good (masked by a 2-section lookahead) | Excellent (< 10 ms, local) |
| Cost per minute of music | Highest (but still trivial) | Low | Very low |
| Robustness to network loss | Not applicable (offline by nature) | **Good** (degrades to deterministic) | **Excellent** (the core is local) |
| Integration complexity | Low | Medium | High |
| Use of the MiniLab 3 | None | Macros + cues | Primary instrument |
| Test / CI surface | Excellent | Good (API is mockable) | Poor (needs a human) |
| Fits rock | Yes | **Yes, ideally** | Partly |
| Fits jazz | **Yes, now** (composition/arrangement) | Partly | **Yes** (interplay) |
| Time to first result | ~2 weeks | ~4–5 weeks | ~9+ weeks |

**A note on jazz:** the cloud changes the picture in part. A frontier model understands reharmonisation, rootless voicings, walking bass with voice leading and tritone substitution far better than any viable local model — so **jazz composition and arrangement become viable as early as Iteration 2**. But what defines jazz as *played* is reactive interplay on a millisecond scale, and there the cloud is strictly worse than local. v1.0's separation holds: **written jazz in Architecture A/B'; improvised jazz only in Architecture C.**

---

## 6. Decision and ADRs

### MVP architecture: **B' — section-shot band with three rates**

**Rationale:**
1. **API latency is only amortisable at section scale.** It is the only granularity where the margin (3–4×) absorbs the p99.
2. **Coherence between instruments becomes free.** One call that sees the whole section produces parts that talk to each other — no negotiation protocol, no cascade, no complex blackboard.
3. **The clip-ahead trick stays intact and remains the highest risk-reduction decision.** Writing into scene N+1 and letting Live's launch quantisation do the switch is what keeps timing perfect regardless of how slow the cloud is.
4. **It degrades instead of failing.** The three layers have independent failure: the reflex layer never fails (it is local), the tactical layer is optional, the structural layer has lookahead.
5. **It frees 15+ GB for Ableton**, which converts directly into sound quality.

### ADRs

| ADR | Decision | Status vs. v1.0 |
|---|---|---|
| ADR-001 | Write clips into the next scene + quantised launch | **Retained** — it is the foundation |
| ADR-002 | Compact textual symbolic DSL | **Retained**, motivation revised (cost and parsing, not decode) |
| ADR-003 | ~~Agent cascade~~ -> **rhythmic priority order within a single call** | **Replaced** |
| ADR-004 | Inference triggered by a musical event, at section granularity | **Revised** (was per bar) |
| ADR-005 | The deterministic engine as an instrument, not a fallback | **Reinforced** |
| ADR-006 | Own `asyncio` core + Pydantic | **Retained** |
| ADR-007 | Rock for the MVP | **Retained** |
| ADR-008 | ~~Benchmark local backends~~ -> **Messages API / Gemini API directly; CLI out of the loop** | **Replaced** |
| ADR-009 | **Tool use with a strict JSON Schema** replaces GBNF | **New** |
| ADR-010 | **Budget governor and circuit breaker from Phase 0** | **New** |
| ADR-011 | **Incremental stream parsing**, output ordered by rhythmic priority | **New** |
| ADR-012 | **Provider behind a port**, with Anthropic and Google adapters | **New** — avoids lock-in and enables per-layer routing |
| [ADR-013](ADR-013-set-as-code-in-toml.md) | **"Set as Code" in `session.toml`**, validated and never created; Drift instead of `DLSMusicDevice` | **New** — supersedes §7 and §8 in part |
| [ADR-016](ADR-016-the-producer-thread.md) | **The producer thread**; `transport/` may not import `llm/` | **New** — invariant 1, enforced statically |
| [ADR-017](ADR-017-composition-over-generation.md) | **The model writes the groove; the engines write the form** | **New** — supersedes part of §7's Phase 4 |
| [ADR-018](ADR-018-the-ab-waiver.md) | **The Phase 3 blind A/B is waived, not met**; threshold intact, carried into Phase 4 | **New** — waives one clause of §7's Phase 3 exit criterion |
| [ADR-019](ADR-019-the-ear-is-the-instrument.md) | **The ear is the instrument**; no metric is a target until one passes a pre-registered preference gate | **New** — amends §7's Phase 4 metrics clause; discharges ADR-018's debt #1 |
| [ADR-020](ADR-020-endings-are-composed-over-the-score.md) | **Endings are composed over the finished score**, by the scheduler: fills, builds, stops, the final chord | **New** — realises §7's Phase 4 transitions; refines ADR-017 |
| [ADR-021](ADR-021-the-minilab-joins-phase-4.md) | **The MiniLab joins Phase 4** as the tactical layer's instrument; Setlist Mode and voice stay in Phase 5 | **New** — amends §7's Phases 4 and 5 |
| [ADR-022](ADR-022-a-cue-costs-a-fire-never-a-write.md) | **A cue costs a fire, never a write**: candidates, legato variants, re-plan, explicit precedence | **New** — extends ADR-001 to human cues |
| [ADR-023](ADR-023-the-second-ab-waiver.md) | **The blind A/B is waived a second time**, threshold intact; when the model is worth calling opens Phase 5 | **New** — waives §7's A/B clause again; amends §7's Phase 5 |

ADR-001 is written down in [`ADR-001-clip-ahead-and-quantised-launch.md`](ADR-001-clip-ahead-and-quantised-launch.md).

---

## 7. MVP roadmap (revised)

### **Phase 0 — Foundation, instrumentation and fuses** · ~1 week

- Repo with `uv` + `ruff` + `mypy --strict` + `pytest`; hexagonal skeleton.
- `LLMProvider` port + `AnthropicAdapter` and `GoogleAdapter`; `httpx` client with a persistent, warm HTTP/2 pool.
- **API latency rig:** measures `TTFT`, `tokens/s`, **p50/p95/p99** per model, on your link, at different times of day. Variance is the interesting datum, not the mean.
- **Budget governor** (ADR-010): per-session cap, per-minute cap, in-flight call count, kill switch, real-time cost counter in the TUI.
- **Circuit breaker** with closed/open/half-open states and automatic degradation to deterministic mode.

**Exit criterion:** a reproducible latency/variance report per model; the governor demonstrably cuts a simulated retry storm in < 2 s.

### **Phase 1 — The Bridge** · ~1 week

Unchanged from v1.0. AbletonOSC + a typed `LiveClient` + `session.yaml` ("Set as Code", idempotent provisioning via the LOM) + `FakeDawAdapter`. Provisional instruments via `DLSMusicDevice` (the AU General MIDI that ships with GarageBand) — focus on timing, not timbre.

**Superseded in part by ADR-013:** the file is `session.toml` (`tomllib` is stdlib), the provisional instrument is **Drift** (`DLSMusicDevice` no longer ships with macOS), the bootstrap validates rather than provisions (the LOM cannot load an instrument, so a track created from code would be silent), and this machine runs Live 12 Lite with its 8-track cap. The clip-ahead half of the phase is written down in ADR-001.

**Exit criterion:** an integration test writes `Em–C–G–D` across 4 bars, fires the scene, and audio comes out of the Scarlett. Idempotent.

### **Phase 2 — Clock, Buffer and Deterministic Engine** · ~2 weeks

**Still the project's most important gate — and now more so, because it is what guarantees P2 against network loss.**

`BarClock` slaved to the transport · `ScoreBuffer` with a 2-section window · clip-ahead scheduler with double scene buffering · deterministic rock engines (drums, bass, guitar, keys) · the `theory/` layer (scales, voicings, validator, repairer) · deterministic seeded humanisation.

**Exit criterion:** 3 minutes of autonomous rock arrangement, with section changes, **zero dropouts, zero glitches, zero network**. A musician listening blind rates it "an acceptable demo".

### **Phase 3 — First structural generation (section-shot)** · ~2 weeks

- Strict tool-use schema for the complete section; DSL ordered by rhythmic priority.
- **Incremental stream parser** (ADR-011) writing progressively into the Score Buffer.
- Semantic validator + repairer + fallback telemetry.
- Prompt caching with the stable block (DSL rules + personas + session context) marked for cache.
- Per-layer routing: strong for structure, fast for tactics.

**Exit criterion:** ≥ 95% schema conformance on the first pass; ≥ 80% validator approval without repair; p95 section latency < 40% of the available musical time; a blind A/B test where the generated section is preferred over the deterministic one in ≥ 65% of cases.

**The A/B clause was waived on 2026-09-01, not met** — 12 of 24 pairs, parity — with its
threshold intact and carried into Phase 4 ([ADR-018](ADR-018-the-ab-waiver.md)). The other
three were met: 97%, 93%, p95 0.84x.

### **Phase 4 — The full Band and the tactical layer** · ~2 weeks

**Superseded in part by ADR-017 and by `phase-3-findings.md` §14.** A per-section
arrangement *in one call* was measured and does not fit the deadline: 30 attempts, 30
cancellations. The arrangement is composed deterministically over the model's groove
instead. The tactical layer's 1–4 bar rewrite is also not feasible as written — the
deadline is 0.73–2.91 s and `claude-haiku-4-5` measured p50 1.83 s, max 15.04 s — so a cue
takes effect deterministically on the next bar and the model refines the next section.

- Complete per-section arrangement (4+ instruments in one call), with a dynamics curve and transitions between sections (fills, breaks, builds).
- Tactical layer with a fast model: human cues rewrite 1–4 bars under the current plan.
- **Automated coherence metrics** in the event log: bass/kick alignment, harmonic conformance, register spread, density vs. target `tension`.
- Musical regression suite in CI with recorded API responses (VCR), to detect model drift.

**Exit criterion:** 8 minutes of continuous session; no deadline overrun left unhandled; metrics within range; cost per session within the declared budget; a chaos test (kill the network mid-session) with no audible interruption.

**Plus the debt carried from Phase 3** (ADR-018): the coherence metrics must first
separate the three "messy" losses in `bench/ab-phase3-final.jsonl` from the other nine,
and the blind A/B is re-run at this phase's close on the same design and the same
threshold — 8 of 12.

**"Metrics within range" is amended by [ADR-019](ADR-019-the-ear-is-the-instrument.md)**,
accepted on 2026-09-12: every section carries its metrics in the event log, and no metric is
used as a target until one has passed a pre-registered preference gate. Three proposed
mechanisms failed to predict the ear (`phase-4-findings.md` §1, §3, §5), which discharges
the calibration debt above by answering it. The A/B re-run at 8 of 12 is untouched.

**The MiniLab 3 moves into this phase** ([ADR-021](ADR-021-the-minilab-joins-phase-4.md),
2026-09-12) as the tactical layer's input, with tension and density as its first two macros.
A cue costs a fire, never a write ([ADR-022](ADR-022-a-cue-costs-a-fire-never-a-write.md)).
The exit criterion gains three lines: a cue lands on the next bar, measured in the event
log; the section after a jump is requested from the model and a stale one never plays; and
a session directed from the MiniLab is judged by ear.

### **Phase 5 — Human in the loop and Setlist Mode** · ~2 weeks

- MiniLab 3: 8 encoders -> macros (`tension`, `density`, `brightness`, `syncopation`, `harmonic_risk`, `humanize`, `arrangement_size`, `lead_activity`); pads -> structural cues and `KEEP`/`VETO` curation (which becomes a preference dataset in the event log).
- Reading the MiniLab directly in Python via CoreMIDI, in parallel with Live.
- Conversational control plane via `garagem-mcp` (headless Claude Code / Gemini CLI / OpenClaw as the client).
- **Setlist Mode — the architectural answer to network dependence:** pre-generate an entire repertoire online (sections, variants, fills, transitions), persist it to disk as parameterised deterministic material, and **play it fully offline**. Connected pre-production, disconnected performance. This is how the system becomes usable on a stage.

**Exit criterion:** a 10-minute session driven only by the MiniLab and by voice; and a 10-minute session **with the Wi-Fi off** using a pre-baked setlist.

**Amended by [ADR-021](ADR-021-the-minilab-joins-phase-4.md)**: the MiniLab reading and its first two
macros (tension, density) are delivered in Phase 4. This phase keeps Setlist Mode, the
voice/MCP control plane, KEEP/VETO curation and the other six macros; the exit criterion's
MiniLab half is already met by the time it starts.

**Amended by [ADR-023](ADR-023-the-second-ab-waiver.md)**: the blind A/B reached parity at
Phase 4's close (18 of 36 pooled), so this phase opens with *when the model is worth calling
at all*, ahead of Setlist Mode, whose offline case assumes the answer.

### **Phase 6 — Timbre, mixing and the asset bakery** · ~2 weeks

A sound design agent via LOM device parameters; a mixing agent (gains, pan, sends, dynamics between sections); background audio asset generation using the **Batch API** (50% discount, 24 h SLA — perfect for overnight work scheduled by OpenClaw's heartbeat); replacing `DLSMusicDevice` with Live Suite instruments.

### **Phase 7+ — Extensions**

Architecture C (local symbolic engine + M4L for sample-accurate scheduling) · a **multimodal listening loop** (sending captured audio via BlackHole for analysis by a multimodal model) · swing and microtiming via the Groove Pool · jazz.

---

## 8. Repository structure

```
garagem/
├── pyproject.toml
├── session.toml                   # "Set as Code" — see ADR-013
├── budget.yaml                    # cost caps, rate limits, deadlines
├── src/garagem/
│   ├── domain/                    # PURE: Note, Bar, Chart, Section, Groove, Tension
│   ├── dsl/                       # incremental parser, serializer, tool-use schemas
│   ├── theory/                    # scales, voicings, validator, repair
│   ├── engines/                   # deterministic engines (rock/*)
│   ├── agents/                    # personas, prompts, routing policies
│   ├── llm/                       # LLMProvider port + adapters (anthropic, google, fake)
│   │   ├── governor.py            # budget, token bucket, kill switch
│   │   └── breaker.py             # circuit breaker
│   ├── daw/                       # DawPort port + adapters (abletonosc, fake)
│   ├── transport/                 # BarClock, ScoreBuffer, clip-ahead scheduler
│   ├── setlist/                   # pre-production and offline playback
│   ├── obs/                       # JSONL event log, metrics, TUI (real-time cost)
│   └── mcp/                       # garagem-mcp server
├── m4l/                           # .amxd devices (Phase 7)
├── cassettes/                     # recorded API responses for CI
└── tests/{unit,property,golden,integration}
```

Rules verified in CI: `domain/` and `theory/` free of I/O; `agents/` free of adapter imports; **no CI test makes a real network call** (cassettes mandatory); generation is deterministic given a seed.

---

## 9. Risks (revised)

| Risk | Prob. | Impact | Mitigation |
|---|---|---|---|
| The API's p99 tail blows the lookahead | **High** | Medium | 2-section lookahead; deadline at 40%; degradation |
| Network loss during a session | Medium | **High** | Circuit breaker + deterministic engine + Setlist Mode |
| Retry storm / runaway cost | Medium | **High** | Governor with a kill switch (Phase 0, not later) |
| Provider changes model behaviour | Medium | Medium | Pinned IDs + musical regression suite with cassettes |
| Rate limit during intense jamming | Medium | Medium | Local token bucket below the real limit |
| Generic output / "AI slop" | Medium | **High** | Strong model + prompting with concrete references + human curation in the event log |
| Accumulated complexity kills the iteration | Medium | High | Per-phase death criteria; no phase starts before the previous one passes |

**Experiments for Iteration 2:**
- **E1 — Optimal granularity:** 8 vs. 16 vs. 32 bars per call. Where does coherence stop improving and latency start hurting?
- **E2 — Model routing:** Opus 5 vs. Sonnet 5 vs. Gemini 3.1 Pro on the structural layer, blind test. Is it worth 2.5× the cost?
- **E3 — Thinking on vs. off** on the structural layer: how much musical quality per second of latency?
- **E4 — One call vs. cascade:** measure the Phase 4 coherence metrics under both topologies. Confirm (or overturn) ADR-003.
- **E5 — Effectiveness of incremental parsing:** effective perceived latency with and without progressive writing.
- **E6 — DSL density:** with fast remote decode, does the compact DSL still pay off? Test a more verbose representation that is more legible to the model — it may produce better music for a few more cents.

---

## 10. Out-of-the-box ideas (candidates)

1. **Pre-generating variants + Follow Actions.** Generate 4 variants of a section ahead of time and let the real-time layer merely *choose*. This decouples decision latency from generation latency — the choice comes to cost nothing. Live's Follow Actions implement this natively. **With the cloud this got cheaper, not more expensive**, because all four variants fit in a single call.
2. **Setlist Mode as a product, not a mitigation.** Connected pre-production plus offline performance is how a real musician works. Worth treating as a first-class feature.
3. **Overnight Batch API.** Bake 200 sections of material through the night at half price, curate in the morning. The library grows while you sleep.
4. **The event log as a preference dataset.** Every `VETO` on the MiniLab is a preference pair. With the cloud it does not become a local fine-tune, but it becomes something perhaps better: a **curated, cached context block** — "this is the user's taste, demonstrated across 200 examples" — that makes the strong model get it right more often on the first try.
5. **Multimodal listening loop.** Send real mix audio for critical analysis ("the bass is masking the kick between 60 and 90 Hz"). Impossible with a local 9B; trivial with a cloud multimodal model.
6. **Latency budget as a musical resource.** Predictable moments (a 4-bar fill, a pedal, a break) are windows of cognitive slack — schedule the heavy call during them. It is what a human arranger does.
7. **Adaptive routing by criticality.** The chorus gets the strong model; a repeating verse gets the fast one; an identical second repeat gets no model at all (event log cache). The system learns where spending is worth it.

---

## 11. Questions for Iteration 2

1. **Session target:** a produced Live Set (asynchronous, editable) or a live-directed performance? This weighs between Architecture A and B'.
2. **Do you play along or direct?** If you play, Architecture C rises in priority and Setlist Mode becomes urgent.
3. **Does offline matter?** If there is any stage or rehearsal scenario without reliable internet, Setlist Mode moves out of Phase 5 and into Phase 2.
4. **Acceptable cost ceiling per session?** I need this to calibrate the governor and model routing. (My guess: you will find the real cost irrelevant, but the number needs to exist.)
5. **Anthropic, Google, or both?** I recommend implementing both adapters in Phase 0 and deciding by measurement in Phase 3 — keeping the door open costs about 200 lines.
6. **Rock subgenre for the MVP:** alternative/indie, hard rock, post-rock, math rock? Math rock breaks the simple-grid premise and would change Phase 2 decisions.
7. **Success metric for Iteration 2:** I propose *"a 3-minute rock arrangement, autonomously generated, that survives a blind listen"* — and, as a second criterion, *"that keeps playing when I switch off the Wi-Fi halfway through"*.

---

*End of Iteration 1, v2.0. Suggested next step: Phase 0 (one week) — latency rig, budget governor and circuit breaker. The p99 numbers on your link are the datum that calibrates the rest of the roadmap.*
