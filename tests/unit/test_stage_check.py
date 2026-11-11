"""`garagem check`: every failure kind reported, all at once, each with its fix (ADR-028)."""

from __future__ import annotations

from pathlib import Path

import pytest

from garagem.daw import DawTimeoutError, DawUnavailableError, FakeDawAdapter, load_session
from garagem.daw.fake import DEFAULT_VOLUME
from garagem.setlist import load_setlist, save_setlist
from garagem.stage import cli
from garagem.stage.check import Finding, Level, Probes, ready, ready_check, render_check

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "session.toml"
CONTROLLER = ROOT / "controller.toml"
COMMANDS = ROOT / "commands.toml"
# Baked at the Set's tempo, and never changed by a test: they write their own copies.
BAKED = ROOT / "setlists" / "arrangement.json"
PORT = "Minilab3 MIDI"

QUIET_LOG = """AMidiIO: Midi Remote Scripts:
  MidiRemoteScript 1 [Control Surface="MiniLab_3" Input="None" Output="None"]
  MidiRemoteScript 2 [Control Surface="AbletonOSC" Input="None" Output="None"]
"""
CLASHING_LOG = """AMidiIO: Midi Remote Scripts:
  MidiRemoteScript 1 [Control Surface="MiniLab_3" Input="Minilab3 (MIDI)" Output="None"]
  MidiRemoteScript 2 [Control Surface="AbletonOSC" Input="None" Output="None"]
"""


def matching_daw(**extra: object) -> FakeDawAdapter:
    tracks = load_session(SESSION).tracks
    base: dict[str, object] = {
        "track_names": [track.name for track in tracks],
        "device_names": [(track.instrument,) for track in tracks],
        "volumes": [DEFAULT_VOLUME if t.volume is None else t.volume for t in tracks],
        "pans": [0.0 if track.pan is None else track.pan for track in tracks],
        "scenes": 8,
        "tempo_bpm": 132.0,
    }
    return FakeDawAdapter(**(base | extra))  # type: ignore[arg-type]


def probes(
    daw: FakeDawAdapter | None = None,
    *,
    inputs: tuple[str, ...] = (PORT,),
    log: str | None = QUIET_LOG,
) -> Probes:
    live = daw if daw is not None else matching_daw()
    return Probes(connect=lambda: live, midi_inputs=lambda: list(inputs), live_log=lambda: log)


def check(
    probe: Probes | None = None,
    *,
    session: Path = SESSION,
    controller: Path = CONTROLLER,
    commands: Path = COMMANDS,
    setlist: Path = BAKED,
    fix: bool = False,
) -> tuple[Finding, ...]:
    return ready_check(session, controller, commands, setlist, probe or probes(), fix=fix)


def kinds(findings: tuple[Finding, ...]) -> set[str]:
    return {finding.kind for finding in findings if finding.level is not Level.OK}


def every_problem_says_what_to_do(findings: tuple[Finding, ...]) -> bool:
    return all(finding.fix for finding in findings if finding.level is not Level.OK)


# ------------------------------------------------------------------------------ all well


def test_a_ready_set_passes_and_says_what_it_checked() -> None:
    findings = check()

    assert ready(findings)
    assert all(finding.level is Level.OK for finding in findings)
    assert {finding.area for finding in findings} == {
        "session.toml",
        "Live",
        "the Set",
        "MiniLab",
        "keyboard",
        "the show",
    }
    assert render_check(findings).endswith("Ready for the show.\n")


def test_the_check_writes_nothing_to_the_set() -> None:
    daw = matching_daw(tempo_bpm=120.0)
    check(probes(daw))
    assert not [call for call in daw.calls if call.startswith("set_")]
    assert "close" in daw.calls


# ------------------------------------------------------------------------- one at a time


def test_a_session_file_that_is_not_there(tmp_path: Path) -> None:
    findings = check(session=tmp_path / "session.toml")
    assert kinds(findings) == {"session_missing"}
    assert every_problem_says_what_to_do(findings)


def test_a_session_file_that_cannot_be_used(tmp_path: Path) -> None:
    broken = tmp_path / "session.toml"
    broken.write_text("schema = 1\ntempo_bpm = 5000\n", encoding="utf-8")
    assert kinds(check(session=broken)) == {"session_unreadable"}


def test_a_session_without_the_bass(tmp_path: Path) -> None:
    text = SESSION.read_text(encoding="utf-8").replace('role = "bass"', 'role = "tuba"')
    edited = tmp_path / "session.toml"
    edited.write_text(text, encoding="utf-8")
    assert "missing_role" in kinds(check(session=edited))


