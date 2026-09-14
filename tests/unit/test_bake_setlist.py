"""Baking a setlist and playing it back, with no network, no Live and no money (ADR-024).

The paid bake is run by hand. Everything it does is here against fakes: the plan and its
estimate, one call per distinct briefing, what a miss stores, the file it writes, and a
rehearsal of the song played from that file.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from garagem.agents import structural
from garagem.domain import Feel
from garagem.llm import (
    BakedProvider,
    CircuitBreaker,
    Governor,
    GuardedProvider,
    LLMProvider,
    ProviderUnavailableError,
    Request,
    StreamEvent,
    load_budget,
    load_catalog,
    prices_of,
)
from garagem.obs import model_share
from garagem.setlist import (
    Missed,
    SetlistSpec,
    Song,
    SongSpec,
    Take,
    digest,
    drifted,
    load_setlist,
    played,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_catalog(ROOT / "config" / "models.toml")
MODEL = structural(CATALOG)
BPM = 132.0


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_setlist")
rehearsal = _load("rehearse_session")

SPEC = SetlistSpec(
    name="test",
    songs=(
        SongSpec(title="One", key=4, scale="minor", feel=Feel.STRAIGHT8, seconds=90, seed=7),
        SongSpec(title="Two", key=9, scale="minor", feel=Feel.SHUFFLE, seconds=90, seed=11),
    ),
)
PLANNED = bake.plan(SPEC, BPM)


def guarded(inner: LLMProvider) -> GuardedProvider:
    budget = load_budget(ROOT / "config" / "budget.toml")
    return GuardedProvider(
        inner,
        governor=Governor(budget.fuse(prices_of(CATALOG))),
        breaker=CircuitBreaker(),
    )


def baked_songs() -> list[Song]:
    provider = guarded(BakedProvider(bake.floor_answers(PLANNED), name="fake"))
    return asyncio.run(bake.bake(provider, MODEL, PLANNED, emit=lambda text: None))


# ------------------------------------------------------------------------------ the plan


def test_the_plan_asks_once_per_distinct_briefing() -> None:
    for song in PLANNED:
        briefings = [song.form[index] for index in song.asked]
        assert len(set(briefings)) == len(briefings)
        assert len(song.asked) < len(song.form)


def test_the_estimate_is_the_measured_usage_beside_a_pessimistic_bound() -> None:
    expected, bound = bake.estimate(MODEL, 18)
    assert Decimal("0") < expected < bound
    assert expected == MODEL.price.cost_of(bake.MEASURED_USAGE) * 18


# ---------------------------------------------------------------------------- one section


def test_a_delivered_section_is_a_take_that_plays_what_it_baked() -> None:
    song = PLANNED[0]
    index = song.asked[0]
    provider = guarded(BakedProvider(bake.floor_answers(PLANNED)))
    outcome = asyncio.run(
        bake.shoot(provider, MODEL, song.form[index], index, song.spec.seed + index)
    )
    assert isinstance(outcome, Take)
    score = played(outcome)
    assert score is not None
    assert digest(score) == outcome.digest
    assert outcome.parts == "BAS,DRM,GTR,KEY"


class Down:
    name = "down"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        raise ProviderUnavailableError("ConnectError: the network is gone")
        yield  # pragma: no cover


class Slow:
    name = "slow"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        await asyncio.sleep(10)
        raise AssertionError("the deadline should have cancelled this")
        yield  # pragma: no cover


def test_a_failed_call_is_stored_as_missed_with_its_reason() -> None:
    song = PLANNED[0]
    index = song.asked[0]
    outcome = asyncio.run(bake.shoot(guarded(Down()), MODEL, song.form[index], index, 7))
    assert isinstance(outcome, Missed)
    assert outcome.reason == "ProviderUnavailableError"


def test_a_call_past_its_deadline_is_missed_and_not_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    song = PLANNED[0]
    index = song.asked[0]
    real = bake.request_for
    monkeypatch.setattr(
        bake, "request_for", lambda section, model: real(section, model, deadline_s=0.01)
    )
    outcome = asyncio.run(bake.shoot(guarded(Slow()), MODEL, song.form[index], index, 7))
    assert isinstance(outcome, Missed)
    assert outcome.reason == "deadline_missed"


# ------------------------------------------------------------------------------ the bake


def test_a_bake_holds_every_song_its_form_and_a_take_per_asked_briefing() -> None:
    songs = baked_songs()
    assert [song.title for song in songs] == ["One", "Two"]
    for song, planned in zip(songs, PLANNED, strict=True):
        assert song.form == planned.form
        assert [take.section for take in song.takes] == list(planned.asked)
        assert song.missed == ()
        assert drifted(song) == ()


def with_argv(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["bake_setlist.py", *argv])


def a_spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "test.toml"
    path.write_text(
        'name = "test"\n[[song]]\ntitle = "One"\nkey = 4\nseconds = 90\nseed = 7\n',
        encoding="utf-8",
    )
    return path


def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> object:
        raise AssertionError("no provider may be built without --yes")

    monkeypatch.setattr(bake.AnthropicAdapter, "from_env", staticmethod(refuse))


def test_without_yes_nothing_is_sent_and_nothing_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    no_key(monkeypatch)
    spec = a_spec_file(tmp_path)
    with_argv(monkeypatch, str(spec))
    assert bake.main() == 0
    assert not spec.with_suffix(".json").exists()
    assert "nothing sent" in capsys.readouterr().err


def test_a_fake_bake_is_free_and_says_it_is_fake(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    no_key(monkeypatch)
    spec = a_spec_file(tmp_path)
    with_argv(monkeypatch, str(spec), "--fake")
    assert bake.main() == 0
    assert not spec.with_suffix(".json").exists()
    setlist = load_setlist(tmp_path / "test.fake.json")
    assert setlist.provider == "fake"
    assert all(take.cost_usd == 0 for song in setlist.songs for take in song.takes)


def test_an_existing_bake_is_never_overwritten(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    no_key(monkeypatch)
    spec = a_spec_file(tmp_path)
    (tmp_path / "test.fake.json").write_text("{}", encoding="utf-8")
    with_argv(monkeypatch, str(spec), "--fake")
    assert bake.main() == 1
    assert (tmp_path / "test.fake.json").read_text(encoding="utf-8") == "{}"
    assert "already exists" in capsys.readouterr().err


# ------------------------------------------------------------------------------ playback


def test_a_baked_song_rehearsed_plays_its_takes_and_the_floor_the_rest() -> None:
    song = baked_songs()[0]
    log, calls = rehearsal.rehearse(0.0, 0, {}, baked=song)
    served, played_sections = model_share(log.events)
    assert played_sections == len(song.form)
    # Every section worth asking is served from the bake, repeats included.
    assert served == sum(1 for s in song.form if bake.worth_asking(s))
    assert calls == served
    reasons = {event.detail.get("reason") for event in log.of_kind("fallback")}
    assert reasons <= {"no_time", "not_in_buffer"}
