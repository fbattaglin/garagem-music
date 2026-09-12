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
    assert (cal.PAIRS, cal.THRESHOLD) == (16, 12)


def test_the_threshold_is_harder_than_a_coin() -> None:
    """P(>= 12 of 16) = 0.038 under a coin. Computed here rather than trusted."""
    assert cal._coin_tail(cal.THRESHOLD, cal.PAIRS) < 0.05


def test_the_power_is_what_was_claimed_before_the_run() -> None:
    """Stated up front because a limitation found afterwards is an excuse.

    This design can find a strong effect and is weak against a moderate one. The ceiling
    is the corpus: only 17 pairs remain that the superseded run did not already play.

    The formula lives in the script rather than here, so the figure `tally` prints and
    the figure this test asserts cannot drift apart.
    """
    assert 0.60 < cal._power(0.75) < 0.66
    assert cal._power(0.85) > 0.90


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


def test_no_briefing_from_the_superseded_run_is_played_again() -> None:
    """A preference about music he has already judged on another axis is not fresh."""
    heard = cal.already_heard(cal.JUDGED_LOG)
    assert heard
    corpus = cal.load_corpus([ROOT / "bench" / name for name in cal.DEFAULT_CORPUS])
    for messy, _ in cal.extremes(corpus, cal.PAIRS, skip=heard):
        key = (messy.section.name, messy.section.bars, messy.section.bpm, str(messy.section.feel))
        assert key not in heard


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
    messy, clean = cal.extremes(corpus, cal.PAIRS, skip=cal.already_heard(cal.JUDGED_LOG))[index]
    return cal.Trial(index, messy, clean, first)


@pytest.mark.parametrize(
    ("first", "vote", "agreed"),
    [
        ("clean", "A", "true"),
        ("clean", "B", "false"),
        ("messy", "A", "false"),
        ("messy", "B", "true"),
        ("clean", "same", "same"),
    ],
)
def test_agreement_is_the_cleaner_take_winning(
    tmp_path: Path, first: str, vote: str, agreed: str
) -> None:
    """All four corners: getting this backwards would invert the whole result.

    The hypothesis under test is that kick/snare collisions *cost* preference, so the
    metric is credited when the take it scores cleaner is the one preferred.
    """
    log = tmp_path / "calibration.jsonl"
    cal.record(log, a_trial(first=first), vote, 12.0)
    assert json.loads(log.read_text(encoding="utf-8"))["metric_agreed"] == agreed


def test_the_reason_is_recorded_beside_the_preference(tmp_path: Path) -> None:
    """A bare vote says which won; only the reason says what it had (§16)."""
    log = tmp_path / "calibration.jsonl"
    cal.record(log, a_trial(), "A", 12.0, "less boring")
    assert json.loads(log.read_text(encoding="utf-8"))["reason"] == "less boring"


def test_the_reason_menu_matches_the_ab_s() -> None:
    """Two vocabularies would make the two runs impossible to compare."""
    assert cal.REASONS["3"] == "cleaner, less messy"
    assert len(cal.REASONS) == 5


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
        cal.record(log, a_trial(index % cal.PAIRS, "clean"), "A" if index < agreed else "B", 12.0)
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


def test_a_reversed_result_is_not_reported_as_a_near_miss(tmp_path: Path) -> None:
    """5 of 15 is not "we could not detect it" — it is the effect with its sign flipped.

    The upper tail answers "did the run clear the bar" and misleads about what happened:
    at 5 agreed of 15 it reads 0.94, which looks like a coin and buries a 10-of-15
    reversal. §3 corrected `tally` for claiming *more* than the design delivers; this is
    the same defect with its sign flipped (`phase-4-findings.md` §5).
    """
    report = cal.tally(_log_with(tmp_path, 5, 15))
    assert "runs the other way" in report
    assert "10 of 15" in report
    assert "P(<= 5 of 15)" in report
    assert "Absence of evidence" in report


def test_the_tally_states_the_n_it_actually_ran(tmp_path: Path) -> None:
    """The power sentence described the superseded 10-pair round for a whole run."""
    report = cal.tally(_log_with(tmp_path, 5, cal.PAIRS))
    assert "ten trials" not in report
    assert f"{cal.PAIRS} trials" in report


def test_the_power_sentence_is_derived_from_the_threshold(tmp_path: Path) -> None:
    """Moving THRESHOLD must not leave a stale claim about power standing behind it."""
    report = cal.tally(_log_with(tmp_path, 5, cal.PAIRS))
    assert f"{cal._power(0.75):.0%}" in report


def test_a_finished_log_can_be_read_back_without_a_listening_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`tally` was reachable only after listening, so a finished run could not be re-read.

    The log is evidence: reading it must never write to it.
    """
    log = _log_with(tmp_path, 5, cal.PAIRS)
    before = log.read_bytes()
    monkeypatch.setattr(sys, "argv", ["calibrate_metrics.py", "--tally", "--log", str(log)])

    assert cal.main() == 0
    assert log.read_bytes() == before
    assert "NOT MET" in capsys.readouterr().err
