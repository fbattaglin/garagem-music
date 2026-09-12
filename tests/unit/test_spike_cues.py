"""The spike's arithmetic, with no Live: how a launch beat and a legato verdict are read.

The experiments themselves only mean something against the real Set and are run by hand.
What can be wrong offline is the reckoning that turns two numbers from Live into an
answer, and a wrong verdict here would send the plan down the wrong branch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "spike_cues.py"
    spec = importlib.util.spec_from_file_location("spike_cues", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["spike_cues"] = module
    spec.loader.exec_module(module)
    return module


spike = _load()


@pytest.mark.parametrize(("fired", "bar"), [(1.7, 4.0), (5.9, 8.0), (10.2, 12.0), (0.1, 4.0)])
def test_a_fire_mid_bar_lands_on_the_next_bar_line(fired: float, bar: float) -> None:
    assert spike.next_bar(fired) == bar


def test_the_launch_beat_is_the_song_time_less_the_position() -> None:
    assert spike.launched_at(song_time=13.0, position=1.0) == 12.0


def test_positions_a_loop_apart_are_the_same_beat() -> None:
    assert spike.same_beat(1.0, 1.0 + spike.CLIP_BEATS)
    assert spike.same_beat(0.2, spike.CLIP_BEATS - 0.2)
    assert not spike.same_beat(1.0, 3.0)


def test_a_clip_that_carried_the_position_over_is_legato() -> None:
    # A launched at beat 4; B fired at 13.8, launched at 16. At song time 17, A's timeline
    # is at 13 and a fresh launch would be at 1.
    assert spike.verdict(position=13.0, continuing=13.0, restarted=1.0) == "legato"


def test_a_clip_that_began_again_is_a_restart() -> None:
    assert spike.verdict(position=1.02, continuing=13.0, restarted=1.0) == "restart"


def test_two_explanations_that_agree_are_unclear_rather_than_a_guess() -> None:
    """If the old clip had just looped, both readings name the same beat."""
    assert spike.verdict(position=1.0, continuing=1.1, restarted=0.9) == "unclear"


def test_the_report_names_each_question_and_its_answer() -> None:
    finding = spike.Finding("clip fire waits for the next bar", "quantised", {"bar": 8.0})
    text = spike.render([finding])
    assert "clip fire waits for the next bar" in text
    assert "**quantised**" in text
    assert "bar=8.0" in text
