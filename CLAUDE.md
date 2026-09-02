# GARAGEM — multi-agent music generation system

A Python ecosystem that generates, arranges and manipulates music in near-real time,
driving Ableton Live through AbletonOSC. Cloud inference (Anthropic / Google).

Full architecture and ADRs: `docs/architecture/`. Read on demand, not at session start.

## Language

**English everywhere — code, comments, docstrings, tests, documentation and commit
messages.** No exceptions. Conversation with the user may be in Portuguese; anything
written to a file is in English.

## Commands

- `uv sync` — install dependencies
- `uv run pytest` — tests (unit + property + golden). **Never touches the network.**
- `uv run pytest -m live` — integration tests; requires Ableton Live open with AbletonOSC active
- `uv run ruff check --fix . && uv run ruff format .` — lint and formatting
- `uv run mypy` — strict typing
- `uv run python scripts/bench_latency.py` — measures p50/p95/p99 TTFT per model.
  Estimates and stops unless `--yes`; spends real money and needs API keys.
- `uv run python scripts/bootstrap_set.py` — validates the Live Set against `session.toml`;
  `--apply` repairs tempo, quantisation and track names. Never creates a track (ADR-013).
- `uv run python scripts/probe_live.py` — walks every AbletonOSC address the adapter uses
  and reports what came back. Read-only; the cheapest place to find a wrong constant.
- `uv run python scripts/install_abletonosc.py` — installs AbletonOSC into Live's Remote
  Scripts. Enabling the Control Surface and restarting Live stay manual.

Run `ruff` and `mypy` before any commit.

## Layout

- `src/garagem/domain/` — pure musical model (Note, Bar, Chart, Section). No I/O.
- `src/garagem/theory/` — scales, voicings, validator, repairer. No I/O.
- `src/garagem/dsl/` — incremental parser, serializer, tool-use schemas
- `src/garagem/engines/` — deterministic generators (the musical floor, no LLM)
- `src/garagem/agents/` — personas, prompts, routing policies
- `src/garagem/llm/` — `LLMProvider` port + adapters + governor + circuit breaker
- `src/garagem/daw/` — `DawPort` port + AbletonOSC adapter + fake
- `src/garagem/transport/` — BarClock, ScoreBuffer, clip-ahead scheduler
- `src/garagem/setlist/` — online pre-production, offline playback
- `src/garagem/obs/` — JSONL event log, metrics, latency rig, TUI
- `session.toml` — "Set as Code": the Live Set the bootstrap validates against (ADR-013)
- `config/models.toml` — the model catalogue: IDs, effort and prices. The only place
  a model ID or a price is written down.
- `config/budget.toml` — what one performance may spend and what it is expected to cost.
  The measurement rigs keep their own caps; a bench round is not a session.

## Invariants (non-negotiable)

1. **Two clocks.** The musical clock (< 2 ms jitter) and the cognitive one (seconds)
   are separated by a data structure — the ScoreBuffer — never by a function call.
2. **The system plays without a network.** Every path that uses an LLM has a local
   deterministic counterpart. An API failure degrades the music; it never silences it.
3. **No network, allocation or JSON on the real-time path.**
4. **Never trust model output.** Strict schema + deterministic musical validator.
5. **Never retry on the critical path.** A retry is a planning decision, not an
   execution one.
6. **Timing is Live's problem.** We write clips into the next scene; Live's launch
   quantisation performs the switch. Never rewrite a clip that is playing.
7. **Every generation is deterministic given a seed.** Seeds go into the event log.

## Conventions

- Python 3.12+, strict typing, `pydantic` for domain models and schemas
- Every agent decision, fallback and human veto becomes an event in the JSONL event log
- Network tests use cassettes in `cassettes/`. A test that makes a real call is a bug.
- Ask before adding a new dependency; the project is deliberately lean
