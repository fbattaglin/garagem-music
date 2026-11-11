"""`garagem show`, headless: the check gates it, the keyboard reaches the band, quit ends it."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from garagem.control import ControllerSpec, FakeController
from garagem.daw import FakeDawAdapter, load_session
from garagem.daw.fake import DEFAULT_VOLUME
from garagem.llm import AnthropicAdapter
from garagem.obs import load_events
from garagem.setlist import (
    SetlistSpec,
    SongSpec,
    Verdict,
    load_setlist,
    save_setlist,
    save_spec,
)
from garagem.stage.check import Probes
from garagem.stage.show import ShowFiles, Wiring, pick, run_show
from garagem.stage.terminal import HeadlessScreen
from garagem.transport import Scheduler

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "session.toml"
BAKED = ROOT / "setlists" / "arrangement.json"
PORT = "Minilab3 MIDI"
QUIET_LOG = """AMidiIO: Midi Remote Scripts:
  MidiRemoteScript 1 [Control Surface="MiniLab_3" Input="None" Output="None"]
"""


def matching_daw() -> FakeDawAdapter:
    tracks = load_session(SESSION).tracks
    return FakeDawAdapter(
        track_names=[track.name for track in tracks],
        device_names=[(track.instrument,) for track in tracks],
        volumes=[DEFAULT_VOLUME if t.volume is None else t.volume for t in tracks],
        pans=[0.0 if track.pan is None else track.pan for track in tracks],
        scenes=8,
        tempo_bpm=132.0,
    )


def files(tmp_path: Path, setlist: Path = BAKED) -> ShowFiles:
    return ShowFiles(
        session=SESSION,
        controller=ROOT / "controller.toml",
        commands=ROOT / "commands.toml",
        setlist=setlist,
        log=tmp_path / "show.jsonl",
        catalog=ROOT / "config" / "models.toml",
        budget=ROOT / "config" / "budget.toml",
    )


class Rig:
    def __init__(self, *, minilab: bool = False) -> None:
        self.daw = matching_daw()
        self.pads: list[FakeController] = []
        inputs = [PORT] if minilab else []
        self.wiring = Wiring(
            probes=Probes(
                connect=lambda: self.daw, midi_inputs=lambda: inputs, live_log=lambda: QUIET_LOG
            ),
            build_minilab=self.minilab,
        )
        self.out = io.StringIO()

    def minilab(self, spec: ControllerSpec) -> FakeController:
        pad = FakeController(spec)
        self.pads.append(pad)
        return pad

    def show(self, tmp_path: Path, screen: HeadlessScreen, **kwargs: object) -> int:
        return run_show(files(tmp_path, **kwargs), 1, self.wiring, screen, self.out)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> object:
        raise AssertionError("the show plays from disk and never builds a model adapter")

    monkeypatch.setattr(AnthropicAdapter, "from_env", staticmethod(refuse))


def finished(self: Scheduler, *args: object, **kwargs: object) -> None:
    self.finished = True


def test_a_show_that_is_not_ready_refuses_before_the_band_plays(tmp_path: Path) -> None:
    rig = Rig()
    assert rig.show(tmp_path, HeadlessScreen(), setlist=tmp_path / "show.json") == 1
    printed = rig.out.getvalue()
    assert "not baked yet" in printed
    assert "garagem show starts once garagem check has nothing to fix." in printed
    assert "start_playing" not in rig.daw.calls


def test_a_ready_show_plays_the_song_from_disk_and_ends_on_its_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Scheduler, "run", finished)
    rig = Rig()
    assert rig.show(tmp_path, HeadlessScreen()) == 0

    printed = rig.out.getvalue()
    assert "Ready, with 1 warning." in printed  # no MiniLab: the keyboard is enough
    assert "Seven: played to its end." in printed
    kinds = [event.kind for event in load_events(tmp_path / "show.jsonl")]
    assert kinds[0] == "setlist_loaded" and kinds[-1] == "session_ended"
    assert rig.daw.calls.index("start_playing") < rig.daw.calls.index("stop_playing")


def test_a_song_plays_at_its_own_tempo_and_the_set_gets_its_own_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig()
    heard: list[float] = []

    def played(self: Scheduler, *args: object, **kwargs: object) -> None:
        heard.append(rig.daw.tempo())
        self.finished = True

    monkeypatch.setattr(Scheduler, "run", played)
    baked = load_setlist(BAKED)
    faster = [
        song.model_copy(
            update={
                "form": tuple(s.model_copy(update={"bpm": 140.0}) for s in song.form),
                "takes": tuple(
                    t.model_copy(update={"briefing": t.briefing.model_copy(update={"bpm": 140.0})})
                    for t in song.takes
                ),
            }
        )
        for song in baked.songs
    ]
    other = tmp_path / "show.json"
    save_setlist(baked.model_copy(update={"songs": tuple(faster)}), other)

    assert rig.show(tmp_path, HeadlessScreen(), setlist=other) == 0
    assert heard == [140.0]
    assert rig.daw.tempo() == 132.0


def test_typed_words_reach_the_band_and_quit_ends_the_show(tmp_path: Path) -> None:
    """The real scheduler, on a Live that never sends a beat: only `quit` can end it."""
    rig = Rig()
    screen = HeadlessScreen(["fill", "sollo", "quit"])
    assert rig.show(tmp_path, screen) == 0

    events = load_events(tmp_path / "show.jsonl")
    (declined,) = [event for event in events if event.kind == "cue_declined"]
    assert (declined.detail["cue"], declined.detail["reason"]) == ("fill", "before_the_downbeat")
    assert any(event.kind == "stopped_by_hand" for event in events)
    assert not any(event.kind == "beat_lost" for event in events)

    said = "\n".join(screen.last)
    assert "fill: not now, the song has not started yet" in said
    assert "'sollo': no such word, type help" in said
    assert "quit: stopping the show" in said
    assert "NOW    stopped" in screen.last
    assert "Seven: stopped by hand." in rig.out.getvalue()
    assert "stop_playing" in rig.daw.calls


def test_a_plugged_minilab_is_heard_beside_the_keyboard_and_let_go_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Scheduler, "run", finished)
    rig = Rig(minilab=True)
    assert rig.show(tmp_path, HeadlessScreen()) == 0
    (pad,) = rig.pads
    assert (pad.started, pad.stopped) == (1, 1)
    assert "Ready for the show." in rig.out.getvalue()


def test_a_song_the_setlist_does_not_have_is_refused(tmp_path: Path) -> None:
    rig = Rig()
    assert run_show(files(tmp_path), 9, rig.wiring, HeadlessScreen(), rig.out) == 1
    assert "plays songs 1 to 3" in rig.out.getvalue()


# ------------------------------------------------- what the show plays (ADR-030)


def concert_beside(tmp_path: Path, *verdicts: str) -> Path:
    """A copy of the baked setlist with a concert beside it: its songs reversed, judged."""
    baked = load_setlist(BAKED)
    bake = tmp_path / "c.json"
    save_setlist(baked, bake)
    songs = [
        SongSpec(
            title=song.title,
            key=song.key,
            scale=song.scale,
            feel=song.feel,
            seconds=song.seconds,
            seed=song.seed,
            verdict=Verdict(verdict),
        )
        for song, verdict in zip(reversed(baked.songs), verdicts, strict=True)
    ]
    save_spec(SetlistSpec(name="c", songs=tuple(songs)), tmp_path / "c.toml")
    return bake


def test_the_show_plays_the_concerts_order_not_the_files(tmp_path: Path) -> None:
    bake = concert_beside(tmp_path, "", "", "")
    baked = load_setlist(bake)
    assert pick(baked, bake, 1, None) == (baked.songs[-1], 1, 3)


def test_once_judged_the_show_counts_only_approved_songs(tmp_path: Path) -> None:
    bake = concert_beside(tmp_path, "rejected", "approved", "")
    baked = load_setlist(bake)
    assert pick(baked, bake, 1, None) == (baked.songs[1], 1, 1)
    assert pick(baked, bake, 2, None) == f"--song 2: {baked.name} plays songs 1 to 1\n"


def test_a_concert_with_nothing_approved_sends_the_person_to_the_studio(tmp_path: Path) -> None:
    bake = concert_beside(tmp_path, "rejected", "rejected", "rejected")
    said = pick(load_setlist(bake), bake, 1, None)
    assert isinstance(said, str) and "uv run garagem studio" in said


def test_an_audition_plays_a_song_whatever_its_verdict(tmp_path: Path) -> None:
    bake = concert_beside(tmp_path, "rejected", "rejected", "rejected")
    baked = load_setlist(bake)
    title = baked.songs[0].title
    assert pick(baked, bake, 1, title) == (baked.songs[0], 1, 1)
    assert "is not written" in str(pick(baked, bake, 1, "Nobody's Song"))


def test_the_log_names_a_song_by_its_place_in_the_file_which_is_what_curation_joins_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Scheduler, "run", finished)
    bake = concert_beside(tmp_path, "", "", "")
    rig = Rig()
    assert rig.show(tmp_path, HeadlessScreen(), setlist=bake) == 0
    (loaded,) = [e for e in load_events(tmp_path / "show.jsonl") if e.kind == "setlist_loaded"]
    assert loaded.detail["song"] == 3
    assert loaded.detail["title"] == load_setlist(bake).songs[2].title
