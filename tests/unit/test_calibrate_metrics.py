"""The calibration gate's machinery, with nobody listening.

What these tests protect is the thing that makes the gate worth having: that the pair
Fabiano is asked about differs in *one* variable, that the threshold was fixed before the
first note, and that the verdict cannot be read off the run while it is happening.

The listening itself is his, and no test can stand in for it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "calibrate_metrics.py"
    spec = importlib.util.spec_from_file_location("calibrate_metrics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["calibrate_metrics"] = module
    spec.loader.exec_module(module)
    return module


cal = _load()


# ------------------------------------------------------------------- the pre-registration


def test_the_threshold_is_in_the_source_and_not_in_a_flag() -> None:
    """A threshold that can be passed on the command line is a threshold chosen after."""
    assert (cal.PAIRS, cal.THRESHOLD) == (10, 8)


def test_the_threshold_is_harder_than_a_coin() -> None:
    """P(>= 8 of 10) = 0.055 under a coin. Computed here rather than trusted."""
    from math import comb

    tail = sum(comb(10, k) for k in range(cal.THRESHOLD, 11)) / 2**10
    assert tail < 0.06


# -------------------------------------------------------------------------- the corpus


def test_the_corpus_reconstructs_and_is_large_enough() -> None:
    """Every recorded round, realised offline. No network, no key, no cost."""
    corpus = cal.load_corpus([ROOT / "bench" / name for name in cal.DEFAULT_CORPUS])
    assert len(corpus) > 2 * cal.PAIRS
    assert {item.source for item in corpus} == set(cal.DEFAULT_CORPUS)


def test_a_row_the_draw_does_not_contain_fails_loudly() -> None:
    """Silently mispairing a briefing would score a section against the wrong chart."""
    drawn = cal.draw(cal.CORPUS_DRAWN, cal.CORPUS_SEED)
    with pytest.raises(ValueError, match=r"the arranger has moved|does not contain"):
        cal._align(drawn, 0, {"section": "nope", "bars": 3, "bpm": 77.0}, "x.jsonl", 0)


def test_the_draw_is_read_unfiltered() -> None:
    """`briefings` applies `worth_asking`, and that filter moved when MIN_DEADLINE_S did.

    The earlier rounds asked for four-bar intros that today's filter removes, so aligning
    against the filtered list would drop those logs entirely.
    """
    from bench_sections import briefings

    assert len(cal.draw(cal.CORPUS_DRAWN, cal.CORPUS_SEED)) > len(
        briefings(cal.CORPUS_DRAWN, cal.CORPUS_SEED)
    )


# --------------------------------------------------------------------------- the pairing


def test_both_sides_of_a_pair_are_the_same_briefing() -> None:
    """The one-variable claim, and the reason the pairing is not simply the extremes.

    §10 put a static loop against an arrangement and spent a round measuring two things
    at once. Here the chart, key, tempo, feel and length are held fixed and only the drum
    pattern the model wrote differs.
    """
    corpus = cal.load_corpus([ROOT / "bench" / name for name in cal.DEFAULT_CORPUS])
    for messy, clean in cal.extremes(corpus, cal.PAIRS):
        assert messy.section == clean.section


def test_the_messy_side_really_does_score_messier() -> None:
    corpus = cal.load_corpus([ROOT / "bench" / name for name in cal.DEFAULT_CORPUS])
    for messy, clean in cal.extremes(corpus, cal.PAIRS):
        assert messy.collision < clean.collision


def test_the_two_sides_are_different_recordings() -> None:
    """Same briefing, different rounds — otherwise there is nothing to compare."""
    corpus = cal.load_corpus([ROOT / "bench" / name for name in cal.DEFAULT_CORPUS])
    for messy, clean in cal.extremes(corpus, cal.PAIRS):
        assert (messy.source, messy.row) != (clean.source, clean.row)


def test_asking_for_more_pairs_than_exist_is_refused() -> None:
    corpus = cal.load_corpus([ROOT / "bench" / name for name in cal.DEFAULT_CORPUS])
    with pytest.raises(ValueError, match="pairs asked for"):
        cal.extremes(corpus, 10_000)


# ---------------------------------------------------------------------------- the record


def a_trial(index: int = 0, first: str = "messy") -> object:
    corpus = cal.load_corpus([ROOT / "bench" / name for name in cal.DEFAULT_CORPUS])
    messy, clean = cal.extremes(corpus, cal.PAIRS)[index]
    return cal.Trial(index, messy, clean, first)


@pytest.mark.parametrize(
    ("first", "vote", "agreed"),
    [
        ("messy", "A", "true"),
        ("messy", "B", "false"),
        ("clean", "A", "false"),
        ("clean", "B", "true"),
        ("messy", "same", "same"),
    ],
)
def test_agreement_is_derived_from_the_hidden_order(
    tmp_path: Path, first: str, vote: str, agreed: str
) -> None:
    """All four corners, because getting this backwards would invert the whole result."""
    log = tmp_path / "calibration.jsonl"
    cal.record(log, a_trial(first=first), vote, 12.0)
    assert json.loads(log.read_text(encoding="utf-8"))["metric_agreed"] == agreed


def test_the_row_says_where_both_sides_came_from(tmp_path: Path) -> None:
    """A verdict that cannot be traced back to its material is not evidence."""
    log = tmp_path / "calibration.jsonl"
    cal.record(log, a_trial(), "A", 12.0)
    row = json.loads(log.read_text(encoding="utf-8"))
    assert ":" in row["messy_from"] and ":" in row["clean_from"]
    assert row["messy_collision"] < row["clean_collision"]


# ----------------------------------------------------------------------------- the tally


def _log_with(tmp_path: Path, agreed: int, total: int) -> Path:
    log = tmp_path / "calibration.jsonl"
    for index in range(total):
        cal.record(log, a_trial(index % cal.PAIRS, "messy"), "A" if index < agreed else "B", 12.0)
    return log


def test_the_tally_reports_met_at_the_threshold(tmp_path: Path) -> None:
    assert "MET" in cal.tally(_log_with(tmp_path, cal.THRESHOLD, cal.PAIRS))


def test_the_tally_reports_not_met_one_below(tmp_path: Path) -> None:
    report = cal.tally(_log_with(tmp_path, cal.THRESHOLD - 1, cal.PAIRS))
    assert "NOT MET" in report
    assert "does not steer arrangement work" in report


def test_a_missed_threshold_is_not_reported_as_a_refutation(tmp_path: Path) -> None:
    """Absence of evidence, at ten trials, is all a missed threshold is.

    The first version of `tally` printed "kit_collision does not track the ear" on any
    miss. Ten trials reach 8 only about half the time even when the metric is right 75%
    of the time, so that sentence claimed far more than the design can deliver — and it
    would have been believed, because it arrived exactly when the answer was unwelcome.
    """
    report = cal.tally(_log_with(tmp_path, 6, cal.PAIRS))
    assert "does not track the ear" not in report
    assert "Absence of evidence" in report
    assert "under a coin" in report
