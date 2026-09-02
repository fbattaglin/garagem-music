"""One line of DSL at a time, and every way a model can get one wrong.

Two of these tests are the phase's exit criteria in miniature. The 21-character guitar
grid is not invented — Gemini 3.6 Flash wrote exactly that into
`cassettes/google_section_flash.jsonl`, and it is pinned here so a parser that ever
started accepting it fails in the offline suite rather than in the music.

And `check_sec` is where "the model does not redefine the section" is enforced. The
scheduler has already sized the clip from our numbers; a `SEC` line that disagrees is a
violation to count, not an instruction to follow.
"""

from __future__ import annotations

import re

import pytest

from garagem.domain import Feel, Instrument, Section, render_grid
from garagem.dsl import brief
from garagem.dsl.errors import LineError
from garagem.dsl.lines import (
    ALIASES,
    SEC_FIELDS,
    VOICINGS,
    BassLine,
    ChordLine,
    DrumLine,
    check_chd,
    check_sec,
    parse_bar_line,
    parse_chd,
    parse_sec,
    tag_of,
)
from garagem.theory import parse_chart

SEC_LINE = "SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4"
CHD_LINE = "CHD | Em | Em | C  | D  | Em | Em | C  | B7 |"


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "verse",
        "bars": 8,
        "key": 4,
        "scale": "minor",
        "feel": Feel.STRAIGHT8,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.4,
        "chart": parse_chart("| Em | Em | C | D | Em | Em | C | B7 |"),
    }
    return Section.model_validate(base | extra)


# ------------------------------------------------------------------------------- the tag


def test_the_tag_is_the_first_word() -> None:
    assert tag_of(SEC_LINE) == "SEC"
    assert tag_of("  DRM K:x...............  ") == "DRM"


def test_a_blank_line_has_no_tag_and_is_not_an_error() -> None:
    assert tag_of("   ") == ""


# ------------------------------------------------------------------------------- the SEC


def test_the_skills_own_sec_example_parses() -> None:
    fields = parse_sec(SEC_LINE)
    assert fields["name"] == "verse"
    assert fields["bars"] == "8"
    assert fields["key"] == "Em"
    assert fields["tension"] == "0.4"


def test_a_missing_field_is_named() -> None:
    with pytest.raises(LineError, match="missing tension"):
        parse_sec("SEC verse bars=8 key=Em feel=straight8 bpm=132 dyn=3")


def test_an_unknown_field_is_named() -> None:
    with pytest.raises(LineError, match="swing"):
        parse_sec(f"{SEC_LINE} swing=0.6")


def test_a_field_that_is_not_a_pair_is_refused() -> None:
    with pytest.raises(LineError, match="key=value"):
        parse_sec("SEC verse bars 8 key=Em feel=straight8 bpm=132 dyn=3 tension=0.4")


def test_a_sec_with_no_name_is_refused() -> None:
    with pytest.raises(LineError, match="no section name"):
        parse_sec("SEC")


def test_an_echo_that_matches_the_briefing_is_clean() -> None:
    assert check_sec(parse_sec(SEC_LINE), a_section()) == ()


def test_a_bars_that_disagrees_is_a_violation_and_the_briefing_wins() -> None:
    line = SEC_LINE.replace("bars=8", "bars=16")
    violations = check_sec(parse_sec(line), a_section())
    assert [v.rule for v in violations] == ["section_mismatch"]
    assert "bars" in violations[0].detail


def test_the_key_must_match_the_mode_we_asked_for() -> None:
    fields = parse_sec(SEC_LINE)
    assert check_sec(fields, a_section()) == ()
    assert check_sec(fields, a_section(scale="major")) != ()


def test_every_field_the_brief_states_is_a_field_check_sec_checks() -> None:
    """A field we state and never check is a constraint nobody enforces."""
    text = brief(a_section())
    for field in SEC_FIELDS:
        assert f"{field}=" in text


def test_a_disagreement_in_every_field_is_reported_at_once() -> None:
    """The repairer and the log want them all, not the first."""
    line = "SEC chorus bars=4 key=C feel=shuffle bpm=90 dyn=5 tension=0.9"
    assert len(check_sec(parse_sec(line), a_section())) == len(SEC_FIELDS) + 1


# ------------------------------------------------------------------------------- the CHD


def test_the_chd_line_parses_through_theory() -> None:
    chart = parse_chd(CHD_LINE)
    assert len(chart.chords) == 8
    assert check_chd(chart, a_section()) == ()


def test_a_chart_that_is_not_the_one_we_asked_for_is_a_mismatch() -> None:
    chart = parse_chd("CHD | Am | F |")
    violations = check_chd(chart, a_section())
    assert [v.rule for v in violations] == ["section_mismatch"]


