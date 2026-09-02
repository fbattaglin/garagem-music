"""Invariant 7, made visible: the same seed produces the same bytes, or the diff says so.

Four fixed briefings, two seeds each, serialised twice — once as the DSL a model would
read, once as every note exactly — and compared against files in `data/`. If a refactor
changes one velocity, this fails and the diff names the note.

**Regenerating is a deliberate act with a diff to read.**

    GARAGEM_UPDATE_GOLDEN=1 uv run pytest tests/golden/ -q

That command rewrites the files and passes. It is the right thing to run when the music
was meant to change, and the wrong thing to run to make a red test green: the whole value
of a golden file is that nobody can move it by accident. Read `git diff` afterwards and
say in the commit message what changed musically and why.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from garagem.domain import Feel, Section
from garagem.dsl import serialize_score, serialize_section
from garagem.engines import play_section
from garagem.theory import parse_chart

DATA = Path(__file__).parent / "data"
UPDATE = os.environ.get("GARAGEM_UPDATE_GOLDEN") == "1"

# Four briefings chosen to cover the corners the engines branch on: a quiet shuffle, the
# Phase 1 progression, a loud sixteenth chorus, and a halftime bridge in a major key.
BRIEFINGS: dict[str, Section] = {
    "verse-shuffle": Section(
        name="verse",
        bars=4,
        key=9,
        scale="minor",
        feel=Feel.SHUFFLE,
        bpm=96.0,
        dyn=2,
        tension=0.2,
        chart=parse_chart("| Am | Am | Dm | E7 |"),
    ),
    "verse-straight8": Section(
        name="verse",
        bars=4,
        key=4,
        scale="minor",
        feel=Feel.STRAIGHT8,
        bpm=132.0,
        dyn=3,
        tension=0.4,
        chart=parse_chart("| Em | C | G | D |"),
    ),
    "chorus-straight16": Section(
        name="chorus",
        bars=4,
        key=4,
        scale="minor",
        feel=Feel.STRAIGHT16,
        bpm=132.0,
        dyn=5,
        tension=0.8,
        chart=parse_chart("| C | D | Em | Em |"),
    ),
    "bridge-halftime": Section(
        name="bridge",
        bars=4,
        key=0,
        scale="major",
        feel=Feel.HALFTIME,
        bpm=110.0,
        dyn=3,
        tension=0.55,
        chart=parse_chart("| Am | F | C | G |"),
    ),
}

SEEDS = (7, 1729)

CASES = [(name, seed) for name in BRIEFINGS for seed in SEEDS]


def rendered(name: str, seed: int) -> str:
    """Both forms in one file, so a single diff shows the notation and the notes."""
    score = play_section(BRIEFINGS[name], seed)
    return f"{serialize_section(score)}\n{serialize_score(score)}"


@pytest.mark.parametrize(("name", "seed"), CASES, ids=lambda value: str(value))
def test_the_section_matches_its_golden_file(name: str, seed: int) -> None:
    path = DATA / f"{name}-{seed}.dsl"
    produced = rendered(name, seed)
    if UPDATE:
        path.write_text(produced, encoding="utf-8")
    assert path.exists(), f"missing golden file {path.name}; regenerate deliberately"
    assert produced == path.read_text(encoding="utf-8")


def test_every_golden_file_belongs_to_a_case() -> None:
    """An orphan file is a briefing somebody deleted and a test that stopped running."""
    expected = {f"{name}-{seed}.dsl" for name, seed in CASES}
    assert {path.name for path in DATA.glob("*.dsl")} == expected


def test_two_seeds_of_one_briefing_are_not_the_same_music() -> None:
    """Otherwise the files would agree for a reason that has nothing to do with the seed."""
    for name in BRIEFINGS:
        assert rendered(name, SEEDS[0]) != rendered(name, SEEDS[1])
