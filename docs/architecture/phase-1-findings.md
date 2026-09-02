# Phase 1 findings

What building the bridge actually met, as opposed to what ADR-000 §7 assumed. Findings
1-3 are recorded as decisions in ADR-013; the rest are properties of AbletonOSC that
shaped the adapter and are pinned by tests.

## 1. The Live installation is 12 **Lite**, not Suite

ADR-000's header says Suite. `/Applications/Ableton Live 12 Lite.app` is what is on the
machine. Lite caps a Set at **8 tracks**, so `load_session` refuses a `session.toml`
with more, naming the limit. Four tracks is what Phase 1 needs, so nothing is blocked —
but the assumption was wrong and anything later that plans for more instruments has to
know it.

## 2. `DLSMusicDevice` no longer exists; the instrument is Drift

ADR-000 §7 specifies `DLSMusicDevice`, Apple's Audio Unit General MIDI synthesiser.
Modern macOS no longer ships it, so the instrument the roadmap names cannot be loaded at
all. **Drift** replaces it: built into Live 12 Lite, oscillator-based, no samples.

## 3. ~~Live's Factory Packs are not downloaded~~ — wrong, and corrected

**This finding was wrong when first written, and the mistake reached the message
`bootstrap_set.py` prints to the user.** It said that nothing sample-based would make a
sound on this machine, on the strength of `~/Music/Ableton/Factory Packs/` being empty.

That folder holds the *additional* downloadable packs. Live's **Core Library ships
inside the application bundle** — 1.8 GB across 7134 sample files, plus 89 Drift
presets, at
`/Applications/Ableton Live 12 Lite.app/Contents/App-Resources/Core Library/`. Sampled
instruments work.

Drift is still what `session.toml` names, but for the honest reason rather than the
invented one: it is simple, CPU-light and needs no preset hunting, and Phase 1 is about
timing rather than timbre. Nothing else is unavailable.

The lesson is the one the project already applies to model output: an absent folder was
read as an absent capability without checking. Looking inside the app bundle took one
command.

## 4. AbletonOSC answers a failed request with nothing at all

There is no `/live/error` address. When a handler raises, the client sees exactly what it
sees when Live is closed, when the control surface is disabled, and when a datagram is
dropped: silence. So `DawTimeoutError` subclasses `DawUnavailableError` deliberately, and
its message names all three causes plus the log path, because the wire cannot tell them
apart and the caller's response is the same for all three: degrade, do not retry.

Setters are the same in the healthy case — a successful `set` replies nothing, exactly
like a refused one. That is why **every setter in the adapter is write-then-confirm**:
send, then call the matching getter, then compare. Without the read-back, a lost write
would surface as music that quietly differs from what was generated.

## 5. Replies always go to port 11001, whatever port the request came from

Confirmed in AbletonOSC's own server code. Two consequences the design had to take:
the client socket is *bound* to 11001 rather than connected, and **only one process on
the machine can talk to Live at a time** — a second one gets `DawUnavailableError` at
construction, saying so. `request()` also drains stale datagrams before sending, because
a late reply to a previous call would otherwise be read as this one's.

## 6. `/live/clip/add/notes` appends; it does not replace

Verified against `abletonosc/clip.py`: the handler calls `clip.add_new_notes`. Writing
the same section twice doubles every note, and the Set still looks plausible. A replace
is `remove/notes` (with the full pitch and time span) followed by `add/notes`, which is
what `write_notes` does — and `FakeDawAdapter.write_notes` replaces for the same reason,
so a fake that appended could not hide the bug.

The reply shapes were read off the same file rather than guessed:
`/live/clip/get/notes` echoes `(track, clip)` and then five fields per note, so a reply
whose remainder does not divide by five is a `DawProtocolError` — silently dropping a
remainder would arrive as a section quietly missing its last chord.

## 7. `python-osc` uses `sendto`, so the `no_network` fuse had a UDP-shaped hole

The suite's fuse patched `connect` and `connect_ex`. UDP never calls either. A unit test
that constructed a real transport would therefore have fired packets at whatever Ableton
Live happened to be open on the machine, and passed. The fuse now also blocks
`sendto` — `bind`, `send`, `recv` and `recvfrom` stay open, because asyncio's internals
use them — and `test_the_fuse_refuses_a_udp_datagram` pins it.

## What is still open

- **The `live` half of the phase.** AbletonOSC is installed but its Control Surface has
  not been enabled and Live has not been restarted, so `scripts/probe_live.py` has never
  answered and the seven `live`-marked tests have never run. Until they do, every claim
  in this file about a *reply shape* rests on reading AbletonOSC's source, not on
  observing Live. See `STATUS.md`.
- **The quantisation codes are still an assumption.** `QUANTIZATION_CODES` maps
  `1 Bar` to 4 on the strength of the LOM's documented enum order. A reordering would
  mistime every scene launch silently. `probe_live.py` reads the live value; the adapter
  refuses an unknown code and says to run it.

## 8. Control Surface slot 1 is already taken by the MiniLab 3

Live's log lists seven Control Surface slots, and slot 1 holds `MiniLab_3` — the
controller Phase 5 ("human in the loop") is built around. The first instructions written
for this phase said to put AbletonOSC in slot 1, which would have silently cost Phase 5
its controller in exchange for the bridge. **AbletonOSC goes in the first free slot**
(slot 2 on this machine); the instruction is corrected in `install_abletonosc.py`,
`STATUS.md`, the adapter's own error message and the `ableton-lom` skill.

Live scans `Remote Scripts/` at startup, so the folder has to exist *before* Live is
launched for AbletonOSC to appear in the dropdown at all. Installed 11:28, Live started
11:34 — the ordering was right here, but it is the first thing to check when the
dropdown has no AbletonOSC entry.

