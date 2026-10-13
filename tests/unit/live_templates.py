"""Hand-written stand-ins for the Core Library presets the import copies its shape from.

Only the elements `garagem.sounds.live_preset` touches, in the nesting Live 12 writes them
(read off `Guitar Electric Clean.adg`, `Analog Clip.adv` and `Hi.adv`). Nothing of Ableton's is
committed; the real templates are exercised where Live is installed.
"""

from __future__ import annotations


def _zone(tag: str, low: int, high: int) -> str:
    return (
        f"<{tag}><Min Value='{low}' /><Max Value='{high}' />"
        f"<CrossfadeMin Value='{low}' /><CrossfadeMax Value='{high}' /></{tag}>"
    )


RACK = f"""<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12402">
  <GroupDevicePreset>
    <OverwriteProtectionNumber Value="3077" />
    <Device>
      <InstrumentGroupDevice Id="0">
        <UserName Value="Guitar Electric Clean" />
        <Annotation Value="Made by Ableton" />
        <Branches />
      </InstrumentGroupDevice>
    </Device>
    <PresetRef />
    <BranchPresets>
      <InstrumentBranchPreset Id="0">
        <Name Value="" />
        <DevicePresets>
          <AbletonDevicePreset Id="0">
            <OverwriteProtectionNumber Value="3077" />
            <Device>
              <OriginalSimpler Id="0">
                <UserName Value="Guitar Electric Clean" />
                <Player>
                  <MultiSampleMap>
                    <SampleParts>
                      <MultiSamplePart Id="0" HasImportedSlicePoints="true">
                        <Name Value="Guitar Electric Bend C3" />
                        {_zone("KeyRange", 0, 127)}
                        {_zone("VelocityRange", 1, 127)}
                        <RootKey Value="60" />
                        <Detune Value="0" />
                        <Volume Value="1" />
                        <SampleStart Value="0" />
                        <SampleEnd Value="166936" />
                        <SustainLoop>
                          <Start Value="0" /><End Value="166936" /><Mode Value="1" />
                        </SustainLoop>
                        <ReleaseLoop>
                          <Start Value="0" /><End Value="166936" /><Mode Value="3" />
                        </ReleaseLoop>
                        <SampleRef>
                          <FileRef>
                            <RelativePathType Value="5" />
                            <RelativePath Value="Samples/Guitar Electric Bend C3.aif" />
                            <Path Value="/Volumes/data/Guitar Electric Bend C3.aif" />
                            <Type Value="2" />
                            <LivePackName Value="Core Library" />
                            <LivePackId Value="www.ableton.com/0" />
                            <OriginalFileSize Value="500865" />
                            <OriginalCrc Value="38976" />
                          </FileRef>
                          <LastModDate Value="1778574055" />
                          <DefaultDuration Value="166937" />
                          <DefaultSampleRate Value="48000" />
                        </SampleRef>
                        <SlicePoints>
                          <SlicePoint TimeInSeconds="0" Rank="0" NormalizedEnergy="1" />
                        </SlicePoints>
                      </MultiSamplePart>
                    </SampleParts>
                  </MultiSampleMap>
                </Player>
                <Filter><IsOn><Manual Value="true" /></IsOn></Filter>
                <VolumeAndPan>
                  <Volume><Manual Value="-19.7999992" /></Volume>
                  <Envelope><ReleaseTime><Manual Value="2000.00012" /></ReleaseTime></Envelope>
                </VolumeAndPan>
                <Globals><NumVoices Value="9" /></Globals>
              </OriginalSimpler>
            </Device>
            <PresetRef><FilePresetRef Id="0" /></PresetRef>
          </AbletonDevicePreset>
          <AbletonDevicePreset Id="1">
            <OverwriteProtectionNumber Value="3077" />
            <Device><Delay Id="0"><UserName Value="Delay" /></Delay></Device>
            <PresetRef />
          </AbletonDevicePreset>
        </DevicePresets>
        <MixerPreset />
        <ZoneSettings>
          {_zone("KeyRange", 0, 127)}
          {_zone("VelocityRange", 1, 127)}
        </ZoneSettings>
      </InstrumentBranchPreset>
    </BranchPresets>
    <ReturnBranchPresets />
  </GroupDevicePreset>
</Ableton>
"""

SATURATOR = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12402">
  <Saturator>
    <UserName Value="Analog Clip" />
    <LastPresetRef>
      <Value>
        <FilePresetRef Id="0">
          <FileRef>
            <RelativePath Value="Devices/Audio Effects/Saturator/Analog Clip.adv" />
          </FileRef>
        </FilePresetRef>
      </Value>
    </LastPresetRef>
    <PreDrive><Manual Value="9" /></PreDrive>
    <PreDcFilter><Manual Value="false" /></PreDcFilter>
    <Type><Manual Value="0" /></Type>
    <PostDrive><Manual Value="-7" /></PostDrive>
    <Oversampling Value="false" />
  </Saturator>
</Ableton>
"""

EQ_THREE = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12402">
  <FilterEQ3>
    <UserName Value="" />
    <GainLo><Manual Value="0.00031622799" /></GainLo>
    <GainMid><Manual Value="0.00031622799" /></GainMid>
    <GainHi><Manual Value="1.48977268" /></GainHi>
    <FreqLo><Manual Value="249.999969" /></FreqLo>
    <FreqHi><Manual Value="1766.57275" /></FreqHi>
  </FilterEQ3>
</Ableton>
"""
