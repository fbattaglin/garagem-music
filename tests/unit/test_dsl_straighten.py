"""Straightening: under a shuffle the swing is the system's, and only the system's.

`phase-4-findings.md` §16 found the model writing a shuffle into its notes — an attack every
three sixteenths — which `beats_of` then swings a second time. `straightened` moves every
attack between two eighths back onto the eighth before it (ADR-024). These tests pin the
rule, what it must never touch, and that lifting cannot put back what it took out.
"""

from __future__ import annotations

import json

import pytest

from garagem.domain import Feel, Instrument, Section, render_positions
from garagem.dsl import ParsedSection, parse_section, realise, serialize_section
from garagem.dsl.lines import BassLine, ChordLine, DrumLine
from garagem.dsl.realise import straightened
from garagem.engines import play_section
from garagem.llm import StreamDone, StreamEvent, ToolInputDelta, ToolUseStart
from garagem.theory import parse_chart, validate
from garagem.theory.percussion import CLOSED_HAT
from garagem.theory.validator import grid_slots, nearest_slot

# Pair 10 of the closing A/B, as the model wrote it: one of the two shuffle pairs the floor
# won on "cleaner, less messy" (`phase-4-findings.md` §15).
PAIR_10 = """SEC bridge bars=8 key=A feel=shuffle bpm=132 dyn=3 tension=0.55
CHD | F#m | D | A | E | F#m | D | A | E |
DRM K:1,7,9,13 S:5,13 H:1,4,7,10,13,16
BAS deg=1 oct=2 rhy:1,4,7,10,13
GTR voi=triad rhy:1,4,7,10,13,16 palm=on
KEY voi=sus4 rhy:1,13 reg=mid"""


def a_section(**extra: object) -> Section:
    base: dict[str, object] = {
        "name": "bridge",
        "bars": 8,
        "key": 9,
        "scale": "major",
        "feel": Feel.SHUFFLE,
        "bpm": 132.0,
        "dyn": 3,
        "tension": 0.55,
        "chart": parse_chart("| F#m | D | A | E | F#m | D | A | E |"),
    }
    return Section.model_validate(base | extra)


def parsed_from(dsl: str, section: Section) -> ParsedSection:
    events: list[StreamEvent] = [
        ToolUseStart(id="t", name="write_section"),
        ToolInputDelta(fragment=json.dumps({"dsl": dsl})),
        StreamDone(stop="tool_use"),
    ]
    return parse_section(events, section)


def drums_of(parsed: ParsedSection) -> DrumLine:
    line = parsed.lines[Instrument.DRUMS][0]
    assert isinstance(line, DrumLine)
    return line


def bass_of(parsed: ParsedSection) -> BassLine:
    line = parsed.lines[Instrument.BASS][0]
    assert isinstance(line, BassLine)
    return line


def guitar_of(parsed: ParsedSection) -> ChordLine:
    line = parsed.lines[Instrument.GUITAR][0]
    assert isinstance(line, ChordLine)
    return line


# ------------------------------------------------------------------------------ the rule


def test_the_models_three_sixteenth_hat_lands_on_the_eighths() -> None:
    """`1,4,7,10,13,16` — every "a" joins its "and", every "e" joins its beat."""
    straight = straightened(parsed_from(PAIR_10, a_section()))
    assert render_positions(drums_of(straight).hat) == "1,3,7,9,13,15"


def test_every_part_is_straightened_not_only_the_hat() -> None:
    straight = straightened(parsed_from(PAIR_10, a_section()))
    assert render_positions(bass_of(straight).rhythm) == "1,3,7,9,13"
    assert render_positions(guitar_of(straight).rhythm) == "1,3,7,9,13,15"


def test_an_attack_already_on_an_eighth_does_not_move() -> None:
    straight = straightened(parsed_from(PAIR_10, a_section()))
    assert render_positions(drums_of(straight).kick) == "1,7,9,13"
    assert render_positions(drums_of(straight).snare) == "5,13"


def test_the_last_sixteenth_stays_in_its_bar() -> None:
    """Moving *earlier* is what keeps an attack out of the next bar's downbeat."""
    dsl = PAIR_10.replace("H:1,4,7,10,13,16", "H:16")
    straight = straightened(parsed_from(dsl, a_section()))
    assert render_positions(drums_of(straight).hat) == "15"


def test_two_attacks_that_land_together_are_one() -> None:
    dsl = PAIR_10.replace("H:1,4,7,10,13,16", "H:1,2,3,4")
    straight = straightened(parsed_from(dsl, a_section()))
    assert render_positions(drums_of(straight).hat) == "1,3"


def test_a_ghost_beside_a_real_attack_is_not_a_ghost_anymore() -> None:
    dsl = PAIR_10.replace(
        "BAS deg=1 oct=2 rhy:1,4,7,10,13", "BAS deg=1 oct=2 rhy:1,2,5,6 ghost:2,5,6"
    )
    bass = bass_of(straightened(parsed_from(dsl, a_section())))
    assert render_positions(bass.rhythm) == "1,5"
    # 1 merged a real attack with a ghost: real. 5 merged two ghosts: still a ghost.
    assert bass.ghosts == (4,)


