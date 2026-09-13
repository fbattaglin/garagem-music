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
from garagem.control import FakeController, load_controller
from garagem.daw import DawPort, DawTimeoutError, FakeDawAdapter
from garagem.domain import Feel, Instrument, MacroKind, Section
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


CLEAR_TABLE = """2026-09-12T13:50:23.532354: info: AMidiIO: Midi Remote Scripts:
  MidiRemoteScript 1 [Control Surface="MiniLab_3" Input="None" Output="None"]
  MidiRemoteScript 2 [Control Surface="AbletonOSC" Input="None" Output="None"]
2026-09-12T13:50:23.532381: info: AMidiIO: Takeover Mode: None
"""

IN_THE_WAY = CLEAR_TABLE.replace(
    'Input="None" Output="None"]', 'Input="Minilab3 (MIDI)" Output="Minilab3 (MIDI)"]', 1
)


@pytest.fixture(autouse=True)
def live_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Never this machine's real Live log: a unit test must not depend on Live's settings."""
    log = tmp_path / "Log.txt"
    log.write_text(CLEAR_TABLE, encoding="utf-8")
    monkeypatch.setattr(jam, "find_live_log", lambda: log)
    return log


def finished(self: object, form: object, seed: object = None, endings: object = None) -> None:
    """A performance that played to the end, with nothing in it."""
    self.finished = True  # type: ignore[attr-defined]


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


def test_a_dry_run_shows_how_each_section_hands_over(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_argv(monkeypatch, "--dry-run", "--seconds", "180")
    jam.main()
    printed = capsys.readouterr().err
    assert "-> build" in printed
    assert "-> final" in printed


def test_plain_is_the_form_as_it_played_before_phase_4(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_argv(monkeypatch, "--dry-run", "--seconds", "180", "--plain")
    jam.main()
    printed = capsys.readouterr().err
    assert "->" not in printed
    spec = jam.load_session(jam.DEFAULT_SESSION)
    brief = jam.brief_of(spec, 180.0, Feel.STRAIGHT8, 4, "minor")
    assert jam.plan(brief, 7, plain=True) == (jam.arrange(brief, 7), None)


def test_the_plan_lifts_the_last_chorus_and_ends_the_song() -> None:
    spec = jam.load_session(jam.DEFAULT_SESSION)
    brief = jam.brief_of(spec, 180.0, Feel.STRAIGHT8, 4, "minor")
    form, endings = jam.plan(brief, 7, plain=False)
    assert endings is not None
    assert len(endings) == len(form)
    assert str(endings[-1]) == "final"
    assert form != jam.arrange(brief, 7)


def test_a_dry_run_with_the_controller_prints_the_legend_and_opens_no_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(spec: object) -> object:
        raise AssertionError("a dry run must not open a MIDI port")

    monkeypatch.setattr(jam, "build_controller", refuse)
    with_argv(monkeypatch, "--dry-run", "--seconds", "30", "--controller", "minilab")
    assert jam.main() == 0
    printed = capsys.readouterr().err
    assert "note 36  -> stop" in printed


def test_an_unplayable_controller_file_is_refused_before_live_is_touched(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bad = tmp_path / "controller.toml"
    bad.write_text('schema = 1\n[controller]\nport = ""\n', encoding="utf-8")

    def refuse(host: str, timeout_s: float) -> DawPort:
        raise AssertionError("a bad controller file must not cost a Set check")

    monkeypatch.setattr(jam, "build_adapter", refuse)
    with_argv(monkeypatch, "--controller", "minilab", "--controller-spec", str(bad))
    assert jam.main() == 1
    assert "port must name a MIDI input" in capsys.readouterr().err


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

    def explode(self: object, form: object, seed: object = None, endings: object = None) -> None:
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
    monkeypatch.setattr(jam.Scheduler, "run", finished)
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
    monkeypatch.setattr(jam.Scheduler, "run", finished)
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

    def explode(self: object, form: object, seed: object = None, endings: object = None) -> None:
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


# ------------------------------------------------------------------------- the controller


def test_the_controller_is_heard_during_the_run_and_stopped_after_it(
    live: FakeDawAdapter,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Stage 2's wiring end to end: pad -> queue -> scheduler -> log -> the count printed."""
    controller = FakeController(load_controller(ROOT / "controller.toml"))
    monkeypatch.setattr(jam, "build_controller", lambda spec: controller)

    def performance(
        self: object, form: object, seed: object = None, endings: object = None
    ) -> None:
        controller.receive("note_on", 9, 36, 110)
        controller.turn(MacroKind.DENSITY, 0.5)
        self._conduct()  # type: ignore[attr-defined]
        self.finished = True  # type: ignore[attr-defined]

    monkeypatch.setattr(jam.Scheduler, "run", performance)
    with_argv(
        monkeypatch,
        "--seconds",
        "10",
        "--controller",
        "minilab",
        "--log",
        str(tmp_path / "jam.jsonl"),
    )

    assert jam.main() == 0
    assert (controller.started, controller.stopped) == (1, 1)
    printed = capsys.readouterr().err
    assert "act on the next bar" in printed
    assert "2 controls received: density x1, stop x1" in printed


