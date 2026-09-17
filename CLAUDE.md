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
  `--apply` repairs tempo, quantisation, track names and track arm. Never creates a track
  (ADR-013).
- `uv run python scripts/probe_live.py` — walks every AbletonOSC address the adapter uses
  and reports what came back. Read-only; the cheapest place to find a wrong constant.
- `uv run python scripts/install_abletonosc.py` — installs AbletonOSC into Live's Remote
  Scripts. Enabling the Control Surface and restarting Live stay manual.
- `uv run python scripts/probe_minilab.py` — lists what the MiniLab 3 sends, control by
  control. Read-only: opens inputs, never an output.
- `uv run python scripts/spike_cues.py` — asks the real Set how clip launches, legato and
  track stops behave (ADR-022). Changes the Set and puts it back; refuses if it is playing.
- `uv run python scripts/spike_voice.py` — parked by ADR-025. A stand-in MCP listener, and the
  command that starts a locked-down Claude Code conductor session with Portuguese dictation.
  `--report` reads how long a spoken cue took to arrive. Changes nothing, needs no Live;
  standard library only.
- `uv run python scripts/rehearse_session.py` — plays an 8-minute generated, conducted session
  offline and predicts its cost and the model's share; `--network-lost-at-s` rehearses the
  chaos test. No network, no Live, no money.
- `uv run python scripts/bake_setlist.py setlists/<name>.toml` — bakes a setlist: the model
  writes each song's sections once into `<name>.json` (ADR-024). Estimates and stops unless
  `--yes`; spends real money. `--fake` bakes the floor's own DSL, free and offline.
- `uv run python scripts/jam.py --setlist setlists/<name>.json --song N` — plays a baked song
  from disk: no network, no key. It reports Phase 5's criteria; `--share N` adds the line for how
  many sections must come from the setlist's takes (ADR-025).
- `uv run python scripts/curate_setlist.py setlists/<name>.json` — writes the keeps and vetoes
  struck on pads 4 and 7 into the setlist, from `bench/jam.jsonl`. `--dry-run` writes nothing.
- `uv run python scripts/audition_shuffle.py` — the five-minute blind check of the shuffle fix
  (ADR-024). `--table` shows the takes and the five chosen; the run needs Terminal and Live.
  No model call.
- `uv run python scripts/record_regression.py` — records the musical regression set that
  `tests/regression/` judges in CI. Estimates and stops unless `--yes`; spends real money.
  `--replay` reports on the recording for free.

Run `ruff` and `mypy` before any commit.

## Layout

- `src/garagem/domain/` — pure musical model (Note, Bar, Chart, Section). No I/O.
- `src/garagem/theory/` — scales, voicings, validator, repairer. No I/O.
- `src/garagem/dsl/` — incremental parser, serializer, tool-use schemas
- `src/garagem/engines/` — deterministic generators (the musical floor, no LLM)
- `src/garagem/agents/` — personas, prompts, routing policies
- `src/garagem/llm/` — `LLMProvider` port + adapters + governor + circuit breaker
- `src/garagem/daw/` — `DawPort` port + AbletonOSC adapter + fake
- `src/garagem/transport/` — BarClock, ScoreBuffer, CueQueue, clip-ahead scheduler
- `src/garagem/control/` — `ControllerPort` + MiniLab 3 adapter (`mido`) + fake. Infrastructure;
  never imported by `transport/` or the pure layers (ADR-021, ADR-022)
- `src/garagem/setlist/` — online pre-production, offline playback. The format only; never
  imports `llm/`, `daw/` or `transport/` (ADR-024)
- `setlists/` — setlist specs (`.toml`, written by hand) and their bakes (`.json`)
- `src/garagem/obs/` — JSONL event log, metrics, latency rig, TUI
- `session.toml` — "Set as Code": the Live Set the bootstrap validates against (ADR-013)
- `controller.toml` — "Controller as Code": which pad and knob asks the band for what.
  Every MIDI number in it was heard by `scripts/probe_minilab.py`, none guessed.
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
- **A musical change passes on a short listen** (ADR-025). Fabiano hears it in a session he plays
  anyway, and his verdict is quoted in the findings. Pre-registration and thresholds are for
  decisions that cost money or are hard to reverse. A findings section fits on a screen. No
  metric is a target (ADR-019).
- **Live generation is frozen** (ADR-025). `jam.py --generate` stays working and tested; new
  model work goes into the offline bake.
