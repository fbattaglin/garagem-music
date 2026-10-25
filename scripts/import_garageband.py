"""Rebuilds GarageBand's guitars, basses and drum kits as Live presets, from this Mac (ADR-029).

    uv run python scripts/import_garageband.py --dry-run    # what would be built; writes nothing
    uv run python scripts/import_garageband.py              # every preset
    uv run python scripts/import_garageband.py --only drums --only bass
    uv run python scripts/import_garageband.py --palm-mute-below 80

Live 12 Lite cannot open GarageBand's instruments (EXS is Logic's format, and Lite has no
Sampler), so each becomes an Instrument Rack of Simplers, one per sample, zoned by key and
velocity:

- **Guitars:** the Vintage Strat and the Warm Electric, every string sampled ringing and
  palm-muted. Each note is played on one string, the lowest that reaches it in the first frets,
  and velocities under `palm_mute_below` play the palm mute. The rack sits inside another,
  followed by Lite's Saturator and an EQ Three standing in for a speaker cabinet. Each guitar
  comes twice: a crunch for GTR (the indie verse) and a heavier one for GTR 2 (the arena chorus).
- **Basses:** Picked Rock and Fingerstyle, in their five velocity layers, an octave below where
  GarageBand maps them, so the band's low E is the string's.
- **Kits:** Drum Kit Designer's SoCal and Heavy, each piece on the note the band writes for it
  (`sounds/kit.py`), so `session.toml`'s `pitches` for the kit is empty.

Their knobs are starting points; the sound is chosen by ear in Live (ADR-028). The split is read
from `session.toml`'s guitar track, or `--palm-mute-below`, and must be the number the track
declares: the band clamps every guitar note to it on the way out.

Nothing is downloaded. Apple's files are only read, and audio is decoded with macOS's own
`afconvert`. The WAVs and the preset go into Live's User Library, never into this repository.
Running it twice writes the same bytes.
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from garagem.daw import SessionSpecError, load_session
from garagem.sounds.audio import cut
from garagem.sounds.exs import ExsError, ExsInstrument, ExsSample, ExsZone, parse_exs
from garagem.sounds.kit import KitError, kit_parts
from garagem.sounds.live_preset import (
    Chain,
    Effect,
    PresetTemplateError,
    SampleFile,
    Voice,
    instrument_rack,
)
from garagem.sounds.mapping import BASS_OCTAVE_DOWN, Part, guitar_parts, multisample_parts

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SESSION = ROOT / "session.toml"

LOGIC_INSTRUMENTS: Final = Path("/Library/Application Support/Logic/Sampler Instruments")
# Where GarageBand keeps the audio its instruments play, consolidated or one file per note.
SAMPLE_ROOTS: Final = (
    Path("/Library/Application Support/Logic/EXS Factory Samples"),
    Path("/Library/Application Support/GarageBand/Instrument Library/Sampler/Sampler Files"),
)
USER_LIBRARY: Final = Path.home() / "Music" / "Ableton" / "User Library"
PRESETS: Final = Path("Presets") / "Instruments" / "Instrument Rack" / "GARAGEM"
SAMPLES: Final = Path("Samples") / "GARAGEM"
# Presets of the installed Live's own: the rack and Simpler every chain is copied from, and the
# two devices after them.
CORE_LIBRARY: Final = Path("Contents/App-Resources/Core Library")
RACK_TEMPLATE: Final = Path("Racks/Instrument Racks/Guitar/Guitar Electric Clean.adg")
SATURATOR_TEMPLATE: Final = Path("Devices/Audio Effects/Saturator/Analog Clip.adv")
EQ_TEMPLATE: Final = Path("Devices/Audio Effects/EQ Three/Hi.adv")

# A muted chug is written at most around 82 and a ringing strum at least around 75; the band
# clamps both to this split (`engines.guitar.articulated`), so it moves a few notes, never many.
DEFAULT_PALM_MUTE_BELOW: Final = 80
# GarageBand's samples peak near 0 dBFS, and a power chord is three of them: 12 dB of room
# keeps the chord out of clipping before the Saturator, which is where the drive belongs. The
# sustain and the velocity's pull on the volume are the template's, which the Strat was
# approved with: a held chord fades over the Simpler's 21-second decay, under the string's own.
GUITAR_VOICE: Final = Voice(
    volume_db=-12.0, release_ms=150.0, voices=12, sustain_db=-70.0, velocity_to_volume=0.35
)
# A held note rings as long as the string does and stops when it is let go; four voices let one
# note ring into the next without a click. As even as the guitar: a rock bass is.
BASS_VOICE: Final = Voice(
    volume_db=-12.0, release_ms=100.0, voices=4, sustain_db=0.0, velocity_to_volume=0.35
)
# Every hit rings out, as in Core Library's own kits: a release of a minute means a note's end
# never cuts a cymbal. Two voices per layer let a hit ring under the next. Drum Kit Designer's
# layers are normalised and its zone levels assume Logic's velocity curve (a soft kick is set
# 8 dB above a hard one), so velocity carries the dynamics in full.
KIT_VOICE: Final = Voice(
    volume_db=-10.0, release_ms=60000.0, voices=2, sustain_db=0.0, velocity_to_volume=1.0
)


# Saturator's curves, as Live numbers them.
MEDIUM_CURVE: Final = "2"
HARD_CURVE: Final = "3"
# EQ Three's gains are amplitudes: 1 is 0 dB.
UNITY: Final = "1"
MINUS_6_DB: Final = "0.5"
MINUS_15_DB: Final = "0.178"


@dataclass(frozen=True)
class Drive:
    """What follows the samples: a Saturator, then an EQ Three for a cabinet."""

    suffix: str
    pre_drive_db: float
    curve: str
    post_drive_db: float


# Starting points, to be moved by ear in Live. The cabinet is the same for both: lows under
# 120 Hz down 6 dB so the drive does not turn to mud, the mids where the guitar lives left
# alone, highs over 5 kHz down 15 dB, which is roughly where a guitar speaker gives up. Every
# band is set: the template is Core Library's "Hi", which silences the lows and the mids, and a
# band left out keeps its -70 dB (phase-8-findings §4).
CRUNCH: Final = Drive(suffix="", pre_drive_db=15.0, curve=MEDIUM_CURVE, post_drive_db=-12.0)
HEAVY: Final = Drive(suffix=" Heavy", pre_drive_db=27.0, curve=HARD_CURVE, post_drive_db=-20.0)
CABINET: Final = (
    ("GainLo", MINUS_6_DB),
    ("FreqLo", "120"),
    ("GainMid", UNITY),
    ("GainHi", MINUS_15_DB),
    ("FreqHi", "5000"),
)


@dataclass(frozen=True)
class Source:
    name: str
    # Under `LOGIC_INSTRUMENTS`.
    exs: Path


GUITARS: Final = (
    Source("GB Vintage Strat", Path("08 Guitars/Vintage Strat.exs")),
    Source("GB Warm Electric", Path("08 Guitars/Warm Electric.exs")),
)
ELECTRIC_BASS: Final = Path("02 Bass/02 Electric Bass")
BASSES: Final = (
    Source("GB Picked Rock Bass", ELECTRIC_BASS / "Picked Rock Bass.exs"),
    Source("GB Fingerstyle Bass", ELECTRIC_BASS / "Fingerstyle Electric Bass.exs"),
)
DRUM_KIT_DESIGNER: Final = Path(
    "03 Drums & Percussion/04 Drum Kit Designer/Drum Kit Designer/Stereo"
)
KITS: Final = (
    Source("GB SoCal Kit", DRUM_KIT_DESIGNER / "SoCal Kit.exs"),
    Source("GB Heavy Kit", DRUM_KIT_DESIGNER / "Heavy Kit.exs"),
)
FAMILIES: Final = {"guitar": GUITARS, "bass": BASSES, "drums": KITS}
DRIVES: Final = (CRUNCH, HEAVY)


@dataclass(frozen=True)
class Preset:
    name: str
    voice: Voice
    effects: tuple[Effect, ...]


@dataclass(frozen=True)
class Templates:
    rack: str
    saturator: str
    eq: str


class NotOnThisMacError(RuntimeError):
    """Something the import needs is not where it should be, said in plain words."""


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    families = list(dict.fromkeys(args.only or FAMILIES))
    try:
        split = args.palm_mute_below or _split_from(args.session)
        templates = None if args.dry_run else _templates(args.live)
        for family in families:
            for source in FAMILIES[family]:
                instrument = _instrument(source)
                parts = _parts(family, instrument, split)
                if args.dry_run:
                    heading = _heading(family, split)
                    sys.stdout.write(_table(source, instrument, parts, heading))
                    continue
                assert templates is not None
                presets = _presets(family, source, templates)
                built = _build(
                    source, instrument, parts, presets, templates.rack, args.user_library
                )
                sys.stdout.write(built)
    except (NotOnThisMacError, ExsError, KitError, PresetTemplateError, SessionSpecError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if not args.dry_run:
        sys.stdout.write(_next_steps(families, split))
    return 0


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="show the zones; write nothing")
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(FAMILIES),
        help="import only these; repeat for more (default: all)",
    )
    parser.add_argument(
        "--palm-mute-below",
        type=int,
        default=None,
        help=f"the velocity split (default: session.toml's, else {DEFAULT_PALM_MUTE_BELOW})",
    )
    parser.add_argument("--session", type=Path, default=DEFAULT_SESSION)
    parser.add_argument("--user-library", type=Path, default=USER_LIBRARY)
    parser.add_argument(
        "--live", type=Path, default=None, help="Live's .app (default: the one in /Applications)"
    )
    return parser.parse_args(argv)


def _split_from(session: Path) -> int:
    spec = load_session(session)
    for track in spec.tracks:
        if track.role == "guitar" and track.palm_mute_below is not None:
            return track.palm_mute_below
    return DEFAULT_PALM_MUTE_BELOW


def _templates(live: Path | None) -> Templates:
    apps = [live] if live else sorted(Path("/Applications").glob("Ableton Live 12*.app"))
    for app in apps:
        library = app / CORE_LIBRARY
        paths = [library / RACK_TEMPLATE, library / SATURATOR_TEMPLATE, library / EQ_TEMPLATE]
        if all(path.is_file() for path in paths):
            rack, saturator, eq = (gzip.decompress(p.read_bytes()).decode("utf-8") for p in paths)
            return Templates(rack=rack, saturator=saturator, eq=eq)
    raise NotOnThisMacError(
        "Could not find Live 12 in /Applications with the Core Library presets this import "
        f"copies its shape from ({RACK_TEMPLATE.name}, {SATURATOR_TEMPLATE.name}, "
        f"{EQ_TEMPLATE.name}). Pass --live with Live's .app."
    )


def _parts(family: str, instrument: ExsInstrument, split: int) -> tuple[Part, ...]:
    if family == "guitar":
        return guitar_parts(instrument, split)
    if family == "bass":
        return multisample_parts(instrument, BASS_OCTAVE_DOWN)
    return kit_parts(instrument)


def _presets(family: str, source: Source, templates: Templates) -> tuple[Preset, ...]:
    """A guitar once per drive; a bass and a kit once, dry."""
    if family == "guitar":
        return tuple(
            Preset(source.name + drive.suffix, GUITAR_VOICE, _effects(drive, templates))
            for drive in DRIVES
        )
    return (Preset(source.name, BASS_VOICE if family == "bass" else KIT_VOICE, ()),)


def _heading(family: str, split: int) -> str:
    if family == "guitar":
        return f"palm mute below velocity {split}"
    if family == "bass":
        return "an octave below GarageBand's keys, the low E on 28"
    return "each piece on the note the band writes"


def _instrument(source: Source) -> ExsInstrument:
    path = LOGIC_INSTRUMENTS / source.exs
    if not path.is_file():
        raise NotOnThisMacError(
            f"GarageBand's {source.exs.stem} is not on this Mac ({path}). Open GarageBand "
            "once: it installs its basic sounds the first time it starts. Then run this again."
        )
    return parse_exs(path.read_bytes())


def _audio_file(sample: ExsSample) -> Path:
    where = Path(sample.folder) / sample.file
    if sample.folder and where.is_file():
        return where
    for root in SAMPLE_ROOTS:
        for found in sorted(root.rglob(sample.file)):
            return found
    raise NotOnThisMacError(
        f"GarageBand's sample {sample.file} is not on this Mac. In GarageBand, open "
        "GarageBand > Sound Library > Download All Available Sounds, then run this again."
    )


def _build(
    source: Source,
    instrument: ExsInstrument,
    parts: Sequence[Part],
    presets: Sequence[Preset],
    rack: str,
    library: Path,
) -> str:
    """The samples once, then each preset playing them."""
    preset_dir = library / PRESETS
    roots = _roots_in_order(parts)
    files = _write_samples(instrument, roots, library / SAMPLES / source.name, preset_dir)
    chains = [
        Chain(
            name=part.name,
            key_lo=part.key_lo,
            key_hi=part.key_hi,
            vel_lo=part.vel_lo,
            vel_hi=part.vel_hi,
            root=part.root,
            tune_cents=part.zone.tune_cents,
            gain_db=part.gain_db,
            sample=files[part.zone],
        )
        for part in parts
    ]
    annotation = (
        f"GarageBand's {instrument.name or source.exs.stem}, rebuilt by "
        "garagem's scripts/import_garageband.py (ADR-029)."
    )
    preset_dir.mkdir(parents=True, exist_ok=True)
    for preset in presets:
        data = instrument_rack(rack, preset.name, annotation, chains, preset.voice, preset.effects)
        (preset_dir / f"{preset.name}.adg").write_bytes(data)
    megabytes = sum(file.size for file in files.values()) / 1e6
    names = " and ".join(preset.name for preset in presets)
    return f"{names}: {len(chains)} zones over {len(files)} samples, {megabytes:.0f} MB\n"


def _effects(drive: Drive, templates: Templates) -> tuple[Effect, ...]:
    saturator = Effect(
        template=templates.saturator,
        name="Drive" + drive.suffix,
        settings=(
            ("PreDrive", f"{drive.pre_drive_db:g}"),
            ("Type", drive.curve),
            ("PostDrive", f"{drive.post_drive_db:g}"),
            ("PreDcFilter", "true"),
            ("Oversampling", "true"),
        ),
    )
    cabinet = Effect(template=templates.eq, name="Cabinet", settings=CABINET)
    return (saturator, cabinet)


def _roots_in_order(parts: Sequence[Part]) -> dict[ExsZone, int]:
    """Every zone the parts play, once each, in the order the parts first play them, with the
    root that first part plays it at: a sample's file is named by it."""
    roots: dict[ExsZone, int] = {}
    for part in parts:
        roots.setdefault(part.zone, part.root)
    return roots


