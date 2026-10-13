"""Writes an Instrument Rack preset (`.adg`) that Live 12 Lite can load (ADR-029).

The shape is not invented here; it comes from presets the installed Live ships:

- **The rack.** The template is an Instrument Rack whose first chain holds a Simpler. That
  chain is copied once per `Chain`, and each copy plays one sample over one key and velocity
  zone. The rack's zones are Lite's own multisample, since Lite has no Sampler.
- **The effects.** Each `Effect` is a device preset (`.adv`) from Core Library with some of its
  knobs set. When there are effects, the sample rack is nested inside an outer rack with the
  effects after it, as Core Library's own layered racks do. One drag then brings the guitar and
  its drive together.

Nothing else of the templates changes, so the XML always matches the version of Live that
wrote it. An `.adg` is gzipped XML, written byte for byte the same each time (gzip's clock
included), so a second import changes nothing.
"""

from __future__ import annotations

import copy
import gzip
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

# Live resolves a `RelativePathType` of 1 against the folder of the document that refers to it,
# and falls back to the absolute `Path`. Both are written, so the preset finds its samples
# whichever way Live looks.
RELATIVE_TO_DOCUMENT: Final = "1"
# What Live writes as a sample's `Type`.
SAMPLE_FILE_TYPE: Final = "2"


class PresetTemplateError(ValueError):
    """A template is not the shape this writer copies from."""


@dataclass(frozen=True)
class SampleFile:
    """A WAV on this Mac, as a preset refers to it."""

    path: str
    # From the folder the preset is written in.
    relative: str
    frames: int
    rate: int
    size: int


@dataclass(frozen=True)
class Chain:
    name: str
    key_lo: int
    key_hi: int
    vel_lo: int
    vel_hi: int
    root: int
    tune_cents: int
    gain_db: float
    sample: SampleFile


@dataclass(frozen=True)
class Voice:
    """The Simpler settings every chain shares."""

    volume_db: float
    release_ms: float
    # Simpler's polyphony. A power chord ringing into the next is six voices.
    voices: int


@dataclass(frozen=True)
class Effect:
    """A Core Library device preset, renamed, with these parameters set."""

    template: str
    name: str
    # Parameter element and the value its `Manual` takes, as Live writes it.
    settings: tuple[tuple[str, str], ...]


def instrument_rack(
    template: str,
    name: str,
    annotation: str,
    chains: Sequence[Chain],
    voice: Voice,
    effects: Sequence[Effect] = (),
) -> bytes:
    """The template's rack with one Simpler chain per `Chain`, then `effects`, gzipped."""
    if not chains:
        raise ValueError("a rack with no chains plays nothing")
    root = ET.fromstring(template)
    preset = _find(root, "GroupDevicePreset")
    samples = _sample_rack(preset, name, chains, voice)
    _set(samples, "Device/InstrumentGroupDevice/Annotation", annotation)
    if effects:
        outer = _effects_rack(preset, name, samples, effects)
        _replace(root, preset, outer)
        preset = outer
    else:
        _replace(root, preset, samples)
        preset = samples
    _set(preset, "Device/InstrumentGroupDevice/Annotation", annotation)
    body = ET.tostring(root, encoding="unicode")
    document = '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
    return gzip.compress(document.encode("utf-8"), mtime=0)


def _sample_rack(
    preset: ET.Element, name: str, chains: Sequence[Chain], voice: Voice
) -> ET.Element:
    rack = copy.deepcopy(preset)
    _set(rack, "Device/InstrumentGroupDevice/UserName", name)
    branches = _find(rack, "BranchPresets")
    model = _simpler_only(_first_chain(branches))
    _clear(branches)
    for index, chain in enumerate(chains):
        branches.append(_chain(model, index, chain, voice))
    return rack


def _effects_rack(
    preset: ET.Element, name: str, samples: ET.Element, effects: Sequence[Effect]
) -> ET.Element:
    """An outer rack of one chain: the sample rack, then each effect in turn."""
    outer = copy.deepcopy(preset)
    _set(outer, "Device/InstrumentGroupDevice/UserName", name)
    branches = _find(outer, "BranchPresets")
    chain = copy.deepcopy(_first_chain(branches))
    _clear(branches)
    branches.append(chain)
    chain.set("Id", "0")
    _set(chain, "Name", name)
    _range(_find(chain, "ZoneSettings/KeyRange"), 0, 127)
    _range(_find(chain, "ZoneSettings/VelocityRange"), 1, 127)

    devices = _find(chain, "DevicePresets")
    wrapper = _find(devices, "AbletonDevicePreset")
    _clear(devices)
    _set(samples, "Device/InstrumentGroupDevice/UserName", f"{name} Samples")
    samples.set("Id", "0")
    devices.append(samples)
    for index, effect in enumerate(effects, start=1):
        devices.append(_effect(wrapper, index, effect))
    return outer


