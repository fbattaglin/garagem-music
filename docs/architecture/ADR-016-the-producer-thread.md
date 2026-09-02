# ADR-016 — The producer thread, and why `transport/` may not import `llm/`

Status: **accepted** · Date: 2026-08-30 · Written for Phase 3. Depends on ADR-011 and
ADR-012; enforces invariant 1 and `.claude/rules/realtime.md`.

## Context

Phase 3 puts a network call into a system whose playing half is synchronous by mandate.
The two sides do not fit together, and the shape of the mismatch is exact:

- `LLMProvider.stream` returns an `AsyncIterator[StreamEvent]` (ADR-012). Streaming is
  the whole point — ADR-011 depends on it.
- `DawPort` is synchronous **on purpose**. Its docstring: *"The only consumer is
  `transport/`, where `.claude/rules/realtime.md` forbids awaiting I/O on the musical
  path."*
- `.claude/rules/realtime.md`, verbatim: *"**Forbidden:** network calls, JSON parsing,
  `await` on I/O, synchronous logging to disk, allocating large lists inside the bar
  loop."* All five of those describe a section-shot.
- `transport/scheduler.py` calls `_section_score(index)` inside `tick()`, on the bar loop.
  Today that is `engines.band.play_section`, which takes microseconds. A model call takes
  **4.29 s at the median** (Phase 0, `claude-sonnet-5`).

And the thing that resolves it was built in Phase 2 and has been sitting unused:

> `ScoreBuffer.take` returns `None` rather than blocking or raising. That is the whole
> design, and it is P2 in one line: the music degrades, it never stops.

Invariant 1 says the musical clock and the cognitive one are separated by a data
structure, **"never by a function call"**. Phase 2 built that data structure and then had
nothing to put on the far side of it. Phase 3 is the far side.

## Decision

**The network lives in `agents/producer.py`, on its own thread, with its own asyncio
loop. It reaches the scheduler only through the `ScoreBuffer`.**

```
   producer thread                    ScoreBuffer                 scheduler thread
   ──────────────────                 ───────────                 ────────────────
   buffer.wanted()          ────────>  frozen SectionScores  <──── buffer.take(index)
   stream + parse (ADR-011)                                        or the deterministic
   realise, repair                                                 engine, logged
   buffer.offer(index, ...)  ───────>
```

The producer **never touches the `DawPort`** and the scheduler **never awaits anything**.
Neither calls the other; neither can block the other. `transport/scheduler.py` needs no
change at all in Phase 3, and a diff to it would be a signal that something has gone
wrong.

**`transport/` may not import `llm/`, and `tests/unit/test_architecture.py` enforces it
statically.** That is the part of this decision that survives the people who made it. A
rule kept by discipline is kept until the first inconvenient afternoon; the same file
already proves that `domain/`, `theory/` and `engines/` open no socket, and this is one
more line in the same table.

`agents/` is the right home rather than `transport/` or `setlist/`: it is where personas,
prompts and routing already live, it is under no real-time rule, and a producer is the
thing that runs an agent.

## Rejected alternatives

**Make the scheduler async.** The most obvious answer, and it puts an event loop between
the `BarClock` and Live. Every rule in `realtime.md` becomes advisory — `await` is
suddenly available on the bar loop, and the next person to need something will use it.
Worse, `DawPort` would have to become async too, and Phase 1's argument for a synchronous
port (*"OSC is bounded request/response against a control-surface thread that ticks at
~100 Hz: there is no stream, no TTFT and nothing an event loop would buy"*) is still
entirely true.

**Generate inline in `_section_score`, with `asyncio.run`.** Two lines of code and it
works in a unit test against `FakeDawAdapter`. Against Live it parks the bar loop for four
seconds while Live keeps pushing beats, the write for the *current* section never happens,
and the failure looks like a glitch rather than like a slow API. This is precisely the
failure invariant 1 is written to prevent.

**A separate process.** Real isolation, and it buys nothing here: the reply port 11001
can only be held by one process (Phase 1), so the producer could not talk to Live anyway
— which is fine, it never does — and everything it needs to share is a `ScoreBuffer` that
would then need serialising across a pipe. A thread and a lock are the smaller answer to
the same question.

**A thread pool, one task per pending section.** The window is two sections. Concurrency
of two, against a `Governor` whose in-flight cap exists precisely to stop this, and
against a provider where two simultaneous calls compete for the same rate limit. One
section at a time, in index order, is what the buffer's window already describes.

## Consequences

- **A thread to start and join.** `Producer.start()` / `.stop()`, daemon, joined with a
  timeout — the same shape as `UdpOscTransport`'s receive thread (ADR-014), for the same
  reason: a stuck join must not hold the interpreter open.
- **The producer's failures are events, never exceptions the scheduler sees.** The
  scheduler's contract is that a missing section is `None`. An exception crossing the
  boundary would break a guarantee the scheduler has no code to handle.
- **Cancellation has to work**, because §4.2's deadline *is* a cancellation: *"If it
  overruns → cancel, log, use the deterministic engine, and do not try again for that
  section."* Not a timeout that is noticed afterwards — a stream that stops.
- **`ScoreBuffer.refused` becomes meaningful for the first time.** In Phase 2 nothing ever
  offered a section, so nothing was ever refused. Now a rising `refused` means the
  producer is finishing work nobody will hear, which is a scheduling bug rather than a
  musical one.
- **Two threads now watch the clock and neither owns it.** The receive thread stores
  beats, the scheduler reads them, the producer reads the buffer. All three meet at data
  structures. That is the same claim invariant 1 makes, extended one layer outward.
- **`jam.py --generate` is a flag, and off is the default.** Phase 2's behaviour stays
  byte-for-byte reachable, which is what makes the Phase 3 comparison mean anything and
  what stops the offline path from quietly rotting.
