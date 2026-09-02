# GARAGEM

Multi-agent system for near-real-time music generation, arrangement and manipulation,
integrated with Ableton Live. Cloud inference, deterministic local playback.

## Getting started

```bash
uv sync
cp .env.example .env    # fill in API keys
uv run pytest           # needs neither network nor Ableton
```

Architecture: `docs/architecture/ADR-000-baseline.md`
Current phase: `docs/architecture/STATUS.md`
