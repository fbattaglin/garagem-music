"""A style: what kind of song, said once and read by whoever needs it (ADR-030).

One file per style in `styles/`. Today a style has two readers:

- **the songwriter**, which is told the style's `direction` in words with every question it
  is asked about the song;
- **the studio**, which starts a new song from the style's palette: a feel, a tempo and a
  scale the style would choose.

The players do not read it yet. They play every style with the same hands, which is why a
style's direction describes the writing and promises nothing about the sound.

**A style is described by its traits, never by a song.** `reference` names the bands a
person would think of, so the studio can say what a word means. The direction itself is
written in what the band does, because that is the only thing the notation can carry.

A spec may also name no style, or say one in its own words: `direction_for` passes words it
does not know through as they were written.
"""

from __future__ import annotations

import random
import tomllib
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from garagem.domain import Feel
from garagem.setlist.setlist import SetlistError, SongSpec

FROZEN = ConfigDict(frozen=True, extra="forbid")
# How long a new song is asked to be, until somebody says otherwise.
DEFAULT_SECONDS = 200.0
KEYS = 12


class Style(BaseModel):
    model_config = FROZEN

    name: str = Field(min_length=1)
    # One line, for a person choosing among styles.
    summary: str = Field(min_length=1)
    reference: str = ""
    # What the songwriter is told. Traits of the writing, in the band's own terms.
    direction: str = Field(min_length=1)
    feels: tuple[Feel, ...] = Field(min_length=1)
    scales: tuple[str, ...] = Field(min_length=1)
    # The slowest and the fastest tempo the style would choose.
    bpm: tuple[float, float]

    @model_validator(mode="after")
    def _tempo_is_a_range(self) -> Self:
        low, high = self.bpm
        if not 0 < low <= high:
            raise ValueError(f"{self.name}: bpm must run from a tempo up to a faster one")
        return self


def load_styles(folder: Path) -> dict[str, Style]:
    """Every style in `folder`, by name. A folder that is not there holds none."""
    styles: dict[str, Style] = {}
    for path in sorted(folder.glob("*.toml")):
        try:
            raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
            style = Style.model_validate({"name": path.stem, **raw})
        except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
            raise SetlistError(f"{path}: {exc}") from exc
        styles[style.name] = style
    return styles


def direction_for(song: SongSpec, styles: dict[str, Style]) -> str:
    """What the songwriter is told about this song beyond its key and its form.

    Empty when the spec says nothing, so a song asked for before styles existed is asked for
    in exactly the words it was.
    """
    lines: list[str] = []
    style = styles.get(song.style)
    if style is not None:
        lines.append(f"Style: {' '.join(style.direction.split())}")
    elif song.style.strip():
        lines.append(f"Style: {song.style.strip()}")
    if song.notes.strip():
        lines.append(f"Notes from the bandleader: {song.notes.strip()}")
    return "\n".join(lines)


def sketch(style: Style, title: str, seed: int, notes: str = "") -> SongSpec:
    """A new song in `style`: its key, feel, scale and tempo chosen from the style's palette.

    Chosen by the seed, so the same seed sketches the same song (P7). Every choice is the
    person's to change afterwards; this only saves them from an empty form.
    """
    rng = random.Random(seed)
    low, high = style.bpm
    return SongSpec(
        title=title,
        key=rng.randrange(KEYS),
        scale=rng.choice(style.scales),
        feel=rng.choice(style.feels),
        seconds=DEFAULT_SECONDS,
        seed=seed,
        # An even tempo: nobody counts a band in at 137.
        bpm=float(2 * round(rng.uniform(low, high) / 2)),
        style=style.name,
        notes=notes,
    )