def test_a_chord_the_vocabulary_lacks_names_the_symbol() -> None:
    with pytest.raises(LineError, match="Cm9"):
        parse_chd("CHD | Cm9 |")


def test_a_chd_with_no_chords_is_refused() -> None:
    with pytest.raises(LineError, match="no chords"):
        parse_chd("CHD")


# ------------------------------------------------------------------------- the bar lines


def test_the_skills_drum_line_parses() -> None:
    line = parse_bar_line("DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x.")
    assert isinstance(line, DrumLine)
    assert render_grid(line.kick) == "x..x..x...x..x.."
    assert line.crash == ()  # a missing voice is silence, not an error


def test_the_skills_bass_line_parses() -> None:
    line = parse_bar_line("BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x. ghost=7,15")
    assert isinstance(line, BassLine)
    assert (line.degree, line.octave) == (1, 2)
    assert line.ghosts == (6, 14)  # 1-indexed on the wire, 0-indexed inside


def test_the_skills_guitar_line_parses() -> None:
    line = parse_bar_line("GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on acc=1,9")
    assert isinstance(line, ChordLine)
    assert line.instrument is Instrument.GUITAR
    assert line.voicing == "pow"
    assert line.palm_muted
    assert line.accents == (0, 8)


def test_the_skills_keys_line_parses() -> None:
    line = parse_bar_line("KEY voi=sus2 rhy:x.......x....... reg=mid")
    assert isinstance(line, ChordLine)
    assert line.instrument is Instrument.KEYS
    assert line.reg == "mid"


def test_the_twenty_one_character_grid_a_real_model_wrote_is_refused() -> None:
    """`cassettes/google_section_flash.jsonl`, verbatim. Pinned as a regression."""
    with pytest.raises(LineError, match="21"):
        parse_bar_line("GTR voi=pow rhy:xx.xx.xx.xx.xx.xx.xx. palm=on")


def test_a_stray_character_in_a_grid_is_refused() -> None:
    with pytest.raises(LineError, match=r"\['o'\]"):
        parse_bar_line("DRM K:x..o............")


def test_an_unknown_voicing_names_the_ones_that_exist() -> None:
    with pytest.raises(LineError, match="quartal"):
        parse_bar_line("GTR voi=quartal rhy:x...............")


def test_an_unknown_register_is_refused() -> None:
    with pytest.raises(LineError, match="stratosphere"):
        parse_bar_line("KEY voi=sus2 rhy:x............... reg=stratosphere")


def test_palm_is_on_or_off() -> None:
    with pytest.raises(LineError, match="palm is on or off"):
        parse_bar_line("GTR voi=pow rhy:x............... palm=maybe")


def test_a_missing_rhythm_is_refused() -> None:
    with pytest.raises(LineError, match="missing rhy"):
        parse_bar_line("BAS deg=1 oct=2")


def test_a_degree_outside_one_to_seven_is_refused() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        parse_bar_line("BAS deg=9 oct=2 rhy:x...............")


def test_a_degree_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(LineError, match="not a whole number"):
        parse_bar_line("BAS deg=one oct=2 rhy:x...............")


def test_a_position_outside_the_bar_is_refused() -> None:
    with pytest.raises(LineError, match=re.escape("outside 1..16")):
        parse_bar_line("BAS deg=1 oct=2 rhy:x............... ghost=99")


def test_an_unknown_drum_voice_is_refused() -> None:
    with pytest.raises(LineError, match="'T'"):
        parse_bar_line("DRM T:x...............")


def test_a_tag_that_is_not_in_the_dsl_is_refused() -> None:
    with pytest.raises(LineError, match="'LEAD'"):
        parse_bar_line("LEAD voi=pow rhy:x...............")


@pytest.mark.parametrize(
    "line",
    [
        "DRM K:x..x..x...x..x.. S:....x.......x... H:x.x.x.x.x.x.x.x.",
        "BAS deg=1 oct=2 rhy:x.x.x.x.x.x.x.x.",
        "GTR voi=pow rhy:xx.xxx.xxx.xx.x. palm=on",
        "KEY voi=sus2 rhy:x.......x....... reg=mid",
    ],
)
def test_every_line_in_the_system_prompt_parses(line: str) -> None:
    """The prompt's examples are the specification the model actually reads."""
    assert parse_bar_line(line) is not None


# --------------------------------------------------------------- aliases, and their limit


def test_power_is_accepted_as_the_word_for_pow() -> None:
    """8 times in 90 sections, and only ever in a chorus: the model names the idea."""
    line = parse_bar_line("GTR voi=power rhy:x...............")
    assert isinstance(line, ChordLine)
    assert line.voicing == "pow"


