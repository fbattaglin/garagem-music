"""The fill audition's passages and its blindness, with no Live (phase-4-findings §10)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest

from garagem.domain import BEATS_PER_BAR, SIXTEENTHS_PER_BAR, Instrument, Note
from garagem.theory.percussion import CRASH, HATS, SNARE, TOMS

ROOT = Path(__file__).resolve().parents[2]


class Option(Protocol):
    """What the script's own `Option` is, for the type checker.

    `audition_fills.py` is loaded by path — it is a script, not a package — so its dataclass
    cannot be imported here, and everything reached through the module is `Any`. This is the
    shape the tests rely on, written down so they are still checked.
    """

    name: str
    style: str
    crash: bool


def _load() -> ModuleType:
    path = ROOT / "scripts" / "audition_fills.py"
    spec = importlib.util.spec_from_file_location("audition_fills", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["audition_fills"] = module
    spec.loader.exec_module(module)
    return module


audition = _load()
VERSE = audition.the_verse()


def in_bar(notes: tuple[Note, ...], bar: int) -> list[Note]:
    start = bar * BEATS_PER_BAR
    return [n for n in notes if start - 0.05 <= n.start_beats < start + BEATS_PER_BAR - 0.05]


ROUNDS = audition.ROUNDS
EVERY_OPTION = [(name, option) for name, options in ROUNDS.items() for option in options]


@pytest.mark.parametrize("name", sorted(ROUNDS))
def test_every_option_in_a_round_is_a_different_thing(name: str) -> None:
    """Otherwise a passage is asking the ear to tell two identical sounds apart."""
    options = ROUNDS[name]
    assert len({(option.style, option.crash) for option in options}) == len(options)


def test_the_rounds_are_the_two_the_findings_describe() -> None:
    """Phase 4's six stay reachable so its ranking can be reproduced rather than only read;
    Phase 7's four are the fill it chose and the two things a cue may still change."""
    assert len(ROUNDS["phase4"]) == 6
    assert len(ROUNDS["phase7"]) == 4
    assert audition.DEFAULT_ROUND == "phase7"
    assert {option.style for option in ROUNDS["phase7"]} == {"toms", "toms_rising"}
    assert sorted(option.crash for option in ROUNDS["phase7"]) == [False, False, True, True]


@pytest.mark.parametrize("name", sorted(ROUNDS))
def test_the_order_is_a_shuffle_that_a_seed_repeats(name: str) -> None:
    count = len(ROUNDS[name])
    assert sorted(audition.blind_order(3, count)) == list(range(count))
    assert audition.blind_order(3, count) == audition.blind_order(3, count)
    assert len({tuple(audition.blind_order(seed, count)) for seed in range(20)}) > 1


@pytest.mark.parametrize(("name", "option"), EVERY_OPTION, ids=lambda value: str(value))
def test_a_passage_is_the_phrase_twice_then_a_bar_of_silence(name: str, option: Option) -> None:
    notes = audition.passage(VERSE, option)
    length = audition.PASSAGE_BARS * BEATS_PER_BAR
    for part in notes.values():
        assert all(note.start_beats + note.duration_beats <= length for note in part)
        assert in_bar(part, audition.PASSAGE_BARS - 1) == []
    drums = notes[Instrument.DRUMS]
    first = [(round(n.start_beats, 3), n.pitch) for n in in_bar(drums, 0)]
    second = [
        (round(n.start_beats - audition.PHRASE_BARS * BEATS_PER_BAR, 3), n.pitch)
        for n in in_bar(drums, audition.PHRASE_BARS)
    ]
    assert first == second


@pytest.mark.parametrize("name", sorted(ROUNDS))
def test_each_style_in_a_round_fills_the_bar_differently(name: str) -> None:
    without = [option for option in ROUNDS[name] if not option.crash]
    bars = {
        option.style: tuple(
            (round(n.start_beats, 3), n.pitch, n.velocity)
            for n in in_bar(audition.passage(VERSE, option)[Instrument.DRUMS], audition.FILL_BAR)
        )
        for option in without
    }
    assert len(set(bars.values())) == len({option.style for option in without})


def test_the_toms_run_is_toms_and_no_hats() -> None:
    toms = next(option for option in ROUNDS["phase7"] if option.style == "toms")
    fill = in_bar(audition.passage(VERSE, toms)[Instrument.DRUMS], audition.FILL_BAR)
    assert {n.pitch for n in fill} & set(TOMS)
    assert not {n.pitch for n in fill} & HATS


def test_rising_toms_change_only_how_hard_the_same_run_is_hit() -> None:
    """The whole claim of `TOMS_RISING`, and the only thing ADR-022 leaves a cue to change:
    the same slots and the same drums, entered at the groove's level instead of at full height.
    """

    def the_run(style: str) -> list[Note]:
        """The strokes the fill adds — not the groove's own kick and crash, which it keeps."""
        option = next(o for o in ROUNDS["phase7"] if o.style == style and not o.crash)
        bar = in_bar(audition.passage(VERSE, option)[Instrument.DRUMS], audition.FILL_BAR)
        return [note for note in bar if note.pitch in (SNARE, *TOMS)]

    flat, rising = the_run("toms"), the_run("toms_rising")
    assert [(round(n.start_beats, 3), n.pitch) for n in flat] == [
        (round(n.start_beats, 3), n.pitch) for n in rising
    ]
    assert [n.velocity for n in rising] != [n.velocity for n in flat]
    assert rising[0].velocity < flat[0].velocity, "it starts under the fill it is entering"
    assert rising[-1].velocity >= flat[-1].velocity, "and ends at or above it"


@pytest.mark.parametrize(("name", "option"), EVERY_OPTION, ids=lambda value: str(value))
def test_only_the_crash_options_land_on_a_crash_where_the_groove_returns(
    name: str, option: Option
) -> None:
    returning = in_bar(audition.passage(VERSE, option)[Instrument.DRUMS], audition.RETURN_BAR)
    crashed = any(
        n.pitch == CRASH and n.start_beats < audition.RETURN_BAR * BEATS_PER_BAR + 0.05
        for n in returning
    )
    assert crashed is option.crash


@pytest.mark.parametrize("name", sorted(ROUNDS))
def test_the_pitched_parts_are_the_same_in_every_passage(name: str) -> None:
    options = ROUNDS[name]
    first = audition.passage(VERSE, options[0])
    for option in options[1:]:
        other = audition.passage(VERSE, option)
        for instrument in (Instrument.BASS, Instrument.GUITAR, Instrument.KEYS):
            assert other[instrument] == first[instrument]


@pytest.mark.parametrize(("name", "option"), EVERY_OPTION, ids=lambda value: str(value))
def test_the_groove_bars_keep_their_sixteenths_on_the_grid(name: str, option: Option) -> None:
    for note in audition.passage(VERSE, option)[Instrument.DRUMS]:
        slot = note.start_beats * SIXTEENTHS_PER_BAR / BEATS_PER_BAR
        assert abs(slot - round(slot)) < 0.2
