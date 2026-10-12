"""The Instrument Rack preset: one Simpler chain per zone, then the drive (ADR-029)."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from live_templates import EQ_THREE, RACK, SATURATOR

from garagem.sounds.live_preset import (
    Chain,
    Effect,
    PresetTemplateError,
    SampleFile,
    Voice,
    instrument_rack,
)

VOICE = Voice(volume_db=-12.0, release_ms=150.0, voices=12)
CORE_LIBRARY = Path("/Applications/Ableton Live 12 Lite.app/Contents/App-Resources/Core Library")
REAL_RACK = CORE_LIBRARY / "Racks/Instrument Racks/Guitar/Guitar Electric Clean.adg"


def chain(
    name: str, key_lo: int, key_hi: int, vel_lo: int, vel_hi: int, gain_db: float = 0.0
) -> Chain:
    sample = SampleFile(
        path=f"/Users/me/Music/Ableton/User Library/Samples/GARAGEM/Strat/{name}.wav",
        relative=f"../../../../Samples/GARAGEM/Strat/{name}.wav",
        frames=58953,
        rate=44100,
        size=117950,
    )
    return Chain(name, key_lo, key_hi, vel_lo, vel_hi, 40, -5, gain_db, sample)


CHAINS = (chain("E2 E mute", 36, 40, 1, 79, gain_db=-6.0), chain("E2 E main soft", 36, 40, 80, 121))
DRIVE = (
    Effect(SATURATOR, "Drive", (("PreDrive", "15"), ("Type", "2"), ("Oversampling", "true"))),
    Effect(EQ_THREE, "Cabinet", (("GainHi", "0.1"), ("FreqHi", "3500"))),
)


def read(data: bytes) -> ET.Element:
    return ET.fromstring(gzip.decompress(data).decode("utf-8"))


def found(element: ET.Element, path: str) -> ET.Element:
    child = element.find(path)
    assert child is not None, path
    return child


def value(element: ET.Element, path: str) -> str:
    return found(element, path).get("Value", "")


def test_each_zone_is_a_chain_holding_one_simpler_and_nothing_after_it() -> None:
    rack = read(instrument_rack(RACK, "GB Vintage Strat", "from GarageBand", CHAINS, VOICE))

    preset = rack.find("GroupDevicePreset")
    assert preset is not None
    assert value(preset, "Device/InstrumentGroupDevice/UserName") == "GB Vintage Strat"
    assert value(preset, "Device/InstrumentGroupDevice/Annotation") == "from GarageBand"
    branches = preset.findall("BranchPresets/InstrumentBranchPreset")
    assert [b.get("Id") for b in branches] == ["0", "1"]
    for branch in branches:
        devices = branch.findall("DevicePresets/AbletonDevicePreset/Device/*")
        assert [d.tag for d in devices] == ["OriginalSimpler"]


def test_a_chain_answers_its_own_keys_and_velocities_with_hard_edges() -> None:
    rack = read(instrument_rack(RACK, "GB", "", CHAINS, VOICE))
    branch = rack.findall(".//InstrumentBranchPreset")[0]
    assert value(branch, "Name") == "E2 E mute"
    zone = branch.find("ZoneSettings")
    assert zone is not None
    assert [
        value(zone, f"KeyRange/{f}") for f in ("Min", "Max", "CrossfadeMin", "CrossfadeMax")
    ] == [
        "36",
        "40",
        "36",
        "40",
    ]
    assert [
        value(zone, f"VelocityRange/{f}") for f in ("Min", "Max", "CrossfadeMin", "CrossfadeMax")
    ] == [
        "1",
        "79",
        "1",
        "79",
    ]


def test_the_simpler_plays_the_whole_cut_at_its_root_and_level() -> None:
    rack = read(instrument_rack(RACK, "GB", "", CHAINS, VOICE))
    part = rack.find(".//MultiSamplePart")
    assert part is not None
    assert part.get("HasImportedSlicePoints") == "false"
    assert value(part, "RootKey") == "40"
    assert value(part, "Detune") == "-5"
    assert value(part, "Volume") == "0.501187"
    assert (value(part, "SampleStart"), value(part, "SampleEnd")) == ("0", "58952")
    assert value(part, "SustainLoop/Mode") == "0"
    assert value(part, "KeyRange/Max") == "127"
    assert len(found(part, "SlicePoints")) == 0


def test_the_sample_is_found_beside_the_preset_or_by_its_full_path() -> None:
    rack = read(instrument_rack(RACK, "GB", "", CHAINS, VOICE))
    ref = rack.find(".//MultiSamplePart/SampleRef")
    assert ref is not None
    assert value(ref, "FileRef/RelativePathType") == "1"
    assert value(ref, "FileRef/RelativePath") == "../../../../Samples/GARAGEM/Strat/E2 E mute.wav"
    assert value(ref, "FileRef/Path").endswith("Samples/GARAGEM/Strat/E2 E mute.wav")
    assert value(ref, "FileRef/LivePackName") == ""
    assert (value(ref, "DefaultDuration"), value(ref, "DefaultSampleRate")) == ("58953", "44100")


def test_every_simpler_shares_the_voice() -> None:
    rack = read(instrument_rack(RACK, "GB", "", CHAINS, VOICE))
    for simpler in rack.iter("OriginalSimpler"):
        assert value(simpler, "VolumeAndPan/Volume/Manual") == "-12"
        assert value(simpler, "VolumeAndPan/Envelope/ReleaseTime/Manual") == "150"
        assert value(simpler, "Filter/IsOn/Manual") == "false"
        assert value(simpler, "Globals/NumVoices") == "12"


def test_with_effects_the_samples_are_nested_and_followed_by_the_drive() -> None:
    rack = read(instrument_rack(RACK, "GB Vintage Strat", "from GarageBand", CHAINS, VOICE, DRIVE))

    outer = rack.find("GroupDevicePreset")
    assert outer is not None
    assert value(outer, "Device/InstrumentGroupDevice/UserName") == "GB Vintage Strat"
    (only,) = outer.findall("BranchPresets/InstrumentBranchPreset")
    devices = list(found(only, "DevicePresets"))
    assert [d.tag for d in devices] == [
        "GroupDevicePreset",
        "AbletonDevicePreset",
        "AbletonDevicePreset",
    ]
    assert [d.get("Id") for d in devices] == ["0", "1", "2"]

    inner, saturator, eq = devices
    assert value(inner, "Device/InstrumentGroupDevice/UserName") == "GB Vintage Strat Samples"
    assert len(inner.findall("BranchPresets/InstrumentBranchPreset")) == 2

    drive = saturator.find("Device/Saturator")
    assert drive is not None
    assert value(drive, "UserName") == "Drive"
    assert value(drive, "PreDrive/Manual") == "15"
    assert value(drive, "Type/Manual") == "2"
    assert value(drive, "Oversampling") == "true"
    assert saturator.find("PresetRef/FilePresetRef") is not None

    cabinet = eq.find("Device/FilterEQ3")
    assert cabinet is not None
    assert value(cabinet, "GainHi/Manual") == "0.1"
    assert value(cabinet, "GainLo/Manual") == "0.00031622799"


def test_the_same_chains_write_the_same_bytes() -> None:
    first = instrument_rack(RACK, "GB", "x", CHAINS, VOICE, DRIVE)
    assert instrument_rack(RACK, "GB", "x", CHAINS, VOICE, DRIVE) == first


def test_a_rack_with_no_chains_is_refused() -> None:
    with pytest.raises(ValueError, match="no chains"):
        instrument_rack(RACK, "GB", "", (), VOICE)


def test_a_template_without_a_simpler_is_refused() -> None:
    no_simpler = RACK.replace("OriginalSimpler", "Operator")
    with pytest.raises(PresetTemplateError, match="no Simpler"):
        instrument_rack(no_simpler, "GB", "", CHAINS, VOICE)


def test_an_effect_setting_the_template_does_not_have_is_refused() -> None:
    wrong = (Effect(SATURATOR, "Drive", (("Overdrive", "1"),)),)
    with pytest.raises(PresetTemplateError, match="Overdrive"):
        instrument_rack(RACK, "GB", "", CHAINS, VOICE, wrong)


@pytest.mark.skipif(not REAL_RACK.is_file(), reason="Live 12 Lite is not installed here")
def test_the_installed_lives_own_presets_take_the_same_edits() -> None:
    def text(relative: str) -> str:
        return gzip.decompress((CORE_LIBRARY / relative).read_bytes()).decode("utf-8")

    effects = (
        Effect(
            text("Devices/Audio Effects/Saturator/Analog Clip.adv"),
            "Drive",
            (("PreDrive", "15"), ("Type", "2"), ("PostDrive", "-12"), ("Oversampling", "true")),
        ),
        Effect(
            text("Devices/Audio Effects/EQ Three/Hi.adv"),
            "Cabinet",
            (("GainLo", "0.5"), ("FreqLo", "120"), ("GainHi", "0.1"), ("FreqHi", "3500")),
        ),
    )
    template = text("Racks/Instrument Racks/Guitar/Guitar Electric Clean.adg")
    rack = read(instrument_rack(template, "GB", "", CHAINS, VOICE, effects))
    inner = found(
        rack,
        "GroupDevicePreset/BranchPresets/InstrumentBranchPreset/DevicePresets/GroupDevicePreset",
    )
    assert len(inner.findall("BranchPresets/InstrumentBranchPreset")) == 2
    assert [
        d.tag for d in rack.iter() if d.tag in ("Saturator", "FilterEQ3", "Delay", "Reverb")
    ] == [
        "Saturator",
        "FilterEQ3",
    ]