def test_an_alias_and_its_target_realise_identically() -> None:
    """The alias must be a spelling, not a seventh voicing with its own behaviour."""
    assert parse_bar_line("GTR voi=power rhy:x.......x.......") == parse_bar_line(
        "GTR voi=pow rhy:x.......x......."
    )


def test_the_alias_table_is_closed() -> None:
    """No fuzzy matching, no prefixes, no edit distance. A dict, and only a dict."""
    assert ALIASES == {"power": "pow"}
    with pytest.raises(LineError, match="not a voicing"):
        parse_bar_line("GTR voi=powerful rhy:x...............")
    with pytest.raises(LineError, match="not a voicing"):
        parse_bar_line("GTR voi=pw rhy:x...............")


def test_every_alias_points_at_a_real_voicing() -> None:
    """A typo here would create a voicing the realiser has no branch for."""
    assert set(ALIASES.values()) <= VOICINGS
    assert not set(ALIASES) & VOICINGS  # an alias never shadows a real name


def test_an_ambiguous_grid_is_still_refused() -> None:
    """The line this alias must not be read as crossing.

    A short grid cannot be repaired the way a known spelling can: which slot went missing
    is unrecoverable, and padding it would put a note where nobody wrote one. Widening a
    closed vocabulary by one spelling and inventing a note are different acts.
    """
    with pytest.raises(LineError, match="16 characters"):
        parse_bar_line("GTR voi=power rhy:x..............")


# ------------------------------------------------ a bar in slots instead of in characters


def test_a_bar_written_as_slots_is_the_same_bar() -> None:
    """`K:1,4,7,11,14` and `K:x..x..x...x..x..` name one thing, not two."""
    assert parse_bar_line("DRM K:1,4,7,11,14 S:5,13") == parse_bar_line(
        "DRM K:x..x..x...x..x.. S:....x.......x..."
    )


def test_slots_work_on_a_rhythm_field_too() -> None:
    assert parse_bar_line("GTR voi=pow rhy:1,3,5,7 palm=on") == parse_bar_line(
        "GTR voi=pow rhy:x.x.x.x......... palm=on"
    )


def test_slots_are_one_indexed_like_ghost_and_acc_already_are() -> None:
    """Two position conventions in one DSL would be a trap. Slot 1 is the downbeat."""
    line = parse_bar_line("BAS deg=1 oct=2 rhy:1 ghost=1")
    assert isinstance(line, BassLine)
    assert line.rhythm[0] is True
    assert line.ghosts == (0,)


def test_slots_run_together_with_the_next_field_still_split() -> None:
    """The lookahead guards the greedy digit run exactly as it guards the grid."""
    run = parse_bar_line("GTR voi=pow rhy:1,3,5,7palm=on")
    assert run == parse_bar_line("GTR voi=pow rhy:1,3,5,7 palm=on")
    assert isinstance(run, ChordLine)
    assert run.palm_muted


def test_a_slot_outside_the_bar_is_refused_by_number() -> None:
    """The whole point: out of range is *detectable*, where a short grid silently shifts."""
    with pytest.raises(LineError, match=r"outside 1\.\.16"):
        parse_bar_line("DRM K:1,4,99")


def test_slots_out_of_order_or_repeated_are_normalised() -> None:
    """Neither is ambiguous, and refusing them would be strictness with no defect behind it."""
    assert parse_bar_line("DRM K:7,1,1,4") == parse_bar_line("DRM K:1,4,7")


def test_an_empty_voice_is_refused_rather_than_read_as_silence() -> None:
    """`K:` is as likely a dropped field as an intended rest. Leave the voice out."""
    with pytest.raises(LineError):
        parse_bar_line("DRM K: S:5")


def test_the_grid_form_keeps_every_one_of_its_error_messages() -> None:
    """Dispatching on `x`/`.` first is what preserves these. The regression that mattered:
    a real model's 21-character guitar grid must still fail as a *length*, not as a
    malformed slot list."""
    with pytest.raises(LineError, match=r"16 characters, got 21"):
        parse_bar_line("GTR voi=pow rhy:xx.xx.xx.xx.xx.xx.xx. palm=on")
    with pytest.raises(LineError, match=r"16 characters, got 15"):
        parse_bar_line("DRM K:x..............")


def test_the_two_forms_cannot_be_confused() -> None:
    """A grid is x and dots; a slot list is digits and commas. Disjoint alphabets."""
    with pytest.raises(LineError, match="not a position"):
        parse_bar_line("DRM K:1,4,seven")
