---
name: ableton-lom
description: AbletonOSC endpoints, Live Object Model mapping and known integration pitfalls with Ableton Live 12. Use when working in src/garagem/daw/, on the Live Set bootstrap, or when debugging timing and clip writing.
---

# AbletonOSC / Live Object Model

A Python remote script running inside Live. Install into
`~/Music/Ableton/User Library/Remote Scripts/AbletonOSC`, then enable it under
Preferences -> Link/Tempo/MIDI -> Control Surface, in the first free slot — the
MiniLab 3 already occupies slot 1 on this machine and Phase 5 needs it.

Listens on **11000**, replies on **11001** to the originating IP.

## Endpoints we use

| Address | Use |
|---|---|
| `/live/song/get/tempo`, `/live/song/set/tempo` | BPM |
| `/live/song/get/current_song_time` | playhead position (the BarClock's source) |
| `/live/song/start_playing`, `/stop_playing` | transport |
| `/live/clip_slot/create_clip` | create a clip of N beats |
| `/live/clip/add/notes`, `/live/clip/remove/notes` | write notes |
| `/live/clip_slot/fire` | fire one clip slot (honours the global quantisation) |
| `/live/track/get/name`, `/live/track/set/name` | validate and repair a track name |
| `/live/song/get/track_names` | validate the Set against `session.toml` |
| `/live/track/get/devices/name` | does this track carry an instrument at all? |
| `/live/track/get/has_midi_input` | is this a MIDI track? An audio one takes no instrument |
| `/live/track/get/output_meter_level` | the only evidence from code that sound happened |
| `/live/scene/fire` | fire a whole scene (honours the global quantisation) |
| `/live/song/get/num_scenes` | validate the Set has somewhere to write ahead into |
| `/live/song/get/is_playing` | transport state — the confirmation `fire` cannot give |
| `/live/song/get/clip_trigger_quantization`, `/live/song/set/...` | the launch quantum (ADR-001) |
| `/live/clip_slot/get/has_clip`, `/live/clip_slot/delete_clip` | clip lifecycle |
| `/live/clip/get/notes`, `/live/clip/get/length` | read back what was written |
| `/live/application/get/version` | which Live is this, and is the script alive |
| `/live/test` | liveness — replies `("ok",)` |
| `/live/device/set/parameter/value` | sound design and mixing |

Getters return the object ID alongside the value. Wildcards work in queries
(`/live/clip/get/* 0 0`).

## Pitfalls

- The handler runs on the control surface thread, at a ~100 Hz tick. **Effective
  latency around 10 ms, with no sample accuracy.** Good for writing ahead, never for
  playing.
- Rewriting a clip that is playing is racy and produces an audible artefact. Always
  write into the next scene and let Live's launch quantisation perform the switch.
- After editing the remote script, the whole of Live must be restarted the first time;
  `/live/api/reload` alone is not enough.
- Logs live in `.../Remote Scripts/AbletonOSC/logs/abletonosc.log`. Verbosity via
  `/live/api/set/log_level`.
- UDP does not guarantee delivery. Every critical write is followed by a confirming
  read.
- **A handler that raises replies with nothing at all.** There is no `/live/error`. A
  malformed request, a dropped packet and a closed Live are the same event to us: a
  timeout. Say all three in the error message, because the timeout cannot tell them
  apart.
- **Setters reply nothing**, not even an acknowledgement. Every confirmation is a
  separate getter call.
- **Replies always go to port 11001**, whatever port the request was sent from. The
  client socket must therefore be *bound* to 11001, and only one process on the machine
  can hold it at a time.
- **`/live/clip/add/notes` appends; it does not replace.** Writing the same section
  twice doubles every note. A replace is `remove/notes` (with no arguments, which
  clears the clip) followed by `add/notes`.
- **A clip getter against an *empty* slot times out.** The handler dereferences a
  `None` clip and raises, and a raising handler replies with nothing — byte for byte
  what a wrong address looks like. Check `clip_slot/get/has_clip` before concluding an
  address is broken.
- **An audio track cannot hold a MIDI clip or an instrument, and cannot be converted.**
  A default Live Set opens with two MIDI and two audio tracks, so the template needs
  the audio ones deleted and MIDI ones inserted. `has_midi_input` is how code tells.

## Instruments

In the early phases, use **Drift**, Live's built-in synthesiser: simple, CPU-light and
no preset hunting. Ideal for validating timing without being distracted by timbre. Swap
for richer instruments in Phase 6.

`DLSMusicDevice` — the AU General MIDI instrument ADR-000 originally specified — no
longer ships with macOS. See ADR-013.

**The LOM cannot load a device onto a track.** `devices/name` reports what is there;
nothing installs it. That is why `bootstrap_set.py` validates and never creates: a track
created from code would receive MIDI correctly and make no sound (ADR-013).

Live's **Core Library ships inside the application bundle** (`/Applications/Ableton
Live 12 Lite.app/Contents/App-Resources/Core Library/`), samples included, so sampled
instruments do work. `~/Music/Ableton/Factory Packs/` being empty means only that the
*additional* downloadable packs are absent — do not read it as "no samples".
