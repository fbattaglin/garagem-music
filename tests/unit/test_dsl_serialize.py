"""Domain to DSL text, and domain to the exact form a golden file needs.

The test that matters most is the one about silence: a part that plays nothing still
gets its line. In a Phase 3 stream a missing line means "not generated yet" and a line of
rests means "chose not to play", and a serializer that dropped empty parts would make
those two indistinguishable.
"""

from __future__ import annotations

import pytest

from garagem.domain import (
    Feel,
    Instrument,
    Note,
    Part,
    Section,
    SectionScore,
)
from garagem.dsl import serialize_score, serialize_section
from garagem.engines import play_section
from garagem.theory import parse_chart

PROGRESSION = parse_chart("| Em | C | G | D |")


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 4,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": PROGRESSION,
    }
    return Section.model_validate(base | extra)


def lines_of(text: str) -> list[str]:
    return text.strip().splitlines()


def tags_of(text: str) -> list[str]:
    return [line.split()[0] for line in lines_of(text)]


# ------------------------------------------------------------------------------ the header


def test_the_sec_line_matches_the_skill_field_for_field() -> None:
    """`SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4`."""
    text = serialize_section(play_section(a_section(bars=8), 7))
    assert lines_of(text)[0] == ("SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4")


def test_a_major_key_has_no_trailing_m() -> None:
    text = serialize_section(play_section(a_section(key=0, scale="major"), 7))
    assert "key=C " in lines_of(text)[0]


def test_the_chd_line_renders_with_pipes() -> None:
    text = serialize_section(play_section(a_section(), 7))
    assert lines_of(text)[1] == "CHD | Em | C | G | D |"


# -------------------------------------------------------------------------------- the body


def test_the_lines_come_in_the_mandated_order() -> None:
    """SEC, CHD, DRM, BAS, GTR, KEY. Never reordered — the parser depends on it."""
    tags = tags_of(serialize_section(play_section(a_section(bars=2), 7)))
    assert tags == ["SEC", "CHD", "DRM", "DRM", "BAS", "BAS", "GTR", "GTR", "KEY", "KEY"]


def test_there_is_one_line_per_bar_per_instrument() -> None:
    text = serialize_section(play_section(a_section(bars=8), 7))
    assert tags_of(text).count("DRM") == 8
    assert tags_of(text).count("KEY") == 8


def test_a_drum_line_carries_all_four_voices() -> None:
    line = next(
        line
        for line in lines_of(serialize_section(play_section(a_section(), 7)))
        if line.startswith("DRM")
    )
    for tag in ("K:", "S:", "H:", "C:"):
        assert tag in line
    assert all(len(part.split(":")[1]) == 16 for part in line.split()[1:])


def test_a_bass_line_names_the_degree_and_the_octave() -> None:
    line = next(
        line
        for line in lines_of(serialize_section(play_section(a_section(), 7)))
        if line.startswith("BAS")
    )
    assert "deg=1" in line
    assert "oct=2" in line
    assert "rhy:" in line


def test_a_guitar_line_names_the_voicing_and_the_mute() -> None:
    line = next(
        line
        for line in lines_of(serialize_section(play_section(a_section(dyn=1), 7)))
        if line.startswith("GTR")
    )
    assert "voi=pow" in line
    assert "palm=on" in line


def test_an_inverted_power_chord_is_still_a_power_chord() -> None:
    """Voice leading moves the hand; it does not change what the chord is called."""
    text = serialize_section(play_section(a_section(bars=4, dyn=1), 7))
    voicings = {line.split()[1] for line in lines_of(text) if line.startswith("GTR")}
    assert voicings == {"voi=pow"}


def test_a_keys_line_names_the_register() -> None:
    line = next(
        line
        for line in lines_of(serialize_section(play_section(a_section(), 7)))
        if line.startswith("KEY")
    )
    assert "reg=" in line


# ------------------------------------------------------------------------------- silence


def test_a_part_that_plays_nothing_still_gets_its_line() -> None:
    """A missing line means "not generated yet"; rests mean "chose not to play"."""
    score = SectionScore(
        section=a_section(bars=1),
        parts=(
            Part(
                instrument=Instrument.DRUMS,
                notes=(Note(pitch=36, start_beats=0.0, duration_beats=0.2),),
            ),
        ),
        seed=7,
    )
    tags = tags_of(serialize_section(score))
    assert tags == ["SEC", "CHD", "DRM", "BAS", "GTR", "KEY"]
    assert "rhy:................" in serialize_section(score)


# ------------------------------------------------------------------------------- stability


def test_the_same_seed_serialises_to_the_same_bytes() -> None:
    assert serialize_section(play_section(a_section(), 7)) == serialize_section(
        play_section(a_section(), 7)
    )


def test_the_text_ends_with_a_newline() -> None:
    assert serialize_section(play_section(a_section(), 7)).endswith("\n")


@pytest.mark.parametrize("feel", list(Feel))
def test_every_feel_serialises(feel: Feel) -> None:
    text = serialize_section(play_section(a_section(feel=feel), 7))
    assert f"feel={feel}" in text


# ----------------------------------------------------------------------------- exact form


def test_the_exact_form_names_the_seed_and_the_scale() -> None:
    """The DSL's `key=Em` loses the mode; the golden form must not."""
    header = lines_of(serialize_score(play_section(a_section(scale="dorian"), 7)))[0]
    assert header == "# seed=7 scale=dorian"


def test_the_exact_form_has_a_line_for_every_note() -> None:
    score = play_section(a_section(), 7)
    body = [line for line in lines_of(serialize_score(score)) if line.startswith("  ")]
    assert len(body) == sum(len(part.notes) for part in score.parts)


def test_the_exact_form_sees_a_velocity_change() -> None:
    """What `serialize_section` cannot see, and why the golden files use this one."""
    score = play_section(a_section(bars=1), 7)
    part = score.parts[0]
    louder = part.model_copy(
        update={"notes": (part.notes[0].model_copy(update={"velocity": 7}), *part.notes[1:])}
    )
    nudged = score.model_copy(update={"parts": (louder, *score.parts[1:])})
    assert serialize_section(nudged) == serialize_section(score)
    assert serialize_score(nudged) != serialize_score(score)
