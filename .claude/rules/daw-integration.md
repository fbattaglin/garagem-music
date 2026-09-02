---
paths:
  - "src/garagem/daw/**/*.py"
  - "scripts/bootstrap_set.py"
---

# Ableton Live integration

- AbletonOSC listens on 11000 and replies on 11001. The handler runs on Live's control
  surface thread, at ~10 ms granularity: **it is not sample-accurate.** Never use this
  path for note timing.
- Every write operation is idempotent. Running `bootstrap_set.py` twice in a row must
  produce exactly the same Live Set.
- The Set's expected state lives in `session.toml`. Code never creates tracks
  implicitly; it validates against the spec and reports divergence.
- The Live API cannot load an instrument onto a track. `bootstrap_set.py` reports a
  track with no device as a divergence; it never tries to fix it (ADR-013).
- If Live is not open, the adapter fails fast with a clear message — no silent retry.
- Every change here needs an equivalent in `FakeDawAdapter`, so that the main suite
  keeps running without Live.
