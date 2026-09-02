---
paths:
  - "src/garagem/domain/**/*.py"
  - "src/garagem/theory/**/*.py"
  - "src/garagem/engines/**/*.py"
---

# Domain layer — purity is mandatory

These modules are the pure musical logic. They are the only part of the system that
runs in CI with no network, no Ableton and no API key.

- Allowed imports: stdlib, `pydantic`, `numpy`, and other modules from these same
  layers.
- **Forbidden:** `httpx`, `requests`, `mido`, `python-osc`, `asyncio`, anything from
  `src/garagem/{llm,daw,transport,obs}/`, file reads, environment variables.
- No unseeded randomness. Use a `Random` received as a parameter or an explicit seed —
  never the global `random.random()`.
- Generation functions must be pure: same input + same seed = same output, byte for
  byte. There are golden tests that depend on it.

If you need a value that comes from outside (current time, configuration, an LLM
result), receive it as an argument. Do not go and fetch it.
