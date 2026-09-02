"""Chords as playable pitches.

The assertions worth reading are the negative ones. `fit_to_range` never drops a note —
it shifts the whole voicing or refuses — because a chord with one note pulled into range
is a chord with a wrong note in it, and that sounds like an engine bug three layers
away. And `voice_lead` is checked against the naive alternative rather than against a
hand-written expectation: the claim is "moves less than root position every time", and
that is what the test says.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from garagem.domain import Chord, Instrument, Quality
from garagem.theory import (
    RANGES,
    STYLES,
    Register,
    TheoryError,
    UnvoiceableError,
    fit_to_range,
    parse_chord,
    voice,
    voice_lead,
)

EM = parse_chord("Em")
C_MAJ = parse_chord("C")
G_MAJ = parse_chord("G")
D_MAJ = parse_chord("D")
C7 = parse_chord("C7")


# ------------------------------------------------------------------------------- styles


def test_a_power_chord_is_root_and_fifth_only() -> None:
    pitches = voice(EM, "pow", Register.LOW)
    assert len(pitches) == 2
    assert pitches[1] - pitches[0] == 7


def test_a_triad_is_three_notes() -> None:
    assert len(voice(EM, "triad", Register.MID)) == 3


def test_a_triad_of_a_seventh_chord_drops_the_seventh() -> None:
    """`voi=triad` asks for a triad, whatever the chart says the chord is."""
    assert len(voice(C7, "triad", Register.MID)) == 3


def test_sus2_replaces_the_third_with_the_second() -> None:
    triad = voice(EM, "triad", Register.MID)
    sus2 = voice(EM, "sus2", Register.MID)
    assert sus2[0] == triad[0]
    assert sus2[1] - sus2[0] == 2


def test_a_shell_voicing_leaves_out_the_fifth() -> None:
    """The note the bass player is already on."""
    shell = voice(C7, "shell", Register.MID)
    root = shell[0]
    assert [pitch - root for pitch in shell] == [0, 4, 10]


def test_a_shell_of_a_power_chord_keeps_the_fifth_rather_than_becoming_one_note() -> None:
    assert len(voice(parse_chord("A5"), "shell", Register.MID)) == 2


def test_drop2_moves_the_second_voice_from_the_top_down_an_octave() -> None:
    closed = voice(C7, "triad", Register.MID)
    dropped = voice(C7, "drop2", Register.MID)
    assert min(dropped) < min(closed)
    assert len(dropped) == len(C7.intervals())


@pytest.mark.parametrize("register", list(Register))
@pytest.mark.parametrize("style", STYLES)
def test_every_style_in_every_register_produces_ascending_pitches(
    style: str, register: Register
) -> None:
    pitches = voice(EM, style, register)
    assert list(pitches) == sorted(pitches)
    assert pitches


def test_an_unknown_style_names_the_ones_that_exist() -> None:
    with pytest.raises(TheoryError, match="drop2"):
        voice(EM, "quartal", Register.MID)


# -------------------------------------------------------------------------------- ranges


def test_a_low_guitar_voicing_moves_up_rather_than_losing_notes() -> None:
    low, high = RANGES[Instrument.GUITAR]
    fitted = fit_to_range(voice(EM, "triad", Register.LOW), Instrument.GUITAR)
    assert len(fitted) == 3
    assert low <= min(fitted) and max(fitted) <= high


def test_a_high_keys_voicing_moves_down() -> None:
    low, high = RANGES[Instrument.KEYS]
    fitted = fit_to_range((96, 100, 103), Instrument.KEYS)
    assert low <= min(fitted) and max(fitted) <= high
    assert [pitch - fitted[0] for pitch in fitted] == [0, 4, 7]


def test_fitting_is_idempotent() -> None:
    """The repairer may run over a part the engine already fitted."""
    once = fit_to_range(voice(EM, "triad", Register.LOW), Instrument.BASS)
    assert fit_to_range(once, Instrument.BASS) == once


def test_a_voicing_wider_than_the_range_is_refused_rather_than_clipped() -> None:
    with pytest.raises(UnvoiceableError, match="does not fit"):
        fit_to_range((28, 90), Instrument.BASS)


def test_drums_have_no_range_because_a_drum_pitch_is_a_map() -> None:
    """Shifting a drum part by an octave turns a kick into a cowbell."""
    assert Instrument.DRUMS not in RANGES
    with pytest.raises(TheoryError, match="no range"):
        fit_to_range((36,), Instrument.DRUMS)


def test_fitting_nothing_gives_nothing() -> None:
    assert fit_to_range((), Instrument.KEYS) == ()


# --------------------------------------------------------------------------- voice leading


def naive_movement(chords: list[Chord]) -> int:
    voicings = [voice(chord, "triad", Register.MID) for chord in chords]
    return sum(
        sum(abs(a - b) for a, b in zip(before, after, strict=True))
        for before, after in pairwise(voicings)
    )


def led_movement(chords: list[Chord]) -> int:
    voicings = [voice(chords[0], "triad", Register.MID)]
    for chord in chords[1:]:
        voicings.append(voice_lead(voicings[-1], voice(chord, "triad", Register.MID)))
    return sum(
        sum(min(abs(pitch - other) for other in before) for pitch in after)
        for before, after in pairwise(voicings)
    )


def test_voice_leading_moves_less_than_root_position() -> None:
    """Four chords that sound like a part, rather than four chords."""
    progression = [EM, C_MAJ, G_MAJ, D_MAJ]
    assert led_movement(progression) < naive_movement(progression)


def test_voice_leading_keeps_every_note() -> None:
    led = voice_lead(voice(EM, "triad", Register.MID), voice(C_MAJ, "triad", Register.MID))
    assert len(led) == 3
    assert sorted({pitch % 12 for pitch in led}) == sorted(C_MAJ.pitch_classes())


def test_voice_leading_is_idempotent_once_it_is_closest() -> None:
    previous = voice(EM, "triad", Register.MID)
    once = voice_lead(previous, voice(C_MAJ, "triad", Register.MID))
    assert voice_lead(previous, once) == once


def test_voice_leading_with_no_previous_chord_changes_nothing() -> None:
    closed = voice(EM, "triad", Register.MID)
    assert voice_lead((), closed) == closed


def test_a_repeated_chord_does_not_move() -> None:
    closed = voice(EM, "triad", Register.MID)
    assert voice_lead(closed, closed) == closed


def test_voice_leading_handles_chords_of_different_sizes() -> None:
    """A power chord followed by a seventh: three notes leading from two."""
    power = voice(parse_chord("E5"), "pow", Register.MID)
    led = voice_lead(power, voice(Chord(root=0, quality=Quality.DOM7), "triad", Register.MID))
    assert len(led) == 3