## 9. A clip getter against an empty slot is indistinguishable from a wrong address

The first probe run reported `/live/clip/get/length` and `/live/clip/get/notes` as
FAILED. Both addresses are correct. AbletonOSC's `create_clip_callback` resolves
`track.clip_slots[i].clip`, which is `None` for an empty slot, and the handler then
raises on it — so the client sees silence, exactly as it would for an address that does
not exist. The probe was reporting working endpoints as broken.

`scripts/probe_live.py` now scans for a slot that actually holds a clip and probes
against that, and says **NOT PROBED — no clip** when the Set is empty rather than
inventing a failure. The consequence for finding 6 is that the reply *shape* of
`/live/clip/get/notes` is still an assumption read from AbletonOSC's source: it can only
be confirmed once the Set has a clip in it.

## 10. A default Live Set is half audio tracks, and `bootstrap_set.py` did not notice

The Set that was open reported `('1-MIDI', '2-MIDI', '3-Audio', '4-Audio')` — Live's
default. `diff_session` checked names and device presence but not whether a track can
accept MIDI at all, so it happily proposed renaming `3-Audio` to `GTR`. That is the
exact failure ADR-013 refuses track creation over: the Set would have *looked* correct,
passed the check, received MIDI and made no sound. An audio track holds no MIDI clip,
takes no instrument, and **cannot be converted** — the human has to delete it and insert
a MIDI track.

`/live/track/get/has_midi_input` answers this, so it is now on the port
(`DawPort.accepts_midi`), in the adapter, in the fake, and in `ALL_ADDRESSES`. A track
in a musical role that does not accept MIDI is a `not_a_midi_track` divergence, marked
**not fixable**, and `apply_session` will not rename it — renaming would only make the
silence harder to find.

## 11. What the probe confirmed on 2026-08-30, against Live 12.4

Thirteen of fifteen readable addresses answered, in ~100 ms each. Two of the three
assumptions the probe exists to check are now facts rather than readings:

- **`clip_trigger_quantization` = 4 for `1 Bar`.** `QUANTIZATION_CODES` is right, so
  scene launches are quantised where ADR-001 says they are.
- **`output_meter_level` answers**, as `(track_index, level)` — the shape
  `_after_index` assumes. The Phase 1 audio criterion has a machine-checkable half.
- **`/live/clip/get/notes` echo shape: confirmed** once the Set held a clip. Reading
  clip 3/1 back gave `(3, 1, 43, 8.0, 4.0, 100.0, False, 47, 8.0, ...)` — the echoed
  `(track, clip)` followed by five fields per note, 12 notes in 62 arguments. Exactly
  what `notes_from_reply` assumes, including that a reply whose remainder does not
  divide by five is a truncation rather than a shorter section.

One detail worth knowing: **velocity comes back as a float** (`100.0`, not `100`), as
does `mute`'s neighbour ordering suggests nothing else does. `notes_from_reply` already
coerces with `int()`, so a `MidiNote` never carries a float velocity — but a stricter
parser that refused non-integers would have failed here, on correct data.

Also observed: `/live/application/get/version` → `(12, 4)`; `track_names` is a flat
tuple with no index prefix, while every `track/get/*` reply is prefixed with the track
index; a track with no device answers `(track_index,)` and nothing else, which is what
makes the `no_instrument` check work.

## 12. The phase closed on the first attempt once the Set was right

All seven `live` tests passed together on 2026-08-30, in 12.1 s, first run after
`bootstrap_set.py` reported a match — no adapter change, no constant corrected, no
endpoint that turned out to be wrong. Every failure met during Phase 1 was either a
missing part of the Set (finding 10), a probe that misread correct behaviour
(finding 9), or a claim in the documentation that had never been checked (findings 3
and 8).

That is worth recording because it is evidence about the *method* rather than the code:
reading AbletonOSC's own handlers to derive the reply shapes, rather than guessing them
and iterating against Live, meant the wire format was right before Live was ever opened.
The `FakeDawAdapter` rehearsal (`tests/unit/test_daw_bridge.py`) then held every claim
that did not need a DAW.

## 13. The suite proves signal; it does not play music, and the criterion assumed it did

The exit criterion's last line — audio arriving at the Scarlett — was written as "run
`uv run pytest -m live -q`, listen, and record who listened". The first person to try it
reported: *"the results seem to have passed, but I only heard two notes."*

They had. The arithmetic:

| | |
|---|---|
| The progression, 16 beats at 132 BPM | **7.27 s** |
| One bar, one chord | 1.82 s |
| What `test_the_instrument_actually_makes_a_sound` listens for (`LISTEN_S`) | **2.00 s** |

The test fires the scene, samples `output_meter_level` for two seconds — 1.1 bars, so
the Em and the first moment of the C — and the next test calls `stop_playing`. It
asserts something true and useful (MIDI reached Drift and Drift produced signal) and it
was never going to let anybody hear the music. `LISTEN_S` was set to 2.0 to keep the
suite fast, and in doing so it made the human half of the criterion unperformable.

**A test suite is built to finish quickly; listening happens in real time. One command
cannot be both.** The criterion was written as though it could, which is the actual
defect — not the constant.

The confirmation was eventually done with a throwaway script that fires the scene and
holds the transport for four passes (~29 s). Nothing in the repository does that yet.
Phase 2's `scripts/jam.py` is the permanent answer, since that phase's exit criterion
also ends in a human listening — but it lands at Step 35 of 39, so between now and then
there is no committed way to hear the instrument. Worth closing sooner than that.

The general lesson is the one this project keeps relearning: a criterion is only met if
someone can actually perform it. "Zero dropouts" and "a musician rates it acceptable"
in Phase 2 both need the same scrutiny before they are written down.
