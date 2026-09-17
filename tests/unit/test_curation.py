"""Curation: marks read back from a log, joined to their takes, and written into a setlist.

ADR-024's answer to "when is the model worth calling" is gathered here, while Fabiano plays:
a keep or a veto on the section sounding, blind to who wrote it. These tests hold the join,
the rule that the last word wins, and that a mark on the floor's music curates nothing.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from garagem.agents import structural
from garagem.domain import Feel
from garagem.engines import shifted
from garagem.llm import (
    BakedProvider,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    load_budget,
    load_catalog,
    prices_of,
)
from garagem.obs import EventLog, load_events, marks, per_author
from garagem.setlist import (
    Setlist,
    SetlistSpec,
    SongSpec,
    TakeStatus,
    load_setlist,
    save_setlist,
    served,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "config" / "models.toml")
MODEL = structural(CATALOG)


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_setlist")
curation = _load("curate_setlist")


def a_setlist() -> Setlist:
    spec = SetlistSpec(
        name="t",
        songs=(SongSpec(title="One", key=4, feel=Feel.STRAIGHT8, seconds=90, seed=7),),
    )
    planned = bake.plan(spec, 132.0)
    provider = GuardedProvider(
        BakedProvider(bake.floor_answers(planned)),
        governor=Governor(load_budget(ROOT / "config" / "budget.toml").fuse(prices_of(CATALOG))),
        breaker=CircuitBreaker(),
    )
    songs = asyncio.run(bake.bake(provider, MODEL, planned, emit=lambda _: None))
    return Setlist(
        name="t",
        provider="fake",
        model=MODEL.id,
        baked_on=date(2026, 9, 13),
        bpm=132.0,
        songs=tuple(songs),
    )


SETLIST = a_setlist()
SONG = SETLIST.songs[0]


def a_run(
    log: EventLog,
    strikes: list[tuple[str, int, str]],
    *,
    setlist: str | None = "t",
    knob: tuple[int, float] | None = None,
) -> None:
    """A performance as the log sees it: the producer's takes, the scheduler's writes, marks.

    `strikes` is (mark, section, author). A model section's take is the song's take for the
    first section with that briefing, as a setlist run serves it. `knob` serves every take under
    its briefing moved by that offset, echo included, as a knob-conducted run logs it.
    """
    if setlist is not None:
        log.record(
            "setlist_loaded",
            0.0,
            setlist=setlist,
            provider="fake",
            model=MODEL.id,
            song=1,
            title="One",
            takes=len(SONG.takes),
        )
    by_briefing = {take.briefing: take for take in SONG.takes}
    for index, section in enumerate(SONG.form):
        take = by_briefing.get(section)
        if take is not None:
            dsl = take.dsl if knob is None else served(take, shifted(take.briefing, *knob))
            log.record("section_parsed", 0.0, section=index, seed=7 + index, dsl=dsl)
            log.record(
                "section_generated", float(index), section=index, seed=7 + index, source="buffer"
            )
        else:
            log.record(
                "fallback", float(index), section=index, seed=7 + index, reason="not_in_buffer"
            )
        for mark, at, author in strikes:
            if at == index:
                log.record(
                    "take_marked",
                    float(index),
                    mark=mark,
                    cue_bar=index,
                    section=index,
                    name=section.name,
                    author=author,
                    seed=7 + index,
                )
    log.record("session_ended", 99.0, finished=True, bpm=132.0)


def model_section() -> int:
    return SONG.takes[0].section


def floor_section() -> int:
    held = {take.briefing for take in SONG.takes}
    return next(i for i, section in enumerate(SONG.form) if section not in held)


# ------------------------------------------------------------------------------ reading


def test_a_mark_on_a_model_section_carries_its_take() -> None:
    log = EventLog(None)
    a_run(log, [("keep", model_section(), "model")])
    (found,) = marks(log.events)
    assert found.dsl == SONG.takes[0].dsl
    assert (found.setlist, found.song) == ("t", 1)


def test_a_mark_on_the_floor_carries_no_take() -> None:
    log = EventLog(None)
    a_run(log, [("veto", floor_section(), "floor")])
    (found,) = marks(log.events)
    assert found.dsl is None


def test_a_mark_on_a_jumped_to_chorus_is_the_floors() -> None:
    log = EventLog(None)
    index = model_section()
    log.record("section_parsed", 0.0, section=index, seed=7, dsl=SONG.takes[0].dsl)
    log.record("section_generated", 1.0, section=index, seed=7, source="buffer")
    log.record(
        "cue_applied",
        2.0,
        cue="chorus_now",
        cue_bar=1,
        fired_bar=2,
        scene=2,
        section=index,
        name="chorus",
        seed=1,
    )
    log.record(
        "take_marked",
        3.0,
        mark="keep",
        cue_bar=2,
        section=index,
        name="chorus",
        author="model",
        seed=7,
    )
    assert marks(log.events)[0].dsl is None


def test_runs_do_not_leak_into_each_other() -> None:
    log = EventLog(None)
    a_run(log, [])
    a_run(log, [("keep", model_section(), "model")], setlist=None)
    (found,) = marks(log.events)
    assert found.setlist is None


def test_marks_are_counted_by_author_for_the_gate() -> None:
    log = EventLog(None)
    a_run(log, [("keep", model_section(), "model"), ("veto", floor_section(), "floor")])
    counts = per_author(marks(log.events))
    assert counts["model"]["keep"] == 1
    assert counts["floor"]["veto"] == 1


# ------------------------------------------------------------------------------ curating


def test_a_keep_pins_and_a_veto_retires() -> None:
    log = EventLog(None)
    second = SONG.takes[1].section
    a_run(log, [("keep", model_section(), "model"), ("veto", second, "model")])
    curated, tally = curation.curate(SETLIST, marks(log.events))
    statuses = [take.status for take in curated.songs[0].takes]
    assert statuses[0] is TakeStatus.KEPT
    assert statuses[1] is TakeStatus.VETOED
    assert tally["keep"] == tally["veto"] == 1


def test_a_mark_on_a_take_a_knob_moved_still_curates_it() -> None:
    """The echo is rewritten for the moved briefing; the join is on what the model wrote."""
    log = EventLog(None)
    a_run(log, [("veto", model_section(), "model")], knob=(1, 0.1))
    (found,) = marks(log.events)
    assert found.dsl != SONG.takes[0].dsl
    curated, tally = curation.curate(SETLIST, marks(log.events))
    assert curated.songs[0].takes[0].status is TakeStatus.VETOED
    assert tally["veto"] == 1


def test_the_last_word_on_a_take_wins() -> None:
    log = EventLog(None)
    a_run(log, [("keep", model_section(), "model")])
    a_run(log, [("veto", model_section(), "model")])
    curated, _ = curation.curate(SETLIST, marks(log.events))
    assert curated.songs[0].takes[0].status is TakeStatus.VETOED


def test_a_mark_on_the_floor_or_another_setlist_changes_nothing() -> None:
    log = EventLog(None)
    a_run(log, [("veto", floor_section(), "floor")])
    a_run(log, [("veto", model_section(), "model")], setlist="another")
    curated, tally = curation.curate(SETLIST, marks(log.events))
    assert curated == SETLIST
    assert tally["veto on the floor"] == 1


def test_curating_twice_from_one_log_gives_the_same_setlist(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "jam.jsonl")
    a_run(log, [("veto", model_section(), "model")])
    log.flush()
    once, _ = curation.curate(SETLIST, marks(load_events(tmp_path / "jam.jsonl")))
    twice, _ = curation.curate(once, marks(load_events(tmp_path / "jam.jsonl")))
    assert once == twice


def test_a_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "t.json"
    save_setlist(SETLIST, path)
    log = EventLog(tmp_path / "jam.jsonl")
    a_run(log, [("veto", model_section(), "model")])
    log.flush()
    monkeypatch.setattr(
        sys,
        "argv",
        ["curate_setlist.py", str(path), "--log", str(tmp_path / "jam.jsonl"), "--dry-run"],
    )
    assert curation.main() == 0
    assert load_setlist(path) == SETLIST
    printed = capsys.readouterr().err
    assert "1 veto mark(s)" in printed
    assert "model" not in printed.replace(MODEL.id, "")


# ------------------------------------------------------------------------------ re-baking


def test_a_vetoed_take_is_asked_again_and_the_old_one_retired() -> None:
    vetoed = SONG.takes[0].model_copy(update={"status": TakeStatus.VETOED})
    song = SONG.model_copy(update={"takes": (vetoed, *SONG.takes[1:])})
    setlist = SETLIST.model_copy(update={"songs": (song,)})
    # The same text answers again: proving the swap needs a delivery, not a different take.
    answers = {bake.brief(vetoed.briefing): vetoed.dsl}
    provider = GuardedProvider(
        BakedProvider(answers),
        governor=Governor(load_budget(ROOT / "config" / "budget.toml").fuse(prices_of(CATALOG))),
        breaker=CircuitBreaker(),
    )
    rebaked, delivered, missed = asyncio.run(
        bake.rebake(provider, MODEL, setlist, emit=lambda _: None)
    )
    assert (delivered, missed) == (1, 0)
    new_song = rebaked.songs[0]
    assert new_song.takes[0].status is TakeStatus.UNMARKED
    assert new_song.retired == (vetoed,)
    assert new_song.takes[1:] == SONG.takes[1:]


def test_a_rebake_that_misses_leaves_the_veto_standing() -> None:
    vetoed = SONG.takes[0].model_copy(update={"status": TakeStatus.VETOED})
    song = SONG.model_copy(update={"takes": (vetoed, *SONG.takes[1:])})
    setlist = SETLIST.model_copy(update={"songs": (song,)})
    provider = GuardedProvider(
        BakedProvider({}),
        governor=Governor(load_budget(ROOT / "config" / "budget.toml").fuse(prices_of(CATALOG))),
        breaker=CircuitBreaker(),
    )
    rebaked, delivered, missed = asyncio.run(
        bake.rebake(provider, MODEL, setlist, emit=lambda _: None)
    )
    assert (delivered, missed) == (0, 1)
    assert rebaked.songs[0].takes[0].status is TakeStatus.VETOED
    assert rebaked.songs[0].retired == ()
