---
paths:
  - "src/garagem/transport/**/*.py"
  - "tests/property/**/*.py"
---

# The real-time path

This code runs close to the musical clock. A GC pause here is an audible glitch.

- **Forbidden:** network calls, JSON parsing, `await` on I/O, synchronous logging to
  disk, allocating large lists inside the bar loop.
- Pre-allocate structures outside the loop. Reuse buffers.
- The `BarClock` is a slave to Live's transport. Never generate the clock locally, and
  never try to compensate for drift on your own.
- CLAUDE.md's "< 2 ms jitter" describes **Live's audio clock, not the BarClock**. Nothing
  in Python schedules a note's onset: we write into a silent scene and Live's launch
  quantisation performs the switch inside the audio engine. The BarClock answers "which
  bar are we in" to a tolerance of hundreds of milliseconds, from beats Live pushes.
  See ADR-015. A clock built here to hit 2 ms over UDP cannot work and is not needed.
- Note writing happens in **scene N+1**, with at least one bar of slack. Never call
  `set_notes` on a clip that is playing.
- Every deadline is explicit and has a deterministic fallback path. A `TimeoutError`
  reaching the top of the loop is a design bug, not an error condition.

When changing anything here, run `uv run pytest tests/property/ -k timing`.
