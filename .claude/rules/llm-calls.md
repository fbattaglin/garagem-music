---
paths:
  - "src/garagem/llm/**/*.py"
  - "src/garagem/agents/**/*.py"
---

# Model calls

- Every call goes through the `governor` (budget) and the `breaker` (circuit breaker).
  A call that skips either is a bug — including in a test script.
- `deadline` is a required argument, never optional with a generous default.
- **No retries on the critical path.** If the call was for the section about to play,
  failed is failed: log it and fall back to the deterministic engine.
- Structured output via tool use with a strict JSON Schema. Never ask for "respond in
  JSON" in the prompt and parse free text.
- The stable block of the prompt (DSL rules, personas, session context) is marked for
  prompt caching and **must not vary between calls** — any change to it invalidates the
  cache and multiplies latency.
- Models are referenced by explicit ID coming from configuration, never by an alias
  such as "the fast model" hard-coded in the source.
- Write the adapter against the `LLMProvider` port. Nothing in `agents/` should know
  whether we are talking to Anthropic or Google.

Tests in this layer use cassettes. If you need a new response, record it explicitly
with `scripts/record_cassette.py` — do not make the call inside the test.
