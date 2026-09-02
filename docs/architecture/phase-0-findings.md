# Phase 0 findings

What the instrumentation actually measured, as opposed to what section 4 of ADR-000
predicted. Every number here comes from `bench/latency.jsonl` and the two recordings in
`cassettes/`; the tables regenerate with `uv run python scripts/bench_latency.py
--report-only`.

Three measurement windows, all on **2026-08-30**: morning-to-midday (09:03-10:09,
28 calls, $0.15), afternoon (15:21-15:23, 25 calls, $0.099) and evening (18:00-18:02,
25 calls, $0.1015). **78 samples, $0.35 spent, and the Phase 0 criterion is met.**

Finding 1 was rewritten once by the second window and settled by the third; read it
before trusting anything written after only one.

## 1. The tail is a cold-start tail - but a *first-ever* one, not a per-process one

**This finding was written after one window and is materially wrong. The second window
rewrote it.** The original text said the outlier is "almost always the first call of a
model's run", concluded that a jam starts cold and would pay 6-14 s on its first
section, and declared that **"warming is not an optimisation, it is a correctness
requirement"**. That conclusion sized a startup step that Phase 3 would have built.

Section 4.2 predicted a p99 of 2-5x the p50. Here is every call, in the order it was
made, across both windows:

| model | morning | afternoon | evening |
|---|---|---|---|
| `claude-opus-5` | **6.11** 1.49 1.77 1.63 1.54 2.41 | 2.64 1.61 1.50 2.28 1.69 | 1.50 1.29 1.28 1.32 1.58 |
| `claude-sonnet-5` | 1.46 1.41 1.49 1.52 1.42 1.47 | 1.26 1.38 1.42 1.43 1.38 | 1.48 1.37 1.45 1.31 1.39 |
| `claude-haiku-4-5-20251001` | **14.38** 1.14 0.79 0.78 1.54 | 2.24 0.90 0.60 2.21 0.62 | 1.08 1.56 0.88 **7.37** 0.81 |
| `gemini-flash-lite-latest` | 1.16 0.81 FAIL **31.98** FAIL **25.01** | 0.79 0.96 0.87 0.76 1.24 | 0.92 0.94 1.15 0.76 0.77 |
| `gemini-3.6-flash` | 12.31 10.19 19.45 16.17 26.65 | 6.89 FAIL FAIL 7.06 FAIL | **47.82** FAIL 8.09 FAIL FAIL |

The afternoon and evening runs were each a **fresh process, a fresh connection pool and
a fresh TLS handshake** - everything the original finding blamed. Neither paid the
penalty. Opus opened the evening at 1.50 s, its *fastest* window; the 6.11 s that still
sets its `max` is the very first call this project ever made.

### The verdict, now that three windows exist

**The morning's fat tail was first contact, not the time of day.** Two later cold
processes, six and nine hours apart, came back clean. What the original finding called
"the first call of a model's run" was really the first call of the *account's* run.

**A residual per-process warm-up of about a second exists, and it is small.** Opus
opened its afternoon window at 2.64 s against a 1.69 s median. It is worth having;
nothing should be designed around it.

**But cold start is not the whole tail either, and this is the new finding.** Haiku's
worst evening call - 7.37 s - was the **fourth** of five, with 0.88 s before it and
0.81 s after. That is not a cold start, not a time of day, and not a failure. It is
simply the tail, arriving unannounced in the middle of a warm run. §4.2 predicted
exactly this and it is the reason the deadline exists.

**`claude-sonnet-5` never paid any of it.** Sixteen calls across three windows, every
TTFT between 1.26 s and 1.52 s - a total spread of 260 ms - with no cold start, no
mid-run spike and no failure. It is the only model measured that behaves like a
component rather than like a service.

### What this changes

- **Warming is an optimisation, not a correctness requirement.** The original text said
  the opposite, in bold, and it would have sized a startup step around a 6-14 s penalty
  that was a first-contact artefact.
- **The p99/p50 ratios in the aggregate report are still first-contact artefacts.**
  Opus reads 3.9x and Haiku 13.3x, and both maxima are morning calls that three later
  windows never reproduced. Read the per-window table above when reasoning about the
  tail; the aggregate will only recover once enough samples move a nearest-rank
  percentile.
- **The deadline still has to be defended, just not against the shape we assumed.** The
  enemy is Haiku's 7.37 s in the middle of a healthy run, not the first call of a jam.

## 2. Gemini 3.6 Flash cannot serve the structural layer at all, on this tier

This is not a tail problem like Opus's, it is the whole distribution: **5 of 5 calls**
came back after the 5.8 s section deadline, with a p50 of 16.17 s - roughly 3x the
deadline, not a rare excursion past it. Recording even one cassette took several
attempts: two of six real recording attempts also hit a 503 ("high demand") before one
succeeded, on top of the deadline misses.

That is consistent with finding 7: this is free-tier queueing, not a property of the
model. But the practical conclusion for now is unambiguous - **the deterministic engine
would have carried every single one of these sections**, which is exactly the
degradation path (P2) working as designed, not a failure. It just means this key
currently has no model that can serve the structural layer within budget: Gemini 3.1
Pro is unreachable (finding 6), and Gemini 3.6 Flash is reachable but too slow on this
tier. Nothing here says the *model* can't do it - only that this key, on this tier,
can't get an answer from it in time.

