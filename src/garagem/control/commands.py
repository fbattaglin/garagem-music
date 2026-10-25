"""`commands.toml`: which typed word asks for what — the keyboard beside the MiniLab (ADR-028).

The same idiom as `controller.toml`: a file a person can read and argue with, a loader that
refuses anything unplayable and names the entry, and no words in code.

**A word is matched whole and exactly**, ignoring case and the spaces around it. No prefix,
no abbreviation and no nearest match: a typo is an unknown word, said back as one, and nothing
typed becomes a cue it did not name. On stage a wrong guess is worse than a refusal.

A word asks either for a cue, which goes into the same `CueQueue` as a pad and lands on the
same bar, or for a stage action, which the show acts on and the band never hears.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from garagem.control.errors import ControllerSpecError
from garagem.domain import CueKind

SCHEMA: Final = 1
WORD: Final = re.compile(r"[a-z]+")


class StageAction(StrEnum):
    """What a typed word asks of the show rather than of the band."""

    # Print the cheat sheet again.
    HELP = "help"
    # Stop the show now: the transport stops and the end card follows.
    QUIT = "quit"


@dataclass(frozen=True, slots=True)
class Command:
    word: str
    help: str
    cue: CueKind | None = None
    stage: StageAction | None = None


@dataclass(frozen=True, slots=True)
class CommandSpec:
    commands: tuple[Command, ...]

    def lookup(self, text: str) -> Command | None:
        typed = text.strip().casefold()
        for command in self.commands:
            if command.word == typed:
                return command
        return None

    def cheat_sheet(self, pads: Mapping[CueKind, int] | None = None) -> str:
        """Every word and what it does, with the pad that does the same where there is one."""
        pads = pads or {}
        width = max(len(command.word) for command in self.commands)
        lines = ["Type a word, then Enter:"]
        for command in self.commands:
            pad = pads.get(command.cue) if command.cue is not None else None
            also = f"  (pad {pad})" if pad is not None else ""
            lines.append(f"  {command.word:<{width}}  {command.help}{also}")
        return "\n".join(lines) + "\n"


def load_commands(path: Path) -> CommandSpec:
    """Read and validate `commands.toml`. Every refusal names the file and the entry."""
    raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema") != SCHEMA:
        raise ControllerSpecError(f"{path}: schema must be {SCHEMA}, got {raw.get('schema')!r}")
    entries: Sequence[dict[str, Any]] = raw.get("command", [])
    commands = tuple(
        _command(f"{path}: [[command]] #{number}", entry)
        for number, entry in enumerate(entries, start=1)
    )
    if not commands:
        raise ControllerSpecError(f"{path}: names no [[command]]; nothing could be typed")
    seen: set[str] = set()
    for command in commands:
        if command.word in seen:
            raise ControllerSpecError(f"{path}: the word {command.word!r} is given twice")
        seen.add(command.word)
    return CommandSpec(commands=commands)


def _command(where: str, entry: dict[str, Any]) -> Command:
    word = entry.get("word")
    if not isinstance(word, str) or WORD.fullmatch(word) is None:
        raise ControllerSpecError(f"{where}: word must be one word in lowercase, got {word!r}")
    text = entry.get("help")
    if not isinstance(text, str) or not text.strip():
        raise ControllerSpecError(f"{where}: {word!r} needs a help line for the cheat sheet")
    has_cue, has_stage = "cue" in entry, "stage" in entry
    if has_cue == has_stage:
        raise ControllerSpecError(f"{where}: {word!r} must ask for exactly one cue or stage")
    if has_cue:
        return Command(word=word, help=text, cue=_member(where, entry["cue"], CueKind))
    return Command(word=word, help=text, stage=_member(where, entry["stage"], StageAction))


def _member[E: (CueKind, StageAction)](where: str, value: object, enum: type[E]) -> E:
    try:
        return enum(str(value))
    except ValueError as exc:
        known = ", ".join(member.value for member in enum)
        raise ControllerSpecError(f"{where}: unknown {value!r}. Known: {known}") from exc
