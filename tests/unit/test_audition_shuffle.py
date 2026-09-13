"""The shuffle check's material, choice and veto, with no Live (`phase-5-findings.md` §2).

The choice and the order are the pre-registration, so they are pinned here: if the
recordings or the rule move, this fails before anyone listens to a different five.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

from garagem.daw import FakeDawAdapter, load_session
from garagem.domain import Feel
from garagem.theory import validate
from garagem.theory.validator import grid_slots, nearest_slot

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "audition_shuffle.py"
    spec = importlib.util.spec_from_file_location("audition_shuffle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["audition_shuffle"] = module
    spec.loader.exec_module(module)
    return module


audition = _load()
POOL = audition.takes()
CHOSEN = audition.choose(POOL)


# ----------------------------------------------------------------------------- material


def test_every_recorded_model_shuffle_is_in_the_pool() -> None:
    by_source = {source: 0 for source in ("ab", "regression", "phase3")}
    for take in POOL:
        by_source[take.source] += 1
    assert by_source == {"ab": 3, "regression": 8, "phase3": 8}
    assert all(take.section.feel is Feel.SHUFFLE for take in POOL)
    assert all("feel=shuffle" in take.dsl for take in POOL)


def test_a_take_straightening_would_not_change_is_counted_as_zero() -> None:
    """§16: 18 of 19 had the three-sixteenth run. The nineteenth has nothing to move."""
    assert sum(1 for take in POOL if sum(audition.moved(take).values()) == 0) == 1


# --------------------------------------------------------------------------- the choice


def test_the_five_are_pinned() -> None:
    assert [take.name for take in CHOSEN] == [
        "regression:25-chorus-shuffle-96",
        "regression:07-chorus-shuffle-110",
        "phase3:10-bridge-shuffle-150",
        "phase3:24-bridge-shuffle-132",
        "regression:08-verse-shuffle-132",
    ]


def test_nothing_already_heard_is_chosen() -> None:
    assert all(take.source not in audition.HEARD for take in CHOSEN)


def test_the_choice_keeps_its_limits() -> None:
    assert len({take.briefing_id for take in CHOSEN}) == audition.PAIRS
    tempos = Counter(take.section.bpm for take in CHOSEN)
    kinds = Counter(take.section.name for take in CHOSEN)
    assert max(tempos.values()) <= audition.MAX_PER_TEMPO
    assert max(kinds.values()) <= audition.MAX_PER_KIND


def test_the_order_is_fixed_and_straightened_leads_three_times() -> None:
    """Fixed by a seed, and deliberately not written out here: the listener may read diffs."""
    sides = audition.first_sides()
    assert sides.count(audition.STRAIGHTENED) == audition.STRAIGHT_FIRST == 3
    assert sides == audition.first_sides()
    assert len({tuple(audition.first_sides(seed=seed)) for seed in range(20)}) > 1


# ------------------------------------------------------------------------------ the sides


@pytest.mark.parametrize("take", CHOSEN, ids=[take.name for take in CHOSEN])
def test_the_two_sides_differ_and_both_play(take: object) -> None:
    sides = audition.sides_of(take)
    assert sides[audition.AS_WRITTEN] != sides[audition.STRAIGHTENED]
    for score in sides.values():
        assert validate(score) == ()
        assert len(score.parts) == 4


@pytest.mark.parametrize("take", CHOSEN, ids=[take.name for take in CHOSEN])
def test_the_straightened_side_has_nothing_between_the_eighths(take: object) -> None:
    score = audition.sides_of(take)[audition.STRAIGHTENED]
    section = score.section
    slots = grid_slots(section)
    eighths = set(slots[::2])
    last_bar = (section.bars - 1) * 4
    for part in score.parts:
        for note in part.notes:
            if note.start_beats < last_bar:
                assert nearest_slot(slots, note.start_beats) in eighths, part.instrument


# ------------------------------------------------------------------------------- the veto


def _votes(tmp_path: Path, winners: list[str]) -> Path:
    log = tmp_path / "votes.jsonl"
    for index, winner in enumerate(winners):
        first = audition.STRAIGHTENED
        vote = "skip" if winner == "skip" else ("A" if winner == first else "B")
        audition.record(log, index, CHOSEN[index], first, vote, "")
    return log


def test_four_for_the_take_as_written_stops_the_fix(tmp_path: Path) -> None:
    written = audition.AS_WRITTEN
    log = _votes(tmp_path, [written, written, written, written, audition.STRAIGHTENED])
    assert "NOT APPLIED" in audition.tally(log)


def test_three_for_the_take_as_written_does_not(tmp_path: Path) -> None:
    written, straight = audition.AS_WRITTEN, audition.STRAIGHTENED
    log = _votes(tmp_path, [written, written, written, straight, straight])
    assert "result: APPLIED" in audition.tally(log)


def test_a_skipped_pair_counts_for_neither_side(tmp_path: Path) -> None:
    written = audition.AS_WRITTEN
    log = _votes(tmp_path, [written, written, written, "skip", audition.STRAIGHTENED])
    assert "result: APPLIED" in audition.tally(log)


def test_the_log_keeps_the_material_beside_the_vote(tmp_path: Path) -> None:
    log = _votes(tmp_path, [audition.AS_WRITTEN])
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["dsl"] == CHOSEN[0].dsl
    assert row["seed"] == CHOSEN[0].seed
    assert row["winner"] == audition.AS_WRITTEN


# --------------------------------------------------------------------- a run, against a fake


class _Terminal:
    def isatty(self) -> bool:
        return True


def test_a_whole_run_against_a_fake_live(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Five pairs written, each at its own tempo, voted, logged; the Set's tempo put back."""
    spec = load_session(ROOT / "session.toml")
    daw = FakeDawAdapter(
        track_names=[track.name for track in spec.tracks],
        scenes=max(len(spec.scenes), 4),
        tempo_bpm=spec.tempo_bpm,
        quantization=spec.quantization,
    )
    ab = audition._ab_script()
    tempos: list[float] = []
    monkeypatch.setattr(ab, "play", lambda daw, scene, seconds: tempos.append(daw.tempo()))
    monkeypatch.setattr(ab, "why", lambda: "")
    monkeypatch.setattr(audition, "_ab_script", lambda: ab)
    monkeypatch.setattr(audition, "build_adapter", lambda host, timeout_s: daw)
    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr("builtins.input", lambda prompt: "1")
    log = tmp_path / "votes.jsonl"
    monkeypatch.setattr(sys, "argv", ["audition_shuffle.py", "--log", str(log)])

    assert audition.main() == 0

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [row["take"] for row in rows] == [take.name for take in CHOSEN]
    assert tempos == [take.section.bpm for take in CHOSEN for _ in range(2)]
    assert daw.tempo() == spec.tempo_bpm
    assert not daw.is_playing()
    # Nothing before the tally says which side was which.
    before_tally = capsys.readouterr().err.split("\nas written preferred in")[0]
    assert audition.STRAIGHTENED not in before_tally
    assert audition.AS_WRITTEN not in before_tally
    assert "A was" not in before_tally
