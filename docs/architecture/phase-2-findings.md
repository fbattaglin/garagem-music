# Phase 2 findings — Clock, Buffer and Deterministic Engine

What the phase met that the design did not predict. Written as it happened, including
the parts where the plan was wrong.

Phase 1's findings are in `phase-1-findings.md`; the ones that changed later decisions
are recorded as ADRs. The same applies here: §1, §2 and §3 below change numbers that
Phase 3 will depend on.

---

## 1. A note that overlaps the next attack of the same pitch is silently truncated

**The first live write of the phase failed, and the message could not say why.**

`/live/clip/add/notes` came back reporting the same number of notes with different
contents: a keys pad written with `duration_beats = 4.0` was returned as `3.986828`.
Live shortens a note that would overlap the *next attack of the same pitch*, does it
without complaint, and reports the shortened note back — so the adapter's write-then-
confirm fails on a write that Live considers successful.

The overlap was created by humanisation. A pad lasting exactly one bar ends precisely
where the next bar's chord begins; the humaniser then moves the next attack up to 0.02
beats *earlier*, and the two overlap by nine milliseconds.

**The fix is musical, not a tolerance.** `engines/humanise.separate()` shortens any note
that would run into the next attack of the same pitch, leaving a `RELEASE_BEATS` gap of
0.01 beats (~4.5 ms at 132 BPM). Every engine calls it as its last step, after
humanising, because humanising is what creates the hazard.

It is also what a player does. A hand lifts before striking the same key again, and a
MIDI part that does not is asking the sampler to retrigger a voice that is still
sounding — a different sound from the one that was written.

Two engines were already overlapping *before* humanisation and nobody had noticed: the
guitar's ringing chords lasted exactly the gap between strums, and the bass under a
shuffle held notes for 0.45 beats across gaps of 0.33.

## 2. The confirming read was finer than the wire can carry

**`BEAT_PLACES` was 6. OSC floats are 32 bits. Those two facts are incompatible.**

The second live write failed with `want 17.018598, got 17.018599` — one unit in the
sixth decimal place of a beat position, which is about half a nanosecond of music.

A 24-bit mantissa carries roughly seven significant decimal digits, so at beat 17 the
smallest step a float32 can represent is already ~1e-6: the same size as the sixth
decimal place. Rounding to six places was therefore comparing noise. Whether a given
note survived the round trip depended on which side of a rounding boundary its float32
approximation landed — which is why Phase 1 never saw it. Phase 1's notes were at 0.0,
4.0, 8.0 and 12.0, all exactly representable.

`BEAT_PLACES` is now **4**. That is 45 microseconds at 132 BPM — 200 times finer than
the humaniser's own maximum push, and about six times coarser than the worst float32
error anywhere in a 32-bar section. The gap is what makes the round trip *exact* rather
than usually exact, which is what an idempotence criterion needs.

**The general rule, worth carrying forward: a confirming read cannot be finer than the
protocol it is confirming through.**

## 3. A section write costs ~2 seconds, not the ~400 ms the plan predicted

Measured over six sections of a real performance, from `bench/jam-phase2.jsonl`:

| notes | ms |
|---|---|
| 137 | 1146 |
| 148 | 1201 |
| 305 | 1991 |
| 315 | 1992 |
| 517 | 2002 |
| 517 | 2002 |

Over the full three-minute run (fourteen sections): **p50 1163 ms, min 1141 ms, max
1939 ms** for four tracks. The plan predicted ~400 ms, derived from
Phase 1's ~100 ms per round trip and one round trip per track. The prediction was wrong
by a factor of five because a write is not one round trip: it is `has_clip`, sometimes
`create_clip`, then `remove/notes`, `add/notes` and a confirming `get/notes` — five or
six exchanges per track, twenty-odd per section.

The cost barely tracks note count (137 notes cost 1146 ms, 517 cost 2002), which
confirms it is dominated by the number of round trips rather than by datagram size.

**At 132 BPM a bar is 1.82 s, so a section write costs about one bar.** The scheduler
writes at the *start* of the playing section, which leaves seven bars of margin on an
eight-bar one. That was the right decision for a reason the plan only half stated:
writing near the boundary would not have been tight, it would have been impossible.

`fire_lead_bars` stays at 1. It is not what the write competes with.

## 4. An unbounded repeat is a hang, not a degradation

The first live run of `jam.py` never returned. Every write was refused (§1), so the next
section was never ready, so the scene was never fired, so the boundary moved forward a
section at a time — for four minutes, until it was killed by hand.

"A late section causes a repeat rather than a gap" is right. "Repeats forever" is not a
degradation, it is a command that does not terminate. `MAX_REPEATS = 2` now ends the run
and logs `repeated_too_long`: about thirty seconds at 132 BPM, long enough to survive one
bad section and short enough that a command still returns.

## 5. `/live/song/get/beat` has no handler

Verified in AbletonOSC's `song.py`: `current_song_time_changed` calls `osc_server.send`
on that address, and `add_handler` is never called for it. Live only ever *sends* on it.

