# ADR-001 — Clip-ahead writing and quantised launch

Status: **accepted** · Date: 2026-08-30 · Named in ADR-000 §6 as "retained — it is the
foundation"; this file is the decision written down.

## Context

The system has two clocks, and they are three orders of magnitude apart.

The musical clock is Live's. A bar at 132 BPM lasts 1.82 s and every note inside it has
to land within a couple of milliseconds of where it belongs, forever, without a single
late arrival. The cognitive clock is the cloud's. Phase 0 measured it on the real link:
a warm structural call returns its first token in 1.46–1.63 s at the median, and the
first call of a session — the cold one — took 6.11 s on Opus 5 and 14.38 s on Haiku 4.5
(`phase-0-findings.md` §1). The tail is not a rare excursion we can engineer around; it
is the ordinary shape of the thing.

Invariant P1 says those two clocks are separated by a data structure, never by a
function call. This ADR decides the other half of that separation: given that the
generator finishes at an unpredictable time, **how does what it produced become sound at
a predictable one?**

Three facts about the transport constrain the answer.

- **AbletonOSC runs on Live's control-surface thread**, which ticks at roughly 100 Hz.
  Effective round-trip latency is ~10 ms and it is not sample-accurate. It is a
  configuration channel, not an audio one.
- **Live already solves this problem internally.** Global launch quantisation exists
  precisely to make a human's imprecise button press land on a bar line. A slow program
  is not different from a slow human.
- **Rewriting a clip while it plays is undefined territory.** Live gives no atomic
  swap; a note removed mid-playback is a note that does not sound.

## Decision

**Generation writes into scene N+1 while scene N plays. Live's launch quantisation
performs the switch. A clip that is playing is never written to.**

Concretely:

1. The Set holds at least two scenes, and the system alternates between them. While
   scene N sounds, every write — `create_clip`, `remove/notes`, `add/notes` — targets
   the clips of scene N+1, which are silent and therefore safe.
2. When the material for N+1 is complete, the system calls `fire_scene(N+1)` and stops.
   It does **not** wait, poll or confirm the launch. Live's
   `clip_trigger_quantization`, set to `1 Bar`, holds the launch until the next bar line
   and performs it inside the audio engine, sample-accurately.
3. Python therefore never decides *when* a note sounds. It decides only *what* sounds
   and *which scene* it belongs to. Timing is Live's problem — invariant 6.
4. If the material is not ready when the bar comes, nothing is fired and scene N loops.
   The music does not stop; it repeats. That is the degradation path (P2), and it is
   indistinguishable from a band vamping while the singer decides what to do next.

The launch quantum is part of the contract. `session.toml` declares it, the bootstrap
validates it, and the port exposes `quantization()` / `set_quantization()` so a Set that
has drifted to `None` is a reported divergence rather than a mystery about timing.

## Rejected alternatives

**Real-time note-on/off over OSC.** Sending each note as it should sound, the way a
sequencer drives a synth. Dead on arrival: the control-surface thread ticks at ~100 Hz,
so the best achievable resolution is ±10 ms with no jitter guarantee, against the < 2 ms
the musical clock requires. It would also put the network on the real-time path, which
P3 forbids outright.

**A Max for Live device holding the buffer inside Live.** This genuinely solves timing —
the device runs in Live's own scheduler — and it is the right answer eventually. It is
rejected *for now* on surface area: it means a second language, a second build artefact,
a second debugging environment and a device that has to be present in every Set, in
exchange for a latency gain we do not yet need. Deferred to Phase 7.

**Rewriting the playing clip with a look-ahead offset** — writing bars 5–8 into the clip
that is currently playing bars 1–4. Tempting, because it removes the one-quantum
reaction delay. Rejected: the write is not atomic, the playhead's position at the moment
of the write is unknown to us within ±10 ms, and a note removed a millisecond before it
was due is silence in the middle of the music. It contradicts invariant 6 directly and
it fails *audibly*, which is the worst failure mode this project has.

**Driving Live's transport from Python** — starting, stopping and repositioning the
playhead to line generation up with the music. Rejected because it inverts the
relationship Phase 2's BarClock depends on: Live is the master clock and we read it. A
system that moves the playhead is a system whose two clocks are coupled by a function
call, which is exactly what P1 forbids.

## Consequences

- **Minimum reaction latency is one launch quantum** — 1.82 s at 132 BPM with `1 Bar`,
  and up to a full section if the material misses its window. This is the price of never
  glitching, and it is paid deliberately. Anything that "feels sluggish" is fixed by
  making the lookahead deeper, never by shortening the quantum.
- **The Set must have at least two scenes.** `load_session` refuses a `session.toml`
  with fewer, because with one scene there is nowhere to write that is not playing.
- **`clip_trigger_quantization` is part of the contract, not a user preference.** A Set
  with quantisation off would launch scenes the instant the packet arrived — mid-bar,
  audibly wrong.
- **The port needs very little.** `create_clip`, `write_notes`, `fire_scene`,
  `song_time_beats`, `is_playing` and the session validators. It deliberately has no
  per-note editing, no playhead control and no way to modify a clip while it sounds:
  the shape of the port is itself the enforcement of this decision.
- **`fire_scene` is fire-and-forget by design.** Confirming it with a read would be
  confirming something that has not happened yet — the launch is up to a bar away. The
  caller's confirmation is `is_playing()` afterwards, not an acknowledgement.
- **Phase 2 inherits an open question this ADR does not answer:** how deep the lookahead
  is and how the ScoreBuffer is sized. This decision only guarantees that whatever the
  buffer holds can be delivered to Live without a race.