def test_a_closed_live_is_one_failure_and_the_rest_still_runs() -> None:
    daw = matching_daw(fail_with=DawTimeoutError("silence"), fail_after=0)
    findings = check(probes(daw))

    assert kinds(findings) == {"live_silent"}
    assert {finding.area for finding in findings if finding.level is Level.OK} >= {
        "MiniLab",
        "the show",
    }
    assert "Control Surface" in next(f.fix for f in findings if f.kind == "live_silent")


def test_another_program_holding_the_port_is_named_as_such() -> None:
    daw = matching_daw(fail_with=DawUnavailableError("port taken"), fail_after=0)
    assert kinds(check(probes(daw))) == {"live_busy"}


def test_live_going_quiet_in_the_middle_of_the_check() -> None:
    daw = matching_daw(fail_with=DawTimeoutError("silence"), fail_after=2)
    assert kinds(check(probes(daw))) == {"live_silent"}


def test_a_playing_live_is_a_failure_with_the_space_bar_as_its_fix() -> None:
    daw = matching_daw()
    daw.start_playing()
    findings = check(probes(daw))
    assert kinds(findings) == {"live_playing"}
    assert "space bar" in next(f.fix for f in findings if f.kind == "live_playing")


def test_a_track_in_solo_is_named_with_the_click_that_undoes_it() -> None:
    names = [track.name for track in load_session(SESSION).tracks]
    findings = check(probes(matching_daw(soloed=[name == "KEYS" for name in names])))
    assert kinds(findings) == {"track_soloed"}
    soloed = next(f for f in findings if f.kind == "track_soloed")
    assert "KEYS" in soloed.what
    assert "lit S" in soloed.fix
    assert not ready(findings)


def test_a_track_switched_off_is_named_with_the_click_that_undoes_it() -> None:
    names = [track.name for track in load_session(SESSION).tracks]
    off = [name in ("BASS", "LEAD") for name in names]
    findings = check(probes(matching_daw(muted=off)))
    assert kinds(findings) == {"track_off"}
    switched = next(f for f in findings if f.kind == "track_off")
    assert "BASS, LEAD" in switched.what
    assert "grey number" in switched.fix
    assert not ready(findings)


def test_fix_leaves_a_solo_for_the_person_who_pressed_it() -> None:
    count = len(load_session(SESSION).tracks)
    daw = matching_daw(soloed=[True] * count)
    assert kinds(check(probes(daw), fix=True)) == {"track_soloed"}
    assert daw.track_soloed(0) is True


def test_every_divergence_is_listed_with_who_fixes_it() -> None:
    names = [track.instrument for track in load_session(SESSION).tracks]
    names[4] = "Grand Piano"
    daw = matching_daw(tempo_bpm=120.0, device_names=[(name,) for name in names])
    findings = check(probes(daw))

    assert kinds(findings) == {"set_tempo", "set_wrong_instrument"}
    fixes = {finding.kind: finding.fix for finding in findings}
    assert "garagem check --fix" in fixes["set_tempo"]
    assert "drag it onto the track" in fixes["set_wrong_instrument"]


def test_fix_sets_what_it_can_and_leaves_the_rest_for_a_person() -> None:
    names = [track.instrument for track in load_session(SESSION).tracks]
    names[4] = "Grand Piano"
    daw = matching_daw(tempo_bpm=120.0, device_names=[(name,) for name in names])
    findings = check(probes(daw), fix=True)

    assert daw.tempo() == 132.0
    assert kinds(findings) == {"set_wrong_instrument"}


def test_fix_writes_nothing_while_live_plays() -> None:
    daw = matching_daw(tempo_bpm=120.0)
    daw.start_playing()
    findings = check(probes(daw), fix=True)

    assert daw.tempo() == 120.0
    assert kinds(findings) == {"live_playing", "set_tempo"}


def test_a_controller_file_that_cannot_be_used(tmp_path: Path) -> None:
    broken = tmp_path / "controller.toml"
    broken.write_text("schema = 1\n[controller]\nport = ''\n", encoding="utf-8")
    assert kinds(check(controller=broken)) == {"controller_unreadable"}
    assert kinds(check(controller=tmp_path / "nowhere.toml")) == {"controller_missing"}


def test_an_unplugged_minilab_is_a_warning_not_a_failure() -> None:
    findings = check(probes(inputs=("IAC Driver Bus 1",)))
    assert kinds(findings) == {"minilab_missing"}
    assert ready(findings)
    assert "Ready, with 1 warning." in render_check(findings)


