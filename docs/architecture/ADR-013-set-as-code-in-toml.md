# ADR-013 — "Set as Code" in TOML, validated and not created

Status: **accepted** · Date: 2026-08-30 · Supersedes parts of ADR-000 §7 and §8.

## Context

Phase 1 needs a machine-readable description of the Live Set the system expects: which
tracks exist, what they are called, what instrument each carries, how many scenes, what
tempo, what launch quantisation. ADR-000 §8 calls that file `session.yaml` and ADR-000
§7 specifies `DLSMusicDevice` as the provisional instrument.

Three things about the actual machine and the actual API contradict that.

**The Live installation is 12 Lite, not Suite.** ADR-000's header assumes Suite. Lite
caps a Set at **8 tracks**, and — unlike a default Live Set, which opens with two MIDI
and two *audio* tracks — every track the system writes to has to accept MIDI. An audio
track holds no MIDI clip, takes no instrument and cannot be converted.

**`DLSMusicDevice` no longer exists.** It was Apple's Audio Unit General MIDI
synthesiser; modern macOS no longer ships it. The instrument named in ADR-000 cannot be
loaded on this machine at all.

**YAML would be a dependency.** `tomllib` is in the standard library from Python 3.11.
`config/models.toml` already established TOML as this project's configuration format,
read by `src/garagem/llm/catalog.py`. Adding PyYAML for a single four-track description
runs against the standing rule that the project is deliberately lean.

There is also a policy question the API does not settle. `.claude/rules/daw-integration.md`
forbids creating tracks implicitly, but `/live/song/create_midi_track` **does exist** —
so the rule is a choice, and a choice needs a reason on the record.

## Decision

**1. The file is `session.toml` at the repository root, read with `tomllib`.**
Supersedes ADR-000 §8. It carries `schema = 1`, the tempo, the launch quantisation, one
`[[track]]` table per track (index, name, role, instrument) and one `[[scene]]` table
per scene. The loader is `src/garagem/daw/session.py`, following the idiom
`llm/catalog.py` already uses.

**2. The bootstrap validates; it never creates.** `scripts/bootstrap_set.py` compares
the open Set against `session.toml` and reports every divergence. It repairs only what
the LOM can repair safely — tempo, launch quantisation, track names. Missing tracks,
extra tracks, missing scenes and tracks with no instrument are reported as the human's
job, with a printed instruction saying exactly what to do in Live.

The reason is not that the API cannot create a track. It can. The reason is that **the
API cannot load an instrument onto a track**: there is no LOM call that puts Drift on a
new track. A track created from Python would appear, satisfy the check, receive MIDI
correctly and make no sound whatsoever — a bridge that reports success and produces
silence. Refusing to create is what keeps "the script is happy" and "you can hear it"
the same statement.

**3. The provisional instrument is Drift.** Supersedes ADR-000 §7 and the
`ableton-lom` skill. Drift is a built-in synthesiser in Live 12 Lite's Core Library,
which ships inside the application bundle. It is chosen for being simple and CPU-light
in a phase about timing rather than timbre — not because sampled instruments are
unavailable, which an early version of `phase-1-findings.md` §3 wrongly claimed.
`instrument = "Drift"` in `session.toml` is informational: it tells the human which
device to drop in, and `bootstrap_set.py` checks only that *some* device is present,
since the LOM reports device names but cannot install them.

**4. Live 12 Lite's 8-track cap is a standing constraint.** `load_session` refuses a
spec with more than 8 tracks, naming the file and the limit. `session.toml` ships with
four: DRUMS, BASS, GTR, KEYS.

## Rejected alternatives

**Keep `session.yaml` and add PyYAML.** Costs a dependency and a second configuration
format for no gain; the file is a flat list of tables, which is TOML's best case. The
only argument for YAML — nested structures — does not apply.

**Put `session.toml` under `config/` next to `models.toml`.** Rejected because ADR-000
§8 puts the Set description at the repository root, and unlike `models.toml` (which is
data the code reads at runtime) `session.toml` describes *this machine's* Set. Keeping
it at the root, where it is visible, matches what it is.

**Create the missing tracks and let the human notice the silence.** Rejected above: a
successful exit that produces no sound is worse than a failure that says what to fix.

**Substitute a Drum Rack or a sampled preset for realism.** Rejected because Phase 1 is
about timing, not timbre, and a heavier instrument only adds variables to a measurement
of when notes land. Phase 6 owns the instruments.

## Consequences

- ADR-000 §8's tree and §7's Phase 1 paragraph are superseded in the two places named
  above. They are not deleted — the roadmap keeps its original text and points here.
- `bootstrap_set.py` can exit 1 on a Set that no script can repair. That is the intended
  outcome, and `render_divergences` exists so the exit tells the human what to do in
  Live rather than what went wrong in Python.
- The check "does this track have an instrument" is by device *presence*, not identity:
  the LOM reports `devices/name`, so a track carrying Wavetable instead of Drift passes.
  That is deliberate — the constraint is "something makes sound", not "exactly Drift".
- Moving to Live Suite later relaxes the 8-track cap and restores sampled instruments.
  Both are single-line changes here: `LITE_TRACK_LIMIT` and the `instrument` field.
- The `ableton-lom` skill and `.claude/rules/daw-integration.md` are updated to match;
  ADR-000 keeps its text and gains a pointer to this file.