## 3. Opus 5 does not fit inside the section deadline reliably

With the 5.8 s deadline the recipes use (40% of an 8-bar section at 132 BPM), 1 of the
6 Opus calls would have been cancelled - the cold one. Sonnet 5 would have made all six
with 4 s of margin, at 40% of the price, and its variance is the lowest of anything
measured: six calls inside 110 ms of each other.

That is not enough evidence to route the structural layer to Sonnet, but it makes E2
sharper than it was written: the question is no longer "is Opus worth 2.5x the cost",
it is "is Opus worth 2.5x the cost **and** the tail risk". A blind test that ignores
variance would answer the wrong question.

## 4. Gemini delivers tool arguments whole - now demonstrated, not assumed

`cassettes/anthropic_section.jsonl` carries the same section as
`cassettes/google_section.jsonl` and `cassettes/google_section_flash.jsonl`. Anthropic
sent the tool input in **45** `partial_json` fragments; both Gemini models sent it in
**one**, complete - the model has no bearing on this, it is a property of the API.

So ADR-011's incremental parser buys, on the structural call:

- **Anthropic:** the whole predicted gain. Drums and bass are parseable well before the
  keys arrive.
- **Gemini:** nothing at all for tool use. The section is either absent or complete.

This is now pinned by a test (`test_only_anthropic_actually_streamed_the_tool_arguments`)
rather than by a paragraph, and it is a direct input to E2 and E5. If routing ever sends
a structural call to Gemini, the lookahead for that call has to be sized for the whole
section, not for its first line.

## 5. Prompt caching works, and it is visible in the recording

The recorded Opus call reports `cache_read_tokens: 740` against `input_tokens: 231` -
the stable prefix was read from cache, not re-sent, exactly as the section 4.4 cost
argument requires. Worth keeping an eye on: any edit to `scripts/recipes/section_brief.py`
invalidates that prefix and the next call pays a cache write at 1.25x input.

## 6. Three things the wire formats did not match

- **Haiku 4.5 rejects `effort` outright** ("This model does not support the effort
  parameter", HTTP 400). It does not ignore it. `Request.effort` is therefore
  `Effort | None`, where `None` means "send no preference" - and the tactical layer is
  exactly the layer that runs on those models.
- **`gemini-3-pro-preview` is gone.** The API answers 404 pointing at
  `gemini-3.1-pro-preview`, and recommends a newer *Interactions API* over
  `generateContent`. We stay on `generateContent` for now: it is stable, documented and
  does SSE. Worth revisiting before the adapters carry any weight.
- **Gemini 3.1 Pro is not served on the free tier.** The key answers 429 with
  `limit: 0` on the input-token quota. `config/models.toml` and
  `scripts/recipes/google_section.py` now point the structural role at
  **Gemini 3.6 Flash** instead - the strongest model this key can call, and priced in
  section 4.4 - with `google_section_flash.py` (Flash-Lite) still covering the tactical
  role. **This does not close the E2 comparison**, which needs Pro against Opus on the
  same briefing; it only gets a real cassette and a real latency number onto the
  record without billing. Swap back to Pro once billing is enabled - see finding 2 for
  why that number is likely to look very different from 3.6 Flash's.

## 7. The free tier is not a measurement surface

Two of six Flash-Lite calls took 25 s and 32 s, one returned 503 "experiencing high
demand", and recording the 3.6 Flash cassette needed several attempts for the same
reason (finding 2). Those numbers say something about the free tier's queue, not about
Gemini's latency. Any Google figure in the report is provisional until the key is on a
paid tier.

## Decision: default to Anthropic until Google is measurable

Every Anthropic model measured so far — Opus 5, Sonnet 5, Haiku 4.5 — served the
structural briefing reliably and within (or close to) the section deadline. Every
Google model reachable on this key either missed the deadline outright (3.6 Flash,
finding 2) or showed free-tier queueing severe enough to make the numbers provisional
(finding 7), and the model the roadmap actually wants for the structural role
(Gemini 3.1 Pro) cannot be reached at all without billing.

So, until billing is enabled and Gemini 3.1 Pro can be measured under the same
conditions: **generation defaults to Anthropic models.** This is a routing decision,
not an architecture one — `LLMProvider` (ADR-012) exists precisely so this can flip
back without touching a caller, and the Google adapter, its cassettes and its tests
stay in the suite so that flip is a config change, not a rewrite, once the numbers
support it. There is no routing policy in the code yet (that lands in Phase 4, per
`STATUS.md`); this decision is the input that policy starts from — the "is Gemini worth
the incremental parser's loss on tool use, and is it fast enough at all" half of E2 is
already answered "not on this tier"; what is still genuinely open is Opus vs. Sonnet
(finding 3) and Pro vs. Opus once Pro is reachable.

## What is still open

- **Two more measurement windows** (afternoon and evening) for the Phase 0 criterion.
  The report names the missing buckets on every run:

      uv run python scripts/bench_latency.py --runs 5 --yes

- **Billing on the Gemini key**, then point `google_section.py` and
  `config/models.toml` back at `gemini-3.1-pro-preview` with `deadline_s=5.8`,
  re-record, and re-run the rig. Until then, the structural-layer number for Google is
  Gemini 3.6 Flash's - and finding 2 says it should not be read as representative of
  what Pro would do.
- **A warm-up step at startup**, following from finding 1.