def test_a_minilab_that_is_not_plugged_in_is_reported_without_a_traceback(
    live: FakeDawAdapter,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(jam, "build_controller", lambda spec: FakeController(available=False))
    with_argv(
        monkeypatch,
        "--seconds",
        "10",
        "--controller",
        "minilab",
        "--log",
        str(tmp_path / "jam.jsonl"),
    )
    assert jam.main() == 1
    assert "built unplugged" in capsys.readouterr().err
    assert not live.is_playing()


def test_the_controller_is_stopped_even_when_the_run_fails(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    controller = FakeController()
    monkeypatch.setattr(jam, "build_controller", lambda spec: controller)

    def explode(self: object, form: object, seed: object = None, endings: object = None) -> None:
        raise RuntimeError("something went wrong mid-performance")

    monkeypatch.setattr(jam.Scheduler, "run", explode)
    with_argv(
        monkeypatch,
        "--seconds",
        "10",
        "--controller",
        "minilab",
        "--log",
        str(tmp_path / "jam.jsonl"),
    )
    with pytest.raises(RuntimeError, match="mid-performance"):
        jam.main()
    assert (controller.started, controller.stopped) == (1, 1)


# --------------------------------------------------------------- what can stop a performance


def test_a_live_control_surface_on_the_cue_port_stops_the_band_before_it_starts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], live_log: Path
) -> None:
    """The first MiniLab gate: Live's own MiniLab script stopped the transport mid-song."""
    live_log.write_text(IN_THE_WAY, encoding="utf-8")

    def refuse(host: str, timeout_s: float) -> DawPort:
        raise AssertionError("a control surface in the way must be reported before Live is used")

    monkeypatch.setattr(jam, "build_adapter", refuse)
    with_argv(monkeypatch, "--seconds", "10", "--controller", "minilab")
    assert jam.main() == 1
    printed = capsys.readouterr().err
    assert "slot 1 (MiniLab_3)" in printed
    assert "Input and Output to None" in printed


def test_without_the_controller_a_live_control_surface_is_not_checked(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch, live_log: Path
) -> None:
    live_log.write_text(IN_THE_WAY, encoding="utf-8")
    monkeypatch.setattr(jam.Scheduler, "run", finished)
    with_argv(monkeypatch, "--seconds", "10", "--log", str(live_log.parent / "jam.jsonl"))
    assert jam.main() == 0


def test_an_unreadable_live_log_is_a_warning_not_a_refusal(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(jam, "find_live_log", lambda: None)
    monkeypatch.setattr(jam, "build_controller", lambda spec: FakeController())
    monkeypatch.setattr(jam.Scheduler, "run", finished)
    with_argv(monkeypatch, "--seconds", "10", "--controller", "minilab", "--log", str(LOG))
    assert jam.main() == 0
    assert "could not find Live's Log.txt" in capsys.readouterr().err


def test_a_performance_stopped_from_outside_is_a_failure_with_the_bar_it_stopped_at(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 0 means the form was played to the end, which a stopped transport did not."""
    monkeypatch.setattr(jam.Scheduler, "run", lambda self, form, seed=None, endings=None: None)
    with_argv(monkeypatch, "--seconds", "10", "--log", str(LOG))
    assert jam.main() == 1
    printed = capsys.readouterr().err
    assert "the performance stopped at bar" in printed
    assert "no beat" in printed


def test_a_looping_song_position_is_reported_as_the_loop_not_as_a_stop(
    live: FakeDawAdapter, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def looped(self: object, form: object, seed: object = None, endings: object = None) -> None:
        self.stopped_because = "position_went_back"  # type: ignore[attr-defined]

    monkeypatch.setattr(jam.Scheduler, "run", looped)
    with_argv(monkeypatch, "--seconds", "10", "--log", str(LOG))
    assert jam.main() == 1
    printed = capsys.readouterr().err
    assert "went back before the next bar" in printed
    assert "arrangement loop" in printed


# ------------------------------------------------------------------------------- jumps


def test_the_chorus_candidate_goes_into_the_scene_session_toml_names_chorus() -> None:
    spec = jam.load_session(jam.DEFAULT_SESSION)
    assert jam.candidate_scenes(spec) == {"chorus": 2}


def test_a_session_with_no_chorus_scene_is_refused_with_the_reason() -> None:
    spec = jam.load_session(jam.DEFAULT_SESSION)
    unnamed = type(spec)(
        name=spec.name,
        tempo_bpm=spec.tempo_bpm,
        quantization=spec.quantization,
        tracks=spec.tracks,
        scenes=spec.scenes[:2],
        loop=spec.loop,
    )
    with pytest.raises(jam.SessionSpecError, match="CHORUS"):
        jam.candidate_scenes(unnamed)


def test_the_summary_says_how_many_bars_each_jump_took_to_land() -> None:
    from garagem.obs import EventLog

    log = EventLog(None)
    log.record("cue_received", 12.0, bar=3, drained_bar=3, cue="chorus_now", family="jump")
    log.record(
        "cue_applied",
        12.0,
        cue="chorus_now",
        cue_bar=3,
        fired_bar=4,
        scene=2,
        section=2,
        name="chorus",
        seed=1,
    )
    log.record("cue_received", 1.0, bar=-1, drained_bar=-1, cue="chorus_now", family="jump")
    log.record("cue_declined", 1.0, cue="chorus_now", cue_bar=-1, reason="before_the_downbeat")
    text = jam.render_cues(log)
    assert "1 cues landed after: 1 bar x1" in text
    assert "declined: before_the_downbeat x1" in text


def test_bar_cue_variants_go_into_the_scenes_session_toml_names_for_them() -> None:
    spec = jam.load_session(jam.DEFAULT_SESSION)
    assert jam.variant_scenes(spec) == {"stop": {0: 4, 1: 5}, "fill": {0: 6, 1: 7}}


def test_a_session_without_variant_scenes_is_refused_with_their_names() -> None:
    spec = jam.load_session(jam.DEFAULT_SESSION)
    short = type(spec)(
        name=spec.name,
        tempo_bpm=spec.tempo_bpm,
        quantization=spec.quantization,
        tracks=spec.tracks,
        scenes=spec.scenes[:3],
        loop=spec.loop,
    )
    with pytest.raises(jam.SessionSpecError, match="STOP A"):
        jam.variant_scenes(short)