def _effect(wrapper: ET.Element, index: int, effect: Effect) -> ET.Element:
    root = ET.fromstring(effect.template)
    if len(root) != 1:
        raise PresetTemplateError("an effect template holds exactly one device")
    device = copy.deepcopy(root[0])
    # Saved alone, a device has no `Id`; inside a rack Live lists it by one, and refuses the
    # whole preset as corrupt without it ("Not all list members have Ids").
    device.set("Id", "0")
    _set(device, "UserName", effect.name)
    for parameter, value in effect.settings:
        # An automatable knob keeps its value in `Manual`; a switch like Oversampling, on itself.
        element = _find(device, parameter)
        manual = element.find("Manual")
        (element if manual is None else manual).set("Value", value)

    preset = copy.deepcopy(wrapper)
    preset.set("Id", str(index))
    holder = _find(preset, "Device")
    _clear(holder)
    holder.append(device)
    # The preset the device came from, so Live names its origin as it does for its own.
    origin = device.find("LastPresetRef/Value/FilePresetRef")
    reference = _find(preset, "PresetRef")
    _clear(reference)
    if origin is not None:
        reference.append(copy.deepcopy(origin))
    return preset


def _first_chain(branches: ET.Element) -> ET.Element:
    first = branches.find("InstrumentBranchPreset")
    if first is None:
        raise PresetTemplateError("the template rack has no chain")
    return first


def _simpler_only(branch: ET.Element) -> ET.Element:
    """The template's chain with its Simpler alone, every effect after it removed."""
    model = copy.deepcopy(branch)
    devices = _find(model, "DevicePresets")
    simplers = [preset for preset in devices if preset.find("Device/OriginalSimpler") is not None]
    if not simplers:
        raise PresetTemplateError("the template's first chain has no Simpler")
    for preset in list(devices):
        if preset is not simplers[0]:
            devices.remove(preset)
    return model


def _chain(model: ET.Element, index: int, chain: Chain, voice: Voice) -> ET.Element:
    branch = copy.deepcopy(model)
    branch.set("Id", str(index))
    _set(branch, "Name", chain.name)
    _range(_find(branch, "ZoneSettings/KeyRange"), chain.key_lo, chain.key_hi)
    _range(_find(branch, "ZoneSettings/VelocityRange"), chain.vel_lo, chain.vel_hi)

    simpler = _find(branch, "DevicePresets/AbletonDevicePreset/Device/OriginalSimpler")
    _set(simpler, "UserName", "")
    _manual(simpler, "VolumeAndPan/Volume", f"{voice.volume_db:g}")
    _manual(simpler, "VolumeAndPan/Envelope/ReleaseTime", f"{voice.release_ms:g}")
    _manual(simpler, "Filter/IsOn", "false")
    _set(simpler, "Globals/NumVoices", str(voice.voices))

    parts = _find(simpler, "Player/MultiSampleMap/SampleParts")
    part = copy.deepcopy(_find(parts, "MultiSamplePart"))
    _clear(parts)
    parts.append(_part(part, chain))
    return branch


def _part(part: ET.Element, chain: Chain) -> ET.Element:
    sample = chain.sample
    last = str(sample.frames - 1)
    part.set("Id", "0")
    part.set("HasImportedSlicePoints", "false")
    _set(part, "Name", chain.name)
    _range(_find(part, "KeyRange"), 0, 127)
    _range(_find(part, "VelocityRange"), 1, 127)
    _set(part, "RootKey", str(chain.root))
    _set(part, "Detune", str(chain.tune_cents))
    _set(part, "Volume", f"{10 ** (chain.gain_db / 20):.6g}")
    _set(part, "SampleStart", "0")
    _set(part, "SampleEnd", last)
    for loop in ("SustainLoop", "ReleaseLoop"):
        _set(part, f"{loop}/Start", "0")
        _set(part, f"{loop}/End", last)
    _set(part, "SustainLoop/Mode", "0")

    ref = _find(part, "SampleRef")
    _set(ref, "FileRef/RelativePathType", RELATIVE_TO_DOCUMENT)
    _set(ref, "FileRef/RelativePath", sample.relative)
    _set(ref, "FileRef/Path", sample.path)
    _set(ref, "FileRef/Type", SAMPLE_FILE_TYPE)
    _set(ref, "FileRef/LivePackName", "")
    _set(ref, "FileRef/LivePackId", "")
    _set(ref, "FileRef/OriginalFileSize", str(sample.size))
    _set(ref, "FileRef/OriginalCrc", "0")
    _set(ref, "LastModDate", "0")
    _set(ref, "DefaultDuration", str(sample.frames))
    _set(ref, "DefaultSampleRate", str(sample.rate))

    slices = part.find("SlicePoints")
    if slices is not None:
        _clear(slices)
    return part


def _replace(root: ET.Element, old: ET.Element, new: ET.Element) -> None:
    index = list(root).index(old)
    root.remove(old)
    root.insert(index, new)


def _clear(element: ET.Element) -> None:
    for child in list(element):
        element.remove(child)


def _range(zone: ET.Element, low: int, high: int) -> None:
    """A zone with hard edges: no crossfade on either side."""
    for field, value in (
        ("Min", low),
        ("Max", high),
        ("CrossfadeMin", low),
        ("CrossfadeMax", high),
    ):
        _set(zone, field, str(value))


def _manual(element: ET.Element, path: str, value: str) -> None:
    _set(element, f"{path}/Manual", value)


def _set(element: ET.Element, path: str, value: str) -> None:
    _find(element, path).set("Value", value)


def _find(element: ET.Element, path: str) -> ET.Element:
    found = element.find(path)
    if found is None:
        raise PresetTemplateError(f"the template has no {path} under {element.tag}")
    return found
