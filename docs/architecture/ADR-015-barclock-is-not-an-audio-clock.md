# ADR-015 — The BarClock is not an audio clock

Status: **accepted** · Date: 2026-08-30 · Clarifies `.claude/rules/realtime.md`;
depends on ADR-001 and ADR-014.

## Context

`.claude/rules/realtime.md` opens with a figure that is easy to misread:

> This code runs close to the musical clock. A GC pause here is an audible glitch.
> ... Tolerable jitter: < 2 ms

A reader arriving at `transport/clock.py` with that sentence in mind will try to build a
Python clock that achieves it, over UDP, against a control-surface thread. They will
fail, and the interesting part is that failing is the correct outcome: **the 2 ms figure
describes Live's audio clock, which we read and never drive.**

P1 says the two clocks are separated by a data structure. ADR-001 says what that means
for output: Python writes into a scene that is not playing, and Live's launch
quantisation performs the switch, sample-accurately, inside the audio engine. Python
therefore never decides *when* a note sounds. It only decides *what* sounds and *which
scene* it belongs to.

The question this ADR settles is the mirror image, on the input side: given that we do
not control timing, **what do we actually need to know about time, and how precisely?**

The answer is bar-granular and coarse. The system needs to know which bar is playing, so
it can decide when to start generating the next section and when to fire the next scene.
Both decisions tolerate hundreds of milliseconds of error, because both are followed by
Live's own quantisation absorbing the difference. Nothing downstream of the BarClock is
sample-accurate, because nothing downstream of it produces audio.

Phase 1 measured what precision is available anyway: **~100 ms per OSC round trip**,
consistently, on localhost. Whatever we might want, that is the granularity the channel
offers.

## Decision

**`BarClock` is a scheduler for the cognitive clock, not a source of timing.**

- It answers "which beat and which bar is Live playing" and "how long until bar N",
  from beat events Live pushes via `/live/song/start_listen/beat` (ADR-014).
- It **never interpolates** between beats. Sub-beat position is precision we have no
  use for, and buying it would mean trusting a drift model we would then have to
  maintain.
- It **never corrects drift**. There is no drift to correct: Live is the master and we
  are reading it. A local clock that "corrected" Live would be a second clock
  disagreeing with the first, which is exactly what P1 forbids.
- It **never schedules a note onset**. Nothing in Python does.

Beat numbers arrive absolute rather than as deltas, which makes loss self-healing: a
dropped datagram costs one late decision, and the next message resyncs with no recovery
code and no counter. A beat number *lower* than the last is a transport jump, not a
glitch — the clock resets and says so, so the scheduler can discard a section it had
queued for a bar that is no longer coming.

`realtime.md` gains one clarifying sentence pointing here. The rule itself does not
weaken: no network, no JSON, no `await` on I/O, no large allocations in the bar loop all
still hold, and they hold for a reason this ADR makes sharper — not because a GC pause
would move a note, but because a GC pause could make us miss the window in which a clip
must be written while it is still silent.

## Rejected alternatives

**A local high-resolution clock, free-running from `time.monotonic()` and resynced to
Live periodically.** This is the standard answer when a remote clock is too coarse, and
it is wrong here: it produces two clocks that disagree between resyncs, and every
disagreement is a chance to write into a clip that turns out to be playing. P1 exists to
prevent precisely this. The coarse clock we cannot get wrong beats the fine clock we
would have to keep right.

**Interpolating beat position between beat messages.** Cheap to write, and it would give
sub-beat resolution immediately. Rejected because the resolution has no consumer: every
decision the BarClock feeds is bar-granular, so the extra precision would exist only to
be trusted by some future caller who did not read this ADR.

**Driving the transport from Python** — starting, stopping and repositioning the
playhead so that musical time is ours. Rejected in ADR-001 for output and rejected again
here for input: it would make Live a slave to a clock that runs in a garbage-collected
language over a datagram socket.

**Polling `current_song_time`.** ~100 ms granularity, five calls a second to learn what
Live will push for free, and the error grows under exactly the load that matters. See
ADR-014.

## Consequences

- **`realtime.md`'s "< 2 ms" is Live's number**, and the rule file now says so in one
  sentence. Anyone building the clock reads it before writing code.
- **Everything the scheduler decides is bar-granular**, so the scheduler's tests can be
  driven by pushing beat numbers into a fake — no sleeping, no wall clock, no flakiness.
  That is what makes the three-minute dress rehearsal (Phase 2, Step 34) possible with
  Ableton closed.
- **A late generation is an extra repeat, never a gap.** A Session-view clip loops until
  another scene is fired, so the failure mode of a slow cognitive clock is the band
  vamping — which is P2 working, and is indistinguishable from a musical choice.
- **The clock has no notion of tempo drift, swing or groove.** Those live in
  `domain/time.py`'s `Feel` and in the engines, where they are musical decisions about
  where a note sits inside a bar — not clock corrections.
- If a later phase genuinely needs sample-accurate timing from Python — Phase 7's Max
  for Live device is the candidate — it will not come from this class. It will come from
  code running inside Live's own scheduler, which is the only place it can.
