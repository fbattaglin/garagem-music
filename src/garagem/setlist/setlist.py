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

**Curation marks takes in place.** `scripts/curate_setlist.py` reads the keeps and vetoes a
performance logged and sets each take's status; the last word on a take wins. A vetoed take no
longer plays, and `bake_setlist.py --rebake-vetoed` asks for its briefing again, retiring the
old take rather than deleting it.

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
from garagem.dsl import brief, parse_text, realise, sec_line
from garagem.dsl.lines import SEC
from garagem.engines import (
    Ending,
    SongBrief,
    arrange,
    completed,
    density_offset,
    endings_for,
    shifted,
    tension_offset,
    with_climax,
)
from garagem.engines.arranger import MACRO_DYN_RANGE, MACRO_TENSION_RANGE
from garagem.theory import repair

FROZEN = ConfigDict(frozen=True, extra="forbid")
FORMAT: Final = 1
DIGEST_CHARS: Final = 16
# Knob positions sampled to find every offset the knobs can reach. Far finer than a MiniLab's
# 128 steps, and the offsets are steps, so nothing between two samples is missed.
KNOB_STEPS: Final = 1000


class SetlistError(ValueError):
    """A spec or a bake that cannot be used. The message names the file and the value."""


# ------------------------------------------------------------------------------ the spec


class Verdict(StrEnum):
    """What the person who runs the band said of a whole song (ADR-030).

    A song's, where keep and veto are a section's. Nothing is `NONE` by being bad: it is what
    every song is until somebody has listened to it.
    """

    NONE = ""
    APPROVED = "approved"
    REJECTED = "rejected"


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
    # Its own tempo (ADR-028). Left out, the song is at the Set's.
    bpm: float | None = Field(default=None, gt=0.0)
    # What kind of song (ADR-030): a style in `styles/`, or words of the person's own. It is
    # the songwriter's to read; the players do not change with it yet.
    style: str = ""
    # Anything else the songwriter should know, in the person's words.
    notes: str = ""
    verdict: Verdict = Verdict.NONE
    # Out of the concert and still in the file: a song set aside, not thrown away.
    parked: bool = False


class SetlistSpec(BaseModel):
    """A concert as a person asks for it: the songs, in the order they are played."""

    model_config = FROZEN

    name: str = Field(min_length=1)
    songs: tuple[SongSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _titles_are_names(self) -> Self:
        """A title is how a song's spec finds its bake, so two songs cannot share one."""
        titles = [song.title for song in self.songs]
        twice = sorted({title for title in titles if titles.count(title) > 1})
        if twice:
            raise ValueError(f"two songs are called {twice[0]!r}; a title names one song")
        return self


def load_spec(path: Path) -> SetlistSpec:
    """Read `setlists/<name>.toml`. `[[song]]` tables, played in the order written."""
    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
        return SetlistSpec.model_validate(
            {"name": raw.get("name", path.stem), "songs": raw.get("song", [])}
        )
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise SetlistError(f"{path}: {exc}") from exc


def _toml(value: object) -> str:
    """One value as TOML. Only what a `SongSpec` holds: text, numbers and a switch."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def render_spec(spec: SetlistSpec, header: str = "") -> str:
    """The spec as the file `load_spec` reads back to the same spec.

    Written by hand rather than by a library: the format is a name and flat tables, and the
    project adds no dependency for that. A field at its default is left out, so a song reads
    as what was asked of it. **Comments inside the file are not kept**; `header` is, because
    a file's opening comment says what the concert is.
    """
    blank = SongSpec(title="-", key=0, seconds=1.0, seed=0)
    lines = [header.rstrip(), ""] if header.strip() else []
    lines.append(f"name = {_toml(spec.name)}")
    for song in spec.songs:
        lines += ["", "[[song]]"]
        for field in SongSpec.model_fields:
            value = getattr(song, field)
            required = field in ("title", "key", "scale", "feel", "seconds", "seed")
            if required or value != getattr(blank, field):
                lines.append(f"{field} = {_toml(value)}")
    return "\n".join(lines) + "\n"


def header_of(text: str) -> str:
    """A spec file's opening comment: every line before the first that is not one."""
    kept: list[str] = []
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def save_spec(spec: SetlistSpec, path: Path) -> None:
    """Write the concert back, keeping the file's opening comment and nothing else of it."""
    header = header_of(path.read_text(encoding="utf-8")) if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_spec(spec, header), encoding="utf-8")