Probing it would time out, and down at the wire a timeout is indistinguishable from a
wrong address — `probe_live.py` would have reported the beat mechanism as broken while it
worked perfectly. That is Phase 1's finding §9 in a new place, so the probe now carries a
`PUSH_ONLY` set alongside `WRITES`, and says which reason applies.

Also confirmed there, and load-bearing for the BarClock: the handler fires on a *rewind*
as well as on a forward beat, and it sends `int(current_song_time)` — an absolute
position rather than a delta, which is why a lost datagram is self-healing.

## 6. There is one beat listener, and a second one silently replaces it

The transport routes unsolicited messages by address, and there is one beat address. The
first version of `test_live_jam.py` registered its own listener to collect beats, which
replaced the `BarClock`'s — and produced a performance in which the clock never advanced,
one scene was fired, and nothing else happened.

Documented on `DawPort.listen_beats` now. Anything that wants to know where the music is
asks the `BarClock`, which is the thing that owns the listener.

## 7. Property tests found a bug that 60 examples did not

At `max_examples=60` the musical invariants were clean. At 500 they were not: a halftime
section at 222 BPM produced two kicks 60 ms apart, exactly on the limit the validator's
`kick_spacing` rule enforces.

The pattern was legal *on the grid* — a sixteenth at 222 BPM is 67 ms — and illegal once
played, because the humaniser can push two adjacent kicks in opposite directions by up to
0.02 beats each. `groove_for` now takes the tempo and picks the busiest pattern that stays
legal **with headroom for humanisation**, which is a drummer choosing a simpler pattern at
a tempo they cannot play the busy one at.

The committed profile stays at 60 examples so the suite is fast. The finding is that
raising it occasionally is worth doing: `max_examples=2000` now passes, and took 44 s.

## 8. Two engines wrote notes the briefing never asked for

Both found by sweeping the briefing space rather than by a test somebody thought of.

**A power chord on a diminished chord used a perfect fifth.** `voice(chord, "pow", …)`
added seven semitones regardless of the chord, so a `iidim` in dorian got a note that is
neither in the chord nor in the key. `fifth_of` now takes the chord's own fifth.

**A sus2 pad could break the dissonance budget when the chart disagrees with its key.**
`| Em |` under a C briefing is a legal request and Phase 3 will certainly make it; the
added second of a sus2 is not a chord tone, so under such a chart it lands outside both.
The keys engine now falls back to a triad, which is always inside the chord.

Neither is exotic. Both would have produced music that the validator rejected and the
repairer then "fixed" — the deterministic floor leaning on the layer that exists to
check it.

## 9. What the numbers say about the phase's claims

From `bench/jam-phase2.jsonl`, one three-minute performance against a real Live —
`uv run python scripts/jam.py --seconds 180 --seed 7`:

- **189 s of music, fourteen sections, thirteen section changes.** The last section was
  fired at beat 400, which is 181.8 s in.
- **Fourteen sections written, fourteen fired, zero `beat_lost`, zero dropped datagrams.**
- **Every transition fired with exactly one bar of slack.** Not "at least one" by luck:
  the scheduler fires at `boundary - 1` and the log records the measured slack.
- **Scenes alternated 0, 1 for all fourteen**, and no write ever went to the scene that was
  playing — checked twice over in `test_jam_offline.py`, once from the event log and once
  from the addresses the adapter was actually given.
- **Zero network calls**, by construction: nothing in `domain/`, `theory/`, `engines/` or
  `transport/` may import a socket, and `tests/unit/test_architecture.py` now enforces
  that statically rather than promising it in a rule file.

## 10. The floor is musical, and that was not guaranteed

Every number in §9 could have been true of something nobody wants to listen to. The
criterion ADR-000 §7 actually states is a person saying it is an acceptable demo, and on
2026-08-30 Fabiano listened to the full three minutes and said *"Está total aceitável. Na
verdade está super agradável."*

Worth recording as a finding rather than only as a tick, because the phase was designed
around the possibility of the opposite answer. A deterministic floor that measured clean
and sounded mechanical would have meant every "degradation" in Phase 3 was a collapse,
and the architecture's central claim — an API failure degrades the music, it never
silences it — would have been a bluff. It is not.

What the ear approved, specifically: a groove table somebody can argue with rather than a
pattern generator, voice leading across every chord change, fills whose density comes
from the section's tension, and humanisation bounded tightly enough never to cross a grid
line. Those were bets. They paid.

## What is still open

- **`write_lead_bars` as a concept.** The plan carried a parameter for how far ahead to
  write. The scheduler writes at section start instead, which is strictly earlier than
  any lead value, so the parameter that survives is `fire_lead_bars`. If Phase 3's
  generation makes a section arrive late, that is the buffer's problem and not a lead.
- **The write budget under an LLM.** §3 measures a write with the deterministic engine,
  where generation is microseconds. Phase 3 adds a call that takes seconds *and* wants the
  same control-surface thread afterwards. The 2 s write is the number that sizing has to
  start from.
