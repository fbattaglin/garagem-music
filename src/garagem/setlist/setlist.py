"""A setlist: songs written once online, played later from disk (ADR-000 §7, ADR-024).

Two files per setlist, both in `setlists/`:

- **`<name>.toml`, the spec,** written by a person: which songs, in which order, with the key,
  scale, feel, length and seed of each. Nothing in it can be paid for twice by accident.
- **`<name>.json`, the bake,** written by `scripts/bake_setlist.py`: each song's form and
  endings as arranged, and a take for every section the model delivered. Curation (Stage 3)
  marks takes kept or vetoed in the same file.

**A take is the model's DSL and a seed, not notes.** The notes are made again at playback by
the same parse, realise, completion and repair the producer uses, so a composition fix such as
straightening reaches every take already baked. Each take keeps a digest of the notes it made
at bake time, and `drifted` says which takes now play differently.

**The song's form is stored, not re-arranged.** A setlist plays the song that was baked, even
after the arranger changes. Its briefings are what the bake holds, and the producer asks for
nothing else (`agents.routing.only`).

**One take per briefing, not per section.** A second verse briefed exactly like the first plays
the first verse's take, with its own seed, so the groove repeats and the humanisation does not:
what a band does with a verse. It is ADR-000's P6, *"sections already generated from the same
briefing are reused rather than regenerated"*, and it is what lets a veto remove a groove
wherever it would have played. `Take.section` is the first section that asked for it.

No `llm`, no `daw`, no `transport`: the format knows the music, not how it is fetched or
played. `tests/unit/test_architecture.py` holds it to that.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from garagem.domain import Feel, Section, SectionScore
from garagem.dsl import brief, parse_text, realise
from garagem.engines import Ending, SongBrief, arrange, completed, endings_for, with_climax
from garagem.theory import repair

FROZEN = ConfigDict(frozen=True, extra="forbid")
FORMAT: Final = 1
DIGEST_CHARS: Final = 16


class SetlistError(ValueError):
    """A spec or a bake that cannot be used. The message names the file and the value."""


# ------------------------------------------------------------------------------ the spec


class SongSpec(BaseModel):
    """One song as a person asks for it."""

    model_config = FROZEN

    title: str = Field(min_length=1)
    # A pitch class: 0 is C, 4 is E, as `jam.py --key` takes it.
    key: int = Field(ge=0, le=11)
    scale: str = "minor"
    feel: Feel = Feel.STRAIGHT8
    seconds: float = Field(gt=0.0)
    seed: int = Field(ge=0)


class SetlistSpec(BaseModel):
    model_config = FROZEN

    name: str = Field(min_length=1)
    songs: tuple[SongSpec, ...] = Field(min_length=1)


def load_spec(path: Path) -> SetlistSpec:
    """Read `setlists/<name>.toml`. `[[song]]` tables, played in the order written."""
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
        return SetlistSpec.model_validate(
            {"name": raw.get("name", path.stem), "songs": raw.get("song", [])}
        )
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise SetlistError(f"{path}: {exc}") from exc


def arranged(song: SongSpec, bpm: float) -> tuple[tuple[Section, ...], tuple[Ending, ...]]:
    """The song's form and endings, exactly as `jam.py` arranges one: climax and all."""
    brief_ = SongBrief(
        key=song.key, scale=song.scale, bpm=bpm, feel=song.feel, minimum_seconds=song.seconds
    )
    form = with_climax(arrange(brief_, song.seed))
    return form, endings_for(form)


def askable(form: Sequence[Section], worth: Callable[[Section], bool]) -> tuple[int, ...]:
    """The first section of each distinct briefing `worth` would ask about, in play order."""
    return tuple(
        index
        for index, section in enumerate(form)
        if worth(section) and list(form).index(section) == index
    )


# ------------------------------------------------------------------------------ the bake


class TakeStatus(StrEnum):
    UNMARKED = "unmarked"
    KEPT = "kept"
    VETOED = "vetoed"