def _write_samples(
    instrument: ExsInstrument, roots: dict[ExsZone, int], sample_dir: Path, preset_dir: Path
) -> dict[ExsZone, SampleFile]:
    if sample_dir.exists():
        # Only this instrument's own folder, which nothing but this script writes into.
        shutil.rmtree(sample_dir)
    sample_dir.mkdir(parents=True)
    zones = list(roots)
    numbers = {zone: number for number, zone in enumerate(zones, start=1)}
    files: dict[ExsZone, SampleFile] = {}
    by_sample: dict[int, list[ExsZone]] = {}
    for zone in zones:
        by_sample.setdefault(zone.sample, []).append(zone)
    with tempfile.TemporaryDirectory() as scratch:
        for index, these in sorted(by_sample.items()):
            sample = instrument.samples[index]
            wav = _decoded(_audio_file(sample), sample.bits, Path(scratch))
            cuts = cut(wav, [(zone.start, zone.end) for zone in these])
            for zone, piece in zip(these, cuts, strict=True):
                path = sample_dir / f"{numbers[zone]:03d} {roots[zone]}.wav"
                path.write_bytes(piece.data)
                files[zone] = SampleFile(
                    path=str(path),
                    relative=os.path.relpath(path, preset_dir),
                    frames=piece.frames,
                    rate=piece.rate,
                    size=len(piece.data),
                )
    return files