def test_an_accent_survives_the_merge() -> None:
    dsl = PAIR_10.replace("GTR voi=triad rhy:1,4,7,10,13,16 palm=on", "GTR voi=triad rhy:1,2 acc:2")
    guitar = guitar_of(straightened(parsed_from(dsl, a_section())))
    assert render_positions(guitar.rhythm) == "1"
    assert guitar.accents == (0,)


# -------------------------------------------------------------------- what it never touches


@pytest.mark.parametrize("feel", [Feel.STRAIGHT8, Feel.STRAIGHT16, Feel.HALFTIME])
def test_every_other_feel_comes_back_as_it_was(feel: Feel) -> None:
    dsl = PAIR_10.replace("feel=shuffle", f"feel={feel}")
    parsed = parsed_from(dsl, a_section(feel=feel))
    assert straightened(parsed) is parsed
    assert realise(parsed, 7, straighten=True) == realise(parsed, 7)


def test_straightening_twice_is_straightening_once() -> None:
    once = straightened(parsed_from(PAIR_10, a_section()))
    assert straightened(once) == once


def test_it_is_off_unless_asked_for() -> None:
    """Off by default until the five-minute check decides (ADR-024)."""
    parsed = parsed_from(PAIR_10, a_section())
    assert realise(parsed, 7) != realise(parsed, 7, straighten=True)
    assert realise(parsed, 7) == realise(parsed, 7, straighten=False)


@pytest.mark.parametrize("dyn", [1, 2, 3, 4])
@pytest.mark.parametrize("seed", [7, 2026])
def test_the_floors_shuffle_is_a_fixed_point_up_to_flat_out(dyn: int, seed: int) -> None:
    """Up to dyn 4 the floor strikes only eighths under a shuffle: nothing to straighten."""
    section = a_section(dyn=dyn)
    parsed = parsed_from(serialize_section(play_section(section, seed)), section)
    assert realise(parsed, seed, straighten=True) == realise(parsed, seed)


def test_flat_out_is_the_one_floor_shuffle_that_would_move_and_only_its_kick() -> None:
    """`engines/groove.py`'s "shuffle, flat out" kick is `1,4,7,9,12,15`: two kicks between
    the eighths, the figure §16 found in the model's hat. Found by the property above.

    Straightening never touches the floor — `play_section` does not pass through `realise` —
    so this pins what the floor *is*, recorded in `phase-5-findings.md` §2 and not acted on.
    """
    section = a_section(dyn=5)
    before = parsed_from(serialize_section(play_section(section, 7)), section)
    after = straightened(before)
    assert render_positions(drums_of(before).kick) == "1,4,7,9,12,15"
    assert render_positions(drums_of(after).kick) == "1,3,7,9,11,15"
    assert drums_of(after).model_copy(update={"kick": drums_of(before).kick}) == drums_of(before)
    for instrument in (Instrument.BASS, Instrument.GUITAR, Instrument.KEYS):
        assert after.lines[instrument] == before.lines[instrument]


# ------------------------------------------------------------------------ the realised music


def _off_the_eighths(section: Section, starts: list[float], bars: range) -> list[float]:
    """Attacks, in the bars given, whose nearest slot is not an eighth."""
    slots = grid_slots(section)
    eighths = set(slots[::2])
    off = []
    for start in starts:
        slot = nearest_slot(slots, start)
        if int(start // 4) in bars and slot not in eighths:
            off.append(start)
    return off


def test_what_plays_has_no_attack_between_the_eighths() -> None:
    """Before the last bar, which is the arrangement's fill and is composed after this."""
    section = a_section()
    score = realise(parsed_from(PAIR_10, section), 7, straighten=True)
    groove_bars = range(section.bars - 1)
    for part in score.parts:
        starts = [note.start_beats for note in part.notes]
        assert _off_the_eighths(section, starts, groove_bars) == [], part.instrument


def test_the_straightened_section_is_still_valid() -> None:
    score = realise(parsed_from(PAIR_10, a_section()), 7, straighten=True)
    assert validate(score) == ()


def test_lifting_cannot_put_an_attack_back_between_the_eighths() -> None:
    """Doubling fills the middle of each gap, and a two-slot gap's middle is off the eighths."""
    dsl = PAIR_10.replace("H:1,4,7,10,13,16", "H:1,5,7")
    section = a_section(dyn=5)
    groove_bars = range(section.bars - 1)

    def hats(straighten: bool) -> list[float]:
        score = realise(parsed_from(dsl, section), 7, straighten=straighten)
        drums = score.part(Instrument.DRUMS).notes
        return [note.start_beats for note in drums if note.pitch == CLOSED_HAT]

    # Unstraightened, the lift doubles `1,5,7` onto slots between the eighths...
    assert _off_the_eighths(section, hats(False), groove_bars) != []
    # ...and straightened it may still lift, but only onto the eighths.
    assert hats(True), "the hat must still play"
    assert _off_the_eighths(section, hats(True), groove_bars) == []