def test_a_control_surface_on_the_cue_port_stops_the_show() -> None:
    findings = check(probes(log=CLASHING_LOG))
    assert kinds(findings) == {"surface_clash"}
    assert "Input and Output to None" in next(f.fix for f in findings if f.kind == "surface_clash")


def test_an_unreadable_live_log_is_a_warning() -> None:
    findings = check(probes(log=None))
    assert kinds(findings) == {"live_log_unreadable"}
    assert ready(findings)


def test_a_commands_file_that_is_missing_or_cannot_be_used(tmp_path: Path) -> None:
    assert kinds(check(commands=tmp_path / "nowhere.toml")) == {"commands_missing"}
    broken = tmp_path / "commands.toml"
    broken.write_text("schema = 1\n", encoding="utf-8")
    assert kinds(check(commands=broken)) == {"commands_unreadable"}


def test_a_cue_with_no_word_is_a_warning(tmp_path: Path) -> None:
    text = COMMANDS.read_text(encoding="utf-8")
    solo = '[[command]]\nword = "solo"\ncue = "next_solo"\nhelp = "the next section is a solo"\n'
    assert solo in text
    edited = tmp_path / "commands.toml"
    edited.write_text(text.replace(solo, ""), encoding="utf-8")
    findings = check(commands=edited)
    assert kinds(findings) == {"commands_incomplete"}
    assert ready(findings)


def test_a_show_that_is_not_baked_says_how_to_bake_it(tmp_path: Path) -> None:
    findings = check(setlist=tmp_path / "show.json")
    assert kinds(findings) == {"setlist_missing"}
    assert "scripts/bake_setlist.py" in next(f.fix for f in findings if f.level is Level.FAIL)


def test_a_setlist_that_cannot_be_read(tmp_path: Path) -> None:
    broken = tmp_path / "show.json"
    broken.write_text("{", encoding="utf-8")
    assert kinds(check(setlist=broken)) == {"setlist_unreadable"}


def test_a_setlist_at_another_tempo_is_not_a_problem(tmp_path: Path) -> None:
    """The show sets each song's tempo itself, so the Set's own is not the setlist's."""
    other = tmp_path / "show.json"
    save_setlist(load_setlist(BAKED).model_copy(update={"bpm": 120.0}), other)
    findings = check(setlist=other)
    assert kinds(findings) == set()
    assert any("3 songs at 132 BPM, from disk" in finding.what for finding in findings)


# ------------------------------------------------------------------------------ at once


def test_every_failure_is_reported_in_one_run(tmp_path: Path) -> None:
    daw = matching_daw(fail_with=DawTimeoutError("silence"), fail_after=0)
    findings = check(
        probes(daw, inputs=(), log=CLASHING_LOG),
        setlist=tmp_path / "show.json",
    )

    assert kinds(findings) == {"live_silent", "minilab_missing", "surface_clash", "setlist_missing"}
    assert every_problem_says_what_to_do(findings)
    assert not ready(findings)
    assert "Not ready: 3 things to fix first." in render_check(findings)


# ---------------------------------------------------------------------------------- cli


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> FakeDawAdapter:
    daw = matching_daw()
    monkeypatch.setattr(cli, "build_adapter", lambda host, timeout_s: daw)
    monkeypatch.setattr(cli, "input_names", lambda: [PORT])
    monkeypatch.setattr(cli, "read_live_log", lambda: QUIET_LOG)
    return daw


def paths(setlist: Path = BAKED) -> list[str]:
    return [
        "--session",
        str(SESSION),
        "--controller",
        str(CONTROLLER),
        "--commands",
        str(COMMANDS),
        "--setlist",
        str(setlist),
    ]


def test_garagem_check_exits_zero_when_ready(
    wired: FakeDawAdapter, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["check", *paths()]) == 0
    assert "Ready for the show." in capsys.readouterr().err


def test_garagem_check_exits_one_when_not(
    wired: FakeDawAdapter, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["check", *paths(tmp_path / "show.json")]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_garagem_check_fix_sets_the_tempo(wired: FakeDawAdapter) -> None:
    wired.set_tempo(120.0)
    assert cli.main(["check", "--fix", *paths()]) == 0
    assert wired.tempo() == 132.0


def test_garagem_commands_prints_the_cheat_sheet(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["commands", "--commands", str(COMMANDS), "--controller", str(CONTROLLER)]) == 0
    sheet = capsys.readouterr().out
    assert "solo" in sheet and "(pad 5)" in sheet
