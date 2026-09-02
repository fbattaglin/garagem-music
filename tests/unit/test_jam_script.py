"""The jam script's decisions, with a fake Live and nothing on the wire.

The two that matter are refusals. It will not play into a Set that does not match
`session.toml` — and it checks that with `diff_session`, the same function the bootstrap
uses, because two definitions of "the right Set" eventually give two answers. And
`--dry-run` opens no socket at all, which is what makes it safe to run while thinking.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from garagem.agents import deadline_for, worth_asking
from garagem.daw import DawPort, DawTimeoutError, FakeDawAdapter
from garagem.domain import Feel, Instrument, Section
from garagem.engines import SongBrief
from garagem.transport import ScoreBuffer

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "bench" / "test-jam.jsonl"


def _load_jam() -> ModuleType:
    path = ROOT / "scripts" / "jam.py"
    spec = importlib.util.spec_from_file_location("jam", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["jam"] = module
    spec.loader.exec_module(module)
    return module


jam = _load_jam()


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> FakeDawAdapter:
    """A fake Live that matches `session.toml`, wired in place of the real adapter."""
    spec = jam.load_session(jam.DEFAULT_SESSION)
    daw = FakeDawAdapter(
        track_names=[track.name for track in spec.tracks],
        scenes=max(len(spec.scenes), 4),
        tempo_bpm=spec.tempo_bpm,
        quantization=spec.quantization,
    )

    def build(host: str, timeout_s: float) -> DawPort:
        return daw

    monkeypatch.setattr(jam, "build_adapter", build)
    return daw


def with_argv(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["jam.py", *argv])


# -------------------------------------------------------------------------------- mapping


def test_every_role_in_the_session_maps_to_an_instrument() -> None:
    """A renamed track must not quietly send the bass to the drum machine."""
    spec = jam.load_session(jam.DEFAULT_SESSION)
    tracks = jam.tracks_of(spec)
    assert set(tracks) == set(Instrument)
    assert tracks[Instrument.DRUMS] == 0


def test_the_tempo_comes_from_the_set_and_not_from_a_flag() -> None:
    """Otherwise the arrangement and Live could disagree about how long a bar is."""
    spec = jam.load_session(jam.DEFAULT_SESSION)
    brief = jam.brief_of(spec, 60.0, Feel.STRAIGHT8, 4, "minor")
    assert isinstance(brief, SongBrief)
    assert brief.bpm == spec.tempo_bpm


# -------------------------------------------------------------------------------- dry run


def test_a_dry_run_prints_the_form_and_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(host: str, timeout_s: float) -> DawPort:
        raise AssertionError("a dry run must not build an adapter")

    monkeypatch.setattr(jam, "build_adapter", refuse)
    with_argv(monkeypatch, "--dry-run", "--seconds", "60")

    assert jam.main() == 0
    printed = capsys.readouterr().err
    assert "sections" in printed
    assert "intro" in printed


def test_the_seed_reaches_the_arranger(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    forms = []
    for seed in ("7", "11"):
        with_argv(monkeypatch, "--dry-run", "--seconds", "180", "--seed", seed)
        jam.main()
        forms.append(capsys.readouterr().err)
    assert forms[0] != forms[1]


# ------------------------------------------------------------------------------ refusals


def test_a_set_that_does_not_match_is_refused(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    live.set_track_name(1, "NOT THE BASS")
    with_argv(monkeypatch, "--seconds", "10")

    assert jam.main() == 1
    printed = capsys.readouterr().err
    assert "bootstrap_set.py" in printed
    assert live.fired == []


def test_a_live_that_is_not_answering_is_reported_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    closed = FakeDawAdapter(fail_with=DawTimeoutError("Live said nothing"), fail_after=0)
    monkeypatch.setattr(jam, "build_adapter", lambda host, timeout_s: closed)
    with_argv(monkeypatch, "--seconds", "10")

    assert jam.main() == 1
    printed = capsys.readouterr().err
    assert "Live said nothing" in printed
    # And the teardown said what it could not do rather than raising over the real error.
    assert "could not stop the transport" in printed


# ---------------------------------------------------------------------------- the finally


def test_the_transport_is_stopped_even_when_the_run_fails(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leaving Live playing a loop nobody is driving is not a tidy end."""

    def explode(self: object, form: object, seed: object = None) -> None:
        raise RuntimeError("something went wrong mid-performance")

    monkeypatch.setattr(jam.Scheduler, "run", explode)
    with_argv(monkeypatch, "--seconds", "10", "--log", str(LOG))

    with pytest.raises(RuntimeError, match="mid-performance"):
        jam.main()

    assert "stop_playing" in live.calls
    assert "close" in live.calls


# ------------------------------------------------------------------------- --generate


