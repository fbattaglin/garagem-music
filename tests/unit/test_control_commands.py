"""`commands.toml` and the keyboard: every cue typeable, and only what is named (ADR-028)."""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from garagem.control import (
    CommandSpec,
    ConsoleController,
    ControllerSpecError,
    FakeController,
    StageAction,
    load_commands,
    load_controller,
)
from garagem.domain import Control, Cue, CueKind
from garagem.transport import CueQueue

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = ROOT / "commands.toml"
PADS = ROOT / "controller.toml"
SPEC = load_commands(SHIPPED)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "commands.toml"
    path.write_text("schema = 1\n" + body, encoding="utf-8")
    return path


# ------------------------------------------------------------------------- the shipped file


def test_every_cue_can_be_typed_the_solo_included() -> None:
    assert {command.cue for command in SPEC.commands if command.cue is not None} == set(CueKind)


def test_the_show_can_be_asked_for_help_and_to_quit() -> None:
    assert {command.stage for command in SPEC.commands if command.stage is not None} == set(
        StageAction
    )


def test_the_cheat_sheet_names_every_word_and_the_pad_beside_it() -> None:
    sheet = SPEC.cheat_sheet(load_controller(PADS).pad_numbers())
    assert all(command.word in sheet for command in SPEC.commands)
    assert "(pad 1)" in sheet.splitlines()[3]  # stop
    solo = next(line for line in sheet.splitlines() if line.strip().startswith("solo"))
    assert "pad" not in solo


# ------------------------------------------------------------------------------ matching


@pytest.mark.parametrize("typed", ["fill", "FILL", "  fill  ", "Fill\n"])
def test_a_word_is_matched_whole_ignoring_case_and_spaces(typed: str) -> None:
    command = SPEC.lookup(typed)
    assert command is not None and command.cue is CueKind.FILL


@pytest.mark.parametrize("typed", ["fil", "fills", "f", "fill now", "fil l", "", "chorus_now"])
def test_nothing_else_is_matched(typed: str) -> None:
    assert SPEC.lookup(typed) is None


@given(st.text(max_size=20))
def test_no_input_becomes_a_cue_it_did_not_name(typed: str) -> None:
    delivered: list[Control] = []
    console = ConsoleController(SPEC)
    console.start(delivered.append)
    console.hear(typed)

    words = {command.word: command for command in SPEC.commands}
    named = words.get(typed.strip().casefold())
    if named is None or named.cue is None:
        assert delivered == []
    else:
        assert delivered == [Cue(kind=named.cue)]


# ----------------------------------------------------------------------- the keyboard port


def test_a_typed_cue_is_the_cue_its_pad_sends_and_queues_the_same() -> None:
    """Both land in one queue, stamped alike: everything after it cannot tell them apart."""
    pads = load_controller(PADS)
    fill = next(pad for pad in pads.pads if pad.cue is CueKind.FILL)
    queue = CueQueue(stamp=lambda: 37)
    pad = FakeController(pads)
    keyboard = ConsoleController(SPEC)
    pad.start(queue.offer)
    keyboard.start(queue.offer)

    pad.receive("note_on", fill.channel - 1, fill.note, 100)
    keyboard.hear("fill")

    struck, typed = queue.drain()
    assert (struck.control, struck.beat) == (typed.control, typed.beat)


def test_nothing_is_delivered_before_start_or_after_stop() -> None:
    delivered: list[Control] = []
    console = ConsoleController(SPEC)
    console.hear("stop")
    console.start(delivered.append)
    console.stop()
    console.hear("stop")
    assert delivered == []
    assert not console.running


def test_a_stage_word_is_answered_but_never_reaches_the_band() -> None:
    delivered: list[Control] = []
    console = ConsoleController(SPEC)
    console.start(delivered.append)
    command = console.hear("quit")
    assert command is not None and command.stage is StageAction.QUIT
    assert delivered == []


def test_without_a_screen_lines_are_read_on_a_thread_and_each_is_reported() -> None:
    lines = iter(["solo", "sollo", "help"])

    def read() -> str:
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    done = threading.Event()
    heard: list[tuple[str, str | None]] = []
    delivered: list[Control] = []

    def report(line: str, command: object) -> None:
        heard.append((line, getattr(command, "word", None)))
        if len(heard) == 3:
            done.set()

    console = ConsoleController(SPEC, lines=read, on_heard=report)
    console.start(delivered.append)
    assert done.wait(2.0)

    assert heard == [("solo", "solo"), ("sollo", None), ("help", "help")]
    assert delivered == [Cue(kind=CueKind.NEXT_SOLO)]


# ---------------------------------------------------------------------------- refusals


@pytest.mark.parametrize(
    ("body", "complaint"),
    [
        ("", "names no [[command]]"),
        ('[[command]]\nword = "Fill"\ncue = "fill"\nhelp = "x"\n', "one word in lowercase"),
        ('[[command]]\nword = "fill in"\ncue = "fill"\nhelp = "x"\n', "one word in lowercase"),
        ('[[command]]\nword = "fill"\ncue = "fill"\n', "needs a help line"),
        ('[[command]]\nword = "fill"\nhelp = "x"\n', "exactly one cue or stage"),
        (
            '[[command]]\nword = "fill"\ncue = "fill"\nstage = "quit"\nhelp = "x"\n',
            "exactly one cue or stage",
        ),
        ('[[command]]\nword = "fill"\ncue = "flil"\nhelp = "x"\n', "unknown 'flil'"),
        ('[[command]]\nword = "bye"\nstage = "exit"\nhelp = "x"\n', "unknown 'exit'"),
        (
            '[[command]]\nword = "fill"\ncue = "fill"\nhelp = "x"\n'
            '[[command]]\nword = "fill"\ncue = "stop"\nhelp = "y"\n',
            "given twice",
        ),
    ],
)
def test_an_unplayable_file_is_refused_naming_the_entry(
    tmp_path: Path, body: str, complaint: str
) -> None:
    with pytest.raises(ControllerSpecError, match=re.escape(complaint)):
        load_commands(write(tmp_path, body))


def test_a_wrong_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "commands.toml"
    path.write_text("schema = 2\n", encoding="utf-8")
    with pytest.raises(ControllerSpecError, match="schema"):
        load_commands(path)


def test_an_empty_spec_cannot_be_built_from_a_file_but_matches_nothing() -> None:
    assert CommandSpec(commands=()).lookup("fill") is None