class Take(BaseModel):
    """What the model wrote for one section of a song, and what that cost."""

    model_config = FROZEN

    # The first section of the song with this briefing: the one it was asked for.
    section: int = Field(ge=0)
    briefing: Section
    seed: int
    model: str
    dsl: str = Field(min_length=1)
    # Which parts the model wrote; the floor completed the rest.
    parts: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    digest: str
    status: TakeStatus = TakeStatus.UNMARKED


class Missed(BaseModel):
    """A section the bake asked about and did not get. The floor plays it, as live."""

    model_config = FROZEN

    section: int = Field(ge=0)
    reason: str
    detail: str = ""
    dsl: str = ""


class Song(BaseModel):
    model_config = FROZEN

    title: str
    key: int
    scale: str
    feel: Feel
    seconds: float
    seed: int
    form: tuple[Section, ...] = Field(min_length=1)
    endings: tuple[Ending, ...]
    takes: tuple[Take, ...] = ()
    missed: tuple[Missed, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(self.endings) != len(self.form):
            raise ValueError(
                f"{self.title}: {len(self.endings)} endings for {len(self.form)} sections"
            )
        seen: set[Section] = set()
        for take in self.takes:
            if take.section >= len(self.form) or take.briefing != self.form[take.section]:
                raise ValueError(f"{self.title}: take {take.section} is not this song's briefing")
            if self.form.index(take.briefing) != take.section:
                raise ValueError(f"{self.title}: take {take.section} is not its briefing's first")
            if take.seed != self.seed + take.section:
                raise ValueError(f"{self.title}: take {take.section} has seed {take.seed}")
            if take.briefing in seen:
                raise ValueError(f"{self.title}: two takes for the briefing at {take.section}")
            seen.add(take.briefing)
        return self

    def total_seconds(self) -> float:
        return sum(section.total_seconds() for section in self.form)

    def playable(self) -> tuple[Take, ...]:
        """The takes a performance may use: every one not vetoed."""
        return tuple(take for take in self.takes if take.status is not TakeStatus.VETOED)


class Setlist(BaseModel):
    model_config = FROZEN

    format: int = FORMAT
    name: str
    # `anthropic` for a real bake; `fake` for one made from the floor, for rehearsing.
    provider: str
    model: str
    baked_on: date
    bpm: float
    songs: tuple[Song, ...] = Field(min_length=1)


def load_setlist(path: Path) -> Setlist:
    try:
        setlist = Setlist.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise SetlistError(f"{path}: {exc}") from exc
    if setlist.format != FORMAT:
        raise SetlistError(f"{path}: format {setlist.format}, expected {FORMAT}")
    return setlist


def save_setlist(setlist: Setlist, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(setlist.model_dump_json(indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- at playback


def answers(song: Song) -> dict[str, str]:
    """Briefing text, as today's prompt words it, to the DSL baked for it."""
    return {brief(take.briefing): take.dsl for take in song.playable()}


def briefings(song: Song) -> frozenset[Section]:
    """The briefings a performance of this song may ask for."""
    return frozenset(take.briefing for take in song.playable())


def digest(score: SectionScore) -> str:
    return hashlib.sha256(score.model_dump_json().encode("utf-8")).hexdigest()[:DIGEST_CHARS]


def played(take: Take) -> SectionScore | None:
    """What the producer makes of a take: parsed, realised, completed, repaired.

    `None` when nothing playable is left, which the bake never stores, so it only happens when
    a later change to the parser or the validator refuses a take it once accepted.
    """
    score = realise(parse_text(take.dsl, take.briefing), take.seed)
    if not score.parts:
        return None
    repaired, left = repair(completed(score))
    return None if left else repaired


def drifted(song: Song) -> tuple[int, ...]:
    """Sections whose take no longer plays the notes it played when it was baked."""
    changed: list[int] = []
    for take in song.takes:
        score = played(take)
        if score is None or digest(score) != take.digest:
            changed.append(take.section)
    return tuple(changed)
