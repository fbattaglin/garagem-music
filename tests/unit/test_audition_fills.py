"""The fill audition's passages and its blindness, with no Live (phase-4-findings §10)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from garagem.domain import BEATS_PER_BAR, SIXTEENTHS_PER_BAR, Instrument, Note
from garagem.theory.percussion import CRASH, HATS, TOMS

ROOT = Path(__file__).resolve().parents[2]


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


def test_there_are_six_options_and_every_one_is_distinct() -> None:
    assert len(audition.OPTIONS) == 6
    assert len({(o.style, o.crash) for o in audition.OPTIONS}) == 6


def test_the_order_is_a_shuffle_that_a_seed_repeats() -> None:
    assert sorted(audition.blind_order(3)) == list(range(6))
    assert audition.blind_order(3) == audition.blind_order(3)
    assert len({tuple(audition.blind_order(seed)) for seed in range(20)}) > 1


def test_a_passage_is_the_phrase_twice_then_a_bar_of_silence() -> None:
    notes = audition.passage(VERSE, audition.OPTIONS[0])
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


def test_the_fill_bar_is_what_differs_between_the_styles() -> None:
    bars = {
        option.style: tuple(
            (round(n.start_beats, 3), n.pitch)
            for n in in_bar(audition.passage(VERSE, option)[Instrument.DRUMS], audition.FILL_BAR)
        )
        for option in audition.OPTIONS
        if not option.crash
    }
    assert len(set(bars.values())) == 3
    toms = next(option for option in audition.OPTIONS if option.style == "toms")
    fill = in_bar(audition.passage(VERSE, toms)[Instrument.DRUMS], audition.FILL_BAR)
    assert {n.pitch for n in fill} & set(TOMS)
    assert not {n.pitch for n in fill} & HATS


def test_only_the_crash_options_land_on_a_crash_where_the_groove_returns() -> None:
    for option in audition.OPTIONS:
        returning = in_bar(audition.passage(VERSE, option)[Instrument.DRUMS], audition.RETURN_BAR)
        crashed = any(
            n.pitch == CRASH and n.start_beats < audition.RETURN_BAR * BEATS_PER_BAR + 0.05
            for n in returning
        )
        assert crashed is option.crash


def test_the_pitched_parts_are_the_same_in_every_passage() -> None:
    first = audition.passage(VERSE, audition.OPTIONS[0])
    for option in audition.OPTIONS[1:]:
        other = audition.passage(VERSE, option)
        for instrument in (Instrument.BASS, Instrument.GUITAR, Instrument.KEYS):
            assert other[instrument] == first[instrument]


def test_the_groove_bars_keep_their_sixteenths_on_the_grid() -> None:
    drums = audition.passage(VERSE, audition.OPTIONS[1])[Instrument.DRUMS]
    for note in drums:
        slot = note.start_beats * SIXTEENTHS_PER_BAR / BEATS_PER_BAR
        assert abs(slot - round(slot)) < 0.2
