"""The musical regression suite: a recording of the model, judged on every push.

ADR-000 names the risk it answers: a provider changes a pinned model's behaviour without
warning. CI holds no key, so it cannot ask the model anything. What it judges is the
recording in `cassettes/regression/`, made by hand with `scripts/record_regression.py`
(`phase-4-findings.md` §13). It fails in three ways:

- **The prompt moved.** A cassette recorded for a request the producer no longer sends
  stops matching. Record again, deliberately.
- **The model fell under Phase 3's bar.** Conformance at or over 95% and approval at or over
  80%, over every briefing asked, failures included.
- **What the system makes of a recording changed.** Each section's realised score and the
  set's summary are golden files. After a code change, the diff is a regression to explain.
  After a new recording, the diff is the drift to read.

Regenerating is a deliberate act with a diff to read, as in `tests/golden/`:

    GARAGEM_UPDATE_GOLDEN=1 uv run pytest tests/regression -q

Until the set is recorded there is nothing to judge, and the module says so rather than
passing.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

from garagem.agents import structural
from garagem.llm import load_catalog
from garagem.obs import Shot
from garagem.obs.sections import summarise

ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ROOT / "cassettes" / "regression"
DATA = Path(__file__).parent / "data"
UPDATE = os.environ.get("GARAGEM_UPDATE_GOLDEN") == "1"


def _load() -> ModuleType:
    path = ROOT / "scripts" / "record_regression.py"
    spec = importlib.util.spec_from_file_location("record_regression", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_regression"] = module
    spec.loader.exec_module(module)
    return module


if not (CASSETTES / "set.json").exists():
    pytest.skip(
        "the regression set is not recorded yet: uv run python scripts/record_regression.py --yes",
        allow_module_level=True,
    )

recorder = _load()
MODEL = structural(load_catalog(ROOT / "config" / "models.toml"))
RECORDED = recorder.load_set(CASSETTES)


@cache
def shots() -> tuple[Shot, ...]:
    return tuple(recorder.replay(CASSETTES, RECORDED, MODEL))


def golden(path: Path, produced: str) -> None:
    if UPDATE:
        DATA.mkdir(exist_ok=True)
        path.write_text(produced, encoding="utf-8")
    assert path.exists(), f"missing golden file {path.name}; regenerate deliberately"
    assert produced == path.read_text(encoding="utf-8")


def test_the_recording_is_of_the_set_the_recorder_draws() -> None:
    """A changed arranger or draw is a different population, and it wants a new recording."""
    drawn = [(id_, section, seed) for id_, section, seed in recorder.the_set()]
    recorded = [(entry.id, entry.section, entry.seed) for entry in RECORDED.briefings]
    assert recorded == drawn


def test_every_cassette_was_recorded_for_the_request_the_producer_sends() -> None:
    assert recorder.mismatched(CASSETTES, RECORDED, MODEL) == []


def test_every_briefing_has_its_cassette_or_its_failure() -> None:
    for entry in RECORDED.briefings:
        assert entry.failed or recorder.cassette_of(CASSETTES, entry).exists(), entry.id


def test_the_recording_meets_phase_3s_targets() -> None:
    assert recorder.missed_targets(summarise(shots(), drawn=RECORDED.drawn)) == []


@pytest.mark.parametrize("entry", RECORDED.briefings, ids=lambda entry: entry.id)
def test_what_the_system_makes_of_each_recording_is_unchanged(entry: object) -> None:
    score = recorder.played(CASSETTES, entry, MODEL)
    golden(DATA / f"{entry.id}.dsl", recorder.rendered(score))  # type: ignore[attr-defined]


def test_the_summary_of_the_set_is_unchanged() -> None:
    scores = [recorder.played(CASSETTES, entry, MODEL) for entry in RECORDED.briefings]
    golden(DATA / "summary.txt", recorder.summary(RECORDED, shots(), scores))


def test_every_golden_file_belongs_to_a_briefing() -> None:
    expected = {f"{entry.id}.dsl" for entry in RECORDED.briefings}
    assert {path.name for path in DATA.glob("*.dsl")} == expected