def test_without_the_flag_no_provider_is_ever_constructed(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 2's behaviour, byte for byte. That is what makes the two comparable."""

    def refuse(spec: object, catalog: object, budget: object) -> object:
        raise AssertionError("a run without --generate must not build a provider")

    monkeypatch.setattr(jam, "build_provider", refuse)
    monkeypatch.setattr(jam.Scheduler, "run", lambda self, form, seed=None: None)
    with_argv(monkeypatch, "--seconds", "10", "--log", str(LOG))

    assert jam.main() == 0


def test_generate_without_a_key_says_which_variable_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """And says it before opening a socket to Live: a missing key is not a Set problem."""

    def refuse(host: str, timeout_s: float) -> DawPort:
        raise AssertionError("the key is checked before Live is opened")

    monkeypatch.setattr(jam, "build_adapter", refuse)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with_argv(monkeypatch, "--seconds", "10", "--generate")

    assert jam.main() == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_a_dry_run_with_generate_still_opens_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        jam, "build_adapter", lambda host, timeout_s: pytest.fail("dry run opened Live")
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with_argv(monkeypatch, "--dry-run", "--generate", "--seconds", "60")

    assert jam.main() == 0
    assert "sections" in capsys.readouterr().err


def test_the_producer_is_started_and_stopped_in_the_finally(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A thread left running past the performance would keep spending money."""
    started: list[str] = []

    class Recording(jam.Producer):  # type: ignore[misc, name-defined]
        def start(self) -> None:
            started.append("start")

        def stop(self) -> None:
            started.append("stop")

    monkeypatch.setattr(jam, "Producer", Recording)
    monkeypatch.setattr(jam, "build_provider", lambda spec, catalog, budget: object())
    monkeypatch.setattr(jam.Scheduler, "run", lambda self, form, seed=None: None)
    # This test is about start/stop. The wait for a first section has its own test, and
    # leaving it in would spend the whole deadline waiting for a producer that is a stub.
    monkeypatch.setattr(jam, "prime", lambda buffer, first: 0.0)
    with_argv(monkeypatch, "--seconds", "10", "--generate", "--log", str(LOG))

    assert jam.main() == 0
    assert started == ["start", "stop"]


def test_the_producer_is_stopped_even_when_the_run_fails(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped: list[str] = []

    class Recording(jam.Producer):  # type: ignore[misc, name-defined]
        def start(self) -> None:
            pass

        def stop(self) -> None:
            stopped.append("stop")

    def explode(self: object, form: object, seed: object = None) -> None:
        raise RuntimeError("mid-performance")

    monkeypatch.setattr(jam, "Producer", Recording)
    monkeypatch.setattr(jam, "build_provider", lambda spec, catalog, budget: object())
    monkeypatch.setattr(jam, "prime", lambda buffer, first: 0.0)
    monkeypatch.setattr(jam.Scheduler, "run", explode)
    with_argv(monkeypatch, "--seconds", "10", "--generate", "--log", str(LOG))

    with pytest.raises(RuntimeError, match="mid-performance"):
        jam.main()
    assert stopped == ["stop"]
    assert "stop_playing" in live.calls


def test_a_cassette_provider_is_wrapped_in_the_guards(tmp_path: Path) -> None:
    """`llm-calls.md`: every call goes through the governor and the breaker.

    Including a replay. A rule with an exception for tests is a rule with an exception.
    """
    from garagem.llm import GuardedProvider, load_budget, load_catalog

    catalog = load_catalog(ROOT / "config" / "models.toml")
    budget = load_budget(ROOT / "config" / "budget.toml")
    path = tmp_path / "empty.jsonl"
    path.write_text(
        '{"cassette":1,"provider":"fake","model":"claude-sonnet-5","fingerprint":"x"}\n',
        encoding="utf-8",
    )
    provider = jam.build_provider(f"cassette:{path}", catalog, budget)
    assert isinstance(provider, GuardedProvider)


def a_first_section(bars: int) -> Section:
    from garagem.theory import parse_chart

    return Section(
        name="intro" if bars == 4 else "verse",
        bars=bars,
        key=4,
        scale="minor",
        feel=Feel.STRAIGHT8,
        bpm=132.0,
        dyn=1,
        tension=0.2,
        chart=parse_chart("| " + " | ".join(["Em"] * bars) + " |"),
    )


def test_the_wait_for_the_first_section_is_the_sections_own_deadline() -> None:
    """Not a number somebody picked: a model past its deadline is not going to answer.

    Eight bars rather than four: a 4-bar section is now under `MIN_DEADLINE_S` and is
    never requested at all, so waiting its deadline would be waiting for nothing — see
    the test below.
    """
    section = a_first_section(8)
    assert worth_asking(section)
    waited = jam.prime(ScoreBuffer(), section, margin_s=0.0)
    assert waited == pytest.approx(deadline_for(section), abs=0.3)


def test_priming_waits_for_nothing_when_the_first_section_will_not_be_asked_for() -> None:
    """A 4-bar intro is under `MIN_DEADLINE_S`, so no answer was ever coming.

    `bench/jam-phase3.jsonl`, 2026-09-01: *"first section not ready after 3.9s"* — the
    downbeat of every performance was delayed by a full deadline plus a margin, waiting on
    a request the producer had already declined to make. One run after the floor rose from
    a guessed 1.5 s to a measured 5.0 s.
    """
    section = a_first_section(4)
    assert not worth_asking(section)
    started = time.monotonic()
    assert jam.prime(ScoreBuffer(), section) == 0.0
    assert time.monotonic() - started < 0.1


def test_priming_returns_at_once_when_the_section_is_already_there() -> None:
    from garagem.domain import Feel, Section, SectionScore
    from garagem.theory import parse_chart
    from garagem.transport import ScoreBuffer

    section = Section(
        name="intro",
        bars=8,
        key=4,
        scale="minor",
        feel=Feel.STRAIGHT8,
        bpm=132.0,
        dyn=1,
        tension=0.2,
        chart=parse_chart("| Em |"),
    )
    buffer = ScoreBuffer()
    buffer.offer(0, SectionScore(section=section, parts=(), seed=7))
    assert jam.prime(buffer, section) < 0.5
