"""The one-cent probe's briefing and its report, with no network (ADR-027 Stage D).

The probe exists to make a notation decision cheap, so what is worth pinning is that it asks
the right question and reads the answer correctly. A probe that mis-reports is worse than no
probe: it would send us building a scale-relative spelling nobody needed, or skipping one we
did.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

from garagem.domain import PITCH_CLASSES, SIXTEENTHS_PER_BAR, Instrument
from garagem.dsl import parse_text, realise, serialize_section
from garagem.engines import SHAPES, play_section
from garagem.engines.arranger import SOLO
from garagem.theory import chart_pitch_classes, pitch_classes, validate

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "probe_solo.py"
    spec = importlib.util.spec_from_file_location("probe_solo", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["probe_solo"] = module
    spec.loader.exec_module(module)
    return module


probe = _load()
SONG = json.loads((ROOT / "setlists" / "songwriter.json").read_text(encoding="utf-8"))["songs"][0]
BPM = 132.0


def test_the_briefing_is_a_solo_section_as_the_arranger_writes_one() -> None:
    """Not a hand-made section: the probe has to ask the question the bake will ask."""
    section = probe.the_briefing(SONG, BPM)
    assert section.name == SOLO
    assert section.bars == SHAPES[SOLO].bars
    assert section.dyn == SHAPES[SOLO].dyn
    assert section.tension == SHAPES[SOLO].tension
    assert section.key == SONG["key"] and section.scale == SONG["scale"]


def test_the_briefing_gives_the_solo_something_to_play_over() -> None:
    """A solo over one chord would answer a different question than the one being asked."""
    chords = probe.the_briefing(SONG, BPM).chart.chords
    assert len(chords) == 4
    assert len({(chord.root, chord.quality) for chord in chords}) >= 3


def test_the_report_reads_bars_off_the_grid_and_not_off_the_beat() -> None:
    """The bug this function had: the solo's landing note is humanised a few milliseconds
    before its downbeat, and dividing the beat by four put it in the bar before — which made
    the floor look as though it rested in the very bar it lands in."""
    section = probe.the_briefing(SONG, BPM)
    floor = play_section(section, SONG["seed"])
    bars = probe.realised_bars(floor)
    assert len(bars) == section.bars
    assert bars[-1], "the landing note belongs to the last bar"
    assert bars[-1][0][0] == 0, "and it is on its downbeat"
    assert all(bar for bar in bars), "a solo plays in every bar"


def test_every_reported_slot_is_inside_its_bar() -> None:
    section = probe.the_briefing(SONG, BPM)
    floor = play_section(section, SONG["seed"])
    for bar in probe.realised_bars(floor):
        assert all(0 <= slot < SIXTEENTHS_PER_BAR for slot, _ in bar)


def test_the_notation_cannot_write_the_floor_s_own_solo_faithfully() -> None:
    """**Stage D's question, answered for nothing** (ADR-027, `phase-7-findings.md` §4).

    `LED … deg:` counts degrees of each bar's chord's implied scale. A hook lives inside a bar
    and never notices. A solo moves through the *key*, and over a chord whose scale disagrees
    with the key there is simply no degree for the note it wants — over `C` in E minor, no
    degree spells F#, because C's scale has F. The serializer writes the nearest degree it can
    and the note changes.

    Pinned as a measurement rather than as a threshold: the number is what it is, and it moving
    would mean either the notation or the floor's solo changed.
    """
    section = probe.the_briefing(SONG, BPM)
    floor = play_section(section, SONG["seed"])
    moved = probe.notation_loss(floor, SONG["seed"])
    total = sum(len(bar) for bar in probe.realised_bars(floor))

    assert moved, "if this is ever empty the notation stopped needing rel=key"
    assert len(moved) == 5 and total == 43
    assert all(abs(was - became) == 1 for _, _, was, became in moved)


def test_the_loss_is_silent_because_tension_pays_for_it() -> None:
    """The dangerous half. Four of the five notes land **outside the key**, and the section
    still validates: the dissonance budget at a solo's tension buys far more than 4 of 43, so
    nothing refuses it and nothing repairs it. A notation that loses notes loudly would be a
    smaller problem than one that loses them quietly."""
    section = probe.the_briefing(SONG, BPM)
    floor = play_section(section, SONG["seed"])
    again = realise(parse_text(serialize_section(floor, pitched=True), section), SONG["seed"])
    allowed = pitch_classes(section.key, section.scale) | chart_pitch_classes(section.chart)

    outside = [
        note
        for note in again.part(Instrument.LEAD).notes
        if note.pitch % PITCH_CLASSES not in allowed
    ]
    assert len(outside) == 4
    assert validate(again) == (), "and the validator lets it through"
    assert validate(floor) == (), "while the floor it came from was in the key throughout"


def test_the_cap_covers_what_the_governor_reserves() -> None:
    """A cap sized to the expected cost refuses the call it was sized for: the governor
    reserves every request at the model's `max_tokens` before it is sent."""
    from garagem.agents import BAKE_MAX_TOKENS, structural
    from garagem.llm import Usage, load_catalog

    model = structural(load_catalog(ROOT / "config" / "models.toml"))
    reserved = model.price.cost_of(Usage(input_tokens=1400, output_tokens=BAKE_MAX_TOKENS))
    assert reserved < probe.CAP_USD, "the cap has to cover what the governor reserves"
    expected = model.price.cost_of(probe.ONE_SECTION)
    assert expected < Decimal("0.02"), "a probe is about a cent, or it is not a probe"