def _decoded(source: Path, bits: int, scratch: Path) -> bytes:
    """`source` as a little-endian PCM WAV, through macOS's own `afconvert`."""
    target = scratch / f"{source.stem}.wav"
    depth = "LEI16" if bits <= 16 else "LEI24"
    completed = subprocess.run(
        ["/usr/bin/afconvert", "-f", "WAVE", "-d", depth, str(source), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise NotOnThisMacError(f"afconvert could not decode {source}: {completed.stderr.strip()}")
    return target.read_bytes()


def _table(source: Source, instrument: ExsInstrument, parts: Sequence[Part], heading: str) -> str:
    lines = [
        f"{source.name} — from {instrument.name or source.exs.name}, {heading}:",
        f"  {'zone':<24} {'keys':>7} {'velocity':>9} {'root':>5} {'seconds':>8}",
    ]
    for part in parts:
        rate = instrument.samples[part.zone.sample].rate or 1
        seconds = (part.zone.end - part.zone.start) / rate
        lines.append(
            f"  {part.name:<24} {part.key_lo:>3}-{part.key_hi:<3} "
            f"{part.vel_lo:>4}-{part.vel_hi:<4} {part.root:>5} {seconds:>8.1f}"
        )
    lines.append(f"  {len(parts)} zones\n\n")
    return "\n".join(lines)


def _next_steps(families: Sequence[str], split: int) -> str:
    steps = [
        "In the browser on the left, open User Library > Presets > Instruments >\n"
        "     Instrument Rack > GARAGEM.",
    ]
    roles: list[str] = []
    if "guitar" in families:
        steps += [
            "Drag GB Vintage Strat onto the GTR track's name. Live swaps its instrument.",
            "If there is no GTR 2 yet: click GTR's name, press Cmd-D to duplicate it, and\n"
            "     rename the copy GTR 2 (Cmd-R). It must sit right under GTR.",
            "Drag GB Vintage Strat Heavy onto GTR 2's name.",
        ]
        roles += ["guitar", "guitar_double"]
    if "bass" in families:
        steps.append("Drag GB Picked Rock Bass onto the BASS track's name.")
        roles.append("bass")
    if "drums" in families:
        steps.append("Drag GB SoCal Kit onto the DRUMS track's name.")
        roles.append("drums")
    steps.append("Save the Set (Cmd-S).")
    lines = ["", "In Live, with the Set open:"]
    lines += [f"  {number}. {step}" for number, step in enumerate(steps, start=1)]
    if "guitar" in families:
        lines.append(f"session.toml's GTR and GTR 2 must say palm_mute_below = {split}.")
    only = "".join(f" --only {role}" for role in roles) if len(families) < len(FAMILIES) else ""
    lines += ["Then listen:", f"  uv run python scripts/soundcheck.py{only}", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