def arranged(song: SongSpec, bpm: float) -> tuple[tuple[Section, ...], tuple[Ending, ...]]:
    """The song's form and endings, as `jam.py` arranges one: at its own tempo, or at `bpm`."""
    brief_ = SongBrief(
        key=song.key,
        scale=song.scale,
        bpm=bpm if song.bpm is None else song.bpm,
        feel=song.feel,
        minimum_seconds=song.seconds,
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
    # The song's material, in the bake's notation: a riff and a hook the sections were
    # written with in hand (ADR-026). Optional, so `FORMAT` stays 1 and every bake made
    # before the songwriter existed still loads. Empty means nobody asked for one.
    theme: str = ""
    # What the songwriter was told when it wrote this (ADR-030). Stored so a spec that has
    # since changed its mind can be told from one that has not (`composed_as`).
    style: str = ""
    notes: str = ""
    takes: tuple[Take, ...] = ()
    missed: tuple[Missed, ...] = ()
    # Vetoed takes that a new bake replaced. Kept, because a veto is a preference and the
    # material it fell on is half of the evidence (ADR-000 §10.4).
    retired: tuple[Take, ...] = ()

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

    @property
    def bpm(self) -> float:
        """The tempo the song was baked at. One per song: the form never changes it."""
        return self.form[0].bpm

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


# ------------------------------------------------------------- the concert and its bake


def composed_as(asked: SongSpec, song: Song, set_bpm: float) -> bool:
    """Whether `song` is what `asked` would have the songwriter write today.

    A verdict, an order or being parked change nothing about the music, so they are not
    compared. Everything the arranger or the songwriter reads is.
    """
    return (
        asked.title == song.title
        and asked.key == song.key
        and asked.scale == song.scale
        and asked.feel == song.feel
        and asked.seconds == song.seconds
        and asked.seed == song.seed
        and (set_bpm if asked.bpm is None else asked.bpm) == song.bpm
        and asked.style == song.style
        and asked.notes == song.notes
    )


def spec_beside(bake: Path) -> Path:
    """The concert a bake belongs to: `show.json` and `show.fake.json` are both `show.toml`'s."""
    name = bake.name
    stem = name[: -len(".fake.json")] if name.endswith(".fake.json") else bake.stem
    return bake.with_name(f"{stem}.toml")


def lineup(setlist: Setlist, concert: SetlistSpec | None) -> tuple[Song, ...]:
    """The songs a show plays, in the order it plays them (ADR-030).

    **The concert decides, once somebody has judged it.** The songs are the concert's, in its
    order, each one approved, not parked, and composed. A concert nobody has judged yet (no
    verdict on any song, which is every spec written before the studio) plays every song it
    has composed and not parked, so an old setlist plays as it always did. With no concert at
    all the bake plays as it was written.
    """
    if concert is None:
        return setlist.songs
    baked = {song.title: song for song in setlist.songs}
    judged = any(song.verdict is not Verdict.NONE for song in concert.songs)
    return tuple(
        baked[asked.title]
        for asked in concert.songs
        if asked.title in baked
        and not asked.parked
        and (asked.verdict is Verdict.APPROVED or not judged)
    )


# --------------------------------------------------------------------------- at playback


def _offsets() -> tuple[tuple[int, float], ...]:
    """Every (dyn, tension) offset the two knobs can put the plan at, read off the knobs' own
    mapping (`engines.density_offset`, `engines.tension_offset`) rather than restated."""
    positions = [step / KNOB_STEPS for step in range(KNOB_STEPS + 1)]
    return tuple(
        sorted(
            {(density_offset(d), tension_offset(t)) for d in positions for t in positions},
            key=lambda offset: (_travel(offset), offset),
        )
    )


def _travel(offset: tuple[int, float]) -> float:
    """How far the knobs are from the middle, as a fraction of their travel."""
    dyn, tension = offset
    return abs(dyn) / MACRO_DYN_RANGE + abs(tension) / MACRO_TENSION_RANGE


def reachable(song: Song) -> dict[Section, Take]:
    """Every briefing the knobs can move a playable take to, and the take that answers it.

    **A knob moves the briefing, and the take keeps playing** (Fabiano, 2026-09-13). The model
    wrote the groove for the plan; a knob asks for more or less density and tension, which the
    system composes over any groove (`dsl/realise.py`). So a moved briefing is answered by the
    take it was moved from, and realised under the moved briefing. Without this, the first knob
    step sent the rest of a baked song to the floor (`phase-5-findings.md` §4).

    Where two takes can reach one briefing, the take that needs the knobs moved least answers
    it, so an exact briefing always gets its own take. Ties go to the order the song asks.
    """
    best: dict[Section, tuple[float, int, Take]] = {}
    for order, take in enumerate(song.playable()):
        for offset in OFFSETS:
            moved = shifted(take.briefing, *offset)
            rank = (_travel(offset), order)
            if moved not in best or rank < best[moved][:2]:
                best[moved] = (*rank, take)
    return {section: take for section, (_, _, take) in best.items()}


def answers(song: Song) -> dict[str, str]:
    """Briefing text, as today's prompt words it, to the DSL baked for it, knobs included."""
    return {brief(section): served(take, section) for section, take in reachable(song).items()}


def served(take: Take, section: Section) -> str:
    """The take as it answers `section`: the model's text, echoing the briefing it now answers.

    Under a knob-moved briefing the take's own `SEC` echo disagrees on `dyn` or `tension`, and
    the parser would log a `section_mismatch` for behaviour that is working as designed: 33 of
    them in one conducted run of songs 2 and 3. The echo is the briefing's, not the model's
    material, so it is rendered for the briefing answered. Curation joins on `body`, which
    leaves the echo out, so a mark still finds its take.
    """
    if section == take.briefing:
        return take.dsl
    return "\n".join(sec_line(section) if _is_sec(line) else line for line in take.dsl.splitlines())


def body(dsl: str) -> str:
    """A take's DSL without its `SEC` echo: what the model wrote, whichever briefing it answers."""
    return "\n".join(line for line in dsl.splitlines() if not _is_sec(line))


def _is_sec(line: str) -> bool:
    return line.split(maxsplit=1)[:1] == [SEC]


def briefings(song: Song) -> frozenset[Section]:
    """The briefings a performance of this song may ask for: its takes, and where knobs move
    them."""
    return frozenset(reachable(song))


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


OFFSETS: Final = _offsets()
